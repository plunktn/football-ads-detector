"""Minimal SQLite persistence for stadiums and camera profiles."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.domain.stadium import Stadium

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
BRANDS_DIR = PROJECT_ROOT / "data" / "brands"
_STADIUMS_YAML_DIR = PROJECT_ROOT / "config" / "stadiums"

_db_path: Path | None = None


def get_db_path() -> Path:
    if _db_path is not None:
        return _db_path
    return DEFAULT_DB_PATH


def set_db_path(path: Path) -> None:
    global _db_path
    _db_path = path


def reset_db_path() -> None:
    global _db_path
    _db_path = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stadiums (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                pais TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS camera_profiles (
                id TEXT PRIMARY KEY,
                stadium_id TEXT NOT NULL,
                variante TEXT NOT NULL,
                version INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (stadium_id) REFERENCES stadiums(id)
            );

            CREATE TABLE IF NOT EXISTS brands (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                logo_path TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                stadium_id TEXT,
                profile_id TEXT,
                mode TEXT NOT NULL,
                duration_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0.0,
                progress_label TEXT NOT NULL DEFAULT '',
                error TEXT,
                kickoff_json TEXT,
                result_json TEXT,
                directory TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS brand_groups (
                id TEXT PRIMARY KEY,
                titulo TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                half TEXT NOT NULL,
                frame_idx INTEGER NOT NULL,
                time_seconds REAL NOT NULL,
                zone_id TEXT,
                posicion TEXT,
                crop_relpath TEXT,
                context_relpath TEXT,
                visual_hash TEXT,
                ocr_text TEXT,
                machine_label TEXT NOT NULL,
                brand_id TEXT,
                machine_brand_ids_json TEXT DEFAULT '[]',
                user_verdict TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS exposure_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                brand_id TEXT NOT NULL,
                brand_name TEXT NOT NULL,
                zone_id TEXT,
                posicion TEXT,
                half TEXT NOT NULL,
                clock_start TEXT NOT NULL,
                clock_end TEXT NOT NULL,
                video_seconds_start REAL NOT NULL,
                video_seconds_end REAL NOT NULL,
                start_frame INTEGER NOT NULL,
                end_frame INTEGER NOT NULL,
                duration_seconds INTEGER NOT NULL,
                area_visible_ratio REAL,
                confianza REAL,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_created_at
                ON jobs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_exposure_segments_job_id
                ON exposure_segments(job_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_job_frames_lookup
                ON job_frames(job_id, half, frame_idx, zone_id);

            CREATE TABLE IF NOT EXISTS brand_refs (
                id TEXT PRIMARY KEY,
                brand_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                source_name TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_brand_refs_brand_id
                ON brand_refs(brand_id);
            """
        )
        _migrate_schema(conn)
        conn.commit()


