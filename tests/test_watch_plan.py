"""计划模式后端测试：全部隔离外部世界（adb/模拟器/网络/钥匙串/Popen/真实 sleep）。"""
import contextlib
import json
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import night_watch as nw
import purchase_settings
import query_gate
import watch_plan


def iso(when):
    return when.replace(microsecond=0).isoformat()


def task(task_id="t1", phase="armed", result=None, pid=100, generation="g1"):
    return {"task_id": task_id, "phase": phase, "result": result, "pid": pid,
            "generation": generation, "version": 2}


class PlanTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        for name, value in [("STATE", self.state), ("TASK", self.state / "task.json"),
                            ("LOG", self.state / "watch.log")]:
            self.stack.enter_context(patch.object(nw, name, value))
        self.stack.enter_context(patch.object(purchase_settings, "SETTINGS",
                                              self.state / "purchase-settings.json"))
        self.stack.enter_context(patch.object(nw, "alert"))
        self.stack.enter_context(patch.object(nw, "log"))
        self.stack.enter_context(patch.object(watch_plan, "log"))
        # 任何真实等待都必须被测试挡掉；计划进程轮询间隔是 2 秒。
        self.stack.enter_context(patch.object(watch_plan.time, "sleep"))
        self.now = datetime.now().replace(microsecond=0)

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def at(self, minutes=60):
        return iso(self.now + timedelta(minutes=minutes))

    def item(self, code="TEST01", at=None, mode="first_launch", amount="1000.00"):
        return {"code": code, "amount": amount,
                "at": iso(at) if isinstance(at, datetime) else at, "mode": mode}

    def save(self, items, dry_run=True):
        return watch_plan.save({"dry_run": dry_run, "items": items})

    def running_plan(self, items, dry_run=True, generation="gentest", pid=5555,
                     settings_revision=None):
        plan = self.save(items, dry_run=dry_run)
        plan.update(phase="running", generation=generation, pid=pid,
                    started_at=iso(self.now), last_tick=iso(self.now),
                    settings_revision=settings_revision or
                    purchase_settings.revision(purchase_settings.load()))
        watch_plan.save_plan(plan)
        return plan

    def plan_path(self):
        return self.state / "plan.json"

    @contextlib.contextmanager
    def arm_world(self):
        """真实 _arm() 路径的外部世界：全部 mock，不碰 adb/模拟器/网络/钥匙串。"""
        patches = [
            patch.object(nw.keychain_store, "load"),
            patch.object(nw.notify, "configured", return_value=False),
            patch.object(nw, "emulator_running", return_value=True),
            patch.object(nw, "booted", return_value=True),
            patch.object(nw, "network_state", return_value="up"),
            patch.object(nw, "adb"),
            patch.object(nw, "spawn_watch"),
            patch.object(nw, "alert"),
            patch.object(nw.subprocess, "run",
                         return_value=types.SimpleNamespace(stdout="AC Power")),
            patch("builtins.print"),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            yield


class SaveTest(PlanTestBase):
    def test_rejects_bad_payloads(self):
        good_at = self.at()
        cases = [
            [],                                                   # 不是对象
            {},                                                   # 没有 items
            {"dry_run": 1, "items": []},                          # dry_run 非布尔
            {"dry_run": "yes", "items": []},
            {"dry_run": True, "items": "nope"},
            {"dry_run": True, "items": [{"code": "bad code!", "amount": "1",
                                        "at": good_at, "mode": "first_launch"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "0",
                                        "at": good_at, "mode": "first_launch"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "abc",
                                        "at": good_at, "mode": "first_launch"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "1",
                                        "at": good_at, "mode": "leech"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "1",
                                        "at": "2026-11-07 09:00:00",
                                        "mode": "first_launch"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "1",
                                        "at": "not-a-time", "mode": "first_launch"}]},
            {"dry_run": True, "items": [{"code": "TEST01", "amount": "1",
                                        "at": "2026-11-06T25:00:00",
                                        "mode": "first_launch"}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(nw.Abort):
                    watch_plan.save(payload)
        self.assertFalse(self.plan_path().exists())

    def test_rejects_more_than_twenty_items(self):
        items = [self.item(code=f"T{index:03d}", at=self.now + timedelta(minutes=20 * index))
                 for index in range(watch_plan.MAX_ITEMS + 1)]
        with self.assertRaises(nw.Abort) as ctx:
            self.save(items)
        self.assertIn("最多 20 项", str(ctx.exception))
        self.assertEqual(len(self.save(items[:watch_plan.MAX_ITEMS])["items"]), 20)

    def test_sorts_and_normalizes(self):
        late = self.item(code="BBBB", at=self.now + timedelta(minutes=120))
        early = self.item(code="AAAA", at=self.now + timedelta(minutes=60), amount="1000")
        plan = self.save([late, early], dry_run=False)
        self.assertEqual([row["code"] for row in plan["items"]], ["AAAA", "BBBB"])
        self.assertEqual(plan["items"][0]["amount"], "1000.00")
        self.assertEqual(plan["phase"], "idle")
        self.assertIsNone(plan["generation"])
        self.assertIsNone(plan["started_at"])
        self.assertIsNone(plan["pid"])
        self.assertFalse(plan["dry_run"])
        self.assertEqual(plan["settings_revision"],
                         purchase_settings.revision(purchase_settings.load()))
        ids = [row["item_id"] for row in plan["items"]]
        self.assertTrue(all(len(item_id) == 8 for item_id in ids))
        self.assertEqual(len(set(ids)), 2)
        data = json.loads(self.plan_path().read_text(encoding="utf-8"))
        self.assertEqual(data["items"][0]["code"], "AAAA")
        self.assertEqual(self.plan_path().stat().st_mode & 0o777, 0o600)

    def test_save_refuses_while_plan_running(self):
        self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "alive", return_value=True):
            with self.assertRaises(nw.Abort) as ctx:
                self.save([self.item(at=self.at(120))])
        self.assertIn("运行", str(ctx.exception))

    def test_empty_plan_is_saved_for_problems(self):
        self.assertEqual(self.save([])["items"], [])


class ScheduleTest(PlanTestBase):
    def test_computes_prep_and_end(self):
        settings = purchase_settings.load()
        now = datetime(2026, 11, 6, 8, 0, 0)
        first_at = datetime(2026, 11, 6, 9, 0, 0)
        second_at = datetime(2026, 11, 6, 11, 0, 0)
        plan = self.save([self.item(code="AAAA", at=first_at),
                          self.item(code="BBBB", at=second_at, mode="redemption")])
        result = watch_plan.schedule(plan, settings, now)
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["warnings"], [])
        first, second = result["items"]
        self.assertEqual(first["prep_at"], "2026-11-06T08:53:00")
        gate_end = query_gate.schedule(first_at, "first_launch", settings)[1]
        self.assertEqual(first["end_at"], iso(gate_end + timedelta(minutes=2)))
        self.assertEqual(second["prep_at"], "2026-11-06T10:53:00")
        self.assertEqual(second["end_at"], "2026-11-06T11:02:00")
        # prep_at/end_at 只在展示时计算，不落盘。
        self.assertNotIn("prep_at", watch_plan.load_plan()["items"][0])
        self.assertNotIn("end_at", watch_plan.load_plan()["items"][0])

    def test_problems(self):
        settings = purchase_settings.load()
        now = datetime(2026, 11, 6, 8, 0, 0)
        self.assertEqual(
            watch_plan.schedule(self.save([]), settings, now)["problems"],
            ["计划里还没有布防。"])
        past = self.save([self.item(code="AAAA", at=now - timedelta(minutes=5))])
        self.assertIn("第 1 项购买时间已过（07:55）。",
                      watch_plan.schedule(past, settings, now)["problems"])
        far = self.save([self.item(code="AAAA", at=now + timedelta(hours=25))])
        self.assertIn("第 1 项购买时间超过 24 小时。",
                      watch_plan.schedule(far, settings, now)["problems"])
        normal = self.save([self.item(code="AAAA", at=now + timedelta(minutes=60)),
                            self.item(code="BBBB", at=now + timedelta(minutes=180))])
        self.assertEqual(watch_plan.schedule(normal, settings, now)["problems"], [])

    def test_adjacent_conflict_reports_minimum_gap(self):
        settings = purchase_settings.load()
        now = datetime(2026, 11, 6, 8, 0, 0)
        plan = self.save([
            self.item(code="AAAA", at=datetime(2026, 11, 6, 9, 0, 0)),
            self.item(code="BBBB", at=datetime(2026, 11, 6, 9, 10, 0)),
        ])
        problems = watch_plan.schedule(plan, settings, now)["problems"]
        text = " ".join(problems)
        self.assertIn("第 2 项与第 1 项间隔太近", text)
        self.assertIn("至少 13 分钟", text)   # 首发占用 3.5 分钟 + 冷启动 7 + 间隔 2
        # 带秒，避免两者落在同一分钟时看起来自相矛盾。
        self.assertIn("09:03:00 开始冷启动", text)
        self.assertIn("09:03:30 才结束", text)

    def test_imminent_first_item_warns(self):
        settings = purchase_settings.load()
        at = datetime(2026, 11, 6, 9, 0, 0)
        plan = self.save([self.item(at=at)])
        self.assertEqual(
            watch_plan.schedule(plan, settings, at - timedelta(minutes=10))["warnings"], [])
        self.assertEqual(
            watch_plan.schedule(plan, settings, at - timedelta(minutes=8))["warnings"],
            ["第一项已进入冷启动时间，开始后将立即冷启动。"])
        # 购买时间已过时不再给“立即冷启动”警告。
        self.assertEqual(
            watch_plan.schedule(plan, settings, at + timedelta(minutes=1))["warnings"], [])


class ViewTest(PlanTestBase):
    def test_empty_view(self):
        data = watch_plan.view()
        self.assertIsNone(data["plan"])
        self.assertFalse(data["running"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["warnings"], [])
        self.assertIsNone(data["task"])
        self.assertEqual(data["log_path"], str(self.state / "plan.log"))
        self.assertEqual(data["logs"], [])
        self.assertEqual(data["settings_revision"],
                         purchase_settings.revision(purchase_settings.load()))
        datetime.fromisoformat(data["now"])

    def test_view_enriches_items_without_persisting(self):
        self.save([self.item(at=self.now + timedelta(minutes=90))])
        data = watch_plan.view()
        row = data["plan"]["items"][0]
        self.assertIn("prep_at", row)
        self.assertIn("end_at", row)
        self.assertEqual(row["state"], "pending")
        self.assertNotIn("prep_at", watch_plan.load_plan()["items"][0])

    def test_running_and_stale(self):
        plan = self.save([self.item(at=self.now + timedelta(minutes=90))])
        plan.update(phase="running", pid=4242, generation="g")
        watch_plan.save_plan(plan)
        with patch.object(nw, "alive", return_value=True):
            data = watch_plan.view()
        self.assertTrue(data["running"])
        self.assertFalse(data["stale"])
        with patch.object(nw, "alive", return_value=False):
            data = watch_plan.view()
        self.assertFalse(data["running"])
        self.assertTrue(data["stale"])

    def test_logs_tail(self):
        (self.state / "plan.log").write_text(
            "\n".join(f"line {index}" for index in range(20)), encoding="utf-8")
        self.assertEqual(watch_plan.view()["logs"],
                         [f"line {index}" for index in range(5, 20)])


class StartTest(PlanTestBase):
    def test_start_without_plan_aborts(self):
        with self.assertRaises(nw.Abort):
            watch_plan.start()

    def test_real_plan_requires_payment_confirmation(self):
        self.save([self.item(at=self.at())], dry_run=False)
        with patch.object(watch_plan.subprocess, "Popen") as popen:
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.start()
        self.assertIn("真实计划必须明确确认实际付款", str(ctx.exception))
        popen.assert_not_called()

    def test_start_rejects_problems(self):
        self.save([self.item(code="AAAA", at=self.now - timedelta(minutes=5))])
        with patch.object(watch_plan.subprocess, "Popen") as popen:
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.start(confirm_real_payment=True)
        self.assertIn("已过", str(ctx.exception))
        popen.assert_not_called()

    def test_start_rejects_active_watch(self):
        self.save([self.item(at=self.at())])
        with patch.object(nw, "load_task", return_value=task(phase="armed", pid=999)), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(watch_plan.subprocess, "Popen") as popen:
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.start(confirm_real_payment=True)
        self.assertIn("已有值守任务", str(ctx.exception))
        popen.assert_not_called()

    def test_start_spawns_worker_and_records_pid(self):
        plan = self.save([self.item(at=self.at())])
        fake = types.SimpleNamespace(pid=4321)
        with patch.object(watch_plan.subprocess, "Popen", return_value=fake) as popen:
            data = watch_plan.start()
        argv = popen.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/caffeinate")
        self.assertEqual(argv[1:3], ["-ims", sys.executable])
        self.assertEqual(argv[3], "-B")
        self.assertEqual(argv[4], str(Path(watch_plan.__file__).resolve()))
        self.assertEqual(argv[5:7], ["run", "--generation"])
        self.assertTrue(argv[7])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["cwd"], str(watch_plan.ROOT))
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "running")
        self.assertEqual(saved["pid"], 4321)
        self.assertEqual(saved["generation"], argv[7])
        self.assertEqual(saved["settings_revision"],
                         purchase_settings.revision(purchase_settings.load()))
        self.assertIsNotNone(saved["started_at"])
        self.assertEqual(saved["items"][0]["state"], "pending")
        self.assertEqual(data["plan"]["phase"], "running")
        # plan.log 已创建（追加 stdout）。
        self.assertTrue((self.state / "plan.log").exists())
        self.assertEqual(plan["plan_id"], saved["plan_id"])

    def test_start_twice_aborts(self):
        self.save([self.item(at=self.at())])
        fake = types.SimpleNamespace(pid=4321)
        with patch.object(watch_plan.subprocess, "Popen", return_value=fake):
            watch_plan.start()
        with patch.object(nw, "alive", return_value=True):
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.start()
        self.assertIn("正在运行", str(ctx.exception))

    def test_start_after_finished_aborts(self):
        plan = self.save([self.item(at=self.at())])
        plan["phase"] = "done"
        watch_plan.save_plan(plan)
        with self.assertRaises(nw.Abort) as ctx:
            watch_plan.start()
        self.assertIn("已结束", str(ctx.exception))

    def test_real_plan_starts_with_confirmation(self):
        self.save([self.item(at=self.at())], dry_run=False)
        fake = types.SimpleNamespace(pid=4321)
        with patch.object(watch_plan.subprocess, "Popen", return_value=fake):
            data = watch_plan.start(confirm_real_payment=True)
        self.assertEqual(data["plan"]["phase"], "running")
        self.assertEqual(data["plan"]["dry_run"], False)


class DisarmTest(PlanTestBase):
    def test_disarm_without_running_plan_aborts(self):
        with self.assertRaises(nw.Abort) as ctx:
            watch_plan.disarm()
        self.assertIn("没有在运行", str(ctx.exception))
        plan = self.save([self.item(at=self.at())])
        with self.assertRaises(nw.Abort):
            watch_plan.disarm()
        self.assertEqual(watch_plan.load_plan()["phase"], plan["phase"])

    def test_disarm_refuses_while_firing_and_plan_stays_running(self):
        self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "load_task",
                          return_value=task(phase="firing", pid=999)), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw.manage, "command") as command, \
             patch.object(watch_plan.os, "killpg") as kill, \
             patch.object(nw, "disarm_task") as disarm_task:
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.disarm()
        self.assertIn("正在提交", str(ctx.exception))
        command.assert_not_called()
        kill.assert_not_called()
        disarm_task.assert_not_called()
        # firing 检查在写 disarmed 之前：计划仍 running，什么都没写。
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "running")
        self.assertIsNone(saved.get("result"))
        self.assertIsNone(saved.get("ended_at"))

    def test_disarm_writes_phase_then_stops_worker_and_watch(self):
        plan = self.running_plan([self.item(code="AAAA", at=self.at(90)),
                                  self.item(code="BBBB", at=self.at(120))])
        plan["items"][0].update(state="running", task_id="t1")
        watch_plan.save_plan(plan)
        task_data = task(task_id="t1", phase="preparing", pid=999)
        live = {5555, 999}
        phases_at_kill = []
        invocation = (f"{Path(watch_plan.__file__).resolve()} run "
                      f"--generation {plan['generation']}")

        def alive(pid):
            return pid in live

        def killpg(pgid, sig):
            phases_at_kill.append(watch_plan.load_plan()["phase"])
            live.discard(pgid)

        with patch.object(nw, "load_task", return_value=task_data), \
             patch.object(nw, "alive", side_effect=alive), \
             patch.object(nw.manage, "command", return_value=invocation), \
             patch.object(watch_plan.os, "getpgid", return_value=5555), \
             patch.object(watch_plan.os, "killpg", side_effect=killpg), \
             patch.object(nw, "disarm_task") as disarm_task:
            data = watch_plan.disarm()
        self.assertEqual(phases_at_kill, ["disarmed"])   # 先写 phase 再杀进程
        disarm_task.assert_called_once_with()
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "disarmed")
        self.assertEqual([row["state"] for row in saved["items"]],
                         ["skipped", "skipped"])
        self.assertIsNotNone(saved["ended_at"])
        self.assertEqual(data["plan"]["phase"], "disarmed")

    def test_disarm_leaves_task_terminal_and_records_history(self):
        plan = self.running_plan([self.item(at=self.at(90))])
        plan["items"][0].update(state="running", task_id="t1")
        watch_plan.save_plan(plan)
        nw.save_task(task(task_id="t1", phase="waiting", pid=999))
        with patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "stop_watch") as stop, \
             patch.object(nw, "close_bank_app") as close, \
             patch("builtins.print"):
            data = watch_plan.disarm()
        # 走真实 nw.disarm_task()：任务进入终态并写历史，界面不再显示“值守中”。
        self.assertEqual(nw.load_task()["phase"], "disarmed")
        rows = [json.loads(line) for line in
                (self.state / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_id"], "t1")
        self.assertEqual(rows[0]["phase"], "disarmed")
        stop.assert_called_once()
        close.assert_called_once_with()   # waiting 页开着，关闭招行 App
        self.assertEqual(data["plan"]["phase"], "disarmed")
        self.assertEqual(data["task"]["phase"], "disarmed")

    def test_disarm_task_failure_is_reported_not_swallowed(self):
        plan = self.running_plan([self.item(at=self.at(90))])
        plan["items"][0].update(state="running", task_id="t1")
        watch_plan.save_plan(plan)
        nw.save_task(task(task_id="t1", phase="preparing", pid=999))
        with patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "disarm_task",
                          side_effect=nw.Abort("进程身份无法确认，拒绝终止；请人工检查。")):
            data = watch_plan.disarm()
        # 计划已经 disarmed，但残留任务不能静默：result / item / plan.log 都要暴露。
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "disarmed")
        self.assertIn("任务未能取消", saved["result"])
        self.assertIn("身份无法确认", saved["items"][0]["result"])
        self.assertIn("任务未能取消", data["plan"]["result"])
        self.assertEqual(data["task"]["phase"], "preparing")   # 残留任务仍暴露在 view
        log_text = (self.state / "plan.log").read_text(encoding="utf-8")
        self.assertIn("任务未能取消", log_text)

    def test_disarm_unknown_plan_process_still_cancels_watch(self):
        self.running_plan([self.item(at=self.at())])
        task_data = task(task_id="t1", phase="preparing", pid=999)
        with patch.object(nw, "load_task", return_value=task_data), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw.manage, "command", return_value="python3 something-else"), \
             patch.object(watch_plan.os, "killpg") as kill, \
             patch.object(nw, "disarm_task") as disarm_task:
            data = watch_plan.disarm()
        kill.assert_not_called()                  # 计划进程身份不明：不盲杀
        disarm_task.assert_called_once_with()     # 但当前 watch 必须继续取消
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "disarmed")
        self.assertIn("计划进程未能确认停止", saved["result"])
        self.assertIn("身份无法确认", saved["result"])
        self.assertIn("计划进程未能确认停止", data["plan"]["result"])
        log_text = (self.state / "plan.log").read_text(encoding="utf-8")
        self.assertIn("计划进程未能确认停止", log_text)

    def test_disarm_with_dead_worker_skips_kill(self):
        plan = self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "load_task", return_value=None), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw.manage, "command") as command, \
             patch.object(nw, "disarm_task") as disarm_task:
            data = watch_plan.disarm()
        command.assert_not_called()
        disarm_task.assert_not_called()
        self.assertEqual(data["plan"]["phase"], "disarmed")
        self.assertEqual(plan["items"][0]["state"], "pending")


