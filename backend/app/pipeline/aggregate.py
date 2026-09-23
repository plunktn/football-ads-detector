"""Turn sampled observations into continuous exposure segments.

LED jobs should call :func:`aggregate_led_observations`. That path bridges
short same-brand holes (default 8 s) and reports wall-clock duration.
:func:`aggregate_observations` keeps the shorter 3 s gap used for fixed
boards so a wide LED bridge cannot inflate lonas.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..schemas import BrandResult, SegmentResult
from .led_timing import (
    LedTiming,
    PresenceSample,
    load_led_timing,
    merge_presence,
)


# Fixed-board / generic caller gap. LED uses LedTiming (default 8 s).
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


def _brand_samples(
    observations: Sequence[FrameObservation],
    brand_id: str,
) -> list[PresenceSample]:
    samples: list[PresenceSample] = []
    for index, observation in enumerate(observations):
        if observation.skipped:
            present = False
            blocked = False
        else:
            present = brand_id in observation.detected_brand_ids
            blocked = (not present) and any(
                other != brand_id for other in observation.detected_brand_ids
            )
        samples.append(
            PresenceSample(
                half=observation.half,
                time_seconds=observation.time_seconds,
                present=present,
                blocked=blocked,
                frame_idx=observation.frame_idx,
                zone_id=observation.zone_id,
                posicion=observation.posicion,
                tipo_panel=observation.tipo_panel,
                source_ids=(index,),
            )
        )
    return samples


def _half_origins(observations: Sequence[FrameObservation]) -> dict[str, float]:
    origins: dict[str, float] = {}
    for observation in observations:
        current = origins.get(observation.half)
        if current is None or observation.time_seconds < current:
            origins[observation.half] = observation.time_seconds
    return origins


def aggregate_observations(
    observations: Iterable[FrameObservation],
    brands: Sequence[tuple[str, str]],
    *,
    sample_interval: float = 1.0,
    merge_gap_sec: float = MERGE_GAP_SEC,
    on_confirm_sec: float = 0.0,
    off_hold_sec: float | None = None,
) -> list[BrandResult]:
    """Aggregate every configured brand, retaining zero-result rows.

    ``merge_gap_sec`` is the hole that still counts as one appearance.
    ``off_hold_sec`` defaults to that same hole (off hysteresis).
    ``on_confirm_sec`` is how much consecutive positive time opens a run.
    Duration of a merged run is the wall-clock span, not the count of hits.
    Another brand's positive sample inside the hole prevents the merge.
    """
    observation_list = list(observations)
    hold = merge_gap_sec if off_hold_sec is None else off_hold_sec
    origins = _half_origins(observation_list)
    results: list[BrandResult] = []
    for brand_id, brand_name in brands:
        intervals = merge_presence(
            _brand_samples(observation_list, brand_id),
            sample_interval=sample_interval,
            on_confirm_sec=on_confirm_sec,
            off_hold_sec=hold,
            merge_gap_sec=merge_gap_sec,
        )
        segments: list[SegmentResult] = []
        for interval in intervals:
            origin = origins.get(interval.half, interval.start_seconds)
            segments.append(
                SegmentResult(
                    half=interval.half,
                    clock_start=_clock(interval.start_seconds - origin),
                    clock_end=_clock(interval.end_seconds - origin),
                    video_seconds_start=interval.start_seconds,
                    video_seconds_end=interval.end_seconds,
                    start_frame=interval.start_frame,
                    end_frame=interval.end_frame,
                    duration_seconds=interval.duration_seconds,
                    zone_id=interval.zone_id,
                    posicion=interval.posicion,
                    tipo_panel=interval.tipo_panel,
                )
            )
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
                count_1t=sum(1 for segment in segments if segment.half == "1T"),
                count_2t=sum(1 for segment in segments if segment.half == "2T"),
            )
        )
    return results


def aggregate_led_observations(
    observations: Iterable[FrameObservation],
    brands: Sequence[tuple[str, str]],
    *,
    sample_interval: float = 1.0,
    timing: LedTiming | None = None,
) -> list[BrandResult]:
    """LED-only aggregate. Uses :func:`load_led_timing` unless ``timing`` is passed.

    Fixed-board observations must keep going through :func:`aggregate_observations`
    so they stay on the 3 s gap.
    """
    resolved = timing or load_led_timing()
    return aggregate_observations(
        observations,
        brands,
        sample_interval=sample_interval,
        merge_gap_sec=resolved.merge_gap_sec,
        on_confirm_sec=resolved.on_confirm_sec,
        off_hold_sec=resolved.off_hold_sec,
    )