def _ligaecuabet_fallback() -> Stadium:
    """Hardcoded profile matching scoreboard.py and roi.py defaults."""
    return Stadium.model_validate(
        {
            "id": "ligaecuabet",
            "nombre": "Liga Ecuabét",
            "pais": "Ecuador",
            "default_camera": "default",
            "camera": {
                "id": "default",
                "variante": "default",
                "scoreboard_crop": {"x": 0.0, "y": 0.0, "w": 0.42, "h": 0.22},
                "grass_hsv": {"lower": [28, 25, 30], "upper": [85, 255, 255]},
                "led_band": {
                    "top_frac": 0.12,
                    "height_frac": 0.055,
                    "min_height_px": 28,
                    "max_height_px": 90,
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
            },
        }
    )


def _load_stadium_from_yaml(path: Path) -> Stadium:
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return Stadium.model_validate(raw)


def _insert_stadium(conn: sqlite3.Connection, stadium: Stadium) -> None:
    now = _utc_now()
    conn.execute(
        """
        INSERT OR IGNORE INTO stadiums (id, nombre, pais, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (stadium.id, stadium.nombre, stadium.pais, now),
    )
    profile_id = f"{stadium.id}:{stadium.camera.id}"
    conn.execute(
        """
        INSERT OR IGNORE INTO camera_profiles (
            id, stadium_id, variante, version, config_json, activo, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile_id,
            stadium.id,
            stadium.camera.variante,
            1,
            stadium.camera.model_dump_json(),
            1,
            now,
        ),
    )


def seed_stadiums() -> None:
    """Populate stadiums from YAML configs, or ligaecuabet fallback if none exist."""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM stadiums").fetchone()[0]
        if count > 0:
            return

        yaml_files = (
            sorted(_STADIUMS_YAML_DIR.glob("*.yaml"))
            if _STADIUMS_YAML_DIR.is_dir()
            else []
        )
        if yaml_files:
            for path in yaml_files:
                _insert_stadium(conn, _load_stadium_from_yaml(path))
        else:
            _insert_stadium(conn, _ligaecuabet_fallback())
        conn.commit()


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl: str,
) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add catalog tables/columns to existing local SQLite files."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS brand_groups (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            half TEXT NOT NULL,
            frame_idx INTEGER NOT NULL,
            time_seconds REAL NOT NULL,
            zone_id TEXT,
            posicion TEXT,
            crop_relpath TEXT,
            context_relpath TEXT,
            visual_hash TEXT,
            ocr_text TEXT,
            machine_label TEXT NOT NULL,
            brand_id TEXT,
            machine_brand_ids_json TEXT DEFAULT '[]',
            user_verdict TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_job_frames_lookup
            ON job_frames(job_id, half, frame_idx, zone_id);

        CREATE TABLE IF NOT EXISTS brand_refs (
            id TEXT PRIMARY KEY,
            brand_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            source_name TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_brand_refs_brand_id
            ON brand_refs(brand_id);
        """
    )
    if "brands" in {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }:
        _add_column_if_missing(conn, "brands", "group_id", "group_id TEXT")
        _add_column_if_missing(
            conn, "brands", "activo", "activo INTEGER NOT NULL DEFAULT 1"
        )
    if "jobs" in {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }:
        _add_column_if_missing(
            conn, "jobs", "catalog_confirmed_at", "catalog_confirmed_at TEXT"
        )
        _add_column_if_missing(
            conn,
            "jobs",
            "catalog_discarded_count",
            "catalog_discarded_count INTEGER NOT NULL DEFAULT 0",
        )
    if "job_frames" in {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }:
        _add_column_if_missing(
            conn, "job_frames", "context_relpath", "context_relpath TEXT"
        )
        _add_column_if_missing(
            conn, "job_frames", "visual_hash", "visual_hash TEXT"
        )


DEFAULT_BRAND_GROUP_ID = "ligaecuabet"
DEFAULT_BRAND_GROUP_TITLE = "LigaEcuabet"


def _slug_id(value: str, fallback: str = "grupo") -> str:
    normalized = "".join(
        char.lower() if char.isalnum() else "-" for char in value.strip()
    )
    return "-".join(part for part in normalized.split("-") if part) or fallback


def seed_brand_groups() -> None:
    """Create LigaEcuabet group and attach ungrouped legacy brands."""
    now = _utc_now()
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM brand_groups").fetchone()[0]
        if count == 0:
            conn.execute(
                """
                INSERT INTO brand_groups (id, titulo, created_at)
                VALUES (?, ?, ?)
                """,
                (DEFAULT_BRAND_GROUP_ID, DEFAULT_BRAND_GROUP_TITLE, now),
            )
        liga = conn.execute(
            "SELECT id FROM brand_groups WHERE id = ? LIMIT 1",
            (DEFAULT_BRAND_GROUP_ID,),
        ).fetchone()
        if liga is not None:
            conn.execute(
                "UPDATE brands SET group_id = ? WHERE group_id IS NULL",
                (DEFAULT_BRAND_GROUP_ID,),
            )
        conn.commit()


def ensure_db() -> None:
    init_db()
    seed_stadiums()
    seed_brand_groups()


def list_stadium_summaries() -> list[dict[str, str]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, nombre FROM stadiums ORDER BY nombre COLLATE NOCASE"
        ).fetchall()
    return [{"id": row["id"], "nombre": row["nombre"]} for row in rows]


def stadium_exists(stadium_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM stadiums WHERE id = ? LIMIT 1",
            (stadium_id,),
        ).fetchone()
    return row is not None


def _brand_has_logo(logo_path: str | None) -> bool:
    if not logo_path:
        return False
    return Path(logo_path).is_file()


def _brand_row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    activo = True
    if "activo" in keys:
        activo = True if row["activo"] is None else bool(row["activo"])
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "aliases": json.loads(row["aliases_json"] or "[]"),
        "has_logo": _brand_has_logo(row["logo_path"]),
        "group_id": row["group_id"] if "group_id" in keys else None,
        "activo": activo,
    }


def _default_group_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT id FROM brand_groups WHERE id = ? LIMIT 1",
        (DEFAULT_BRAND_GROUP_ID,),
    ).fetchone()
    if row is not None:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM brand_groups ORDER BY created_at ASC LIMIT 1"
    ).fetchone()
    return row["id"] if row is not None else None


def list_brand_groups() -> list[dict[str, Any]]:
    with get_connection() as conn:
        groups = conn.execute(
            "SELECT id, titulo, created_at FROM brand_groups ORDER BY titulo COLLATE NOCASE"
        ).fetchall()
        brand_rows = conn.execute(
            """
            SELECT id, nombre, aliases_json, logo_path, group_id, activo
            FROM brands
            ORDER BY nombre COLLATE NOCASE
            """
        ).fetchall()
    by_group: dict[str, list[dict[str, Any]]] = {row["id"]: [] for row in groups}
    for brand in brand_rows:
        public = _brand_row_to_public(brand)
        group_id = public.get("group_id")
        if group_id in by_group:
            by_group[group_id].append(public)
    return [
        {
            "id": row["id"],
            "titulo": row["titulo"],
            "created_at": row["created_at"],
            "brands": by_group.get(row["id"], []),
        }
        for row in groups
    ]


def create_brand_group(titulo: str) -> str:
    titulo = titulo.strip()
    if not titulo:
        raise ValueError("titulo es obligatorio.")
    base = _slug_id(titulo)
    group_id = base
    suffix = 2
    now = _utc_now()
    with get_connection() as conn:
        while conn.execute(
            "SELECT 1 FROM brand_groups WHERE id = ? LIMIT 1",
            (group_id,),
        ).fetchone() is not None:
            group_id = f"{base}-{suffix}"
            suffix += 1
        conn.execute(
            """
            INSERT INTO brand_groups (id, titulo, created_at)
            VALUES (?, ?, ?)
            """,
            (group_id, titulo, now),
        )
        conn.commit()
    return group_id


def delete_brand_group(group_id: str) -> None:
    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM brand_groups WHERE id = ? LIMIT 1",
            (group_id,),
        ).fetchone()
        if exists is None:
            raise KeyError(group_id)
        count = conn.execute(
            "SELECT COUNT(*) FROM brands WHERE group_id = ?",
            (group_id,),
        ).fetchone()[0]
        if count:
            raise ValueError("El grupo todavía tiene marcas.")
        conn.execute("DELETE FROM brand_groups WHERE id = ?", (group_id,))
        conn.commit()


def list_brands() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, nombre, aliases_json, logo_path, group_id, activo
            FROM brands
            ORDER BY nombre COLLATE NOCASE
            """
        ).fetchall()
    return [_brand_row_to_public(row) for row in rows]


