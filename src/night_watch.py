#!/usr/bin/env python3
"""Overnight watch: keep the emulator healthy with the bank app closed, log in
fresh shortly before the sale, open the detail page, then submit exactly one
purchase through fast_buy_uia2.run().

The account holder arms it in their own terminal before bed:

    python3 -B src/night_watch.py arm --code 133045A --amount 0.01 \
        --at 2026-11-03T09:00:00 [--dry-run]

`--at` is the sale time; goBuy() fires OPEN_DELAY after it. `arm` closes the
app and starts a detached `caffeinate -ims ... night_watch.py run`, so the
Mac stays awake exactly as long as the watch runs while the display may turn
off on its own. `status` and `disarm` inspect or cancel it. Alerts go out by
email (see notify.py).

Timeline:
  night      emulator health every 2 min, app stays closed
  T-15 min   cold-start app -> 我的 -> pattern login; on failure force-stop and
             retry, at most LOGIN_TRIES patterns sent in total
  then       jump to the detail page (buy button state does not matter)
  T-1 min    confirm the detail page is still open (navigation only)
  T+200 ms   fast_buy_uia2.run(): goBuy() straight into the purchase form

Rules kept from AGENT_WORKFLOW.md: one submission only, never retry; an
unknown result is reported, not resubmitted.
"""
import argparse
import fcntl
import uuid
from contextlib import contextmanager
import json
import os
import re
import signal
import subprocess
import sys
import time
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
STATE = ROOT / "var" / "night"
TASK = STATE / "task.json"
LOG = STATE / "watch.log"
PACKAGE = "cmb.pb"

PREP_MINUTES = 7                     # new watch default: cold start + login + gated page
MIN_PREP_MINUTES = 1                 # CLI override; settings default is seven minutes
FINAL_LEAD = timedelta(seconds=60)   # last page check, then hand off to run()
OPEN_DELAY = timedelta(milliseconds=200)
ARM_SLACK = timedelta(minutes=2)     # arm at least prep + 2 min before the sale
NOW_LEAD = timedelta(minutes=3)      # `arm --now`: sale this far out, prep starts at once
MAX_LEAD = timedelta(hours=24)
HEALTH_EVERY = 120                   # seconds between overnight checks
LOGIN_TRIES = 3                      # patterns actually sent; stays clear of lockout
LOGIN_CYCLES = 5                     # cold starts, including ones with no login page

MODES = ("first_launch", "redemption")
DEFAULT_WINDOW_MINUTES = 2           # redemption: keep reopening this long
MAX_WINDOW_MINUTES = 60
REDEEM_WAIT = 15.0   # allow slow navigation/business data; fresh errors retry sooner
REDEEM_GAP = 0.95    # minimum interval after a confirmed fresh error

import fast_buy
import keychain_store
import manage
import notify
import purchase_settings
import query_gate
import secure_input


class Abort(Exception):
    pass


def log(message):
    print(f"{datetime.now():%m-%d %H:%M:%S} {message}", flush=True)


