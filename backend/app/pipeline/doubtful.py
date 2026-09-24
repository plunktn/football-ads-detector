"""Illegible LED time becomes doubtful / unmeasurable ranges.

A usable board that OCR cannot read is not silent zero seconds. Those samples
merge with the same wall-clock gap as a measured LED run, then any overlap
with a measured brand interval is removed. What remains is excluded from the
±15–20% claim and shown for review.

Shots with no LED plane (close-up, bumper, wide) are not doubtful: the board
was not in frame. Fixed boards are ignored.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .aggregate import FrameObservation
from .led_timing import (
    DEFAULT_LED_MERGE_GAP_SEC,
    LedTiming,
    PresenceSample,
    load_led_timing,
    merge_presence,
    wall_clock_seconds,
)


REASON_LABELS = {
    "illegible_ocr": "no medible: OCR ilegible",
    "ambiguous_ocr": "no medible: confianza baja",
    "low_led_quality": "no medible: valla ilegible",
}


@dataclass(frozen=True)
class UnmeasurableInterval:
    half: str
    start_seconds: float
    end_seconds: float
    duration_seconds: int
    reason: str
    ocr_text: str = ""
    start_frame: int = 0
    end_frame: int = 0

    @property
    def reason_label(self) -> str:
        return REASON_LABELS.get(self.reason, "no medible")


def reason_label(reason: str) -> str:
    return REASON_LABELS.get(reason, "no medible")


def observation_unmeasurable_reason(observation: FrameObservation) -> str | None:
    """Why this sample cannot support a brand second, or None if it can."""
    if observation.tipo_panel == "FIXED_PRINT":
        return None
    if observation.detected_brand_ids:
        return None
    if observation.skipped:
        # A located zone whose crop failed is low quality. No zone means the
        # LED plane was not in frame (close-up / bumper / wide).
        if observation.zone_id:
            return "low_led_quality"
        return None
    if observation.ambiguous_brand_ids:
        return "ambiguous_ocr"
    if (observation.ocr_text or "").strip():
        return "illegible_ocr"
    return None


def _clock(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _cut_pieces(
    pieces: list[tuple[float, float]],
    cover_start: float,
    cover_end: float,
) -> list[tuple[float, float]]:
    if cover_end <= cover_start:
        return pieces
    kept: list[tuple[float, float]] = []
    for start, end in pieces:
        if cover_end <= start + 1e-9 or cover_start >= end - 1e-9:
            kept.append((start, end))
            continue
        if cover_start > start + 1e-9:
            kept.append((start, cover_start))
        if cover_end < end - 1e-9:
            kept.append((cover_end, end))
    return [(start, end) for start, end in kept if end - start > 1e-6]


def subtract_measured(
    intervals: Sequence[UnmeasurableInterval],
    covers: Sequence[tuple[str, float, float]],
) -> list[UnmeasurableInterval]:
    """Drop the part of each doubtful range already claimed by a brand run."""
    kept: list[UnmeasurableInterval] = []
    for interval in intervals:
        pieces = [(interval.start_seconds, interval.end_seconds)]
        for half, start, end in covers:
            if half != interval.half:
                continue
            pieces = _cut_pieces(pieces, start, end)
        for start, end in pieces:
            kept.append(
                UnmeasurableInterval(
                    half=interval.half,
                    start_seconds=start,
                    end_seconds=end,
                    duration_seconds=wall_clock_seconds(start, end),
                    reason=interval.reason,
                    ocr_text=interval.ocr_text,
                    start_frame=interval.start_frame,
                    end_frame=interval.end_frame,
                )
            )
    return [item for item in kept if item.duration_seconds > 0]


def _dominant_reason(reasons: Sequence[str]) -> str:
    if not reasons:
        return "illegible_ocr"
    return Counter(reasons).most_common(1)[0][0]


def aggregate_unmeasurable(
    observations: Sequence[FrameObservation],
    *,
    sample_interval: float = 1.0,
    timing: LedTiming | None = None,
    covers: Sequence[tuple[str, float, float]] = (),
) -> list[UnmeasurableInterval]:
    """Merge illegible LED samples into wall-clock ranges outside measured runs."""
    resolved = timing or load_led_timing()
    if sample_interval <= 0:
        sample_interval = 1.0

    grouped: dict[tuple[str, float], list[FrameObservation]] = {}
    for observation in observations:
        if observation.tipo_panel == "FIXED_PRINT":
            continue
        grouped.setdefault((observation.half, observation.time_seconds), []).append(
            observation
        )

    samples: list[PresenceSample] = []
    reasons: dict[int, str] = {}
    excerpts: dict[int, str] = {}
    index = 0
    for half, time_seconds in sorted(grouped, key=lambda key: (key[0], key[1])):
        rows = grouped[(half, time_seconds)]
        if any(row.detected_brand_ids for row in rows):
            primary = next(row for row in rows if row.detected_brand_ids)
            samples.append(
                PresenceSample(
                    half=half,
                    time_seconds=time_seconds,
                    present=False,
                    blocked=True,
                    frame_idx=primary.frame_idx,
                    source_ids=(index,),
                )
            )
            index += 1
            continue
        reason = None
        excerpt = ""
        primary = rows[0]
        for row in rows:
            candidate = observation_unmeasurable_reason(row)
            if candidate is None:
                continue
            reason = candidate
            primary = row
            text = (row.ocr_text or "").strip()
            if text:
                excerpt = text
                break
        if reason is None:
            samples.append(
                PresenceSample(
                    half=half,
                    time_seconds=time_seconds,
                    present=False,
                    blocked=False,
                    frame_idx=primary.frame_idx,
                    source_ids=(index,),
                )
            )
            index += 1
            continue
        reasons[index] = reason
        excerpts[index] = excerpt[:80]
        samples.append(
            PresenceSample(
                half=half,
                time_seconds=time_seconds,
                present=True,
                blocked=False,
                frame_idx=primary.frame_idx,
                source_ids=(index,),
            )
        )
        index += 1

    merged = merge_presence(
        samples,
        sample_interval=sample_interval,
        on_confirm_sec=resolved.on_confirm_sec,
        off_hold_sec=resolved.off_hold_sec,
        merge_gap_sec=resolved.merge_gap_sec,
    )
    intervals: list[UnmeasurableInterval] = []
    for piece in merged:
        piece_reasons = [reasons[source_id] for source_id in piece.source_ids if source_id in reasons]
        excerpt = next(
            (excerpts[source_id] for source_id in piece.source_ids if excerpts.get(source_id)),
            "",
        )
        intervals.append(
            UnmeasurableInterval(
                half=piece.half,
                start_seconds=piece.start_seconds,
                end_seconds=piece.end_seconds,
                duration_seconds=piece.duration_seconds,
                reason=_dominant_reason(piece_reasons),
                ocr_text=excerpt,
                start_frame=piece.start_frame,
                end_frame=piece.end_frame,
            )
        )
    return subtract_measured(intervals, covers)


def covers_from_segments(
    segments: Sequence[object],
) -> list[tuple[str, float, float]]:
    covers: list[tuple[str, float, float]] = []
    for segment in segments:
        half = getattr(segment, "half", None)
        start = getattr(segment, "video_seconds_start", None)
        end = getattr(segment, "video_seconds_end", None)
        if half is None and isinstance(segment, dict):
            half = segment.get("half")
            start = segment.get("video_seconds_start")
            end = segment.get("video_seconds_end")
        if half is None or start is None or end is None:
            continue
        covers.append((str(half), float(start), float(end)))
    return covers


def as_public_segment(
    interval: UnmeasurableInterval,
    *,
    origin_seconds: float = 0.0,
) -> dict[str, object]:
    return {
        "half": interval.half,
        "clock_start": _clock(interval.start_seconds - origin_seconds),
        "clock_end": _clock(interval.end_seconds - origin_seconds),
        "video_seconds_start": interval.start_seconds,
        "video_seconds_end": interval.end_seconds,
        "duration_seconds": interval.duration_seconds,
        "reason": interval.reason,
        "reason_label": interval.reason_label,
        "doubtful": True,
        "measurable": False,
        "ocr_text": interval.ocr_text,
        "start_frame": interval.start_frame,
        "end_frame": interval.end_frame,
    }


def union_intervals(
    intervals: Sequence[UnmeasurableInterval],
) -> list[UnmeasurableInterval]:
    """Merge overlapping same-half doubtful ranges so the report lists each once."""
    ordered = sorted(
        intervals,
        key=lambda item: (item.half, item.start_seconds, item.end_seconds),
    )
    merged: list[UnmeasurableInterval] = []
    for interval in ordered:
        if (
            merged
            and merged[-1].half == interval.half
            and interval.start_seconds <= merged[-1].end_seconds + 1e-6
        ):
            previous = merged[-1]
            end = max(previous.end_seconds, interval.end_seconds)
            longer = interval if interval.duration_seconds > previous.duration_seconds else previous
            merged[-1] = UnmeasurableInterval(
                half=previous.half,
                start_seconds=previous.start_seconds,
                end_seconds=end,
                duration_seconds=wall_clock_seconds(previous.start_seconds, end),
                reason=longer.reason,
                ocr_text=previous.ocr_text or interval.ocr_text,
                start_frame=previous.start_frame,
                end_frame=interval.end_frame,
            )
            continue
        merged.append(interval)
    return merged


def half_origins(observations: Sequence[FrameObservation]) -> dict[str, float]:
    origins: dict[str, float] = {}
    for observation in observations:
        current = origins.get(observation.half)
        if current is None or observation.time_seconds < current:
            origins[observation.half] = observation.time_seconds
    return origins


# Re-export the default so callers can document the shared gap.
MERGE_GAP_SEC = DEFAULT_LED_MERGE_GAP_SEC
