"""Build a human-readable exposure report from the confirmed catalog.

Totals use the same LED merge as the commercial Excel: same brand, same half,
wall-clock span of the bridged interval. Positive frames of another brand
inside the hole keep the runs apart.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .. import db
from .led_timing import LedTiming, PresenceSample, load_led_timing, merge_presence


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _format_duration(total_seconds: int) -> str:
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    if minutes <= 0:
        return f"{seconds} s"
    return f"{minutes} min {seconds} s"


def _is_exposure_frame(row: dict[str, Any]) -> bool:
    if row.get("user_verdict") == "false_positive":
        return False
    brand_id = row.get("brand_id")
    if not brand_id:
        return False
    label = row.get("machine_label") or ""
    verdict = row.get("user_verdict")
    return label == "positive" or verdict == "assigned"


def _sample_interval_for_job(job: Any) -> float:
    directory = job["directory"] if "directory" in job.keys() else None
    if not directory:
        return 1.0
    meta_path = Path(directory) / "meta.json"
    if not meta_path.is_file():
        return 1.0
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        fps = float(meta.get("sample_fps") or 1)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return 1.0
    if fps <= 0:
        return 1.0
    return 1.0 / fps


def _presence_sample(row: dict[str, Any], *, present: bool, blocked: bool) -> PresenceSample:
    source_ids: tuple[int, ...] = ()
    if present and row.get("id") is not None:
        source_ids = (int(row["id"]),)
    return PresenceSample(
        half=str(row.get("half") or ""),
        time_seconds=float(row.get("time_seconds") or 0.0),
        present=present,
        blocked=blocked,
        frame_idx=int(row.get("frame_idx") or 0),
        zone_id=row.get("zone_id"),
        posicion=row.get("posicion"),
        source_ids=source_ids,
    )


def _public_frame(job_id: str, row: dict[str, Any]) -> dict[str, Any]:
    frame_id = int(row["id"])
    has_context = bool(row.get("context_relpath"))
    return {
        "id": frame_id,
        "half": row.get("half") or "",
        "frame_idx": int(row.get("frame_idx") or 0),
        "time_seconds": float(row.get("time_seconds") or 0.0),
        "posicion": row.get("posicion"),
        "ocr_text": row.get("ocr_text") or "",
        "image_url": f"/jobs/{job_id}/catalog/frames/{frame_id}/image",
        "crop_image_url": f"/jobs/{job_id}/catalog/frames/{frame_id}/image?kind=crop",
        "has_context": has_context,
    }


def build_catalog_report(
    job_id: str,
    *,
    timing: LedTiming | None = None,
    sample_interval: float | None = None,
) -> dict[str, Any] | None:
    """Return report payload or None if job missing. Requires confirmed catalog."""
    job = db.get_job_row(job_id)
    if job is None:
        return None

    confirmed = None
    if "catalog_confirmed_at" in job.keys():
        confirmed = job["catalog_confirmed_at"]

    library = {brand["id"]: brand for brand in db.list_brands()}
    by_brand: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in db.list_job_frames(job_id):
        if not _is_exposure_frame(row):
            continue
        by_brand[str(row["brand_id"])].append(row)

    resolved = timing or load_led_timing()
    if sample_interval is None:
        interval = _sample_interval_for_job(job)
    else:
        interval = sample_interval

    brands_out: list[dict[str, Any]] = []
    for brand_id, frames in by_brand.items():
        info = library.get(brand_id) or db.get_brand(brand_id)
        name = (info or {}).get("nombre") or brand_id
        samples = [_presence_sample(row, present=True, blocked=False) for row in frames]
        for other_id, other_frames in by_brand.items():
            if other_id == brand_id:
                continue
            samples.extend(
                _presence_sample(row, present=False, blocked=True) for row in other_frames
            )
        merged = merge_presence(
            samples,
            sample_interval=interval,
            on_confirm_sec=resolved.on_confirm_sec,
            off_hold_sec=resolved.off_hold_sec,
            merge_gap_sec=resolved.merge_gap_sec,
        )
        frame_by_id = {int(row["id"]): row for row in frames if row.get("id") is not None}
        segments_out: list[dict[str, Any]] = []
        for piece in merged:
            chunk = [
                frame_by_id[source_id]
                for source_id in piece.source_ids
                if source_id in frame_by_id
            ]
            if not chunk:
                chunk = [
                    row
                    for row in frames
                    if str(row.get("half") or "") == piece.half
                    and piece.start_seconds - 1e-6
                    <= float(row.get("time_seconds") or 0.0)
                    <= piece.last_sighting_seconds + 1e-6
                ]
            chunk.sort(
                key=lambda row: (
                    float(row.get("time_seconds") or 0.0),
                    int(row.get("frame_idx") or 0),
                )
            )
            if not chunk:
                continue
            first = chunk[0]
            sample = _public_frame(job_id, first)
            segments_out.append(
                {
                    "half": piece.half,
                    "clock_start": _clock(piece.start_seconds),
                    "clock_end": _clock(piece.end_seconds),
                    "video_seconds_start": piece.start_seconds,
                    "video_seconds_end": piece.end_seconds,
                    "duration_seconds": piece.duration_seconds,
                    "posicion": first.get("posicion"),
                    "frame_count": len(chunk),
                    "sample_frame": sample,
                    "frames": [_public_frame(job_id, item) for item in chunk],
                }
            )
        total_seconds = sum(int(seg["duration_seconds"]) for seg in segments_out)
        brands_out.append(
            {
                "brand_id": brand_id,
                "name": name,
                "appearances": len(segments_out),
                "total_seconds": total_seconds,
                "minutes": total_seconds // 60,
                "seconds": total_seconds % 60,
                "duration_label": _format_duration(total_seconds),
                "frame_count": len(frames),
                "count_1t": sum(1 for seg in segments_out if seg["half"] == "1T"),
                "count_2t": sum(1 for seg in segments_out if seg["half"] == "2T"),
                "segments": segments_out,
            }
        )

    brands_out.sort(key=lambda item: (-int(item["total_seconds"]), str(item["name"]).lower()))
    total_seconds = sum(int(item["total_seconds"]) for item in brands_out)
    total_appearances = sum(int(item["appearances"]) for item in brands_out)

    stadium_id = job["stadium_id"] if "stadium_id" in job.keys() else None
    analyzed = None
    # Prefer analyzed_seconds from result.json when present via get_job elsewhere;
    # report stays catalog-driven.
    return {
        "job_id": job_id,
        "catalog_confirmed_at": confirmed,
        "confirmed": confirmed is not None,
        "stadium_id": stadium_id,
        "created_at": job["created_at"] if "created_at" in job.keys() else None,
        "summary": {
            "brand_count": len(brands_out),
            "appearances": total_appearances,
            "total_seconds": total_seconds,
            "duration_label": _format_duration(total_seconds),
            "minutes": total_seconds // 60,
            "seconds": total_seconds % 60,
        },
        "brands": brands_out,
        "analyzed_seconds": analyzed,
    }