def alert(subject, body=""):
    log(f"通知：{subject}")
    notify.send(subject, f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{subject}\n\n{body}".strip())


def load_task():
    return json.loads(TASK.read_text(encoding="utf-8")) if TASK.exists() else None


@contextmanager
def task_lock(blocking=True):
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "task.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise Abort("另一个布防操作正在进行，请稍后再试。")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save_task(task):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = TASK.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, TASK)


def persist(task):
    """A previous worker must never overwrite a replacement or cancelled task."""
    with task_lock():
        current = load_task()
        if (not current or current.get("task_id") != task.get("task_id")
                or current.get("generation") != task.get("generation")
                or current.get("phase") == "disarmed"):
            raise Abort("任务已被替换或取消，旧值守停止。")
        if current.get("fired_at") and task.get("phase") == "firing":
            raise Abort("任务已进入过提交，禁止再次执行。")
        if current.get("fired_at") and task.get("fired_at") != current["fired_at"]:
            raise Abort("不能删除或更改提交标记。")
        if task.get("patterns_sent", 0) < current.get("patterns_sent", 0):
            raise Abort("不能减少已输入图案次数。")
        save_task(task)
        if task.get("phase") in ("done", "aborted", "disarmed"):
            record_history(task)


def record_history(task):
    record = {k: task.get(k) for k in ("task_id", "armed_at", "code", "amount", "at",
              "mode", "window_minutes", "probes", "dry_run", "phase", "result",
              "fired_at", "resumes", "purchase_flow", "fire_at", "end_at",
              "prep_minutes", "watch_settings")}
    record["ended_at"] = datetime.now().isoformat()
    with (STATE / "history.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(record, ensure_ascii=False) + "\n")


def status_info(lines=30):
    task = load_task()
    tick = task and task.get("last_tick")
    age = (datetime.now() - datetime.fromisoformat(tick)).total_seconds() if tick else None
    return {"task": task, "running": bool(task and alive(task.get("pid"))),
            "legacy": bool(task and task.get("version") != 2),
            "last_tick_age_s": age, "stale": age is not None and age > 300,
            "logs": LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
                    if LOG.exists() else []}


def spawn_watch(task):
    # -i/-m/-s keep the Mac and disk awake without forcing the display on.
    # Display sleep is allowed; whether macOS then asks for a password is a
    # system setting this script deliberately does not change.
    with LOG.open("ab") as out:
        proc = subprocess.Popen(["/usr/bin/caffeinate", "-ims", sys.executable, "-B",
                                 str(Path(__file__).resolve()), "run",
                                 "--generation", task["generation"]],
                                stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                                cwd=ROOT, start_new_session=True)
    task["pid"] = proc.pid
    save_task(task)


def stop_watch(task):
    pid = task.get("pid")
    if not alive(pid):
        return
    cmd = manage.command(pid)
    # macOS caffeinate execs Python at the recorded PID; its assertion holder
    # is a child. Verify the worker invocation, not the wrapper's name.
    invocation = r"(?:^|\s)" + re.escape(str(Path(__file__).resolve())) + r"\s+run"
    generation = task.get("generation")
    if generation:
        invocation += r"\s+--generation\s+" + re.escape(str(generation))
    elif task.get("version") == 2:
        raise Abort("进程身份无法确认，拒绝终止；请人工检查。")
    invocation += r"\s*$"
    if not re.search(invocation, cmd):
        raise Abort("进程身份无法确认，拒绝终止；请人工检查。")
    try:
        if os.getpgid(pid) != pid:
            raise Abort("进程身份无法确认，拒绝终止；请人工检查。")
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # Worker exited between the liveness check and termination.
    end = time.monotonic() + 10
    while alive(pid) and time.monotonic() < end:
        time.sleep(.1)
    if alive(pid):
        os.killpg(pid, signal.SIGKILL)
        end = time.monotonic() + 2
        while alive(pid) and time.monotonic() < end:
            time.sleep(.1)
        if alive(pid):
            raise Abort("旧值守未退出，不能恢复。")


def resume_task(reason, by="user", kill_stale=False, after_manual_login=False):
    with task_lock(False):
        task = load_task()
        if not task or task.get("version") != 2:
            raise Abort("旧版本任务，不能恢复；请查交易记录后重新布防。")
        if task.get("fired_at") or task.get("phase") not in ("armed", "preparing", "aborted"):
            # "waiting" (redemption window) is live: never resumed here.
            raise Abort("任务已提交或阶段不允许恢复；请查交易记录，不要重试。")
        if datetime.fromisoformat(task["fire_at"]) - datetime.now() <= timedelta(minutes=3):
            raise Abort("距开售不足三分钟，不能恢复。")
        if len(task.get("resumes", [])) >= 2:
            raise Abort("已恢复两次，不能继续恢复。")
        if task.get("patterns_sent", 0) >= LOGIN_TRIES and not after_manual_login:
            raise Abort("图案次数已用完，请手动登录。")
        if not reason.strip() or len(reason) > 200:
            raise Abort("请填写 1–200 字的恢复原因。")
        if not (emulator_running() and booted()):
            raise Abort("模拟器没有运行或尚未开机。")
        if alive(task.get("pid")):
            tick = task.get("last_tick")
            if not kill_stale or not tick or (datetime.now() - datetime.fromisoformat(tick)).total_seconds() <= 300:
                raise Abort("值守仍在运行且不满足卡住条件。")
            stop_watch(task)
        task.pop("result", None)
        task.setdefault("resumes", []).append({"at": datetime.now().isoformat(), "reason": reason, "by": by})
        task.update(phase="armed", generation=uuid.uuid4().hex,
                    after_manual_login=after_manual_login, last_tick=datetime.now().isoformat())
        save_task(task)
        spawn_watch(task)
    alert(f"值守已恢复（第 {len(task['resumes'])} 次，原因：{reason}）")
    return task


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def parse_target(value, now=None, prep_minutes=PREP_MINUTES, label="开售时间"):
    if "T" not in value:
        raise Abort(f"{label}必须写完整时间，例如 2026-11-03T09:00:00。")
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise Abort("时间格式应为 YYYY-MM-DDTHH:MM:SS。")
    if when.tzinfo is not None:
        raise Abort("请使用本机本地时间，不要带时区。")
    if not 1 <= prep_minutes <= 60:
        raise Abort("冷启动提前量必须为 1–60 分钟。")
    lead = when - (now or datetime.now())
    min_lead = timedelta(minutes=prep_minutes) + ARM_SLACK
    if lead < min_lead:
        raise Abort(f"{label}至少要在 {min_lead.seconds // 60} 分钟之后，留给登录和打开购买页。")
    if lead > MAX_LEAD:
        raise Abort(f"{label}不能超过 24 小时之后。")
    return when


def parse_window(when, until, window_minutes):
    """End of the redemption window. `until` wins over `window_minutes`."""
    if until:
        if "T" not in until:
            raise Abort("结束时间要写完整，例如 2026-11-04T00:18:00。")
        try:
            end = datetime.fromisoformat(until)
        except ValueError:
            raise Abort("结束时间格式应为 YYYY-MM-DDTHH:MM:SS。")
        if end.tzinfo is not None:
            raise Abort("请使用本机本地时间，不要带时区。")
        if end <= when:
            raise Abort("结束时间必须晚于开始时间。")
    else:
        minutes = window_minutes if window_minutes is not None else DEFAULT_WINDOW_MINUTES
        if not 1 <= minutes <= MAX_WINDOW_MINUTES:
            raise Abort(f"窗口分钟数只能是 1–{MAX_WINDOW_MINUTES}。")
        end = when + timedelta(minutes=minutes)
    if end - when > timedelta(minutes=MAX_WINDOW_MINUTES):
        raise Abort(f"窗口最长 {MAX_WINDOW_MINUTES} 分钟。")
    return end, int(round((end - when).total_seconds() / 60))


# ---------------------------------------------------------------- arm / disarm

def arm(args):
    with task_lock(False):
        return _arm(args)


def arm_task(code, amount, at=None, dry_run=False, prep_minutes=None, now=False,
             mode="first_launch", window_minutes=None, until=None, settings_revision=None):
    return arm(argparse.Namespace(code=code, amount=amount, at=at, dry_run=dry_run,
                                  prep_minutes=prep_minutes, now=now, mode=mode,
                                  window_minutes=window_minutes, until=until,
                                  settings_revision=settings_revision))


def _arm(args):
    task = load_task()
    if task and (alive(task.get("pid")) or task.get("phase") == "firing"):
        raise Abort("已有值守在运行；先 status 查看或 disarm 取消。")
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise Abort("产品代码格式不正确。")
    mode = getattr(args, "mode", "first_launch") or "first_launch"
    if mode not in MODES:
        raise Abort("模式只能是 first_launch 或 redemption。")
    retry_settings = purchase_settings.validate(purchase_settings.load())
    expected_revision = getattr(args, 'settings_revision', None)
    if expected_revision and expected_revision != purchase_settings.revision(retry_settings):
        raise Abort('值守配置已变化，请重新打开布防表单核对当前配置。')
    if args.prep_minutes is None:
        args.prep_minutes = retry_settings['cold_start_minutes']
    amount = fast_buy.parse_amount(args.amount)
    if not 1 <= args.prep_minutes <= 60:
        raise Abort("冷启动提前量必须为 1–60 分钟。")
    if args.now:
        # Rehearsal: preparation starts at once (the sale is already inside
        # the prep window) and leaves ~2 min before the last-minute check.
        when = datetime.now().replace(microsecond=0) + NOW_LEAD
    else:
        when = parse_target(args.at, prep_minutes=args.prep_minutes,
                            label="额度放出时间" if mode == "redemption" else "开售时间")
    start, query_end = query_gate.schedule(when, mode, retry_settings)
    end = window = None
    if mode == "redemption":
        end, window = parse_window(start, getattr(args, "until", None),
                                   (getattr(args, "window_minutes", None) if getattr(args, "window_minutes", None) is not None else retry_settings["irregular_window_minutes"]))
    elif getattr(args, "until", None) or getattr(args, "window_minutes", None):
        raise Abort("只有不定时抢购模式可以设置结束时间或窗口。")
    retry_settings['cold_start_minutes'] = args.prep_minutes
    if mode == 'redemption':
        retry_settings['irregular_window_minutes'] = window
    keychain_store.load()   # validates credentials exist; values are not kept
    if not notify.configured():
        print("邮件未配置：通知只写日志，用 status 查看。")
    if not (emulator_running() and booted()):
        raise Abort("模拟器没有在运行；先 ./scripts/project start。")
    if "AC Power" not in subprocess.run(["pmset", "-g", "batt"], capture_output=True,
                                        text=True).stdout:
        print("提醒：Mac 当前没有接电源。caffeinate 在电池供电时不能阻止合盖睡眠。")
    adb("shell", "am", "force-stop", PACKAGE)   # app stays closed overnight

    STATE.mkdir(parents=True, exist_ok=True)
    task = {"code": args.code, "amount": amount, "at": when.isoformat(),
            "fire_at": start.isoformat(), "dry_run": args.dry_run,
            "purchase_flow": query_gate.FLOW, "watch_settings": retry_settings,
            "prep_minutes": args.prep_minutes, "version": 2, "mode": mode,
            "task_id": uuid.uuid4().hex, "generation": uuid.uuid4().hex,
            "armed_at": datetime.now().isoformat(timespec="microseconds"),
            "last_tick": datetime.now().isoformat(), "resumes": [],
            "phase": "armed", "patterns_sent": 0}
    if mode == "redemption":
        task.update(end_at=end.isoformat(), window_minutes=window)
    else:
        task['form_deadline'] = retry_settings['reopen_deadline']
        task['end_at'] = query_end.isoformat()
    save_task(task)
    spawn_watch(task)
    action = "演练（只到密码页，不提交）" if args.dry_run else "真实提交一次"
    if mode == "redemption":
        print(f"已布防不定时抢购：{args.code} {amount} 元，{when:%m-%d %H:%M:%S} 起 "
              f"{window} 分钟窗口内反复打开购买页，有额度就{action}。招行 App 已关闭。")
    else:
        print(f"已布防：{args.code} {amount} 元，开售 {when:%m-%d %H:%M:%S}，"
              f"{retry_settings['first_offset_ms']}ms 后开始查询，最多再重试 "
              f"{retry_settings['first_max_retries']} 次，{action}。招行 App 已关闭。")
    print(f"日志：{LOG}")
    return task


def disarm(_args):
    return disarm_task()


def disarm_task():
    with task_lock(False):
        return _disarm()


def _disarm():
    task = load_task()
    if not task:
        print("没有值守任务。")
        return
    if task.get("phase") == "firing":
        raise Abort("正在提交，不能取消；请等结果并查交易记录。")
    page_open = task.get("phase") in PAGE_PHASES
    stop_watch(task)
    task["phase"] = "disarmed"
    save_task(task)
    record_history(task)
    if page_open:
        close_bank_app()
    print("已取消值守。")
    return task


# Phases in which the worker may have the bank app, login or purchase page open.
PAGE_PHASES = ("preparing", "waiting")


def close_bank_app():
    """Close the bank app so the purchase page stops its in-page queryBuy loop.

    Killing the worker skips its CDP cleanup; without this the page would keep
    querying until its watcher lease expires.
    """
    try:
        if emulator_running():
            adb("shell", "am", "force-stop", PACKAGE, timeout=10)
            print("已关闭招行 App，购买页轮询已停止。")
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"关闭招行 App 失败（{exc.__class__.__name__}）；购买页最多 "
              f"{query_gate.LEASE_MS // 1000} 秒后因失去值守自行停止。")


def status(_args):
    task = load_task()
    if not task:
        print("没有值守任务。")
        return
    running = alive(task.get("pid"))
    if task.get("mode") == "redemption":
        end = task.get("end_at", "")
        print(f"任务：不定时抢购 {task['code']} {task['amount']} 元，"
              f"{task['at']} 起 {task.get('window_minutes', DEFAULT_WINDOW_MINUTES)} 分钟窗口"
              f"（结束 {end[11:19]}）{'（演练）' if task.get('dry_run') else ''}")
    else:
        print(f"任务：首发 {task['code']} {task['amount']} 元，开售 {task['at']}"
              f"{'（演练）' if task.get('dry_run') else ''}")
    print(f"阶段：{task.get('phase')}；进程：{'运行中' if running else '未运行'}；"
          f"已输入图案 {task.get('patterns_sent', 0)} 次")
    if LOG.exists():
        print("最近日志：")
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]:
            print("  " + line)


