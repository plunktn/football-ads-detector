"""Synchronous one-FPS orchestration for the video analysis pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from ..domain.stadium import CameraProfile
from ..exceptions import JobCancelled
from ..schemas import BrandInput, BrandResult, DoubtfulSegment, Kickoff, parse_duration_seconds
from .aggregate import FrameObservation, aggregate_led_observations, aggregate_observations
from .doubtful import (
    aggregate_unmeasurable,
    as_public_segment,
    covers_from_segments,
    half_origins,
)
from .led_timing import load_led_timing
from .brands import match_brand_ids, match_fixed_brand_ids, prepare_brands
from .ocr import read_led_hits
from .playlist import PlaylistSlot, slots_for_verify
from .roi import DebugCropWriter
from .stages import classify_shot, locate_zones
from .verify import (
    _brand_id_for,
    hit_rate as compliance_hit_rate,
    to_compliance_row,
    verify_slot_from_observations,
    verify_slot_in_video,
)
from .video import VideoInfo, get_video_info, read_frame_at_seconds


logger = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 1.0
FALLBACK_FIRST_HALF_SECONDS = 47 * 60


@dataclass(frozen=True)
class AnalysisWindow:
    path: Path
    half: str
    start_seconds: float
    end_seconds: float
    sample_interval: float = 1.0

    @property
    def sample_count(self) -> int:
        step = self.sample_interval if self.sample_interval > 0 else 1.0
        return max(0, int((self.end_seconds - self.start_seconds - 1e-9) // step) + 1)


@dataclass(frozen=True)
class AnalysisUpdate:
    half: str
    match_seconds: float
    frame_idx: int
    processed_samples: int
    total_samples: int
    partial_brands: list[BrandResult]
    observation_snapshot: tuple[FrameObservation, ...] | None = None


def _write_jpeg(
    path: Path,
    image_bgr,
    *,
    max_width: int | None = None,
    quality: int = 75,
) -> bool:
    out = image_bgr
    if max_width is not None and out.shape[1] > max_width:
        scale = max_width / float(out.shape[1])
        out = cv2.resize(
            out,
            (max_width, max(1, int(round(out.shape[0] * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(
        cv2.imwrite(
            str(path),
            out,
            [int(cv2.IMWRITE_JPEG_QUALITY), quality],
        )
    )


def save_job_preview_frame(video_path: Path, dest: Path, at_seconds: float = 30.0) -> bool:
    """Grab one broadcast still so the UI is not empty during kickoff."""
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            return False
        info = get_video_info(video_path)
        t = min(max(0.0, at_seconds), max(0.0, info.duration_seconds - 0.5))
        ok, frame, _ = read_frame_at_seconds(cap, t)
        if not ok or frame is None:
            ok, frame = cap.read()
        if not ok or frame is None:
            return False
        return _write_jpeg(dest, frame, max_width=960, quality=70)
    finally:
        cap.release()


@dataclass(frozen=True)
class DoubtfulObservation:
    half: str
    time_seconds: float
    frame_idx: int
    reason: str
    ocr_text: str = ""
    zone_id: str | None = None
    shot: str | None = None
    crop_relpath: str | None = None


@dataclass(frozen=True)
class AnalysisOutput:
    analyzed_seconds: int
    brands: list[BrandResult]
    fixed_brands: list[BrandResult] = field(default_factory=list)
    compliance: list = field(default_factory=list)
    hit_rate: float | None = None
    observations: list[FrameObservation] = field(default_factory=list)
    doubtful: list[DoubtfulObservation] = field(default_factory=list)
    doubtful_segments: list[DoubtfulSegment] = field(default_factory=list)
    halves: tuple[str, ...] = ()


def _bounded_end(info: VideoInfo, start: float, duration: float | None) -> float:
    if start >= info.duration_seconds:
        return start
    if duration is None:
        return info.duration_seconds
    return min(info.duration_seconds, start + duration)


def build_analysis_windows(
    video_paths: Sequence[str | Path],
    *,
    mode: str,
    duration_mode: str,
    kickoff: Kickoff,
    sample_interval: float = 1.0,
) -> list[AnalysisWindow]:
    """Build the exact video ranges allowed by the selected duration mode."""
    if not video_paths:
        return []

    duration = parse_duration_seconds(duration_mode)
    is_full = duration is None
    paths = [Path(path) for path in video_paths]
    infos = [get_video_info(path) for path in paths]
    first_start = max(0.0, kickoff.first_half_video_seconds)
    step = sample_interval if sample_interval > 0 else 1.0
    windows: list[AnalysisWindow] = []

    if mode == "split" and len(paths) >= 2:
        first_end = _bounded_end(infos[0], first_start, duration)
        windows.append(
            AnalysisWindow(paths[0], "1T", first_start, first_end, step)
        )
        if is_full:
            second_start = max(0.0, kickoff.second_half_video_seconds or 0.0)
            second_end = _bounded_end(infos[1], second_start, None)
            windows.append(
                AnalysisWindow(paths[1], "2T", second_start, second_end, step)
            )
        return [window for window in windows if window.end_seconds > window.start_seconds]

    first_end: float
    second_start = kickoff.second_half_video_seconds
    if is_full:
        if second_start is not None and second_start > first_start:
            first_end = min(infos[0].duration_seconds, second_start)
        else:
            # Without a detected 2T reset, avoid processing an unlimited
            # pre-match/halftime recording. The plan's fallback is 45:00 plus
            # a small allowance for stoppage time.
            first_end = _bounded_end(
                infos[0], first_start, FALLBACK_FIRST_HALF_SECONDS
            )
    else:
        first_end = _bounded_end(infos[0], first_start, duration)
    windows.append(AnalysisWindow(paths[0], "1T", first_start, first_end, step))

    if is_full and second_start is not None and second_start > first_start:
        second_end = _bounded_end(infos[0], second_start, None)
        windows.append(
            AnalysisWindow(paths[0], "2T", second_start, second_end, step)
        )

    return [window for window in windows if window.end_seconds > window.start_seconds]


def halves_of(windows: Sequence[AnalysisWindow]) -> tuple[str, ...]:
    """Half labels that actually receive samples, in window order."""
    seen: list[str] = []
    for window in windows:
        if window.half not in seen:
            seen.append(window.half)
    return tuple(seen)


def _brand_pairs(brands: Sequence[BrandInput]) -> list[tuple[str, str]]:
    prepared = prepare_brands(list(brands))
    return [(brand.id, brand.name) for brand in prepared]


def _annotate_panel_kinds(
    led_brands: list[BrandResult],
    fixed_brands: list[BrandResult],
) -> tuple[list[BrandResult], list[BrandResult]]:
    led_hits = {brand.brand_id for brand in led_brands if brand.appearances > 0}
    fixed_hits = {brand.brand_id for brand in fixed_brands if brand.appearances > 0}
    annotated_led = []
    for brand in led_brands:
        if brand.brand_id in led_hits and brand.brand_id in fixed_hits:
            kind = "AMBAS"
        elif brand.brand_id in led_hits:
            kind = "LED"
        elif brand.brand_id in fixed_hits:
            kind = "FIJA"
        else:
            kind = None
        annotated_led.append(brand.model_copy(update={"panel_kind": kind}))
    annotated_fixed = []
    for brand in fixed_brands:
        kind = "AMBAS" if brand.brand_id in led_hits else "FIJA"
        annotated_fixed.append(brand.model_copy(update={"panel_kind": kind}))
    return annotated_led, annotated_fixed


def run_analysis(
    video_paths: Sequence[str | Path],
    *,
    mode: str,
    duration_mode: str,
    kickoff: Kickoff,
    brands: Sequence[BrandInput],
    debug_dir: str | Path,
    on_update: Callable[[AnalysisUpdate], None] | None = None,
    camera_profile: CameraProfile | None = None,
    analysis_mode: str = "discovery",
    playlist_slots: Sequence[PlaylistSlot] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    include_fixed: bool = False,
    sample_fps: int = 1,
) -> AnalysisOutput:
    """Analyze selected windows at ``sample_fps`` samples per second.

    discovery: LED scan (+ optional fixed bands).
    playlist_verify: same scan, then hit/miss each 1T/2T playlist slot.
    Non-usable shots (close-up / bumper / wide) never add LED seconds.
    """
    if should_cancel is not None and should_cancel():
        raise JobCancelled("Detenido por el usuario")
    fps = max(1, int(sample_fps))
    sample_interval = 1.0 / float(fps)
    led_timing = load_led_timing()
    logger.info(
        "LED timing merge_gap=%.1fs on_confirm=%.1fs off_hold=%.1fs",
        led_timing.merge_gap_sec,
        led_timing.on_confirm_sec,
        led_timing.off_hold_sec,
    )
    windows = build_analysis_windows(
        video_paths,
        mode=mode,
        duration_mode=duration_mode,
        kickoff=kickoff,
        sample_interval=sample_interval,
    )
    total_samples = sum(window.sample_count for window in windows)
    prepared = prepare_brands(list(brands))
    brand_pairs = [(brand.id, brand.name) for brand in prepared]
    observations: list[FrameObservation] = []
    doubtful: list[DoubtfulObservation] = []
    debug_path = Path(debug_dir)
    debug_writer = DebugCropWriter(debug_path)
    catalog_dir = debug_path.parent / "catalog"
    processed = 0

    for window in windows:
        cap = cv2.VideoCapture(str(window.path))
        try:
            t = window.start_seconds
            while t < window.end_seconds - 1e-9:
                if should_cancel is not None and should_cancel():
                    raise JobCancelled("Detenido por el usuario")
                ok, frame, frame_idx = read_frame_at_seconds(cap, t)
                if not ok or frame is None:
                    logger.warning(
                        "Could not decode %s at %.1fs", window.path.name, t
                    )
                    t += sample_interval
                    continue

                shot = classify_shot(frame, camera_profile)
                located = locate_zones(
                    frame,
                    camera_profile,
                    shot,
                    include_fixed=include_fixed,
                )
                frame_observations: list[FrameObservation] = []
                for zone, roi in located:
                    if roi.skipped or roi.crop_bgr is None:
                        frame_observations.append(
                            FrameObservation(
                                half=window.half,
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
                        if zone.tipo_panel != "FIXED_PRINT":
                            doubtful.append(
                                DoubtfulObservation(
                                    half=window.half,
                                    time_seconds=t,
                                    frame_idx=frame_idx,
                                    reason=roi.reason or "roi_skipped",
                                    zone_id=zone.id,
                                    shot=str(shot),
                                )
                            )
                        continue
                    if zone.tipo_panel != "FIXED_PRINT":
                        debug_writer.maybe_save(frame_idx, roi)
                    ocr_hits = read_led_hits(roi.crop_bgr)
                    raw_text = " ".join(hit.text for hit in ocr_hits)
                    min_repeats = 1 if zone.tipo_panel == "FIXED_PRINT" else 2
                    strong = match_brand_ids(
                        raw_text,
                        prepared,
                        ocr_hits,
                        min_repeats=min_repeats,
                    )
                    # Template matcher is FIXED_PRINT only — never on LED crops.
                    if zone.tipo_panel == "FIXED_PRINT":
                        strong = strong | match_fixed_brand_ids(
                            roi.crop_bgr, list(brands)
                        )
                    weak: set[str] = set()
                    crop_relpath: str | None = None
                    context_relpath: str | None = None
                    if zone.tipo_panel != "FIXED_PRINT":
                        weak = match_brand_ids(
                            raw_text,
                            prepared,
                            ocr_hits,
                            min_repeats=1,
                        )
                        weak -= strong
                        catalog_dir.mkdir(parents=True, exist_ok=True)
                        if zone.id:
                            relpath = f"catalog/led_{frame_idx:06d}_{zone.id}.jpg"
                        else:
                            relpath = f"catalog/led_{frame_idx:06d}.jpg"
                        if _write_jpeg(
                            debug_path.parent / relpath,
                            roi.crop_bgr,
                            quality=85,
                        ):
                            crop_relpath = relpath
                        ctx_rel = f"catalog/ctx_{frame_idx:06d}.jpg"
                        ctx_path = debug_path.parent / ctx_rel
                        if ctx_path.is_file() or _write_jpeg(
                            ctx_path,
                            frame,
                            max_width=1280,
                            quality=72,
                        ):
                            context_relpath = ctx_rel
                        if weak and not strong:
                            doubtful.append(
                                DoubtfulObservation(
                                    half=window.half,
                                    time_seconds=t,
                                    frame_idx=frame_idx,
                                    reason="ambiguous_ocr",
                                    ocr_text=raw_text,
                                    zone_id=zone.id,
                                    shot=str(shot),
                                    crop_relpath=crop_relpath,
                                )
                            )
                    frame_observations.append(
                        FrameObservation(
                            half=window.half,
                            time_seconds=t,
                            frame_idx=frame_idx,
                            detected_brand_ids=frozenset(strong),
                            skipped=False,
                            zone_id=zone.id,
                            posicion=zone.posicion,
                            tipo_panel=zone.tipo_panel,
                            shot=shot,
                            ambiguous_brand_ids=frozenset(weak),
                            ocr_text=raw_text,
                            crop_relpath=crop_relpath,
                            context_relpath=context_relpath,
                        )
                    )
                if not frame_observations:
                    # CLOSEUP / GRAPHIC / WIDE / UNKNOWN → NO_EVIDENCE, no LED seconds.
                    frame_observations.append(
                        FrameObservation(
                            half=window.half,
                            time_seconds=t,
                            frame_idx=frame_idx,
                            detected_brand_ids=frozenset(),
                            skipped=True,
                            shot=shot,
                        )
                    )
                    doubtful.append(
                        DoubtfulObservation(
                            half=window.half,
                            time_seconds=t,
                            frame_idx=frame_idx,
                            reason=f"no_usable_led_plane:{shot}",
                            shot=str(shot),
                        )
                    )

                observations.extend(frame_observations)
                processed += 1
                if on_update is not None and (
                    processed == 1
                    or processed % 2 == 0
                    or processed == total_samples
                ):
                    led_partial = [
                        item
                        for item in observations
                        if item.tipo_panel != "FIXED_PRINT"
                    ]
                    flush_catalog = (
                        processed == 1
                        or processed % 8 == 0
                        or processed == total_samples
                    )
                    on_update(
                        AnalysisUpdate(
                            half=window.half,
                            match_seconds=max(0.0, t - window.start_seconds),
                            frame_idx=frame_idx,
                            processed_samples=processed,
                            total_samples=total_samples,
                            partial_brands=aggregate_led_observations(
                                led_partial,
                                brand_pairs,
                                sample_interval=sample_interval,
                                timing=led_timing,
                            ),
                            observation_snapshot=(
                                tuple(observations) if flush_catalog else None
                            ),
                        )
                    )
                t += sample_interval
        finally:
            cap.release()

    led_obs = [
        item for item in observations if item.tipo_panel != "FIXED_PRINT"
    ]
    fixed_obs = [
        item for item in observations if item.tipo_panel == "FIXED_PRINT"
    ]
    led_brands, fixed_brands = _annotate_panel_kinds(
        aggregate_led_observations(
            led_obs,
            brand_pairs,
            sample_interval=sample_interval,
            timing=led_timing,
        ),
        aggregate_observations(
            fixed_obs, brand_pairs, sample_interval=sample_interval
        ),
    )
    origins = half_origins(led_obs)
    measured_covers = [
        cover
        for brand in led_brands
        for cover in covers_from_segments(brand.segments)
    ]
    doubtful_segments = [
        DoubtfulSegment.model_validate(
            as_public_segment(
                interval,
                origin_seconds=origins.get(interval.half, 0.0),
            )
        )
        for interval in aggregate_unmeasurable(
            led_obs,
            sample_interval=sample_interval,
            timing=led_timing,
            covers=measured_covers,
        )
    ]

    compliance = []
    rate = None
    if analysis_mode == "playlist_verify" and playlist_slots:
        verify_slots = slots_for_verify(playlist_slots)
        video_by_half = {window.half: window.path for window in windows}
        duration_by_half: dict[str, float] = {}
        for window in windows:
            try:
                duration_by_half[window.half] = get_video_info(
                    window.path
                ).duration_seconds
            except ValueError:
                pass
        for slot in verify_slots:
            brand_id = _brand_id_for(slot, brands) or ""
            path = video_by_half.get(slot.period) or (
                video_paths[0] if video_paths else None
            )
            duration = duration_by_half.get(slot.period)
            if duration is None and path is not None:
                try:
                    duration = get_video_info(path).duration_seconds
                except ValueError:
                    duration = None
            result = verify_slot_from_observations(
                slot,
                observations,
                kickoff,
                brand_id,
                video_duration_sec=duration,
            )
            if result.status.value not in {"HIT", "PAST_EOF"}:
                if path is not None:
                    result = verify_slot_in_video(
                        path,
                        slot,
                        kickoff,
                        brands,
                        camera_profile=camera_profile,
                        debug_dir=Path(debug_dir) / "verify",
                        video_duration_sec=duration,
                    )
            compliance.append(to_compliance_row(result))
        rate = compliance_hit_rate(compliance)

    return AnalysisOutput(
        analyzed_seconds=processed,
        brands=led_brands,
        fixed_brands=fixed_brands,
        compliance=compliance,
        hit_rate=rate,
        observations=observations,
        doubtful=doubtful,
        doubtful_segments=doubtful_segments,
        halves=halves_of(windows),
    )
