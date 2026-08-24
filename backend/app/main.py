import json
import logging
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from .jobs import (
    TERMINAL_STATUSES,
    JobBusyError,
    JobManager,
    JobNotFoundError,
)
from .schemas import BrandInput, JobConfig


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data" / "jobs"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

app = FastAPI(
    title="Football Ads Detector API",
    version="0.1.0",
    description="Medición de exposición en vallas LED laterales.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:43123",
        "http://localhost:43123",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

job_manager = JobManager(DATA_ROOT)


def _slug(value: str) -> str:
    normalized = "".join(
        char.lower() if char.isalnum() else "-" for char in value.strip()
    )
    return "-".join(part for part in normalized.split("-") if part) or "brand"


def _is_upload(value: object) -> bool:
    return isinstance(value, UploadFile)


def _save_upload(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    upload.file.seek(0)
    with destination.open("wb") as output:
        shutil.copyfileobj(upload.file, output)


def _video_destination(directory: Path, field: str, upload: UploadFile) -> Path:
    original_suffix = Path(upload.filename or "").suffix.lower()
    suffix = original_suffix if original_suffix in ALLOWED_VIDEO_EXTENSIONS else ".mp4"
    return directory / f"{field}{suffix}"


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/jobs", status_code=201)
async def create_job(request: Request) -> dict[str, str]:
    active_id = job_manager.active_job_id
    if active_id:
        active = job_manager.jobs.get(active_id)
        if active and active.status not in TERMINAL_STATUSES:
            raise HTTPException(status_code=409, detail="Ya hay un análisis en curso.")

    form = await request.form()
    mode = form.get("mode")
    duration_mode = form.get("duration_mode")
    brands_raw = form.get("brands")

    if mode not in {"single", "split"}:
        raise HTTPException(status_code=422, detail="mode debe ser single o split.")
    if duration_mode not in {"5min", "10min", "full"}:
        raise HTTPException(
            status_code=422,
            detail="duration_mode debe ser 5min, 10min o full.",
        )
    if not isinstance(brands_raw, str):
        raise HTTPException(status_code=422, detail="brands debe ser JSON.")

    try:
        parsed_brands = json.loads(brands_raw)
        if not isinstance(parsed_brands, list) or not parsed_brands:
            raise ValueError
        brands = [BrandInput.model_validate(item) for item in parsed_brands]
        used_ids: set[str] = set()
        normalized_brands: list[BrandInput] = []
        for brand in brands:
            base_id = _slug(brand.id or brand.name)
            brand_id = base_id
            suffix = 2
            while brand_id in used_ids:
                brand_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(brand_id)
            normalized_brands.append(brand.model_copy(update={"id": brand_id}))
        brands = normalized_brands
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="brands debe ser una lista válida con al menos una marca.",
        ) from exc

    video_fields = (
        ["video"] if mode == "single" else ["video_first", "video_second"]
    )
    uploads: dict[str, UploadFile] = {}
    for field in video_fields:
        upload = form.get(field)
        if not _is_upload(upload) or not upload.filename:
            raise HTTPException(
                status_code=422,
                detail=f"Falta el archivo {field}.",
            )
        uploads[field] = upload

    job_id = str(uuid4())
    directory = DATA_ROOT / job_id
    directory.mkdir(parents=True, exist_ok=False)
    video_paths: list[Path] = []
    try:
        for field, upload in uploads.items():
            destination = _video_destination(directory, field, upload)
            await run_in_threadpool(_save_upload, upload, destination)
            video_paths.append(destination)

        # Logos are stored for later pipeline phases. They do not block
        # detection, as the v1 contract uses brand names and OCR.
        for brand in brands:
            brand_id = brand.id or _slug(brand.name)
            logo = form.get(f"logo_{brand_id}")
            if _is_upload(logo) and logo.filename:
                await run_in_threadpool(
                    _save_upload,
                    logo,
                    directory / f"logo_{brand_id}.png",
                )

        config = JobConfig(
            mode=mode,
            duration_mode=duration_mode,
            sample_fps=1,
        )
        record = job_manager.add_job(
            job_id=job_id,
            directory=directory,
            brands=brands,
            video_paths=video_paths,
            config=config,
        )
        logger.info("Created job %s with %s video(s)", record.id, len(video_paths))
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    return {"id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return job_manager.get(job_id).response()
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job no encontrado.") from exc


@app.get("/jobs/{job_id}/events")
async def job_events(job_id: str):
    try:
        job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job no encontrado.") from exc

    return StreamingResponse(
        job_manager.events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
