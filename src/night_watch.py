#!/usr/bin/env python3
"""Overnight watch: keep the emulator healthy with the bank app closed, log in
fresh shortly before the sale, open the detail page, then submit exactly one
purchase through fast_buy_uia2.run().

The account holder arms it in their own terminal before bed:

    python3 -B src/night_watch.py arm --code 133045A --amount 0.01 \
        --at 2026-11-03T09:00:00 [--dry-run]

`--at` is the sale time; goBuy() fires OPEN_DELAY after it. `arm` closes the
app and starts a detached `caffeinate -dimsu ... night_watch.py run`, so the
Mac stays awake exactly as long as the watch runs. `status` and `disarm`
inspect or cancel it. Alerts go out by email (see notify.py).

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
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
STATE = ROOT / "var" / "night"
TASK = STATE / "task.json"
LOG = STATE / "watch.log"
PACKAGE = "cmb.pb"

PREP_MINUTES = 15                    # cold start + login + detail page
MIN_PREP_MINUTES = 5                 # shorter only for quick rehearsals
FINAL_LEAD = timedelta(seconds=60)   # last page check, then hand off to run()
OPEN_DELAY = timedelta(milliseconds=200)
ARM_SLACK = timedelta(minutes=2)     # arm at least prep + 2 min before the sale
NOW_LEAD = timedelta(minutes=3)      # `arm --now`: sale this far out, prep starts at once
MAX_LEAD = timedelta(hours=24)
HEALTH_EVERY = 120                   # seconds between overnight checks
LOGIN_TRIES = 3                      # patterns actually sent; stays clear of lockout
LOGIN_CYCLES = 5                     # cold starts, including ones with no login page

import fast_buy
import keychain_store
import manage
import notify
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


def save_task(task):
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = TASK.with_suffix(".tmp")
    tmp.write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, TASK)


def alive(pid):
    try:
        os.kill(pid, 0)
    except (OSError, TypeError):
        return False
    return True


def parse_target(value, now=None, prep_minutes=PREP_MINUTES):
    if "T" not in value:
        raise Abort("值守必须写完整时间，例如 2026-11-03T09:00:00。")
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise Abort("时间格式应为 YYYY-MM-DDTHH:MM:SS。")
    if when.tzinfo is not None:
        raise Abort("请使用本机本地时间，不要带时区。")
    if not MIN_PREP_MINUTES <= prep_minutes <= PREP_MINUTES:
        raise Abort(f"准备提前量只能是 {MIN_PREP_MINUTES}–{PREP_MINUTES} 分钟。")
    lead = when - (now or datetime.now())
    min_lead = timedelta(minutes=prep_minutes) + ARM_SLACK
    if lead < min_lead:
        raise Abort(f"开售时间至少要在 {min_lead.seconds // 60} 分钟之后，留给登录和打开详情页。")
    if lead > MAX_LEAD:
        raise Abort("开售时间不能超过 24 小时之后。")
    return when


# ---------------------------------------------------------------- arm / disarm

def arm(args):
    task = load_task()
    if task and alive(task.get("pid")):
        raise Abort("已有值守在运行；先 status 查看或 disarm 取消。")
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise Abort("产品代码格式不正确。")
    amount = fast_buy.parse_amount(args.amount)
    if args.now:
        # Rehearsal: preparation starts at once (the sale is already inside
        # the prep window) and leaves ~2 min before the last-minute check.
        when = datetime.now().replace(microsecond=0) + NOW_LEAD
    else:
        when = parse_target(args.at, prep_minutes=args.prep_minutes)
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
    save_task({"code": args.code, "amount": amount, "at": when.isoformat(),
               "fire_at": (when + OPEN_DELAY).isoformat(), "dry_run": args.dry_run,
               "prep_minutes": args.prep_minutes,
               "armed_at": datetime.now().isoformat(timespec="seconds"),
               "phase": "armed", "patterns_sent": 0})
    with LOG.open("ab") as out:
        proc = subprocess.Popen(["caffeinate", "-dimsu", sys.executable, "-B",
                                 str(Path(__file__).resolve()), "run"],
                                stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                                cwd=ROOT, start_new_session=True)
    task = load_task()
    task["pid"] = proc.pid
    save_task(task)
    mode = "演练（只到密码页，不提交）" if args.dry_run else "真实提交一次"
    print(f"已布防：{args.code} {amount} 元，开售 {when:%m-%d %H:%M:%S}，"
          f"{OPEN_DELAY.microseconds // 1000}ms 后进入购买页，{mode}。招行 App 已关闭。")
    print(f"日志：{LOG}")


def disarm(_args):
    task = load_task()
    if not task:
        print("没有值守任务。")
        return
    if task.get("phase") == "firing":
        raise Abort("正在提交，不能取消；请等结果并查交易记录。")
    pid = task.get("pid")
    if alive(pid):
        os.killpg(pid, signal.SIGTERM)
    task["phase"] = "disarmed"
    save_task(task)
    print("已取消值守。")


def status(_args):
    task = load_task()
    if not task:
        print("没有值守任务。")
        return
    running = alive(task.get("pid"))
    print(f"任务：{task['code']} {task['amount']} 元，开售 {task['at']}"
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
        save_task(task)
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
        login_fresh(task)
        done["login"] = True
    # The purchase form now opens straight from the app link at sale time, so
    # the detail page is only a warm-up (session, network); never fail on it.
    try:
        open_detail(task["code"])
    except Exception as exc:
        log(f"详情页没有打开（不影响开售时直接打开购买页）：{exc}")


def fire(task, when):
    import fast_buy_uia2
    task["phase"] = "firing"
    save_task(task)   # before run(): a restarted watcher must never submit again
    log("交给 fast_buy_uia2.run()")
    try:
        result = fast_buy_uia2.run(task["code"], task["amount"], at=when,
                                   dry_run=task.get("dry_run", False))
    except Exception as exc:
        task["phase"] = "done"
        task["result"] = f"停止：{exc}"
        save_task(task)
        alert("购买流程中途停止", f"{exc}\n\n若已出现提交动作，请先查交易记录，不要重试。")
        return
    task["phase"] = "done"
    if task.get("dry_run"):
        task["result"] = "演练完成"
        save_task(task)
        fast_buy_uia2.close_password_panel()
        alert("演练完成：已到密码页，未输入密码、未提交")
        return
    task["result"] = result or "结果未知"
    save_task(task)
    if result in ("提交成功", "购买成功", "交易委托已接受"):
        alert(f"已提交：{result}", "以银行交易记录和产品管理机构确认为准。")
    else:
        alert(f"结果需要人工确认：{task['result']}", "请查交易记录，不要重复提交。")


def sleep_until(when, step):
    while True:
        left = (when - datetime.now()).total_seconds()
        if left <= 0:
            return
        time.sleep(min(left, step))


def run(_args):
    task = load_task()
    if not task or task.get("phase") != "armed":
        log(f"任务阶段为 {task and task.get('phase')}，不运行")
        return
    sale = datetime.fromisoformat(task["at"])
    fire_at = datetime.fromisoformat(task["fire_at"])
    prep_lead = timedelta(minutes=task.get("prep_minutes", PREP_MINUTES))
    strikes = [0]
    mode = "演练" if task.get("dry_run") else "真实提交一次"
    alert(f"值守已开始：{task['code']} {task['amount']} 元，开售 {sale:%m-%d %H:%M:%S}（{mode}）")
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
                        HEALTH_EVERY)

        log("开始准备：冷启动并登录")
        task["phase"] = "preparing"
        save_task(task)
        last = None
        done = {}
        while datetime.now() < sale - FINAL_LEAD:
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
        alert("准备完成：已登录", f"{task['code']}，{fire_at:%H:%M:%S.%f}"[:-3] + " 进入购买页。")

        sleep_until(sale - FINAL_LEAD, 5)
        # Look only, never login or tap: fire() opens the form from the app
        # link and stops on its own if the form never shows up.
        if not adb("shell", "pidof", PACKAGE).strip():
            log("最后检查：招行 App 不在运行，开售时仍会尝试打开购买页")
        fire(task, fire_at)
    except Exception as exc:
        if task.get("phase") != "firing":
            task["phase"] = "aborted"
            task["result"] = str(exc)
            save_task(task)
        alert("值守中止，未提交", f"{type(exc).__name__}: {exc}")
        raise


def main():
    parser = argparse.ArgumentParser(description="夜间值守：开售前登录，到点提交一次购买")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("arm", help="睡前布防")
    p.add_argument("--code", required=True)
    p.add_argument("--amount", required=True)
    when = p.add_mutually_exclusive_group(required=True)
    when.add_argument("--at", help="开售时间 YYYY-MM-DDTHH:MM:SS（本机时间）")
    when.add_argument("--now", action="store_true",
                      help=f"排练：立即冷启动登录，{NOW_LEAD.seconds // 60} 分钟后提交")
    p.add_argument("--dry-run", action="store_true", help="演练：只到密码页，不输密码、不提交")
    p.add_argument("--prep-minutes", type=int, default=PREP_MINUTES,
                   help=f"开售前几分钟开始冷启动登录（{MIN_PREP_MINUTES}–{PREP_MINUTES}，默认 {PREP_MINUTES}）")
    sub.add_parser("status")
    sub.add_parser("disarm")
    sub.add_parser("run", help="由 arm 在后台启动，不要手动运行")
    args = parser.parse_args()
    {"arm": arm, "status": status, "disarm": disarm, "run": run}[args.cmd](args)


if __name__ == "__main__":
    try:
        main()
    except (Abort, fast_buy.Stop, RuntimeError, OSError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
