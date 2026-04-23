# PRD Workflow Mapping

1. HR uploads JD
- Dashboard `POST /jobs`
- Backend `POST /upload-jd`

2. System receives resumes
- Dashboard `POST /resumes`
- Backend `POST /upload-resumes`
- Source labels: `manual` or `gmail`

3. Parser processes resumes
- PDF and DOCX text extraction
- Name, email, phone, skills, experience extraction

4. LLM batch judge runs
- Dashboard `POST /judge`
- Backend `POST /judge-batch/{job_id}`

5. HR views ranked dashboard
- Dashboard `GET /?jobId=...`
- Backend `GET /dashboard/{job_id}`

6. HR opens exact resume file
- Dashboard `GET /resume/:resumeId`
- Backend `GET /resume/{resume_id}`