# ---------------------------------------------------------------- device checks

def adb(*args, timeout=20):
    return subprocess.run(secure_input.BASE + list(args), text=True, capture_output=True,
                          timeout=timeout, check=True).stdout


def booted():
    try:
        return adb("shell", "getprop", "sys.boot_completed", timeout=10).strip() == "1"
    except (subprocess.SubprocessError, OSError):
        return False


def emulator_running():
    state = manage.load()
    item = state.get("emulator", {})
    return manage.owned(item.get("pid", -1), item.get("tokens", ["__missing__"]))


def restart_emulator():
    log("重启模拟器")
    manage.stop()
    manage.start()
    end = time.monotonic() + 300
    while time.monotonic() < end:
        if booted():
            time.sleep(10)
            keep_screen_on()
            return
        time.sleep(5)
    raise Abort("模拟器重启后 5 分钟仍未开机。")


def keep_screen_on():
    """stay_on and simulated AC power do not survive an emulator restart."""
    adb("shell", "settings", "put", "global", "stay_on_while_plugged_in", "15")
    adb("shell", "dumpsys", "battery", "set", "ac", "1")
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")


def ensure_emulator(strikes):
    """Restart only after repeated failures; a single slow adb call is common."""
    if emulator_running() and booted():
        strikes[0] = 0
        return
    strikes[0] += 1
    log(f"模拟器检查失败（第 {strikes[0]} 次）")
    if strikes[0] >= 3:
        restart_emulator()
        strikes[0] = 0
        alert("模拟器已自动重启", "App 本来就是关闭状态，开售前 15 分钟照常登录。")


