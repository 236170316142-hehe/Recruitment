from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.auth import router as auth_router
from app.core.config import settings
from app.db.mongo import close_client, get_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    db = get_db()
    
    try:
        # Create indexes for job/resume collections
        await db.jobs.create_index("job_id", unique=True)
        await db.resumes.create_index("resume_id", unique=True)
        await db.resumes.create_index([("job_id", 1), ("source", 1)])
        await db.rankings.create_index([("job_id", 1), ("final_score", -1)])
        await db.rankings.create_index([("job_id", 1), ("rank", 1)])
        
        # Create indexes for user collection
        await db.users.create_index("user_id", unique=True)
        await db.users.create_index("google_id", unique=True)
        await db.users.create_index("email")
    except Exception as e:
        print(f"Index creation skipped/failed: {e}")
    
    yield
    await close_client()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for easier deployment, restrict in production if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(router)