class ClearTest(PlanTestBase):
    def test_clear_idle_plan(self):
        self.save([self.item(at=self.at())])
        data = watch_plan.clear()
        self.assertIsNone(data["plan"])
        self.assertFalse(self.plan_path().exists())

    def test_clear_without_plan_is_idempotent(self):
        self.assertIsNone(watch_plan.clear()["plan"])

    def test_clear_running_plan_aborts(self):
        self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "alive", return_value=True):
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.clear()
        self.assertIn("正在运行", str(ctx.exception))
        self.assertTrue(self.plan_path().exists())

    def test_clear_stale_plan_allowed(self):
        self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "alive", return_value=False):
            data = watch_plan.clear()
        self.assertIsNone(data["plan"])


    def test_clear_refuses_active_watch(self):
        self.save([self.item(at=self.at())])
        nw.save_task(task(task_id="t1", phase="preparing", pid=999))
        with patch.object(nw, "alive", return_value=False):
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.clear()
        self.assertIn("当前仍有值守任务", str(ctx.exception))
        self.assertTrue(self.plan_path().exists())

    def test_clear_stale_plan_refuses_active_watch(self):
        # 计划进程已死（stale）但 watch 还活着：不能删 plan.json 丢掉计划上下文。
        self.running_plan([self.item(at=self.at())])
        nw.save_task(task(task_id="t1", phase="waiting", pid=999))
        with patch.object(nw, "alive", return_value=False):
            with self.assertRaises(nw.Abort) as ctx:
                watch_plan.clear()
        self.assertIn("当前仍有值守任务", str(ctx.exception))
        self.assertTrue(self.plan_path().exists())


