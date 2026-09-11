import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db
from app import sync_config
from app.main import app


class SyncConfigRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        db.set_db_path(root / "app.db")
        self._brands_prev = db.BRANDS_DIR
        db.BRANDS_DIR = root / "brands"
        db.BRANDS_DIR.mkdir(parents=True, exist_ok=True)
        db.init_db()
        db.create_brand_group("Liga Test")
        groups = db.list_brand_groups()
        group_id = groups[0]["id"]
        logo = db.BRANDS_DIR / "marca-a.png"
        logo.write_bytes(b"\x89PNG\r\n\x1a\nlogo")
        db.upsert_brand("marca-a", "Marca A", ["A"], str(logo), group_id=group_id)
        ref_path = db.brand_refs_dir("marca-a") / "ref1.jpg"
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_bytes(b"jpeg-bytes")
        db.insert_brand_ref("ref1", "marca-a", "image", str(ref_path), "shot.jpg")

    def tearDown(self) -> None:
        db.BRANDS_DIR = self._brands_prev
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_export_import_roundtrip_preserves_brands_and_files(self) -> None:
        payload = sync_config.export_config_zip()
        self.assertGreater(len(payload), 50)

        # wipe config
        with db.get_connection() as conn:
            conn.execute("DELETE FROM brand_refs")
            conn.execute("DELETE FROM brands")
            conn.execute("DELETE FROM brand_groups")
            conn.commit()
        if db.BRANDS_DIR.exists():
            for child in db.BRANDS_DIR.iterdir():
                if child.is_file():
                    child.unlink()
                else:
                    import shutil

                    shutil.rmtree(child)

        counts = sync_config.import_config_zip(payload, replace=True)
        self.assertEqual(counts["brands"], 1)
        self.assertEqual(counts["brand_refs"], 1)
        brands = db.list_brands()
        self.assertEqual(len(brands), 1)
        self.assertEqual(brands[0]["id"], "marca-a")
        refs = db.list_brand_refs("marca-a")
        self.assertEqual(len(refs), 1)
        self.assertTrue(Path(refs[0]["path"]).is_file())

    def test_import_does_not_delete_jobs(self) -> None:
        with db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, stadium_id, profile_id, mode, duration_mode, status,
                    progress, progress_label, error, kickoff_json, result_json,
                    directory, created_at, updated_at
                ) VALUES (
                    'job-keep', NULL, NULL, 'single', '5min', 'completed',
                    1.0, 'done', NULL, NULL, NULL,
                    '/tmp/job', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
                )
                """
            )
            conn.commit()
        payload = sync_config.export_config_zip()
        sync_config.import_config_zip(payload, replace=True)
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM jobs WHERE id = 'job-keep'"
            ).fetchone()
        self.assertIsNotNone(row)


class SyncConfigApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        db.set_db_path(root / "app.db")
        self._brands_prev = db.BRANDS_DIR
        db.BRANDS_DIR = root / "brands"
        db.BRANDS_DIR.mkdir(parents=True, exist_ok=True)
        db.init_db()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        db.BRANDS_DIR = self._brands_prev
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_sync_config_requires_token(self) -> None:
        with patch.dict(os.environ, {"SYNC_TOKEN": "secret-token"}, clear=False):
            denied = self.client.get("/sync/config")
            self.assertEqual(denied.status_code, 401)
            ok = self.client.get(
                "/sync/config",
                headers={"X-Sync-Token": "secret-token"},
            )
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.headers.get("content-type"), "application/zip")

    def test_sync_status_endpoint(self) -> None:
        response = self.client.get("/sync/status")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("cloud_configured", body)
        self.assertIn("server_accepts_sync", body)


if __name__ == "__main__":
    unittest.main()
