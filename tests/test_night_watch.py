import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import night_watch as nw


class NightWatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.patches = [patch.object(nw, "STATE", state),
                        patch.object(nw, "TASK", state / "task.json"),
                        patch.object(nw, "alert", lambda *a, **k: None),
                        patch.object(nw, "log", lambda *a, **k: None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def task(self, **extra):
        task = {"code": "133045A", "amount": "0.01", "at": "2026-11-03T09:00:00.200",
                "dry_run": False, "phase": "armed", "login_tried": False}
        task.update(extra)
        nw.save_task(task)
        return task

    def test_target_needs_date_and_lead(self):
        now = datetime(2026, 11, 2, 23, 0)
        with self.assertRaises(nw.Abort):
            nw.parse_target("09:00:00", now)
        with self.assertRaises(nw.Abort):
            nw.parse_target("2026-11-02T23:15:00", now)   # inside the 17 min lead
        with self.assertRaises(nw.Abort):
            nw.parse_target("2026-11-04T09:00:00", now)
        self.assertEqual(nw.parse_target("2026-11-03T09:00:00", now),
                         datetime(2026, 11, 3, 9, 0, 0))
        self.assertEqual(nw.OPEN_DELAY, timedelta(milliseconds=200))

    def test_short_prep_allows_quick_rehearsal(self):
        now = datetime(2026, 11, 2, 23, 0)
        self.assertEqual(nw.parse_target("2026-11-02T23:07:00", now, prep_minutes=5),
                         datetime(2026, 11, 2, 23, 7))
        with self.assertRaises(nw.Abort):
            nw.parse_target("2026-11-02T23:06:59", now, prep_minutes=5)
        with self.assertRaises(nw.Abort):
            nw.parse_target("2026-11-02T23:30:00", now, prep_minutes=4)

    def test_fire_marks_firing_before_submitting(self):
        seen = []
        fake = types.SimpleNamespace(
            run=lambda *a, **k: seen.append(nw.load_task()["phase"]) or "提交成功",
            close_password_panel=lambda: None)
        with patch.dict(sys.modules, {"fast_buy_uia2": fake}):
            nw.fire(self.task(), datetime.now())
        self.assertEqual(seen, ["firing"])
        self.assertEqual(nw.load_task()["phase"], "done")

    def test_fire_failure_never_retries(self):
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("页面不对")
        fake = types.SimpleNamespace(run=boom, close_password_panel=lambda: None)
        with patch.dict(sys.modules, {"fast_buy_uia2": fake}):
            nw.fire(self.task(), datetime.now())
        self.assertEqual(len(calls), 1)
        self.assertEqual(nw.load_task()["phase"], "done")

    def test_restarted_watcher_does_not_fire_again(self):
        for phase in ("firing", "done", "aborted", "disarmed"):
            self.task(phase=phase)
            with patch.object(nw, "fire") as fire:
                nw.run(None)
            fire.assert_not_called()

    def test_disarm_refuses_while_firing(self):
        self.task(phase="firing")
        with self.assertRaises(nw.Abort):
            nw.disarm(None)

    def login_env(self, logged_in, login_page=lambda: True):
        return [patch.object(nw, "cold_start"),
                patch.object(nw, "logged_in", side_effect=logged_in),
                patch.object(nw, "on_login_page", side_effect=login_page),
                patch.object(nw, "read_screen", return_value="tree"),
                patch.object(nw, "alert"),
                patch.object(nw.keychain_store, "load", return_value={"login_pattern": "1235"}),
                patch.object(nw.time, "sleep")]

    def test_login_stops_after_three_patterns(self):
        task = self.task(patterns_sent=0)
        mocks = self.login_env(logged_in=lambda: False)
        with patch.object(nw.secure_input, "login") as login:
            for m in mocks:
                m.start()
            try:
                with self.assertRaises(nw.Abort):
                    nw.login_fresh(task)
            finally:
                for m in mocks:
                    m.stop()
        self.assertEqual(login.call_count, nw.LOGIN_TRIES)
        self.assertEqual(nw.load_task()["patterns_sent"], nw.LOGIN_TRIES)

    def test_pattern_budget_survives_restart(self):
        task = self.task(patterns_sent=nw.LOGIN_TRIES)
        mocks = self.login_env(logged_in=lambda: False)
        with patch.object(nw.secure_input, "login") as login:
            for m in mocks:
                m.start()
            try:
                with self.assertRaises(nw.Abort):
                    nw.login_fresh(task)
            finally:
                for m in mocks:
                    m.stop()
        login.assert_not_called()

    def test_login_retries_after_cold_restart(self):
        # first pattern fails, second succeeds
        states = iter([False, False, False, True])   # before/after each attempt
        pages = iter([True, True, False])
        task = self.task(patterns_sent=0)
        mocks = self.login_env(logged_in=lambda: next(states), login_page=lambda: next(pages))
        with patch.object(nw.secure_input, "login") as login:
            for m in mocks:
                m.start()
            try:
                nw.login_fresh(task)
            finally:
                for m in mocks:
                    m.stop()
        self.assertEqual(login.call_count, 2)
        self.assertEqual(nw.load_task()["patterns_sent"], 2)
        login.assert_called_with("1235", root="tree")   # uia2 tree, not uiautomator dump

    def test_unreadable_login_page_costs_no_pattern(self):
        task = self.task(patterns_sent=0)
        mocks = self.login_env(logged_in=lambda: False)
        with patch.object(nw.secure_input, "login") as login:
            for m in mocks:
                m.start()
            try:
                with patch.object(nw, "read_screen", side_effect=RuntimeError("无法读取")):
                    with self.assertRaises(nw.Abort):
                        nw.login_fresh(task)
            finally:
                for m in mocks:
                    m.stop()
        login.assert_not_called()
        self.assertEqual(nw.load_task()["patterns_sent"], 0)

    def test_already_logged_in_sends_no_pattern(self):
        task = self.task(patterns_sent=0)
        mocks = self.login_env(logged_in=lambda: True)
        with patch.object(nw.secure_input, "login") as login:
            for m in mocks:
                m.start()
            try:
                nw.login_fresh(task)
            finally:
                for m in mocks:
                    m.stop()
        login.assert_not_called()

    def test_detail_failure_does_not_fail_prepare(self):
        # The form opens from the app link at sale time; the detail page is
        # only a warm-up, and a second prepare must not log in again.
        task = self.task()
        done = {}
        with patch.object(nw, "ensure_emulator"), patch.object(nw, "ensure_awake"), \
             patch.object(nw, "adb", return_value="1234\n"), \
             patch.object(nw, "login_fresh") as login, \
             patch.object(nw, "log"), \
             patch.object(nw, "open_detail", side_effect=[RuntimeError("慢"), None]):
            nw.prepare(task, [0], done)
            nw.prepare(task, [0], done)
        login.assert_called_once()

    def test_emulator_restart_needs_three_strikes(self):
        strikes = [0]
        with patch.object(nw, "emulator_running", return_value=False), \
             patch.object(nw, "restart_emulator") as restart:
            nw.ensure_emulator(strikes)
            nw.ensure_emulator(strikes)
            restart.assert_not_called()
            nw.ensure_emulator(strikes)
            restart.assert_called_once()

    def page(self, url, visible=True, screen_y=0, empty=False, width=320, height=592):
        import json
        return {"url": url, "type": "page", "description": json.dumps(
            {"visible": visible, "screenY": screen_y, "empty": empty,
             "width": width, "height": height})}

    def test_full_screen_ignores_embedded_and_hidden(self):
        detail = "https://x/financedetail.html?XRIPINN=133045A"
        self.assertTrue(nw.is_full_screen(self.page(detail)))
        self.assertFalse(nw.is_full_screen(self.page(detail, screen_y=310)))   # 首页内嵌
        self.assertFalse(nw.is_full_screen(self.page(detail, visible=False)))
        self.assertFalse(nw.is_full_screen(self.page(detail, width=228, height=305)))   # 客户经理卡片
        with patch.object(nw, "webview_pages", return_value=[self.page(detail, screen_y=310)]):
            self.assertFalse(nw.detail_open("133045A"))
            self.assertTrue(nw.detail_open("133045A", full=False))
            self.assertFalse(nw.detail_open("999999", full=False))

    def test_open_detail_prefers_app_link(self):
        with patch.object(nw.fast_buy, "ensure_forward"), \
             patch.object(nw, "detail_open", return_value=False), \
             patch.object(nw, "open_by_link", return_value=True), \
             patch.object(nw, "tap_text") as tap:
            nw.open_detail("133045A")
        tap.assert_not_called()

    def test_app_link_encodes_url(self):
        link = nw.app_link("https://m.cmb/x.html?a=1&b=2")
        self.assertTrue(link.startswith("cmbmobilebank://cmbls/FunctionJump/?action=gourl&src=https%3A%2F%2F"))
        self.assertIn("a%3D1%26b%3D2&closeCurrentView=false&needlogin=true", link)

    def test_open_detail_goes_through_licai_full_screen(self):
        licai = self.page("https://x/tabfinprddefault.html")
        with patch.object(nw.fast_buy, "ensure_forward"), \
             patch.object(nw, "detail_open", return_value=False), \
             patch.object(nw, "open_by_link", return_value=False), \
             patch.object(nw, "wait_full_screen", side_effect=[None, licai]), \
             patch.object(nw, "tap_text", return_value=True) as tap, \
             patch.object(nw, "jump", return_value=True) as jump, \
             patch.object(nw.time, "sleep"):
            nw.open_detail("133045A")
        self.assertEqual([c.args[0] for c in tap.call_args_list], ["首页", "理财"])
        jump.assert_called_once_with(licai, "133045A", True, 15.0)

    def test_open_detail_falls_back_to_embedded(self):
        embedded = self.page("", screen_y=310)
        with patch.object(nw.fast_buy, "ensure_forward"), \
             patch.object(nw, "detail_open", return_value=False), \
             patch.object(nw, "open_by_link", return_value=False), \
             patch.object(nw, "wait_full_screen", return_value=None), \
             patch.object(nw, "tap_text", return_value=False), \
             patch.object(nw, "webview_pages", return_value=[embedded]), \
             patch.object(nw, "jump", return_value=True) as jump:
            nw.open_detail("133045A")
        jump.assert_called_once_with(embedded, "133045A", False, 15.0)

    def test_restart_restores_screen_on(self):
        with patch.object(nw.manage, "stop"), patch.object(nw.manage, "start"), \
             patch.object(nw, "booted", return_value=True), \
             patch.object(nw, "adb") as adb, patch.object(nw.time, "sleep"):
            nw.restart_emulator()
        calls = [c.args for c in adb.call_args_list]
        self.assertIn(("shell", "settings", "put", "global", "stay_on_while_plugged_in", "15"), calls)
        self.assertIn(("shell", "dumpsys", "battery", "set", "ac", "1"), calls)


if __name__ == "__main__":
    unittest.main()
