"""Grass HSV → touchline → LED strip crop, plus the lateral camera gate."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..domain.stadium import CameraProfile
from .video import get_video_info, read_frame_at_seconds


logger = logging.getLogger(__name__)

# Night broadcasts push turf hue toward ~30–34 and darken V. Keep the upper
# bound below cyan LEDs (~90) so NETT plus glow is not classified as grass.
_GRASS_LOWER = np.array([28, 25, 30], dtype=np.uint8)
_GRASS_UPPER = np.array([85, 255, 255], dtype=np.uint8)
_GRASS_MIN_RATIO = 0.08
_MIN_VALID_COLUMNS_RATIO = 0.15
_MIN_LED_PX = 18
_COLUMN_STEP = 4
_MEDIAN_WINDOW = 21
_GRASS_Y_TOP_FRAC = 0.28
_GRASS_Y_BOT_FRAC = 0.92
# Wide/high cameras put the far LED above 22% of the frame. 0.12 still
# stays below the scoreboard (~0.08) and catches that sideline strip.
_LED_BAND_Y_TOP_FRAC = 0.12
_PROBE_SECONDS = 60.0
_DEBUG_EVERY = 30
# Matte midfield boards (LigaEcuabet) sit in the LED row but are not emissive.
_MATTE_YELLOW_LOWER = np.array([18, 70, 70], dtype=np.uint8)
_MATTE_YELLOW_UPPER = np.array([40, 255, 255], dtype=np.uint8)
_LED_KEEP_COL_FRAC = 0.22
_MATTE_YELLOW_COL_FRAC = 0.55
_MATTE_TEXTURE_MAX = 14.0
_MIN_LED_MEAN_V = 70.0


@dataclass(frozen=True)
class RoiParams:
    grass_lower: tuple[int, int, int]
    grass_upper: tuple[int, int, int]
    grass_min_ratio: float
    grass_y_top_frac: float
    grass_y_bot_frac: float
    led_band_y_top_frac: float
    led_height_frac: float
    led_min_height_px: int
    led_max_height_px: int
    matte_yellow_lower: tuple[int, int, int]
    matte_yellow_upper: tuple[int, int, int]
    matte_yellow_col_frac: float
    led_keep_col_frac: float
    matte_texture_max: float
    min_led_mean_v: float
    # True when profile is None (legacy defaults) or profile.matte_yellow is set.
    mask_fixed_banners: bool


_DEFAULT_ROI_PARAMS = RoiParams(
    grass_lower=(int(_GRASS_LOWER[0]), int(_GRASS_LOWER[1]), int(_GRASS_LOWER[2])),
    grass_upper=(int(_GRASS_UPPER[0]), int(_GRASS_UPPER[1]), int(_GRASS_UPPER[2])),
    grass_min_ratio=_GRASS_MIN_RATIO,
    grass_y_top_frac=_GRASS_Y_TOP_FRAC,
    grass_y_bot_frac=_GRASS_Y_BOT_FRAC,
    led_band_y_top_frac=_LED_BAND_Y_TOP_FRAC,
    led_height_frac=0.035,
    led_min_height_px=22,
    led_max_height_px=70,
    matte_yellow_lower=(
        int(_MATTE_YELLOW_LOWER[0]),
        int(_MATTE_YELLOW_LOWER[1]),
        int(_MATTE_YELLOW_LOWER[2]),
    ),
    matte_yellow_upper=(
        int(_MATTE_YELLOW_UPPER[0]),
        int(_MATTE_YELLOW_UPPER[1]),
        int(_MATTE_YELLOW_UPPER[2]),
    ),
    matte_yellow_col_frac=_MATTE_YELLOW_COL_FRAC,
    led_keep_col_frac=_LED_KEEP_COL_FRAC,
    matte_texture_max=_MATTE_TEXTURE_MAX,
    min_led_mean_v=_MIN_LED_MEAN_V,
    mask_fixed_banners=True,
)


def _roi_params(profile: CameraProfile | None) -> RoiParams:
    if profile is None:
        return _DEFAULT_ROI_PARAMS
    matte = profile.matte_yellow
    return RoiParams(
        grass_lower=(
            int(profile.grass_hsv.lower[0]),
            int(profile.grass_hsv.lower[1]),
            int(profile.grass_hsv.lower[2]),
        ),
        grass_upper=(
            int(profile.grass_hsv.upper[0]),
            int(profile.grass_hsv.upper[1]),
            int(profile.grass_hsv.upper[2]),
        ),
        grass_min_ratio=profile.grass_min_ratio,
        grass_y_top_frac=profile.grass_y_top_frac,
        grass_y_bot_frac=profile.grass_y_bot_frac,
        led_band_y_top_frac=profile.led_band.top_frac,
        led_height_frac=profile.led_band.height_frac,
        led_min_height_px=profile.led_band.min_height_px,
        led_max_height_px=profile.led_band.max_height_px,
        matte_yellow_lower=(
            tuple(int(v) for v in matte.hsv.lower)
            if matte is not None
            else _DEFAULT_ROI_PARAMS.matte_yellow_lower
        ),
        matte_yellow_upper=(
            tuple(int(v) for v in matte.hsv.upper)
            if matte is not None
            else _DEFAULT_ROI_PARAMS.matte_yellow_upper
        ),
        matte_yellow_col_frac=(
            matte.col_frac if matte is not None else _DEFAULT_ROI_PARAMS.matte_yellow_col_frac
        ),
        led_keep_col_frac=(
            matte.keep_col_frac if matte is not None else _DEFAULT_ROI_PARAMS.led_keep_col_frac
        ),
        matte_texture_max=(
            matte.texture_max if matte is not None else _DEFAULT_ROI_PARAMS.matte_texture_max
        ),
        min_led_mean_v=(
            matte.min_led_mean_v if matte is not None else _DEFAULT_ROI_PARAMS.min_led_mean_v
        ),
        mask_fixed_banners=matte is not None,
    )


def _led_height_from_params(frame_h: int, params: RoiParams) -> int:
    return int(
        np.clip(
            params.led_height_frac * frame_h,
            params.led_min_height_px,
            params.led_max_height_px,
        )
    )


@dataclass
class RoiResult:
    skipped: bool
    reason: str | None
    crop_bgr: np.ndarray | None
    debug_overlay: np.ndarray | None
    y0: int | None = None
    y1: int | None = None


@dataclass
class ProbeStats:
    sampled: int = 0
    kept: int = 0
    skipped: int = 0
    saved: int = 0


@dataclass(frozen=True)
class _LedBand:
    y0: int
    y1: int
    score: float
    kind: str

    @property
    def height(self) -> int:
        return max(0, self.y1 - self.y0)

    @property
    def center(self) -> float:
        return 0.5 * (self.y0 + self.y1)


class DebugCropWriter:
    """Persist 1 of every N successful LED crops for visual inspection."""

    def __init__(self, directory: Path, every: int = _DEBUG_EVERY):
        self.directory = Path(directory)
        self.every = max(1, every)
        self.kept = 0
        self.saved = 0

    def maybe_save(self, frame_idx: int, roi: RoiResult) -> bool:
        if roi.skipped or roi.crop_bgr is None or roi.crop_bgr.size == 0:
            return False
        self.kept += 1
        if (self.kept - 1) % self.every != 0:
            return False

        self.directory.mkdir(parents=True, exist_ok=True)
        crop_path = self.directory / f"led_{frame_idx:06d}.jpg"
        cv2.imwrite(str(crop_path), roi.crop_bgr)
        if roi.debug_overlay is not None:
            overlay_path = self.directory / f"overlay_{frame_idx:06d}.jpg"
            cv2.imwrite(str(overlay_path), roi.debug_overlay)
        self.saved += 1
        logger.info(
            "Saved LED debug crop %s (y0=%s y1=%s)",
            crop_path,
            roi.y0,
            roi.y1,
        )
        return True


def crop_overhang_ratio(
    touch: float,
    y0: int,
    led_h: int,
) -> float:
    """How far the crop top sits above the grass relative to expected LED height.

    Values near 1.0 mean the strip kisses the touchline. Values ≫ 1.35 mean the
    ROI climbed into upper fixed lonas (AURUM / GUTMAN / MIRACLE).
    """
    if led_h <= 0:
        return float("inf")
    overhang = max(0.0, float(touch) - float(y0))
    return overhang / float(led_h)


def grass_mask(frame: np.ndarray, profile: CameraProfile | None = None) -> np.ndarray:
    params = _roi_params(profile)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array(params.grass_lower, dtype=np.uint8),
        np.array(params.grass_upper, dtype=np.uint8),
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return mask


def led_height_px(frame_h: int, profile: CameraProfile | None = None) -> int:
    return _led_height_from_params(frame_h, _roi_params(profile))


def _median_smooth(values: np.ndarray, window: int = _MEDIAN_WINDOW) -> np.ndarray:
    pad = window // 2
    padded = np.pad(values.astype(np.float64), (pad, pad), mode="edge")
    out = np.empty(values.shape, dtype=np.float64)
    for i in range(len(values)):
        chunk = padded[i : i + window]
        finite = chunk[np.isfinite(chunk)]
        out[i] = float(np.median(finite)) if finite.size else np.nan
    return out


def _touchline_ys(
    mask: np.ndarray,
    profile: CameraProfile | None = None,
    *,
    params: RoiParams | None = None,
) -> np.ndarray | None:
    """Top of the bottom-most grass run per sampled column (the touchline)."""
    p = params if params is not None else _roi_params(profile)
    height, width = mask.shape[:2]
    y_min = int(height * p.grass_y_top_frac)
    y_max = int(height * p.grass_y_bot_frac)
    if y_max - y_min < 10 or width < _COLUMN_STEP:
        return None

    xs = np.arange(0, width, _COLUMN_STEP)
    ys = np.full(xs.shape, np.nan, dtype=np.float64)
    region = mask[y_min:y_max]
    for i, x in enumerate(xs):
        col = region[:, x]
        idx = len(col) - 1
        while idx >= 0 and col[idx] == 0:
            idx -= 1
        if idx < 0:
            continue
        while idx >= 0 and col[idx] > 0:
            idx -= 1
        ys[i] = float(y_min + idx + 1)

    valid = np.isfinite(ys)
    if valid.mean() < _MIN_VALID_COLUMNS_RATIO or int(valid.sum()) < 8:
        return None

    ys = _median_smooth(ys)
    valid = np.isfinite(ys)
    if int(valid.sum()) < 8:
        return None

    all_x = np.arange(width, dtype=np.float64)
    y_full = np.interp(all_x, xs[valid], ys[valid])
    return y_full


def _median_nongrass_run(
    mask: np.ndarray,
    y_grass: np.ndarray,
    profile: CameraProfile | None = None,
    *,
    params: RoiParams | None = None,
) -> int:
    height, width = mask.shape[:2]
    p = params if params is not None else _roi_params(profile)
    led_h = _led_height_from_params(height, p)
    samples: list[int] = []
    for x in range(0, width, 16):
        y = int(round(y_grass[x]))
        run = 0
        y_start = min(height - 1, max(0, y - 2))
        for yy in range(y_start, max(0, y_start - led_h * 2), -1):
            if mask[yy, x] == 0:
                run += 1
            else:
                break
        samples.append(run)
    return int(np.median(samples)) if samples else 0


def _find_color_bands(
    frame: np.ndarray,
    *,
    y_min: int,
    y_max: int,
    profile: CameraProfile | None = None,
    params: RoiParams | None = None,
) -> list[_LedBand]:
    """Find bright full-width LED candidates (yellow/cyan/magenta/blue/red)."""
    p = params if params is not None else _roi_params(profile)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {
        # LEDs are bright; keep V floors high so dark stands/navy don't match.
        # Keep yellow away from grass greens (H>~40).
        "yellow": cv2.inRange(hsv, (15, 70, 130), (38, 255, 255)),
        "cyan": cv2.inRange(hsv, (85, 40, 130), (125, 255, 255)),
        "magenta": cv2.inRange(hsv, (140, 50, 130), (179, 255, 255)),
        "blue": cv2.inRange(hsv, (95, 70, 130), (135, 255, 255)),
        "red": cv2.bitwise_or(
            cv2.inRange(hsv, (0, 70, 130), (10, 255, 255)),
            cv2.inRange(hsv, (170, 70, 130), (179, 255, 255)),
        ),
    }
    height = frame.shape[0]
    max_h = _led_height_from_params(height, p) + 12
    bands: list[_LedBand] = []

    for kind, mask in masks.items():
        row = (mask[y_min:y_max] > 0).mean(axis=1)
        if row.size == 0 or float(row.max()) < 0.10:
            continue
        used = np.zeros(row.shape, dtype=bool)
        for _ in range(3):
            available = row.copy()
            available[used] = 0
            peak_rel = int(available.argmax())
            score = float(available[peak_rel])
            if score < 0.10:
                break
            thr = max(0.08, score * 0.40)
            lo = hi = peak_rel
            while lo > 0 and row[lo - 1] >= thr:
                lo -= 1
            while hi < len(row) - 1 and row[hi + 1] >= thr:
                hi += 1
            used[lo : hi + 1] = True
            y0 = y_min + lo
            y1 = y_min + hi + 1
            band_h = y1 - y0
            if band_h < _MIN_LED_PX:
                continue
            if band_h > max_h:
                # Keep a window around the color peak so a yellow skirt
                # under the LED does not push the crop off the letters.
                peak_y = y_min + peak_rel
                y0 = int(np.clip(peak_y - max_h // 2, y0, y1 - max_h))
                y1 = y0 + max_h
            bands.append(_LedBand(y0=y0, y1=y1, score=score, kind=kind))
    return bands


def _pick_led_band(
    bands: list[_LedBand],
    *,
    y_grass: np.ndarray | None,
    frame_h: int,
    profile: CameraProfile | None = None,
    params: RoiParams | None = None,
) -> _LedBand | None:
    if not bands:
        return None

    p = params if params is not None else _roi_params(profile)
    led_h = _led_height_from_params(frame_h, p)
    touch = float(np.median(y_grass)) if y_grass is not None else None
    scored: list[tuple[float, _LedBand]] = []

    # Far-sideline LEDs at 720p sit ~100–110 px above a deep grass median;
    # keep that window while still ranking out upper lonas via gap penalty.
    max_gap = max(led_h * 2.5, frame_h * 0.16)
    for band in bands:
        if touch is None:
            if band.center < frame_h * p.led_band_y_top_frac or band.center > frame_h * 0.78:
                continue
            rank = -80.0 * band.score + abs(band.center - frame_h * 0.45)
            scored.append((rank, band))
            continue

        gap_above = touch - band.y1
        gap_below = band.y0 - touch
        intersects = band.y0 <= touch + 12 and band.y1 >= touch - led_h * 2
        # Reject scoreboard / upper lonas, but keep a far LED in a wide shot
        # (players on the touchline open a gap of ~50–110 px at 720p).
        if gap_above > max_gap and not intersects:
            continue
        if band.score < 0.35:
            continue
        if gap_below > led_h:
            continue

        proximity = abs(touch - band.y1)
        height_bonus = -0.15 * min(band.height, led_h)
        rank = proximity - 80.0 * band.score + height_bonus
        if intersects:
            rank -= 25.0
        # Prefer the LED kissing the grass over a board floating higher.
        rank += max(0.0, gap_above) * 0.45
        scored.append((rank, band))

    if not scored:
        return None
    best_score = max(band.score for _rank, band in scored)
    scored = [
        (rank, band)
        for rank, band in scored
        if band.score >= best_score * 0.75
    ]
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _anchor_band_to_grass(
    band: _LedBand | None,
    y_grass: np.ndarray | None,
    frame_h: int,
    profile: CameraProfile | None = None,
    *,
    params: RoiParams | None = None,
) -> tuple[int, int] | None:
    """Force a thin strip immediately above the touchline when grass is known.

    Never copy a color-band's full ``y0/y1`` — upper lonas share bright HSV and
    would drag the crop into AURUM/GUTMAN/MIRACLE boards. Far LEDs (high camera)
    get a thin strip ending at ``band.y1``, not the full band height.
    """
    p = params if params is not None else _roi_params(profile)
    led_h = _led_height_from_params(frame_h, p)
    if y_grass is not None:
        touch = int(round(float(np.median(y_grass))))
        touch = int(np.clip(touch, led_h + 2, frame_h - 1))
        if band is not None and abs(band.y1 - touch) <= led_h * 0.75:
            # LED kissing the grass: grow strictly upward from the touchline.
            # Do not push y1 below touch — that lifts y0 into fixed lonas.
            y1 = touch
            y0 = max(0, y1 - led_h)
            if y1 - y0 >= _MIN_LED_PX:
                return y0, y1
        if band is not None and band.score >= 0.35:
            # Far / elevated LED: thin strip at the band bottom only.
            y1 = min(frame_h, band.y1)
            y0 = max(0, y1 - led_h)
            if y1 - y0 >= _MIN_LED_PX:
                return y0, y1
        y1 = touch
        y0 = max(0, y1 - led_h)
        if y1 - y0 >= _MIN_LED_PX:
            return y0, y1
        return None
    if band is None:
        return None
    y1 = min(frame_h, band.y1)
    y0 = max(0, y1 - led_h)
    if y1 - y0 < _MIN_LED_PX:
        return None
    return y0, y1


def _mask_fixed_banner_columns(
    crop_bgr: np.ndarray,
    profile: CameraProfile | None = None,
    *,
    params: RoiParams | None = None,
) -> np.ndarray:
    """Blank matte yellow fixed boards that share the LED row or sit under it.

    Strategy is opt-in from CameraProfile.matte_yellow:
    - profile is None: use hardcoded LigaEcuabet HSV/texture defaults (legacy).
    - profile.matte_yellow is None: skip entirely — no column blanking or
      yellow-skirt trim. Stadiums without painted inserts keep the full LED row.
    - profile.matte_yellow is set: use that HSV range, col_frac, texture_max,
      and keep_col_frac.

    Painted inserts are lower-texture than emissive LED, so yellow patches
    are compared against neighboring LED columns.
    """
    if crop_bgr is None or crop_bgr.size == 0:
        return crop_bgr

    p = params if params is not None else _roi_params(profile)
    if not p.mask_fixed_banners:
        return crop_bgr
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    yellow = cv2.inRange(
        hsv,
        np.array(p.matte_yellow_lower, dtype=np.uint8),
        np.array(p.matte_yellow_upper, dtype=np.uint8),
    ) > 0
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3))
    v = hsv[:, :, 2].astype(np.float32)

    yellow_frac_x = yellow.mean(axis=0)
    texture_x = lap.mean(axis=0)
    v_x = v.mean(axis=0)

    led_ref = texture_x[(yellow_frac_x < 0.30) & (v_x > 70)]
    tex_ref = float(np.median(led_ref)) if led_ref.size >= 8 else 22.0
    matte_tex_max = max(p.matte_texture_max, tex_ref * 0.55)

    keep_x = np.ones(crop_bgr.shape[1], dtype=bool)
    for x in range(crop_bgr.shape[1]):
        matte_yellow = yellow_frac_x[x] >= p.matte_yellow_col_frac and texture_x[x] <= matte_tex_max
        empty = v_x[x] < 35
        # Non-emissive print lonas that leak into the LED row (low texture + dull V).
        dull_print = texture_x[x] <= matte_tex_max * 0.85 and v_x[x] < 95 and yellow_frac_x[x] < 0.30
        if matte_yellow or empty or dull_print:
            keep_x[x] = False

    keep_x_u8 = keep_x.astype(np.uint8) * 255
    keep_x_u8 = cv2.morphologyEx(
        keep_x_u8.reshape(1, -1),
        cv2.MORPH_CLOSE,
        np.ones((1, 11), np.uint8),
    ).reshape(-1)
    keep_x = keep_x_u8 > 0

    # Limited-width yellow inserts (fixed LigaEcuabet) after closing LED gaps.
    yellow_run = yellow_frac_x >= 0.40
    if 0.04 <= float(yellow_run.mean()) <= 0.42:
        keep_x[yellow_run] = False

    if keep_x.mean() < p.led_keep_col_frac:
        keep_x[:] = True

    out = crop_bgr.copy()
    out[:, ~keep_x] = 0

    # Physically trim the yellow skirt under the LED — blacking it still leaks OCR.
    yellow_frac_y = yellow.mean(axis=1)
    cut = out.shape[0]
    for y in range(out.shape[0] - 2):
        if (
            yellow_frac_y[y] >= 0.40
            and yellow_frac_y[y + 1] >= 0.40
            and yellow_frac_y[y + 2] >= 0.40
        ):
            cut = y
            break
    if 12 <= cut < out.shape[0]:
        out = out[:cut]

    return out


def _led_polygon(
    y_grass: np.ndarray,
    frame_h: int,
    frame_w: int,
    profile: CameraProfile | None = None,
    *,
    params: RoiParams | None = None,
) -> np.ndarray:
    p = params if params is not None else _roi_params(profile)
    led_h = _led_height_from_params(frame_h, p)
    xs = np.arange(0, frame_w, _COLUMN_STEP, dtype=np.int32)
    if xs[-1] != frame_w - 1:
        xs = np.append(xs, np.int32(frame_w - 1))
    top = np.clip(np.round(y_grass[xs] - led_h), 0, frame_h - 1).astype(np.int32)
    bot = np.clip(np.round(y_grass[xs] - 2), 0, frame_h - 1).astype(np.int32)
    top = np.minimum(top, np.maximum(bot - 1, 0))
    pts_bot = np.stack([xs, bot], axis=1)
    pts_top = np.stack([xs[::-1], top[::-1]], axis=1)
    return np.vstack([pts_bot, pts_top]).astype(np.int32)


def _draw_overlay(
    frame: np.ndarray,
    y_grass: np.ndarray | None,
    y0: int,
    y1: int,
) -> np.ndarray:
    overlay = frame.copy()
    width = frame.shape[1]
    if y_grass is not None:
        for x in range(0, width, _COLUMN_STEP):
            y = int(round(y_grass[x]))
            cv2.circle(overlay, (x, y), 1, (0, 255, 255), -1)
    cv2.rectangle(overlay, (0, y0), (width - 1, y1 - 1), (0, 255, 0), 2)
    return overlay


def _skipped(reason: str) -> RoiResult:
    return RoiResult(skipped=True, reason=reason, crop_bgr=None, debug_overlay=None)


def _trusted_grass_line(
    y_grass: np.ndarray | None,
    bands: list[_LedBand],
    frame_h: int,
) -> np.ndarray | None:
    """Drop bogus high touchlines when a strong lower LED band is obvious."""
    if y_grass is None:
        return None
    touch = float(np.median(y_grass))
    strong_lower = [
        band
        for band in bands
        if band.score >= 0.40 and band.center >= frame_h * 0.40
    ]
    if touch < frame_h / 3.0 and strong_lower:
        return None
    return y_grass


def extract_led_roi(
    frame: np.ndarray,
    profile: CameraProfile | None = None,
) -> RoiResult:
    """Crop only the LED strip sitting on the grass. Never a fixed lower rectangle."""
    if frame is None or frame.size == 0 or frame.ndim != 3:
        return _skipped("empty_frame")

    params = _roi_params(profile)
    height, width = frame.shape[:2]
    mask = grass_mask(frame, profile)
    grass_ratio = float((mask > 0).mean())
    y_grass_raw = (
        _touchline_ys(mask, profile, params=params)
        if grass_ratio >= params.grass_min_ratio
        else None
    )

    bands = _find_color_bands(
        frame,
        y_min=int(height * params.led_band_y_top_frac),
        y_max=int(height * 0.90),
        profile=profile,
        params=params,
    )
    y_grass = _trusted_grass_line(y_grass_raw, bands, height)
    band = _pick_led_band(
        bands, y_grass=y_grass, frame_h=height, profile=profile, params=params
    )

    if y_grass is not None:
        median_line = float(np.median(y_grass))
        if median_line < height / 3.0 and band is None:
            return _skipped("wide_shot")

    anchored = _anchor_band_to_grass(
        band, y_grass, height, profile, params=params
    )
    if anchored is not None:
        y0, y1 = anchored
        crop = _mask_fixed_banner_columns(
            frame[y0:y1, 0:width], profile, params=params
        )
        mean_v = float(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2].mean())
        if crop.size == 0 or (crop > 0).mean() < 0.04 or mean_v < params.min_led_mean_v:
            if grass_ratio < params.grass_min_ratio:
                return _skipped("low_grass")
            return _skipped("empty_crop")
        overlay = _draw_overlay(frame, y_grass, y0, y1)
        return RoiResult(
            skipped=False,
            reason=None,
            crop_bgr=crop,
            debug_overlay=overlay,
            y0=y0,
            y1=y1,
        )

    if grass_ratio < params.grass_min_ratio:
        return _skipped("low_grass")
    if y_grass is None and y_grass_raw is None:
        return _skipped("few_grass_points")
    if y_grass is None:
        # Grass was untrusted; still require a color band.
        return _skipped("few_grass_points" if band is None else "empty_crop")

    median_line = float(np.median(y_grass))
    if median_line < height / 3.0:
        return _skipped("wide_shot")

    thickness = _median_nongrass_run(mask, y_grass, profile, params=params)
    if thickness < _MIN_LED_PX:
        return _skipped("led_too_thin")

    polygon = _led_polygon(y_grass, height, width, profile, params=params)
    led_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(led_mask, [polygon], 255)
    ys, xs = np.where(led_mask > 0)
    if ys.size == 0 or xs.size == 0:
        return _skipped("empty_crop")

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    # Never climb into the fixed lonas above the LED.
    led_h = _led_height_from_params(height, params)
    y0 = max(y0, y1 - led_h - 4)
    if (y1 - y0) < _MIN_LED_PX:
        return _skipped("led_too_thin")

    crop = _mask_fixed_banner_columns(
        frame[y0:y1, x0:x1], profile, params=params
    )
    if crop.size == 0 or (crop > 0).mean() < 0.04:
        return _skipped("empty_crop")

    overlay = _draw_overlay(frame, y_grass, y0, y1)
    return RoiResult(
        skipped=False,
        reason=None,
        crop_bgr=crop,
        debug_overlay=overlay,
        y0=y0,
        y1=y1,
    )


def extract_fixed_banner_roi(
    frame: np.ndarray,
    profile: CameraProfile | None = None,
    *,
    led: RoiResult | None = None,
) -> RoiResult:
    """Crop the matte second-row lonas sitting immediately above the LED."""
    if frame is None or frame.size == 0 or frame.ndim != 3:
        return _skipped("empty_frame")

    params = _roi_params(profile)
    height, width = frame.shape[:2]
    led_h = _led_height_from_params(height, params)
    scoreboard_h = int(height * 0.22)
    if led is None:
        led = extract_led_roi(frame, profile)
    if not led.skipped and led.y0 is not None:
        y1 = max(0, led.y0)
        y0 = max(scoreboard_h, y1 - int(round(led_h * 1.25)))
    else:
        mask = grass_mask(frame, profile)
        y_grass = _touchline_ys(mask, profile, params=params)
        if y_grass is None:
            return _skipped("few_grass_points")
        touch = int(round(float(np.median(y_grass))))
        led_y0 = max(0, touch - led_h)
        y1 = led_y0
        y0 = max(scoreboard_h, y1 - int(round(led_h * 1.25)))

    if y1 - y0 < _MIN_LED_PX:
        return _skipped("fixed_too_thin")
    crop = frame[y0:y1, 0:width]
    if crop.size == 0 or (crop > 0).mean() < 0.04:
        return _skipped("empty_crop")
    overlay = _draw_overlay(frame, None, y0, y1)
    return RoiResult(
        skipped=False,
        reason=None,
        crop_bgr=crop,
        debug_overlay=overlay,
        y0=y0,
        y1=y1,
    )


def iter_video_rois(
    video_path: str | Path,
    start_seconds: float,
    *,
    max_seconds: float = _PROBE_SECONDS,
    sample_interval: float = 1.0,
) -> Iterator[tuple[float, int, RoiResult]]:
    """Yield ROI results at 1 FPS from start_seconds, for a short debug window."""
    info = get_video_info(video_path)
    end = min(info.duration_seconds, max(0.0, start_seconds) + max_seconds)
    cap = cv2.VideoCapture(str(video_path))
    try:
        t = max(0.0, start_seconds)
        while t < end:
            ok, frame, frame_idx = read_frame_at_seconds(cap, t)
            if ok and frame is not None:
                yield t, frame_idx, extract_led_roi(frame)
            t += sample_interval
    finally:
        cap.release()


def probe_led_rois(
    video_path: str | Path,
    start_seconds: float,
    debug_dir: Path,
    *,
    max_seconds: float = _PROBE_SECONDS,
    on_crop: Callable[[int, RoiResult], None] | None = None,
) -> ProbeStats:
    """Sample LED crops after kickoff and persist 1/30 for inspection."""
    writer = DebugCropWriter(debug_dir)
    stats = ProbeStats()
    try:
        for _t, frame_idx, roi in iter_video_rois(
            video_path,
            start_seconds,
            max_seconds=max_seconds,
        ):
            stats.sampled += 1
            if roi.skipped:
                stats.skipped += 1
                logger.debug("ROI skip t=%.1fs frame=%s: %s", _t, frame_idx, roi.reason)
                continue
            stats.kept += 1
            writer.maybe_save(frame_idx, roi)
            if on_crop is not None:
                on_crop(frame_idx, roi)
    except ValueError as exc:
        logger.warning("ROI probe skipped, video unreadable: %s", exc)
        return stats

    stats.saved = writer.saved
    logger.info(
        "ROI probe: sampled=%s kept=%s skipped=%s saved=%s",
        stats.sampled,
        stats.kept,
        stats.skipped,
        stats.saved,
    )
    return stats
