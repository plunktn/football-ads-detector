"""Synchronous one-FPS orchestration for the video analysis pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2

from ..schemas import BrandInput, BrandResult, Kickoff
from .aggregate import FrameObservation, aggregate_observations
from .brands import match_brand_ids, prepare_brands
from .ocr import read_led_text
from .roi import DebugCropWriter, extract_led_roi
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

    @property
    def sample_count(self) -> int:
        return max(0, int((self.end_seconds - self.start_seconds - 1e-9) // 1) + 1)


@dataclass(frozen=True)
class AnalysisUpdate:
    half: str
    match_seconds: float
    frame_idx: int
    processed_samples: int
    total_samples: int
    partial_brands: list[BrandResult]


@dataclass(frozen=True)
class AnalysisOutput:
    analyzed_seconds: int
    brands: list[BrandResult]


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
) -> list[AnalysisWindow]:
    """Build the exact video ranges allowed by the selected duration mode."""
    if not video_paths:
        return []

    duration = {"5min": 300.0, "10min": 600.0}.get(duration_mode)
    paths = [Path(path) for path in video_paths]
    infos = [get_video_info(path) for path in paths]
    first_start = max(0.0, kickoff.first_half_video_seconds)
    windows: list[AnalysisWindow] = []

    if mode == "split" and len(paths) >= 2:
        first_end = _bounded_end(infos[0], first_start, duration)
        windows.append(AnalysisWindow(paths[0], "1T", first_start, first_end))
        if duration_mode == "full":
            second_start = max(0.0, kickoff.second_half_video_seconds or 0.0)
            second_end = _bounded_end(infos[1], second_start, None)
            windows.append(AnalysisWindow(paths[1], "2T", second_start, second_end))
        return [window for window in windows if window.end_seconds > window.start_seconds]

    first_end: float
    second_start = kickoff.second_half_video_seconds
    if duration_mode == "full":
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
    windows.append(AnalysisWindow(paths[0], "1T", first_start, first_end))

    if duration_mode == "full" and second_start is not None and second_start > first_start:
        second_end = _bounded_end(infos[0], second_start, None)
        windows.append(AnalysisWindow(paths[0], "2T", second_start, second_end))

    return [window for window in windows if window.end_seconds > window.start_seconds]


def _brand_pairs(brands: Sequence[BrandInput]) -> list[tuple[str, str]]:
    prepared = prepare_brands(list(brands))
    return [(brand.id, brand.name) for brand in prepared]


def run_analysis(
    video_paths: Sequence[str | Path],
    *,
    mode: str,
    duration_mode: str,
    kickoff: Kickoff,
    brands: Sequence[BrandInput],
    debug_dir: str | Path,
    on_update: Callable[[AnalysisUpdate], None] | None = None,
) -> AnalysisOutput:
    """Analyze selected windows at one sample per second.

    This function is synchronous by design; the JobManager runs it in a worker
    thread so OpenCV and ONNX inference never block FastAPI's event loop.
    """
    windows = build_analysis_windows(
        video_paths,
        mode=mode,
        duration_mode=duration_mode,
        kickoff=kickoff,
    )
    total_samples = sum(window.sample_count for window in windows)
    prepared = prepare_brands(list(brands))
    brand_pairs = [(brand.id, brand.name) for brand in prepared]
    observations: list[FrameObservation] = []
    debug_writer = DebugCropWriter(Path(debug_dir))
    processed = 0

    for window in windows:
        cap = cv2.VideoCapture(str(window.path))
        try:
            t = window.start_seconds
            while t < window.end_seconds - 1e-9:
                ok, frame, frame_idx = read_frame_at_seconds(cap, t)
                if not ok or frame is None:
                    logger.warning(
                        "Could not decode %s at %.1fs", window.path.name, t
                    )
                    t += SAMPLE_INTERVAL_SECONDS
                    continue

                roi = extract_led_roi(frame)
                if roi.skipped or roi.crop_bgr is None:
                    observation = FrameObservation(
                        half=window.half,
                        time_seconds=t,
                        frame_idx=frame_idx,
                        detected_brand_ids=frozenset(),
                        skipped=True,
                    )
                else:
                    debug_writer.maybe_save(frame_idx, roi)
                    raw_text = read_led_text(roi.crop_bgr)
                    detected = frozenset(
                        match_brand_ids(
                            raw_text,
                            prepared,
                        )
                    )
                    observation = FrameObservation(
                        half=window.half,
                        time_seconds=t,
                        frame_idx=frame_idx,
                        detected_brand_ids=detected,
                        skipped=False,
                    )

                observations.append(observation)
                processed += 1
                if on_update is not None and (
                    processed == 1
                    or processed % 2 == 0
                    or processed == total_samples
                ):
                    on_update(
                        AnalysisUpdate(
                            half=window.half,
                            match_seconds=max(0.0, t - window.start_seconds),
                            frame_idx=frame_idx,
                            processed_samples=processed,
                            total_samples=total_samples,
                            partial_brands=aggregate_observations(
                                observations,
                                brand_pairs,
                            ),
                        )
                    )
                t += SAMPLE_INTERVAL_SECONDS
        finally:
            cap.release()

    return AnalysisOutput(
        analyzed_seconds=processed,
        brands=aggregate_observations(observations, brand_pairs),
    )
