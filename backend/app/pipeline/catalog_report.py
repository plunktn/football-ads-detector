"""Build a human-readable exposure report from the confirmed catalog."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import db


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


def _segment_frames(frames: list[dict[str, Any]], gap_seconds: float = 2.0) -> list[list[dict[str, Any]]]:
    if not frames:
        return []
    ordered = sorted(
        frames,
        key=lambda row: (row.get("half") or "", float(row.get("time_seconds") or 0.0), int(row.get("frame_idx") or 0)),
    )
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = [ordered[0]]
    for row in ordered[1:]:
        prev = current[-1]
        same_half = (row.get("half") or "") == (prev.get("half") or "")
        delta = float(row.get("time_seconds") or 0.0) - float(prev.get("time_seconds") or 0.0)
        if same_half and 0 <= delta <= gap_seconds:
            current.append(row)
            continue
        segments.append(current)
        current = [row]
    segments.append(current)
    return segments


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


def build_catalog_report(job_id: str) -> dict[str, Any] | None:
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

    brands_out: list[dict[str, Any]] = []
    for brand_id, frames in by_brand.items():
        info = library.get(brand_id) or db.get_brand(brand_id)
        name = (info or {}).get("nombre") or brand_id
        segments_out: list[dict[str, Any]] = []
        for chunk in _segment_frames(frames):
            first = chunk[0]
            last = chunk[-1]
            start = float(first.get("time_seconds") or 0.0)
            end = float(last.get("time_seconds") or 0.0)
            unique_seconds = {
                int(round(float(item.get("time_seconds") or 0.0))) for item in chunk
            }
            duration = max(1, len(unique_seconds))
            sample = _public_frame(job_id, first)
            segments_out.append(
                {
                    "half": first.get("half") or "",
                    "clock_start": _clock(start),
                    "clock_end": _clock(end),
                    "video_seconds_start": start,
                    "video_seconds_end": end,
                    "duration_seconds": duration,
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
