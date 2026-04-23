import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, Depends
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.auth import get_current_user
from app.db.mongo import get_db
from app.models.schemas import JDUploadResponse, RankingResponse, ResumeUploadItem, ResumeUploadResponse
from app.services.groq_ranker import GroqRanker
from app.services.parser import extract_text, parse_jd, parse_resume
from app.services.scoring import rank_candidates
from app.services.user_service import UserService
from app.services.gmail_client import GmailClient
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _safe_filename(filename: str) -> str:
    return "".join(char for char in filename if char.isalnum() or char in {"-", "_", "."})


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


# ============================================================================
# JOB MANAGEMENT
# ============================================================================


@router.post("/jobs", response_model=JDUploadResponse)
async def create_job(file: UploadFile | None = File(default=None), text: str = Form(default="")):
    """Create a new job with JD."""
    db = get_db()
    jd_text = text.strip()

    if file is not None:
        extension = Path(file.filename or "").suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail="JD file type not supported")

        jd_id = str(uuid4())
        safe_name = _safe_filename(file.filename or f"{jd_id}{extension}")
        storage_path = settings.jd_storage_dir / f"{jd_id}_{safe_name}"

        contents = await file.read()
        storage_path.write_bytes(contents)
        jd_text = extract_text(storage_path)

    if not jd_text:
        raise HTTPException(status_code=400, detail="Provide JD text or upload a valid JD file")

    parsed = parse_jd(jd_text)
    job_id = str(uuid4())
    now = datetime.now(timezone.utc)

    await db.jobs.insert_one(
        {
            "job_id": job_id,
            "title": parsed["title"],
            "text": parsed["text"],
            "required_skills": parsed["required_skills"],
            "min_experience_years": parsed["min_experience_years"],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
    )

    return JDUploadResponse(
        job_id=job_id,
        title=parsed["title"],
        required_skills=parsed["required_skills"],
        min_experience_years=parsed["min_experience_years"],
    )


@router.post("/upload-jd", response_model=JDUploadResponse)
async def upload_jd(file: UploadFile | None = File(default=None), text: str = Form(default="")):
    """Legacy endpoint - redirects to /jobs"""
    return await create_job(file, text)


@router.get("/jobs")
async def list_jobs():
    """List all active jobs."""
    db = get_db()
    jobs = await db.jobs.find({"status": "active"}).sort("created_at", -1).to_list(length=50)
    for job in jobs:
        job.pop("_id", None)
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job details."""
    db = get_db()
    job = await db.jobs.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.pop("_id", None)
    return job


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and all its resumes/rankings."""
    db = get_db()
    job = await db.jobs.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Delete from DB
    await db.jobs.delete_one({"job_id": job_id})
    await db.resumes.delete_many({"job_id": job_id})
    await db.rankings.delete_many({"job_id": job_id})
    
    return {"message": "Job deleted successfully"}


# ============================================================================
# RESUME INGESTION & UPLOAD
# ============================================================================


@router.post("/resumes/upload", response_model=ResumeUploadResponse)
async def upload_resumes_new(
    job_id: str = Form(...),
    source: Literal["manual", "gmail"] = Form(default="manual"),
    files: list[UploadFile] = File(...),
):
    """Upload resumes for a job."""
    db = get_db()
    created = []
    skipped_count = 0
    now = datetime.now(timezone.utc)

    for file in files:
        extension = Path(file.filename or "").suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            continue

        resume_id = str(uuid4())
        safe_name = _safe_filename(file.filename or f"{resume_id}{extension}")
        storage_path = settings.resume_storage_dir / f"{resume_id}_{safe_name}"

        contents = await file.read()
        storage_path.write_bytes(contents)

        text = extract_text(storage_path)
        parsed = parse_resume(text, fallback_name=safe_name.rsplit(".", maxsplit=1)[0])

        # Multi-layer smart filtering:
        # 1. Faster Heuristics
        if not parsed.get("is_resume", True):
            print(f"Heuristic Filter: Skipping non-resume document: {safe_name}")
            if storage_path.exists(): storage_path.unlink()
            continue
            
        # 2. Advanced AI Classification (Smart Layer)
        ranker = GroqRanker()
        if not await ranker.classify_document(text):
            print(f"AI Filter: Skipping non-resume document: {safe_name}")
            if storage_path.exists(): storage_path.unlink()
            skipped_count += 1
            continue

        # Deduplication check
        if parsed.get("email"):
            existing = await db.resumes.find_one({"job_id": job_id, "email": parsed["email"]})
            if existing:
                print(f"Skipping duplicate resume for {parsed['email']}")
                if storage_path.exists():
                    storage_path.unlink()
                continue

        document = {
            "resume_id": resume_id,
            "job_id": job_id,
            "filename": safe_name,
            "source": source,
            "file_path": str(storage_path),
            "text": parsed["text"],
            "candidate_name": parsed["candidate_name"],
            "email": parsed["email"],
            "phone": parsed["phone"],
            "skills": parsed["skills"],
            "experience_years": parsed["experience_years"],
            "status": "pending_ranking",
            "created_at": now,
            "updated_at": now,
        }
        await db.resumes.insert_one(document)
        created.append(
            ResumeUploadItem(
                resume_id=resume_id,
                filename=safe_name,
                candidate_name=parsed["candidate_name"],
                source=source,
            )
        )

    return ResumeUploadResponse(
        job_id=job_id, 
        uploaded_count=len(created), 
        resumes=created,
        skipped_count=skipped_count
    )


@router.post("/resumes/fetch-gmail", response_model=ResumeUploadResponse)
async def fetch_resumes_gmail(
    job_id: str = Form(...),
    current_user: dict = Depends(get_current_user)
):
    """Fetch resumes from active Gmail account for a job."""
    db = get_db()
    
    # Verify job
    job = await db.jobs.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get active Gmail token
    user_service = UserService(db)
    access_token = await user_service.get_active_gmail_token(current_user["user_id"])
    if not access_token:
        raise HTTPException(
            status_code=400, 
            detail="No active Gmail account connected. Please connect Gmail in profile settings."
        )

    # Fetch from Gmail
    try:
        from googleapiclient.errors import HttpError
        gmail = GmailClient.from_access_token(access_token)
        skipped_count = 0
        
        # Try multiple search strategies
        search_queries = [
            f"has:attachment filename:(pdf OR docx OR txt) {job['title']}",
            f"has:attachment filename:(pdf OR docx OR txt) \"{job['title']}\"",
            f"has:attachment filename:(pdf OR docx OR txt) resume",
            f"has:attachment filename:(pdf OR docx OR txt) cv"
        ]
        
        attachments = []
        for q in search_queries:
            try:
                attachments = gmail.fetch_attachments(query=q)
                if attachments:
                    print(f"Found results with query: {q}")
                    break
            except HttpError as e:
                if e.resp.status == 403:
                    raise HTTPException(
                        status_code=403,
                        detail="Gmail Access Expired or Denied. Please LOG OUT and LOG IN again to renew permissions."
                    )
                raise
            
        if not attachments:
            return ResumeUploadResponse(job_id=job_id, uploaded_count=0, resumes=[])

        created = []
        now = datetime.now(timezone.utc)

        for att in attachments:
            resume_id = str(uuid4())
            safe_name = _safe_filename(att["filename"])
            storage_path = settings.resume_storage_dir / f"{resume_id}_{safe_name}"

            # Ensure bytes
            file_bytes = att["data"]
            storage_path.write_bytes(file_bytes)

            text = extract_text(storage_path)
            parsed = parse_resume(text, fallback_name=safe_name.rsplit(".", maxsplit=1)[0])

            # Multi-layer smart filtering:
            # 1. Faster Heuristics
            if not parsed.get("is_resume", True):
                print(f"Heuristic Filter: Skipping non-resume document: {safe_name}")
                if storage_path.exists(): storage_path.unlink()
                continue
                
            # 2. Advanced AI Classification (Smart Layer)
            ranker = GroqRanker()
            if not await ranker.classify_document(text):
                print(f"AI Filter: Skipping non-resume document: {safe_name}")
                if storage_path.exists(): storage_path.unlink()
                skipped_count += 1
                continue

            # Deduplication check
            if parsed.get("email"):
                existing = await db.resumes.find_one({"job_id": job_id, "email": parsed["email"]})
                if existing:
                    print(f"Skipping duplicate resume for {parsed['email']}")
                    if storage_path.exists():
                        storage_path.unlink()
                    skipped_count += 1
                    continue

            document = {
                "resume_id": resume_id,
                "job_id": job_id,
                "filename": safe_name,
                "source": "gmail",
                "file_path": str(storage_path),
                "text": parsed["text"],
                "candidate_name": parsed["candidate_name"],
                "email": parsed["email"],
                "phone": parsed["phone"],
                "skills": parsed["skills"],
                "experience_years": parsed["experience_years"],
                "status": "pending_ranking",
                "created_at": now,
                "updated_at": now,
                "gmail_subject": att["subject"],
                "gmail_sender": att["sender"],
            }
            await db.resumes.insert_one(document)
            created.append(
                ResumeUploadItem(
                    resume_id=resume_id,
                    filename=safe_name,
                    candidate_name=parsed["candidate_name"],
                    source="gmail",
                )
            )

        return ResumeUploadResponse(
            job_id=job_id, 
            uploaded_count=len(created), 
            resumes=created,
            skipped_count=skipped_count
        )

    except Exception as e:
        logger.error(f"Error fetching from Gmail: {e}")
        raise HTTPException(status_code=500, detail=f"Gmail fetch failed: {str(e)}")


@router.post("/upload-resumes", response_model=ResumeUploadResponse)
async def upload_resumes(
    job_id: str = Form(...),
    source: Literal["manual", "gmail"] = Form(default="manual"),
    files: list[UploadFile] = File(...),
):
    """Legacy endpoint - redirects to /resumes/upload"""
    return await upload_resumes_new(job_id, source, files)


@router.get("/resumes/{job_id}")
async def list_resumes(
    job_id: str,
    source: str = Query(None),
    skip: int = Query(0),
    limit: int = Query(100),
):
    """List resumes for a job with optional filtering."""
    db = get_db()
    query = {"job_id": job_id}
    if source:
        query["source"] = source

    resumes = await db.resumes.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    for resume in resumes:
        resume.pop("_id", None)
        resume.pop("text", None)
    return {"resumes": resumes, "count": len(resumes)}


@router.delete("/resumes/{resume_id}")
async def delete_resume(resume_id: str):
    """Delete an individual resume and its physical file."""
    db = get_db()
    
    resume = await db.resumes.find_one({"resume_id": resume_id})
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
        
    # Delete from DB
    await db.resumes.delete_one({"resume_id": resume_id})
    await db.rankings.delete_many({"resume_id": resume_id})
    
    # Delete physical file
    file_path_str = resume.get("file_path")
    if file_path_str:
        file_path = Path(file_path_str)
        if file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.error(f"Error deleting file {file_path}: {e}")
        
    return {"message": "Resume deleted successfully"}


# ============================================================================
# LLM RANKING
# ============================================================================


@router.post("/judge-batch/{job_id}", response_model=RankingResponse)
async def judge_batch(job_id: str):
    """Run LLM batch ranking for a job."""
    db = get_db()
    job = await db.jobs.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    resumes = await db.resumes.find({"job_id": job_id}).to_list(length=500)
    if not resumes:
        raise HTTPException(status_code=400, detail="No resumes found for this job")

    # Try Groq LLM ranking first if enabled
    ranked = []
    if settings.use_llm_scoring and settings.groq_api_key:
        ranker = GroqRanker()
        groq_rankings = await ranker.rank_candidates(job["text"], resumes)
        if groq_rankings:
            # Enforce score-based confidence rules
            for r in groq_rankings:
                score = r.get("score", 0)
                if score >= 70:
                    r["confidence"] = "HIGH"
                elif score >= 40:
                    r["confidence"] = "MEDIUM"
                else:
                    r["confidence"] = "LOW"
            # Sort by score descending
            groq_rankings.sort(key=lambda x: x.get("score", 0), reverse=True)
            ranked = groq_rankings
    
    # Fallback to local scoring if LLM ranking fails or is disabled
    if not ranked:
        ranked = rank_candidates(job, resumes)

    now = datetime.now(timezone.utc)
    await db.rankings.delete_many({"job_id": job_id})
    
    if ranked:
        ranking_docs = []
        for i, item in enumerate(ranked, start=1):
            ranking_docs.append(
                {
                    "ranking_id": str(uuid4()),
                    "job_id": job_id,
                    "resume_id": item.get("resume_id"),
                    "rank": i,
                    "score": item.get("score", item.get("final_score", 0)),
                    "confidence": item.get("confidence", "MEDIUM"),
                    "reasoning": item.get("reasoning", ""),
                    "strengths": item.get("strengths", []),
                    "weaknesses": item.get("weaknesses", item.get("missing_required_skills", [])),
                    "created_at": now,
                }
            )
        await db.rankings.insert_many(ranking_docs)

    return RankingResponse(
        job_id=job_id,
        total_candidates=len(ranked),
        generated_at=now,
        candidates=[],
    )


# ============================================================================
# DASHBOARD & FILTERING
# ============================================================================


@router.get("/dashboard/{job_id}", response_model=RankingResponse)
async def dashboard(
    job_id: str,
    confidence: str = Query(None),
    source: str = Query(None),
    search: str = Query(None),
):
    """Get ranked dashboard with optional filters."""
    db = get_db()
    
    # Get job
    job = await db.jobs.find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get rankings
    ranking_query = {"job_id": job_id}
    rankings = await db.rankings.find(ranking_query).sort("rank", 1).to_list(length=500)
    if not rankings:
        return RankingResponse(
            job_id=job_id,
            total_candidates=0,
            generated_at=datetime.now(timezone.utc),
            candidates=[],
        )

    # Get candidate details
    candidates = []
    for ranking in rankings:
        resume = await db.resumes.find_one({"resume_id": ranking.get("resume_id")})
        if not resume:
            continue

        # Apply filters
        if confidence and ranking.get("confidence") != confidence:
            continue
        if source and resume.get("source") != source:
            continue
        if search and search.lower() not in resume.get("candidate_name", "").lower():
            continue

        candidate = {
            "rank": ranking.get("rank"),
            "resume_id": ranking.get("resume_id"),
            "name": resume.get("candidate_name", "Unknown"),
            "email": resume.get("email", ""),
            "source": resume.get("source", "manual"),
            "score": ranking.get("score", 0),
            "confidence": ranking.get("confidence", "MEDIUM"),
            "reasoning": ranking.get("reasoning", ""),
            "strengths": ranking.get("strengths", []),
            "weaknesses": ranking.get("weaknesses", []),
            "resume_url": f"/resume/{ranking.get('resume_id')}",
        }
        candidates.append(candidate)

    latest = max(
        (r.get("created_at", datetime.now(timezone.utc)) for r in rankings),
        default=datetime.now(timezone.utc),
    )

    return RankingResponse(
        job_id=job_id,
        total_candidates=len(candidates),
        generated_at=latest,
        candidates=candidates,
    )


@router.get("/candidates/search")
async def search_candidates(job_id: str, query: str = Query(...)):
    """Search candidates by name or email."""
    db = get_db()
    resumes = await db.resumes.find(
        {
            "job_id": job_id,
            "$or": [
                {"candidate_name": {"$regex": query, "$options": "i"}},
                {"email": {"$regex": query, "$options": "i"}},
            ],
        }
    ).to_list(length=100)

    for resume in resumes:
        resume.pop("_id", None)
        resume.pop("text", None)
    return {"results": resumes}


# ============================================================================
# RESUME VIEWER
# ============================================================================


@router.get("/resume/{resume_id}")
async def get_resume_file(resume_id: str):
    """Open exact original resume file by ID."""
    db = get_db()
    resume = await db.resumes.find_one({"resume_id": resume_id})
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    file_path = Path(resume["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file is missing")

    media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
    return FileResponse(path=file_path, media_type=media_type, filename=resume.get("filename", os.path.basename(file_path)))


@router.get("/candidate/{resume_id}")
async def get_candidate_detail(resume_id: str):
    """Get full candidate detail including ranking."""
    db = get_db()
    resume = await db.resumes.find_one({"resume_id": resume_id})
    if not resume:
        raise HTTPException(status_code=404, detail="Candidate not found")

    ranking = await db.rankings.find_one({"resume_id": resume_id})

    result = {
        "resume_id": resume_id,
        "name": resume.get("candidate_name", "Unknown"),
        "email": resume.get("email", ""),
        "phone": resume.get("phone", ""),
        "source": resume.get("source", "manual"),
        "skills": resume.get("skills", []),
        "experience_years": resume.get("experience_years", 0),
        "score": ranking.get("score", 0) if ranking else 0,
        "confidence": ranking.get("confidence", "MEDIUM") if ranking else "MEDIUM",
        "reasoning": ranking.get("reasoning", "") if ranking else "",
        "strengths": ranking.get("strengths", []) if ranking else [],
        "weaknesses": ranking.get("weaknesses", []) if ranking else [],
        "resume_url": f"/resume/{resume_id}",
    }
    return result
