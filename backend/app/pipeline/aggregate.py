"""Turn sampled LED observations into continuous exposure segments."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import ceil

from ..schemas import BrandResult, SegmentResult
from .hysteresis import DEFAULT_MAX_GAP_SAMPLES, apply_hysteresis


# Merge contiguous same-brand segments in a half when the gap is ≤ this many seconds.
MERGE_GAP_SEC = 3.0


@dataclass(frozen=True)
class FrameObservation:
    half: str
    time_seconds: float
    frame_idx: int
    detected_brand_ids: frozenset[str]
    skipped: bool
    zone_id: str | None = None
    posicion: str | None = None
    tipo_panel: str | None = None
    shot: object | None = None
    ambiguous_brand_ids: frozenset[str] = field(default_factory=frozenset)
    ocr_text: str = ""
    crop_relpath: str | None = None
    context_relpath: str | None = None


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _gap_samples(merge_gap_sec: float, sample_interval: float) -> int:
    if sample_interval <= 0:
        return DEFAULT_MAX_GAP_SAMPLES
    return max(1, int(ceil(merge_gap_sec / sample_interval)))


def _merge_adjacent_segments(
    segments: list[SegmentResult],
    *,
    merge_gap_sec: float,
) -> list[SegmentResult]:
    """Join same-half segments when the video gap is within ``merge_gap_sec``."""
    if not segments:
        return []
    ordered = sorted(
        segments,
        key=lambda s: (s.half, s.video_seconds_start, s.video_seconds_end),
    )
    merged: list[SegmentResult] = [ordered[0]]
    for segment in ordered[1:]:
        prev = merged[-1]
        if segment.half != prev.half:
            merged.append(segment)
            continue
        gap = segment.video_seconds_start - prev.video_seconds_end
        if gap <= merge_gap_sec + 1e-9:
            # Span of merged window (includes filled gaps).
            duration = max(
                1,
                int(round(segment.video_seconds_end - prev.video_seconds_start)),
            )
            merged[-1] = SegmentResult(
                half=prev.half,
                clock_start=prev.clock_start,
                clock_end=segment.clock_end,
                video_seconds_start=prev.video_seconds_start,
                video_seconds_end=segment.video_seconds_end,
                start_frame=prev.start_frame,
                end_frame=segment.end_frame,
                duration_seconds=duration,
                zone_id=prev.zone_id or segment.zone_id,
                posicion=prev.posicion or segment.posicion,
                tipo_panel=prev.tipo_panel or segment.tipo_panel,
            )
        else:
            merged.append(segment)
    return merged


def _aggregate_one_half(
    observations: Sequence[FrameObservation],
    brand_id: str,
    brand_name: str,
    *,
    sample_interval: float = 1.0,
    merge_gap_sec: float = MERGE_GAP_SEC,
) -> BrandResult:
    states = [
        None if observation.skipped else brand_id in observation.detected_brand_ids
        for observation in observations
    ]
    max_gap = _gap_samples(merge_gap_sec, sample_interval)
    states = apply_hysteresis(states, max_gap_samples=max_gap)

    segments: list[SegmentResult] = []
    start_index: int | None = None
    last_true_index: int | None = None
    false_streak = 0
    skipped_streak = 0
    # Close only after more consecutive misses than the allowed merge gap.
    close_after = max_gap + 1

    def close_segment() -> None:
        nonlocal start_index, last_true_index, false_streak, skipped_streak
        if start_index is None or last_true_index is None:
            start_index = None
            last_true_index = None
            false_streak = 0
            skipped_streak = 0
            return

        first = observations[start_index]
        last = observations[last_true_index]
        # Span of the bridged run (hysteresis already filled interior gaps).
        duration = max(
            1,
            int(round(last.time_seconds - first.time_seconds + sample_interval)),
        )
        segments.append(
            SegmentResult(
                half=first.half,
                clock_start=_clock(first.time_seconds - observations[0].time_seconds),
                clock_end=_clock(
                    last.time_seconds - observations[0].time_seconds + sample_interval
                ),
                video_seconds_start=first.time_seconds,
                video_seconds_end=last.time_seconds + sample_interval,
                start_frame=first.frame_idx,
                end_frame=last.frame_idx,
                duration_seconds=duration,
                zone_id=first.zone_id,
                posicion=first.posicion,
                tipo_panel=first.tipo_panel,
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
            if start_index is not None and skipped_streak >= close_after:
                close_segment()
        else:
            false_streak += 1
            skipped_streak = 0
            if start_index is not None and false_streak >= close_after:
                close_segment()

    close_segment()
    segments = _merge_adjacent_segments(segments, merge_gap_sec=merge_gap_sec)
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
    *,
    sample_interval: float = 1.0,
    merge_gap_sec: float = MERGE_GAP_SEC,
) -> list[BrandResult]:
    """Aggregate every configured brand, retaining zero-result rows."""
    by_half: dict[str, list[FrameObservation]] = {}
    for observation in observations:
        by_half.setdefault(observation.half, []).append(observation)

    results: list[BrandResult] = []
    for brand_id, brand_name in brands:
        per_half = [
            _aggregate_one_half(
                half_observations,
                brand_id,
                brand_name,
                sample_interval=sample_interval,
                merge_gap_sec=merge_gap_sec,
            )
            for half_observations in by_half.values()
            if half_observations
        ]
        segments = [segment for result in per_half for segment in result.segments]
        segments = _merge_adjacent_segments(segments, merge_gap_sec=merge_gap_sec)
        total_seconds = sum(segment.duration_seconds for segment in segments)
        count_1t = sum(1 for segment in segments if segment.half == "1T")
        count_2t = sum(1 for segment in segments if segment.half == "2T")
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
                count_1t=count_1t,
                count_2t=count_2t,
            )
        )
    return results
