"""Lightweight perceptual hashes for rough visual grouping of LED crops."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def dhash_hex(image_bgr: np.ndarray, hash_size: int = 8) -> str:
    """Difference hash as 16-char hex (64 bits when hash_size=8)."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(
        gray,
        (hash_size + 1, hash_size),
        interpolation=cv2.INTER_AREA,
    )
    diff = resized[:, 1:] > resized[:, :-1]
    bits = diff.flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    width = (hash_size * hash_size + 3) // 4
    return f"{value:0{width}x}"


def dhash_from_path(path: Path, hash_size: int = 8) -> str | None:
    if not path.is_file():
        return None
    image = cv2.imread(str(path))
    if image is None:
        return None
    return dhash_hex(image, hash_size=hash_size)


def hamming_hex(left: str, right: str) -> int:
    if not left or not right:
        return 64
    a = int(left, 16)
    b = int(right, 16)
    return (a ^ b).bit_count()


def order_by_similarity(
    items: list[dict],
    *,
    hash_key: str = "visual_hash",
    max_distance: int = 18,
) -> list[dict]:
    """Greedy clusters: similar hashes stay adjacent; returns items with similarity_group."""
    if not items:
        return []

    remaining = list(range(len(items)))
    ordered: list[dict] = []
    group_id = 0

    while remaining:
        seed = remaining.pop(0)
        seed_hash = str(items[seed].get(hash_key) or "")
        cluster = [seed]
        if seed_hash:
            kept: list[int] = []
            for index in remaining:
                other_hash = str(items[index].get(hash_key) or "")
                if other_hash and hamming_hex(seed_hash, other_hash) <= max_distance:
                    cluster.append(index)
                else:
                    kept.append(index)
            remaining = kept
        for index in cluster:
            row = dict(items[index])
            row["similarity_group"] = group_id
            ordered.append(row)
        group_id += 1

    return ordered
