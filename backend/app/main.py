import csv
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from uuid import uuid4

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from pydantic import ValidationError

from .jobs import (
    TERMINAL_STATUSES,
    JobManager,
    JobNotFoundError,
)
from . import db
from .domain.stadium import Stadium
from .pipeline.calibrate import load_sample_frame, persist_stadium, propose_from_frame
from .pipeline.brands import brands_from_names
from .job_storage import maybe_purge_job_media, video_paths_from_meta
from .pipeline.brand_refs import extract_video_keyframes, save_image_bytes
from .pipeline.catalog import build_catalog_payload
from .pipeline.catalog_report import build_catalog_report
from .pipeline.playlist import parse_playlist, unique_brands
from .pipeline.video import get_video_info
from .settings import cloud_sync_enabled, cors_origins, sync_token
from .sync_config import (
    SYNC_HEADER,
    export_config_zip,
    import_config_zip,
    maybe_pull_from_cloud,
    maybe_push_to_cloud,
    pull_from_cloud,
    push_to_cloud,
)
from .schemas import (
    BrandGroupSummary,
    BrandInput,
    BrandRefSummary,
    BrandRefsCreateResponse,
    BrandSummary,
    CalibrationProposeResponse,
    CalibrationPreviews,
    CalibrationSaveRequest,
    CalibrationSaveResponse,
    CatalogFramePatch,
    CatalogReportResponse,
    CatalogResponse,
    JobConfig,
    JobSummary,
    StadiumSummary,
    normalize_duration_mode,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data" / "jobs"
BRANDS_DIR = PROJECT_ROOT / "data" / "brands"
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
ALLOWED_PLAYLIST_EXTENSIONS = {".xlsx", ".xlsm"}
ALLOWED_CALIBRATION_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
}
ALLOWED_BRAND_REF_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

app = FastAPI(
    title="Football Ads Detector API",
    version="0.1.0",
    description="Medición de exposición en vallas LED laterales.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

job_manager = JobManager(DATA_ROOT)


@app.on_event("startup")
async def startup() -> None:
    await run_in_threadpool(db.ensure_db)
    await job_manager.recover_from_db()
    await run_in_threadpool(maybe_pull_from_cloud)


def _require_sync_token(request: Request) -> None:
    expected = sync_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SYNC_TOKEN no configurado en este servidor.",
        )
    got = request.headers.get(SYNC_HEADER) or request.headers.get(SYNC_HEADER.lower())
    if got != expected:
        raise HTTPException(status_code=401, detail="Token de sync inválido.")


async def _after_config_mutation() -> None:
    await run_in_threadpool(maybe_push_to_cloud)


@app.get("/sync/status")
async def sync_status() -> dict:
    return {
        "cloud_configured": cloud_sync_enabled(),
        "cloud_api_url": bool(cloud_sync_enabled()),
        "server_accepts_sync": bool(sync_token()),
    }


@app.get("/sync/config")
async def sync_config_export(request: Request) -> Response:
    _require_sync_token(request)
    payload = await run_in_threadpool(export_config_zip)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=config-sync.zip"},
    )


@app.put("/sync/config")
async def sync_config_import(request: Request) -> dict:
    _require_sync_token(request)
    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="ZIP vacío.")
    try:
        counts = await run_in_threadpool(import_config_zip, body, True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="ZIP inválido.") from exc
    return {"ok": True, "counts": counts}


@app.post("/sync/pull")
async def sync_pull_local() -> dict:
    if not cloud_sync_enabled():
        raise HTTPException(
            status_code=503,
            detail="Configura CLOUD_API_URL y SYNC_TOKEN en el backend local.",
        )
    try:
        return await run_in_threadpool(pull_from_cloud)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pull falló: {exc}") from exc


@app.post("/sync/push")
async def sync_push_local() -> dict:
    if not cloud_sync_enabled():
        raise HTTPException(
            status_code=503,
            detail="Configura CLOUD_API_URL y SYNC_TOKEN en el backend local.",
        )
    try:
        return await run_in_threadpool(push_to_cloud)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Push falló: {exc}") from exc


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


def _brand_ref_image_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".png":
        return ".png"
    return ".jpg"


