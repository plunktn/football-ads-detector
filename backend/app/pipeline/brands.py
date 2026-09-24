"""Normalize brand names and fuzzy-match them against LED OCR text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Sequence

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein
from rapidfuzz.fuzz import partial_ratio_alignment

import cv2
import numpy as np

from ..config.aliases import aliases_for, is_overlay_name, resolve_catalog_name
from ..config.interest_brands import (
    canonical_alias_table,
    matches_interest_brand,
    resolve_interest_fragment,
)
from ..schemas import BrandInput
from .extract.template_match import DEFAULT_SCORE_THRESHOLD, detect_fixed_brands
from .ocr import OcrHit


# OCR garbles such as NETT OIUS live in config/interest_brands.yaml, not here.

_PARTIAL_RATIO_MIN = 86
_TOKEN_SET_RATIO_MIN = 86
_MIN_FUZZY_CHARS = 4
_MIN_PARTIAL_COVER = 0.75
_MIN_LED_REPEATS = 2
_MIN_SPATIAL_GAP = 0.08
_LIGAECUABET_COMPACT = "LIGAECUABET"


@dataclass(frozen=True)
class PreparedBrand:
    id: str
    name: str
    needles: tuple[str, ...]


def _strong_partial_match(needle: str, haystack: str) -> bool:
    """Reject weak partial hits like matching only PLUS inside NET PLUS."""
    if not needle or not haystack:
        return False
    alignment = partial_ratio_alignment(needle, haystack)
    if alignment is None or alignment.score < _PARTIAL_RATIO_MIN:
        return False
    matched = max(0, alignment.dest_end - alignment.dest_start)
    return matched >= max(_MIN_FUZZY_CHARS, int(round(_MIN_PARTIAL_COVER * len(needle))))


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.upper()
    s = s.replace("&", " AND ")
    # Brand-style plus ("NETT+", "+PLUS") — never phone numbers like "+593".
    s = re.sub(r"(?<=[A-Z])\+|\+(?=[A-Z])", " PLUS ", s)
    s = s.replace("+", " ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _compact(s: str) -> str:
    return s.replace(" ", "")


def _is_ecuabet_brand(brand: PreparedBrand) -> bool:
    compact_name = _compact(norm(brand.name))
    if compact_name in {"ECUABET", "ECUEBET"}:
        return True
    return any(
        _compact(needle) in {"ECUABET", "ECUEBET"} for needle in brand.needles
    )


def _is_nettplus_brand(brand: PreparedBrand) -> bool:
    compact_name = _compact(norm(brand.name))
    if compact_name in {"NETTPLUS", "NETPLUS"}:
        return True
    return any(_compact(needle) in {"NETTPLUS", "NETPLUS"} for needle in brand.needles)


def _plus_like(tail: str) -> bool:
    """True for PLUS and the cyan-LED OCR confusions (OIUS, OLUS, PIUS, …)."""
    if len(tail) < 3:
        return False
    if tail[:3] in {"PLU", "PIU", "OIU", "OLU", "DIU", "PLV"}:
        return True
    if len(tail) >= 4:
        return Levenshtein.distance(tail[:4], "PLUS") <= 2
    return False


def _count_nettplus_stems(compact_hay: str) -> int:
    """Count NETT+PLUS-like repeats, even when OCR garbles PLUS."""
    if not compact_hay:
        return 0
    count = 0
    index = 0
    while True:
        start = compact_hay.find("NETT", index)
        if start < 0:
            return count
        tail = compact_hay[start + 4 : start + 8]
        if _plus_like(tail):
            count += 1
            index = start + 8
        else:
            index = start + 4


def _strip_ligaecuabet(haystack: str, compact_hay: str) -> tuple[str, str]:
    """Fixed midfield board says LIGAECUABET; LED campaign says ECUABET."""
    compact_hay = compact_hay.replace(_LIGAECUABET_COMPACT, "")
    haystack = re.sub(r"LIGA\s*ECUABET", " ", haystack)
    haystack = re.sub(r"\s+", " ", haystack).strip()
    return haystack, compact_hay


def _canonical_aliases_for(normalized_name: str) -> tuple[str, ...]:
    compact_name = _compact(normalized_name)
    merged: list[str] = []
    for key, aliases in canonical_alias_table().items():
        variants = {_compact(norm(key)), *(_compact(norm(alias)) for alias in aliases)}
        if compact_name in variants:
            merged.extend(aliases)
    merged.extend(aliases_for(normalized_name))
    resolved = resolve_interest_fragment(normalized_name)
    if resolved is not None:
        merged.extend(resolved.aliases)
        merged.append(resolved.name)
    return tuple(dict.fromkeys(merged))


def generate_aliases(name: str, extra: list[str] | None = None) -> list[str]:
    """Always emit space-stripped / PLUS variants plus the PLAN.md strong aliases."""
    seeds = [name, *(extra or [])]
    aliases: set[str] = set()
    normalized_name = norm(name)

    for seed in seeds:
        value = norm(seed)
        if not value:
            continue
        aliases.add(value)
        aliases.add(_compact(value))
        if " PLUS" in value:
            aliases.add(value.replace(" PLUS", "PLUS"))

    for alias in _canonical_aliases_for(normalized_name):
        value = norm(alias)
        aliases.add(value)
        aliases.add(_compact(value))

    cleaned = {item for item in aliases if len(_compact(item)) >= _MIN_FUZZY_CHARS}
    return sorted(cleaned)


def prepare_brands(brands: list[BrandInput]) -> list[PreparedBrand]:
    prepared: list[PreparedBrand] = []
    for brand in brands:
        brand_id = brand.id or _compact(norm(brand.name)).lower() or "brand"
        needles = generate_aliases(brand.name, brand.aliases)
        name_n = norm(brand.name)
        if name_n and name_n not in needles:
            needles = [name_n, *needles]
        prepared.append(
            PreparedBrand(id=brand_id, name=brand.name, needles=tuple(needles))
        )
    return prepared


def _needles_for_count(brand: PreparedBrand) -> list[str]:
    needles = list(brand.needles)
    name_n = norm(brand.name)
    if name_n:
        needles.append(name_n)
        needles.append(_compact(name_n))
    unique: list[str] = []
    seen: set[str] = set()
    for needle in needles:
        compact = _compact(needle)
        if len(compact) < _MIN_FUZZY_CHARS or compact in seen:
            continue
        seen.add(compact)
        unique.append(compact)
    unique.sort(key=len, reverse=True)
    return unique


def _count_disjoint_spans(compact_hay: str, needles: Sequence[str]) -> int:
    if not compact_hay:
        return 0
    spans: list[tuple[int, int]] = []
    for needle in needles:
        start = 0
        while True:
            idx = compact_hay.find(needle, start)
            if idx < 0:
                break
            spans.append((idx, idx + len(needle)))
            start = idx + len(needle)
    if not spans:
        return 0
    spans.sort()
    merged = [spans[0]]
    for lo, hi in spans[1:]:
        prev_lo, prev_hi = merged[-1]
        if lo < prev_hi:
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))
    return len(merged)


def _prepared_is_interest(brand: PreparedBrand, fragment: str) -> bool:
    resolved = resolve_interest_fragment(fragment)
    if resolved is None:
        return False
    if matches_interest_brand(brand.id, brand.name, resolved):
        return True
    for needle in brand.needles:
        if matches_interest_brand(needle, needle, resolved):
            return True
    return False


def _box_matches_brand(brand: PreparedBrand, raw_text: str) -> bool:
    if _prepared_is_interest(brand, raw_text):
        return True
    haystack = norm(raw_text)
    if not haystack:
        return False
    compact_hay = _compact(haystack)
    if _is_ecuabet_brand(brand):
        haystack, compact_hay = _strip_ligaecuabet(haystack, compact_hay)
    if not compact_hay:
        return False
    if _count_disjoint_spans(compact_hay, _needles_for_count(brand)) >= 1:
        return True
    if _is_nettplus_brand(brand) and _count_nettplus_stems(compact_hay) >= 1:
        return True
    if len(compact_hay) < _MIN_FUZZY_CHARS:
        return False
    name_n = norm(brand.name)
    if name_n and _strong_partial_match(name_n, haystack):
        return True
    for needle in brand.needles:
        if len(_compact(needle)) < _MIN_FUZZY_CHARS:
            continue
        if _strong_partial_match(needle, haystack):
            return True
    if (
        name_n
        and len(_compact(name_n)) >= _MIN_FUZZY_CHARS
        and len(compact_hay) >= len(_compact(name_n)) - 1
        and fuzz.token_set_ratio(name_n, haystack) >= _TOKEN_SET_RATIO_MIN
        and _compact(name_n)[:4] in compact_hay
    ):
        return True
    return False


def _count_spatial_hits(brand: PreparedBrand, hits: Sequence[OcrHit]) -> int:
    xs = sorted(hit.x_center for hit in hits if _box_matches_brand(brand, hit.text))
    if not xs:
        return 0
    clustered = 1
    last = xs[0]
    for x in xs[1:]:
        if x - last >= _MIN_SPATIAL_GAP:
            clustered += 1
            last = x
    return clustered


def _count_token_windows(brand: PreparedBrand, haystack: str) -> int:
    """Count non-overlapping token groups that each look like the brand."""
    tokens = haystack.split()
    if not tokens:
        return 0
    count = 0
    index = 0
    while index < len(tokens):
        matched = False
        max_width = min(6, len(tokens) - index)
        for width in range(1, max_width + 1):
            chunk = " ".join(tokens[index : index + width])
            if _box_matches_brand(brand, chunk):
                count += 1
                index += width
                matched = True
                break
        if not matched:
            index += 1
    return count


def count_brand_hits(
    brand: PreparedBrand,
    raw_text: str,
    hits: Sequence[OcrHit] | None = None,
) -> int:
    """How many distinct LED-panel repeats of this brand are in the crop."""
    haystack = norm(raw_text)
    compact_hay = _compact(haystack)
    if _is_ecuabet_brand(brand):
        haystack, compact_hay = _strip_ligaecuabet(haystack, compact_hay)

    text_hits = max(
        _count_disjoint_spans(compact_hay, _needles_for_count(brand)),
        _count_token_windows(brand, haystack),
    )
    if _is_nettplus_brand(brand):
        text_hits = max(text_hits, _count_nettplus_stems(compact_hay))
    spatial_hits = _count_spatial_hits(brand, hits) if hits else 0
    return max(text_hits, spatial_hits)


def brand_present(
    brand: PreparedBrand,
    raw_text: str,
    hits: Sequence[OcrHit] | None = None,
    *,
    min_repeats: int = _MIN_LED_REPEATS,
) -> bool:
    """True when the brand is visible at least ``min_repeats`` times."""
    return count_brand_hits(brand, raw_text, hits) >= min_repeats


def filter_overlay_hits(hits: Sequence[OcrHit] | None) -> list[OcrHit]:
    if not hits:
        return []
    return [hit for hit in hits if not is_overlay_name(hit.text)]


def _strip_overlay_words(raw: str) -> str:
    kept = [token for token in norm(raw).split() if not is_overlay_name(token)]
    return " ".join(kept)


def match_brand_ids(
    raw_text: str,
    brands: list[PreparedBrand],
    hits: Sequence[OcrHit] | None = None,
    *,
    min_repeats: int = _MIN_LED_REPEATS,
) -> set[str]:
    """Return the set of brand ids visible in one OCR string.

    Fuzzy thresholds (rapidfuzz): partial_ratio and token_set_ratio ≥ 86
    (``_PARTIAL_RATIO_MIN`` / ``_TOKEN_SET_RATIO_MIN``). Needles come from the
    brand name, DB aliases, the playlist alias table, and
    ``config/interest_brands.yaml``. An OCR fragment that resolves to an
    interest brand counts for that canonical brand.
    LED rows require ``min_repeats`` (default 2) spatial/text repeats.
    """
    clean_hits = filter_overlay_hits(hits) if hits is not None else None
    haystack = (
        " ".join(hit.text for hit in clean_hits)
        if clean_hits
        else _strip_overlay_words(raw_text)
    )
    return {
        brand.id
        for brand in brands
        if not is_overlay_name(brand.name)
        and brand_present(brand, haystack, clean_hits, min_repeats=min_repeats)
    }


def brands_from_names(names: Sequence[str]) -> list[BrandInput]:
    """Build catalog brands from playlist client names, dropping TV overlays."""
    prepared: list[BrandInput] = []
    used: set[str] = set()
    for raw in names:
        if not str(raw).strip() or is_overlay_name(raw):
            continue
        catalog = resolve_catalog_name(raw)
        brand_id = _compact(norm(catalog)).lower() or "brand"
        if brand_id in used:
            continue
        used.add(brand_id)
        extra = list(aliases_for(catalog))
        if raw.strip() not in extra:
            extra.append(raw.strip())
        prepared.append(BrandInput(id=brand_id, name=catalog, aliases=extra))
    return prepared


def _load_logo_bgr(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return None
    return image


def match_fixed_brand_ids(
    crop_bgr: np.ndarray,
    brands: list[BrandInput],
    *,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> set[str]:
    """FIXED_PRINT path: brands with a loaded logo are matched visually, not via OCR."""
    pairs = [(brand, _load_logo_bgr(brand.logo_path)) for brand in brands]
    return {
        hit["brand_id"]
        for hit in detect_fixed_brands(
            crop_bgr,
            pairs,
            score_threshold=score_threshold,
        )
    }