def get_brand(brand_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, nombre, aliases_json, logo_path, created_at, group_id, activo
            FROM brands WHERE id = ? LIMIT 1
            """,
            (brand_id,),
        ).fetchone()
    if row is None:
        return None
    public = _brand_row_to_public(row)
    public["logo_path"] = row["logo_path"]
    public["created_at"] = row["created_at"]
    return public


def upsert_brand(
    brand_id: str,
    nombre: str,
    aliases: list[str] | None = None,
    logo_path: str | None = None,
    group_id: str | None = None,
    activo: int | bool | None = None,
) -> dict[str, Any]:
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    now = _utc_now()
    activo_value = 1 if activo is None else int(bool(activo))
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT logo_path, group_id, activo FROM brands WHERE id = ? LIMIT 1",
            (brand_id,),
        ).fetchone()
        resolved_logo_path = logo_path
        if resolved_logo_path is None and existing is not None:
            resolved_logo_path = existing["logo_path"]
        resolved_group = group_id
        if resolved_group is None and existing is not None:
            resolved_group = existing["group_id"]
        if resolved_group is None:
            resolved_group = _default_group_id(conn)
        if existing is not None and activo is None:
            activo_value = int(existing["activo"] if existing["activo"] is not None else 1)
        if resolved_group is not None:
            group_row = conn.execute(
                "SELECT 1 FROM brand_groups WHERE id = ? LIMIT 1",
                (resolved_group,),
            ).fetchone()
            if group_row is None:
                raise ValueError(f"group_id desconocido: {resolved_group!r}.")
        conn.execute(
            """
            INSERT INTO brands (
                id, nombre, aliases_json, logo_path, created_at, group_id, activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                nombre = excluded.nombre,
                aliases_json = excluded.aliases_json,
                logo_path = COALESCE(excluded.logo_path, brands.logo_path),
                group_id = COALESCE(excluded.group_id, brands.group_id),
                activo = excluded.activo
            """,
            (
                brand_id,
                nombre,
                aliases_json,
                resolved_logo_path,
                now,
                resolved_group,
                activo_value,
            ),
        )
        conn.commit()
    brand = get_brand(brand_id)
    assert brand is not None
    return brand


def update_brand(brand_id: str, **fields: Any) -> dict[str, Any]:
    existing = get_brand(brand_id)
    if existing is None:
        raise KeyError(brand_id)
    allowed = {"nombre", "aliases", "activo", "group_id", "logo_path"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Campos no válidos: {', '.join(sorted(unknown))}.")
    assignments: list[str] = []
    values: list[Any] = []
    if "nombre" in fields and fields["nombre"] is not None:
        nombre = str(fields["nombre"]).strip()
        if not nombre:
            raise ValueError("nombre es obligatorio.")
        assignments.append("nombre = ?")
        values.append(nombre)
    if "aliases" in fields and fields["aliases"] is not None:
        assignments.append("aliases_json = ?")
        values.append(json.dumps(list(fields["aliases"]), ensure_ascii=False))
    if "activo" in fields and fields["activo"] is not None:
        assignments.append("activo = ?")
        values.append(int(bool(fields["activo"])))
    if "group_id" in fields and fields["group_id"] is not None:
        with get_connection() as conn:
            group_row = conn.execute(
                "SELECT 1 FROM brand_groups WHERE id = ? LIMIT 1",
                (fields["group_id"],),
            ).fetchone()
        if group_row is None:
            raise ValueError(f"group_id desconocido: {fields['group_id']!r}.")
        assignments.append("group_id = ?")
        values.append(fields["group_id"])
    if "logo_path" in fields and fields["logo_path"] is not None:
        assignments.append("logo_path = ?")
        values.append(fields["logo_path"])
    if not assignments:
        return existing
    values.append(brand_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE brands SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        conn.commit()
    brand = get_brand(brand_id)
    assert brand is not None
    return brand


def delete_brand(brand_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM brands WHERE id = ?", (brand_id,))
        conn.commit()
        return cursor.rowcount > 0


def brand_refs_dir(brand_id: str) -> Path:
    return BRANDS_DIR / brand_id / "refs"


def _brand_ref_row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    brand_id = row["brand_id"]
    return {
        "id": row["id"],
        "brand_id": brand_id,
        "kind": row["kind"],
        "source_name": row["source_name"],
        "path": row["path"],
        "created_at": row["created_at"],
        "image_url": f"/brands/{brand_id}/refs/{row['id']}/image",
    }


def list_brand_refs(brand_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, brand_id, kind, path, source_name, created_at
            FROM brand_refs
            WHERE brand_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (brand_id,),
        ).fetchall()
    return [_brand_ref_row_to_public(row) for row in rows]


def get_brand_ref(brand_id: str, ref_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, brand_id, kind, path, source_name, created_at
            FROM brand_refs
            WHERE brand_id = ? AND id = ?
            LIMIT 1
            """,
            (brand_id, ref_id),
        ).fetchone()
    if row is None:
        return None
    return _brand_ref_row_to_public(row)


def insert_brand_ref(
    ref_id: str,
    brand_id: str,
    kind: str,
    path: str,
    source_name: str | None = None,
) -> dict[str, Any]:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO brand_refs (
                id, brand_id, kind, path, source_name, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ref_id, brand_id, kind, path, source_name, now),
        )
        conn.commit()
    ref = get_brand_ref(brand_id, ref_id)
    assert ref is not None
    return ref


