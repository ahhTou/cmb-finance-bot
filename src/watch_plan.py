#!/usr/bin/env python3
"""计划模式：把多个布防按购买时间排成一份计划，由后台进程串行执行。

用户只填购买时间；每项的冷启动时间按现有 `cold_start_minutes` 自动倒推，
预计占用结束时间由查询窗口和提交余量算出。计划进程逐项调用
`night_watch.arm_task()`，一项结束（成功或失败）再进入下一项；用户手动取消
当前布防则整份计划停止。只有一个模拟器，所以永远串行，不并发。

存储（都在 `night_watch.STATE` 下，调用时推导，便于测试替换）：
- `plan.json`：计划输入 + 运行状态（0600、原子写）
- `plan.lock`：`flock` 串行化 plan.json 的读改写
- `plan.log`：计划进程 stdout

计划进程由 `plan-start` 用 `caffeinate -ims` 后台启动：

    python3 -B src/watch_plan.py run --generation <generation>

绝不在计划进程里做任何额外交易动作：每项仍走 `night_watch` 原有的单次提交
流程，计划只负责排程和串行。
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fast_buy
import night_watch as nw
import plan_settings
import purchase_settings
import query_gate

MAX_ITEMS = 20                        # 一份计划最多几项（先例：favorites.MAX_ITEMS）
MAX_LEAD = timedelta(hours=24)        # 与 night_watch.MAX_LEAD 一致
LOG_LINES = 15                        # view 返回的 plan.log 行数
CODE = re.compile(r"[A-Za-z0-9]{4,20}")
ACTIVE_PHASES = ("armed", "preparing", "waiting", "firing")


# ---------------------------------------------------------------- 存储与锁

def plan_path():
    return nw.STATE / "plan.json"


def lock_path():
    return nw.STATE / "plan.lock"


def log_path():
    return nw.STATE / "plan.log"


def log(message):
    print(f"{datetime.now():%m-%d %H:%M:%S} {message}", flush=True)


def _now():
    return datetime.now().replace(microsecond=0)


def _now_iso():
    return _now().isoformat()


def _iso(when):
    return when.replace(microsecond=0).isoformat()


@contextmanager
def plan_lock(blocking=True):
    """Serialize read-modify-write of plan.json (same pattern as task_lock)."""
    nw.STATE.mkdir(parents=True, exist_ok=True)
    with lock_path().open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise nw.Abort("另一个计划操作正在进行，请稍后再试。")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_plan():
    path = plan_path()
    if not path.exists():
        return None
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise nw.Abort("计划文件格式无效。")
    if not isinstance(plan, dict):
        raise nw.Abort("计划文件格式无效。")
    return plan


def save_plan(plan):
    path = plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _settings_revision():
    return purchase_settings.revision(purchase_settings.load())


def _runtime(plan=None):
    """The plan worker's scheduler values: snapshot if present, live otherwise."""
    raw = (plan or {}).get("runtime_settings")
    return plan_settings.snapshot(raw) if raw else plan_settings.load()


def plan_content_revision(plan):
    """Digest only confirmed input; runtime state and computed times are excluded."""
    content = {"dry_run": plan.get("dry_run", False), "items": [
        {key: item.get(key) for key in ("code", "amount", "at", "mode")}
        for item in plan.get("items", [])]}
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------- 校验与调度

def _parse_time(value):
    if not isinstance(value, str) or "T" not in value:
        raise nw.Abort("购买时间格式应为 YYYY-MM-DDTHH:MM:SS。")
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise nw.Abort("购买时间格式应为 YYYY-MM-DDTHH:MM:SS。")
    if when.tzinfo is not None:
        raise nw.Abort("请使用本机本地时间，不要带时区。")
    return when.replace(microsecond=0)


def _parse_amount(value):
    try:
        return fast_buy.parse_amount(value)
    except fast_buy.Stop as exc:
        raise nw.Abort(str(exc))
    except (TypeError, ValueError):
        raise nw.Abort("金额格式不正确。")


