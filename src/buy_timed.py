#!/usr/bin/env python3
"""带分步计时的 0.01 购买。

行为 100% 同源：直接调用 `fast_buy_uia2.run()`，只传入一个只读的
`mark(name, monotonic_time)` 回调记录时间戳；不复制、不改变任何点击/等待。
本文件只负责：每单前把详情页打开、每单后收起结果页、打印与落盘计时。
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "var/uia2"))
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "15039")
os.environ.setdefault("ADBUTILS_ADB_PATH", str(ROOT / "var/android-sdk/platform-tools/adb"))
os.environ.setdefault("ANDROID_SERIAL", "emulator-15554")

import fast_buy
import fast_buy_uia2 as fu
import keychain_store
from secure_input import send_commands

DETAIL_URL = (
    "https://mobile.cmbchina.com/IEntrustFinance/subsidiaryproduct/financedetail.html"
    "?XRIPINN={code}&XSAACOD=D07&DeviceType=E&Version=14.4.8&SystemVersion=15&_u=24"
    "&appflag=1&_urlrefer=PLATFORM&behavior_entryid=ASC006002"
)
LOG_PATH = ROOT / "var" / "buy_timed_log.jsonl"

STEP_ORDER = [
    ("uia2/转发预热", "start", "forward"),
    ("goBuy JS 调用", "forward", "gobuy"),
    ("购买表单就绪", "gobuy", "form"),
    ("点「同意协议下一步」", "form", "next"),
    ("风险弹窗出现", "next", "risk"),
    ("点「一键输入」", "risk", "fill"),
    ("点「确认」", "fill", "confirm"),
    ("密码页出现", "confirm", "password"),
    ("输 6 位+完成+确定", "password", "submit"),
    ("提交→结果页", "submit", "result"),
]


def js_eval_page(page, expression, timeout=8):
    async def call():
        async with websockets.connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                      "params": {"expression": expression,
                                                 "returnByValue": True}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("result", {}).get("value")

    return asyncio.run(call())


def visible_webview_pages():
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=3) as r:
            pages = json.load(r)
    except OSError:
        return []
    out = []
    for p in pages:
        try:
            desc = json.loads(p.get("description") or "{}")
        except ValueError:
            desc = {}
        if desc.get("visible"):
            out.append(p)
    return out


DETAIL_STATE_JS = r"""
(()=>{
  const root=document.querySelector('#app') && document.querySelector('#app').__vue__;
  let page=null;
  (function walk(v,d){ if(!v||d>15||page) return; if(v.goBuyParam && typeof v.goBuy==='function') page=v; (v.$children||[]).forEach(c=>walk(c,d+1)); })(root,0);
  const btn=document.querySelector('#buybtn');
  return JSON.stringify({btnTag: page?page.btnTag:null, hasBuy: !!btn,
                         buyText: btn?btn.innerText.trim():'', url: location.href.slice(0,120)});
})()
"""


def detail_state(code, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for page in visible_webview_pages():
            url = page.get("url") or ""
            if "financedetail" in url and f"XRIPINN={code}" in url:
                try:
                    return json.loads(js_eval_page(page, DETAIL_STATE_JS))
                except Exception:
                    time.sleep(0.1)
                    continue
        time.sleep(0.1)
    return None


def foreground_detail(code):
    """Same signal run() uses for its preflight: the native tree, not CDP."""
    try:
        root = fu.dump()
    except Exception:
        return False
    text = " ".join(((n.get("text") or "") + " " + (n.get("content-desc") or "")).strip()
                    for n in root.iter("node"))
    return "购买，点击可跳转" in text and code in text


def goto_detail(code, timeout=12.0):
    if foreground_detail(code):
        return
    pages = visible_webview_pages()
    if not pages:
        raise fast_buy.Stop("没有可见 WebView，无法打开详情页。")
    url = DETAIL_URL.format(code=code)
    js_eval_page(pages[-1], "location.href=" + json.dumps(url) + "; 'go'")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if foreground_detail(code):
            return
        time.sleep(0.2)
    raise fast_buy.Stop("详情页不在前台；请先在 App 内打开该产品详情页。")


def dismiss_native_result():
    """Tap 完成 on a native result page if present, then settle."""
    try:
        root = fu.dump()
    except Exception:
        return
    text = " ".join(((n.get("text") or "") + (n.get("content-desc") or ""))
                    for n in root.iter("node"))
    if any(k in text for k in ("提交成功", "购买成功", "申请失败", "密码错误")):
        for node in root.iter("node"):
            label = ((node.get("text") or "") + " " + (node.get("content-desc") or "")).strip()
            if label in ("完成", "确定", "返回"):
                x, y = fu.center(node.get("bounds"))
                send_commands([f"input tap {x} {y}"])
                break
        time.sleep(1.0)


def build_steps(marks):
    steps = []
    for label, a, b in STEP_ORDER:
        end = marks.get(b)
        if end is None and b == "result":
            end = marks.get("result_missing")
        if a in marks and end is not None and end >= marks[a]:
            steps.append((label, end - marks[a]))
    return steps


def print_record(idx, record, steps):
    print(f"\n=== 第 {idx} 单 ===", flush=True)
    acc = 0.0
    for name, seconds in steps:
        acc += seconds
        print(f"  {name:<16} {seconds:6.3f}s   (累计 {acc:6.3f}s)", flush=True)
    print(f"  {'提交用时':<16} {record['submit_seconds']:6.3f}s   (goBuy→确定)", flush=True)
    print(f"  {'总用时':<16} {record['total_seconds']:6.3f}s   (goBuy→结果页)", flush=True)
    print(f"  结果页提示：{record['result']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="带分步计时的 0.01 购买（调用 fast_buy_uia2.run）")
    parser.add_argument("--code", default="133045A")
    parser.add_argument("--amount", default="0.01")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--at", help="start at local HH:MM:SS.mmm or ISO time")
    args = parser.parse_args()
    amount = f"{float(args.amount):.2f}"
    if amount != "0.01":
        raise fast_buy.Stop("本脚本目前只允许 0.01 元。")
    if not keychain_store.load().get("payment_password"):
        raise fast_buy.Stop("钥匙串中没有有效的交易密码。")

    fast_buy.ensure_forward()
    t_warm = time.monotonic()
    fu.device()
    fu.dump()
    print(f"uia2 连接/预热：{time.monotonic() - t_warm:.2f}s", flush=True)

    at = fast_buy.parse_at(args.at)
    records = []
    for i in range(1, args.runs + 1):
        if i > 1:
            dismiss_native_result()
        goto_detail(args.code)

        marks = {}
        result = fu.run(args.code, amount, at=at,
                        mark=lambda name, when: marks.__setitem__(name, when))
        steps = build_steps(marks)
        gobuy = marks.get("gobuy", 0)
        submit = marks.get("submit", gobuy) - gobuy
        end = marks.get("result") or marks.get("result_missing") or marks.get("submit", gobuy)
        total = end - gobuy
        record = {
            "index": i, "code": args.code, "amount": amount,
            "submit_seconds": round(submit, 3),
            "total_seconds": round(total, 3),
            "result": result or "未识别",
            "steps": [(name, round(seconds, 3)) for name, seconds in steps],
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        print_record(i, record, steps)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        records.append(record)
        if result is None:
            raise fast_buy.Stop(f"第 {i} 单结果未知，已停止。请先查交易记录，勿重试。")
        if "失败" in result or "密码错误" in result:
            raise fast_buy.Stop(f"第 {i} 单结果为「{result}」，已停止。")
        time.sleep(1.0)

    if not records:
        return
    submit_avg = sum(r["submit_seconds"] for r in records) / len(records)
    total_avg = sum(r["total_seconds"] for r in records) / len(records)
    print("\n=== 汇总 ===")
    for r in records:
        print(f"  第 {r['index']} 单：提交 {r['submit_seconds']:.3f}s，总计 {r['total_seconds']:.3f}s")
    print(f"  平均：提交 {submit_avg:.3f}s，总计 {total_avg:.3f}s")


if __name__ == "__main__":
    try:
        main()
    except (fast_buy.Stop, RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已提交，请先查交易记录，勿重试。", file=sys.stderr)
        sys.exit(1)