def delete_brand_ref(brand_id: str, ref_id: str) -> dict[str, Any] | None:
    existing = get_brand_ref(brand_id, ref_id)
    if existing is None:
        return None
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM brand_refs WHERE brand_id = ? AND id = ?",
            (brand_id, ref_id),
        )
        conn.commit()
    return existing


def replace_logo_brand_ref(
    brand_id: str,
    logo_path: str,
    source_name: str | None = None,
) -> dict[str, Any] | None:
    """Keep a single logo ref in sync with ``brands.logo_path``."""
    with get_connection() as conn:
        old_rows = conn.execute(
            """
            SELECT id, path FROM brand_refs
            WHERE brand_id = ? AND kind = 'logo'
            """,
            (brand_id,),
        ).fetchall()
        for row in old_rows:
            conn.execute(
                "DELETE FROM brand_refs WHERE brand_id = ? AND id = ?",
                (brand_id, row["id"]),
            )
    for row in old_rows:
        old_path = Path(row["path"])
        if old_path.is_file() and old_path != Path(logo_path):
            try:
                old_path.unlink()
            except OSError:
                pass
    ref_id = f"{brand_id}-logo"
    return insert_brand_ref(
        ref_id,
        brand_id,
        "logo",
        logo_path,
        source_name,
    )


