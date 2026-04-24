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
async def create_job(
    file: UploadFile | None = File(default=None), 
    text: str = Form(default=""),
    current_user: dict = Depends(get_current_user)
):
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
            "user_id": current_user["user_id"],
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
async def list_jobs(current_user: dict = Depends(get_current_user)):
    """List all active jobs for the current user."""
    db = get_db()
    jobs = await db.jobs.find({
        "status": "active",
        "user_id": current_user["user_id"]
    }).sort("created_at", -1).to_list(length=50)
    for job in jobs:
        job.pop("_id", None)
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Get job details for the current user."""
    db = get_db()
    job = await db.jobs.find_one({
        "job_id": job_id,
        "user_id": current_user["user_id"]
    })
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.pop("_id", None)
    return job


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a job and all its resumes/rankings if owned by the user."""
    db = get_db()
    job = await db.jobs.find_one({
        "job_id": job_id,
        "user_id": current_user["user_id"]
    })
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
    current_user: dict = Depends(get_current_user)
):
    """Upload resumes for a job owned by the current user."""
    db = get_db()
    
    # Verify job ownership
    job = await db.jobs.find_one({"job_id": job_id, "user_id": current_user["user_id"]})
    if not job:
        raise HTTPException(status_code=403, detail="Not authorized to upload to this job")
    
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
            print(f"DEBUG: Heuristic Filter Skipped: {safe_name} - Not a resume")
            if storage_path.exists(): storage_path.unlink()
            skipped_count += 1
            continue
            
        # 2. Advanced AI Classification (Smart Layer)
        ranker = GroqRanker()
        try:
            if not await ranker.classify_document(text):
                print(f"DEBUG: AI Filter Skipped: {safe_name} - AI classified as non-resume")
                if storage_path.exists(): storage_path.unlink()
                skipped_count += 1
                continue
        except Exception as e:
            print(f"DEBUG: AI classification error for {safe_name}: {e}. Proceeding anyway.")
            pass

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
            "user_id": current_user["user_id"],
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
    
    # Verify job ownership
    job = await db.jobs.find_one({"job_id": job_id, "user_id": current_user["user_id"]})
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

            # 1. Faster Heuristics
            if not parsed.get("is_resume", True):
                print(f"DEBUG: Heuristic Filter Skipped (Gmail): {safe_name} - Not a resume")
                if storage_path.exists(): storage_path.unlink()
                skipped_count += 1
                continue
                
            # 2. Advanced AI Classification (Smart Layer)
            ranker = GroqRanker()
            try:
                if not await ranker.classify_document(text):
                    print(f"DEBUG: AI Filter Skipped (Gmail): {safe_name} - AI classified as non-resume")
                    if storage_path.exists(): storage_path.unlink()
                    skipped_count += 1
                    continue
            except Exception as e:
                print(f"DEBUG: AI classification error (Gmail) for {safe_name}: {e}. Proceeding anyway.")
                pass

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
                "user_id": current_user["user_id"],
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
    current_user: dict = Depends(get_current_user)
):
    """List resumes for a job owned by the current user."""
    db = get_db()
    # Verify job ownership
    job = await db.jobs.find_one({"job_id": job_id, "user_id": current_user["user_id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    query = {
        "job_id": job_id,
        "$or": [
            {"user_id": current_user["user_id"]},
            {"user_id": {"$exists": False}},
            {"user_id": None}
        ]
    }
    if source:
        query["source"] = source

    resumes = await db.resumes.find(query).sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    for resume in resumes:
        resume.pop("_id", None)
        resume.pop("text", None)
    return {"resumes": resumes, "count": len(resumes)}


@router.delete("/resumes/{resume_id}")
async def delete_resume(resume_id: str, current_user: dict = Depends(get_current_user)):
    """Delete an individual resume owned by the user."""
    db = get_db()
    
    resume = await db.resumes.find_one({
        "resume_id": resume_id,
        "user_id": current_user["user_id"]
    })
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
async def judge_batch(
    job_id: str, 
    threshold: int = Query(70),
    current_user: dict = Depends(get_current_user)
):
    """Run LLM batch ranking for a job owned by the user."""
    db = get_db()
    job = await db.jobs.find_one({"job_id": job_id, "user_id": current_user["user_id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get resumes for this job
    # Resiliency: Include resumes with matching job_id even if user_id is missing (legacy claim)
    resumes = await db.resumes.find({
        "job_id": job_id, 
        "$or": [
            {"user_id": current_user["user_id"]},
            {"user_id": {"$exists": False}},
            {"user_id": None}
        ]
    }).to_list(length=1000)
    
    if not resumes:
        raise HTTPException(
            status_code=400, 
            detail=f"No resumes found for Job '{job.get('title', job_id)}'. Please upload resumes first."
        )

    # Re-extract skills from stored text using the current (expanded) SKILL_LEXICON
    # This fixes the problem where jobs/resumes stored with the old lexicon have stale skill lists
    from app.services.parser import extract_skills
    
    # Re-extract JD skills
    jd_text = job.get("text", "")
    if jd_text:
        fresh_jd_skills = extract_skills(jd_text)
        if len(fresh_jd_skills) > len(job.get("required_skills", [])):
            job["required_skills"] = fresh_jd_skills
            await db.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"required_skills": fresh_jd_skills}}
            )
    
    # Re-extract resume skills
    for resume in resumes:
        resume_text = resume.get("text", "")
        if resume_text:
            fresh_skills = extract_skills(resume_text)
            if len(fresh_skills) > len(resume.get("skills", [])):
                resume["skills"] = fresh_skills
                # Update DB in background (non-blocking)
                await db.resumes.update_one(
                    {"resume_id": resume["resume_id"]},
                    {"$set": {"skills": fresh_skills}}
                )
    
    logger.info(f"Matching {len(resumes)} resumes against job '{job.get('title')}' (required skills: {job.get('required_skills')})")
    for r in resumes:
        logger.info(f"  Resume '{r.get('candidate_name')}': skills={r.get('skills')}, exp={r.get('experience_years')}yrs, text_len={len(r.get('text',''))}")

    # Try Groq LLM ranking first if enabled
    ranked = []
    if settings.use_llm_scoring and settings.groq_api_key:
        ranker = GroqRanker()
        try:
            groq_rankings = await ranker.rank_candidates(job["text"], resumes)
            if groq_rankings:
                # Check if AI actually worked (not all zeros)
                valid_count = sum(1 for r in groq_rankings if r.get("score", 0) > 0)
                logger.info(f"Groq returned {len(groq_rankings)} results, {valid_count} with scores > 0")
                if valid_count > 0:
                    # Enforce score-based confidence rules
                    for r in groq_rankings:
                        score = r.get("score", 0)
                        if score >= threshold:
                            r["confidence"] = "HIGH"
                        elif score >= threshold // 2:
                            r["confidence"] = "MEDIUM"
                        else:
                            r["confidence"] = "LOW"
                    groq_rankings.sort(key=lambda x: x.get("score", 0), reverse=True)
                    ranked = groq_rankings
        except Exception as e:
            logger.error(f"Groq ranking failed entirely: {e}")
    
    # Always run local scoring as backup data source
    local_results = rank_candidates(job, resumes)
    local_ranked = {r["resume_id"]: r for r in local_results}
    
    if not ranked:
        logger.info("Using LOCAL scoring (AI unavailable or returned all zeros)")
        # Use local scoring but enrich with strengths/weaknesses
        for r in local_results:
            strengths = []
            if r.get("skills_match_score", 0) > 0: strengths.append(f"Skill Match ({int(r['skills_match_score'])}%)")
            if r.get("jd_relevance_score", 0) > 30: strengths.append(f"JD Relevance ({int(r['jd_relevance_score'])}%)")
            if r.get("experience_match_score", 0) > 50: strengths.append(f"Experience Fit ({int(r['experience_match_score'])}%)")
            if not strengths: strengths.append("Candidate Identified")
            r["strengths"] = strengths
            r["weaknesses"] = r.get("missing_required_skills", [])
            r["score"] = r.get("final_score", 0)
        ranked = local_results
    else:
        # Groq worked - but fill in any zero-score candidates from local
        for r in ranked:
            if r.get("score", 0) == 0:
                local_data = local_ranked.get(r["resume_id"], {})
                r["score"] = local_data.get("final_score", 0)
                r["confidence"] = local_data.get("confidence", "LOW")
                r["reasoning"] = f"(Local Fallback) {local_data.get('reasoning', '')}"
                strengths = []
                if local_data.get("skills_match_score", 0) > 0: strengths.append(f"Skill Match ({int(local_data['skills_match_score'])}%)")
                if local_data.get("jd_relevance_score", 0) > 30: strengths.append(f"JD Relevance ({int(local_data['jd_relevance_score'])}%)")
                if local_data.get("experience_match_score", 0) > 50: strengths.append(f"Experience Fit ({int(local_data['experience_match_score'])}%)")
                r["strengths"] = strengths if strengths else ["Candidate Identified"]
                r["weaknesses"] = local_data.get("missing_required_skills", [])

    now = datetime.now(timezone.utc)
    await db.rankings.delete_many({"job_id": job_id})
    
    if ranked:
        # Re-sort after potential fallback updates
        ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        ranking_docs = []
        for i, item in enumerate(ranked, start=1):
            # Ensure strengths/weaknesses are present and never empty if score > 0
            s = item.get("strengths")
            w = item.get("weaknesses")
            
            if not s or len(s) == 0:
                # Guaranteed fallback strengths
                s = []
                if item.get("score", 0) > 40: s.append("Partial Skill Match")
                if item.get("score", 0) > 20: s.append("JD Relevance")
                if not s: s.append("Candidate Identified")
                
            if not w or len(w) == 0:
                # Guaranteed fallback weaknesses from missing skills
                w = item.get("missing_required_skills", [])
                if not w: w.append("General evaluation")

            ranking_docs.append(
                {
                    "ranking_id": str(uuid4()),
                    "job_id": job_id,
                    "resume_id": item.get("resume_id"),
                    "rank": i,
                    "score": item.get("score", item.get("final_score", 0)),
                    "confidence": item.get("confidence", "MEDIUM"),
                    "reasoning": item.get("reasoning", ""),
                    "strengths": s,
                    "weaknesses": w,
                    "created_at": now,
                }
            )
        await db.rankings.insert_many(ranking_docs)

    # Update job with latest ranking info
    await db.jobs.update_one(
        {"job_id": job_id},
        {"$set": {
            "last_ranked_at": now,
            "last_threshold": threshold
        }}
    )

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
    current_user: dict = Depends(get_current_user)
):
    """Get ranked dashboard for a job owned by the user."""
    db = get_db()
    
    # Get job
    job = await db.jobs.find_one({
        "job_id": job_id,
        "user_id": current_user["user_id"]
    })
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get rankings
    ranking_query = {"job_id": job_id}
    # Optional: We could add user_id to rankings too, but since job_id is user-specific, it's safe.
    # But let's check job ownership already (done above).
    
    rankings = await db.rankings.find(ranking_query).sort("rank", 1).to_list(length=500)
    if not rankings:
        return RankingResponse(
            job_id=job_id,
            total_candidates=0,
            threshold=job.get("last_threshold", 70),
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
            "filename": resume.get("filename", ""),
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
        threshold=job.get("last_threshold", 70),
        generated_at=latest,
        candidates=candidates,
    )


@router.get("/candidates/search")
async def search_candidates(
    job_id: str, 
    query: str = Query(...),
    current_user: dict = Depends(get_current_user)
):
    """Search candidates by name or email owned by the user."""
    db = get_db()
    resumes = await db.resumes.find(
        {
            "job_id": job_id,
            "$or": [
                {
                    "user_id": current_user["user_id"],
                    "$or": [
                        {"candidate_name": {"$regex": query, "$options": "i"}},
                        {"email": {"$regex": query, "$options": "i"}},
                    ]
                },
                {
                    "user_id": {"$exists": False},
                    "$or": [
                        {"candidate_name": {"$regex": query, "$options": "i"}},
                        {"email": {"$regex": query, "$options": "i"}},
                    ]
                }
            ]
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
async def get_resume_file(resume_id: str, current_user: dict = Depends(get_current_user)):
    """Open exact original resume file by ID owned by the user."""
    db = get_db()
    resume = await db.resumes.find_one({
        "resume_id": resume_id,
        "user_id": current_user["user_id"]
    })
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    file_path = Path(resume["file_path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file is missing")

    media_type = "application/pdf" if file_path.suffix.lower() == ".pdf" else "application/octet-stream"
    # Use content_disposition_type="inline" to view in browser instead of downloading
    return FileResponse(path=file_path, media_type=media_type, content_disposition_type="inline")


@router.get("/candidate/{resume_id}")
async def get_candidate_detail(resume_id: str, current_user: dict = Depends(get_current_user)):
    """Get full candidate detail owned by the user."""
    db = get_db()
    resume = await db.resumes.find_one({
        "resume_id": resume_id,
        "user_id": current_user["user_id"]
    })
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
        "filename": resume.get("filename", ""),
        "resume_url": f"/resume/{resume_id}",
    }
    return result
