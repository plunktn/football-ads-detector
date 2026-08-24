"""Temporal smoothing for one-Hz LED detections."""

from __future__ import annotations

from collections.abc import Sequence


DetectionState = bool | None


def apply_hysteresis(states: Sequence[DetectionState]) -> list[DetectionState]:
    """Fill a single false/unknown sample between two positive detections.

    ``None`` means that the ROI gate skipped the frame.  It is intentionally
    kept as unknown unless both neighbors are positive; a skipped frame is not
    evidence that a brand disappeared.
    """
    smoothed = list(states)
    for index in range(1, len(smoothed) - 1):
        if (
            smoothed[index] in (False, None)
            and smoothed[index - 1] is True
            and smoothed[index + 1] is True
        ):
            smoothed[index] = True
    return smoothed


def fill_single_second_gaps(states: Sequence[DetectionState]) -> list[DetectionState]:
    """Descriptive alias used by callers that do not need the implementation name."""
    return apply_hysteresis(states)
