import os
from pathlib import Path

from dotenv import load_dotenv

# Local operator: backend/.env or repo-root .env
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_REPO_ROOT / ".env")


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def keep_job_videos() -> bool:
    """When false (default), heavy job media is deleted after a successful run."""
    return _env_flag("KEEP_JOB_VIDEOS", default=False)


def cors_origins() -> list[str]:
    defaults = [
        "http://127.0.0.1:43123",
        "http://localhost:43123",
        "https://football-ads-detector.pages.dev",
    ]
    raw = os.getenv("CORS_ORIGINS", "")
    extra = [origin.strip() for origin in raw.split(",") if origin.strip()]
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    origins: list[str] = []
    for origin in defaults + extra:
        if origin not in seen:
            seen.add(origin)
            origins.append(origin)
    return origins


def sync_token() -> str | None:
    raw = (os.getenv("SYNC_TOKEN") or "").strip()
    return raw or None


def cloud_api_url() -> str | None:
    raw = (os.getenv("CLOUD_API_URL") or "").strip().rstrip("/")
    return raw or None


def cloud_sync_enabled() -> bool:
    return bool(cloud_api_url() and sync_token())