def _item_from_input(row):
    if not isinstance(row, dict):
        raise nw.Abort("计划项格式无效。")
    code = row.get("code")
    if not isinstance(code, str) or not CODE.fullmatch(code):
        raise nw.Abort("产品代码须为 4–20 位字母或数字。")
    amount = _parse_amount(row.get("amount"))
    at = _parse_time(row.get("at"))
    mode = row.get("mode", "first_launch")
    if mode not in nw.MODES:
        raise nw.Abort("模式只能是 first_launch 或 redemption。")
    return {"item_id": uuid.uuid4().hex[:8], "code": code, "amount": amount,
            "at": _iso(at), "mode": mode, "state": "pending", "task_id": None,
            "result": None, "armed_at": None, "ended_at": None}


def _plan_at(item):
    try:
        return _parse_time(item["at"])
    except (KeyError, TypeError):
        raise nw.Abort("计划里的购买时间格式无效。")


def _plan_end_at(at, mode, settings, runtime):
    """预计占用结束时间：首发看查询窗口 + 提交余量，不定时看抢购窗口。"""
    if mode == "redemption":
        return at + timedelta(minutes=settings["irregular_window_minutes"])
    _, gate_end = query_gate.schedule(at, "first_launch", settings)
    return max(at, gate_end) + timedelta(minutes=runtime["first_end_slack_minutes"])


def schedule(plan, settings, now, runtime=None):
    """实时计算每项的 prep_at/end_at，并给出阻塞问题和警告。

    prep_at/end_at 只在展示时计算，不写进 plan.json。
    """
    settings = purchase_settings.validate(settings)
    runtime = runtime or plan_settings.load()
    arm_gap = timedelta(minutes=runtime["arm_gap_minutes"])
    prep = timedelta(minutes=settings["cold_start_minutes"])
    items = plan.get("items") if isinstance(plan, dict) else None
    items = items if isinstance(items, list) else []
    enriched, problems, warnings = [], [], []
    for item in items:
        at = _plan_at(item)
        prep_at = at - prep
        end_at = _plan_end_at(at, item.get("mode"), settings, runtime)
        enriched.append(dict(item, prep_at=_iso(prep_at), end_at=_iso(end_at)))
    if not items:
        problems.append("计划里还没有布防。")
    for index, item in enumerate(items, 1):
        at = _plan_at(item)
        if at <= now:
            problems.append(f"第 {index} 项购买时间已过（{at:%H:%M}）。")
        elif at > now + MAX_LEAD:
            problems.append(f"第 {index} 项购买时间超过 24 小时。")
    for index in range(1, len(items)):
        prev_at = _plan_at(items[index - 1])
        prev_end = datetime.fromisoformat(enriched[index - 1]["end_at"])
        cur_prep = datetime.fromisoformat(enriched[index]["prep_at"])
        if cur_prep >= prev_end + arm_gap:
            continue
        # 让 cur_prep 至少比 prev_end 晚 arm_gap 所需的购买时间差。
        need = prev_end - prev_at + prep + arm_gap
        minutes = math.ceil(need.total_seconds() / 60)
        problems.append(
            f"第 {index + 1} 项与第 {index} 项间隔太近：第 {index + 1} 项需在 "
            f"{cur_prep:%H:%M:%S} 开始冷启动，但第 {index} 项预计 {prev_end:%H:%M:%S} 才结束；"
            f"请把购买时间拉开到至少 {minutes} 分钟。")
    if enriched:
        prep_at = datetime.fromisoformat(enriched[0]["prep_at"])
        if now > prep_at - arm_gap and _plan_at(items[0]) > now:
            warnings.append("第一项已进入冷启动时间，开始后将立即冷启动。")
    return {"items": enriched, "problems": problems, "warnings": warnings}


def view():
    """后端响应：计划 + 运行/过期状态 + problems/warnings + 任务与日志。"""
    settings = purchase_settings.load()
    revision = purchase_settings.revision(settings)
    now = _now()
    plan = load_plan()
    runtime = _runtime(plan)
    problems, warnings = [], []
    running = stale = False
    if plan is not None:
        computed = schedule(plan, settings, now, runtime)
        plan = dict(plan, items=computed["items"], content_revision=plan_content_revision(plan))
        problems, warnings = computed["problems"], computed["warnings"]
        running = plan.get("phase") == "running" and nw.alive(plan.get("pid"))
        stale = plan.get("phase") == "running" and not running
    path = log_path()
    logs = (path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_LINES:]
            if path.exists() else [])
    return {"plan": plan, "running": bool(running), "stale": bool(stale),
            "problems": problems, "warnings": warnings, "task": nw.load_task(),
            "log_path": str(path), "logs": logs, "settings_revision": revision,
            "now": now.isoformat()}


