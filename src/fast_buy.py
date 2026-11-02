#!/usr/bin/env python3
"""One-shot fast purchase from an already-open product detail page.

This is the time-critical path only. Preparation (login, search, opening the
product detail page) is done separately and verified by the agent. The security
keyboard layout is fixed on this emulator, so the fast path uses fixed key
coordinates and avoids the ~2s accessibility dump. Use --read-keys to read the
keyboard from the UI tree instead, or --dry-run to stop before submitting.
The script submits exactly once and never retries.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import keychain_store
from secure_input import adb, center, has, screen, screencap_raw, send_commands

# Coordinates confirmed on the 320x640 emulator.
PRODUCT_ROW = (145, 441)
DETAIL_BUY = (208, 561)
FORM_AMOUNT = (140, 392)
FORM_NEXT = (160, 552)
RISK_FILL = (80, 467)
RISK_CONFIRM = (160, 557)
KEY_DONE = (294, 357)
KEY_SUBMIT = (160, 310)

# Fixed security-keyboard positions, confirmed by the account owner.
PASSWORD_KEYS = {
    "1": (54, 402), "2": (159, 402), "3": (265, 402),
    "4": (54, 456), "5": (159, 456), "6": (265, 456),
    "7": (54, 510), "8": (159, 510), "9": (265, 510),
    "0": (159, 564),
}

BALANCE_TEMPLATE = Path(__file__).with_name("templates") / "balance_label.json"


class Stop(Exception):
    pass


def tap(xy):
    adb("shell", "input", "tap", str(xy[0]), str(xy[1]))


def load_balance_template():
    obj = json.loads(BALANCE_TEMPLATE.read_text())
    return obj, base64.b64decode(obj["data_b64"])


def balance_region(frame, obj, dx=0, dy=0):
    header = obj["header"]
    frame_width = obj["frame_width"]
    if len(frame) < header + frame_width * obj["frame_height"] * 4:
        return None
    out = bytearray()
    for row in range(obj["h"]):
        offset = header + ((obj["y"] + dy + row) * frame_width + obj["x"] + dx) * 4
        out += frame[offset:offset + obj["w"] * 4]
    return bytes(out)


def balance_diff(frame, obj, template):
    best = 255.0
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            region = balance_region(frame, obj, dx, dy)
            if region is None:
                continue
            diff = mean_diff(region, template)
            if diff < best:
                best = diff
    return best


def mean_diff(a, b):
    if len(a) != len(b) or not a:
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def wait_balance(timeout=3.0, threshold=12.0):
    """Wait for the purchase form's 可用余额 row using a small raw template."""
    obj, template = load_balance_template()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        frame = screencap_raw()
        if balance_diff(frame, obj, template) < threshold:
            return
        time.sleep(0.05)
    raise Stop("购买表单的可用余额没有加载，未继续。")


def red_button_visible(frame):
    """Fast check for the detail page's red 购买 button."""
    if len(frame) < 16 + 320 * 640 * 4:
        return False
    count = 0
    for y in range(543, 580, 2):
        for x in range(110, 307, 2):
            offset = 16 + (y * 320 + x) * 4
            r, g, b = frame[offset], frame[offset + 1], frame[offset + 2]
            if r > 150 and g < 90 and b < 90:
                count += 1
    return count > 200


def wait_detail_button(timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if red_button_visible(screencap_raw()):
            return
        time.sleep(0.05)
    raise Stop("产品详情页没有加载，未继续。")


def ensure_forward():
    pids = adb("shell", "pidof", "cmb.pb").split()
    if not pids:
        raise Stop("找不到招行 App 进程。")
    adb("forward", "tcp:9222", f"localabstract:webview_devtools_remote_{pids[0]}")


def js_prefill_and_buy(amount, code, timeout=3.0):
    """Set CurDepositBuyAmount on the detail page and call goBuy()."""
    import asyncio
    import json as jsonlib
    import urllib.request
    from urllib.parse import urlparse, parse_qs
    import websockets

    end = time.monotonic() + timeout
    detail = None
    fallback = None
    while time.monotonic() < end:
        try:
            pages = jsonlib.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=1))
            for p in pages:
                url = p.get("url", "")
                if "financedetail.html" not in url:
                    continue
                query = parse_qs(urlparse(url).query)
                if (query.get("XRIPINN") or [""])[0] == code:
                    detail = p
                    break
                try:
                    if jsonlib.loads(p.get("description", "{}")).get("visible"):
                        fallback = p
                except Exception:
                    pass
            detail = detail or fallback
            if detail:
                break
        except Exception:
            pass
        time.sleep(0.05)
    if not detail:
        raise Stop("没有找到目标产品的详情页 WebView。")

    script = """
    (()=>{
      const app=document.querySelector('#app');
      const root=app && app.__vue__;
      let page=null;
      (function walk(v,d){
        if(!v||d>15||page) return;
        if(v.goBuyParam && typeof v.goBuy==='function') page=v;
        (v.$children||[]).forEach(c=>walk(c,d+1));
      })(root,0);
      if(!page) return 'no page';
      page.goBuyParam.CurDepositBuyAmount=__AMOUNT__;
      page.goBuy();
      return 'ok';
    })()
    """.replace("__AMOUNT__", jsonlib.dumps(amount))

    async def call():
        async with websockets.connect(detail["webSocketDebuggerUrl"], open_timeout=3) as ws:
            await ws.send(jsonlib.dumps({"id": 1, "method": "Runtime.evaluate",
                                         "params": {"expression": script, "returnByValue": True}}))
            while True:
                msg = jsonlib.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("result", {}).get("value")

    if asyncio.run(call()) != "ok":
        raise Stop("JS 预填金额失败。")