async def _require_brand(brand_id: str) -> dict:
    brand = await run_in_threadpool(db.get_brand, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Marca no encontrada.")
    return brand


def _video_destination(directory: Path, field: str, upload: UploadFile) -> Path:
    original_suffix = Path(upload.filename or "").suffix.lower()
    suffix = original_suffix if original_suffix in ALLOWED_VIDEO_EXTENSIONS else ".mp4"
    return directory / f"{field}{suffix}"


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


def _normalize_stadium_id(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    slug = "_".join(part for part in slug.split("_") if part)
    if not slug:
        raise HTTPException(status_code=422, detail="stadium_id es obligatorio.")
    return slug


@app.get("/stadiums")
async def list_stadiums() -> list[StadiumSummary]:
    rows = await run_in_threadpool(db.list_stadium_summaries)
    return [StadiumSummary.model_validate(row) for row in rows]


@app.post("/calibration/propose")
async def propose_calibration(request: Request) -> CalibrationProposeResponse:
    form = await request.form()
    upload = form.get("file") or form.get("image") or form.get("video")
    if not _is_upload(upload) or not upload.filename:
        raise HTTPException(
            status_code=422,
            detail="Sube una imagen o un video de muestra en el campo file.",
        )

    suffix = Path(upload.filename).suffix.lower()
    if suffix and suffix not in ALLOWED_CALIBRATION_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Usa JPG, PNG, WebP, MP4, MOV, MKV o WebM.",
        )

    data = await upload.read()
    if not data:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")

    try:
        frame = await run_in_threadpool(load_sample_frame, data, upload.filename)
        camera, preview_map = await run_in_threadpool(propose_from_frame, frame)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CalibrationProposeResponse(
        camera=camera,
        previews=CalibrationPreviews.model_validate(preview_map),
    )


@app.post("/calibration/save")
async def save_calibration(payload: CalibrationSaveRequest) -> CalibrationSaveResponse:
    stadium_id = _normalize_stadium_id(payload.stadium_id)
    stadium = Stadium(
        id=stadium_id,
        nombre=payload.nombre.strip(),
        pais=payload.pais,
        default_camera=payload.camera.id,
        camera=payload.camera,
    )
    try:
        Stadium.model_validate(stadium.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    summary = await run_in_threadpool(persist_stadium, stadium)
    await _after_config_mutation()
    return CalibrationSaveResponse.model_validate(summary)


@app.get("/brands")
async def list_brands() -> list[BrandSummary]:
    rows = await run_in_threadpool(db.list_brands)
    return [BrandSummary.model_validate(row) for row in rows]


@app.get("/brand-groups")
async def list_brand_groups() -> list[BrandGroupSummary]:
    rows = await run_in_threadpool(db.list_brand_groups)
    return [BrandGroupSummary.model_validate(row) for row in rows]


async def _read_titulo(request: Request) -> str:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="titulo es obligatorio.")
        titulo = payload.get("titulo")
    else:
        form = await request.form()
        titulo = form.get("titulo")
    if not isinstance(titulo, str) or not titulo.strip():
        raise HTTPException(status_code=422, detail="titulo es obligatorio.")
    return titulo.strip()


@app.post("/brand-groups", status_code=201)
async def create_brand_group(request: Request) -> BrandGroupSummary:
    titulo = await _read_titulo(request)
    try:
        group_id = await run_in_threadpool(db.create_brand_group, titulo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    groups = await run_in_threadpool(db.list_brand_groups)
    for group in groups:
        if group["id"] == group_id:
            await _after_config_mutation()
            return BrandGroupSummary.model_validate(group)
    await _after_config_mutation()
    return BrandGroupSummary(id=group_id, titulo=titulo, brands=[])


@app.delete("/brand-groups/{group_id}", status_code=204)
async def delete_brand_group(group_id: str) -> Response:
    try:
        await run_in_threadpool(db.delete_brand_group, group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Grupo no encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _after_config_mutation()
    return Response(status_code=204)


@app.post("/brands", status_code=201)
async def create_brand(request: Request) -> BrandSummary:
    form = await request.form()
    name_raw = form.get("name")
    aliases_raw = form.get("aliases")
    logo = form.get("logo")

    if not isinstance(name_raw, str) or not name_raw.strip():
        raise HTTPException(status_code=422, detail="name es obligatorio.")

    name = name_raw.strip()
    brand_id = _slug(name)

    group_id_raw = form.get("group_id")
    group_id: str | None = None
    if isinstance(group_id_raw, str) and group_id_raw.strip():
        group_id = group_id_raw.strip()

    aliases: list[str] = []
    if aliases_raw is not None:
        if not isinstance(aliases_raw, str):
            raise HTTPException(status_code=422, detail="aliases debe ser JSON.")
        try:
            parsed_aliases = json.loads(aliases_raw)
            if not isinstance(parsed_aliases, list):
                raise ValueError
            aliases = [str(item).strip() for item in parsed_aliases if str(item).strip()]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="aliases debe ser una lista JSON válida.",
            ) from exc

    logo_path: str | None = None
    if _is_upload(logo) and logo.filename:
        destination = BRANDS_DIR / f"{brand_id}.png"
        await run_in_threadpool(_save_upload, logo, destination)
        logo_path = str(destination)

    try:
        row = await run_in_threadpool(
            db.upsert_brand,
            brand_id,
            name,
            aliases,
            logo_path,
            group_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if logo_path:
        await run_in_threadpool(
            db.replace_logo_brand_ref,
            brand_id,
            logo_path,
            logo.filename if _is_upload(logo) else None,
        )
    await _after_config_mutation()
    return BrandSummary.model_validate(row)


@app.patch("/brands/{brand_id}")
async def patch_brand(brand_id: str, request: Request) -> BrandSummary:
    existing = await run_in_threadpool(db.get_brand, brand_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Marca no encontrada.")

    content_type = request.headers.get("content-type", "")
    fields: dict = {}
    logo = None
    if "application/json" in content_type:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="JSON inválido.")
        if "nombre" in payload:
            fields["nombre"] = payload["nombre"]
        if "name" in payload and "nombre" not in fields:
            fields["nombre"] = payload["name"]
        if "aliases" in payload:
            aliases = payload["aliases"]
            if aliases is not None and not isinstance(aliases, list):
                raise HTTPException(status_code=422, detail="aliases debe ser una lista.")
            fields["aliases"] = aliases
        if "activo" in payload and payload["activo"] is not None:
            fields["activo"] = payload["activo"]
        if "group_id" in payload and payload["group_id"]:
            fields["group_id"] = payload["group_id"]
    else:
        form = await request.form()
        if "nombre" in form or "name" in form:
            name_raw = form.get("nombre") or form.get("name")
            if isinstance(name_raw, str):
                fields["nombre"] = name_raw
        aliases_raw = form.get("aliases")
        if isinstance(aliases_raw, str) and aliases_raw.strip():
            try:
                parsed_aliases = json.loads(aliases_raw)
                if not isinstance(parsed_aliases, list):
                    raise ValueError
                fields["aliases"] = [
                    str(item).strip() for item in parsed_aliases if str(item).strip()
                ]
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="aliases debe ser una lista JSON válida.",
                ) from exc
        activo_raw = form.get("activo")
        if isinstance(activo_raw, str) and activo_raw != "":
            fields["activo"] = activo_raw.strip() not in {"0", "false", "False"}
        group_id_raw = form.get("group_id")
        if isinstance(group_id_raw, str) and group_id_raw.strip():
            fields["group_id"] = group_id_raw.strip()
        logo = form.get("logo")

    if _is_upload(logo) and logo.filename:
        destination = BRANDS_DIR / f"{brand_id}.png"
        await run_in_threadpool(_save_upload, logo, destination)
        fields["logo_path"] = str(destination)

    try:
        row = await run_in_threadpool(db.update_brand, brand_id, **fields)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Marca no encontrada.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if fields.get("logo_path"):
        await run_in_threadpool(
            db.replace_logo_brand_ref,
            brand_id,
            fields["logo_path"],
            logo.filename if _is_upload(logo) and logo.filename else None,
        )
    await _after_config_mutation()
    return BrandSummary.model_validate(row)


@app.get("/brands/{brand_id}/refs")
async def list_brand_refs(brand_id: str) -> list[BrandRefSummary]:
    await _require_brand(brand_id)
    rows = await run_in_threadpool(db.list_brand_refs, brand_id)
    return [BrandRefSummary.model_validate(row) for row in rows]


@app.post("/brands/{brand_id}/refs", status_code=201)
async def create_brand_refs(
    brand_id: str,
    request: Request,
) -> BrandRefsCreateResponse:
    await _require_brand(brand_id)
    form = await request.form()
    image_uploads = [
        upload
        for upload in form.getlist("images")
        if _is_upload(upload) and upload.filename
    ]
    video_upload = form.get("video")
    has_video = _is_upload(video_upload) and video_upload.filename

    if not image_uploads and not has_video:
        raise HTTPException(
            status_code=422,
            detail="Sube al menos una imagen (images) o un video (video).",
        )

    refs_dir = db.brand_refs_dir(brand_id)
    created: list[BrandRefSummary] = []

    for upload in image_uploads:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_BRAND_REF_IMAGE_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail="Las imágenes deben ser JPG, PNG o WebP.",
            )
        ref_id = uuid4().hex
        destination = refs_dir / f"{ref_id}{_brand_ref_image_suffix(upload.filename or '')}"
        data = await upload.read()
        try:
            await run_in_threadpool(save_image_bytes, data, destination)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        row = await run_in_threadpool(
            db.insert_brand_ref,
            ref_id,
            brand_id,
            "image",
            str(destination),
            upload.filename,
        )
        created.append(BrandRefSummary.model_validate(row))

    if has_video:
        suffix = Path(video_upload.filename or "").suffix.lower()
        if suffix not in ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail="El video debe ser MP4, MOV, MKV o WebM.",
            )
        temp_video = refs_dir / f"_tmp_{uuid4().hex}{suffix}"
        try:
            await run_in_threadpool(_save_upload, video_upload, temp_video)
            keyframes = await run_in_threadpool(
                extract_video_keyframes,
                temp_video,
                refs_dir,
            )
            if not keyframes:
                raise HTTPException(
                    status_code=422,
                    detail="No se pudieron extraer frames del video.",
                )
            source_name = video_upload.filename
            for ref_id, frame_path in keyframes:
                row = await run_in_threadpool(
                    db.insert_brand_ref,
                    ref_id,
                    brand_id,
                    "video_frame",
                    str(frame_path),
                    source_name,
                )
                created.append(BrandRefSummary.model_validate(row))
        finally:
            if temp_video.is_file():
                temp_video.unlink()

    await _after_config_mutation()
    return BrandRefsCreateResponse(refs=created)


