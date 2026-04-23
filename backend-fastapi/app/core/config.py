from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Recruitment Hub API"
    mongo_uri: str
    mongo_db_name: str = "recruitment_hub"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    use_llm_scoring: bool = False
    api_port: int = 8000
    
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    
    # JWT
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"

    base_dir: Path = Path(__file__).resolve().parents[2]
    storage_dir: Path = base_dir / "storage"
    jd_storage_dir: Path = storage_dir / "jds"
    resume_storage_dir: Path = storage_dir / "resumes"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
settings.jd_storage_dir.mkdir(parents=True, exist_ok=True)
settings.resume_storage_dir.mkdir(parents=True, exist_ok=True)
