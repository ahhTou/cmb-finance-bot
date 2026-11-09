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
ARM_MAX_LEAD = timedelta(days=36500)  # 计划不再限制 14 天（只防 datetime 溢出）
LOG_LINES = 15                        # view 返回的 plan.log 行数
CODE = re.compile(r"[A-Za-z0-9]{4,20}")
ACTIVE_PHASES = ("armed", "preparing", "waiting", "firing")
PAUSE_MODES = ("after_current", "immediate")
# plan.json 里新增的暂停/停止状态；旧计划文件缺这些键时按默认值补齐。
PLAN_STATE_DEFAULTS = {
    "pause_requested": False,
    "pause_reason": None,
    "paused_at": None,
    "stop_requested": False,
    "resume_count": 0,
}


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
    for key, value in PLAN_STATE_DEFAULTS.items():
        plan.setdefault(key, value)
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

def _settings_for(plan):
    """Purchase settings used by this plan: the start snapshot when available."""
    raw = (plan or {}).get("settings_snapshot")
    if isinstance(raw, dict):
        try:
            return purchase_settings.validate(raw)
        except RuntimeError:
            pass
    return purchase_settings.load()


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
    immediate = settings["cold_start_minutes"] == 0
    prep = timedelta(minutes=settings["cold_start_minutes"])
    items = plan.get("items") if isinstance(plan, dict) else None
    items = items if isinstance(items, list) else []
    next_index = next((index for index, item in enumerate(items)
                       if item.get("state") in ("pending", "running")), None)
    enriched, problems, warnings = [], [], []
    for index, item in enumerate(items):
        at = _plan_at(item)
        estimated_prep = at - prep
        prep_at = _iso(estimated_prep)
        prep_mode = "scheduled"
        prep_text = None
        if immediate:
            prep_mode, prep_text, prep_at = "immediate", "开始后立即准备", None
        elif index == next_index and now > estimated_prep - arm_gap and at > now:
            prep_mode, prep_text = "immediate", "剩余时间不足，开始后立即冷启动"
        end_at = _plan_end_at(at, item.get("mode"), settings, runtime)
        enriched.append(dict(item, prep_at=prep_at, prep_mode=prep_mode,
                             prep_text=prep_text, end_at=_iso(end_at)))
    if not items:
        problems.append("计划里还没有布防。")
    for index, item in enumerate(items, 1):
        at = _plan_at(item)
        if at <= now:
            problems.append(f"第 {index} 项购买时间已过（{at:%H:%M}）。")
    for index in range(1, len(items)):
        prev_at = _plan_at(items[index - 1])
        prev_end = datetime.fromisoformat(enriched[index - 1]["end_at"])
        current = enriched[index]
        cur_prep = (datetime.fromisoformat(current["prep_at"])
                    if current["prep_at"] else _plan_at(items[index]))
        if cur_prep >= prev_end + arm_gap:
            continue
        # 让 cur_prep 至少比 prev_end 晚 arm_gap 所需的购买时间差。
        need = prev_end - prev_at + prep + arm_gap
        minutes = math.ceil(need.total_seconds() / 60)
        action = "准备" if current["prep_mode"] == "immediate" else "开始冷启动"
        problems.append(
            f"第 {index + 1} 项与第 {index} 项间隔太近：第 {index + 1} 项需在 "
            f"{cur_prep:%H:%M:%S} {action}，但第 {index} 项预计 {prev_end:%H:%M:%S} 才结束；"
            f"请把购买时间拉开到至少 {minutes} 分钟。")
    if enriched and not immediate:
        prep_at = datetime.fromisoformat(enriched[0]["prep_at"])
        if now > prep_at - arm_gap and _plan_at(items[0]) > now:
            warnings.append("第一项已进入冷启动时间，开始后将立即冷启动。")
    return {"items": enriched, "problems": problems, "warnings": warnings}


def _status(primary, secondary, description=None):
    return {"primary": primary, "secondary": secondary, "description": description}


