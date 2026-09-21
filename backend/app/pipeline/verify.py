"""Verify playlist slots against a video window (1T/2T only)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2

from ..config.aliases import resolve_catalog_name
from ..domain.stadium import CameraProfile
from ..schemas import BrandInput, ComplianceRow, Kickoff, VerificationStatus
from .aggregate import FrameObservation
from .brands import match_brand_ids, match_fixed_brand_ids, prepare_brands
from .ocr import read_led_hits
from .playlist import PlaylistSlot
from .roi import DebugCropWriter
from .stages import ShotKind, classify_shot, locate_zones
from .video import get_video_info, read_frame_at_seconds


SAMPLE_INTERVAL_SECONDS = 1.0
HIT_TOLERANCE_SEC = 20.0
NEIGHBOR_SEARCH_SEC = 60.0

_USABLE_SHOTS = frozenset({ShotKind.WIDE_LED, ShotKind.LATERAL})


@dataclass(frozen=True)
class SlotVerification:
    slot: PlaylistSlot
    status: VerificationStatus
    observed_video_sec: float | None
    capture_path: str | None
    source: str | None
    brand_id: str
    delta_sec: float | None = None
    reason: str | None = None
    zone: str | None = None

    @property
    def hit(self) -> bool:
        return self.status == VerificationStatus.HIT


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


def scheduled_video_sec(slot: PlaylistSlot, kickoff: Kickoff) -> float | None:
    window = slot_video_window(slot, kickoff)
    if window is None:
        return None
    return window[0]


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


def _is_usable_observation(observation: FrameObservation) -> bool:
    if observation.shot in _USABLE_SHOTS and not observation.skipped:
        return True
    if observation.shot is None and not observation.skipped:
        # Legacy observations without shot: treat non-skipped as usable LED.
        return True
    return False


def _observations_in_range(
    observations: Sequence[FrameObservation],
    lo: float,
    hi: float,
) -> list[FrameObservation]:
    return [
        observation
        for observation in observations
        if lo <= observation.time_seconds < hi
    ]


def _find_brand_in_observations(
    observations: Sequence[FrameObservation],
    brand_id: str,
    lo: float,
    hi: float,
) -> FrameObservation | None:
    for observation in _observations_in_range(observations, lo, hi):
        if observation.skipped:
            continue
        if brand_id in observation.detected_brand_ids:
            return observation
    return None


def _find_ambiguous_in_observations(
    observations: Sequence[FrameObservation],
    brand_id: str,
    lo: float,
    hi: float,
) -> FrameObservation | None:
    for observation in _observations_in_range(observations, lo, hi):
        if observation.skipped:
            continue
        if brand_id in (observation.ambiguous_brand_ids or frozenset()):
            return observation
    return None


def _classify_from_observations(
    slot: PlaylistSlot,
    observations: Sequence[FrameObservation],
    kickoff: Kickoff,
    brand_id: str,
    *,
    video_duration_sec: float | None = None,
) -> SlotVerification:
    window = slot_video_window(slot, kickoff)
    if window is None:
        reason = (
            "missing_2t_origin"
            if slot.period == "2T"
            else "unsupported_period"
        )
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.NO_EVIDENCE,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            reason=reason,
        )

    lo, hi = window
    scheduled = lo
    if video_duration_sec is not None and scheduled > video_duration_sec:
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.PAST_EOF,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            delta_sec=None,
            reason=f"scheduled_video_sec={scheduled:.1f} > duration={video_duration_sec:.1f}",
        )

    in_window = _observations_in_range(observations, lo, hi)
    hit_obs = _find_brand_in_observations(observations, brand_id, lo, hi)
    if hit_obs is not None:
        delta = hit_obs.time_seconds - scheduled
        source = "fija" if hit_obs.tipo_panel == "FIXED_PRINT" else "led"
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.HIT,
            observed_video_sec=hit_obs.time_seconds,
            capture_path=None,
            source=source,
            brand_id=brand_id,
            delta_sec=delta,
            reason="brand_in_window",
            zone=hit_obs.zone_id,
        )

    ambiguous = _find_ambiguous_in_observations(observations, brand_id, lo, hi)
    if ambiguous is not None:
        delta = ambiguous.time_seconds - scheduled
        source = "fija" if ambiguous.tipo_panel == "FIXED_PRINT" else "led"
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.AMBIGUOUS,
            observed_video_sec=ambiguous.time_seconds,
            capture_path=None,
            source=source,
            brand_id=brand_id,
            delta_sec=delta,
            reason="weak_ocr_match",
            zone=ambiguous.zone_id,
        )

    neighbor_lo = max(0.0, scheduled - NEIGHBOR_SEARCH_SEC)
    neighbor_hi = scheduled + slot.duration_sec + NEIGHBOR_SEARCH_SEC
    neighbor = _find_brand_in_observations(
        observations, brand_id, neighbor_lo, neighbor_hi
    )
    if neighbor is not None:
        delta = neighbor.time_seconds - scheduled
        if abs(delta) > HIT_TOLERANCE_SEC:
            source = "fija" if neighbor.tipo_panel == "FIXED_PRINT" else "led"
            return SlotVerification(
                slot=slot,
                status=VerificationStatus.OFFSET,
                observed_video_sec=neighbor.time_seconds,
                capture_path=None,
                source=source,
                brand_id=brand_id,
                delta_sec=delta,
                reason=f"brand_outside_tolerance |Δ|={abs(delta):.1f}s",
                zone=neighbor.zone_id,
            )
        # Within ±20s but outside the scheduled duration window (edge case).
        source = "fija" if neighbor.tipo_panel == "FIXED_PRINT" else "led"
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.HIT,
            observed_video_sec=neighbor.time_seconds,
            capture_path=None,
            source=source,
            brand_id=brand_id,
            delta_sec=delta,
            reason="brand_within_tolerance",
            zone=neighbor.zone_id,
        )

    if not in_window:
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.NO_EVIDENCE,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            reason="no_samples_in_window",
        )

    usable = [obs for obs in in_window if _is_usable_observation(obs)]
    if not usable:
        shots = sorted({str(obs.shot) for obs in in_window if obs.shot})
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.NO_EVIDENCE,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            reason="no_usable_led_plane:" + ",".join(shots) if shots else "no_usable_led_plane",
        )

    return SlotVerification(
        slot=slot,
        status=VerificationStatus.MISS,
        observed_video_sec=None,
        capture_path=None,
        source=None,
        brand_id=brand_id,
        reason="usable_led_without_brand",
        zone=usable[0].zone_id,
    )


def verify_slot_from_observations(
    slot: PlaylistSlot,
    observations: Sequence[FrameObservation],
    kickoff: Kickoff,
    brand_id: str,
    *,
    video_duration_sec: float | None = None,
) -> SlotVerification:
    return _classify_from_observations(
        slot,
        observations,
        kickoff,
        brand_id,
        video_duration_sec=video_duration_sec,
    )


def verify_slot_in_video(
    video_path: str | Path,
    slot: PlaylistSlot,
    kickoff: Kickoff,
    brands: Sequence[BrandInput],
    *,
    camera_profile: CameraProfile | None = None,
    debug_dir: str | Path | None = None,
    video_duration_sec: float | None = None,
) -> SlotVerification:
    """Sample 1 fps inside the slot window (+ neighbors) and classify status."""
    brand_id = _brand_id_for(slot, brands)
    if brand_id is None:
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.MISS,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id="",
            reason="unknown_brand",
        )
    window = slot_video_window(slot, kickoff)
    if window is None:
        reason = (
            "missing_2t_origin"
            if slot.period == "2T"
            else "unsupported_period"
        )
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.NO_EVIDENCE,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            reason=reason,
        )

    duration = video_duration_sec
    if duration is None:
        try:
            duration = get_video_info(video_path).duration_seconds
        except ValueError:
            duration = None
    lo, hi = window
    if duration is not None and lo > duration:
        return SlotVerification(
            slot=slot,
            status=VerificationStatus.PAST_EOF,
            observed_video_sec=None,
            capture_path=None,
            source=None,
            brand_id=brand_id,
            reason=f"scheduled_video_sec={lo:.1f} > duration={duration:.1f}",
        )

    prepared = prepare_brands(list(brands))
    writer = DebugCropWriter(Path(debug_dir), every=1) if debug_dir else None
    observations: list[FrameObservation] = []
    capture: str | None = None
    capture_zone: str | None = None

    search_lo = max(0.0, lo - NEIGHBOR_SEARCH_SEC)
    search_hi = hi + NEIGHBOR_SEARCH_SEC
    if duration is not None:
        search_hi = min(search_hi, duration)

    cap = cv2.VideoCapture(str(video_path))
    try:
        t = search_lo
        while t < search_hi - 1e-9:
            ok, frame, frame_idx = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                shot = classify_shot(frame, camera_profile)
                located = locate_zones(
                    frame, camera_profile, shot, include_fixed=False
                )
                if not located:
                    observations.append(
                        FrameObservation(
                            half=slot.period,
                            time_seconds=t,
                            frame_idx=frame_idx,
                            detected_brand_ids=frozenset(),
                            skipped=True,
                            shot=shot,
                        )
                    )
                for zone, roi in located:
                    if roi.skipped or roi.crop_bgr is None:
                        observations.append(
                            FrameObservation(
                                half=slot.period,
                                time_seconds=t,
                                frame_idx=frame_idx,
                                detected_brand_ids=frozenset(),
                                skipped=True,
                                zone_id=zone.id,
                                posicion=zone.posicion,
                                tipo_panel=zone.tipo_panel,
                                shot=shot,
                            )
                        )
                        continue
                    ocr_hits = read_led_hits(roi.crop_bgr)
                    raw_text = " ".join(hit.text for hit in ocr_hits)
                    min_repeats = 1 if zone.tipo_panel == "FIXED_PRINT" else 2
                    strong = match_brand_ids(
                        raw_text,
                        prepared,
                        ocr_hits,
                        min_repeats=min_repeats,
                    )
                    if zone.tipo_panel == "FIXED_PRINT":
                        strong = strong | match_fixed_brand_ids(
                            roi.crop_bgr, list(brands)
                        )
                    weak = set()
                    if brand_id not in strong and zone.tipo_panel != "FIXED_PRINT":
                        weak = match_brand_ids(
                            raw_text,
                            prepared,
                            ocr_hits,
                            min_repeats=1,
                        )
                        weak -= strong
                    if brand_id in strong and writer is not None and lo <= t < hi:
                        writer.maybe_save(frame_idx, roi)
                        capture = str(Path(debug_dir) / f"led_{frame_idx:06d}.jpg")
                        capture_zone = zone.id
                    elif brand_id in weak and writer is not None and capture is None:
                        writer.maybe_save(frame_idx, roi)
                        capture = str(Path(debug_dir) / f"led_{frame_idx:06d}.jpg")
                        capture_zone = zone.id
                    observations.append(
                        FrameObservation(
                            half=slot.period,
                            time_seconds=t,
                            frame_idx=frame_idx,
                            detected_brand_ids=frozenset(strong),
                            skipped=False,
                            zone_id=zone.id,
                            posicion=zone.posicion,
                            tipo_panel=zone.tipo_panel,
                            shot=shot,
                            ambiguous_brand_ids=frozenset(weak),
                        )
                    )
            t += SAMPLE_INTERVAL_SECONDS
    finally:
        cap.release()

    result = _classify_from_observations(
        slot,
        observations,
        kickoff,
        brand_id,
        video_duration_sec=duration,
    )
    if capture is not None and result.capture_path is None:
        return SlotVerification(
            slot=result.slot,
            status=result.status,
            observed_video_sec=result.observed_video_sec,
            capture_path=capture,
            source=result.source,
            brand_id=result.brand_id,
            delta_sec=result.delta_sec,
            reason=result.reason,
            zone=result.zone or capture_zone,
        )
    return result


def to_compliance_row(result: SlotVerification) -> ComplianceRow:
    return ComplianceRow(
        brand=result.slot.brand,
        period=result.slot.period,
        scheduled_start_sec=result.slot.start_sec,
        duration_sec=result.slot.duration_sec,
        status=result.status,
        delta_sec=result.delta_sec,
        reason=result.reason,
        observed_video_sec=result.observed_video_sec,
        capture_path=result.capture_path,
        source=result.source,
        zone=result.zone,
    )


def hit_rate(rows: Sequence[ComplianceRow]) -> float | None:
    """HIT / (HIT + MISS). Doubtful and PAST_EOF excluded from denominator."""
    decisive = [
        row
        for row in rows
        if row.status in (VerificationStatus.HIT, VerificationStatus.MISS)
    ]
    if not decisive:
        return None
    return sum(1 for row in decisive if row.status == VerificationStatus.HIT) / len(
        decisive
    )