def _job_frame_row_to_public(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "half": row["half"],
        "frame_idx": row["frame_idx"],
        "time_seconds": row["time_seconds"],
        "zone_id": row["zone_id"],
        "posicion": row["posicion"],
        "crop_relpath": row["crop_relpath"],
        "context_relpath": row["context_relpath"] if "context_relpath" in keys else None,
        "visual_hash": row["visual_hash"] if "visual_hash" in keys else None,
        "ocr_text": row["ocr_text"],
        "machine_label": row["machine_label"],
        "brand_id": row["brand_id"],
        "machine_brand_ids_json": row["machine_brand_ids_json"],
        "user_verdict": row["user_verdict"],
    }


def insert_job_frames(job_id: str, rows: list[dict[str, Any]]) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM job_frames WHERE job_id = ?", (job_id,))
        if rows:
            conn.executemany(
                """
                INSERT INTO job_frames (
                    job_id, half, frame_idx, time_seconds, zone_id, posicion,
                    crop_relpath, context_relpath, visual_hash, ocr_text, machine_label, brand_id,
                    machine_brand_ids_json, user_verdict
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        job_id,
                        row.get("half", ""),
                        int(row.get("frame_idx", 0)),
                        float(row.get("time_seconds", 0.0)),
                        row.get("zone_id"),
                        row.get("posicion"),
                        row.get("crop_relpath"),
                        row.get("context_relpath"),
                        row.get("visual_hash"),
                        row.get("ocr_text"),
                        row["machine_label"],
                        row.get("brand_id"),
                        row.get("machine_brand_ids_json") or "[]",
                        row.get("user_verdict"),
                    )
                    for row in rows
                ],
            )
        conn.commit()


def list_job_frames(job_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM job_frames
            WHERE job_id = ?
            ORDER BY half, time_seconds, frame_idx, id
            """,
            (job_id,),
        ).fetchall()
    return [_job_frame_row_to_public(row) for row in rows]


def get_job_frame(job_id: str, frame_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM job_frames WHERE id = ? AND job_id = ? LIMIT 1",
            (frame_id, job_id),
        ).fetchone()
    if row is None:
        return None
    return _job_frame_row_to_public(row)


def update_job_frame(frame_id: int, **fields: Any) -> dict[str, Any] | None:
    allowed = {"brand_id", "user_verdict", "machine_label"}
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM job_frames WHERE id = ? LIMIT 1",
                (frame_id,),
            ).fetchone()
        return _job_frame_row_to_public(row) if row is not None else None
    values.append(frame_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE job_frames SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM job_frames WHERE id = ? LIMIT 1",
            (frame_id,),
        ).fetchone()
    if row is None:
        return None
    return _job_frame_row_to_public(row)


def set_job_catalog_confirmed(job_id: str, iso: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs SET catalog_confirmed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (iso, _utc_now(), job_id),
        )
        conn.commit()


def set_job_catalog_discarded_count(job_id: str, count: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE jobs SET catalog_discarded_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (int(count), _utc_now(), job_id),
        )
        conn.commit()