_TASK_SECONDARY = {
    "armed": "preparing",
    "preparing": "preparing",
    "waiting": "waiting",
    "firing": "submitting",
}
_TASK_DESCRIPTION = {
    "preparing": "正在冷启动、登录或打开购买页",
    "waiting": "购买页已就绪，等待到点查询或查询中",
    "submitting": "已进入提交阶段，等待结果",
}


def _item_status(item, task, now):
    """Primary · secondary · description for one plan item."""
    state = item.get("state") or "pending"
    result = item.get("result") or None
    if state == "running":
        linked = task if task and (not item.get("task_id") or task.get("task_id") == item.get("task_id")) else None
        phase = (linked or {}).get("phase")
        secondary = _TASK_SECONDARY.get(phase, "starting")
        # 布防前健康检查的进度：还没有进入任务阶段时，描述直接显示它。
        if item.get("health") and phase not in _TASK_SECONDARY:
            return _status("running", secondary, item["health"])
        return _status("running", secondary, _TASK_DESCRIPTION.get(secondary, "正在准备这一项"))
    if state == "done":
        outcome = item.get("outcome")
        secondary = "dry_run" if outcome == "dry_run" else "success" if outcome == "success" else "completed"
        return _status("done", secondary, result or "已完成")
    if state == "failed":
        text = result or ""
        if item.get("outcome") == "unknown" or "结果未知" in text:
            secondary = "result_unknown"
        elif "配置" in text or "已修改" in text:
            secondary = "config_changed"
        elif "超过预计" in text or "超时" in text:
            secondary = "timeout"
        elif "没有买到" in text or "额度" in text:
            secondary = "no_quota"
        else:
            secondary = "purchase_failed"
        return _status("failed", secondary, result or "失败")
    if state == "skipped":
        text = result or ""
        if "取消" in text:
            return _status("cancelled", "manual_cancel", result)
        if "购买时间已过" in text:
            return _status("expired", "time_passed", result or "购买时间已过")
        return _status("skipped", "skipped", result)
    # Pending: a past window means it was not executed while the app/plan ran.
    try:
        at = _plan_at(item)
    except nw.Abort:
        return _status("pending", "scheduled", None)
    if at <= now:
        return _status("expired", "time_passed", "计划时间已过，未在应用运行期间执行")
    secondary = "immediate" if item.get("prep_mode") == "immediate" else "scheduled"
    return _status("pending", secondary, item.get("prep_text"))


def _plan_status(plan, item_statuses, task, running, stale, heartbeat_stale):
    phase = plan.get("phase")
    result = plan.get("result") or None
    if phase == "running":
        if stale:
            return _status("unknown", "process_exited", "计划进程已退出，结果未知；请查交易记录")
        current = next((index for index, item in enumerate(plan.get("items") or [])
                        if (item.get("state") or "pending") == "running"), None)
        if current is None:
            current = next((index for index, item in enumerate(plan.get("items") or [])
                            if (item.get("state") or "pending") == "pending"), None)
        if heartbeat_stale:
            return _status("running", "heartbeat_timeout", "计划进程仍在，但心跳超时；只告警，不自动重试交易")
        if current is not None:
            item = plan["items"][current]
            secondary = item_statuses[current]["secondary"]
            return _status("running", secondary, f"第 {current + 1} 项 {item.get('code', '')}：{item_statuses[current]['description'] or ''}".strip())
        return _status("running", "starting", None)
    if phase == "paused":
        reason = ("管理 App 已退出，自动暂停" if plan.get("pause_reason") == "app_exit"
                  else "手动暂停")
        description = f"计划已暂停（{reason}）"
        if (task and task.get("plan_id") == plan.get("plan_id")
                and task.get("phase") in ACTIVE_PHASES):
            description += "；当前布防继续执行，恢复后继续后续项"
        return _status("pending", "paused", description)
    if phase == "done":
        return _status("done", "completed", result or "计划已完成")
    if phase == "aborted":
        text = result or ""
        secondary = "config_changed" if "配置" in text else "result_unknown" if "结果未知" in text else "aborted"
        return _status("failed", secondary, result or "计划已中止")
    if phase == "disarmed":
        return _status("cancelled", "manual_cancel", result or "计划已取消")
    items = plan.get("items") or []
    expired = sum(1 for status in item_statuses if status["primary"] == "expired")
    if items and expired == len(items):
        return _status("expired", "time_passed", "计划时间已过，未在应用运行期间执行")
    if expired:
        return _status("pending", "partially_expired", f"有 {expired} 项已过期")
    return _status("pending", "scheduled", "计划待开始")


