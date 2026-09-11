import os


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