def upsert_stadium_profile(stadium: Stadium) -> dict[str, Any]:
    """Insert or update a stadium and append a new active camera profile version."""
    now = _utc_now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM stadiums WHERE id = ? LIMIT 1",
            (stadium.id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO stadiums (id, nombre, pais, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (stadium.id, stadium.nombre, stadium.pais, now),
            )
        else:
            conn.execute(
                "UPDATE stadiums SET nombre = ?, pais = ? WHERE id = ?",
                (stadium.nombre, stadium.pais, stadium.id),
            )

        row = conn.execute(
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM camera_profiles
            WHERE stadium_id = ?
            """,
            (stadium.id,),
        ).fetchone()
        version = int(row["version"]) + 1
        conn.execute(
            "UPDATE camera_profiles SET activo = 0 WHERE stadium_id = ?",
            (stadium.id,),
        )
        profile_id = f"{stadium.id}:{stadium.camera.id}:v{version}"
        conn.execute(
            """
            INSERT INTO camera_profiles (
                id, stadium_id, variante, version, config_json, activo, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                stadium.id,
                stadium.camera.variante,
                version,
                stadium.camera.model_dump_json(),
                1,
                now,
            ),
        )
        conn.commit()
    return {
        "id": stadium.id,
        "nombre": stadium.nombre,
        "pais": stadium.pais,
        "profile_id": profile_id,
        "version": version,
        "camera": stadium.camera.model_dump(mode="json"),
    }


def get_camera_profile_json(stadium_id: str) -> dict[str, Any] | None:
    """Return the active default camera profile config for a stadium, if stored."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT config_json FROM camera_profiles
            WHERE stadium_id = ? AND activo = 1
            ORDER BY version DESC
            LIMIT 1
            """,
            (stadium_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["config_json"])


def insert_job(
    *,
    job_id: str,
    stadium_id: str | None,
    profile_id: str | None,
    mode: str,
    duration_mode: str,
    status: str,
    directory: str,
    progress: float = 0.0,
    progress_label: str = "En cola",
) -> None:
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, stadium_id, profile_id, mode, duration_mode,
                status, progress, progress_label, directory,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                stadium_id,
                profile_id,
                mode,
                duration_mode,
                status,
                progress,
                progress_label,
                directory,
                now,
                now,
            ),
        )
        conn.commit()


