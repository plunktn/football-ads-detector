"""Grass HSV → touchline → LED strip crop, plus the lateral camera gate."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

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
_PROBE_SECONDS = 60.0
_DEBUG_EVERY = 30


@dataclass
class RoiResult:
    skipped: bool
    reason: str | None
    crop_bgr: np.ndarray | None
    debug_overlay: np.ndarray | None


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
        logger.info("Saved LED debug crop %s", crop_path)
        return True


def grass_mask(frame: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _GRASS_LOWER, _GRASS_UPPER)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return mask


def led_height_px(frame_h: int) -> int:
    return int(np.clip(0.055 * frame_h, 28, 90))


def _median_smooth(values: np.ndarray, window: int = _MEDIAN_WINDOW) -> np.ndarray:
    pad = window // 2
    padded = np.pad(values.astype(np.float64), (pad, pad), mode="edge")
    out = np.empty(values.shape, dtype=np.float64)
    for i in range(len(values)):
        chunk = padded[i : i + window]
        finite = chunk[np.isfinite(chunk)]
        out[i] = float(np.median(finite)) if finite.size else np.nan
    return out


def _touchline_ys(mask: np.ndarray) -> np.ndarray | None:
    """Top of the bottom-most grass run per sampled column (the touchline)."""
    height, width = mask.shape[:2]
    y_min = int(height * _GRASS_Y_TOP_FRAC)
    y_max = int(height * _GRASS_Y_BOT_FRAC)
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


def _median_nongrass_run(mask: np.ndarray, y_grass: np.ndarray) -> int:
    height, width = mask.shape[:2]
    led_h = led_height_px(height)
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
) -> list[_LedBand]:
    """Find bright full-width yellow/cyan LED candidates."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {
        "yellow": cv2.inRange(hsv, (15, 60, 120), (45, 255, 255)),
        "cyan": cv2.inRange(hsv, (85, 35, 120), (125, 255, 255)),
    }
    height = frame.shape[0]
    max_h = led_height_px(height) + 20
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
                mid = (y0 + y1) // 2
                half = max_h // 2
                y0 = mid - half
                y1 = mid + half
            bands.append(_LedBand(y0=y0, y1=y1, score=score, kind=kind))
    return bands


def _pick_led_band(
    bands: list[_LedBand],
    *,
    y_grass: np.ndarray | None,
    frame_h: int,
) -> _LedBand | None:
    if not bands:
        return None

    led_h = led_height_px(frame_h)
    touch = float(np.median(y_grass)) if y_grass is not None else None
    scored: list[tuple[float, _LedBand]] = []

    for band in bands:
        if touch is None:
            # Without grass, keep mid/lower full-width boards and avoid the
            # scoreboard strip in the upper quarter.
            if band.center < frame_h * 0.28:
                continue
            rank = -40.0 * band.score + abs(band.center - frame_h * 0.55)
            scored.append((rank, band))
            continue

        # Ideal: LED bottom kisses the touchline from above. Night broadcasts
        # often bleed a few pixels of LED into the grass estimate, so allow a
        # small overlap below the line too.
        gap_above = touch - band.y1  # >0 means band fully above grass
        gap_below = band.y0 - touch  # >0 means band fully below grass
        intersects = band.y0 <= touch + 12 and band.y1 >= touch - led_h * 2
        if not intersects and band.score < 0.35:
            continue
        if gap_below > led_h:
            # Band sits well inside the pitch — usually a false yellow patch.
            continue
        if band.center < frame_h / 3.0 and gap_above > led_h * 2:
            # Upper-third band far from grass → scoreboard / stands.
            continue

        proximity = abs(min(gap_above, 0) if gap_above > 0 else gap_below)
        # Prefer stronger, thicker boards near the touchline. No cyan bias:
        # ECUABET is often yellow while NETT plus is cyan.
        height_bonus = -0.15 * min(band.height, led_h)
        rank = proximity - 55.0 * band.score + height_bonus
        if intersects:
            rank -= 25.0
        scored.append((rank, band))

    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def _led_polygon(y_grass: np.ndarray, frame_h: int, frame_w: int) -> np.ndarray:
    led_h = led_height_px(frame_h)
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


def extract_led_roi(frame: np.ndarray) -> RoiResult:
    """Crop only the LED strip sitting on the grass. Never a fixed lower rectangle."""
    if frame is None or frame.size == 0 or frame.ndim != 3:
        return _skipped("empty_frame")

    height, width = frame.shape[:2]
    mask = grass_mask(frame)
    grass_ratio = float((mask > 0).mean())
    y_grass = _touchline_ys(mask) if grass_ratio >= _GRASS_MIN_RATIO else None

    bands = _find_color_bands(
        frame,
        y_min=int(height * 0.22),
        y_max=int(height * 0.90),
    )
    band = _pick_led_band(bands, y_grass=y_grass, frame_h=height)

    if y_grass is not None:
        median_line = float(np.median(y_grass))
        if median_line < height / 3.0 and band is None:
            return _skipped("wide_shot")

    if band is not None:
        y0 = max(0, band.y0)
        y1 = min(height, band.y1)
        if (y1 - y0) < _MIN_LED_PX:
            return _skipped("led_too_thin")
        # Rectangular crop — jagged grass masks destroy OCR on LED text.
        crop = frame[y0:y1, 0:width]
        overlay = _draw_overlay(frame, y_grass, y0, y1)
        return RoiResult(
            skipped=False,
            reason=None,
            crop_bgr=crop,
            debug_overlay=overlay,
        )

    if grass_ratio < _GRASS_MIN_RATIO:
        return _skipped("low_grass")
    if y_grass is None:
        return _skipped("few_grass_points")

    median_line = float(np.median(y_grass))
    if median_line < height / 3.0:
        return _skipped("wide_shot")

    thickness = _median_nongrass_run(mask, y_grass)
    if thickness < _MIN_LED_PX:
        return _skipped("led_too_thin")

    polygon = _led_polygon(y_grass, height, width)
    led_mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(led_mask, [polygon], 255)
    ys, xs = np.where(led_mask > 0)
    if ys.size == 0 or xs.size == 0:
        return _skipped("empty_crop")

    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    if (y1 - y0) < _MIN_LED_PX:
        return _skipped("led_too_thin")

    # Prefer a dense rectangle over the masked polygon for OCR.
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return _skipped("empty_crop")

    overlay = _draw_overlay(frame, y_grass, y0, y1)
    return RoiResult(
        skipped=False,
        reason=None,
        crop_bgr=crop,
        debug_overlay=overlay,
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