@app.get("/brands/{brand_id}/refs/{ref_id}/image")
async def get_brand_ref_image(brand_id: str, ref_id: str):
    ref = await run_in_threadpool(db.get_brand_ref, brand_id, ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="Referencia no encontrada.")
    image_path = Path(ref["path"]).resolve()
    refs_root = db.brand_refs_dir(brand_id).resolve()
    brands_root = BRANDS_DIR.resolve()
    allowed_roots = {refs_root, brands_root}
    if not any(str(image_path).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Imagen no encontrada.")
    media_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(
        image_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.delete("/brands/{brand_id}/refs/{ref_id}", status_code=204)
async def delete_brand_ref(brand_id: str, ref_id: str) -> Response:
    await _require_brand(brand_id)
    deleted = await run_in_threadpool(db.delete_brand_ref, brand_id, ref_id)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Referencia no encontrada.")
    image_path = Path(deleted["path"])
    if image_path.is_file():
        await run_in_threadpool(image_path.unlink)
    await _after_config_mutation()
    return Response(status_code=204)


@app.delete("/brands/{brand_id}", status_code=204)
async def delete_brand(brand_id: str) -> Response:
    deleted = await run_in_threadpool(db.delete_brand, brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Marca no encontrada.")
    await _after_config_mutation()
    return Response(status_code=204)


@app.post("/jobs", status_code=201)
async def create_job(request: Request) -> dict[str, str]:
    form = await request.form()
    mode = form.get("mode")
    duration_mode = form.get("duration_mode")
    brands_raw = form.get("brands")
    stadium_id_raw = form.get("stadium_id")
    analysis_mode_raw = form.get("analysis_mode")
    kickoff_offset_raw = form.get("kickoff_offset_sec")
    second_half_raw = form.get("second_half_start_sec")
    playlist_upload = form.get("playlist")

    if mode not in {"single", "split"}:
        raise HTTPException(status_code=422, detail="mode debe ser single o split.")
    if not isinstance(duration_mode, str):
        raise HTTPException(
            status_code=422,
            detail="duration_mode debe ser 'full' o '{N}min' (ej. 5min, 16min).",
        )
    try:
        duration_mode = normalize_duration_mode(duration_mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    analysis_mode = "discovery"
    if isinstance(analysis_mode_raw, str) and analysis_mode_raw.strip():
        if analysis_mode_raw.strip() not in {"discovery", "playlist_verify"}:
            raise HTTPException(
                status_code=422,
                detail="analysis_mode debe ser discovery o playlist_verify.",
            )
        analysis_mode = analysis_mode_raw.strip()

    def _parse_optional_float(raw, field_name: str) -> float | None:
        if raw is None or raw == "":
            return None
        if not isinstance(raw, str):
            raise HTTPException(
                status_code=422, detail=f"{field_name} debe ser un número."
            )
        try:
            return float(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"{field_name} debe ser un número."
            ) from exc

    kickoff_offset_sec = _parse_optional_float(
        kickoff_offset_raw, "kickoff_offset_sec"
    )
    second_half_start_sec = _parse_optional_float(
        second_half_raw, "second_half_start_sec"
    )

    if brands_raw is None or brands_raw == "":
        brands_raw = "[]"
    if not isinstance(brands_raw, str):
        raise HTTPException(status_code=422, detail="brands debe ser JSON.")

    try:
        parsed_brands = json.loads(brands_raw)
        if not isinstance(parsed_brands, list):
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
            detail="brands debe ser una lista JSON válida.",
        ) from exc

    stadium_id: str | None = None
    if stadium_id_raw is not None:
        if not isinstance(stadium_id_raw, str) or not stadium_id_raw.strip():
            raise HTTPException(
                status_code=422,
                detail="stadium_id debe ser un texto no vacío.",
            )
        stadium_id = stadium_id_raw.strip()
        exists = await run_in_threadpool(db.stadium_exists, stadium_id)
        if not exists:
            raise HTTPException(
                status_code=422,
                detail=f"stadium_id desconocido: {stadium_id!r}.",
            )

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
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"El archivo {field} no es un video compatible. "
                    "Usá MP4, MOV, MKV o WebM."
                ),
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
            try:
                info = await run_in_threadpool(get_video_info, destination)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"El archivo {field} no se puede leer como video.",
                ) from exc
            if info.frame_count <= 0 or info.duration_seconds <= 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"El archivo {field} no contiene frames de video.",
                )
            video_paths.append(destination)

        playlist_path = None
        if _is_upload(playlist_upload) and playlist_upload.filename:
            suffix = Path(playlist_upload.filename).suffix.lower()
            if suffix not in ALLOWED_PLAYLIST_EXTENSIONS:
                raise HTTPException(
                    status_code=422,
                    detail="La playlist debe ser un Excel .xlsx.",
                )
            playlist_path = directory / "playlist.xlsx"
            await run_in_threadpool(_save_upload, playlist_upload, playlist_path)
            try:
                playlist_slots = parse_playlist(playlist_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=422,
                    detail="No se pudo leer la playlist Lions.",
                ) from exc
            analysis_mode = "playlist_verify"
            playlist_brands = brands_from_names(unique_brands(playlist_slots))
            known = {brand.id for brand in brands}
            for extra in playlist_brands:
                if extra.id not in known:
                    brands.append(extra)
                    known.add(extra.id)

        if not brands:
            raise HTTPException(
                status_code=422,
                detail="Cargá al menos una marca o una playlist Lions.",
            )

        # Logos feed the FIXED_PRINT template matcher; LED OCR still runs
        # from brand names even when a logo is missing.
        brands_with_logos: list[BrandInput] = []
        for brand in brands:
            brand_id = brand.id or _slug(brand.name)
            destination = directory / f"logo_{brand_id}.png"
            logo = form.get(f"logo_{brand_id}")
            if _is_upload(logo) and logo.filename:
                await run_in_threadpool(_save_upload, logo, destination)
            else:
                library_brand = await run_in_threadpool(db.get_brand, brand_id)
                library_logo = (
                    Path(library_brand["logo_path"])
                    if library_brand and library_brand.get("logo_path")
                    else None
                )
                if library_logo and library_logo.is_file():
                    await run_in_threadpool(shutil.copy2, library_logo, destination)
            brands_with_logos.append(
                brand.model_copy(
                    update={
                        "logo_path": str(destination) if destination.is_file() else None
                    }
                )
            )
        brands = brands_with_logos

        config = JobConfig(
            mode=mode,
            duration_mode=duration_mode,
            sample_fps=1,
            stadium_id=stadium_id,
            analysis_mode=analysis_mode,
            kickoff_offset_sec=kickoff_offset_sec,
            second_half_start_sec=second_half_start_sec,
        )
        meta = {
            "brands": [brand.model_dump(mode="json") for brand in brands],
            "video_paths": [str(path) for path in video_paths],
            "sample_fps": config.sample_fps,
            "analysis_mode": config.analysis_mode,
            "playlist_path": str(playlist_path) if playlist_path else None,
            "kickoff_offset_sec": kickoff_offset_sec,
            "second_half_start_sec": second_half_start_sec,
        }
        (directory / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        record = job_manager.add_job(
            job_id=job_id,
            directory=directory,
            brands=brands,
            video_paths=video_paths,
            config=config,
            playlist_path=playlist_path,
        )
        logger.info("Created job %s with %s video(s)", record.id, len(video_paths))
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    return {"id": job_id, "status": record.status}


def _build_export_csv(job_id: str, result) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "brand_id",
            "brand_name",
            "zone_id",
            "posicion",
            "half",
            "clock_start",
            "clock_end",
            "duration_seconds",
            "video_seconds_start",
            "video_seconds_end",
        ]
    )
    for brand in result.brands:
        for segment in brand.segments:
            writer.writerow(
                [
                    brand.brand_id,
                    brand.name,
                    segment.zone_id or "",
                    segment.posicion or "",
                    segment.half,
                    segment.clock_start,
                    segment.clock_end,
                    segment.duration_seconds,
                    segment.video_seconds_start,
                    segment.video_seconds_end,
                ]
            )
    return buffer.getvalue()