def ensure_awake():
    power = adb("shell", "dumpsys", "power")
    if "mWakefulness=Awake" not in power:
        log("屏幕不是 Awake，发送唤醒")
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")


# ---------------------------------------------------------------- login

def read_screen():
    """UI tree via UiAutomator2, falling back to `uiautomator dump`.

    The system dump waits for the page to go idle and fails with "could not
    get idle state" on pages with endless animations (我的 does this), which
    is why 首页 → 理财 failed in the 22:47 rehearsal. uia2 has no such wait.
    """
    try:
        import fast_buy_uia2
        return fast_buy_uia2.dump()
    except Exception:
        return secure_input.screen()


def tap_text(label, timeout):
    """Tap the node whose text or description is exactly `label`."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            root = read_screen()
        except Exception:
            root = None
        for node in (root.iter("node") if root is not None else ()):
            if label in ((node.get("text") or "").strip(), (node.get("content-desc") or "").strip()):
                x, y = secure_input.center(node.get("bounds"))
                adb("shell", "input", "tap", str(x), str(y))
                return True
        time.sleep(1)
    return False


def cold_start():
    adb("shell", "am", "force-stop", PACKAGE)
    time.sleep(1)
    adb("shell", "monkey", "-p", PACKAGE, "-c", "android.intent.category.LAUNCHER", "1")
    if not tap_text("我的", timeout=40):
        raise RuntimeError("冷启动后 40 秒内没有找到“我的”。")
    time.sleep(3)


def on_login_page():
    try:
        root = read_screen()
        return (secure_input.has(root, "我的头像") and secure_input.has(root, "更多选项")
                and secure_input.screen_protected())
    except Exception:
        return False


def logged_in():
    """On 我的: a normal (unblanked) screenshot means logged in."""
    try:
        return not secure_input.screen_protected()
    except (RuntimeError, subprocess.SubprocessError, OSError):
        return False


def login_fresh(task):
    """Cold start, open 我的, pattern login. Force-stop and retry on failure.

    patterns_sent is saved before each attempt, so a crash or restart can
    never push the total past LOGIN_TRIES.
    """
    for cycle in range(1, LOGIN_CYCLES + 1):
        try:
            cold_start()
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            log(f"第 {cycle} 次冷启动失败：{exc}")
            continue
        if logged_in():
            log("“我的”可正常截图，已登录")
            return
        if not on_login_page():
            log(f"第 {cycle} 次：既不是登录页也不是已登录，重启 App")
            continue
        if task.get("patterns_sent", 0) >= LOGIN_TRIES:
            raise Abort(f"已输入图案 {LOGIN_TRIES} 次仍未登录，为避免锁定不再尝试。")
        # Read the tree here with uia2, before counting an attempt. login()'s
        # own `uiautomator dump` fails once uia2 is running (23:18 rehearsal:
        # three attempts burned, no gesture ever drawn).
        try:
            root = read_screen()
        except Exception as exc:
            log(f"第 {cycle} 次：读不到登录页控件，重启 App：{exc}")
            continue
        task["patterns_sent"] = task.get("patterns_sent", 0) + 1
        persist(task)
        log(f"输入图案（第 {task['patterns_sent']}/{LOGIN_TRIES} 次）")
        pattern = keychain_store.load().get("login_pattern")
        try:
            secure_input.login(pattern, root=root)
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            log(f"图案输入异常：{exc}")
        finally:
            pattern = None
        time.sleep(6)
        if logged_in() and not on_login_page():
            alert(f"登录成功（第 {task['patterns_sent']} 次图案）")
            return
        log("图案后仍未登录，重启 App 再试")
    raise Abort(f"冷启动 {LOGIN_CYCLES} 次仍未登录。")


# ---------------------------------------------------------------- detail page

def webview_pages():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3) as r:
            return json.load(r)
    except (OSError, ValueError):
        return []


def describe(page):
    try:
        return json.loads(page.get("description") or "{}")
    except ValueError:
        return {}


def is_visible(page):
    return bool(describe(page).get("visible"))


def is_full_screen(page):
    """CDP's `visible` is also true for WebViews embedded in hidden tabs; a
    full-screen H5 page is the visible, non-empty one starting at screenY 0.
    Size matters too: the 客户经理 chat leaves 228x305 card WebViews that are
    visible at screenY 0 and would otherwise swallow the jump."""
    d = describe(page)
    return (bool(d.get("visible")) and not d.get("empty") and d.get("screenY") == 0
            and (d.get("width") or 0) >= 300 and (d.get("height") or 0) >= 500)


def detail_open(code, full=True):
    return any((is_full_screen(p) if full else is_visible(p))
               and "financedetail" in (p.get("url") or "")
               and f"XRIPINN={code}" in (p.get("url") or "") for p in webview_pages())


def jump(page, code, full, timeout):
    import buy_timed
    url = buy_timed.DETAIL_URL.format(code=code)
    buy_timed.js_eval_page(page, "location.href=" + json.dumps(url) + "; 'go'")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if detail_open(code, full):
            return True
        time.sleep(0.3)
    return False


def wait_full_screen(timeout):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        pages = [p for p in webview_pages() if is_full_screen(p)]
        if pages:
            return pages[0]
        time.sleep(0.5)
    return None


app_link = fast_buy.app_link


def open_by_link(code, timeout=20.0):
    import buy_timed
    adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
        "-d", "'" + app_link(buy_timed.DETAIL_URL.format(code=code)) + "'", PACKAGE)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if detail_open(code):
            return True
        time.sleep(0.5)
    return False


def open_detail(code, timeout=15.0):
    """Open the detail page full-screen; the buy button state does not matter.

    First choice is the app's deep link: the app opens the page in its own
    new WebView, exactly like a shared link (verified 2026-11-02, ~9s). If
    that fails, tap 首页 → 理财 to get a full-screen H5 page and jump inside
    it. Last resort is jumping a WebView embedded in 首页: the page stays
    off-screen, but goBuy() from it still opens the purchase form.
    """
    fast_buy.ensure_forward()
    if detail_open(code):
        return
    if open_by_link(code):
        log("详情页已通过 App 链接打开")
        return
    log("App 链接没有打开详情页，改走 首页 → 理财")
    page = wait_full_screen(1)
    if page is None and tap_text("首页", timeout=5):
        time.sleep(2)
        if tap_text("理财", timeout=5):
            page = wait_full_screen(10)
    if page is not None and jump(page, code, True, timeout):
        log("详情页已全屏打开")
        return
    log("全屏打开失败，改为在内嵌 WebView 里直跳")
    pages = webview_pages()
    targets = [p for p in pages if is_visible(p)] or [p for p in pages if p.get("type") == "page"]
    if not targets:
        raise RuntimeError("没有可用的 WebView，无法直跳详情页。")
    if not jump(targets[-1], code, False, timeout):
        raise RuntimeError("直跳后详情页没有出现。")


# ---------------------------------------------------------------- the night

def prepare(task, strikes, done):
    """`done` remembers a successful login across retries: if only the detail
    jump failed, retry it without a cold start that would log out again."""
    ensure_emulator(strikes)
    ensure_awake()
    if not (done.get("login") and adb("shell", "pidof", PACKAGE).strip()):
        if task.get("after_manual_login"):
            if not tap_text("我的", timeout=10) or not logged_in() or on_login_page():
                raise Abort("手动登录状态未确认，不输入图案。")
        else:
            login_fresh(task)
        done["login"] = True
    if task.get("purchase_flow") == query_gate.FLOW:
        return  # the gated purchase page is opened immediately after login
    # The purchase form now opens straight from the app link at sale time, so
    # the detail page is only a warm-up (session, network); never fail on it.
    try:
        open_detail(task["code"])
    except Exception as exc:
        log(f"详情页没有打开（不影响开售时直接打开购买页）：{exc}")


def fire(task, when):
    import fast_buy_uia2
    task["phase"] = "firing"
    task["fired_at"] = datetime.now().isoformat()
    persist(task)   # before run(): a restarted watcher must never submit again
    log("交给 fast_buy_uia2.run()")
    try:
        result = fast_buy_uia2.run(task["code"], task["amount"], at=when,
                                   dry_run=task.get("dry_run", False),
                                   form_deadline=task.get('form_deadline', purchase_settings.DEFAULTS['reopen_deadline']))
    except Exception as exc:
        task["phase"] = "done"
        task["result"] = f"停止：{exc}"
        persist(task)
        alert("购买流程中途停止", f"{exc}\n\n若已出现提交动作，请先查交易记录，不要重试。")
        return
    task["phase"] = "done"
    if task.get("dry_run"):
        task["result"] = "演练完成"
        persist(task)
        fast_buy_uia2.close_password_panel()
        alert("演练完成：已到密码页，未输入密码、未提交")
        return
    task["result"] = result or "结果未知"
    persist(task)
    if result in ("提交成功", "购买成功", "交易委托已接受"):
        alert(f"已提交：{result}", "以银行交易记录和产品管理机构确认为准。")
    else:
        alert(f"结果需要人工确认：{task['result']}", "请查交易记录，不要重复提交。")


def redemption_fire(task, start):
    """Keep reopening the purchase page until the form shows up, then buy once.

    "Sold out" is not an error here: the app answers the buy link with
    `额度不足`, which is exactly the state this mode waits out. Nothing is
    submitted until the form appears and the amount checks out; the firing
    marker is written at that point, never later.
    """
    import fast_buy_uia2
    end = datetime.fromisoformat(task["end_at"])
    sleep_until(start, 2, task)
    task["phase"] = "waiting"
    persist(task)
    window = max(1.0, (end - datetime.now()).total_seconds())
    log(f"不定时抢购窗口开始：最多 {window:.0f} 秒内反复打开购买页")
    alert("不定时抢购窗口开始",
          f"{task['code']} {task['amount']} 元，最多 {window:.0f} 秒；有额度才提交。")

    def tick(opens):
        task["last_tick"] = datetime.now().isoformat()
        task["probes"] = opens
        persist(task)

    def before_submit():
        task["phase"] = "firing"
        task["fired_at"] = datetime.now().isoformat()
        persist(task)   # a restarted watcher must never submit again
        log("购买表单已出现，进入提交")

    try:
        result = fast_buy_uia2.run(
            task["code"], task["amount"], at=None, dry_run=task.get("dry_run", False),
            form_deadline=window, form_wait=REDEEM_WAIT, form_gap=REDEEM_GAP,
            before_submit=None if task.get("dry_run") else before_submit, tick=tick)
    except Exception as exc:
        task["phase"] = "done"
        if task.get("fired_at"):
            task["result"] = f"结果未知：{exc}"
            persist(task)
            alert("提交后异常，结果需要人工确认", "先查交易记录，不要重试。")
        else:
            task["result"] = f"窗口内没有买到：{exc}"
            persist(task)
            alert("不定时抢购结束：窗口内没有买到", f"{exc}\n\n没有提交任何交易。")
        return
    task["phase"] = "done"
    if task.get("dry_run"):
        task["result"] = "演练完成"
        persist(task)
        fast_buy_uia2.close_password_panel()
        alert("演练完成：已到密码页，未输入密码、未提交")
        return
    task["result"] = result or "结果未知"
    persist(task)
    if result in ("提交成功", "购买成功", "交易委托已接受"):
        alert(f"已提交：{result}", "以银行交易记录和产品管理机构确认为准。")
    else:
        alert(f"结果需要人工确认：{task['result']}", "请查交易记录，不要重复提交。")


def gated_fire(task):
    """Open once before release; persist the firing marker only after checks."""
    import fast_buy_uia2

    def heartbeat(attempts):
        previous = task.get('probes', 0)
        task['last_tick'] = datetime.now().isoformat()
        task['probes'] = attempts
        persist(task)
        if previous != attempts:
            log(f"queryBuy 累计查询 {attempts} 次")

    def prepared():
        task['phase'] = 'waiting'
        persist(task)
        # SMTP can block for 20 seconds; never let it expire the page lease.
        threading.Thread(target=alert, args=(
            '购买页已就绪，queryBuy 已挂起',
            f"首个查询计划时间：{task['fire_at']}；等待期间不发查询。"), daemon=True).start()

    def before_submit():
        task['phase'] = 'firing'
        task['fired_at'] = datetime.now().isoformat()
        persist(task)
        log('本次购买表单已校验，进入单次购买流程')

    try:
        root, quota = query_gate.run(task, heartbeat, prepared)
        result = fast_buy_uia2.run(task['code'], task['amount'],
                                  dry_run=task.get('dry_run', False),
                                  prepared_form=root, product_quota=quota,
                                  verify_form=lambda: query_gate.verify_prepared(task),
                                  before_submit=None if task.get('dry_run') else before_submit)
        task['phase'] = 'done'
        task['result'] = '演练完成' if task.get('dry_run') else (result or '结果未知')
        persist(task)
        if task.get('dry_run'):
            fast_buy_uia2.close_password_panel()
        alert(task['result'], '以银行交易记录为准；不要重复提交。' if task.get('fired_at')
              else '未输入密码、未提交。')
    except Exception as exc:
        task['phase'] = 'done'
        task['result'] = (f'结果未知：{exc}' if task.get('fired_at') else f'未提交：{exc}')
        persist(task)
        alert('结果需要人工确认' if task.get('fired_at') else '值守停止，未提交', task['result'])
    finally:
        query_gate.finish(task)


def sleep_until(when, step, task=None):
    while True:
        if task is not None:
            task["last_tick"] = datetime.now().isoformat()
            persist(task)
        left = (when - datetime.now()).total_seconds()
        if left <= 0:
            return
        time.sleep(min(left, step))


def run(_args):
    with task_lock():
        task = load_task()
        generation = getattr(_args, "generation", None)
        if task and task.get("version") == 2 and generation != task.get("generation"):
            raise Abort("值守代次不匹配，请通过 arm 或 resume 启动。")
    if not task or task.get("phase") != "armed":
        log(f"任务阶段为 {task and task.get('phase')}，不运行")
        return
    sale = datetime.fromisoformat(task["at"])
    fire_at = datetime.fromisoformat(task["fire_at"])
    prep_lead = timedelta(minutes=task.get("prep_minutes", PREP_MINUTES if task.get("purchase_flow") else 15))
    strikes = [0]
    action = "演练" if task.get("dry_run") else "真实提交一次"
    if task.get("mode") == "redemption":
        alert(f"不定时抢购已开始：{task['code']} {task['amount']} 元，"
              f"{sale:%m-%d %H:%M:%S} 起 {task.get('window_minutes', DEFAULT_WINDOW_MINUTES)} "
              f"分钟窗口（{action}）")
    else:
        alert(f"值守已开始：{task['code']} {task['amount']} 元，开售 {sale:%m-%d %H:%M:%S}（{action}）")
    try:
        reported = None
        while datetime.now() < sale - prep_lead:
            try:
                ensure_emulator(strikes)
                ensure_awake()
                reported = None
            except Exception as exc:   # keep watching; mail each new problem once
                log(f"夜间检查异常：{exc}")
                if str(exc) != reported:
                    reported = str(exc)
                    alert("夜间检查异常，继续值守", f"{type(exc).__name__}: {exc}")
            sleep_until(min(sale - prep_lead, datetime.now() + timedelta(seconds=HEALTH_EVERY)),
                        HEALTH_EVERY, task)

        log("开始准备：冷启动并登录")
        task["phase"] = "preparing"
        persist(task)
        last = None
        done = {}
        prepare_until = fire_at - timedelta(seconds=2) if task.get('purchase_flow') == query_gate.FLOW else sale - FINAL_LEAD
        while datetime.now() < prepare_until:
            task["last_tick"] = datetime.now().isoformat()
            persist(task)
            try:
                prepare(task, strikes, done)
                break
            except Abort:
                raise
            except Exception as exc:   # transient: page not loaded, adb hiccup
                last = exc
                log(f"准备失败，稍后重试：{exc}")
                time.sleep(20)
        else:
            raise Abort(f"准备阶段一直没有成功：{last}")
        if task.get('purchase_flow') == query_gate.FLOW:
            gated_fire(task)
            return
        if task.get("mode") == "redemption":
            alert("准备完成：已登录", f"{task['code']}，{sale:%H:%M:%S} 开始反复打开购买页。")
        else:
            alert("准备完成：已登录",
                  f"{task['code']}，{fire_at:%H:%M:%S.%f}"[:-3] + " 进入购买页。")

        sleep_until(sale - FINAL_LEAD, 5, task)
        # Look only, never login or tap: the buy step opens the form from the
        # app link and stops on its own if the form never shows up.
        if not adb("shell", "pidof", PACKAGE).strip():
            log("最后检查：招行 App 不在运行，到点仍会尝试打开购买页")
        if task.get("mode") == "redemption":
            redemption_fire(task, sale)
        else:
            fire(task, fire_at)
    except Exception as exc:
        if task.get("phase") != "firing":
            task["phase"] = "aborted"
            task["result"] = str(exc)
            persist(task)
        alert("值守中止，未提交", f"{type(exc).__name__}: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser(description="夜间值守：开售前登录，到点提交一次购买")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("arm", help="睡前布防")
    p.add_argument("--code", required=True)
    p.add_argument("--amount", required=True)
    when = p.add_mutually_exclusive_group(required=True)
    when.add_argument("--at", help="开售时间（首发）或额度放出时间（不定时抢购）"
                                  "YYYY-MM-DDTHH:MM:SS（本机时间）")
    when.add_argument("--now", action="store_true",
                      help=f"排练：立即冷启动登录，{NOW_LEAD.seconds // 60} 分钟后开售/开始窗口")
    p.add_argument("--dry-run", action="store_true", help="演练：只到密码页，不输密码、不提交")
    p.add_argument("--settings-revision", help=argparse.SUPPRESS)
    p.add_argument("--prep-minutes", type=int,
                   help="开始前几分钟冷启动登录（1–60，默认使用设置，初始 7 分钟）")
    p.add_argument("--mode", choices=MODES, default="first_launch",
                   help="first_launch 首发（默认）或 redemption 不定时抢购")
    p.add_argument("--window-minutes", type=int,
                   help=f"不定时抢购窗口分钟数（默认 {DEFAULT_WINDOW_MINUTES}，最长 {MAX_WINDOW_MINUTES}）")
    p.add_argument("--until", help="不定时抢购结束时间 YYYY-MM-DDTHH:MM:SS，优先于 --window-minutes")
    sub.add_parser("status")
    sub.add_parser("disarm")
    worker = sub.add_parser("run", help="由 arm 在后台启动，不要手动运行")
    worker.add_argument("--generation")
    recovery = sub.add_parser("resume")
    recovery.add_argument("--reason", required=True)
    recovery.add_argument("--kill-stale", action="store_true")
    recovery.add_argument("--after-manual-login", action="store_true")
    args = parser.parse_args()
    {"arm": arm, "status": status, "disarm": disarm, "run": run,
     "resume": lambda a: resume_task(a.reason, kill_stale=a.kill_stale,
                                     after_manual_login=a.after_manual_login)}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except (Abort, fast_buy.Stop, RuntimeError, OSError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
