"""RapidOCR helpers shared by the scoreboard reader and the LED crop."""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np


logger = logging.getLogger(__name__)

_reader: Any | None = None
_reader_attempted = False


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


def texts_from_ocr_output(output: Any) -> list[str]:
    """Normalize RapidOCR's result shape across supported package versions."""
    if isinstance(output, tuple):
        output = output[0]
    if not isinstance(output, list):
        return []

    texts: list[str] = []
    for item in output:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            text = item[1]
            if isinstance(text, str):
                texts.append(text)
    return texts


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


def read_led_text(crop_bgr: np.ndarray | None) -> str:
    """OCR only the LED strip crop. Never the full frame."""
    if crop_bgr is None or crop_bgr.size == 0:
        return ""
    # Always upscale the short LED strip — cyan/yellow boards are often <40px tall.
    texts = [read_image_text(crop_bgr, min_side_for_upscale=10_000)]
    height = crop_bgr.shape[0]
    if height < 80:
        enlarged = cv2.resize(
            crop_bgr,
            None,
            fx=2.0,
            fy=2.0,
            interpolation=cv2.INTER_CUBIC,
        )
        texts.append(read_image_text(enlarged, min_side_for_upscale=10_000))
    # Deduplicate while preserving order.
    merged: list[str] = []
    seen: set[str] = set()
    for chunk in " ".join(texts).split():
        key = chunk.upper()
        if key not in seen:
            seen.add(key)
            merged.append(chunk)
    return " ".join(merged)
