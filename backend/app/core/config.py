"""Environment-driven settings (PDF s.13: configuration via environment variables).

Swapping SQLite->PostgreSQL or LocalDisk->S3 is a config change, not a code change.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IDS_", env_file=".env", extra="ignore")

    app_name: str = "Document Screening Assistant"
    environment: str = "demo"
    database_url: str = f"sqlite:///{(PROJECT_DIR / 'data' / 'app.db').as_posix()}"
    storage_backend: str = "local"  # local | s3 (future)
    storage_root: Path = PROJECT_DIR / "data" / "storage"
    synthetic_dir: Path = PROJECT_DIR / "data" / "synthetic"
    rules_file: Path = BACKEND_DIR / "rules" / "uto_td3_v1.json"
    secret_key: str = "demo-secret-change-me-demo-secret-32b"  # secrets manager in deployment
    token_ttl_minutes: int = 480

    # Intake limits (PDF 5.1)
    max_upload_mb: int = 12
    max_image_pixels: int = 40_000_000
    allowed_types: tuple[str, ...] = ("jpeg", "png")

    # Demo only: pause between pipeline stages so progress is visible on screen
    demo_step_delay: float = 0.5
    jobs_backend: str = "background"  # background | celery (future)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.storage_root.mkdir(parents=True, exist_ok=True)
    s.synthetic_dir.mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite:///"):
        Path(s.database_url.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)
    return s
