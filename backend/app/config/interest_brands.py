"""Brands of interest and the OCR aliases that resolve to them.

The list lives in ``backend/config/interest_brands.yaml``. Matching ignores
case, accents, and punctuation. Fixed-board matching does not use this module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "interest_brands.yaml"


def compact_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = text.upper().replace("&", " AND ")
    return re.sub(r"[^A-Z0-9]+", "", text)


@dataclass(frozen=True)
class InterestBrand:
    id: str
    name: str
    aliases: tuple[str, ...]
    legacy_ids: tuple[str, ...] = ()

    def keys(self) -> set[str]:
        found = {compact_key(self.id), compact_key(self.name)}
        found.update(compact_key(item) for item in self.legacy_ids)
        found.update(compact_key(item) for item in self.aliases)
        found.discard("")
        return found


@lru_cache(maxsize=4)
def load_interest_brands(path: str | None = None) -> tuple[InterestBrand, ...]:
    source = Path(path) if path else _DEFAULT_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    brands: list[InterestBrand] = []
    for item in raw.get("brands") or []:
        if not isinstance(item, dict):
            continue
        brand_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or brand_id).strip()
        if not brand_id or not name:
            continue
        aliases = tuple(
            str(alias).strip()
            for alias in (item.get("aliases") or [])
            if str(alias).strip()
        )
        legacy = tuple(
            str(legacy).strip()
            for legacy in (item.get("legacy_ids") or [])
            if str(legacy).strip()
        )
        brands.append(
            InterestBrand(id=brand_id, name=name, aliases=aliases, legacy_ids=legacy)
        )
    return tuple(brands)


def clear_interest_brand_cache() -> None:
    load_interest_brands.cache_clear()


def _index(brands: tuple[InterestBrand, ...]) -> dict[str, InterestBrand]:
    index: dict[str, InterestBrand] = {}
    for brand in brands:
        for key in brand.keys():
            index.setdefault(key, brand)
    return index


def resolve_interest_fragment(
    fragment: str,
    brands: tuple[InterestBrand, ...] | None = None,
) -> InterestBrand | None:
    """Map one OCR fragment or alias onto the canonical interest brand."""
    key = compact_key(fragment)
    if not key:
        return None
    catalog = brands if brands is not None else load_interest_brands()
    return _index(catalog).get(key)


def interest_aliases_for(name_or_id: str) -> tuple[str, ...]:
    """Aliases of the interest brand that ``name_or_id`` resolves to."""
    brand = resolve_interest_fragment(name_or_id)
    if brand is None:
        return ()
    names = [brand.name, *brand.aliases]
    return tuple(dict.fromkeys(names))


def canonical_alias_table() -> dict[str, tuple[str, ...]]:
    """Name → aliases, for the LED matcher. Includes the canonical name."""
    table: dict[str, tuple[str, ...]] = {}
    for brand in load_interest_brands():
        table[brand.name] = tuple(dict.fromkeys((brand.name, *brand.aliases)))
    return table


def matches_interest_brand(
    brand_id: str,
    brand_name: str,
    interest: InterestBrand,
) -> bool:
    keys = interest.keys()
    return compact_key(brand_id) in keys or compact_key(brand_name) in keys


def is_interest_brand(brand_id: str, brand_name: str = "") -> bool:
    catalog = load_interest_brands()
    for brand in catalog:
        if matches_interest_brand(brand_id, brand_name, brand):
            return True
    resolved = resolve_interest_fragment(brand_name) or resolve_interest_fragment(brand_id)
    return resolved is not None


def canonical_interest_name(brand_id: str, brand_name: str = "") -> str | None:
    for brand in load_interest_brands():
        if matches_interest_brand(brand_id, brand_name, brand):
            return brand.name
    resolved = resolve_interest_fragment(brand_name) or resolve_interest_fragment(brand_id)
    return resolved.name if resolved is not None else None


def alias_seed_rows() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Library ids → (display name, aliases), including legacy ids."""
    rows: dict[str, tuple[str, tuple[str, ...]]] = {}
    for brand in load_interest_brands():
        aliases = tuple(dict.fromkeys((brand.name, *brand.aliases)))
        rows[brand.id] = (brand.name, aliases)
        for legacy in brand.legacy_ids:
            rows[legacy] = (brand.name, aliases)
    return rows
