"""Export / import brand+stadium config as a ZIP (cloud source of truth)."""

from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app import db
from app.settings import cloud_api_url, cloud_sync_enabled, sync_token

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
SYNC_HEADER = "X-Sync-Token"

_suppress_cloud_push = False


def suppress_cloud_push(active: bool) -> None:
    global _suppress_cloud_push
    _suppress_cloud_push = active


def brands_root() -> Path:
    return Path(db.BRANDS_DIR)


def _rel_logo(brand_id: str, source: Path | None) -> str:
    suffix = source.suffix.lower() if source and source.suffix else ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    return f"brands/{brand_id}{suffix}"


def _rel_ref(brand_id: str, ref_id: str, source: Path | None) -> str:
    suffix = source.suffix.lower() if source and source.suffix else ".jpg"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".jpg"
    return f"brands/{brand_id}/refs/{ref_id}{suffix}"


def _file_bytes(path: Path | None) -> bytes | None:
    if path is None or not path.is_file():
        return None
    return path.read_bytes()


def build_manifest_and_files() -> tuple[dict[str, Any], dict[str, bytes]]:
    """Serialize config tables + brand binaries with relative paths."""
    files: dict[str, bytes] = {}
    with db.get_connection() as conn:
        stadiums = [
            dict(row)
            for row in conn.execute(
                "SELECT id, nombre, pais, created_at FROM stadiums ORDER BY id"
            ).fetchall()
        ]
        camera_profiles = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, stadium_id, variante, version, config_json, activo, created_at
                FROM camera_profiles
                ORDER BY stadium_id, version
                """
            ).fetchall()
        ]
        brand_groups = [
            dict(row)
            for row in conn.execute(
                "SELECT id, titulo, created_at FROM brand_groups ORDER BY id"
            ).fetchall()
        ]
        brand_rows = conn.execute(
            """
            SELECT id, nombre, aliases_json, logo_path, created_at, group_id, activo
            FROM brands
            ORDER BY id
            """
        ).fetchall()
        ref_rows = conn.execute(
            """
            SELECT id, brand_id, kind, path, source_name, created_at
            FROM brand_refs
            ORDER BY brand_id, id
            """
        ).fetchall()

    brands_out: list[dict[str, Any]] = []
    for row in brand_rows:
        logo_abs = Path(row["logo_path"]) if row["logo_path"] else None
        if logo_abs is None or not logo_abs.is_file():
            candidate = brands_root() / f"{row['id']}.png"
            logo_abs = candidate if candidate.is_file() else None
        logo_rel = _rel_logo(row["id"], logo_abs) if logo_abs else None
        if logo_abs and logo_rel:
            payload = _file_bytes(logo_abs)
            if payload is not None:
                files[logo_rel] = payload
        brands_out.append(
            {
                "id": row["id"],
                "nombre": row["nombre"],
                "aliases_json": row["aliases_json"] or "[]",
                "created_at": row["created_at"],
                "group_id": row["group_id"],
                "activo": int(row["activo"] if row["activo"] is not None else 1),
                "logo_relpath": logo_rel,
            }
        )

    refs_out: list[dict[str, Any]] = []
    for row in ref_rows:
        ref_abs = Path(row["path"]) if row["path"] else None
        if ref_abs is None or not ref_abs.is_file():
            # try default location
            for suffix in (".jpg", ".png", ".webp", ".jpeg"):
                candidate = brands_root() / row["brand_id"] / "refs" / f"{row['id']}{suffix}"
                if candidate.is_file():
                    ref_abs = candidate
                    break
        file_rel = _rel_ref(row["brand_id"], row["id"], ref_abs) if ref_abs else None
        if ref_abs and file_rel:
            payload = _file_bytes(ref_abs)
            if payload is not None:
                files[file_rel] = payload
        refs_out.append(
            {
                "id": row["id"],
                "brand_id": row["brand_id"],
                "kind": row["kind"],
                "source_name": row["source_name"],
                "created_at": row["created_at"],
                "file_relpath": file_rel,
            }
        )

    manifest = {
        "version": MANIFEST_VERSION,
        "stadiums": stadiums,
        "camera_profiles": camera_profiles,
        "brand_groups": brand_groups,
        "brands": brands_out,
        "brand_refs": refs_out,
    }
    return manifest, files


def export_config_zip() -> bytes:
    manifest, files = build_manifest_and_files()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        for relpath, payload in sorted(files.items()):
            archive.writestr(relpath, payload)
    return buffer.getvalue()


def _safe_relpath(relpath: str) -> str:
    cleaned = relpath.replace("\\", "/").lstrip("/")
    parts = Path(cleaned).parts
    if ".." in parts or not cleaned.startswith("brands/"):
        raise ValueError(f"Ruta de archivo no permitida: {relpath!r}")
    return cleaned


def import_config_zip(payload: bytes, *, replace: bool = True) -> dict[str, int]:
    """Apply ZIP. replace=True wipes config tables (not jobs) then inserts."""
    with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
        if MANIFEST_NAME not in archive.namelist():
            raise ValueError("ZIP sin manifest.json")
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest inválido")
        file_map: dict[str, bytes] = {}
        for name in archive.namelist():
            if name == MANIFEST_NAME or name.endswith("/"):
                continue
            rel = _safe_relpath(name)
            file_map[rel] = archive.read(name)

    stadiums = list(manifest.get("stadiums") or [])
    camera_profiles = list(manifest.get("camera_profiles") or [])
    brand_groups = list(manifest.get("brand_groups") or [])
    brands = list(manifest.get("brands") or [])
    brand_refs = list(manifest.get("brand_refs") or [])

    root = brands_root()
    data_root = root.parent.resolve()
    if replace and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    for rel, data in file_map.items():
        destination = (data_root / Path(_safe_relpath(rel))).resolve()
        if not str(destination).startswith(str(data_root)):
            raise ValueError(f"Path escape: {rel}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    with db.get_connection() as conn:
        if replace:
            conn.execute("DELETE FROM brand_refs")
            conn.execute("DELETE FROM brands")
            conn.execute("DELETE FROM brand_groups")
            conn.execute("DELETE FROM camera_profiles")
            conn.execute("DELETE FROM stadiums")

        for row in stadiums:
            conn.execute(
                """
                INSERT INTO stadiums (id, nombre, pais, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nombre = excluded.nombre,
                    pais = excluded.pais
                """,
                (
                    row["id"],
                    row["nombre"],
                    row.get("pais"),
                    row.get("created_at") or db._utc_now(),
                ),
            )

        for row in camera_profiles:
            conn.execute(
                """
                INSERT INTO camera_profiles (
                    id, stadium_id, variante, version, config_json, activo, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    stadium_id = excluded.stadium_id,
                    variante = excluded.variante,
                    version = excluded.version,
                    config_json = excluded.config_json,
                    activo = excluded.activo
                """,
                (
                    row["id"],
                    row["stadium_id"],
                    row["variante"],
                    int(row["version"]),
                    row["config_json"],
                    int(row.get("activo", 1)),
                    row.get("created_at") or db._utc_now(),
                ),
            )

        for row in brand_groups:
            conn.execute(
                """
                INSERT INTO brand_groups (id, titulo, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET titulo = excluded.titulo
                """,
                (
                    row["id"],
                    row["titulo"],
                    row.get("created_at") or db._utc_now(),
                ),
            )

        for row in brands:
            logo_rel = row.get("logo_relpath")
            logo_path = None
            if logo_rel:
                logo_path = str((data_root / Path(_safe_relpath(logo_rel))).resolve())
            conn.execute(
                """
                INSERT INTO brands (
                    id, nombre, aliases_json, logo_path, created_at, group_id, activo
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    nombre = excluded.nombre,
                    aliases_json = excluded.aliases_json,
                    logo_path = excluded.logo_path,
                    group_id = excluded.group_id,
                    activo = excluded.activo
                """,
                (
                    row["id"],
                    row["nombre"],
                    row.get("aliases_json") or "[]",
                    logo_path,
                    row.get("created_at") or db._utc_now(),
                    row.get("group_id"),
                    int(row.get("activo", 1)),
                ),
            )

        for row in brand_refs:
            file_rel = row.get("file_relpath")
            path = ""
            if file_rel:
                path = str((data_root / Path(_safe_relpath(file_rel))).resolve())
            conn.execute(
                """
                INSERT INTO brand_refs (
                    id, brand_id, kind, path, source_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    brand_id = excluded.brand_id,
                    kind = excluded.kind,
                    path = excluded.path,
                    source_name = excluded.source_name
                """,
                (
                    row["id"],
                    row["brand_id"],
                    row["kind"],
                    path,
                    row.get("source_name"),
                    row.get("created_at") or db._utc_now(),
                ),
            )
        conn.commit()

    return {
        "stadiums": len(stadiums),
        "camera_profiles": len(camera_profiles),
        "brand_groups": len(brand_groups),
        "brands": len(brands),
        "brand_refs": len(brand_refs),
        "files": len(file_map),
    }


def pull_from_cloud() -> dict[str, Any]:
    if not cloud_sync_enabled():
        raise RuntimeError("CLOUD_API_URL y SYNC_TOKEN son obligatorios para pull.")
    url = f"{cloud_api_url()}/sync/config"
    token = sync_token()
    assert token
    with httpx.Client(timeout=120.0) as client:
        response = client.get(url, headers={SYNC_HEADER: token})
    if response.status_code == 401:
        raise PermissionError("SYNC_TOKEN rechazado por cloud.")
    response.raise_for_status()
    suppress_cloud_push(True)
    try:
        counts = import_config_zip(response.content, replace=True)
    finally:
        suppress_cloud_push(False)
    logger.info("sync pull ok: %s", counts)
    return {"ok": True, "counts": counts}


def push_to_cloud() -> dict[str, Any]:
    if _suppress_cloud_push:
        return {"ok": True, "skipped": "suppress"}
    if not cloud_sync_enabled():
        raise RuntimeError("CLOUD_API_URL y SYNC_TOKEN son obligatorios para push.")
    url = f"{cloud_api_url()}/sync/config"
    token = sync_token()
    assert token
    payload = export_config_zip()
    with httpx.Client(timeout=120.0) as client:
        response = client.put(
            url,
            content=payload,
            headers={
                SYNC_HEADER: token,
                "Content-Type": "application/zip",
            },
        )
    if response.status_code == 401:
        raise PermissionError("SYNC_TOKEN rechazado por cloud.")
    response.raise_for_status()
    body = response.json() if response.content else {}
    logger.info("sync push ok: %s", body)
    return {"ok": True, "remote": body}


def maybe_push_to_cloud() -> None:
    """Best-effort push after local config mutations."""
    if _suppress_cloud_push or not cloud_sync_enabled():
        return
    try:
        push_to_cloud()
    except Exception:
        logger.exception("sync push falló (se conserva el cambio local)")


def maybe_pull_from_cloud() -> None:
    if not cloud_sync_enabled():
        return
    try:
        pull_from_cloud()
    except Exception:
        logger.exception("sync pull al arrancar falló (se usa DB local)")