@app.get("/jobs")
async def list_jobs(limit: int = 50) -> list[JobSummary]:
    rows = await run_in_threadpool(db.list_job_summaries, limit)
    summaries = [JobSummary.model_validate(row) for row in rows]
    by_id = {summary.id: summary for summary in summaries}
    for job_id, record in job_manager.jobs.items():
        if job_id not in by_id:
            continue
        summary = by_id[job_id]
        summary.status = record.status
        summary.progress = record.progress
        if record.result is not None:
            summary.summary.brand_count = len(record.result.brands)
            summary.summary.total_exposure_seconds = sum(
                brand.total_seconds for brand in record.result.brands
            )
            summary.summary.analyzed_seconds = record.result.analyzed_seconds
    return summaries


@app.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    record = job_manager.jobs.get(job_id)
    if record is not None and record.status in {
        "queued",
        "detecting_kickoff",
        "processing",
    }:
        raise HTTPException(
            status_code=409,
            detail="No se puede borrar un análisis en curso. Deténlo o espera a que termine.",
        )
    row = await run_in_threadpool(db.get_job_row, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    if row["status"] in {"queued", "detecting_kickoff", "processing"}:
        raise HTTPException(
            status_code=409,
            detail="No se puede borrar un análisis en curso. Deténlo o espera a que termine.",
        )

    directory = await run_in_threadpool(db.delete_job, job_id)
    job_manager.discard(job_id)
    if directory:
        job_dir = Path(directory)
        if job_dir.is_dir():
            await run_in_threadpool(shutil.rmtree, job_dir, True)
    return {"job_id": job_id, "deleted": True}


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    try:
        record = await job_manager.request_cancel(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job no encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.response()


@app.get("/jobs/active")
async def get_active_job():
    """Return the in-memory job so a refreshed browser can resume its view."""
    active_id = job_manager.active_job_id
    if not active_id:
        return None
    record = job_manager.jobs.get(active_id)
    if record is None or record.status in TERMINAL_STATUSES:
        return None
    return record.response()


def _read_frame_jpeg(video_path: Path, frame_idx: int) -> bytes | None:
    if frame_idx < 0:
        return None
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return None
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        encoded, buffer = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), 88],
        )
        return buffer.tobytes() if encoded else None
    finally:
        cap.release()


