"""Heuristic broadcast shot classifier (grass geometry + touchline)."""

from __future__ import annotations

from enum import StrEnum

import numpy as np

from ...domain.stadium import CameraProfile
from ..roi import (
    _find_color_bands,
    _pick_led_band,
    _roi_params,
    _touchline_ys,
    grass_mask,
)


class ShotKind(StrEnum):
    LATERAL = "LATERAL"
    WIDE = "WIDE"
    BEHIND_GOAL = "BEHIND_GOAL"
    REPLAY_OR_GRAPHIC = "REPLAY_OR_GRAPHIC"
    UNKNOWN = "UNKNOWN"


def classify_shot(
    frame: np.ndarray,
    profile: CameraProfile | None = None,
) -> ShotKind:
    """Decide which panel localizers should run on this frame.

    Behind-goal is stubbed as UNKNOWN until dedicated heuristics exist.
    """
    if frame is None or frame.size == 0 or frame.ndim != 3:
        return ShotKind.UNKNOWN

    params = _roi_params(profile)
    mask = grass_mask(frame, profile)
    grass_ratio = float((mask > 0).mean())
    height = frame.shape[0]

    if grass_ratio < params.grass_min_ratio:
        # Studio/replay graphics have almost no turf; a faint grass hint
        # (close-up, tunnel, mixed overlay) stays UNKNOWN.
        if grass_ratio < params.grass_min_ratio * 0.5:
            return ShotKind.REPLAY_OR_GRAPHIC
        return ShotKind.UNKNOWN

    y_grass = _touchline_ys(mask, profile, params=params)
    if y_grass is not None:
        median_line = float(np.median(y_grass))
        if median_line < height / 3.0:
            bands = _find_color_bands(
                frame,
                y_min=int(height * params.led_band_y_top_frac),
                y_max=int(height * 0.90),
                profile=profile,
                params=params,
            )
            if _pick_led_band(
                bands,
                y_grass=y_grass,
                frame_h=height,
                profile=profile,
                params=params,
            ) is None:
                return ShotKind.WIDE

    return ShotKind.LATERAL