def view():
    """后端响应：计划 + 运行/过期状态 + problems/warnings + 任务与日志。"""
    live_settings = purchase_settings.load()
    revision = purchase_settings.revision(live_settings)
    now = _now()
    plan = load_plan()
    runtime = _runtime(plan)
    problems, warnings = [], []
    running = stale = heartbeat_stale = settings_changed = False
    heartbeat_age = None
    if plan is not None:
        computed = schedule(plan, _settings_for(plan), now, runtime)
        plan = dict(plan, items=computed["items"], content_revision=plan_content_revision(plan))
        problems, warnings = computed["problems"], computed["warnings"]
        running = plan.get("phase") == "running" and nw.alive(plan.get("pid"))
        stale = plan.get("phase") == "running" and not running
        settings_changed = bool(
            plan.get("settings_revision")
            and revision != plan["settings_revision"])
        last_tick = plan.get("last_tick")
        if last_tick:
            try:
                heartbeat_age = max(0, round((now - datetime.fromisoformat(last_tick)).total_seconds()))
            except (TypeError, ValueError):
                heartbeat_age = None
        heartbeat_stale = bool(
            plan.get("phase") == "running"
            and (heartbeat_age is None
                 or heartbeat_age > runtime["heartbeat_timeout_seconds"]))
    task = nw.load_task()
    if plan is not None:
        statuses = [_item_status(item, task, now) for item in plan["items"]]
        for item, status in zip(plan["items"], statuses):
            item["status"] = status
        plan["status"] = _plan_status(plan, statuses, task, running, stale, heartbeat_stale)
    path = log_path()
    logs = (path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_LINES:]
            if path.exists() else [])
    return {"plan": plan, "status": plan.get("status") if plan else None,
            "running": bool(running), "stale": bool(stale),
            "heartbeat_stale": heartbeat_stale, "heartbeat_age_s": heartbeat_age,
            "heartbeat_timeout_s": runtime["heartbeat_timeout_seconds"],
            "settings_changed": settings_changed,
            "problems": problems, "warnings": warnings, "task": task,
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
            "settings_revision": _settings_revision(), "result": None, "items": items,
            **PLAN_STATE_DEFAULTS}
    with plan_lock(False):
        current = load_plan()
        if current and current.get("phase") == "running" and nw.alive(current.get("pid")):
            raise nw.Abort("计划正在运行，不能修改；先取消计划。")
        if current and current.get("phase") == "paused":
            # A paused plan is still alive: it must be resumed or stopped, never
            # silently replaced by a new draft.
            raise nw.Abort("计划已暂停；请先继续或停止计划后再保存。")
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
        if phase == "paused":
            raise nw.Abort("计划已暂停；请先继续或停止计划后再开始。")
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
                        settings_snapshot=settings, runtime_settings=runtime,
                        pause_requested=False, pause_reason=None, paused_at=None,
                        stop_requested=False, resume_count=0)
            for item in plan.get("items", []):
                item.update(state="pending", task_id=None, result=None,
                            armed_at=None, ended_at=None)
                item.pop("health", None)
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


