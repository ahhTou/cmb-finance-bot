import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import night_watch as nw


def iso(when):
    return when.replace(microsecond=0).isoformat()


class RedemptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.now = datetime.now().replace(microsecond=0)
        keys = MagicMock()
        keys.load.return_value = {"login_pattern": "1235"}
        notify = MagicMock()
        notify.configured.return_value = True
        self.patches = [patch.object(nw, "STATE", state),
                        patch.object(nw, "TASK", state / "task.json"),
                        patch.object(nw, "alert"),
                        patch.object(nw, "log"),
                        patch.object(nw, "spawn_watch"),
                        patch.object(nw, "adb", return_value=""),
                        patch.object(nw, "emulator_running", return_value=True),
                        patch.object(nw, "booted", return_value=True),
                        patch.object(nw, "keychain_store", keys),
                        patch.object(nw, "notify", notify),
                        patch.object(nw.subprocess, "run",
                                     return_value=types.SimpleNamespace(stdout="AC Power")),
                        patch("builtins.print")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def arm(self, **extra):
        start = self.now + timedelta(minutes=30)
        args = dict(code="JX040229", amount="3000", at=iso(start), dry_run=False,
                    prep_minutes=15, now=False, mode="redemption", window_minutes=None, until=None)
        args.update(extra)
        return nw.arm_task(**args), start

    def task(self, **extra):
        start = self.now + timedelta(minutes=10)
        task = {"code": "JX040229", "amount": "3000", "at": iso(start),
                "fire_at": iso(start + nw.OPEN_DELAY), "dry_run": False, "phase": "armed",
                "mode": "redemption", "end_at": iso(start + timedelta(minutes=3)),
                "window_minutes": 3}
        task.update(extra)
        nw.save_task(task)
        return task

    # ---- arming

    def test_redemption_defaults_to_three_minutes(self):
        task, start = self.arm()
        self.assertEqual(task["mode"], "redemption")
        self.assertEqual(task["window_minutes"], 3)
        self.assertEqual(datetime.fromisoformat(task["end_at"]), start + timedelta(minutes=3))
        self.assertEqual(datetime.fromisoformat(task["fire_at"]), start + nw.OPEN_DELAY)

    def test_redemption_window_and_until(self):
        task, start = self.arm(window_minutes=7)
        self.assertEqual(task["window_minutes"], 7)
        self.assertEqual(datetime.fromisoformat(task["end_at"]), start + timedelta(minutes=7))
        # --until wins over --window-minutes
        task, _ = self.arm(window_minutes=7, until=iso(start + timedelta(minutes=2)))
        self.assertEqual(task["window_minutes"], 2)
        self.assertEqual(datetime.fromisoformat(task["end_at"]), start + timedelta(minutes=2))

    def test_window_bounds(self):
        for minutes in (0, -1, nw.MAX_WINDOW_MINUTES + 1):
            with self.assertRaises(nw.Abort):
                self.arm(window_minutes=minutes)
        _, start = self.arm()
        with self.assertRaises(nw.Abort):   # ends before it starts
            self.arm(until=iso(start - timedelta(seconds=1)))
        with self.assertRaises(nw.Abort):   # must carry a date
            self.arm(until="00:18:00")
        with self.assertRaises(nw.Abort):
            self.arm(until=iso(start + timedelta(minutes=nw.MAX_WINDOW_MINUTES + 1)))

    def test_window_is_redemption_only(self):
        with self.assertRaises(nw.Abort):
            self.arm(mode="first_launch", window_minutes=3)
        with self.assertRaises(nw.Abort):
            self.arm(mode="first_launch", until=iso(self.now + timedelta(minutes=35)))

    def test_first_launch_task_keeps_no_window(self):
        with patch.object(nw.purchase_settings, 'load', return_value={'reopen_deadline': 125}):
            task, _ = self.arm(mode="first_launch")
        self.assertNotIn("end_at", task)
        self.assertEqual(task["mode"], "first_launch")
        self.assertEqual(task['form_deadline'], 125)

    def test_first_launch_uses_deadline_saved_at_arming(self):
        task = self.task(mode='first_launch', form_deadline=125)
        run = MagicMock(return_value='提交成功')
        with patch.dict(sys.modules, {'fast_buy_uia2': self.fake(run)}), \
             patch.object(nw.purchase_settings, 'load', return_value={'reopen_deadline': 5}):
            nw.fire(task, self.now)
        self.assertEqual(run.call_args.kwargs['form_deadline'], 125)

    # ---- firing

    def fake(self, behaviour):
        return types.SimpleNamespace(run=behaviour, close_password_panel=lambda: None)

    def fire(self, behaviour):
        task = self.task(at=iso(self.now),
                         end_at=iso(self.now + timedelta(minutes=3)))
        with patch.dict(sys.modules, {"fast_buy_uia2": self.fake(behaviour)}), \
             patch.object(nw, "sleep_until"), patch.object(nw.time, "sleep"):
            nw.redemption_fire(task, self.now)
        return task

    def test_form_marks_firing_then_reports_success(self):
        seen = []

        def run(code, amount, at=None, dry_run=False, form_deadline=None,
                form_wait=None, form_gap=None, before_submit=None, tick=None):
            seen.append((code, amount, form_deadline, form_wait, form_gap))
            before_submit()
            seen.append(nw.load_task()["phase"])   # persisted before submitting
            return "提交成功"

        started = datetime.now()
        task = self.fire(run)
        code, amount, deadline, wait, gap = seen[0]
        self.assertEqual((code, amount), ("JX040229", "3000"))
        self.assertAlmostEqual(deadline, 180, delta=3)   # window length
        self.assertEqual(wait, nw.REDEEM_WAIT)
        self.assertEqual(gap, nw.REDEEM_GAP)
        self.assertEqual(seen[1], "firing")
        saved = nw.load_task()
        self.assertEqual(saved["phase"], "done")
        self.assertEqual(saved["result"], "提交成功")
        self.assertTrue(saved.get("fired_at"))
        self.assertGreaterEqual(datetime.fromisoformat(saved["fired_at"]), started)

    def test_probe_heartbeat_is_persisted(self):
        def run(code, amount, at=None, dry_run=False, form_deadline=None,
                form_wait=None, form_gap=None, before_submit=None, tick=None):
            tick(30)
            return None

        self.fire(run)
        saved = nw.load_task()
        self.assertEqual(saved["probes"], 30)
        self.assertTrue(saved.get("last_tick"))

    def test_sold_out_window_ends_without_submitting(self):
        def run(code, amount, **kwargs):
            raise nw.fast_buy.Stop("打开 140 次，购买表单都没有出现。")

        self.fire(run)
        saved = nw.load_task()
        self.assertEqual(saved["phase"], "done")
        self.assertIn("窗口内没有买到", saved["result"])
        self.assertNotIn("fired_at", saved)

    def test_over_quota_stops_and_alerts_without_submission_marker(self):
        import fast_buy_uia2 as fu
        import xml.etree.ElementTree as ET
        root = ET.fromstring('<hierarchy><node text="3000" />'
                             '<node text="单笔可购买额度200.06元" /></hierarchy>')
        d = MagicMock()
        with patch.object(fu.keychain_store, 'load', return_value={'payment_password': '111111'}), \
             patch.object(fu, 'device', return_value=d), \
             patch.object(fu, 'dump', return_value=root), \
             patch.object(fu.fast_buy, 'ensure_forward'), \
             patch.object(fu, 'open_form', return_value=root) as opener, \
             patch.object(nw, 'alert') as alert:
            self.fire(fu.run)
        saved = nw.load_task()
        self.assertEqual(saved['phase'], 'done')
        self.assertIn('高于页面可购额度', saved['result'])
        self.assertNotIn('fired_at', saved)
        opener.assert_called_once()
        d.assert_not_called()
        self.assertIn('高于页面可购额度', alert.call_args.args[1])

    def test_failure_after_form_is_not_a_retry(self):
        def run(code, amount, **kwargs):
            kwargs["before_submit"]()
            raise nw.fast_buy.Stop("风险弹窗没有出现。")

        self.fire(run)
        saved = nw.load_task()
        self.assertEqual(saved["phase"], "done")
        self.assertIn("结果未知", saved["result"])
        self.assertTrue(saved.get("fired_at"))

    def test_dry_run_reaches_password_page_without_firing(self):
        def run(code, amount, at=None, dry_run=False, form_deadline=None,
                form_wait=None, form_gap=None, before_submit=None, tick=None):
            assert dry_run is True
            assert before_submit is None    # a rehearsal never writes the marker
            return None

        task = self.task(dry_run=True)
        with patch.dict(sys.modules, {"fast_buy_uia2": self.fake(run)}, clear=False), \
             patch.object(nw, "sleep_until"), patch.object(nw.time, "sleep"):
            nw.redemption_fire(task, datetime.fromisoformat(task["at"]))
        saved = nw.load_task()
        self.assertEqual(saved["result"], "演练完成")
        self.assertNotIn("fired_at", saved)

    # ---- dispatch

    def test_run_dispatches_to_redemption(self):
        task = self.task()
        with patch.object(nw, "prepare"), patch.object(nw, "sleep_until"), \
             patch.object(nw, "adb", return_value="1234"), \
             patch.object(nw, "redemption_fire") as redeem, \
             patch.object(nw, "fire") as fire:
            nw.run(None)
        redeem.assert_called_once()
        self.assertEqual(redeem.call_args.args[0]["mode"], "redemption")
        fire.assert_not_called()

    def test_restarted_redemption_watcher_does_not_fire_again(self):
        self.task(phase="firing")
        with patch.object(nw, "redemption_fire") as redeem:
            nw.run(None)
        redeem.assert_not_called()


if __name__ == "__main__":
    unittest.main()
