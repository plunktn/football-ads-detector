"""LED catalog classification and persistence after analysis."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .. import db
from .aggregate import FrameObservation
from .brands import PreparedBrand
from .phash import dhash_from_path, order_by_similarity


def classify_led_frame(
    *,
    skipped: bool,
    has_crop: bool,
    ocr_text: str,
    detected_brand_ids: set[str],
    ambiguous_brand_ids: set[str],
) -> tuple[str, str | None] | None:
    """Return (machine_label, brand_id) or None if the frame should not be stored."""
    if skipped or not has_crop:
        return None
    if detected_brand_ids:
        brand_id = sorted(detected_brand_ids)[0]
        return ("positive", brand_id)
    if ambiguous_brand_ids or ocr_text.strip():
        return ("attention", None)
    return ("empty", None)


def persist_catalog(
    job_id: str,
    directory: str | Path,
    observations: Sequence[FrameObservation],
    prepared_brands: Sequence[PreparedBrand] | Sequence[Any] | None = None,
) -> int:
    """Insert catalog rows for LED observations. Returns discarded_count."""
    del prepared_brands  # ids already live on each observation
    job_dir = Path(directory)
    rows: list[dict[str, Any]] = []
    discarded = 0
    for observation in observations:
        if observation.tipo_panel == "FIXED_PRINT":
            continue
        classified = classify_led_frame(
            skipped=observation.skipped,
            has_crop=bool(observation.crop_relpath),
            ocr_text=observation.ocr_text,
            detected_brand_ids=set(observation.detected_brand_ids),
            ambiguous_brand_ids=set(observation.ambiguous_brand_ids),
        )
        if classified is None:
            discarded += 1
            continue
        label, brand_id = classified
        visual_hash: str | None = None
        if observation.crop_relpath:
            visual_hash = dhash_from_path(job_dir / observation.crop_relpath)
        rows.append(
            {
                "half": observation.half,
                "frame_idx": observation.frame_idx,
                "time_seconds": observation.time_seconds,
                "zone_id": observation.zone_id,
                "posicion": observation.posicion,
                "crop_relpath": observation.crop_relpath,
                "context_relpath": observation.context_relpath,
                "visual_hash": visual_hash,
                "ocr_text": observation.ocr_text,
                "machine_label": label,
                "brand_id": brand_id,
                "machine_brand_ids_json": json.dumps(
                    sorted(observation.detected_brand_ids),
                    ensure_ascii=False,
                ),
                "user_verdict": None,
            }
        )
    db.insert_job_frames(job_id, rows)
    db.set_job_catalog_discarded_count(job_id, discarded)
    return discarded


def _frame_public(job_id: str, row: dict[str, Any]) -> dict[str, Any]:
    frame_id = row["id"]
    has_context = bool(row.get("context_relpath"))
    image_url = f"/jobs/{job_id}/catalog/frames/{frame_id}/image"
    crop_url = f"/jobs/{job_id}/catalog/frames/{frame_id}/image?kind=crop"
    public = {
        "id": frame_id,
        "half": row["half"],
        "frame_idx": row["frame_idx"],
        "time_seconds": row["time_seconds"],
        "zone_id": row["zone_id"],
        "posicion": row["posicion"],
        "ocr_text": row["ocr_text"] or "",
        "machine_label": row["machine_label"],
        "brand_id": row["brand_id"],
        "user_verdict": row["user_verdict"],
        "image_url": image_url,
        "crop_image_url": crop_url if has_context or row.get("crop_relpath") else None,
        "has_context": has_context,
        "visual_hash": row.get("visual_hash"),
    }
    if "similarity_group" in row:
        public["similarity_group"] = row["similarity_group"]
    return public


def _ensure_visual_hash(job_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    if row.get("visual_hash"):
        return row
    relpath = row.get("crop_relpath")
    if not relpath:
        return row
    digest = dhash_from_path(job_dir / relpath)
    if digest:
        enriched = dict(row)
        enriched["visual_hash"] = digest
        return enriched
    return row


def build_catalog_payload(job_id: str) -> dict[str, Any] | None:
    job = db.get_job_row(job_id)
    if job is None:
        return None
    confirmed = job["catalog_confirmed_at"] if "catalog_confirmed_at" in job.keys() else None
    discarded = 0
    if "catalog_discarded_count" in job.keys() and job["catalog_discarded_count"] is not None:
        discarded = int(job["catalog_discarded_count"])

    job_dir = Path(job["directory"])
    library = {brand["id"]: brand for brand in db.list_brands()}
    brand_frames: dict[str, list[dict[str, Any]]] = {}
    attention_raw: list[dict[str, Any]] = []
    empty_raw: list[dict[str, Any]] = []

    for row in db.list_job_frames(job_id):
        enriched = _ensure_visual_hash(job_dir, row)
        public = _frame_public(job_id, enriched)
        verdict = row.get("user_verdict")
        brand_id = row.get("brand_id")
        if brand_id and verdict != "false_positive":
            brand_frames.setdefault(brand_id, []).append(public)
            continue
        if verdict == "false_positive" or row.get("machine_label") == "attention":
            attention_raw.append(public)
        elif row.get("machine_label") == "empty":
            empty_raw.append(public)
        else:
            attention_raw.append(public)

    attention = order_by_similarity(attention_raw)
    empty = order_by_similarity(empty_raw)

    brands_out: list[dict[str, Any]] = []
    for brand_id, frames in brand_frames.items():
        info = library.get(brand_id) or db.get_brand(brand_id)
        name = (info or {}).get("nombre") or brand_id
        brands_out.append({"brand_id": brand_id, "name": name, "frames": frames})
    brands_out.sort(key=lambda item: str(item["name"]).lower())

    positives = sum(len(item["frames"]) for item in brands_out)
    return {
        "job_id": job_id,
        "catalog_confirmed_at": confirmed,
        "discarded_count": discarded,
        "brands": brands_out,
        "attention": attention,
        "empty": empty,
        "progress": {
            "positives": positives,
            "attention": len(attention),
            "empty": len(empty),
            "confirmed": confirmed is not None,
        },
    }