def pause(mode="after_current"):
    """plan-pause：暂停计划。

    after_current（默认）只写请求，计划进程在当前布防项结束后或下一个循环顶
    置 paused；immediate 会先取消本计划当前的值守（firing 一律拒绝），再停掉
    计划进程并立即置 paused。没有活跃的计划值守时两者等价。
    """
    if mode not in PAUSE_MODES:
        raise nw.Abort("暂停方式只能是 after_current 或 immediate。")
    with plan_lock(False):
        plan = load_plan()
        if plan is None or plan.get("phase") != "running":
            raise nw.Abort("计划没有在运行，不需要暂停。")
        now = _now_iso()
        if mode == "after_current":
            plan.update(pause_requested=True, pause_reason="manual", last_tick=now)
            if nw.alive(plan.get("pid")):
                save_plan(plan)
            else:
                # The worker is gone (stale): nothing will ever apply the
                # request, so settle the paused state here.
                plan.update(phase="paused", pause_requested=False, paused_at=now,
                            pause_reason="manual", last_tick=now)
                save_plan(plan)
                _note("计划已暂停：当前布防结束后暂停")
            return view()
        # immediate: never stop a submission that may already be firing.
        # "当前 watch" 必须是本计划、且属于正在跑的项的 task；上一项遗留的终态
        # task（可能带 fired_at）不算，否则会在两项之间误报“正在提交”。
        task = nw.load_task()
        own = task if task and task.get("plan_id") == plan.get("plan_id") else None
        running = next((row for row in plan.get("items") or []
                        if row.get("state") == "running"), None)
        running_task_id = (running or {}).get("task_id")
        if own and running is not None and not running_task_id:
            own = own if own.get("plan_item") == running.get("item_id") else None
        elif own and (running is None or own.get("task_id") != running_task_id):
            own = None
        if own and (own.get("phase") == "firing" or own.get("fired_at")):
            raise nw.Abort("当前布防正在提交，不能暂停；请等结果并查交易记录。")
        plan.update(pause_requested=True, pause_reason="manual", last_tick=now)
        save_plan(plan)
        active = own if own and own.get("phase") in ACTIVE_PHASES else None
        if active:
            nw.disarm_task(expected_plan_id=plan.get("plan_id"),
                           expected_task_id=active.get("task_id"))
            items = plan.get("items") or []
            index = next((i for i, item in enumerate(items)
                          if item.get("task_id") == active.get("task_id")), None)
            if index is None:
                index = next((i for i, item in enumerate(items)
                              if item.get("state") == "running"), None)
            if index is not None:
                items[index].update(state="skipped",
                                    result="计划暂停：当前布防已停止", ended_at=now)
        try:
            _stop_plan_process(plan)
        except (nw.Abort, OSError) as exc:
            _note(f"计划进程未能确认停止：{exc}")
        plan.update(phase="paused", pause_requested=False, paused_at=now,
                    pause_reason="manual", last_tick=now)
        save_plan(plan)
        _note("计划已暂停：当前布防已停止")
    return view()


def resume():
    """plan-resume：恢复暂停的计划（或取消 App 退出留下的自动暂停）。"""
    with plan_lock(False):
        plan = load_plan()
        if plan is None:
            raise nw.Abort("计划没有暂停，不需要恢复。")
        phase = plan.get("phase")
        if phase == "running":
            if plan.get("pause_requested") and plan.get("pause_reason") == "app_exit":
                # The management App is back before the worker reached a
                # boundary: simply cancel the pending automatic pause.
                plan.update(pause_requested=False, pause_reason=None, paused_at=None,
                            last_tick=_now_iso())
                save_plan(plan)
                return view()
            raise nw.Abort("计划没有暂停，不需要恢复。")
        if phase != "paused":
            raise nw.Abort("计划没有暂停，不需要恢复。")
        task = nw.load_task()
        if _active_task(task) and task.get("plan_id") != plan.get("plan_id"):
            raise nw.Abort("当前有手动布防，请在布防结束后开始计划。")
        generation = uuid.uuid4().hex
        now = _now_iso()
        plan.update(phase="running", generation=generation, pid=None, last_tick=now,
                    pause_requested=False, pause_reason=None, paused_at=None,
                    stop_requested=False,
                    resume_count=int(plan.get("resume_count") or 0) + 1)
        save_plan(plan)
        try:
            proc = _spawn(generation)
        except (OSError, ValueError) as exc:
            plan.update(phase="paused", result=f"计划进程启动失败：{exc}",
                        last_tick=_now_iso())
            save_plan(plan)
            raise nw.Abort(f"计划进程启动失败：{exc}")
        plan["pid"] = proc.pid
        save_plan(plan)
    return view()