def parse_at(value):
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        try:
            t = datetime.strptime(value, "%H:%M:%S.%f").time()
        except ValueError:
            raise Stop("时间格式应为 HH:MM:SS.mmm 或 ISO 本地时间。")
        when = datetime.combine(datetime.now().date(), t)
    if when.tzinfo is not None:
        raise Stop("请使用本机本地时间，不要带时区。")
    if when <= datetime.now():
        raise Stop("目标时间已过；跨天请使用 YYYY-MM-DDTHH:MM:SS.mmm。")
    return when


def wait_until(when):
    while True:
        delay = (when - datetime.now()).total_seconds()
        if delay <= 0:
            return
        time.sleep(min(delay, 0.05))


def label(node):
    return (node.get("text") or "") + " " + (node.get("content-desc") or "")


def contains_code(root, code):
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])")
    return any(pattern.search(label(n)) for n in root.iter("node"))


def locate_unique(root, needle, exact=False):
    found = []
    for node in root.iter("node"):
        text = label(node).strip()
        if (text == needle if exact else needle in text):
            try:
                found.append(center(node.get("bounds")))
            except RuntimeError:
                continue
    found = list(dict.fromkeys(found))
    if len(found) != 1:
        raise Stop(f"页面控件无法唯一识别：{needle}")
    return found[0]


def read_password_page(code, amount, timeout=3.0):
    """Slow safety fallback: read the keyboard layout from the UI tree."""
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            root = screen()
        except (RuntimeError, subprocess.SubprocessError, ET.ParseError) as exc:
            last = exc
            time.sleep(0.15)
            continue
        if has(root, "请输入取款密码") and has(root, "招商银行安全输入"):
            if not any(("￥" + amount) in label(n) for n in root.iter("node")):
                raise Stop(f"密码页金额不是 ￥{amount}，已停止。")
            keys = {}
            for node in root.iter("node"):
                if node.get("class") != "android.widget.Button":
                    continue
                digit = (node.get("text") or "").strip()
                if re.fullmatch(r"[0-9]", digit):
                    if digit in keys:
                        raise Stop("数字键重复，无法确认键盘布局。")
                    keys[digit] = center(node.get("bounds"))
            if set(keys) != set("0123456789"):
                raise Stop("数字键不完整，无法输入。")
            return keys
        time.sleep(0.1)
    raise Stop("没有到达密码页，未提交。") from last


