"""Explicit pipeline stages: shot classification and zone localization."""

from .locate import locate_zones
from .shot_class import ShotKind, classify_shot

__all__ = ["ShotKind", "classify_shot", "locate_zones"]
