"""Interchangeable panel extractors (OCR loop, FIXED_PRINT template match, …)."""

from .template_match import (
    DEFAULT_SCORE_THRESHOLD,
    TemplateHit,
    detect_fixed_brands,
    match_logo,
)

__all__ = [
    "DEFAULT_SCORE_THRESHOLD",
    "TemplateHit",
    "detect_fixed_brands",
    "match_logo",
]
