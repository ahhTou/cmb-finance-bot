"""计划调度设置：临时文件、无网络/钥匙串/ADB。"""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import plan_settings


class PlanSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "night/plan-settings.json"
        location = patch.object(plan_settings, "SETTINGS", self.path)
        location.start()
        self.addCleanup(location.stop)

    def test_missing_file_returns_defaults_without_creating_files(self):
        self.assertEqual(plan_settings.load(), plan_settings.DEFAULTS)
        self.assertFalse(self.path.parent.exists())

    def test_view_returns_an_independent_settings_copy(self):
        view = plan_settings.view()
        self.assertEqual(set(view), {"settings"})
        self.assertEqual(view["settings"], plan_settings.DEFAULTS)
        view["settings"]["poll_seconds"] = 99
        self.assertEqual(plan_settings.view()["settings"]["poll_seconds"], 2)

    def test_partial_save_merges_and_is_atomic_private_json(self):
        with patch.object(plan_settings.os, "replace", wraps=os.replace) as replace:
            result = plan_settings.save({"poll_seconds": 3, "heartbeat_seconds": 15})
        self.assertEqual(result["poll_seconds"], 3)
        self.assertEqual(result["heartbeat_seconds"], 15)
        self.assertEqual(result["arm_gap_minutes"], 2)
        self.assertEqual(json.loads(self.path.read_text()), result)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_values_are_rejected_without_overwriting(self):
        plan_settings.save({"grace_seconds": 20})
        before = self.path.read_bytes()
        for values in ({"poll_seconds": 0}, {"poll_seconds": 61},
                       {"heartbeat_seconds": "10"}, {"end_timeout_minutes": 121},
                       {"typo": 1}, {"arm_gap_minutes": 1.5}, []):
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                plan_settings.save(values)
        self.assertEqual(self.path.read_bytes(), before)

    def test_heartbeat_must_not_be_shorter_than_poll(self):
        with self.assertRaisesRegex(RuntimeError, "心跳间隔"):
            plan_settings.save({"poll_seconds": 5, "heartbeat_seconds": 3})

    def test_invalid_file_is_reported_and_not_silently_rewritten(self):
        self.path.parent.mkdir()
        for text in ("{broken", "[]", '{"poll_seconds": 0}', '{"typo": 1}'):
            self.path.write_text(text)
            with self.subTest(text=text):
                with self.assertRaises(RuntimeError):
                    plan_settings.load()
                with self.assertRaises(RuntimeError):
                    plan_settings.save({"poll_seconds": 2})
                self.assertEqual(self.path.read_text(), text)

    def test_snapshot_fills_defaults_and_keeps_snapshot_values(self):
        raw = {"poll_seconds": 4, "grace_seconds": 0, "end_timeout_minutes": -1}
        result = plan_settings.snapshot(raw)
        self.assertEqual(result["poll_seconds"], 4)
        self.assertEqual(result["grace_seconds"], 0)
        self.assertEqual(result["end_timeout_minutes"], -1)
        self.assertEqual(result["heartbeat_seconds"], 10)
        # A corrupt snapshot must not become a zero or non-integer sleep.
        self.assertEqual(plan_settings.snapshot({"poll_seconds": "2"}), plan_settings.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