def pause_after_app_exit():
    """Best-effort：管理 App 退出后让运行中的计划在当前布防结束后暂停。

    Called by push.py's lifecycle watchdog; never raises. Does not overwrite a
    manual pause request or a pending stop.
    """
    try:
        with plan_lock(False):
            plan = load_plan()
            if not plan or plan.get("phase") != "running":
                return False
            if plan.get("stop_requested") or plan.get("pause_reason") == "manual":
                return False
            plan.update(pause_requested=True, pause_reason="app_exit",
                        last_tick=_now_iso())
            save_plan(plan)
        _note("管理 App 已退出，计划将在当前布防结束后暂停")
        return True
    except Exception:
        return False


def disarm(mode="immediate"):
    """plan-disarm：停止计划。

    immediate（默认，兼容旧用法）保持原有行为：立刻写 disarmed 再停进程和当前
    值守；after_current 只写停止请求，计划进程在当前布防项结束后自己收口。
    """
    if mode not in PAUSE_MODES:
        raise nw.Abort("停止方式只能是 after_current 或 immediate。")
    with plan_lock(False):
        plan = load_plan()
        if plan is None or plan.get("phase") not in ("running", "paused"):
            raise nw.Abort("计划没有在运行。")
        if plan.get("phase") == "paused" and mode == "after_current":
            raise nw.Abort("计划已暂停，请直接停止或恢复后再操作。")
        if mode == "after_current" and nw.alive(plan.get("pid")):
            plan.update(stop_requested=True, last_tick=_now_iso())
            save_plan(plan)
            return view()
        # immediate, or after_current on a stale worker (degraded to immediate).
        task = nw.load_task()
        if task and task.get("phase") == "firing":
            raise nw.Abort("当前布防正在提交，不能取消计划；请等结果并查交易记录。")
        now = _now_iso()
        running_index = next((index for index, item in enumerate(plan.get("items") or [])
                              if item.get("state") == "running"), None)
        plan.update(phase="disarmed", ended_at=now, result="计划已被手动取消",
                    last_tick=now, stop_requested=False, pause_requested=False)
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
    """plan-clear：仅未运行/未暂停、且没有活跃值守任务时删除 plan.json。"""
    with plan_lock(False):
        plan = load_plan()
        if plan and plan.get("phase") == "running" and nw.alive(plan.get("pid")):
            raise nw.Abort("计划正在运行；先取消计划。")
        if plan and plan.get("phase") == "paused":
            raise nw.Abort("计划已暂停；请先继续或停止计划后再清空。")
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


def _touch_running(plan, *, health=None, item_id=None):
    """Merge this worker's progress fields into the *current* plan.json.

    Used while the pre-arm health check runs, when the in-memory `plan` snapshot
    is stale: another process may have written pause_requested /
    stop_requested / pause_reason meanwhile. Reload under the lock and update
    only `last_tick` (and the matching item's `health` by item_id); never write
    the stale snapshot back. Returns False when the plan is no longer running.
    """
    with plan_lock():
        current = load_plan()
        if (not current or current.get("phase") != "running"
                or current.get("generation") != plan.get("generation")
                or current.get("plan_id") != plan.get("plan_id")):
            return False
        current["last_tick"] = _now_iso()
        if health is not None:
            for row in current.get("items") or []:
                if item_id is not None and row.get("item_id") == item_id:
                    row["health"] = health
                    break
        save_plan(current)
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


def _pause_boundary(plan):
    """Worker boundary: persist phase=paused (keeps pause_reason)."""
    reason = plan.get("pause_reason")
    now = _now_iso()
    plan.update(phase="paused", pause_requested=False, paused_at=now, last_tick=now)
    if not _save_running(plan):
        return False
    log("计划已暂停：管理 App 已退出" if reason == "app_exit"
        else "计划已暂停：当前布防结束后暂停")
    return True


