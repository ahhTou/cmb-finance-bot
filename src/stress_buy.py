#!/usr/bin/env python3
"""Run N real 0.01 purchases through fast_buy_uia2 and report timing/failures."""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "var/uia2"))

import fast_buy
import fast_buy_uia2 as U
from secure_input import has

CODE = "133045A"
AMOUNT = "0.01"
DETAIL_URL = (
    "https://mobile.cmbchina.com/IEntrustFinance/subsidiaryproduct/financedetail.html"
    "?XRIPINN=133045A&XSAACOD=D07&DeviceType=E&Version=14.4.8&SystemVersion=15"
    "&_u=24&appflag=1&_urlrefer=PLATFORM&behavior_entryid=ASC006002"
)


def navigate_detail():
    fast_buy.ensure_forward()
    pages = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
    page = None
    for p in pages:
        try:
            if json.loads(p.get("description", "{}")).get("visible"):
                page = p
                break
        except Exception:
            pass
    if page is None:
        for p in pages:
            u = urlparse(p.get("url", ""))
            if "financedetail" in u.path or "saentrustbuy" in u.path:
                page = p
                break
    if page is None:
        raise fast_buy.Stop("没有可用的 WebView 页面。")

    import asyncio
    import websockets

    async def call():
        async with websockets.connect(page["webSocketDebuggerUrl"], open_timeout=5) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": DETAIL_URL}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                if msg.get("id") == 1:
                    return
    asyncio.run(call())


def goto_detail(timeout=10.0):
    end = time.monotonic() + timeout
    navigated = False
    while time.monotonic() < end:
        try:
            root = U.dump()
        except Exception:
            time.sleep(0.3)
            continue
        if has(root, "购买，点击") and has(root, CODE):
            return
        if has(root, "密码框关闭"):
            fast_buy.tap((286, 109))
        elif has(root, "关闭谈窗"):
            fast_buy.tap((281, 153))
        elif has(root, "一键输入"):
            fast_buy.tap((281, 153))
        elif has(root, "购买金额"):
            fast_buy.tap((29, 46))
        elif not navigated:
            navigate_detail()
            navigated = True
            time.sleep(1.5)
        else:
            time.sleep(0.5)
        time.sleep(0.5)
    raise fast_buy.Stop("无法回到产品详情页。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    args = parser.parse_args()

    results = []
    for i in range(1, args.iterations + 1):
        try:
            goto_detail()
            cp = subprocess.run(
                [sys.executable, "-B", str(ROOT / "src/fast_buy_uia2.py"),
                 "--code", CODE, "--amount", AMOUNT],
                capture_output=True, text=True, timeout=90,
            )
            out = cp.stdout
            err = cp.stderr
            m = re.search(r"核心流程约 ([\d.]+) 秒", out)
            ok = "结果页提示：提交成功" in out
            unknown = ("已提交一次" in out) and not ok
            results.append({"i": i, "core": float(m.group(1)) if m else None,
                            "ok": ok, "unknown": unknown, "returncode": cp.returncode,
                            "out_tail": out[-160:], "err_tail": err[-160:]})
            print(f"[{i}/{args.iterations}] ok={ok} core={results[-1]['core']} rc={cp.returncode}", flush=True)
            if unknown:
                print("submitted but result unknown; stopping to avoid duplicates.", flush=True)
                break
        except Exception as exc:
            results.append({"i": i, "core": None, "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"})
            print(f"[{i}/{args.iterations}] FAIL {type(exc).__name__}: {exc}", flush=True)

    cores = [r["core"] for r in results if r.get("ok") and r.get("core")]
    ok_count = sum(1 for r in results if r.get("ok"))
    print("\n=== SUMMARY ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"success={ok_count} fail={len(results)-ok_count} "
          f"avg_core={sum(cores)/len(cores):.2f}s" if cores else "no successful cores")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"harness stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
