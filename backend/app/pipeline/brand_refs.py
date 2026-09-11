"""Extract and deduplicate visual references for brand matching (phase 1: storage)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app.pipeline.phash import dhash_hex, hamming_hex

MAX_VIDEO_FRAMES = 32
DEFAULT_SAMPLE_FPS = 1.0
DEFAULT_DEDUPE_DISTANCE = 12


def _is_similar_to_any(frame_hash: str, seen: list[str], max_distance: int) -> bool:
    for existing in seen:
        if hamming_hex(frame_hash, existing) <= max_distance:
            return True
    return False


def extract_video_keyframes(
    video_path: Path,
    output_dir: Path,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    max_frames: int = MAX_VIDEO_FRAMES,
    dedupe_distance: int = DEFAULT_DEDUPE_DISTANCE,
    jpeg_quality: int = 88,
) -> list[tuple[str, Path]]:
    """Sample ~1 fps, dedupe similar frames, save up to ``max_frames`` JPEGs.

    Returns ``(ref_id, path)`` pairs where ``ref_id`` is the filename stem.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video: {video_path}")

    saved: list[tuple[str, Path]] = []
    seen_hashes: list[str] = []
    frame_idx = 0

    try:
        native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if native_fps <= 0:
            native_fps = 25.0
        frame_interval = max(1, int(round(native_fps / sample_fps)))

        while len(saved) < max_frames:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if frame_idx % frame_interval == 0:
                frame_hash = dhash_hex(frame)
                if not _is_similar_to_any(frame_hash, seen_hashes, dedupe_distance):
                    ref_id = uuid4().hex
                    dest = output_dir / f"{ref_id}.jpg"
                    encoded, buffer = cv2.imencode(
                        ".jpg",
                        frame,
                        [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
                    )
                    if encoded:
                        dest.write_bytes(buffer.tobytes())
                        saved.append((ref_id, dest))
                        seen_hashes.append(frame_hash)
            frame_idx += 1
    finally:
        cap.release()

    return saved


def save_image_bytes(data: bytes, destination: Path) -> None:
    """Decode image bytes and persist as JPEG or PNG at ``destination``."""
    if not data:
        raise ValueError("La imagen está vacía.")
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("No se pudo decodificar la imagen.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    if suffix == ".png":
        ok = cv2.imwrite(str(destination), image)
    else:
        ok = cv2.imwrite(
            str(destination),
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), 88],
        )
    if not ok:
        raise ValueError("No se pudo guardar la imagen.")
