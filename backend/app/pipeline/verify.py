"""Verify playlist slots against a video window (1T/2T only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2

from ..config.aliases import resolve_catalog_name
from ..domain.stadium import CameraProfile
from ..schemas import BrandInput, ComplianceRow, Kickoff
from .aggregate import FrameObservation
from .brands import match_brand_ids, match_fixed_brand_ids, prepare_brands
from .ocr import read_led_hits
from .playlist import PlaylistSlot
from .roi import DebugCropWriter
from .stages import classify_shot, locate_zones
from .video import read_frame_at_seconds


SAMPLE_INTERVAL_SECONDS = 1.0


@dataclass(frozen=True)
class SlotVerification:
    slot: PlaylistSlot
    hit: bool
    observed_video_sec: float | None
    capture_path: str | None
    source: str | None
    brand_id: str


def slot_video_window(
    slot: PlaylistSlot,
    kickoff: Kickoff,
) -> tuple[float, float] | None:
    """Map a match-clock slot onto video seconds using 1T/2T kickoff."""
    if slot.period == "1T":
        origin = kickoff.first_half_video_seconds
    elif slot.period == "2T":
        if kickoff.second_half_video_seconds is None:
            return None
        origin = kickoff.second_half_video_seconds
    else:
        return None
    start = origin + slot.start_sec
    return start, start + slot.duration_sec


def _brand_id_for(slot: PlaylistSlot, brands: Sequence[BrandInput]) -> str | None:
    catalog = resolve_catalog_name(slot.brand)
    compact_catalog = catalog.replace(" ", "").upper()
    for brand in brands:
        if brand.name.strip().upper() == catalog.upper():
            return brand.id
        compact_id = (brand.id or "").replace("-", "").upper()
        if compact_id == compact_catalog.replace("-", ""):
            return brand.id
        aliases = {item.strip().upper() for item in brand.aliases}
        if slot.brand.strip().upper() in aliases or catalog.upper() in aliases:
            return brand.id
    return None


def verify_slot_from_observations(
    slot: PlaylistSlot,
    observations: Sequence[FrameObservation],
    kickoff: Kickoff,
    brand_id: str,
) -> SlotVerification:
    window = slot_video_window(slot, kickoff)
    if window is None:
        return SlotVerification(slot, False, None, None, None, brand_id)
    lo, hi = window
    for observation in observations:
        if observation.skipped:
            continue
        if not (lo <= observation.time_seconds < hi):
            continue
        if brand_id in observation.detected_brand_ids:
            source = "fija" if observation.tipo_panel == "FIXED_PRINT" else "led"
            return SlotVerification(
                slot,
                True,
                observation.time_seconds,
                None,
                source,
                brand_id,
            )
    return SlotVerification(slot, False, None, None, None, brand_id)


def verify_slot_in_video(
    video_path: str | Path,
    slot: PlaylistSlot,
    kickoff: Kickoff,
    brands: Sequence[BrandInput],
    *,
    camera_profile: CameraProfile | None = None,
    debug_dir: str | Path | None = None,
) -> SlotVerification:
    """Sample 1 fps inside the slot window and look for the catalog brand."""
    brand_id = _brand_id_for(slot, brands)
    if brand_id is None:
        return SlotVerification(slot, False, None, None, None, "")
    window = slot_video_window(slot, kickoff)
    if window is None:
        return SlotVerification(slot, False, None, None, None, brand_id)

    prepared = prepare_brands(list(brands))
    lo, hi = window
    writer = DebugCropWriter(Path(debug_dir), every=1) if debug_dir else None
    capture: str | None = None
    cap = cv2.VideoCapture(str(video_path))
    try:
        t = lo
        while t < hi - 1e-9:
            ok, frame, frame_idx = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                shot = classify_shot(frame, camera_profile)
                located = locate_zones(frame, camera_profile, shot)
                for zone, roi in located:
                    if roi.skipped or roi.crop_bgr is None:
                        continue
                    ocr_hits = read_led_hits(roi.crop_bgr)
                    raw_text = " ".join(hit.text for hit in ocr_hits)
                    min_repeats = 1 if zone.tipo_panel == "FIXED_PRINT" else 2
                    detected = match_brand_ids(
                        raw_text,
                        prepared,
                        ocr_hits,
                        min_repeats=min_repeats,
                    ) | match_fixed_brand_ids(roi.crop_bgr, list(brands))
                    if brand_id in detected:
                        if writer is not None:
                            writer.maybe_save(frame_idx, roi)
                            capture = str(
                                Path(debug_dir) / f"led_{frame_idx:06d}.jpg"
                            )
                        source = "fija" if zone.tipo_panel == "FIXED_PRINT" else "led"
                        return SlotVerification(
                            slot, True, t, capture, source, brand_id
                        )
            t += SAMPLE_INTERVAL_SECONDS
    finally:
        cap.release()
    return SlotVerification(slot, False, None, None, None, brand_id)


def to_compliance_row(result: SlotVerification) -> ComplianceRow:
    return ComplianceRow(
        brand=result.slot.brand,
        period=result.slot.period,
        scheduled_start_sec=result.slot.start_sec,
        duration_sec=result.slot.duration_sec,
        hit=result.hit,
        observed_video_sec=result.observed_video_sec,
        capture_path=result.capture_path,
        source=result.source,
    )


def hit_rate(rows: Sequence[ComplianceRow]) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.hit) / len(rows)
