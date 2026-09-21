"""FIXED_PRINT extractor: multi-scale template / logo matching."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from ...schemas import BrandInput


DEFAULT_SCORE_THRESHOLD = 0.70
# LED-row logos are often much smaller than campaign PNGs; also cover slight zoom.
_SCALES = (0.25, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0, 1.15, 1.35, 1.6, 2.0)
_MIN_TEMPLATE_SIDE = 4
_LOW_VARIANCE_STD = 8.0


@dataclass(frozen=True)
class TemplateHit:
    score: float
    bbox: tuple[int, int, int, int]
    visible_area_ratio: float


def _as_bgr(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _color_score(patch: np.ndarray, templ: np.ndarray) -> float:
    """1 when mean BGR matches; 0 when any channel is 255 apart.

    Needed because TM_SQDIFF_NORMED is numerically unstable on flat mats and
    can report a perfect score against the wrong solid color.
    """
    patch_mean = patch.reshape(-1, 3).astype(np.float32).mean(axis=0)
    templ_mean = templ.reshape(-1, 3).astype(np.float32).mean(axis=0)
    max_delta = float(np.max(np.abs(patch_mean - templ_mean)))
    return max(0.0, 1.0 - max_delta / 255.0)


def _spatial_loc(crop_bgr: np.ndarray, templ_bgr: np.ndarray) -> tuple[float, tuple[int, int]]:
    # Channel-spread (e.g. solid red) is not spatial texture; CCOEFF needs gray variance.
    templ_gray = cv2.cvtColor(templ_bgr, cv2.COLOR_BGR2GRAY)
    std = float(templ_gray.std())
    if not np.isfinite(std) or std < _LOW_VARIANCE_STD:
        result = cv2.matchTemplate(crop_bgr, templ_bgr, cv2.TM_SQDIFF)
        min_val, _, min_loc, _ = cv2.minMaxLoc(result)
        mse = float(min_val) / max(1, templ_bgr.size)
        score = 1.0 - min(1.0, mse / (255.0 ** 2))
        loc = min_loc
    else:
        crop_gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(crop_gray, templ_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        score = float(max_val)
        loc = max_loc
    if not np.isfinite(score):
        return -1.0, (0, 0)
    return max(0.0, min(1.0, score)), (int(loc[0]), int(loc[1]))


def match_logo(
    crop_bgr: np.ndarray,
    logo_bgr: np.ndarray,
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> TemplateHit | None:
    """Locate `logo_bgr` inside a LED/fixed-row crop via multi-scale matchTemplate.

    ORB + homography is unreliable on small, low-texture LED mats, so this
    extractor uses cv2.matchTemplate across a scale pyramid instead.
    """
    if crop_bgr is None or logo_bgr is None:
        return None
    if crop_bgr.size == 0 or logo_bgr.size == 0:
        return None

    crop = _as_bgr(np.ascontiguousarray(crop_bgr))
    logo = _as_bgr(np.ascontiguousarray(logo_bgr))
    crop_h, crop_w = crop.shape[:2]
    logo_h, logo_w = logo.shape[:2]
    if crop_h < _MIN_TEMPLATE_SIDE or crop_w < _MIN_TEMPLATE_SIDE:
        return None
    if logo_h < 1 or logo_w < 1:
        return None

    crop_area = float(crop_h * crop_w)
    best_score = -1.0
    best_bbox: tuple[int, int, int, int] | None = None
    best_area = -1

    for scale in _SCALES:
        tw = max(1, int(round(logo_w * scale)))
        th = max(1, int(round(logo_h * scale)))
        if tw > crop_w or th > crop_h:
            continue
        if tw < _MIN_TEMPLATE_SIDE or th < _MIN_TEMPLATE_SIDE:
            continue
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        templ = cv2.resize(logo, (tw, th), interpolation=interpolation)
        spatial, (x, y) = _spatial_loc(crop, templ)
        patch = crop[y : y + th, x : x + tw]
        if patch.shape[0] != th or patch.shape[1] != tw:
            continue
        score = min(spatial, _color_score(patch, templ))
        if not np.isfinite(score):
            continue
        area = tw * th
        # Prefer the largest window when several scales share a near-perfect score.
        better = score > best_score + 1e-4 or (
            abs(score - best_score) <= 1e-4 and area > best_area
        )
        if better:
            best_score = score
            best_bbox = (x, y, tw, th)
            best_area = area

    if best_bbox is None or best_score < score_threshold:
        return None

    x, y, w, h = best_bbox
    visible_area_ratio = (w * h) / crop_area if crop_area else 0.0
    return TemplateHit(
        score=best_score,
        bbox=(x, y, w, h),
        visible_area_ratio=visible_area_ratio,
    )


def detect_fixed_brands(
    crop_bgr: np.ndarray,
    brands_with_logos: list[tuple[BrandInput, np.ndarray | None]],
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[dict]:
    """Match campaign logos against a crop. Brands without a logo array are skipped."""
    detections: list[dict] = []
    for brand, logo_bgr in brands_with_logos:
        if logo_bgr is None:
            continue
        hit = match_logo(crop_bgr, logo_bgr, score_threshold=score_threshold)
        if hit is None:
            continue
        brand_id = brand.id or brand.name
        detections.append(
            {
                "brand_id": brand_id,
                "score": hit.score,
                "visible_area_ratio": hit.visible_area_ratio,
            }
        )
    return detections
