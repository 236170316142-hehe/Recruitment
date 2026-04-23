from datetime import datetime, timezone
from typing import Optional

from groq import AsyncGroq
import asyncio
import json

from app.core.config import settings

class GroqRanker:
    def __init__(self):
        self.model = settings.groq_model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not settings.groq_api_key:
                return None
            try:
                # We initialize without 'proxies' to avoid version issues on Render
                self._client = AsyncGroq(api_key=settings.groq_api_key)
            except Exception as e:
                print(f"CRITICAL: Failed to initialize Groq client: {e}")
                return None
        return self._client

        client = self.client
        if not client:
            return True # Fallback if client failed

        try:
            # We use a faster/cheaper model for simple classification
            prompt = f"""Task: Determine if the following text belongs to an individual's Professional Resume/CV.
Reject documents that are flyers, program pamphlets, workshop invitations, invoices, or advertisements.

TEXT SNIPPET:
{text[:2500]}

Return ONLY a JSON object: {{"is_resume": boolean, "reason": "string"}}"""

            completion = await client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "system", "content": "You are a document classifier."},
                          {"role": "user", "content": prompt}],
                max_tokens=100,
                response_format={"type": "json_object"}
            )
            
            data = json.loads(completion.choices[0].message.content)
            is_res = data.get("is_resume", True)
            if not is_res:
                print(f"AI Filter: Document rejected as non-resume. Reason: {data.get('reason')}")
            return is_res
        except Exception as e:
            print(f"AI Classification Error: {e}")
            return True

    async def rank_candidates(self, jd_text: str, resumes: list[dict]) -> list[dict]:
        """Use Groq LLM to rank candidates based on JD and resume texts in parallel (sequential for 70B)."""
        if not settings.use_llm_scoring or not settings.groq_api_key:
            return []

        # Use strict sequential processing for 70B models to avoid TPM/RPM limits
        semaphore = asyncio.Semaphore(1) 
        # Further reduce text to save tokens on free tier
        jd_text_limited = jd_text[:2000]

        async def analyze_candidate(r):
            async with semaphore:
                candidate_name = r.get("candidate_name", "Unknown")
                resume_id = r.get("resume_id")
                # Shorter resume text to stay under TPM
                resume_text = (r.get("text") or "")[:3000]

                try:
                    prompt = f"""You are a high-level Senior Technical Recruiter. Perform a deep logical analysis.

ANALYTICAL FRAMEWORK:
1. INTERNAL CHECK: Do NOT claim a skill is missing if it exists in the resume.
2. EXPERIENCE: Verify if they have the required years.
3. CALIBRATION: Be critical. 90+ is nearly perfect. 50 is average.

JOB DESCRIPTION SUMMARY:
{jd_text_limited}

CANDIDATE RESUME:
Name: {candidate_name}
{resume_text}

Return ONLY a valid JSON object with:
- analysis: Internal step-by-step reasoning.
- resume_id: "{resume_id}"
- score: (0-100) Be discriminating.
- confidence: HIGH (>=70), MEDIUM (40-69), LOW (<40).
- reasoning: Short conclusion.
- strengths: list of 3-5 key technical strengths.
- weaknesses: list of essential missing items.
- skills: list of technical keywords."""

                client = self.client
                if not client:
                    return {"resume_id": resume_id, "score": 0, "confidence": "LOW", "reasoning": "AI Unavailable", "strengths": [], "weaknesses": [], "skills": []}

                try:
                    prompt = f"""You are a high-level Senior Technical Recruiter. Perform a deep logical analysis.

ANALYTICAL FRAMEWORK:
1. INTERNAL CHECK: Do NOT claim a skill is missing if it exists in the resume.
2. EXPERIENCE: Verify if they have the required years.
3. CALIBRATION: Be critical. 90+ is nearly perfect. 50 is average.

JOB DESCRIPTION SUMMARY:
{jd_text_limited}

CANDIDATE RESUME:
Name: {candidate_name}
{resume_text}

Return ONLY a valid JSON object with:
- analysis: Internal step-by-step reasoning.
- resume_id: "{resume_id}"
- score: (0-100) Be discriminating.
- confidence: HIGH (>=70), MEDIUM (40-69), LOW (<40).
- reasoning: Short conclusion.
- strengths: list of 3-5 key technical strengths.
- weaknesses: list of essential missing items.
- skills: list of technical keywords."""

                    completion = await client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=800,
                        response_format={"type": "json_object"}
                    )

                    response_text = completion.choices[0].message.content
                    # Small pause to avoid RPM limit
                    await asyncio.sleep(0.5) 
                    return json.loads(response_text)

                except Exception as e:
                    print(f"Error ranking candidate {candidate_name}: {e}")
                    return {
                        "resume_id": resume_id,
                        "score": 0,
                        "confidence": "LOW",
                        "reasoning": f"Analysis Interrupted: {str(e)}",
                        "strengths": [],
                        "weaknesses": ["Limit reached or error"],
                        "skills": []
                    }

        # Phase 1: Sequential Analysis
        tasks = [analyze_candidate(r) for r in resumes]
        rankings = await asyncio.gather(*tasks)
        
        # Phase 2: Relative Calibration
        if len(rankings) > 1:
            try:
                # Filter out failed analyses
                valid_rankings = [r for r in rankings if r.get("score") is not None and r["score"] > 0]
                if len(valid_rankings) < 2: return rankings

                calibration_summaries = "\n".join([
                    f"- {r.get('resume_id')}: Score {r.get('score')}, Strengths: {', '.join(r.get('strengths', []))}" 
                    for r in valid_rankings
                ])

                calibration_prompt = f"""You are a senior hiring manager. DISTINGUISH between these candidates and eliminate ties. 

JD: {jd_text_limited}
SUMMARIES:
{calibration_summaries}

Adjust scores (0-100) to create a clear separation. 
Return ONLY JSON: {{"resume_id": adjusted_score, ...}}"""

                client = self.client
                if not client: return rankings

                cal_completion = await client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": calibration_prompt}],
                    max_tokens=400,
                    response_format={"type": "json_object"}
                )
                
                adj_scores = json.loads(cal_completion.choices[0].message.content)
                for r in rankings:
                    rid = r.get("resume_id")
                    if rid in adj_scores:
                        r["score"] = float(adj_scores[rid])
                        if r["score"] >= 70: r["confidence"] = "HIGH"
                        elif r["score"] >= 40: r["confidence"] = "MEDIUM"
                        else: r["confidence"] = "LOW"

            except Exception as e:
                print(f"Calibration failed: {e}")

        return rankings