def _stop_boundary(plan):
    """Worker boundary: stop the plan, skipping items that never ran."""
    now = _now_iso()
    plan.update(phase="disarmed", ended_at=now, last_tick=now, stop_requested=False,
                result="计划已停止：当前布防结束后停止")
    for item in plan.get("items") or []:
        if (item.get("state") or "pending") == "pending":
            item.update(state="skipped", result="计划已停止", ended_at=now)
    if not _save_running(plan):
        return False
    log("计划已停止：当前布防结束后停止")
    nw.alert("计划已取消", "计划已在当前布防结束后停止。", event="plan_cancelled")
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


def _new_health_monitor(runtime):
    """Runtime health-check bookkeeping shared by one plan-worker run."""
    return {"issue": "", "next": time.monotonic() + runtime["health_monitor_seconds"]}


def _monitor_health(plan, index, runtime, monitor):
    """Best-effort health check while waiting for one item's watch.

    Never restarts or kills anything and never raises: a broken emulator only
    warns once per state change (`health_warning`) and notifies again when it
    recovers (`network_recovered`). A down network gets one non-blocking
    `reconnect_wifi()` attempt per tick; the next tick checks again.
    """
    try:
        now = time.monotonic()
        if now < monitor["next"]:
            return
        monitor["next"] = now + runtime["health_monitor_seconds"]
        item = (plan.get("items") or [])[index]
        issue = ""
        if not nw.emulator_running():
            issue = "模拟器没有运行"
        elif not nw.booted():
            issue = "模拟器没有开机"
        elif nw.network_state() != "up":
            issue = "模拟器没有网络"
            try:
                nw.reconnect_wifi()      # safe, non-blocking; re-check next tick
            except Exception:
                pass
        if issue == monitor["issue"]:
            return
        monitor["issue"] = issue
        code = item.get("code", "")
        if issue:
            nw.alert("计划运行期健康检查异常",
                     f"第 {index + 1} 项 {code}：{issue}；计划继续，请留意。",
                     3, event="health_warning")
        else:
            nw.alert("计划运行期健康检查已恢复",
                     f"第 {index + 1} 项 {code}：模拟器与网络已恢复正常；计划继续。",
                     3, event="network_recovered")
    except Exception:
        pass                             # a health check must never abort the plan


def _wait_item(plan, index, end_at, runtime, monitor=None):
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
        if plan.get("settings_revision"):
            try:
                changed = (purchase_settings.revision(purchase_settings.load())
                           != plan["settings_revision"])
            except (RuntimeError, OSError, ValueError):
                changed = True
            # A submission in flight or an already terminal item must finish;
            # the run loop then stops before arming the next item.
            settled = bool(task and (task.get("phase") in ("done", "aborted", "disarmed", "firing")
                                     or task.get("fired_at")))
            if changed and not settled:
                return ("config-changed",
                        "值守配置在计划期间被修改，当前项未提交，计划已停止")
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
        if monitor is not None:
            _monitor_health(plan, index, runtime, monitor)
        time.sleep(runtime["poll_seconds"])


