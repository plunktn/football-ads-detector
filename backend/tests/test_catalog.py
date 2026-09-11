import tempfile
import unittest
from pathlib import Path

from app import db
from app.pipeline.aggregate import FrameObservation
from app.pipeline.catalog import classify_led_frame, persist_catalog


class ClassifyLedFrameTests(unittest.TestCase):
    def test_skipped_returns_none(self) -> None:
        self.assertIsNone(
            classify_led_frame(
                skipped=True,
                has_crop=True,
                ocr_text="NETT",
                detected_brand_ids={"nett"},
                ambiguous_brand_ids=set(),
            )
        )

    def test_no_crop_returns_none(self) -> None:
        self.assertIsNone(
            classify_led_frame(
                skipped=False,
                has_crop=False,
                ocr_text="NETT",
                detected_brand_ids=set(),
                ambiguous_brand_ids=set(),
            )
        )

    def test_positive_uses_sorted_detected_id(self) -> None:
        label, brand_id = classify_led_frame(
            skipped=False,
            has_crop=True,
            ocr_text="x",
            detected_brand_ids={"zeta", "alfa"},
            ambiguous_brand_ids=set(),
        )
        self.assertEqual(label, "positive")
        self.assertEqual(brand_id, "alfa")

    def test_attention_via_ocr(self) -> None:
        label, brand_id = classify_led_frame(
            skipped=False,
            has_crop=True,
            ocr_text="  ALGO  ",
            detected_brand_ids=set(),
            ambiguous_brand_ids=set(),
        )
        self.assertEqual(label, "attention")
        self.assertIsNone(brand_id)

    def test_attention_via_ambiguous(self) -> None:
        label, brand_id = classify_led_frame(
            skipped=False,
            has_crop=True,
            ocr_text="",
            detected_brand_ids=set(),
            ambiguous_brand_ids={"nett"},
        )
        self.assertEqual(label, "attention")
        self.assertIsNone(brand_id)

    def test_empty(self) -> None:
        label, brand_id = classify_led_frame(
            skipped=False,
            has_crop=True,
            ocr_text="  ",
            detected_brand_ids=set(),
            ambiguous_brand_ids=set(),
        )
        self.assertEqual(label, "empty")
        self.assertIsNone(brand_id)


class PersistCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        db.set_db_path(Path(self._tmpdir.name) / "test.db")
        db.init_db()
        db.insert_job(
            job_id="job-1",
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

    def test_persist_skips_fixed_and_discarded(self) -> None:
        observations = [
            FrameObservation(
                half="1T",
                time_seconds=1.0,
                frame_idx=1,
                detected_brand_ids=frozenset({"nett"}),
                skipped=False,
                zone_id="led_lateral_main",
                posicion="LATERAL_MAIN",
                tipo_panel="LED",
                ocr_text="NETT",
                crop_relpath="catalog/led_000001.jpg",
                context_relpath="catalog/ctx_000001.jpg",
            ),
            FrameObservation(
                half="1T",
                time_seconds=2.0,
                frame_idx=2,
                detected_brand_ids=frozenset(),
                skipped=True,
                zone_id="led_lateral_main",
                tipo_panel="LED",
            ),
            FrameObservation(
                half="1T",
                time_seconds=3.0,
                frame_idx=3,
                detected_brand_ids=frozenset({"board"}),
                skipped=False,
                zone_id="fixed_1",
                tipo_panel="FIXED_PRINT",
                crop_relpath="catalog/should_not.jpg",
            ),
        ]
        discarded = persist_catalog("job-1", self._tmpdir.name, observations)
        self.assertEqual(discarded, 1)
        frames = db.list_job_frames("job-1")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["machine_label"], "positive")
        self.assertEqual(frames[0]["brand_id"], "nett")
        self.assertEqual(frames[0]["context_relpath"], "catalog/ctx_000001.jpg")
        row = db.get_job_row("job-1")
        assert row is not None
        self.assertEqual(row["catalog_discarded_count"], 1)


if __name__ == "__main__":
    unittest.main()
