from math import ceil


def confidence_from_score(score: float) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 60:
        return "MEDIUM"
    return "LOW"


def jd_relevance_score(jd_text: str, resume_text: str) -> float:
    jd_words = {word for word in jd_text.lower().split() if len(word) > 3}
    if not jd_words:
        return 0.0

    resume_words = set(resume_text.lower().split())
    overlap = len(jd_words.intersection(resume_words))
    score = (overlap / len(jd_words)) * 100
    return round(min(score, 100.0), 2)


def skills_match_score(required_skills: list[str], resume_skills: list[str]) -> tuple[float, list[str]]:
    if not required_skills:
        return 100.0, []

    resume_set = set(resume_skills)
    required_set = set(required_skills)
    matched = required_set.intersection(resume_set)
    missing = sorted(required_set.difference(resume_set))
    score = (len(matched) / len(required_set)) * 100
    return round(score, 2), missing


def experience_match_score(min_experience: int, resume_experience: int) -> tuple[float, int]:
    if min_experience <= 0:
        return 100.0, 0

    if resume_experience >= min_experience:
        extra = min(resume_experience - min_experience, 5)
        bonus = (extra / 5) * 10
        return round(min(100.0, 90.0 + bonus), 2), 0

    gap = min_experience - resume_experience
    score = max(0.0, 100.0 - (gap * 20))
    return round(score, 2), gap


def final_weighted_score(jd_score: float, skills_score: float, exp_score: float) -> float:
    # Prioritize Skills (50%) and Experience (25%) over simple keyword overlap (25%)
    final = (jd_score * 0.25) + (skills_score * 0.50) + (exp_score * 0.25)
    return round(min(final, 100.0), 2)


def rank_candidates(job: dict, resumes: list[dict]) -> list[dict]:
    ranked = []
    for resume in resumes:
        jd_score = jd_relevance_score(job["text"], resume["text"])
        skill_score, missing_skills = skills_match_score(job["required_skills"], resume.get("skills", []))
        exp_score, exp_gap = experience_match_score(
            job.get("min_experience_years", 0), resume.get("experience_years", 0)
        )

        final = final_weighted_score(jd_score, skill_score, exp_score)
        confidence = confidence_from_score(final)

        reasoning = (
            f"JD relevance={ceil(jd_score)}%, skills match={ceil(skill_score)}%, "
            f"experience fit={ceil(exp_score)}%."
        )

        ranked.append(
            {
                "resume_id": resume["resume_id"],
                "name": resume.get("candidate_name", "Unknown Candidate"),
                "email": resume.get("email", ""),
                "source": resume.get("source", "manual"),
                "jd_relevance_score": jd_score,
                "skills_match_score": skill_score,
                "experience_match_score": exp_score,
                "final_score": final,
                "confidence": confidence,
                "reasoning": reasoning,
                "missing_required_skills": missing_skills,
                "experience_gap": exp_gap,
            }
        )

    ranked.sort(key=lambda item: item["final_score"], reverse=True)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked
