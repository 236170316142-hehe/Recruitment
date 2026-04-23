# Architecture

## Services

### Frontend (`frontend-node`)

- Express + EJS dashboard
- Handles form uploads
- Calls backend API endpoints
- Renders ranked candidate table and resume open action

### Backend (`backend-fastapi`)

- Handles JD upload and parsing
- Handles resume upload and parsing
- Performs weighted candidate ranking by JD, skills, and experience
- Persists jobs, resumes, and rankings in MongoDB Atlas

## Data Collections (MongoDB)

- `jobs`: JD text and parsed requirements
- `resumes`: source, parsed content, metadata, and file path
- `rankings`: per-job ranking output with scores and confidence

## API Endpoints

- `POST /upload-jd`
- `POST /upload-resumes`
- `POST /judge-batch/{job_id}`
- `GET /dashboard/{job_id}`
- `GET /resume/{resume_id}`
