"""Temporal smoothing for one-Hz (or denser) LED detections."""

from __future__ import annotations

from collections.abc import Sequence


DetectionState = bool | None

# Default: fill gaps of up to 3 samples between positives (≈3s at 1 fps).
DEFAULT_MAX_GAP_SAMPLES = 3


def apply_hysteresis(
    states: Sequence[DetectionState],
    *,
    max_gap_samples: int = DEFAULT_MAX_GAP_SAMPLES,
) -> list[DetectionState]:
    """Fill short false/unknown runs between two positive detections.

    ``None`` means the ROI gate skipped the frame. It is treated like a gap
    for bridging purposes so brief wide/close-up cuts do not split a LED run
    when the same brand is visible on both sides within ``max_gap_samples``.
    """
    if max_gap_samples < 1:
        return list(states)

    smoothed = list(states)
    n = len(smoothed)
    index = 0
    while index < n:
        if smoothed[index] is not True:
            index += 1
            continue
        # Find end of this True run.
        end = index
        while end + 1 < n and smoothed[end + 1] is True:
            end += 1
        # Look ahead for a gap of False/None then another True.
        gap_start = end + 1
        gap_end = gap_start
        while gap_end < n and smoothed[gap_end] in (False, None):
            gap_end += 1
        gap_len = gap_end - gap_start
        if (
            gap_len > 0
            and gap_len <= max_gap_samples
            and gap_end < n
            and smoothed[gap_end] is True
        ):
            for fill in range(gap_start, gap_end):
                smoothed[fill] = True
            index = gap_end
            continue
        index = end + 1
    return smoothed


def fill_single_second_gaps(states: Sequence[DetectionState]) -> list[DetectionState]:
    """Descriptive alias used by callers that do not need the implementation name."""
    return apply_hysteresis(states)
