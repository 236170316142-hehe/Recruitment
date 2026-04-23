from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class JDUploadResponse(BaseModel):
    job_id: str
    title: str
    required_skills: list[str]
    min_experience_years: int


class ResumeUploadItem(BaseModel):
    resume_id: str
    filename: str
    candidate_name: str
    source: Literal["manual", "gmail"]


class ResumeUploadResponse(BaseModel):
    job_id: str
    uploaded_count: int
    resumes: list[ResumeUploadItem]
    skipped_count: int = 0


class RankedCandidate(BaseModel):
    rank: int
    resume_id: str
    name: str
    email: str
    source: str
    score: float = Field(ge=0, le=100)
    confidence: str
    reasoning: str
    strengths: list[str] = []
    weaknesses: list[str] = []
    resume_url: str


class RankingResponse(BaseModel):
    job_id: str
    total_candidates: int
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    candidates: list[RankedCandidate]
