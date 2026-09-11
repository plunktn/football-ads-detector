import tempfile
import unittest
from pathlib import Path

from app import db
from app.pipeline.catalog_report import build_catalog_report


class CatalogReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()
        db.upsert_brand("nett", "NETT plus")
        db.upsert_brand("ecuabet", "ECUABET")
        db.insert_job(
            job_id="job-report",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="completed",
            directory=self._tmpdir.name,
        )

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_requires_confirm_flag_in_payload(self) -> None:
        db.insert_job_frames(
            "job-report",
            [
                {
                    "half": "1T",
                    "frame_idx": 10,
                    "time_seconds": 100.0,
                    "crop_relpath": "catalog/a.jpg",
                    "machine_label": "positive",
                    "brand_id": "nett",
                }
            ],
        )
        payload = build_catalog_report("job-report")
        assert payload is not None
        self.assertFalse(payload["confirmed"])
        self.assertEqual(payload["summary"]["appearances"], 1)

    def test_groups_consecutive_seconds(self) -> None:
        db.set_job_catalog_confirmed("job-report", "2026-09-10T12:00:00+00:00")
        db.insert_job_frames(
            "job-report",
            [
                {
                    "half": "1T",
                    "frame_idx": 1,
                    "time_seconds": 10.0,
                    "crop_relpath": "a.jpg",
                    "machine_label": "positive",
                    "brand_id": "nett",
                },
                {
                    "half": "1T",
                    "frame_idx": 2,
                    "time_seconds": 11.0,
                    "crop_relpath": "b.jpg",
                    "machine_label": "positive",
                    "brand_id": "nett",
                },
                {
                    "half": "1T",
                    "frame_idx": 3,
                    "time_seconds": 20.0,
                    "crop_relpath": "c.jpg",
                    "machine_label": "positive",
                    "brand_id": "nett",
                },
                {
                    "half": "1T",
                    "frame_idx": 4,
                    "time_seconds": 12.0,
                    "crop_relpath": "d.jpg",
                    "machine_label": "attention",
                    "brand_id": None,
                    "user_verdict": None,
                },
                {
                    "half": "1T",
                    "frame_idx": 5,
                    "time_seconds": 30.0,
                    "crop_relpath": "e.jpg",
                    "machine_label": "positive",
                    "brand_id": "ecuabet",
                    "user_verdict": "false_positive",
                },
            ],
        )
        payload = build_catalog_report("job-report")
        assert payload is not None
        self.assertTrue(payload["confirmed"])
        self.assertEqual(payload["summary"]["brand_count"], 1)
        brand = payload["brands"][0]
        self.assertEqual(brand["brand_id"], "nett")
        self.assertEqual(brand["appearances"], 2)
        self.assertEqual(brand["total_seconds"], 3)
        self.assertEqual(brand["segments"][0]["clock_start"], "00:10")
        self.assertEqual(brand["segments"][0]["clock_end"], "00:11")
        self.assertEqual(brand["segments"][0]["duration_seconds"], 2)


if __name__ == "__main__":
    unittest.main()
