"""Normalize brand names and fuzzy-match them against LED OCR text."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..schemas import BrandInput


# Canonical example from PLAN.md §2 / Fase 5. Merged whenever the user
# name is a close variant of these brands.
_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "NETT PLUS": ("NETTPLUS", "NETPLUS", "NET PLUS", "NETT PLUS"),
    "LIONS SPORTS AND MEDIA": (
        "LIONS SPORTS AND MEDIA",
        "LIONS SPORT AND MEDIA",
        "LIONS SPORTS MEDIA",
    ),
}

_PARTIAL_RATIO_MIN = 82
_TOKEN_SET_RATIO_MIN = 80
_MIN_FUZZY_CHARS = 4


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.upper()
    s = s.replace("&", " AND ")
    s = s.replace("+", " PLUS ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _compact(s: str) -> str:
    return s.replace(" ", "")


def _canonical_aliases_for(normalized_name: str) -> tuple[str, ...]:
    compact_name = _compact(normalized_name)
    for key, aliases in _CANONICAL_ALIASES.items():
        variants = {_compact(norm(key)), *(_compact(norm(alias)) for alias in aliases)}
        if compact_name in variants:
            return aliases
    return ()


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


@dataclass(frozen=True)
class PreparedBrand:
    id: str
    name: str
    needles: tuple[str, ...]


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


def brand_present(brand: PreparedBrand, raw_text: str) -> bool:
    haystack = norm(raw_text)
    if not haystack:
        return False

    for needle in brand.needles:
        if needle and needle in haystack:
            return True
        compact_needle = _compact(needle)
        if compact_needle and compact_needle in _compact(haystack):
            return True

    name_n = norm(brand.name)
    if not name_n:
        return False

    if fuzz.partial_ratio(name_n, haystack) >= _PARTIAL_RATIO_MIN:
        return True
    if (
        len(_compact(name_n)) >= _MIN_FUZZY_CHARS
        and fuzz.token_set_ratio(name_n, haystack) >= _TOKEN_SET_RATIO_MIN
    ):
        return True

    for needle in brand.needles:
        if len(_compact(needle)) < _MIN_FUZZY_CHARS:
            continue
        if fuzz.partial_ratio(needle, haystack) >= _PARTIAL_RATIO_MIN:
            return True
    return False


def match_brand_ids(raw_text: str, brands: list[PreparedBrand]) -> set[str]:
    """Return the set of brand ids visible in one LED OCR string."""
    return {brand.id for brand in brands if brand_present(brand, raw_text)}
