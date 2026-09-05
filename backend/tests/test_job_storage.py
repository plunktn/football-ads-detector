import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.job_storage import maybe_purge_job_media, purge_job_media


class JobStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.directory = Path(self._tmpdir.name) / "job"
        self.directory.mkdir()
        self.video = self.directory / "video.mp4"
        self.video.write_bytes(b"video")
        debug = self.directory / "debug"
        debug.mkdir()
        (debug / "led_000001.jpg").write_bytes(b"jpg")
        meta = {
            "brands": [],
            "video_paths": [str(self.video)],
            "sample_fps": 1,
        }
        (self.directory / "meta.json").write_text(
            json.dumps(meta),
            encoding="utf-8",
        )
        (self.directory / "result.json").write_text("{}", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_purge_job_media_removes_video_and_debug(self) -> None:
        removed = purge_job_media(self.directory, [self.video])

        self.assertFalse(self.video.exists())
        self.assertFalse((self.directory / "debug").exists())
        self.assertTrue((self.directory / "result.json").exists())
        self.assertIn(self.video, removed)

        meta = json.loads((self.directory / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["video_paths"], [])
        self.assertTrue(meta["media_purged"])

    @patch.dict(os.environ, {"KEEP_JOB_VIDEOS": "true"}, clear=False)
    def test_maybe_purge_respects_keep_flag(self) -> None:
        removed = maybe_purge_job_media(self.directory, [self.video])

        self.assertEqual(removed, [])
        self.assertTrue(self.video.exists())

    @patch.dict(os.environ, {"KEEP_JOB_VIDEOS": "false"}, clear=False)
    def test_maybe_purge_runs_when_flag_false(self) -> None:
        removed = maybe_purge_job_media(self.directory, [self.video])

        self.assertFalse(self.video.exists())
        self.assertEqual(len(removed), 2)


if __name__ == "__main__":
    unittest.main()