def update_job(
    *,
    job_id: str,
    status: str | None = None,
    progress: float | None = None,
    progress_label: str | None = None,
    error: str | None = None,
    kickoff_json: str | None = None,
    result_json: str | None = None,
    clear_error: bool = False,
) -> None:
    fields: list[str] = ["updated_at = ?"]
    values: list[Any] = [_utc_now()]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(progress)
    if progress_label is not None:
        fields.append("progress_label = ?")
        values.append(progress_label)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    elif clear_error:
        fields.append("error = NULL")
    if kickoff_json is not None:
        fields.append("kickoff_json = ?")
        values.append(kickoff_json)
    if result_json is not None:
        fields.append("result_json = ?")
        values.append(result_json)
    values.append(job_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()


def delete_exposure_segments(job_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM exposure_segments WHERE job_id = ?",
            (job_id,),
        )
        conn.commit()


def insert_exposure_segments(job_id: str, result: dict[str, Any]) -> None:
    brands = result.get("brands") or []
    rows: list[tuple[Any, ...]] = []
    for brand in brands:
        brand_id = brand.get("brand_id", "")
        brand_name = brand.get("name", "")
        for segment in brand.get("segments") or []:
            rows.append(
                (
                    job_id,
                    brand_id,
                    brand_name,
                    segment.get("zone_id"),
                    segment.get("posicion"),
                    segment.get("half", ""),
                    segment.get("clock_start", ""),
                    segment.get("clock_end", ""),
                    float(segment.get("video_seconds_start", 0.0)),
                    float(segment.get("video_seconds_end", 0.0)),
                    int(segment.get("start_frame", 0)),
                    int(segment.get("end_frame", 0)),
                    int(segment.get("duration_seconds", 0)),
                    segment.get("area_visible_ratio"),
                    segment.get("confianza"),
                )
            )
    if not rows:
        return
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO exposure_segments (
                job_id, brand_id, brand_name, zone_id, posicion, half,
                clock_start, clock_end, video_seconds_start, video_seconds_end,
                start_frame, end_frame, duration_seconds,
                area_visible_ratio, confianza
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()


def persist_job_completion(
    job_id: str,
    *,
    status: str,
    progress: float,
    progress_label: str,
    kickoff_json: str | None,
    result_json: str,
) -> None:
    with get_connection() as conn:
        now = _utc_now()
        conn.execute(
            """
            UPDATE jobs SET
                status = ?,
                progress = ?,
                progress_label = ?,
                kickoff_json = COALESCE(?, kickoff_json),
                result_json = ?,
                error = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                progress,
                progress_label,
                kickoff_json,
                result_json,
                now,
                job_id,
            ),
        )
        conn.execute(
            "DELETE FROM exposure_segments WHERE job_id = ?",
            (job_id,),
        )
        result = json.loads(result_json)
        brands = result.get("brands") or []
        rows: list[tuple[Any, ...]] = []
        for brand in brands:
            brand_id = brand.get("brand_id", "")
            brand_name = brand.get("name", "")
            for segment in brand.get("segments") or []:
                rows.append(
                    (
                        job_id,
                        brand_id,
                        brand_name,
                        segment.get("zone_id"),
                        segment.get("posicion"),
                        segment.get("half", ""),
                        segment.get("clock_start", ""),
                        segment.get("clock_end", ""),
                        float(segment.get("video_seconds_start", 0.0)),
                        float(segment.get("video_seconds_end", 0.0)),
                        int(segment.get("start_frame", 0)),
                        int(segment.get("end_frame", 0)),
                        int(segment.get("duration_seconds", 0)),
                        segment.get("area_visible_ratio"),
                        segment.get("confianza"),
                    )
                )
        if rows:
            conn.executemany(
                """
                INSERT INTO exposure_segments (
                    job_id, brand_id, brand_name, zone_id, posicion, half,
                    clock_start, clock_end, video_seconds_start, video_seconds_end,
                    start_frame, end_frame, duration_seconds,
                    area_visible_ratio, confianza
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()


def _summary_from_result_json(result_json: str | None) -> dict[str, int]:
    if not result_json:
        return {
            "brand_count": 0,
            "total_exposure_seconds": 0,
            "analyzed_seconds": 0,
        }
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        return {
            "brand_count": 0,
            "total_exposure_seconds": 0,
            "analyzed_seconds": 0,
        }
    brands = result.get("brands") or []
    return {
        "brand_count": len(brands),
        "total_exposure_seconds": sum(
            int(brand.get("total_seconds") or 0) for brand in brands
        ),
        "analyzed_seconds": int(result.get("analyzed_seconds") or 0),
    }


def list_job_summaries(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, status, progress, created_at, stadium_id, result_json
            FROM jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "status": row["status"],
            "progress": row["progress"],
            "created_at": row["created_at"],
            "stadium_id": row["stadium_id"],
            "summary": _summary_from_result_json(row["result_json"]),
        }
        for row in rows
    ]


def get_job_row(job_id: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE id = ? LIMIT 1",
            (job_id,),
        ).fetchone()


def delete_job(job_id: str) -> str | None:
    """Delete job row and related tables. Returns directory path if removed."""
    row = get_job_row(job_id)
    if row is None:
        return None
    directory = str(row["directory"])
    with get_connection() as conn:
        conn.execute("DELETE FROM job_frames WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM exposure_segments WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()
    return directory


def list_non_terminal_jobs() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM jobs
            WHERE status NOT IN ('completed', 'error')
            ORDER BY created_at ASC
            """
        ).fetchall()


def mark_orphaned_jobs_error() -> list[str]:
    """Mark in-flight jobs from a previous process as failed."""
    now = _utc_now()
    error_msg = "El análisis se interrumpió al reiniciar el servidor."
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id FROM jobs
            WHERE status IN ('detecting_kickoff', 'processing')
            """
        ).fetchall()
        if rows:
            conn.execute(
                """
                UPDATE jobs SET
                    status = 'error',
                    error = ?,
                    progress_label = 'No se pudo completar el análisis',
                    updated_at = ?
                WHERE status IN ('detecting_kickoff', 'processing')
                """,
                (error_msg, now),
            )
            conn.commit()
    return [row["id"] for row in rows]
