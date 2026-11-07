"""Non-secret push preferences; temporary files only, no network or Keychain."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import push
import push_settings


class PushSettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "night/push-settings.json"
        location = patch.object(push_settings, "SETTINGS", self.path)
        location.start()
        self.addCleanup(location.stop)
        # A regression must never touch the real credential store or network.
        self.keychain = patch.object(push.keychain_store, "find", side_effect=AssertionError("real Keychain forbidden"))
        self.keychain.start()
        self.addCleanup(self.keychain.stop)
        network = patch.object(push._OPENER, "open", side_effect=AssertionError("real network forbidden"))
        network.start()
        self.addCleanup(network.stop)

    def test_missing_file_defaults_all_on_without_creating_files(self):
        settings = push_settings.load()
        self.assertIs(settings["enabled"], True)
        self.assertEqual(len(settings["events"]), 25)
        self.assertTrue(all(value is True for value in settings["events"].values()))
        self.assertIs(settings["events"]["app_started"], True)
        self.assertIs(settings["events"]["app_exited"], True)
        self.assertFalse(self.path.parent.exists())

    def test_partial_fields_fill_defaults_and_return_independent_objects(self):
        settings = push_settings.validate({"events": {"plan_completed": False}})
        self.assertTrue(settings["enabled"])
        self.assertFalse(settings["events"]["plan_completed"])
        self.assertTrue(settings["events"]["purchase_unknown"])
        settings["events"]["purchase_unknown"] = False
        self.assertTrue(push_settings.validate({})["events"]["purchase_unknown"])
        self.assertTrue(push_settings.validate({"enabled": False})["events"]["plan_completed"])

    def test_strict_validation_rejects_unknown_fields_and_non_booleans(self):
        invalid = [None, [], "enabled", {"other": True}, {"events": None},
                   {"events": []}, {"events": {"typo": True}}]
        for value in (0, 1, "true", "false", None, [], {}):
            invalid.extend([{"enabled": value}, {"events": {"purchase_success": value}}])
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(RuntimeError):
                push_settings.validate(values)
        self.assertFalse(self.path.parent.exists())

    def test_save_atomically_writes_private_complete_json(self):
        with patch.object(push_settings.os, "replace", wraps=os.replace) as replace:
            result = push_settings.save({"enabled": False, "events": {"login_success": False}})
        self.assertEqual(json.loads(self.path.read_text()), result)
        self.assertEqual(push_settings.load(), result)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.with_suffix(".lock").stat().st_mode & 0o777, 0o600)
        self.assertEqual(replace.call_count, 1)
        self.assertEqual(replace.call_args.args[1], self.path)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertFalse(result["events"]["login_success"])
        self.assertTrue(result["events"]["watch_started"])

    def test_partial_saves_keep_existing_values(self):
        push_settings.save({"enabled": False, "events": {"login_success": False}})
        result = push_settings.save({"events": {"plan_started": False}})
        self.assertFalse(result["enabled"])
        self.assertFalse(result["events"]["login_success"])
        self.assertFalse(result["events"]["plan_started"])
        result = push_settings.save({"enabled": True})
        self.assertTrue(result["enabled"])
        self.assertFalse(result["events"]["login_success"])
        self.assertFalse(result["events"]["plan_started"])
        self.assertEqual(push_settings.save({}), result)

    def test_concurrent_partial_updates_do_not_lose_event_changes(self):
        keys = ["watch_started", "watch_cancelled", "plan_started", "plan_completed"]
        barrier = threading.Barrier(len(keys), timeout=2)

        def update(key):
            barrier.wait()
            return push_settings.save({"events": {key: False}})

        with ThreadPoolExecutor(max_workers=len(keys)) as executor:
            futures = [executor.submit(update, key) for key in keys]
            for future in futures:
                future.result(timeout=2)
        result = push_settings.load()
        for key in keys:
            self.assertFalse(result["events"][key])
        self.assertTrue(result["events"]["purchase_unknown"])

    def test_invalid_save_never_creates_files_or_overwrites_saved_state(self):
        with self.assertRaises(RuntimeError):
            push_settings.save({"enabled": 1})
        self.assertFalse(self.path.parent.exists())
        push_settings.save({"enabled": False})
        before = self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            push_settings.save({"events": {"purchase_unknown": "false"}})
        self.assertEqual(self.path.read_bytes(), before)

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temp(self):
        push_settings.save({"enabled": False})
        before = self.path.read_bytes()
        with patch.object(push_settings.os, "replace", side_effect=OSError("disk unavailable")):
            with self.assertRaises(RuntimeError):
                push_settings.save({"enabled": True})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        # The failed write must release its lock so the next save can succeed.
        self.assertTrue(push_settings.save({"enabled": True})["enabled"])

    def test_partial_legacy_file_defaults_new_events_to_enabled(self):
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({"events": {"watch_started": False}}))
        settings = push_settings.load()
        self.assertTrue(settings["enabled"])
        self.assertFalse(settings["events"]["watch_started"])
        self.assertTrue(settings["events"]["purchase_unknown"])

    def test_invalid_file_fails_without_silently_overwriting_user_preferences(self):
        self.path.parent.mkdir()
        for text in ("{broken", "[]", '{"enabled": 1}', '{"events":{"typo":true}}'):
            self.path.write_text(text)
            with self.subTest(text=text):
                with self.assertRaises(RuntimeError):
                    push_settings.load()
                with self.assertRaises(RuntimeError):
                    push_settings.save({"enabled": True})
                self.assertEqual(self.path.read_text(), text)

    def test_non_utf8_file_is_reported_as_invalid(self):
        self.path.parent.mkdir()
        self.path.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(RuntimeError, "格式无效"):
            push_settings.load()

    def test_unreadable_file_and_unwritable_directory_report_safe_errors(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("mock denial")):
            with self.assertRaisesRegex(RuntimeError, "无法读取"):
                push_settings.load()
        with patch.object(Path, "mkdir", side_effect=PermissionError("mock denial")):
            with self.assertRaisesRegex(RuntimeError, "无法保存"):
                push_settings.save({"enabled": False})

    def test_view_has_flat_settings_and_complete_catalog_without_shared_mutation(self):
        view = push_settings.view()
        self.assertEqual(set(view), {"enabled", "events", "catalog"})
        keys = [event["key"] for event in view["catalog"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(view["events"]))
        for row in view["catalog"]:
            self.assertEqual(set(row), {"key", "label", "description", "group"})
            self.assertTrue(all(isinstance(value, str) and value for value in row.values()))
        view["catalog"][0]["label"] = "changed"
        view["events"][keys[0]] = False
        self.assertNotEqual(push_settings.view()["catalog"][0]["label"], "changed")
        self.assertTrue(push_settings.load()["events"][keys[0]])

    def test_saved_event_changes_apply_to_next_send_without_restart(self):
        with patch.object(push, "load", return_value={"mock": True}) as credential, \
             patch.object(push, "_deliver", return_value=(True, None)) as deliver:
            self.assertTrue(push.send("状态", "布防", event="watch_started"))
            push_settings.save({"events": {"watch_started": False}})
            self.assertFalse(push.send("状态", "布防", event="watch_started"))
            self.assertTrue(push.send("结果", "成功", event="purchase_success"))
            push_settings.save({"enabled": False})
            self.assertFalse(push.send("结果", "成功", event="purchase_success"))
            push_settings.save({"enabled": True, "events": {"watch_started": True}})
            self.assertTrue(push.send("状态", "布防", event="watch_started"))
        self.assertEqual(deliver.call_count, 3)
        self.assertEqual(credential.call_count, 3)

    def test_test_push_ignores_saved_global_and_event_switches(self):
        push_settings.save({"enabled": False,
                            "events": {key: False for key in push_settings.EVENT_KEYS}})
        with patch.object(push, "load", return_value={"mock": True}), \
             patch.object(push, "_deliver", return_value=(True, None)) as deliver:
            self.assertEqual(push.send_test(), {"sent": True})
        deliver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