def _settle(plan, index, item, outcome):
    """Apply one waited item outcome; shared by the loop and pause recovery.

    Returns True when the plan can continue with the next item, False when the
    worker must stop (plan aborted, cancelled or no longer running).
    """
    state, result = outcome
    if state == "disarmed":
        _abort(plan, f"第 {index + 1} 项布防被取消，计划已停止",
               item_index=index, item_state="skipped", item_result="用户取消布防")
        return False
    if state == "config-changed":
        residual = _abort_running_watch(plan)
        message = f"第 {index + 1} 项：{result}"
        if residual:
            message += f"；{residual}"
        _abort(plan, message, item_index=index, item_state="failed",
               item_result="值守配置已修改，当前项未提交")
        return False
    if state in ("unknown", "firing-timeout"):
        if not _finish_item(plan, index, "failed", result, outcome="unknown"):
            return False
        _abort(plan, f"第 {index + 1} 项{result}")
        return False
    if state in ("success", "dry_run"):
        if not _finish_item(plan, index, "done", result, outcome=state):
            return False
        log(f"第 {index + 1} 项完成：{result or '已提交'}")
        nw.alert(f"计划第 {index + 1} 项完成",
                 f"{item['code']}：{result or '已提交'}",
                 3 if plan.get("dry_run") else 5, event='plan_item_completed')
        return True
    if not _finish_item(plan, index, "failed", result):
        return False
    log(f"第 {index + 1} 项失败：{result or '未知'}")
    nw.alert(f"计划第 {index + 1} 项失败",
             f"{item['code']}：{result or '未知原因'}", 5, event='plan_item_failed')
    return True


