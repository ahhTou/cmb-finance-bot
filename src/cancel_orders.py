#!/usr/bin/env python3
"""批量撤销「交易记录」里可撤单的 0.01 元测试订单。

已验证流程（2026-11-02）：
  交易记录 → 点「可撤单」→ 交易详情（satransdetail.html）→ 点「撤单」
  → 原生「请输入取款密码」面板 → 6 位密码 → 完成 → 确定
  → 「您的撤单请求已受理」→ 完成 → 回到交易记录。

安全约束：
- 一次只撤一笔；每笔撤完核对列表数量确实减少后才继续；
- 详情页校验金额与「可撤单」，密码面板再校验金额；
- 六位密码是否全部落入以「确定」是否由灰变可用为准；未满 6 位就关闭面板并停止，
  绝不点「确定」；
- 任何结果不明确立即停止，不重试；
- 密码从 macOS 钥匙串读取，不打印、不写入日志。

用法：
  python3 -B src/cancel_orders.py               # 撤掉所有可撤的 0.01 订单
  python3 -B src/cancel_orders.py --list        # 只列出现有可撤单订单
  python3 -B src/cancel_orders.py --limit 1     # 只撤一笔
  python3 -B src/cancel_orders.py --dry-run     # 走到密码面板即停，不输入密码
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "var/uia2"))
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "15039")
os.environ.setdefault("ADBUTILS_ADB_PATH", str(ROOT / "var/android-sdk/platform-tools/adb"))
os.environ.setdefault("ANDROID_SERIAL", "emulator-15554")

import uiautomator2 as u2
import websockets

import fast_buy
import keychain_store
from secure_input import adb, center, send_commands

LIST_PAGE = "transactionlist.html"
DETAIL_PAGE = "satransdetail.html"
LIST_TITLE = "交易记录"
DETAIL_TITLE = "交易详情"
DIGIT_GAP = "0.10"
LOG_PATH = ROOT / "var" / "cancel_log.jsonl"

DEVICE = None


class Stop(Exception):
    pass


# ---------------------------------------------------------------- native side

def device():
    global DEVICE
    if DEVICE is None:
        DEVICE = u2.connect("emulator-15554")
    return DEVICE


def dump():
    return ET.fromstring(device().dump_hierarchy())


def alltext(root):
    return " ".join(((n.get("text") or "") + " " + (n.get("content-desc") or "")).strip()
                    for n in root.iter("node"))


def find(root, needle, exact=False):
    for n in root.iter("node"):
        t = ((n.get("text") or "") + " " + (n.get("content-desc") or "")).strip()
        if (t == needle if exact else needle in t):
            return n
    return None


def digit_buttons(root):
    keys = {}
    for n in root.iter("node"):
        if n.get("class") == "android.widget.Button" and re.fullmatch(r"[0-9]", (n.get("text") or "").strip()):
            keys[(n.get("text") or "").strip()] = center(n.get("bounds"))
    return keys


def front_title():
    """Native header title of the foreground H5 page."""
    try:
        root = dump()
    except Exception:
        return None
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        if text in (LIST_TITLE, DETAIL_TITLE):
            return text
    return None


# ---------------------------------------------------------------- CDP helpers

def pages():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3) as r:
            return json.load(r)
    except OSError:
        return []


def page_for(needle):
    """The foreground WebView page for `needle` (App keeps old pages alive)."""
    candidates = []
    for p in pages():
        if needle not in (p.get("url") or ""):
            continue
        try:
            desc = json.loads(p.get("description") or "{}")
        except ValueError:
            desc = {}
        candidates.append((bool(desc.get("visible")), p))
    if not candidates:
        return None
    visible = [p for vis, p in candidates if vis]
    if visible:
        return visible[-1]
    # Older WebViews may not report visibility; only fall back to a single page.
    return candidates[0][1] if len(candidates) == 1 else None


def js_eval(needle, expression, timeout=10):
    page = page_for(needle)
    if page is None:
        raise Stop(f"没有找到可见页面：{needle}")

    async def call():
        async with websockets.connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": expression,
                                                 "returnByValue": True}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("result", {}).get("value")

    try:
        return asyncio.run(call())
    except Stop:
        raise
    except Exception as exc:
        raise Stop(f"页面脚本执行失败：{exc}") from exc


SCAN_JS = r"""
(()=>{
  const tags=[...document.querySelectorAll('.cancel-tag')];
  const rows=tags.map(e=>{
    const li=e.closest('li')||e.parentElement;
    return (li?li.innerText:'').replace(/\s+/g,' ').trim();
  });
  return JSON.stringify({count:rows.length, rows:rows.slice(0,40), title:document.title});
})()
"""

DETAIL_JS = r"""
(()=>{
  const t=document.body.innerText;
  const btn=[...document.querySelectorAll('div')].find(e=>e.children.length===0&&e.textContent.trim()==='撤单');
  return JSON.stringify({
    title:document.title,
    hasCancel:!!btn,
    contract:(t.match(/合同号\s*(\d+)/)||[])[1]||'',
    amount:(t.match(/购买金额\s*([\d.]+)\s*元/)||[])[1]||'',
    cancellable:t.includes('前可撤单')
  });
})()
"""

CLICK_CANCEL_JS = r"""
(()=>{
  const b=[...document.querySelectorAll('div')].find(e=>e.children.length===0&&e.textContent.trim()==='撤单');
  if(!b) return 'no button';
  b.click(); return 'ok';
})()
"""


def scan_list_once():
    info = json.loads(js_eval(LIST_PAGE, SCAN_JS))
    if LIST_TITLE not in (info.get("title") or ""):
        raise Stop("交易记录页尚未就绪。")
    return info


def click_cancel_tag(amount):
    expr = """(()=>{
      const tags=[...document.querySelectorAll('.cancel-tag')];
      for (const e of tags) {
        const li=e.closest('li')||e.parentElement;
        const t=(li?li.innerText:'').replace(/\\s+/g,' ');
        if (t.includes('可撤单') && t.includes(__A__)) { e.click(); return 'ok'; }
      }
      return 'none';
    })()""".replace("__A__", json.dumps(f"{amount}元"))
    return js_eval(LIST_PAGE, expr)


# ---------------------------------------------------------------- navigation

def tap_header_back():
    root = dump()
    for n in root.iter("node"):
        if (n.get("content-desc") or "").strip() == "返回，按钮":
            x, y = center(n.get("bounds"))
            send_commands([f"input tap {x} {y}"])
            return True
    adb("shell", "input", "keyevent", "4")
    return False


def ensure_list(timeout=15.0, max_presses=5):
    end = time.monotonic() + timeout
    presses = 0
    while time.monotonic() < end:
        if front_title() == LIST_TITLE and page_for(LIST_PAGE) is not None:
            try:
                return scan_list_once()
            except Stop:
                pass
        if presses < max_presses:
            tap_header_back()
            presses += 1
            time.sleep(1.0)
        else:
            time.sleep(0.3)
    raise Stop("无法回到「交易记录」页。")


def wait_detail(amount, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if front_title() != DETAIL_TITLE or page_for(DETAIL_PAGE) is None:
            time.sleep(0.1)
            continue
        try:
            info = json.loads(js_eval(DETAIL_PAGE, DETAIL_JS))
        except Stop:
            time.sleep(0.1)
            continue
        if info.get("hasCancel") and info.get("contract") and info.get("cancellable"):
            if info.get("amount") != amount:
                raise Stop(f"详情页金额 {info.get('amount')} 不是 {amount}，已停止。")
            return info
        time.sleep(0.1)
    raise Stop("没有进入交易详情页（详情页无「撤单」或不可撤）。")


# ---------------------------------------------------------------- password panel

def wait_password_panel(amount, timeout=6.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root = dump()
        text = alltext(root)
        keys = digit_buttons(root)
        ok = find(root, "确定", exact=True)
        if ("请输入取款密码" in text and "您申请撤销" in text
                and len(keys) == 10 and ok is not None):
            if amount not in text:
                raise Stop(f"密码面板金额不是 {amount}，已停止。")
            # Let the slide-up animation and focus settle; early taps get eaten.
            time.sleep(0.9)
            root = dump()
            keys = digit_buttons(root)
            ok = find(root, "确定", exact=True)
            if len(keys) != 10 or ok is None:
                raise Stop("密码面板在稳定后消失，已停止。")
            return root, keys, ok
        time.sleep(0.1)
    raise Stop("密码面板没有出现。")


def close_password_panel():
    root = dump()
    btn = find(root, "密码框关闭")
    if btn is not None:
        x, y = center(btn.get("bounds"))
        send_commands([f"input tap {x} {y}"])
        time.sleep(0.6)


def submit_password(root, keys, password):
    field = find(root, "点击谈出密码键盘")
    if field is None:
        raise Stop("密码输入框不可定位。")
    fx, fy = center(field.get("bounds"))
    cmds = [f"input tap {fx} {fy}", "sleep 0.40"]
    for ch in password:
        cmds += [f"input tap {keys[ch][0]} {keys[ch][1]}", f"sleep {DIGIT_GAP}"]
    cmds += ["sleep 0.40"]
    send_commands(cmds)
    time.sleep(0.30)

    # The panel exposes no dot count, but 确定 only enables once all six digits
    # are in. Check with the keyboard still open; never tap 确定 at 5 digits.
    root = dump()
    ok = find(root, "确定", exact=True)
    if ok is None or ok.get("enabled") != "true":
        close_password_panel()
        raise Stop("密码未满 6 位（「确定」仍不可用），已关闭密码框，未提交。")

    done = find(root, "完成", exact=True)
    if done is None:
        close_password_panel()
        raise Stop("找不到「完成」按钮，已关闭密码框。")
    dx, dy = center(done.get("bounds"))
    ox, oy = center(ok.get("bounds"))
    send_commands([f"input tap {dx} {dy}", "sleep 0.30",
                   f"input tap {ox} {oy}"])


def wait_cancel_result(timeout=35.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        text = alltext(dump())
        if "撤单请求已受理" in text:
            match = re.search(r"合同号是\s*(\d+)", text)
            return "ok", (match.group(1) if match else ""), text
        for bad in ("密码错误", "撤单失败", "交易失败"):
            if bad in text:
                return "failed", bad, text
        time.sleep(0.15)
    return "unknown", "", ""


def tap_done():
    root = dump()
    done = find(root, "完成", exact=True)
    if done is not None:
        x, y = center(done.get("bounds"))
        send_commands([f"input tap {x} {y}"])


def wait_count(expected, timeout=10.0):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            info = scan_list_once()
        except Stop:
            time.sleep(0.2)
            continue
        last = info["count"]
        if last == expected:
            return info
        time.sleep(0.25)
    raise Stop(f"交易记录数量未按预期变化：期望 {expected}，实际 {last}。"
               "请人工核对，勿重复撤单。")


def log(record):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(record, ts=datetime.now().isoformat(timespec="seconds")),
                            ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- main

def run(amount, limit, dry_run):
    ensure_list()
    info = scan_list_once()
    print(f"当前「进行中」列表中有 {info['count']} 笔可撤单订单。", flush=True)
    if info["count"] == 0:
        print("没有可撤单的订单，结束。", flush=True)
        return

    password = None
    if not dry_run:
        password = keychain_store.load().get("payment_password")
        if not isinstance(password, str) or not re.fullmatch(r"[0-9]{6}", password):
            raise Stop("钥匙串中没有有效的交易密码。")

    done = 0
    while True:
        info = ensure_list()
        before = info["count"]
        if before == 0:
            break
        if limit and done >= limit:
            print(f"已达到 --limit {limit}，停止。", flush=True)
            break

        if click_cancel_tag(amount) != "ok":
            raise Stop(f"列表中没有金额为 {amount} 的可撤单行。")

        detail = wait_detail(amount)
        print(f"[{done + 1}] 合同号 {detail['contract']}，金额 {detail['amount']}，点「撤单」。", flush=True)
        if js_eval(DETAIL_PAGE, CLICK_CANCEL_JS) != "ok":
            raise Stop("详情页没有「撤单」按钮。")
        root, keys, _ = wait_password_panel(amount)

        if dry_run:
            close_password_panel()
            ensure_list()
            print(f"dry run：已到密码面板（合同号 {detail['contract']}），未输入密码、未提交。", flush=True)
            return

        submit_password(root, keys, password)
        status, cancel_contract, text = wait_cancel_result()
        if status == "ok":
            log({"action": "cancel", "result": "ok", "amount": amount,
                 "contract": detail["contract"], "cancel_contract": cancel_contract})
            print(f"[{done + 1}] 撤单成功，撤单合同号 {cancel_contract}。", flush=True)
            tap_done()
            time.sleep(0.8)
            wait_count(before - 1)
            done += 1
            continue

        log({"action": "cancel", "result": status, "amount": amount,
             "contract": detail["contract"], "detail": (text or "")[:300]})
        if status == "failed":
            raise Stop(f"撤单失败：{text[:200]}。请人工核对，勿重试。")
        raise Stop("撤单结果未知（未看到「撤单请求已受理」）。"
                   "请立即人工查交易记录，勿重复提交。")

    print(f"完成：本次共撤 {done} 笔。", flush=True)


def main():
    parser = argparse.ArgumentParser(description="批量撤销可撤单的 0.01 元测试订单")
    parser.add_argument("--amount", default="0.01", help="只处理该金额的订单（默认 0.01）")
    parser.add_argument("--limit", type=int, default=0, help="最多撤几笔（0 = 全部）")
    parser.add_argument("--dry-run", action="store_true", help="走到密码面板即停，不输入密码")
    parser.add_argument("--list", action="store_true", help="只列出现有可撤单订单")
    args = parser.parse_args()

    amount = f"{float(args.amount):.2f}"
    fast_buy.ensure_forward()
    device()
    info = ensure_list()
    if args.list:
        print(f"可撤单 {info['count']} 笔：")
        for row in info["rows"]:
            print("  -", row)
        return
    run(amount, args.limit, args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except (Stop, RuntimeError, OSError, ValueError, KeyError,
            ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已提交过撤单动作，请先查交易记录，勿重试。", file=sys.stderr)
        sys.exit(1)