class RunnerTest(PlanTestBase):
    def prepare(self, items, dry_run=True, generation="gen-run", settings_revision=None):
        return self.running_plan(items, dry_run=dry_run, generation=generation,
                                 settings_revision=settings_revision)

    def two_items(self):
        return [self.item(code="AAAA", at=self.at(60)),
                self.item(code="BBBB", at=self.at(120))]

    def test_runs_items_in_order_then_done(self):
        plan = self.prepare(self.two_items())
        arms = [task("t1", "armed"), task("t2", "armed")]
        polls = [task("t1", "done", "提交成功"), task("t2", "done", "提交成功")]
        with patch.object(nw, "arm_task", side_effect=arms) as arm, \
             patch.object(nw, "load_task", side_effect=polls), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert") as alert:
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "done")
        self.assertEqual([row["state"] for row in saved["items"]], ["done", "done"])
        self.assertEqual([row["result"] for row in saved["items"]],
                         ["提交成功", "提交成功"])
        self.assertEqual(arm.call_count, 2)
        first = arm.call_args_list[0]
        self.assertEqual(first.args, ("AAAA", "1000.00"))
        self.assertEqual(first.kwargs["at"], saved["items"][0]["at"])
        self.assertTrue(first.kwargs["dry_run"])
        self.assertEqual(first.kwargs["prep_minutes"], 7)
        self.assertEqual(first.kwargs["mode"], "first_launch")
        self.assertEqual(first.kwargs["plan_id"], plan["plan_id"])
        self.assertEqual(first.kwargs["plan_item"], plan["items"][0]["item_id"])
        self.assertEqual(first.kwargs["settings_revision"], plan["settings_revision"])
        self.assertEqual(saved["items"][0]["task_id"], "t1")
        self.assertIsNotNone(saved["items"][0]["armed_at"])
        self.assertIsNotNone(saved["items"][0]["ended_at"])
        self.assertIsNotNone(saved["ended_at"])
        self.assertIn("完成 2 项", saved["result"])
        alerts = " ".join(str(call) for call in alert.call_args_list)
        self.assertIn("计划已开始", alerts)
        self.assertIn("计划已结束", alerts)

    def test_failed_item_does_not_stop_the_plan(self):
        self.prepare(self.two_items())
        arms = [task("t1", "armed"), task("t2", "armed")]
        polls = [task("t1", "aborted", "准备阶段一直没有成功"),
                 task("t2", "done", "提交成功")]
        with patch.object(nw, "arm_task", side_effect=arms), \
             patch.object(nw, "load_task", side_effect=polls), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "done")
        self.assertEqual([row["state"] for row in saved["items"]],
                         ["failed", "done"])
        self.assertEqual(saved["items"][0]["result"], "准备阶段一直没有成功")
        self.assertIn("失败 1 项", saved["result"])

    def test_arming_exception_marks_item_failed_and_continues(self):
        self.prepare(self.two_items())
        with patch.object(nw, "arm_task",
                          side_effect=[nw.Abort("模拟器没有在运行"), task("t2", "armed")]), \
             patch.object(nw, "load_task",
                          return_value=task("t2", "done", "提交成功")), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "done")
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertIn("模拟器没有在运行", saved["items"][0]["result"])
        self.assertEqual(saved["items"][1]["state"], "done")

    def test_user_cancelled_item_aborts_whole_plan(self):
        self.prepare(self.two_items())
        with patch.object(nw, "arm_task", side_effect=[task("t1", "armed")]) as arm, \
             patch.object(nw, "load_task",
                          return_value=task("t1", "disarmed", "已取消值守")), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(arm.call_count, 1)
        self.assertEqual(saved["phase"], "aborted")
        self.assertIn("第 1 项布防被取消，计划已停止", saved["result"])
        self.assertEqual(saved["items"][0]["state"], "skipped")
        self.assertEqual(saved["items"][1]["state"], "pending")

    def test_past_item_is_skipped(self):
        self.prepare([self.item(code="AAAA", at=self.now - timedelta(minutes=5)),
                      self.item(code="BBBB", at=self.at(60))])
        with patch.object(nw, "arm_task", side_effect=[task("t2", "armed")]) as arm, \
             patch.object(nw, "load_task",
                          return_value=task("t2", "done", "提交成功")), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(arm.call_count, 1)
        self.assertEqual(arm.call_args.args[0], "BBBB")
        self.assertEqual(saved["items"][0]["state"], "skipped")
        self.assertEqual(saved["items"][0]["result"], "购买时间已过")
        self.assertEqual(saved["items"][1]["state"], "done")
        self.assertEqual(saved["phase"], "done")

    def test_settings_change_aborts_plan(self):
        self.prepare(self.two_items(), settings_revision="stale-revision")
        with patch.object(nw, "arm_task") as arm, \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertIn("值守配置在计划期间被修改", saved["result"])
        arm.assert_not_called()

    def test_prep_downgrades_to_immediate_when_late(self):
        self.prepare([self.item(code="AAAA", at=self.at(5)),
                      self.item(code="BBBB", at=self.at(60))])
        arms = [task("t1", "armed"), task("t2", "armed")]
        polls = [task("t1", "done", "提交成功"), task("t2", "done", "提交成功")]
        with patch.object(nw, "arm_task", side_effect=arms) as arm, \
             patch.object(nw, "load_task", side_effect=polls), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(nw, "alert"), \
             patch.object(watch_plan, "log") as log:
            watch_plan.run("gen-run")
        self.assertEqual([call.kwargs["prep_minutes"] for call in arm.call_args_list],
                         [0, purchase_settings.DEFAULTS["cold_start_minutes"]])
        self.assertTrue(any("立即冷启动" in str(call) for call in log.call_args_list))

    def test_vanished_worker_fails_after_grace(self):
        self.prepare([self.item(at=self.at(60))])
        with patch.object(nw, "arm_task", return_value=task("t1", "armed")), \
             patch.object(nw, "load_task", return_value=task("t1", "armed")), \
             patch.object(nw, "alive", return_value=False), \
             patch.object(watch_plan, "GRACE_SECONDS", -1), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertIn("值守进程已退出", saved["items"][0]["result"])
        self.assertEqual(saved["phase"], "done")

    def test_item_timeout_disarms_watch_and_continues(self):
        self.prepare(self.two_items())
        armed = task("t1", "armed")
        with patch.object(nw, "arm_task",
                          side_effect=[armed, task("t2", "armed")]), \
             patch.object(nw, "load_task", return_value=armed), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw, "disarm_task") as disarm_task, \
             patch.object(watch_plan, "END_TIMEOUT", timedelta(hours=-4)), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        # 超时杀 watch 必须走 disarm_task（task_lock 内复查 firing + 写终态/历史）。
        disarm_task.assert_called_once_with()
        self.assertEqual([row["state"] for row in saved["items"]],
                         ["failed", "failed"])
        self.assertIn("超过预计结束时间", saved["items"][0]["result"])
        self.assertEqual(saved["phase"], "done")

    def test_item_timeout_disarm_failure_aborts_plan_unknown(self):
        self.prepare([self.item(at=self.at(60))])
        armed = task("t1", "armed")
        with patch.object(nw, "arm_task", return_value=armed), \
             patch.object(nw, "load_task", return_value=armed), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw, "disarm_task",
                          side_effect=nw.Abort("正在提交，不能取消；请等结果并查交易记录。")), \
             patch.object(watch_plan, "END_TIMEOUT", timedelta(hours=-4)), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        # 无法终止（含 firing 竞态）时升级为整份中止，不能继续下一项。
        self.assertEqual(saved["phase"], "aborted")
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertIn("结果未知，请查交易记录，不要重复提交", saved["result"])
        self.assertIn("正在提交，不能取消", saved["result"])

    def test_firing_timeout_aborts_without_killing(self):
        self.prepare([self.item(at=self.at(60))])
        with patch.object(nw, "arm_task", return_value=task("t1", "armed")), \
             patch.object(nw, "load_task", return_value=task("t1", "firing")), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw, "stop_watch") as stop, \
             patch.object(watch_plan, "END_TIMEOUT", timedelta(minutes=-120)), \
             patch.object(nw, "alert"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertIn("结果未知", saved["result"])
        stop.assert_not_called()

    def test_worker_arms_through_real_arm_task(self):
        # 回归测试：计划进程自己调 arm_task 时，计划互斥必须放行本计划，
        # 且 plan_id/plan_item 必须写进任务；这里不 mock nw.arm_task。
        plan = self.prepare([self.item(at=self.at(60))])
        real_arm = nw.arm_task

        def fake_arm(*args, **kwargs):
            armed = real_arm(*args, **kwargs)
            armed.update(phase="done", result="提交成功")
            nw.save_task(armed)
            return armed

        with self.arm_world(), \
             patch.object(nw, "arm_task", side_effect=fake_arm), \
             patch.object(nw, "alive", side_effect=lambda pid: pid == plan["pid"]):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        task_saved = nw.load_task()
        self.assertEqual(saved["phase"], "done")
        self.assertEqual(saved["items"][0]["state"], "done")
        self.assertEqual(saved["items"][0]["result"], "提交成功")
        self.assertEqual(task_saved["plan_id"], plan["plan_id"])
        self.assertEqual(task_saved["plan_item"], plan["items"][0]["item_id"])

    def test_wrong_generation_exits_without_touching_plan(self):
        plan = self.prepare(self.two_items())
        with patch.object(nw, "arm_task") as arm:
            watch_plan.run("other-generation")
        arm.assert_not_called()
        self.assertEqual(watch_plan.load_plan()["phase"], "running")
        self.assertEqual(watch_plan.load_plan()["generation"], plan["generation"])

    def test_uncaught_error_aborts_plan_and_fails_running_item(self):
        plan = self.prepare(self.two_items())
        plan["items"][0].update(state="running", armed_at=iso(self.now), task_id="t1")
        watch_plan.save_plan(plan)
        with patch.object(nw, "alert"), \
             patch.object(purchase_settings, "load", side_effect=RuntimeError("设置文件坏了")):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertIn("设置文件坏了", saved["result"])
        # 异常兜底不能把界面留在「计划已中止 + 某项执行中」。
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertEqual(saved["items"][1]["state"], "pending")

    def test_abort_cancels_live_watch(self):
        # P1：计划因未捕获异常中止时，不能留下一个还会到点提交的 watch。
        self.prepare([self.item(at=self.at(60))])
        armed = task("t1", "armed")
        with patch.object(nw, "arm_task", return_value=armed), \
             patch.object(nw, "load_task",
                          side_effect=[armed, RuntimeError("task.json 坏了"), armed, armed]), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw, "stop_watch") as stop, \
             patch.object(nw, "close_bank_app"), \
             patch.object(nw, "record_history") as record, \
             patch.object(nw, "alert"), \
             patch("builtins.print"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertEqual(saved["items"][0]["state"], "failed")
        self.assertIn("task.json 坏了", saved["result"])
        # 走真实 nw.disarm_task()：watch 被取消到终态并写历史。
        stop.assert_called_once()
        record.assert_called_once()
        self.assertEqual(nw.load_task()["phase"], "disarmed")

    def test_abort_marks_firing_watch_unknown_without_killing(self):
        self.prepare([self.item(at=self.at(60))])
        armed = task("t1", "armed")
        firing = task("t1", "firing")
        with patch.object(nw, "arm_task", return_value=armed), \
             patch.object(nw, "load_task",
                          side_effect=[armed, RuntimeError("读任务失败"), firing]), \
             patch.object(nw, "alive", return_value=True), \
             patch.object(nw, "disarm_task") as disarm_task, \
             patch.object(nw, "alert"), \
             patch("builtins.print"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertEqual(saved["items"][0]["state"], "failed")
        disarm_task.assert_not_called()   # 提交中绝不杀
        self.assertIn("提交阶段异常，结果未知", saved["result"])
        self.assertIn("请查交易记录，不要重复提交", saved["result"])

    def test_abort_with_unreadable_task_reports_unknown(self):
        self.prepare([self.item(at=self.at(60))])
        with patch.object(nw, "arm_task", return_value=task("t1", "armed")), \
             patch.object(nw, "load_task", side_effect=RuntimeError("task.json 坏了")), \
             patch.object(nw, "alert"), \
             patch("builtins.print"):
            watch_plan.run("gen-run")
        saved = watch_plan.load_plan()
        self.assertEqual(saved["phase"], "aborted")
        self.assertIn("无法读取当前值守任务", saved["result"])
        self.assertIn("结果未知", saved["result"])

    def test_disarmed_plan_worker_exits_quietly(self):
        plan = self.prepare(self.two_items())
        plan["phase"] = "disarmed"
        watch_plan.save_plan(plan)
        with patch.object(nw, "arm_task") as arm:
            watch_plan.run("gen-run")
        arm.assert_not_called()


class ArmPlanFieldsTest(PlanTestBase):
    def test_arm_task_records_plan_fields_and_history(self):
        when = self.now + timedelta(minutes=60)
        with self.arm_world():
            armed = nw.arm_task("JX040229", "1000", at=iso(when), dry_run=True,
                                plan_id="plan-1", plan_item="item-1")
        self.assertEqual(armed["plan_id"], "plan-1")
        self.assertEqual(armed["plan_item"], "item-1")
        nw.record_history(armed)
        record = json.loads((self.state / "history.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(record["plan_id"], "plan-1")
        self.assertEqual(record["plan_item"], "item-1")

    def test_manual_arm_refused_while_plan_running(self):
        self.running_plan([self.item(at=self.at())])
        with patch.object(nw, "alive", return_value=True):
            with self.assertRaises(nw.Abort) as ctx:
                nw.arm_task("TEST01", "0.01", at=self.at(120), dry_run=True)
        self.assertIn("计划正在运行", str(ctx.exception))

    def test_plan_worker_arm_passes_mutual_exclusion(self):
        # 计划进程自己也是走 nw.arm_task()，带对 plan_id/plan_item 时必须放行。
        plan = self.running_plan([self.item(at=self.at())])
        with self.arm_world(), patch.object(nw, "alive", return_value=True):
            armed = nw.arm_task("TEST01", "0.01", at=self.at(120), dry_run=True,
                                plan_id=plan["plan_id"], plan_item="item-1")
            self.assertEqual(armed["plan_id"], plan["plan_id"])
            self.assertEqual(armed["plan_item"], "item-1")
            with self.assertRaises(nw.Abort) as ctx:
                nw.arm_task("TEST01", "0.01", at=self.at(150), dry_run=True)
            self.assertIn("计划正在运行", str(ctx.exception))
            with self.assertRaises(nw.Abort):
                nw.arm_task("TEST01", "0.01", at=self.at(150), dry_run=True,
                            plan_id="wrong-plan", plan_item="item-2")


if __name__ == "__main__":
    unittest.main()