def _recover_running(plan, runtime, monitor=None):
    """Settle a `running` item left over by a pause when the worker restarts.

    The item was armed (or about to be) when the previous worker paused/exited:
    - nothing armed yet → put it back in the pending queue;
    - its watch is still there (or already terminal) → wait and settle it with
      the normal outcome rules;
    - its task record vanished/replaced → unknown, stop the plan.
    Returns False when the worker must exit.
    """
    while True:
        index = next((i for i, item in enumerate(plan.get("items") or [])
                      if item.get("state") == "running"), None)
        if index is None:
            return True
        item = plan["items"][index]
        task = nw.load_task()
        own = task if task and task.get("plan_id") == plan.get("plan_id") else None
        if own is not None and item.get("task_id") and own.get("task_id") != item["task_id"]:
            own = None          # task record replaced by another one: ours is lost
        if not item.get("task_id"):
            # A crash between arm_task() and saving task_id leaves the record
            # tagged with this item's plan_item; anything else means the item
            # never armed and can go back to pending.
            adopted = own if own and own.get("plan_item") == item.get("item_id") else None
            if adopted is None:
                item.update(state="pending", armed_at=None, ended_at=None, result=None)
                item.pop("health", None)
                plan["last_tick"] = _now_iso()
                if not _save_running(plan):
                    return False
                log(f"第 {index + 1} 项上次还没开始布防，已重新排队。")
                continue
            item["task_id"] = adopted.get("task_id")
        elif own is None:
            result = "结果未知：值守任务记录已丢失；请查交易记录，不要重复提交"
            if not _finish_item(plan, index, "failed", result, outcome="unknown"):
                return False
            _abort(plan, f"第 {index + 1} 项{result}")
            return False
        settings = _settings_for(plan)
        end_at = datetime.fromisoformat(
            schedule(plan, settings, _now(), runtime)["items"][index]["end_at"])
        outcome = _wait_item(plan, index, end_at, runtime, monitor)
        if outcome is None:
            return False
        # Another process may have written pause/stop while we waited: settle the
        # outcome onto the current plan.json, not the copy from before the wait.
        latest = _read_running(plan)
        if latest is None:
            return False
        plan = latest
        item = plan["items"][index]
        if not _settle(plan, index, item, outcome):
            return False
        log(f"第 {index + 1} 项已按暂停前的值守结果收口。")


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
        monitor = _new_health_monitor(runtime)
        nw.alert(f"计划已开始：{len(plan.get('items') or [])} 项（{action}）", event='plan_started')
        log(f"计划开始：{len(plan.get('items') or [])} 项（{action}）")
        # A pause can leave an item `running`; settle it before anything else.
        if not _recover_running(plan, runtime, monitor):
            return
        while True:
            plan = _read_running(plan)
            if plan is None:
                return
            if plan.get("stop_requested"):
                _stop_boundary(plan)
                return
            if plan.get("pause_requested"):
                _pause_boundary(plan)
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
            live_settings = purchase_settings.load()
            if purchase_settings.revision(live_settings) != plan.get("settings_revision"):
                _abort(plan, "值守配置在计划期间被修改，计划已停止")
                return
            settings = _settings_for(plan)
            end_at = datetime.fromisoformat(
                schedule(plan, settings, now, runtime)["items"][index]["end_at"])
            prep = settings["cold_start_minutes"]
            if at - now < timedelta(minutes=prep) + arm_gap:
                prep = 0
                log(f"第 {index + 1} 项剩余时间不足，改为立即冷启动。")
            plan["last_tick"] = _now_iso()
            item.update(state="running", armed_at=_now_iso(), ended_at=None,
                        result=None, task_id=None, prep_minutes=prep,
                        health="正在做布防前健康检查")
            if not _save_running(plan):
                return
            log(f"第 {index + 1} 项开始布防：{item['code']} {item['amount']} 元，"
                f"购买 {at:%H:%M:%S}，冷启动提前 {prep} 分钟。")
            beat = [time.monotonic()]
            health_item_id = item.get("item_id")

            def tick():
                """Keep the plan heartbeat fresh while the health check waits.

                Only last_tick is merged into the current plan.json: the snapshot
                from before the health check is stale and writing it back would
                clobber a pause/stop request another process just wrote.
                """
                now_mono = time.monotonic()
                if now_mono - beat[0] < runtime["heartbeat_seconds"]:
                    return
                beat[0] = now_mono
                try:
                    _touch_running(plan)
                except Exception:
                    pass             # best-effort: a failed heartbeat never blocks arming

            def note(text):
                """Plan-mode progress: plan.log + the item's health text."""
                log(f"健康检查：{text}")
                try:
                    _touch_running(plan, health=text, item_id=health_item_id)
                except Exception:
                    pass             # best-effort: never let progress writing abort

            try:
                repairs = nw.arm_health(runtime["health_timeout_minutes"],
                                        tick=tick, note=note)
            except nw.Abort as exc:
                message = str(exc) or "健康检查未通过"
                if not message.startswith("健康检查未通过"):
                    message = f"健康检查未通过：{message}"
                # A pause/stop may have been written while the check was running:
                # settle the failure onto the current plan.json, never the snapshot.
                latest = _read_running(plan)
                if latest is None:
                    return
                plan = latest
                item = plan["items"][index]
                if not _finish_item(plan, index, "failed", message):
                    return
                log(f"第 {index + 1} 项布防失败：{message}")
                nw.alert(f"计划第 {index + 1} 项失败", f"{item['code']}：{message}", 5,
                         event='plan_item_failed')
                continue   # 健康检查失败只让本项失败，继续下一项
            latest = _read_running(plan)
            if latest is None:
                return     # 健康检查期间计划被取消
            plan = latest
            item = plan["items"][index]
            if plan.get("pause_requested"):
                # 暂停请求落在真正布防之前：这一项退回 pending，计划就地暂停。
                item.update(state="pending", armed_at=None, ended_at=None, result=None)
                item.pop("health", None)
                plan["last_tick"] = _now_iso()
                _pause_boundary(plan)
                return
            if repairs:
                log("健康检查：已" + "、".join(repairs))
            log("健康检查通过")
            item.pop("health", None)
            plan["last_tick"] = _now_iso()
            if not _save_running(plan):
                return
            try:
                task = nw.arm_task(item["code"], item["amount"], at=item["at"],
                                   dry_run=bool(plan.get("dry_run")),
                                   prep_minutes=prep, mode=item["mode"],
                                   settings_revision=plan.get("settings_revision"),
                                   plan_id=plan.get("plan_id"),
                                   plan_item=item.get("item_id"),
                                   max_lead=ARM_MAX_LEAD)
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
            outcome = _wait_item(plan, index, end_at, runtime, monitor)
            if outcome is None:
                return
            # A pause/stop may have been requested while the item was finishing:
            # reload first so _settle() never writes the pre-wait plan back.
            latest = _read_running(plan)
            if latest is None:
                return
            plan = latest
            item = plan["items"][index]
            if not _settle(plan, index, item, outcome):
                return
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
