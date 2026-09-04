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

        fetched = db.get_brand("nett-plus")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched["nombre"], "NETT plus")
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


if __name__ == "__main__":
    unittest.main()
