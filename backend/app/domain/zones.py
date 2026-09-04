"""Panel zone taxonomy for stadium advertising surfaces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Position = Literal[
    "LATERAL_MAIN",
    "LATERAL_OPPOSITE",
    "BEHIND_GOAL_LEFT",
    "BEHIND_GOAL_RIGHT",
    "CORNER_QUADRANT",
    "FIXED_BOARD_MIDFIELD",
    "CARPET_3D",
    "INTERVIEW_BACKDROP",
    "SCOREBOARD_OVERLAY",
]

PanelType = Literal[
    "LED_DYNAMIC",
    "LED_STATIC_CONTENT",
    "FIXED_PRINT",
    "VIRTUAL_OVERLAY",
    "PAINTED_GRASS",
    "MIXED",
]


class PanelZone(BaseModel):
    id: str
    posicion: Position
    tipo_panel: PanelType
    prioridad: int = 0
    geometria: dict | None = None


DEFAULT_PANEL_ZONES: list[PanelZone] = [
    PanelZone(
        id="led_lateral_main",
        posicion="LATERAL_MAIN",
        tipo_panel="LED_DYNAMIC",
        prioridad=1,
    ),
    PanelZone(
        id="fixed_second_row",
        posicion="FIXED_BOARD_MIDFIELD",
        tipo_panel="FIXED_PRINT",
        prioridad=2,
    ),
]
