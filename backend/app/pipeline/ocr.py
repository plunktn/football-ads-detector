"""RapidOCR helpers shared by the scoreboard reader and the LED crop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


logger = logging.getLogger(__name__)

_reader: Any | None = None
_reader_attempted = False


@dataclass(frozen=True)
class OcrHit:
    """One RapidOCR box on the LED crop. x_center is 0–1 across crop width."""

    text: str
    x_center: float


def get_ocr_reader() -> Any | None:
    """Load RapidOCR once so kickoff OCR and LED OCR share the same model."""
    global _reader, _reader_attempted
    if _reader_attempted:
        return _reader

    _reader_attempted = True
    try:
        from rapidocr_onnxruntime import RapidOCR

        _reader = RapidOCR()
    except Exception as exc:  # pragma: no cover - depends on local OCR install
        logger.warning("RapidOCR no disponible: %s", exc)
        _reader = None
    return _reader


def _items_from_ocr_output(output: Any) -> list[Any]:
    if isinstance(output, tuple):
        output = output[0]
    if not isinstance(output, list):
        return []
    return output


def texts_from_ocr_output(output: Any) -> list[str]:
    """Normalize RapidOCR's result shape across supported package versions."""
    texts: list[str] = []
    for item in _items_from_ocr_output(output):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = item[1]
            if isinstance(text, str):
                texts.append(text)
    return texts


def hits_from_ocr_output(output: Any, image_width: int) -> list[OcrHit]:
    """Keep RapidOCR boxes so brand matching can require repeated panels."""
    width = max(1, int(image_width))
    hits: list[OcrHit] = []
    for item in _items_from_ocr_output(output):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        text = item[1]
        if not isinstance(text, str) or not text.strip():
            continue
        x_center = 0.5
        box = item[0]
        xs: list[float] = []
        if isinstance(box, (list, tuple)):
            for point in box:
                if isinstance(point, (list, tuple)) and point:
                    try:
                        xs.append(float(point[0]))
                    except (TypeError, ValueError):
                        continue
                elif isinstance(point, (int, float)):
                    xs.append(float(point))
        if xs:
            x_center = float(np.clip((min(xs) + max(xs)) / 2.0 / width, 0.0, 1.0))
        hits.append(OcrHit(text=text, x_center=x_center))
    return hits


def read_image_text(image: np.ndarray, *, min_side_for_upscale: int = 160) -> str:
    """Run OCR on a BGR image; upscale small crops so thin LED type is readable."""
    if image is None or image.size == 0:
        return ""

    reader = get_ocr_reader()
    if reader is None:
        return ""

    try:
        texts = texts_from_ocr_output(reader(image))
        if min(image.shape[:2]) < min_side_for_upscale:
            enlarged = cv2.resize(
                image,
                None,
                fx=1.5,
                fy=1.5,
                interpolation=cv2.INTER_CUBIC,
            )
            texts.extend(texts_from_ocr_output(reader(enlarged)))
        return " ".join(texts)
    except Exception as exc:  # pragma: no cover - model/runtime dependent
        logger.debug("Falló OCR: %s", exc)
        return ""


def read_led_hits(crop_bgr: np.ndarray | None) -> list[OcrHit]:
    """OCR the LED strip once (upscaled) and keep boxes. Do not dedupe tokens."""
    if crop_bgr is None or crop_bgr.size == 0:
        return []

    reader = get_ocr_reader()
    if reader is None:
        return []

    image = crop_bgr
    if crop_bgr.shape[0] < 80:
        image = cv2.resize(
            crop_bgr,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC,
        )

    try:
        return hits_from_ocr_output(reader(image), image.shape[1])
    except Exception as exc:  # pragma: no cover - model/runtime dependent
        logger.debug("Falló OCR LED: %s", exc)
        return []


def read_led_text(crop_bgr: np.ndarray | None) -> str:
    """OCR only the LED strip crop. Never the full frame."""
    return " ".join(hit.text for hit in read_led_hits(crop_bgr))
