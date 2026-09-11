import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from app import db
from app.pipeline.brand_refs import extract_video_keyframes, save_image_bytes


def _write_test_video(path: Path, frame_count: int = 40, fps: float = 10.0) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (160, 120))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter no disponible en este entorno.")
    try:
        for index in range(frame_count):
            value = min(255, index * 6)
            frame = np.full((120, 160, 3), value, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()


class BrandRefKeyframeTests(unittest.TestCase):
    def test_extract_video_keyframes_respects_cap_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video_path = Path(tmp) / "ad.mp4"
            output_dir = Path(tmp) / "frames"
            _write_test_video(video_path, frame_count=60, fps=10.0)
            pairs = extract_video_keyframes(
                video_path,
                output_dir,
                sample_fps=1.0,
                max_frames=32,
                dedupe_distance=12,
            )
            self.assertGreater(len(pairs), 0)
            self.assertLessEqual(len(pairs), 32)
            for ref_id, frame_path in pairs:
                self.assertTrue(ref_id)
                self.assertTrue(frame_path.is_file())
                self.assertEqual(frame_path.suffix, ".jpg")

    def test_save_image_bytes_writes_jpeg(self) -> None:
        image = np.zeros((24, 48, 3), dtype=np.uint8)
        image[:, 12:36] = (0, 255, 0)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "ref.jpg"
            save_image_bytes(encoded.tobytes(), destination)
            self.assertTrue(destination.is_file())


class BrandRefDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()
        db.upsert_brand("demo", "Demo Brand")

    def tearDown(self) -> None:
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_insert_list_and_delete_brand_ref(self) -> None:
        ref_id = uuid4().hex
        image_path = Path(self._tmpdir.name) / "ref.jpg"
        image_path.write_bytes(b"fake")
        created = db.insert_brand_ref(
            ref_id,
            "demo",
            "image",
            str(image_path),
            "still.png",
        )
        self.assertEqual(created["kind"], "image")
        self.assertEqual(created["source_name"], "still.png")
        self.assertEqual(created["image_url"], f"/brands/demo/refs/{ref_id}/image")

        listed = db.list_brand_refs("demo")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], ref_id)

        deleted = db.delete_brand_ref("demo", ref_id)
        assert deleted is not None
        self.assertEqual(deleted["id"], ref_id)
        self.assertEqual(db.list_brand_refs("demo"), [])

    def test_replace_logo_brand_ref_keeps_single_logo_row(self) -> None:
        logo_a = Path(self._tmpdir.name) / "logo-a.png"
        logo_b = Path(self._tmpdir.name) / "logo-b.png"
        logo_a.write_bytes(b"a")
        logo_b.write_bytes(b"b")
        first = db.replace_logo_brand_ref("demo", str(logo_a), "logo-a.png")
        assert first is not None
        self.assertEqual(first["kind"], "logo")
        second = db.replace_logo_brand_ref("demo", str(logo_b), "logo-b.png")
        assert second is not None
        listed = db.list_brand_refs("demo")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["path"], str(logo_b))


if __name__ == "__main__":
    unittest.main()