def running():
    """True while a plan worker is alive; used by night_watch._arm() mutual exclusion."""
    plan = load_plan()
    return bool(plan and plan.get("phase") == "running" and nw.alive(plan.get("pid")))


def accepts(plan_id):
    """True when `plan_id` is the plan that is running right now.

    The plan worker itself arms through `night_watch.arm_task()`, so the mutual
    exclusion in `_arm()` must let the worker of the *current* plan through
    while still refusing unrelated manual arming.
    """
    if not plan_id:
        return False
    plan = load_plan()
    return bool(plan and plan.get("phase") == "running"
                and nw.alive(plan.get("pid")) and plan.get("plan_id") == plan_id)


def _active_task(task):
    return bool(task and (task.get("phase") in ACTIVE_PHASES or nw.alive(task.get("pid"))))


# ---------------------------------------------------------------- 保存 / 开始 / 取消

def save(raw):
    """plan-save：校验输入并重新生成一份 idle 计划（清空运行状态）。"""
    if not isinstance(raw, dict):
        raise nw.Abort("计划格式无效。")
    dry_run = raw.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise nw.Abort("演练开关必须是 true 或 false。")
    rows = raw.get("items")
    if not isinstance(rows, list):
        raise nw.Abort("计划项格式无效。")
    if len(rows) > MAX_ITEMS:
        raise nw.Abort(f"计划最多 {MAX_ITEMS} 项。")
    items = [_item_from_input(row) for row in rows]
    items.sort(key=lambda item: item["at"])
    plan = {"version": 1, "plan_id": uuid.uuid4().hex, "generation": None,
            "created_at": _now_iso(), "started_at": None, "ended_at": None,
            "dry_run": dry_run, "phase": "idle", "pid": None, "last_tick": None,
            "settings_revision": _settings_revision(), "result": None, "items": items}
    with plan_lock(False):
        current = load_plan()
        if current and current.get("phase") == "running" and nw.alive(current.get("pid")):
            raise nw.Abort("计划正在运行，不能修改；先取消计划。")
        save_plan(plan)
    return plan


def _spawn(generation):
    """Start the detached worker, mirroring night_watch.spawn_watch()."""
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as out:
        return subprocess.Popen(["/usr/bin/caffeinate", "-ims", sys.executable, "-B",
                                 str(Path(__file__).resolve()), "run",
                                 "--generation", generation],
                                stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                                cwd=str(ROOT), start_new_session=True)


def start(confirm_real_payment=False, plan_id=None, content_revision=None,
          settings_revision=None):
    """plan-start：严格校验后启动计划进程，pid 写进 plan.json。"""
    with plan_lock(False):
        plan = load_plan()
        if plan is None:
            raise nw.Abort("还没有计划；先保存计划。")
        phase = plan.get("phase")
        if phase == "running":
            raise nw.Abort("计划正在运行；先取消计划再开始。" if nw.alive(plan.get("pid"))
                           else "计划进程已退出；先取消计划再重新开始。")
        if phase != "idle":
            raise nw.Abort("计划已结束；请清空后重新保存再开始。")
        settings = purchase_settings.load()
        runtime = plan_settings.load()
        problems = schedule(plan, settings, _now(), runtime)["problems"]
        if problems:
            raise nw.Abort(problems[0])
        if not plan.get("dry_run") and not confirm_real_payment:
            raise nw.Abort("真实计划必须明确确认实际付款。")
        with nw.task_lock(False):
            # Settings writes use task_lock too: compare and commit under that
            # lock, so no new configuration can slip between confirmation/start.
            settings = purchase_settings.load()
            if (not plan_id or not content_revision or not settings_revision
                    or plan_id != plan.get("plan_id")
                    or content_revision != plan_content_revision(plan)
                    or settings_revision != purchase_settings.revision(settings)):
                raise nw.Abort("计划内容或值守配置已变化，或缺少确认版本；请重新读取计划并核对后开始。")
            problems = schedule(plan, settings, _now(), runtime)["problems"]
            if problems:
                raise nw.Abort(problems[0])
            task = nw.load_task()
            if _active_task(task):
                raise nw.Abort("已有值守任务在运行；先取消防守再开始计划。")
            generation = uuid.uuid4().hex
            now = _now_iso()
            plan.update(phase="running", generation=generation, started_at=now,
                        ended_at=None, pid=None, last_tick=now, result=None,
                        settings_revision=purchase_settings.revision(settings),
                        runtime_settings=runtime)
            for item in plan.get("items", []):
                item.update(state="pending", task_id=None, result=None,
                            armed_at=None, ended_at=None)
            save_plan(plan)
            try:
                proc = _spawn(generation)
            except (OSError, ValueError) as exc:
                plan.update(phase="aborted", ended_at=_now_iso(),
                            result=f"计划进程启动失败：{exc}")
                save_plan(plan)
                raise nw.Abort(f"计划进程启动失败：{exc}")
            plan["pid"] = proc.pid
            save_plan(plan)
    return view()


