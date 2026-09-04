"""Stadium and per-camera tuning profiles for ROI and scoreboard crops."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .zones import DEFAULT_PANEL_ZONES, PanelZone

CameraVariant = Literal["default", "dia", "noche"]


class HsvRange(BaseModel):
    lower: list[int] = Field(min_length=3, max_length=3)
    upper: list[int] = Field(min_length=3, max_length=3)

    @field_validator("lower", "upper")
    @classmethod
    def hsv_triplet(cls, value: list[int]) -> list[int]:
        if len(value) != 3:
            raise ValueError("HSV range must have exactly three values [H, S, V].")
        h, s, v = value
        if not (0 <= h <= 179):
            raise ValueError("Hue must be between 0 and 179.")
        if not (0 <= s <= 255 and 0 <= v <= 255):
            raise ValueError("Saturation and value must be between 0 and 255.")
        return value


class FractionRect(BaseModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)


class LedBandConfig(BaseModel):
    top_frac: float = Field(ge=0.0, le=1.0)
    height_frac: float = Field(gt=0.0, le=1.0)
    min_height_px: int = Field(gt=0)
    max_height_px: int = Field(gt=0)

    @field_validator("max_height_px")
    @classmethod
    def max_not_below_min(cls, value: int, info) -> int:
        min_px = info.data.get("min_height_px")
        if min_px is not None and value < min_px:
            raise ValueError("max_height_px must be >= min_height_px.")
        return value


class MatteYellowConfig(BaseModel):
    hsv: HsvRange
    col_frac: float = Field(gt=0.0, le=1.0)
    keep_col_frac: float = Field(gt=0.0, le=1.0)
    texture_max: float = Field(gt=0.0)
    min_led_mean_v: float = Field(ge=0.0)


class CameraProfile(BaseModel):
    id: str
    variante: CameraVariant = "default"
    scoreboard_crop: FractionRect
    grass_hsv: HsvRange
    led_band: LedBandConfig
    grass_y_top_frac: float = Field(default=0.28, ge=0.0, le=1.0)
    grass_y_bot_frac: float = Field(default=0.92, ge=0.0, le=1.0)
    grass_min_ratio: float = Field(default=0.08, gt=0.0, le=1.0)
    matte_yellow: MatteYellowConfig | None = None
    panel_zones: list[PanelZone] = Field(default_factory=lambda: list(DEFAULT_PANEL_ZONES))


class Stadium(BaseModel):
    id: str
    nombre: str
    pais: str | None = None
    default_camera: str = "default"
    camera: CameraProfile
