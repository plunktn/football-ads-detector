"""Turn one-Hz LED observations into continuous exposure segments."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..schemas import BrandResult, SegmentResult
from .hysteresis import apply_hysteresis


@dataclass(frozen=True)
class FrameObservation:
    half: str
    time_seconds: float
    frame_idx: int
    detected_brand_ids: frozenset[str]
    skipped: bool


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _aggregate_one_half(
    observations: Sequence[FrameObservation],
    brand_id: str,
    brand_name: str,
) -> BrandResult:
    states = [
        None if observation.skipped else brand_id in observation.detected_brand_ids
        for observation in observations
    ]
    states = apply_hysteresis(states)

    segments: list[SegmentResult] = []
    start_index: int | None = None
    last_true_index: int | None = None
    false_streak = 0
    skipped_streak = 0

    def close_segment() -> None:
        nonlocal start_index, last_true_index, false_streak, skipped_streak
        if start_index is None or last_true_index is None:
            start_index = None
            last_true_index = None
            false_streak = 0
            skipped_streak = 0
            return

        true_count = sum(state is True for state in states[start_index : last_true_index + 1])
        first = observations[start_index]
        last = observations[last_true_index]
        segments.append(
            SegmentResult(
                half=first.half,
                clock_start=_clock(first.time_seconds - observations[0].time_seconds),
                clock_end=_clock(
                    last.time_seconds - observations[0].time_seconds + 1.0
                ),
                video_seconds_start=first.time_seconds,
                video_seconds_end=last.time_seconds + 1.0,
                start_frame=first.frame_idx,
                end_frame=last.frame_idx,
                duration_seconds=true_count,
            )
        )
        start_index = None
        last_true_index = None
        false_streak = 0
        skipped_streak = 0

    for index, state in enumerate(states):
        if state is True:
            if start_index is None:
                start_index = index
            last_true_index = index
            false_streak = 0
            skipped_streak = 0
        elif state is None:
            skipped_streak += 1
            false_streak = 0
            # One or two skipped seconds leave the open segment alive. The
            # third skipped second closes it without counting unknown frames.
            if start_index is not None and skipped_streak >= 3:
                close_segment()
        else:
            false_streak += 1
            skipped_streak = 0
            # One False is tolerated; two consecutive False samples close.
            if start_index is not None and false_streak >= 2:
                close_segment()

    close_segment()
    total_seconds = sum(segment.duration_seconds for segment in segments)
    start_frames = [segment.start_frame for segment in segments]
    return BrandResult(
        brand_id=brand_id,
        name=brand_name,
        appearances=len(segments),
        total_seconds=total_seconds,
        minutes=total_seconds // 60,
        seconds=total_seconds % 60,
        start_frames=start_frames,
        segments=segments,
    )


def aggregate_observations(
    observations: Iterable[FrameObservation],
    brands: Sequence[tuple[str, str]],
) -> list[BrandResult]:
    """Aggregate every configured brand, retaining zero-result rows."""
    by_half: dict[str, list[FrameObservation]] = {}
    for observation in observations:
        by_half.setdefault(observation.half, []).append(observation)

    results: list[BrandResult] = []
    for brand_id, brand_name in brands:
        per_half = [
            _aggregate_one_half(half_observations, brand_id, brand_name)
            for half_observations in by_half.values()
            if half_observations
        ]
        segments = [segment for result in per_half for segment in result.segments]
        total_seconds = sum(segment.duration_seconds for segment in segments)
        results.append(
            BrandResult(
                brand_id=brand_id,
                name=brand_name,
                appearances=len(segments),
                total_seconds=total_seconds,
                minutes=total_seconds // 60,
                seconds=total_seconds % 60,
                start_frames=[segment.start_frame for segment in segments],
                segments=segments,
            )
        )
    return results