def _stop_plan_process(plan):
    """Stop the plan worker only after proving its identity (same as stop_watch)."""
    pid = plan.get("pid")
    if not nw.alive(pid):
        return
    cmd = nw.manage.command(pid)
    invocation = (r"(?:^|\s)" + re.escape(str(Path(__file__).resolve()))
                  + r"\s+run\s+--generation\s+" + re.escape(str(plan.get("generation")))
                  + r"\s*$")
    if not re.search(invocation, cmd):
        raise nw.Abort("进程身份无法确认，拒绝终止；请人工检查。")
    try:
        if os.getpgid(pid) != pid:
            raise nw.Abort("进程身份无法确认，拒绝终止；请人工检查。")
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # Worker exited between the liveness check and termination.
    end = time.monotonic() + _runtime(plan)["kill_wait_seconds"]
    while nw.alive(pid) and time.monotonic() < end:
        time.sleep(.1)
    if nw.alive(pid):
        os.killpg(pid, signal.SIGKILL)
        end = time.monotonic() + 2
        while nw.alive(pid) and time.monotonic() < end:
            time.sleep(.1)
        if nw.alive(pid):
            raise nw.Abort("计划进程未退出；请人工检查。")


def _note(message):
    """Expose a disarm residue in plan.log.

    `plan-disarm` runs inside admin_cli, whose stdout is redirected; plan.log is
    what the plan page and the next agent actually read, so append there too.
    """
    log(message)
    try:
        with log_path().open("a", encoding="utf-8") as out:
            out.write(f"{datetime.now():%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


def _disarm_current_watch(plan, item_index):
    """Cancel the current watch via night_watch.disarm_task().

    Going through disarm_task (instead of a bare stop_watch) leaves task.json in
    a terminal `disarmed` state and appends a history record, so the task page /
    status / SSE do not keep showing a dead watch as running.
    """
    task = nw.load_task()
    if not task or task.get("phase") not in ACTIVE_PHASES:
        return  # 没有任务或已经是终态：无需处理
    try:
        nw.disarm_task(expected_plan_id=plan.get("plan_id"),
                       expected_task_id=(plan["items"][item_index].get("task_id")
                                         if item_index is not None else None))
    except nw.Abort as exc:
        message = f"任务未能取消：{exc}"
        _note(message)
        with plan_lock():
            current = load_plan()
            if not current or current.get("plan_id") != plan.get("plan_id"):
                return
            current["result"] = f"{current.get('result') or '计划已被手动取消'}；{message}"
            items = current.get("items") or []
            if item_index is not None and item_index < len(items):
                items[item_index]["result"] = (f"{items[item_index].get('result') or ''}；"
                                               f"{message}")
            save_plan(current)


def disarm():
    """plan-disarm：先写 disarmed 再停进程，最后把当前值守取消到终态。"""
    with plan_lock(False):
        plan = load_plan()
        if plan is None or plan.get("phase") != "running":
            raise nw.Abort("计划没有在运行。")
        task = nw.load_task()
        if task and task.get("phase") == "firing":
            raise nw.Abort("当前布防正在提交，不能取消计划；请等结果并查交易记录。")
        now = _now_iso()
        running_index = next((index for index, item in enumerate(plan.get("items") or [])
                              if item.get("state") == "running"), None)
        plan.update(phase="disarmed", ended_at=now, result="计划已被手动取消",
                    last_tick=now)
        for item in plan.get("items", []):
            if item.get("state") in ("pending", "running"):
                item.update(state="skipped", result="计划已被手动取消", ended_at=now)
        save_plan(plan)
    # The plan is already `disarmed`. Even if the plan process cannot be
    # identified, the watch it left behind must still be cancelled; expose the
    # residue instead of skipping the cleanup.
    try:
        _stop_plan_process(plan)
    except (nw.Abort, OSError) as exc:
        message = f"计划进程未能确认停止：{exc}"
        _note(message)
        with plan_lock():
            current = load_plan()
            if current and current.get("plan_id") == plan.get("plan_id"):
                current["result"] = (f"{current.get('result') or '计划已被手动取消'}；"
                                     f"{message}")
                save_plan(current)
    _disarm_current_watch(plan, running_index)
    nw.alert("计划已取消", "计划调度已取消；当前布防的取消结果请查看计划页。",
             event="plan_cancelled")
    return view()


def clear():
    """plan-clear：仅未运行、且没有活跃值守任务时删除 plan.json。"""
    with plan_lock(False):
        plan = load_plan()
        if plan and plan.get("phase") == "running" and nw.alive(plan.get("pid")):
            raise nw.Abort("计划正在运行；先取消计划。")
        if _active_task(nw.load_task()):
            raise nw.Abort("当前仍有值守任务；先取消防守。")
        plan_path().unlink(missing_ok=True)
    return view()


# ---------------------------------------------------------------- 计划进程

def _read_running(plan):
    """Reload the plan if this generation is still the running one."""
    with plan_lock():
        current = load_plan()
        if (not current or current.get("phase") != "running"
                or current.get("generation") != plan.get("generation")
                or current.get("plan_id") != plan.get("plan_id")):
            return None
        return current


def _save_running(plan):
    """Persist the worker's plan only while it is still the running generation."""
    with plan_lock():
        current = load_plan()
        if (not current or current.get("phase") != "running"
                or current.get("generation") != plan.get("generation")
                or current.get("plan_id") != plan.get("plan_id")):
            return False
        save_plan(plan)
        return True


def _first_pending(plan):
    for index, item in enumerate(plan.get("items") or []):
        if item.get("state") == "pending":
            return index
    return None


def _summary(plan):
    items = plan.get("items") or []
    counts = {name: sum(1 for item in items if item.get("state") == name)
              for name in ("done", "failed", "skipped")}
    return (f"完成 {counts['done']} 项，失败 {counts['failed']} 项，"
            f"跳过 {counts['skipped']} 项")


def _finish_item(plan, index, state, result, outcome=None):
    item = plan["items"][index]
    item.update(state=state, result=result, outcome=outcome or ("failed" if state == "failed" else None),
                ended_at=_now_iso())
    plan["last_tick"] = _now_iso()
    return _save_running(plan)


def _abort(plan, message, item_index=None, item_state="skipped", item_result=None):
    if item_index is not None:
        plan["items"][item_index].update(state=item_state, ended_at=_now_iso(),
                                         result=item_result or message)
    plan.update(phase="aborted", ended_at=_now_iso(), result=message,
                last_tick=_now_iso())
    if not _save_running(plan):
        return False
    log(f"计划已中止：{message}")
    nw.alert("计划已中止", message, 5, event='plan_aborted')
    return True


def _abort_running_watch(plan):
    """Cancel the live watch when the plan dies unexpectedly.

    Returns a note for the plan/item result; "" when there is nothing left to
    stop. A submission in flight (`firing`) is never killed: its outcome is
    unknown and must be checked in the bank's transaction history instead.
    """
    try:
        task = nw.load_task()
    except Exception as exc:
        return (f"无法读取当前值守任务（{type(exc).__name__}）：结果未知，"
                f"请查交易记录，不要重复提交")
    if (not task or task.get("plan_id") != plan.get("plan_id")
            or task.get("phase") not in ACTIVE_PHASES):
        return ""
    if task.get("phase") == "firing":
        return "提交阶段异常，结果未知；请查交易记录，不要重复提交"
    try:
        nw.disarm_task(expected_plan_id=plan.get("plan_id"),
                       expected_task_id=task.get("task_id"))
    except Exception as exc:
        return f"当前值守未能取消（{exc}）；结果未知，请查交易记录，不要重复提交"
    return ""


def _safe_abort(plan, message):
    """Exception path: never leave plan.json stuck in running, nor a live watch."""
    if _read_running(plan) is None:
        return
    note = _abort_running_watch(plan)
    result = f"{message}；{note}" if note else message
    with plan_lock():
        current = load_plan()
        if (not current or current.get("phase") != "running"
                or current.get("generation") != plan.get("generation")):
            return
        now = _now_iso()
        for item in current.get("items", []):
            if item.get("state") == "running":
                item.update(state="failed", result=result, ended_at=now)
        current.update(phase="aborted", ended_at=now, result=result,
                       last_tick=now)
        save_plan(current)
    log(f"计划异常中止：{result}")
    nw.alert("计划已中止", result, 5, event='plan_aborted')


def _wait_item(plan, index, end_at, runtime):
    """Wait for the armed item's watch process to reach a terminal phase."""
    task_id = plan["items"][index].get("task_id")
    grace = None
    beat = time.monotonic()
    while True:
        current = _read_running(plan)
        if current is None:
            return None
        plan = current
        if time.monotonic() - beat >= runtime["heartbeat_seconds"]:
            plan["last_tick"] = _now_iso()
            if not _save_running(plan):
                return None
            beat = time.monotonic()
        task = nw.load_task()
        if task_id and task and task.get("task_id") != task_id:
            task = None  # Replaced by another task: treat as a vanished worker.
        terminal = bool(task and task.get("phase") in ("done", "aborted", "disarmed"))
        live = bool(task and nw.alive(task.get("pid")))
        if terminal and not live:
            if task.get("phase") == "disarmed":
                return "disarmed", task.get("result")
            outcome = nw.task_outcome(task)
            result = task.get("result")
            if outcome == "unknown":
                result = f"结果未知：{result or '没有可确认的交易结果'}；请查交易记录，不要重复提交"
            return outcome, result
        if not live:
            grace = grace if grace is not None else time.monotonic() + runtime["grace_seconds"]
            if time.monotonic() >= grace:
                if task is None or task.get("phase") == "firing" or task.get("fired_at"):
                    return "unknown", "值守进程已退出，结果未知；请查交易记录，不要重复提交"
                return "failed", "值守进程已退出（未进入提交）"
        else:
            grace = None
        if datetime.now() > end_at + timedelta(minutes=runtime["end_timeout_minutes"]):
            if task and task.get("phase") == "firing":
                # Never kill a submission in flight: report and stop the plan.
                return "firing-timeout", "提交阶段超时，结果未知；请查交易记录，不要重复提交"
            try:
                if task:
                    # disarm_task re-checks `firing` under task_lock, so this can
                    # not SIGTERM a submission that started in between; it also
                    # leaves task.json terminal and appends a history record.
                    nw.disarm_task(expected_plan_id=plan.get("plan_id"),
                                   expected_task_id=task_id)
            except (nw.Abort, OSError) as exc:
                return ("firing-timeout",
                        f"布防超时且无法终止（{exc}）；结果未知，请查交易记录，不要重复提交")
            return "failed", "布防超过预计结束时间仍未结束，已停止"
        time.sleep(runtime["poll_seconds"])


def run(generation):
    """计划进程入口：串行执行所有 pending 项，直到完成或中止。"""
    with plan_lock():
        plan = load_plan()
        if not plan or plan.get("phase") != "running" or plan.get("generation") != generation:
            log("计划阶段或代次不匹配，计划进程退出。")
            return
    action = "演练" if plan.get("dry_run") else "真实"
    try:
        runtime = _runtime(plan)
        arm_gap = timedelta(minutes=runtime["arm_gap_minutes"])
        nw.alert(f"计划已开始：{len(plan.get('items') or [])} 项（{action}）", event='plan_started')
        log(f"计划开始：{len(plan.get('items') or [])} 项（{action}）")
        while True:
            plan = _read_running(plan)
            if plan is None:
                return
            index = _first_pending(plan)
            if index is None:
                summary = _summary(plan)
                plan.update(phase="done", ended_at=_now_iso(), result=summary,
                            last_tick=_now_iso())
                if not _save_running(plan):
                    return
                log(f"计划结束：{summary}")
                nw.alert(f"计划已结束（{action}）", summary, event='plan_completed')
                return
            item = plan["items"][index]
            at = _plan_at(item)
            now = datetime.now()
            if at <= now:
                if not _finish_item(plan, index, "skipped", "购买时间已过"):
                    return
                log(f"第 {index + 1} 项购买时间已过，跳过。")
                nw.alert(f"计划第 {index + 1} 项跳过", f"{item['code']} 购买时间已过", event='plan_item_skipped')
                continue
            settings = purchase_settings.load()
            if purchase_settings.revision(settings) != plan.get("settings_revision"):
                _abort(plan, "值守配置在计划期间被修改，计划已停止")
                return
            end_at = datetime.fromisoformat(
                schedule(plan, settings, now, runtime)["items"][index]["end_at"])
            prep = settings["cold_start_minutes"]
            if at - now < timedelta(minutes=prep) + arm_gap:
                prep = 0
                log(f"第 {index + 1} 项剩余时间不足，改为立即冷启动。")
            plan["last_tick"] = _now_iso()
            item.update(state="running", armed_at=_now_iso(), ended_at=None,
                        result=None, task_id=None)
            if not _save_running(plan):
                return
            log(f"第 {index + 1} 项开始布防：{item['code']} {item['amount']} 元，"
                f"购买 {at:%H:%M:%S}，冷启动提前 {prep} 分钟。")
            try:
                task = nw.arm_task(item["code"], item["amount"], at=item["at"],
                                   dry_run=bool(plan.get("dry_run")),
                                   prep_minutes=prep, mode=item["mode"],
                                   settings_revision=plan.get("settings_revision"),
                                   plan_id=plan.get("plan_id"),
                                   plan_item=item.get("item_id"))
            except Exception as exc:
                if not _finish_item(plan, index, "failed", str(exc)):
                    return
                log(f"第 {index + 1} 项布防失败：{exc}")
                nw.alert(f"计划第 {index + 1} 项失败", f"{item['code']}：{exc}", 5, event='plan_item_failed')
                continue
            item["task_id"] = task.get("task_id") if isinstance(task, dict) else None
            plan["last_tick"] = _now_iso()
            if not _save_running(plan):
                return
            outcome = _wait_item(plan, index, end_at, runtime)
            if outcome is None:
                return
            state, result = outcome
            if state == "disarmed":
                _abort(plan, f"第 {index + 1} 项布防被取消，计划已停止",
                       item_index=index, item_state="skipped", item_result="用户取消布防")
                return
            if state in ("unknown", "firing-timeout"):
                if not _finish_item(plan, index, "failed", result, outcome="unknown"):
                    return
                _abort(plan, f"第 {index + 1} 项{result}")
                return
            if state in ("success", "dry_run"):
                if not _finish_item(plan, index, "done", result, outcome=state):
                    return
                log(f"第 {index + 1} 项完成：{result or '已提交'}")
                nw.alert(f"计划第 {index + 1} 项完成",
                         f"{item['code']}：{result or '已提交'}",
                         3 if plan.get("dry_run") else 5, event='plan_item_completed')
            else:
                if not _finish_item(plan, index, "failed", result):
                    return
                log(f"第 {index + 1} 项失败：{result or '未知'}")
                nw.alert(f"计划第 {index + 1} 项失败",
                         f"{item['code']}：{result or '未知原因'}", 5, event='plan_item_failed')
    except Exception as exc:
        _safe_abort(plan, f"{type(exc).__name__}: {exc}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="计划模式：按购买时间串行执行多个布防")
    sub = parser.add_subparsers(dest="cmd", required=True)
    worker = sub.add_parser("run", help="由 plan-start 在后台启动，不要手动运行")
    worker.add_argument("--generation")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        run(args.generation)


if __name__ == "__main__":
    try:
        main()
    except (nw.Abort, RuntimeError, OSError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
