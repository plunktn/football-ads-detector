"""Durable kickoff / 2T profiles (YAML + API, not cloud sync)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import db
from app.config import clock_overrides
from app.config.clock_overrides import (
    ClockOverrideError,
    get_clock_override,
    load_clock_overrides,
    merge_clock_request,
    upsert_clock_override,
)
from app.main import app


class ClockOverrideTests(unittest.TestCase):
    def test_shipped_libertad_profile_is_continuous_at_4145(self) -> None:
        profile = get_clock_override("libertad-vs-orense")
        self.assertEqual(profile.label, "Libertad vs Orense")
        self.assertEqual(profile.clock_mode, "continuous")
        self.assertIsNone(profile.kickoff_offset_sec)
        self.assertEqual(profile.second_half_start_sec, 4145.0)
        self.assertIn("4145", profile.notes)

    def test_merge_fills_blanks_and_explicit_values_win(self) -> None:
        merged = merge_clock_request(
            profile_id="libertad-vs-orense",
            kickoff_offset_sec=None,
            second_half_start_sec=None,
            clock_mode=None,
        )
        self.assertEqual(merged.profile_id, "libertad-vs-orense")
        self.assertIsNone(merged.kickoff_offset_sec)
        self.assertEqual(merged.second_half_start_sec, 4145.0)
        self.assertEqual(merged.clock_mode, "continuous")

        overridden = merge_clock_request(
            profile_id="libertad-vs-orense",
            kickoff_offset_sec=200.0,
            second_half_start_sec=4200.0,
            clock_mode="reset",
        )
        self.assertEqual(overridden.kickoff_offset_sec, 200.0)
        self.assertEqual(overridden.second_half_start_sec, 4200.0)
        self.assertEqual(overridden.clock_mode, "reset")

    def test_unknown_profile_and_bad_order_fail(self) -> None:
        with self.assertRaises(ClockOverrideError):
            merge_clock_request(
                profile_id="no-existe",
                kickoff_offset_sec=None,
                second_half_start_sec=None,
                clock_mode=None,
            )
        with self.assertRaises(ClockOverrideError):
            merge_clock_request(
                profile_id=None,
                kickoff_offset_sec=100.0,
                second_half_start_sec=100.0,
                clock_mode="reset",
            )

    def test_upsert_roundtrip_does_not_touch_the_repo_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "clock_overrides.yaml"
            path.write_text(
                "profiles:\n"
                "  - id: libertad-vs-orense\n"
                "    label: Libertad vs Orense\n"
                "    clock_mode: continuous\n"
                "    kickoff_offset_sec: null\n"
                "    second_half_start_sec: 4145\n"
                "    notes: qa\n",
                encoding="utf-8",
            )
            saved = upsert_clock_override(
                "libertad-vs-orense",
                {
                    "label": "Libertad vs Orense",
                    "clock_mode": "continuous",
                    "kickoff_offset_sec": 210,
                    "second_half_start_sec": 4145,
                    "notes": "1T medido en este archivo",
                },
                path,
            )
            self.assertEqual(saved.kickoff_offset_sec, 210.0)
            loaded = load_clock_overrides(path)
            self.assertEqual(loaded[0].kickoff_offset_sec, 210.0)
            self.assertEqual(loaded[0].second_half_start_sec, 4145.0)
            repo = get_clock_override("libertad-vs-orense")
            self.assertIsNone(repo.kickoff_offset_sec)


class ClockOverrideApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        db.set_db_path(root / "app.db")
        db.init_db()
        self.path = root / "clock_overrides.yaml"
        self.path.write_text(
            "profiles:\n"
            "  - id: libertad-vs-orense\n"
            "    label: Libertad vs Orense\n"
            "    clock_mode: continuous\n"
            "    kickoff_offset_sec: null\n"
            "    second_half_start_sec: 4145\n"
            "    notes: qa 4145\n",
            encoding="utf-8",
        )
        self._patch = patch.object(clock_overrides, "_DEFAULT_PATH", self.path)
        self._patch.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patch.stop()
        db.reset_db_path()
        self._tmpdir.cleanup()

    def test_get_and_put_roundtrip(self) -> None:
        listed = self.client.get("/clock-overrides")
        self.assertEqual(listed.status_code, 200)
        profiles = listed.json()["profiles"]
        self.assertEqual(profiles[0]["second_half_start_sec"], 4145.0)
        self.assertEqual(profiles[0]["clock_mode"], "continuous")

        saved = self.client.put(
            "/clock-overrides/libertad-vs-orense",
            json={
                "label": "Libertad vs Orense",
                "clock_mode": "continuous",
                "kickoff_offset_sec": 190,
                "second_half_start_sec": 4145,
                "notes": "1T medido en este archivo",
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["kickoff_offset_sec"], 190.0)
        again = self.client.get("/clock-overrides")
        self.assertEqual(again.json()["profiles"][0]["kickoff_offset_sec"], 190.0)

        rejected = self.client.put(
            "/clock-overrides/otro-partido",
            json={
                "label": "Otro",
                "clock_mode": "reset",
                "kickoff_offset_sec": 80,
                "second_half_start_sec": 40,
                "notes": "",
            },
        )
        self.assertEqual(rejected.status_code, 422)


if __name__ == "__main__":
    unittest.main()
