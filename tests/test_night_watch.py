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
            nw.parse_target("2026-11-02T23:08:00", now)   # inside the default 9 min lead
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

    def test_zero_prep_is_immediate_and_skips_the_time_check(self):
        # 0 does not mean "cold start at the sale second": arming starts the
        # cold start at once, so no remaining-time requirement applies.
        now = datetime(2026, 11, 2, 23, 0)
        self.assertEqual(nw.parse_target("2026-11-02T23:00:30", now, prep_minutes=0),
                         datetime(2026, 11, 2, 23, 0, 30))
        self.assertEqual(nw.parse_target("2026-11-02T23:00:00", now, prep_minutes=0),
                         datetime(2026, 11, 2, 23, 0))
        with self.assertRaises(nw.Abort):   # the 24 h ceiling still applies
            nw.parse_target("2026-11-04T09:00:00", now, prep_minutes=0)
        with self.assertRaises(nw.Abort):   # out of range
            nw.parse_target("2026-11-02T23:30:00", now, prep_minutes=-1)

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
        return [patch.object(nw, "network_state", return_value="up"),
                patch.object(nw, "cold_start"),
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

    def test_login_here_logs_in_once_on_the_gesture_page(self):
        task = self.task(patterns_sent=0)
        pages = iter([True, False, False])   # login page, then gone twice
        with patch.object(nw, "read_screen", return_value="tree"), \
             patch.object(nw.secure_input, "login_page", side_effect=lambda root: next(pages)), \
             patch.object(nw.keychain_store, "load", return_value={"login_pattern": "1235"}), \
             patch.object(nw.time, "sleep"), \
             patch.object(nw.secure_input, "login") as login:
            self.assertTrue(nw.login_here(task))
        self.assertEqual(login.call_count, 1)
        self.assertEqual(login.call_args.kwargs["root"], "tree")
        self.assertEqual(task["patterns_sent"], 1)
        self.assertEqual(nw.load_task()["patterns_sent"], 1)

    def test_login_here_does_nothing_without_the_login_page(self):
        task = self.task(patterns_sent=0)
        with patch.object(nw, "read_screen", return_value="tree"), \
             patch.object(nw.secure_input, "login_page", return_value=False), \
             patch.object(nw.secure_input, "login") as login:
            self.assertFalse(nw.login_here(task))
        login.assert_not_called()
        self.assertEqual(task["patterns_sent"], 0)

    def test_login_here_respects_the_pattern_budget(self):
        task = self.task(patterns_sent=nw.LOGIN_TRIES)
        with patch.object(nw, "read_screen", return_value="tree"), \
             patch.object(nw.secure_input, "login_page", return_value=True), \
             patch.object(nw.secure_input, "login") as login:
            with self.assertRaises(nw.Abort):
                nw.login_here(task)
        login.assert_not_called()

    def test_logged_in_rejects_a_login_overlay(self):
        # An unprotected screenshot is not enough: the gesture view still
        # means the login page is on screen.
        with patch.object(nw, "read_screen", return_value="tree"), \
             patch.object(nw.secure_input, "login_page", return_value=True), \
             patch.object(nw.secure_input, "screen_protected", return_value=False):
            self.assertFalse(nw.logged_in())

    def test_detail_failure_does_not_fail_prepare(self):
        # The form opens from the app link at sale time; the detail page is
        # only a warm-up, and a second prepare must not log in again.
        task = self.task()
        done = {}
        with patch.object(nw, "ensure_emulator"), patch.object(nw, "ensure_awake"), \
             patch.object(nw, "ensure_network"), \
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


class FakeClock:
    """Fake monotonic clock: sleeping advances it, so waits cost no real time."""
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def sleep(self, seconds):
        self.seconds += seconds


class ArmHealthTest(unittest.TestCase):
    """布防前健康检查：全部 mock，绝不碰 adb/模拟器/网络，也不真实等待。"""

    def setUp(self):
        self.clock = FakeClock()
        self.m = {}
        patchers = {
            "start": patch.object(nw.manage, "start"),
            "running": patch.object(nw, "emulator_running", return_value=True),
            "booted": patch.object(nw, "booted", return_value=True),
            "network": patch.object(nw, "network_state", return_value="up"),
            "reconnect": patch.object(nw, "reconnect_wifi"),
            "restart": patch.object(nw, "restart_emulator"),
            "screen": patch.object(nw, "keep_screen_on"),
            "log": patch.object(nw, "log"),
        }
        for name, patcher in patchers.items():
            self.m[name] = patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (patch.object(nw.time, "sleep", self.clock.sleep),
                        patch.object(nw.time, "monotonic", self.clock.monotonic)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_healthy_device_is_not_touched(self):
        repairs = nw.arm_health(15)
        self.assertEqual(repairs, [])
        self.m["start"].assert_not_called()
        self.m["restart"].assert_not_called()
        self.m["reconnect"].assert_not_called()
        self.m["screen"].assert_called_once()
        self.m["log"].assert_not_called()

    def test_starts_the_emulator_when_it_is_not_running(self):
        self.m["running"].side_effect = [False, True]
        self.m["booted"].side_effect = [False, True, True]
        notes = []
        repairs = nw.arm_health(15, note=notes.append)
        self.assertEqual(repairs, ["启动模拟器"])
        self.assertIn("模拟器没有在运行，正在启动", notes)
        self.m["start"].assert_called_once()
        self.m["restart"].assert_not_called()
        self.m["log"].assert_not_called()

    def test_boot_timeout_restarts_the_emulator(self):
        state = {"booted": False}
        self.m["running"].side_effect = [False, True]
        self.m["booted"].side_effect = lambda: state["booted"]
        self.m["restart"].side_effect = lambda tick=None: state.update(booted=True)
        notes = []
        repairs = nw.arm_health(1, note=notes.append)
        self.assertEqual(repairs, ["启动模拟器", "重启模拟器"])
        self.assertIn("模拟器没有在等待时间内开机，正在重启模拟器", notes)
        self.assertGreaterEqual(self.clock.seconds, 60)
        self.m["restart"].assert_called_once()
        self.assertIsNotNone(self.m["restart"].call_args.kwargs["tick"])
        self.m["log"].assert_not_called()

    def test_restart_failure_becomes_one_unified_abort(self):
        self.m["running"].side_effect = [False, True]
        self.m["booted"].return_value = False
        self.m["restart"].side_effect = nw.Abort("模拟器重启后 5 分钟仍未开机。")
        with self.assertRaises(nw.Abort) as ctx:
            nw.arm_health(1)
        text = str(ctx.exception)
        self.assertIn("健康检查未通过", text)
        self.assertIn("已尝试", text)
        self.assertIn("启动模拟器", text)
        self.assertIn("重启模拟器", text)
        self.assertIn("最长等待 1 分钟", text)

    def test_down_network_reconnects_wifi(self):
        self.m["network"].side_effect = ["down", "up", "up"]
        notes = []
        repairs = nw.arm_health(15, note=notes.append)
        self.assertEqual(repairs, ["重新连接 Wi-Fi"])
        self.assertIn("模拟器没有网络，正在重新连接 Wi-Fi", notes)
        self.assertIn("网络已恢复", notes)
        self.m["reconnect"].assert_called_once()
        self.m["restart"].assert_not_called()
        self.m["log"].assert_not_called()

    def test_no_device_restarts_the_emulator(self):
        self.m["network"].side_effect = ["no-device", "up"]
        notes = []
        repairs = nw.arm_health(15, note=notes.append)
        self.assertEqual(repairs, ["重启模拟器"])
        self.assertIn("adb 连不上模拟器，正在重启模拟器", notes)
        self.m["restart"].assert_called_once()
        self.m["reconnect"].assert_not_called()
        self.m["log"].assert_not_called()

    def test_screen_on_failure_is_a_note_not_a_failure(self):
        self.m["screen"].side_effect = nw.Abort("stay_on 失败")
        notes = []
        repairs = nw.arm_health(15, note=notes.append)
        self.assertEqual(repairs, [])
        self.assertIn("恢复屏幕常亮失败（Abort），继续布防", notes)

    def test_final_confirmation_aborts_when_network_is_gone(self):
        self.m["network"].side_effect = ["up", "down"]
        with self.assertRaises(nw.Abort) as ctx:
            nw.arm_health(15)
        self.assertIn("健康检查未通过", str(ctx.exception))
        self.assertIn("仍然没有网络", str(ctx.exception))

    def test_waiting_ticks_and_notes_without_touching_watch_log(self):
        self.m["running"].side_effect = [False, True]
        self.m["booted"].side_effect = [False, False, True, True]
        ticks, notes = [], []
        repairs = nw.arm_health(1, tick=lambda: ticks.append(1), note=notes.append)
        self.assertEqual(repairs, ["启动模拟器"])
        self.assertGreaterEqual(len(ticks), 2)
        self.assertIn("模拟器没有在运行，正在启动", notes)
        self.m["log"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
