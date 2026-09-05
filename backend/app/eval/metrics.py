"""Pure interval metrics for pipeline evaluation (no video I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Interval:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(
                f"Interval end ({self.end}) must be >= start ({self.start})"
            )


def interval_seconds(intervals: Sequence[Interval]) -> float:
    """Total seconds covered by intervals (overlaps counted separately)."""
    return sum(max(0.0, interval.end - interval.start) for interval in intervals)


def merge_intervals(intervals: Sequence[Interval]) -> list[Interval]:
    """Merge overlapping or adjacent intervals."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    merged: list[Interval] = [ordered[0]]
    for interval in ordered[1:]:
        last = merged[-1]
        if interval.start <= last.end:
            merged[-1] = Interval(last.start, max(last.end, interval.end))
        else:
            merged.append(interval)
    return merged


def _pairwise_overlap(a: Interval, b: Interval) -> float:
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    return max(0.0, end - start)


def overlap_seconds(
    predicted: Sequence[Interval],
    ground_truth: Sequence[Interval],
) -> float:
    """Seconds where predicted and ground-truth intervals overlap."""
    if not predicted or not ground_truth:
        return 0.0
    total = 0.0
    for pred in predicted:
        for gt in ground_truth:
            total += _pairwise_overlap(pred, gt)
    return total


def compute_brand_metrics(
    predicted: Sequence[Interval],
    ground_truth: Sequence[Interval],
) -> dict[str, float]:
    """Compute TP overlap, precision, recall, and absolute total error."""
    tp = overlap_seconds(predicted, ground_truth)
    predicted_total = interval_seconds(predicted)
    gt_total = interval_seconds(ground_truth)
    precision = tp / predicted_total if predicted_total > 0 else 0.0
    recall = tp / gt_total if gt_total > 0 else 0.0
    error_s = abs(predicted_total - gt_total)
    return {
        "true_positive_seconds": tp,
        "predicted_seconds": predicted_total,
        "gt_seconds": gt_total,
        "precision": precision,
        "recall": recall,
        "error_s": error_s,
    }


def aggregate_brand_totals(
    per_clip: Sequence[dict[str, float]],
) -> dict[str, float]:
    """Micro-average metrics from per-clip totals (sum TP and denominators)."""
    tp = sum(item["true_positive_seconds"] for item in per_clip)
    predicted_total = sum(item["predicted_seconds"] for item in per_clip)
    gt_total = sum(item["gt_seconds"] for item in per_clip)
    precision = tp / predicted_total if predicted_total > 0 else 0.0
    recall = tp / gt_total if gt_total > 0 else 0.0
    error_s = abs(predicted_total - gt_total)
    return {
        "true_positive_seconds": tp,
        "predicted_seconds": predicted_total,
        "gt_seconds": gt_total,
        "precision": precision,
        "recall": recall,
        "error_s": error_s,
    }


def round_metrics(metrics: dict[str, float], *, places: int = 4) -> dict[str, float]:
    """Round float values for reproducible baseline output."""
    return {
        key: float(round(float(value), places))
        for key, value in sorted(metrics.items())
    }