def run(code, amount, fast=False, read_keys=False, dry_run=False,
        form_wait=1.5, risk_wait=0.6, password_wait=0.05, at=None, from_results=False,
        js_prefill=False, preopened=False):
    credentials = keychain_store.load()
    password = credentials.get("payment_password")
    if not isinstance(password, str) or not re.fullmatch(r"[0-9]{6}", password):
        raise Stop("钥匙串中没有有效的交易密码。")

    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(0.2)
    if not fast:
        root = screen()
        if from_results and not preopened:
            if not (has(root, "手机银行搜索") and contains_code(root, code)):
                raise Stop("请先把产品搜索结果页打开，再运行本脚本。")
        elif not (has(root, "购买，点击可跳转") and contains_code(root, code)):
            raise Stop("请先把目标产品详情页打开，再运行本脚本。")

    if at is not None:
        wait_until(at)

    began = time.monotonic()
    js_used = False
    if preopened:
        ensure_forward()
        js_prefill_and_buy(amount, code)
        js_used = True
    else:
        if from_results:
            tap(PRODUCT_ROW)
            wait_detail_button()
            time.sleep(0.10)
        if js_prefill:
            try:
                ensure_forward()
                js_prefill_and_buy(amount, code)
                js_used = True
            except Exception:
                js_used = False
        if not js_used:
            tap(DETAIL_BUY)

    if BALANCE_TEMPLATE.exists():
        wait_balance(timeout=3.0)
    else:
        time.sleep(form_wait)

    if not js_used:
        # Tap the amount field, clear any retained value, type the amount, and
        # close the keyboard. One shell keeps the adb round-trips out of the path.
        send_commands([
            f"input tap {FORM_AMOUNT[0]} {FORM_AMOUNT[1]}",
            "sleep 0.20",
            "input keyevent KEYCODE_MOVE_END 67 67 67 67 67 67",
            f"input text {amount}",
            "sleep 0.20",
            "input keyevent KEYCODE_BACK",
        ])
        time.sleep(0.30)
    tap(FORM_NEXT)
    time.sleep(0.20)
    # Read the settled native dialog and click the actual nodes. The fixed
    # coordinate race could hit a document link and open a PDF viewer.
    root = screen()
    fill_xy = locate_unique(root, "一键输入")
    confirm_xy = locate_unique(root, "确认", exact=True)
    tap(fill_xy)
    time.sleep(0.30)
    tap(confirm_xy)

    # Verify that this really is the password page (and the amount) before
    # touching the keyboard. The black-frame check alone can mistake a PDF
    # viewer for the password page.
    keys = read_password_page(code, amount, timeout=3.0)
    time.sleep(password_wait)

    if dry_run:
        print(f"dry run：到密码页约 {time.monotonic() - began:.2f} 秒；"
              "未输入密码、未提交。", flush=True)
        return

    # Send the six digits back-to-back, then give the field time to commit all
    # six before "完成"/"确定". This is faster than per-digit sleeps and avoids
    # submitting while the last digit is still queued.
    commands = [f"input tap {keys[d][0]} {keys[d][1]}" for d in password]
    commands.extend(["sleep 0.45",
                     f"input tap {KEY_DONE[0]} {KEY_DONE[1]}",
                     "sleep 0.30",
                     f"input tap {KEY_SUBMIT[0]} {KEY_SUBMIT[1]}"])
    send_commands(commands)
    submitted = time.monotonic()
    print(f"已提交一次，核心流程约 {submitted - began:.2f} 秒；等待结果。", flush=True)

    time.sleep(1.0)
    try:
        result = read_result(timeout=20.0)
        print(f"结果页提示：{result}", flush=True)
    except Stop as exc:
        print(f"未能确认结果：{exc}。请立即到招行查询交易记录，不要重试。", flush=True)
    print("请以银行交易记录为准；不要重复提交。", flush=True)


def read_result(timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            root = screen()
        except (RuntimeError, subprocess.SubprocessError, ET.ParseError):
            time.sleep(0.2)
            continue
        text = " ".join(label(n) for n in root.iter("node"))
        for needle in ("提交成功", "申请失败", "密码错误", "购买成功"):
            if needle in text:
                return needle
        time.sleep(0.2)
    raise Stop("结果页没有出现可识别的提示")


def main():
    parser = argparse.ArgumentParser(description="产品详情页上的单次快速购买（实验）")
    parser.add_argument("--code", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--fast", action="store_true",
                        help="skip the preflight UI dump; the caller has confirmed the detail page")
    parser.add_argument("--read-keys", action="store_true",
                        help="read the security keyboard from the UI tree (slow, safe fallback)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run up to the password page but do not enter or submit anything")
    parser.add_argument("--form-wait", type=float, default=1.5,
                        help="wait seconds for the purchase form to load")
    parser.add_argument("--risk-wait", type=float, default=0.6)
    parser.add_argument("--password-wait", type=float, default=0.05)
    parser.add_argument("--at", help="start at local HH:MM:SS.mmm or ISO time")
    parser.add_argument("--from-results", action="store_true",
                        help="start the clock by tapping the product on the search results page")
    parser.add_argument("--js-prefill", action="store_true",
                        help="set CurDepositBuyAmount and call goBuy() via WebView JS")
    parser.add_argument("--preopened", action="store_true",
                        help="the detail page is already open; at T just call goBuy()")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise Stop("产品代码格式不正确。")
    try:
        amount = f"{float(args.amount):.2f}"
    except ValueError:
        raise Stop("金额格式不正确。")
    if amount != "0.01":
        raise Stop("本脚本目前只允许 0.01 元。")
    run(args.code, amount, fast=args.fast, read_keys=args.read_keys, dry_run=args.dry_run,
        form_wait=args.form_wait, risk_wait=args.risk_wait, password_wait=args.password_wait,
        at=parse_at(args.at), from_results=args.from_results,
        js_prefill=args.js_prefill, preopened=args.preopened)


if __name__ == "__main__":
    try:
        main()
    except (Stop, RuntimeError, OSError, ValueError, KeyError,
            subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已出现提交动作，请先查询银行记录，勿重试。", file=sys.stderr)
        sys.exit(1)
