import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import db
from app.jobs import JobManager
from app.schemas import BrandInput, JobConfig


class JobQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._jobs_root = Path(self._tmpdir.name) / "jobs"
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def _make_job_args(self, job_id: str) -> dict:
        directory = self._jobs_root / job_id
        directory.mkdir(parents=True)
        video_path = directory / "video.mp4"
        video_path.write_bytes(b"fake")
        meta = {
            "brands": [{"id": "nett", "name": "NETT plus", "aliases": []}],
            "video_paths": [str(video_path)],
            "sample_fps": 1,
        }
        (directory / "meta.json").write_text(
            json.dumps(meta),
            encoding="utf-8",
        )
        return {
            "job_id": job_id,
            "directory": directory,
            "brands": [BrandInput(id="nett", name="NETT plus")],
            "video_paths": [video_path],
            "config": JobConfig(mode="single", duration_mode="full"),
        }

    async def test_two_jobs_can_be_created_without_busy_error(self) -> None:
        manager = JobManager(self._jobs_root)
        with patch.object(manager, "_maybe_start_next", new_callable=AsyncMock):
            first = manager.add_job(**self._make_job_args("job-1"))
            second = manager.add_job(**self._make_job_args("job-2"))

        self.assertEqual(first.status, "queued")
        self.assertEqual(second.status, "queued")
        self.assertIn("job-1", manager.jobs)
        self.assertIn("job-2", manager.jobs)

        summaries = db.list_job_summaries()
        self.assertEqual(len(summaries), 2)
        self.assertEqual({row["id"] for row in summaries}, {"job-1", "job-2"})


class JobPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_insert_and_list_jobs(self) -> None:
        db.insert_job(
            job_id="abc",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="queued",
            directory="/tmp/abc",
        )
        rows = db.list_job_summaries()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "abc")
        self.assertEqual(rows[0]["stadium_id"], "ligaecuabet")
        self.assertEqual(rows[0]["summary"]["brand_count"], 0)

    def test_persist_completion_writes_exposure_segments(self) -> None:
        db.insert_job(
            job_id="done-1",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="processing",
            directory="/tmp/done-1",
        )
        result = {
            "analyzed_seconds": 120,
            "brands": [
                {
                    "brand_id": "nett",
                    "name": "NETT plus",
                    "segments": [
                        {
                            "half": "1T",
                            "clock_start": "00:00",
                            "clock_end": "00:05",
                            "video_seconds_start": 0.0,
                            "video_seconds_end": 5.0,
                            "start_frame": 0,
                            "end_frame": 150,
                            "duration_seconds": 5,
                            "zone_id": "led_lateral_main",
                            "posicion": "LATERAL_MAIN",
                        }
                    ],
                }
            ],
        }
        db.persist_job_completion(
            "done-1",
            status="completed",
            progress=1.0,
            progress_label="Análisis completado",
            kickoff_json='{"first_half_video_seconds": 0.0}',
            result_json=json.dumps(result),
        )
        with db.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM exposure_segments WHERE job_id = ?",
                ("done-1",),
            ).fetchone()[0]
        self.assertEqual(count, 1)
        summary = db.list_job_summaries(limit=1)[0]
        self.assertEqual(summary["summary"]["brand_count"], 1)
        self.assertEqual(summary["summary"]["analyzed_seconds"], 120)

    def test_mark_orphaned_jobs_error(self) -> None:
        db.insert_job(
            job_id="orphan",
            stadium_id="ligaecuabet",
            profile_id=None,
            mode="single",
            duration_mode="full",
            status="processing",
            directory="/tmp/orphan",
        )
        orphaned = db.mark_orphaned_jobs_error()
        self.assertEqual(orphaned, ["orphan"])
        row = db.get_job_row("orphan")
        assert row is not None
        self.assertEqual(row["status"], "error")
        self.assertIn("reiniciar", row["error"] or "")


if __name__ == "__main__":
    unittest.main()
