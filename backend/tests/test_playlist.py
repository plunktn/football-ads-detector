import tempfile
import unittest
from pathlib import Path

from app.pipeline.playlist import (
    libertad_orense_fixture_sheets,
    parse_minuto,
    parse_playlist,
    period_from_sheet,
    slots_for_verify,
    unique_brands,
    write_lions_workbook,
)


class MinutoParseTests(unittest.TestCase):
    def test_decimal_mm_ss(self) -> None:
        self.assertEqual(parse_minuto("0.15"), 15.0)
        self.assertEqual(parse_minuto(0.15), 15.0)
        self.assertEqual(parse_minuto("1.30"), 90.0)
        self.assertEqual(parse_minuto(1.3), 90.0)
        self.assertEqual(parse_minuto("12.05"), 725.0)

    def test_colon_and_whole_minutes(self) -> None:
        self.assertEqual(parse_minuto("0:15"), 15.0)
        self.assertEqual(parse_minuto(15), 15 * 60)
        self.assertEqual(parse_minuto("15"), 15 * 60)


class PlaylistParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "PLAYLIST_LIBERTADvORENSE.xlsx"
        write_lions_workbook(self.path, libertad_orense_fixture_sheets())

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_reads_every_sheet_not_just_active(self) -> None:
        slots = parse_playlist(self.path)
        periods = {slot.period for slot in slots}
        self.assertEqual(periods, {"PREVIA", "1T", "ENTRETIEMPO", "2T", "POST"})
        self.assertGreaterEqual(len(slots), 10)
        first_half = [slot for slot in slots if slot.period == "1T"]
        self.assertEqual(first_half[0].brand, "NETT.plus")
        self.assertEqual(first_half[0].start_sec, 15.0)
        self.assertEqual(first_half[0].duration_sec, 15.0)
        self.assertEqual(first_half[0].end_sec, 30.0)
        camero = next(slot for slot in first_half if slot.brand == "CAMERO")
        self.assertEqual(camero.start_sec, 150.0)
        second = [slot for slot in slots if slot.period == "2T"]
        coble = next(slot for slot in second if slot.brand == "COBLERED")
        self.assertEqual(coble.start_sec, 75.0)

    def test_verify_keeps_only_match_halves(self) -> None:
        slots = slots_for_verify(parse_playlist(self.path))
        self.assertTrue(all(slot.period in {"1T", "2T"} for slot in slots))
        self.assertEqual(len(slots), 7)

    def test_unique_brands_preserve_playlist_spelling(self) -> None:
        names = unique_brands(parse_playlist(self.path))
        self.assertIn("NETT.plus", names)
        self.assertIn("CAMERO", names)

    def test_sheet_name_aliases(self) -> None:
        self.assertEqual(period_from_sheet("PRIMER TIEMPO"), "1T")
        self.assertEqual(period_from_sheet("2do tiempo"), "2T")
        self.assertEqual(period_from_sheet("Previa"), "PREVIA")


if __name__ == "__main__":
    unittest.main()
