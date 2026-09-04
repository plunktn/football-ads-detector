"""Route a classified shot to the matching panel-zone ROI extractors."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ...domain.stadium import CameraProfile
from ...domain.zones import DEFAULT_PANEL_ZONES, PanelZone
from ..roi import RoiResult, extract_fixed_banner_roi, extract_led_roi
from .shot_class import ShotKind

_SKIP_SHOTS = {ShotKind.WIDE, ShotKind.REPLAY_OR_GRAPHIC, ShotKind.UNKNOWN}
_OVERLAY_POSITIONS = {"SCOREBOARD_OVERLAY"}
_OVERLAY_TYPES = {"VIRTUAL_OVERLAY"}


def _effective_zones(profile: CameraProfile | None) -> Sequence[PanelZone]:
    if profile is None or not profile.panel_zones:
        return list(DEFAULT_PANEL_ZONES)
    return profile.panel_zones


def locate_zones(
    frame: np.ndarray,
    profile: CameraProfile | None,
    shot: ShotKind,
) -> list[tuple[PanelZone, RoiResult]]:
    """Return (zone, ROI) pairs that should be OCR'd for this shot.

    Replay/graphic and empty-WIDE frames skip localization. TV overlays
    (scoreboard, virtual banners) are never returned.
    """
    if shot in _SKIP_SHOTS:
        return []
    if shot != ShotKind.LATERAL:
        return []

    led_roi: RoiResult | None = None
    located: list[tuple[PanelZone, RoiResult]] = []
    for zone in _effective_zones(profile):
        if zone.posicion in _OVERLAY_POSITIONS or zone.tipo_panel in _OVERLAY_TYPES:
            continue
        if zone.posicion == "LATERAL_MAIN" and zone.tipo_panel != "FIXED_PRINT":
            if led_roi is None:
                led_roi = extract_led_roi(frame, profile=profile)
            located.append((zone, led_roi))
            continue
        if zone.tipo_panel == "FIXED_PRINT":
            if led_roi is None:
                led_roi = extract_led_roi(frame, profile=profile)
            located.append(
                (
                    zone,
                    extract_fixed_banner_roi(frame, profile=profile, led=led_roi),
                )
            )
    return located
