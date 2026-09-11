import json
import tempfile
import unittest
from pathlib import Path

from app import db


class DbSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_seed_is_idempotent(self) -> None:
        db.ensure_db()
        first = db.list_stadium_summaries()
        db.seed_stadiums()
        second = db.list_stadium_summaries()
        self.assertEqual(first, second)

    def test_seeds_ligaecuabet(self) -> None:
        db.ensure_db()
        summaries = db.list_stadium_summaries()
        ids = {row["id"] for row in summaries}
        self.assertIn("ligaecuabet", ids)
        self.assertTrue(db.stadium_exists("ligaecuabet"))

    def test_camera_profile_has_scoreboard_and_grass(self) -> None:
        db.ensure_db()
        profile = db.get_camera_profile_json("ligaecuabet")
        self.assertIsNotNone(profile)
        crop = profile["scoreboard_crop"]
        self.assertEqual(crop["w"], 0.42)
        self.assertEqual(crop["h"], 0.22)
        self.assertEqual(profile["grass_hsv"]["lower"], [28, 25, 30])


class JobConfigStadiumTests(unittest.TestCase):
    def test_defaults_to_ligaecuabet(self) -> None:
        from app.schemas import JobConfig

        config = JobConfig(mode="single", duration_mode="full")
        self.assertEqual(config.stadium_id, "ligaecuabet")

    def test_preserves_explicit_stadium(self) -> None:
        from app.schemas import JobConfig

        config = JobConfig(
            mode="single",
            duration_mode="full",
            stadium_id="example_day",
        )
        self.assertEqual(config.stadium_id, "example_day")


class BrandLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_upsert_and_list_brands(self) -> None:
        created = db.upsert_brand(
            "nett-plus",
            "NETT plus",
            ["NETTPLUS", "NETT PLUS"],
        )
        self.assertEqual(created["id"], "nett-plus")
        self.assertEqual(created["nombre"], "NETT plus")
        self.assertEqual(created["aliases"], ["NETTPLUS", "NETT PLUS"])
        self.assertFalse(created["has_logo"])

        updated = db.upsert_brand(
            "nett-plus",
            "NETT plus",
            ["NETTPLUS", "NETT+"],
            logo_path=str(Path(self._tmpdir.name) / "logo.png"),
        )
        self.assertEqual(updated["aliases"], ["NETTPLUS", "NETT+"])
        self.assertFalse(updated["has_logo"])

        listed = db.list_brands()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["nombre"], "NETT plus")
        self.assertTrue(listed[0]["activo"])
        self.assertIsNone(listed[0]["group_id"])

        fetched = db.get_brand("nett-plus")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched["nombre"], "NETT plus")
        self.assertTrue(fetched["activo"])
        self.assertIsNone(db.get_brand("missing"))


class StadiumUpsertTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_upsert_creates_new_profile_version(self) -> None:
        from app.config.stadiums import load_stadium_profile
        from app.domain.stadium import Stadium

        camera = load_stadium_profile("ligaecuabet")
        first = db.upsert_stadium_profile(
            Stadium(
                id="capwell",
                nombre="Capwell",
                pais="Ecuador",
                default_camera=camera.id,
                camera=camera,
            )
        )
        second = db.upsert_stadium_profile(
            Stadium(
                id="capwell",
                nombre="Estadio Capwell",
                pais="Ecuador",
                default_camera=camera.id,
                camera=camera,
            )
        )
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["nombre"], "Estadio Capwell")
        self.assertTrue(db.stadium_exists("capwell"))
        profile = db.get_camera_profile_json("capwell")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["scoreboard_crop"]["w"], 0.42)


class BrandGroupAndCatalogDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.ensure_db()

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_seeds_ligaecuabet_group_and_attaches_brands(self) -> None:
        db.upsert_brand("nett", "NETT plus")
        db.seed_brand_groups()
        groups = db.list_brand_groups()
        self.assertTrue(any(group["id"] == "ligaecuabet" for group in groups))
        liga = next(group for group in groups if group["id"] == "ligaecuabet")
        self.assertEqual(liga["titulo"], "LigaEcuabet")
        brand_ids = {brand["id"] for brand in liga["brands"]}
        self.assertIn("nett", brand_ids)
        fetched = db.get_brand("nett")
        assert fetched is not None
        self.assertEqual(fetched["group_id"], "ligaecuabet")

    def test_create_and_refuse_delete_group_with_brands(self) -> None:
        group_id = db.create_brand_group("Copa Sudamericana")
        self.assertTrue(group_id)
        db.upsert_brand("copa", "Copa", group_id=group_id)
        with self.assertRaises(ValueError):
            db.delete_brand_group(group_id)
        db.delete_brand("copa")
        db.delete_brand_group(group_id)
        ids = {group["id"] for group in db.list_brand_groups()}
        self.assertNotIn(group_id, ids)

    def test_update_brand_activo_and_delete(self) -> None:
        db.upsert_brand("x", "X")
        updated = db.update_brand("x", activo=False, nombre="X2")
        self.assertFalse(updated["activo"])
        self.assertEqual(updated["nombre"], "X2")
        self.assertTrue(db.delete_brand("x"))
        self.assertIsNone(db.get_brand("x"))

    def test_job_frames_insert_update_and_confirm(self) -> None:
        db.insert_job(
            job_id="job-cat",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="completed",
            directory="/tmp/job-cat",
        )
        db.insert_job_frames(
            "job-cat",
            [
                {
                    "half": "1T",
                    "frame_idx": 10,
                    "time_seconds": 1.0,
                    "zone_id": "led_lateral_main",
                    "posicion": "LATERAL_MAIN",
                    "crop_relpath": "catalog/led_000010.jpg",
                    "ocr_text": "NETT",
                    "machine_label": "positive",
                    "brand_id": "nett",
                    "machine_brand_ids_json": '["nett"]',
                    "user_verdict": None,
                }
            ],
        )
        frames = db.list_job_frames("job-cat")
        self.assertEqual(len(frames), 1)
        updated = db.update_job_frame(
            frames[0]["id"],
            brand_id=None,
            user_verdict="false_positive",
            machine_label="attention",
        )
        assert updated is not None
        self.assertEqual(updated["user_verdict"], "false_positive")
        self.assertIsNone(updated["brand_id"])
        db.set_job_catalog_confirmed("job-cat", "2026-09-10T12:00:00+00:00")
        row = db.get_job_row("job-cat")
        assert row is not None
        self.assertEqual(row["catalog_confirmed_at"], "2026-09-10T12:00:00+00:00")


class SchemaMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "legacy.db"

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_migrate_adds_missing_columns(self) -> None:
        import sqlite3

        conn = sqlite3.connect(self._path)
        conn.executescript(
            """
            CREATE TABLE brands (
                id TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                logo_path TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE jobs (
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
            """
        )
        conn.commit()
        conn.close()

        db.set_db_path(self._path)
        db.init_db()
        with db.get_connection() as conn:
            brand_cols = db._table_columns(conn, "brands")
            job_cols = db._table_columns(conn, "jobs")
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        self.assertIn("group_id", brand_cols)
        self.assertIn("activo", brand_cols)
        self.assertIn("catalog_confirmed_at", job_cols)
        self.assertIn("brand_groups", tables)
        self.assertIn("job_frames", tables)
        self.assertIn("brand_refs", tables)
        with db.get_connection() as conn:
            frame_cols = db._table_columns(conn, "job_frames")
        self.assertIn("context_relpath", frame_cols)
        self.assertIn("visual_hash", frame_cols)


if __name__ == "__main__":
    unittest.main()
