"""Configurable OCR/playlist → catalog brand names and TV-overlay denylist."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml


_ALIASES_PATH = Path(__file__).with_name("brand_aliases.yaml")


def _norm_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    text = text.upper()
    text = text.replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", "", text)
    return text


@lru_cache(maxsize=1)
def load_alias_table(path: str | Path | None = None) -> dict[str, tuple[str, ...]]:
    source = Path(path) if path is not None else _ALIASES_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    catalog = raw.get("catalog") or {}
    table: dict[str, tuple[str, ...]] = {}
    for canonical, aliases in catalog.items():
        names = [str(canonical)]
        if isinstance(aliases, list):
            names.extend(str(item) for item in aliases if str(item).strip())
        table[str(canonical)] = tuple(dict.fromkeys(names))
    return table


@lru_cache(maxsize=1)
def overlay_ignore_names(path: str | Path | None = None) -> tuple[str, ...]:
    source = Path(path) if path is not None else _ALIASES_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    items = raw.get("overlay_ignore") or []
    return tuple(str(item) for item in items if str(item).strip())


def resolve_catalog_name(raw: str, table: dict[str, tuple[str, ...]] | None = None) -> str:
    """Map a playlist/OCR string onto the catalog name when an alias hits."""
    needle = _norm_key(raw)
    if not needle:
        return raw.strip()
    mapping = table if table is not None else load_alias_table()
    for canonical, aliases in mapping.items():
        variants = {_norm_key(canonical), *(_norm_key(alias) for alias in aliases)}
        if needle in variants:
            return canonical
    return raw.strip()


def aliases_for(name: str, table: dict[str, tuple[str, ...]] | None = None) -> tuple[str, ...]:
    mapping = table if table is not None else load_alias_table()
    resolved = resolve_catalog_name(name, mapping)
    if resolved in mapping:
        return mapping[resolved]
    compact = _norm_key(name)
    for canonical, aliases in mapping.items():
        variants = {_norm_key(canonical), *(_norm_key(alias) for alias in aliases)}
        if compact in variants:
            return aliases
    return ()


def overlay_needles(path: str | Path | None = None) -> tuple[str, ...]:
    return tuple(_norm_key(name) for name in overlay_ignore_names(path) if _norm_key(name))


def is_overlay_name(raw: str, needles: tuple[str, ...] | None = None) -> bool:
    compact = _norm_key(raw)
    if not compact:
        return False
    tokens = needles if needles is not None else overlay_needles()
    return any(token and token in compact for token in tokens)