@app.get("/jobs/{job_id}/frames/{frame_idx}")
async def get_job_frame(job_id: str, frame_idx: int, half: str = "1T"):
    """Return the original broadcast frame for a segment thumbnail/lightbox."""
    job_directory = (DATA_ROOT / job_id).resolve()
    if job_directory.parent != DATA_ROOT.resolve():
        raise HTTPException(status_code=404, detail="Job no encontrado.")

    try:
        record = job_manager.get(job_id)
    except JobNotFoundError:
        record = None

    if half not in {"1T", "2T"}:
        raise HTTPException(status_code=422, detail="half debe ser 1T o 2T.")

    if record is not None:
        video_index = 1 if half == "2T" and len(record.video_paths) > 1 else 0
        if video_index >= len(record.video_paths):
            raise HTTPException(
                status_code=404,
                detail="Video de la mitad no encontrado.",
            )
        video_path = record.video_paths[video_index]
    else:
        if not job_directory.is_dir():
            raise HTTPException(status_code=404, detail="Job no encontrado.")
        first_candidates = sorted(job_directory.glob("video_first.*"))
        second_candidates = sorted(job_directory.glob("video_second.*"))
        single_candidates = sorted(job_directory.glob("video.*"))
        candidates = (
            second_candidates if half == "2T" and second_candidates else
            first_candidates if half == "1T" and first_candidates else
            single_candidates
        )
        if not candidates:
            raise HTTPException(status_code=404, detail="Video no encontrado.")
        video_path = candidates[0]

    payload = await run_in_threadpool(
        _read_frame_jpeg,
        video_path,
        frame_idx,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Frame no encontrado.")
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/jobs/{job_id}/catalog")
async def get_job_catalog(job_id: str) -> CatalogResponse:
    payload = await run_in_threadpool(build_catalog_payload, job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return CatalogResponse.model_validate(payload)


@app.get("/jobs/{job_id}/catalog/frames/{frame_id}/image")
async def get_catalog_frame_image(
    job_id: str,
    frame_id: int,
    kind: str = "context",
):
    row = await run_in_threadpool(db.get_job_frame, job_id, frame_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Frame no encontrado.")
    job = await run_in_threadpool(db.get_job_row, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    job_dir = Path(job["directory"]).resolve()
    wanted = (kind or "context").strip().lower()
    candidates: list[str] = []
    if wanted == "crop":
        if row.get("crop_relpath"):
            candidates.append(row["crop_relpath"])
    else:
        if row.get("context_relpath"):
            candidates.append(row["context_relpath"])
        if row.get("crop_relpath"):
            candidates.append(row["crop_relpath"])
    for relpath in candidates:
        image_path = (job_dir / relpath).resolve()
        if str(image_path).startswith(str(job_dir)) and image_path.is_file():
            return FileResponse(
                image_path,
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=3600"},
            )
    raise HTTPException(status_code=404, detail="Imagen de catálogo no encontrada.")


@app.get("/jobs/{job_id}/preview.jpg")
async def get_job_preview(job_id: str):
    job = await run_in_threadpool(db.get_job_row, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    job_dir = Path(job["directory"]).resolve()
    preview = (job_dir / "preview.jpg").resolve()
    if not str(preview).startswith(str(job_dir)) or not preview.is_file():
        raise HTTPException(status_code=404, detail="Preview no disponible.")
    return FileResponse(
        preview,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.patch("/jobs/{job_id}/catalog/frames/{frame_id}")
async def patch_catalog_frame(job_id: str, frame_id: int, payload: CatalogFramePatch):
    job = await run_in_threadpool(db.get_job_row, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    if job["catalog_confirmed_at"]:
        raise HTTPException(status_code=409, detail="El catálogo ya fue confirmado.")
    frame = await run_in_threadpool(db.get_job_frame, job_id, frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="Frame no encontrado.")
    if payload.action == "false_positive":
        updated = await run_in_threadpool(
            db.update_job_frame,
            frame_id,
            brand_id=None,
            user_verdict="false_positive",
            machine_label="attention",
        )
    elif payload.action == "assign":
        if not payload.brand_id:
            raise HTTPException(status_code=422, detail="brand_id es obligatorio.")
        brand = await run_in_threadpool(db.get_brand, payload.brand_id)
        if brand is None:
            raise HTTPException(status_code=422, detail="Marca no encontrada.")
        updated = await run_in_threadpool(
            db.update_job_frame,
            frame_id,
            brand_id=payload.brand_id,
            user_verdict="assigned",
            machine_label="positive",
        )
    else:
        raise HTTPException(status_code=422, detail="Acción no válida.")
    if updated is None:
        raise HTTPException(status_code=404, detail="Frame no encontrado.")
    public = {
        "id": updated["id"],
        "half": updated["half"],
        "frame_idx": updated["frame_idx"],
        "time_seconds": updated["time_seconds"],
        "zone_id": updated["zone_id"],
        "posicion": updated["posicion"],
        "ocr_text": updated["ocr_text"] or "",
        "machine_label": updated["machine_label"],
        "brand_id": updated["brand_id"],
        "user_verdict": updated["user_verdict"],
        "image_url": f"/jobs/{job_id}/catalog/frames/{frame_id}/image",
        "crop_image_url": f"/jobs/{job_id}/catalog/frames/{frame_id}/image?kind=crop",
        "has_context": bool(updated.get("context_relpath")),
    }
    return public


@app.post("/jobs/{job_id}/catalog/confirm")
async def confirm_job_catalog(job_id: str):
    job = await run_in_threadpool(db.get_job_row, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    if job["catalog_confirmed_at"]:
        raise HTTPException(status_code=409, detail="El catálogo ya fue confirmado.")
    iso = db._utc_now()
    await run_in_threadpool(db.set_job_catalog_confirmed, job_id, iso)
    record = job_manager.jobs.get(job_id)
    if record is not None:
        record.catalog_confirmed_at = iso
        video_paths = list(record.video_paths) or video_paths_from_meta(record.directory)
        if video_paths:
            await run_in_threadpool(
                maybe_purge_job_media,
                record.directory,
                video_paths,
            )
            record.video_paths = []
    else:
        job_dir = Path(job["directory"])
        video_paths = video_paths_from_meta(job_dir)
        if video_paths:
            await run_in_threadpool(maybe_purge_job_media, job_dir, video_paths)
    return {"job_id": job_id, "catalog_confirmed_at": iso}


@app.get("/jobs/{job_id}/report")
async def get_job_report(job_id: str) -> CatalogReportResponse:
    payload = await run_in_threadpool(build_catalog_report, job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    if not payload.get("confirmed"):
        raise HTTPException(
            status_code=409,
            detail="Confirma el catálogo antes de ver el informe.",
        )
    return CatalogReportResponse.model_validate(payload)


@app.get("/jobs/{job_id}/export.csv")
async def export_job_csv(job_id: str):
    try:
        result = job_manager.get_result(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Job no encontrado o sin resultados exportables.",
        ) from exc

    payload = _build_export_csv(job_id, result)
    filename = f"analisis-{job_id}.csv"
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/jobs/{job_id}/export.xlsx")
async def export_job_xlsx(job_id: str):
    try:
        record = job_manager.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job no encontrado.") from exc

    report_path = record.directory / "informe.xlsx"
    if record.result and record.result.report_xlsx_path:
        report_path = Path(record.result.report_xlsx_path)
    if not report_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="El informe Excel todavía no está disponible.",
        )
    payload = report_path.read_bytes()
    filename = f"informe-{job_id}.xlsx"
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
