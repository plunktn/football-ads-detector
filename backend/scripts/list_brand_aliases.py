#!/usr/bin/env python3
"""Smoke: print brand id | nombre | aliases from the local SQLite library."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main() -> int:
    db.ensure_db()
    brands = db.list_brands()
    if not brands:
        print("(no brands in DB)")
        return 0
    for brand in brands:
        aliases = ", ".join(brand.get("aliases") or []) or "—"
        print(f"{brand['id']}\t{brand['nombre']}\t{aliases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
