import re
from pathlib import Path
from typing import Dict, Any, List, Optional

import docx
import fitz

SKILL_LEXICON = {
    "python", "java", "javascript", "typescript", "react", "node.js", "node",
    "fastapi", "django", "flask", "mongodb", "sql", "postgresql", "aws",
    "docker", "kubernetes", "git", "machine learning", "nlp", "data analysis", "excel",
}


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        with fitz.open(file_path) as doc:
            return "\n".join(page.get_text("text") for page in doc).strip()

    if suffix == ".docx":
        doc = docx.Document(file_path)
        return "\n".join(paragraph.text for paragraph in doc.paragraphs).strip()

    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8", errors="ignore")

    return ""


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_email(text: str) -> str:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def extract_phone(text: str) -> str:
    match = re.search(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3}\)?[\s-]?)?\d{3}[\s-]?\d{4}", text)
    return match.group(0) if match else ""


def extract_name(text: str, fallback: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    
    bad_name_keywords = {
        "skillsbuild", "program", "workshop", "winter", "summer", 
        "overview", "certification", "university", "recruitment", 
        "hub", "corporate", "limited", "ltd", "inc", "invitation", "pamphlet"
    }
    
    if lines:
        candidate = lines[0]
        # Basic check to avoid company names/program titles
        lowered_candidate = candidate.lower()
        if any(bad in lowered_candidate for bad in bad_name_keywords):
            return fallback
            
        if len(candidate.split()) <= 4:
            return candidate
            
    return fallback


def extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found = []
    for skill in SKILL_LEXICON:
        if skill in lowered:
            found.append(skill)
    return sorted(set(found))


def extract_experience_years(text: str) -> int:
    matches = re.findall(r"(\d{1,2})\+?\s*(?:years|yrs)", text.lower())
    if not matches:
        return 0
    return max(int(value) for value in matches)


def parse_jd(text: str) -> dict:
    normalized = normalize_text(text)
    required_skills = extract_skills(normalized)
    min_experience_years = extract_experience_years(normalized)

    first_sentence = normalized.split(".")[0] if normalized else "Untitled Job"
    title = first_sentence[:90] if first_sentence else "Untitled Job"

    return {
        "title": title,
        "text": normalized,
        "required_skills": required_skills,
        "min_experience_years": min_experience_years,
    }


def is_resume(text: str) -> bool:
    """Heuristic to determine if a document is a resume."""
    if not text:
        return False
    
    lowered = text.lower()
    resume_indicators = {
        "experience", "education", "skills", "employment", 
        "summary", "professional", "projects", "university", 
        "curriculum vitae", "cv", "resume", "objective",
        "contacts", "work history", "academic", "profile"
    }
    negative_indicators = {
        "registration", "workshop", "certification program", 
        "course overview", "pamphlet", "flyer", "workshop session",
        "eligibility", "membership", "advertisement", "invitation to",
        "upcoming", "join us", "program date"
    }
    
    # Check indicators
    matches = sum(1 for indicator in resume_indicators if indicator in lowered)
    neg_matches = sum(1 for neg in negative_indicators if neg in lowered)
    
    # Core requirements
    has_core_section = any(core in lowered for core in ["experience", "education", "work history", "academic"])
    
    # Strictly reject if it has high negative indicators
    if neg_matches >= 1 and matches < 3:
        return False
    if neg_matches >= 2:
        return False
        
    # If it has 3 or more indicators AND at least one core section
    if "curriculum vitae" in lowered or "resume" in lowered:
        return matches >= 2 and neg_matches == 0
        
    return matches >= 3 and has_core_section and neg_matches == 0


def parse_resume(text: str, fallback_name: str) -> dict:
    normalized = normalize_text(text)
    return {
        "text": normalized,
        "candidate_name": extract_name(text, fallback_name),
        "email": extract_email(normalized),
        "phone": extract_phone(normalized),
        "skills": extract_skills(normalized),
        "experience_years": extract_experience_years(normalized),
        "is_resume": is_resume(normalized),
    }
