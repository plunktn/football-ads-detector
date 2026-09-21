"""Propose stadium camera calibration from a sample broadcast frame."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import cv2
import numpy as np
from pydantic import ValidationError

from app.config.stadiums import DEFAULT_STADIUM_ID, load_stadium_profile, save_stadium_yaml
from app.domain.stadium import CameraProfile, FractionRect, HsvRange, Stadium
from app import db

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

DEFAULT_SCOREBOARD_CROP = {"x": 0.0, "y": 0.0, "w": 0.42, "h": 0.22}
FALLBACK_GRASS_HSV = {"lower": [28, 25, 30], "upper": [85, 255, 255]}

_FALLBACK_CAMERA = {
    "id": "default",
    "variante": "default",
    "scoreboard_crop": DEFAULT_SCOREBOARD_CROP,
    "grass_hsv": FALLBACK_GRASS_HSV,
    "led_band": {
        "top_frac": 0.12,
        "height_frac": 0.035,
        "min_height_px": 22,
        "max_height_px": 70,
    },
    "grass_y_top_frac": 0.28,
    "grass_y_bot_frac": 0.92,
    "grass_min_ratio": 0.08,
    "matte_yellow": {
        "hsv": {"lower": [18, 70, 70], "upper": [40, 255, 255]},
        "col_frac": 0.55,
        "keep_col_frac": 0.22,
        "texture_max": 14.0,
        "min_led_mean_v": 70.0,
    },
}


def template_camera() -> CameraProfile:
    try:
        return load_stadium_profile(DEFAULT_STADIUM_ID)
    except (FileNotFoundError, ValidationError, ValueError):
        return CameraProfile.model_validate(_FALLBACK_CAMERA)


def decode_image_bytes(data: bytes) -> np.ndarray | None:
    array = np.frombuffer(data, dtype=np.uint8)
    if array.size == 0:
        return None
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    return frame if frame is not None and frame.size else None


def middle_video_frame(data: bytes, suffix: str = ".mp4") -> np.ndarray:
    if suffix not in VIDEO_EXTENSIONS:
        suffix = ".mp4"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = Path(handle.name)
    try:
        handle.write(data)
        handle.close()
        capture = cv2.VideoCapture(str(path))
        try:
            if not capture.isOpened():
                raise ValueError("No se pudo leer el video.")
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if count > 1:
                capture.set(cv2.CAP_PROP_POS_FRAMES, count // 2)
            ok, frame = capture.read()
            if (not ok or frame is None) and count > 1:
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError("El video no contiene frames.")
            return frame
        finally:
            capture.release()
    finally:
        path.unlink(missing_ok=True)


def load_sample_frame(data: bytes, filename: str | None = None) -> np.ndarray:
    suffix = Path(filename or "").suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        frame = decode_image_bytes(data)
        if frame is None:
            raise ValueError("No se pudo leer la imagen.")
        return frame
    if suffix in VIDEO_EXTENSIONS:
        return middle_video_frame(data, suffix)

    frame = decode_image_bytes(data)
    if frame is not None:
        return frame
    return middle_video_frame(data, suffix or ".mp4")


def estimate_grass_hsv(frame: np.ndarray) -> HsvRange:
    """Percentile HSV bounds from greenish pixels in the lower-middle pitch."""
    height, width = frame.shape[:2]
    y0 = int(height * 0.50)
    y1 = max(y0 + 1, int(height * 0.88))
    x0 = int(width * 0.18)
    x1 = max(x0 + 1, int(width * 0.82))
    region = frame[y0:y1, x0:x1]
    if region.size == 0:
        return HsvRange.model_validate(FALLBACK_GRASS_HSV)

    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    greenish = (hue >= 25) & (hue <= 90) & (sat >= 25) & (val >= 25)
    pixels = hsv[greenish]
    if pixels.shape[0] < 200:
        return HsvRange.model_validate(FALLBACK_GRASS_HSV)

    lower = np.percentile(pixels, 5, axis=0)
    upper = np.percentile(pixels, 95, axis=0)
    lower = np.clip(lower - np.array([4.0, 12.0, 12.0]), [0, 0, 0], [179, 255, 255])
    upper = np.clip(upper + np.array([4.0, 24.0, 24.0]), [0, 0, 0], [179, 255, 255])
    if upper[0] < lower[0]:
        lower[0], upper[0] = upper[0], lower[0]
    return HsvRange(
        lower=[int(round(v)) for v in lower],
        upper=[int(round(v)) for v in upper],
    )


def propose_scoreboard_crop(frame: np.ndarray) -> FractionRect:
    """Use a bright top-left rectangle when one is obvious; else the default crop."""
    default = FractionRect.model_validate(DEFAULT_SCOREBOARD_CROP)
    height, width = frame.shape[:2]
    roi_h = max(8, int(height * 0.40))
    roi_w = max(8, int(width * 0.55))
    roi = frame[0:roi_h, 0:roi_w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 185, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return default

    min_area = 0.012 * height * width
    best: tuple[int, int, int, int] | None = None
    best_area = 0.0
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = float(w * h)
        if area < min_area or area <= best_area:
            continue
        if h < 8 or w < 24:
            continue
        if w / max(h, 1) < 1.35:
            continue
        if x > width * 0.12:
            continue
        if y > height * 0.12:
            continue
        best = (x, y, w, h)
        best_area = area

    if best is None:
        return default

    x, y, w, h = best
    return FractionRect(
        x=round(x / width, 4),
        y=round(y / height, 4),
        w=round(min(w / width, 1.0 - x / width), 4),
        h=round(min(h / height, 1.0 - y / height), 4),
    )


def _jpeg_b64(image: np.ndarray, max_width: int = 640) -> str:
    if image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        image = cv2.resize(
            image,
            (max_width, max(1, int(image.shape[0] * scale))),
            interpolation=cv2.INTER_AREA,
        )
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        return ""
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _crop_preview(frame: np.ndarray, crop: FractionRect) -> np.ndarray:
    height, width = frame.shape[:2]
    x0 = int(crop.x * width)
    y0 = int(crop.y * height)
    x1 = int((crop.x + crop.w) * width)
    y1 = int((crop.y + crop.h) * height)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, max(x0 + 1, x1)), min(height, max(y0 + 1, y1))
    return frame[y0:y1, x0:x1]


def _grass_mask_overlay(frame: np.ndarray, grass_hsv: HsvRange) -> np.ndarray:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array(grass_hsv.lower, dtype=np.uint8),
        np.array(grass_hsv.upper, dtype=np.uint8),
    )
    overlay = frame.copy()
    tint = overlay.copy()
    tint[:, :] = (40, 210, 40)
    overlay[mask > 0] = cv2.addWeighted(overlay, 0.45, tint, 0.55, 0)[mask > 0]
    return overlay


def propose_from_frame(frame: np.ndarray) -> tuple[CameraProfile, dict[str, str]]:
    template = template_camera()
    crop = propose_scoreboard_crop(frame)
    grass = estimate_grass_hsv(frame)
    camera = template.model_copy(
        update={
            "id": "default",
            "scoreboard_crop": crop,
            "grass_hsv": grass,
        }
    )
    previews = {
        "scoreboard_jpeg_b64": _jpeg_b64(_crop_preview(frame, crop)),
        "grass_mask_jpeg_b64": _jpeg_b64(_grass_mask_overlay(frame, grass)),
    }
    return camera, {key: value for key, value in previews.items() if value}


def persist_stadium(stadium: Stadium) -> dict:
    yaml_path = save_stadium_yaml(stadium)
    summary = db.upsert_stadium_profile(stadium)
    summary["yaml_path"] = str(yaml_path)
    return summary
