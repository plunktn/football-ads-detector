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
            """
        )
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


def ensure_db() -> None:
    init_db()
    seed_stadiums()


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
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "aliases": json.loads(row["aliases_json"] or "[]"),
        "has_logo": _brand_has_logo(row["logo_path"]),
    }


def list_brands() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, nombre, aliases_json, logo_path FROM brands ORDER BY nombre COLLATE NOCASE"
        ).fetchall()
    return [_brand_row_to_public(row) for row in rows]


def get_brand(brand_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, nombre, aliases_json, logo_path, created_at
            FROM brands WHERE id = ? LIMIT 1
            """,
            (brand_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "aliases": json.loads(row["aliases_json"] or "[]"),
        "logo_path": row["logo_path"],
        "created_at": row["created_at"],
        "has_logo": _brand_has_logo(row["logo_path"]),
    }


def upsert_brand(
    brand_id: str,
    nombre: str,
    aliases: list[str] | None = None,
    logo_path: str | None = None,
) -> dict[str, Any]:
    aliases_json = json.dumps(aliases or [], ensure_ascii=False)
    now = _utc_now()
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT logo_path FROM brands WHERE id = ? LIMIT 1",
            (brand_id,),
        ).fetchone()
        resolved_logo_path = logo_path
        if resolved_logo_path is None and existing is not None:
            resolved_logo_path = existing["logo_path"]
        conn.execute(
            """
            INSERT INTO brands (id, nombre, aliases_json, logo_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                nombre = excluded.nombre,
                aliases_json = excluded.aliases_json,
                logo_path = COALESCE(excluded.logo_path, brands.logo_path)
            """,
            (brand_id, nombre, aliases_json, resolved_logo_path, now),
        )
        conn.commit()
    brand = get_brand(brand_id)
    assert brand is not None
    return brand


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
