#!/usr/bin/env python3
"""Pre-opened detail page purchase using UiAutomator2 for native page reads.

The WebView detail page is driven by CDP (goBuy + CurDepositBuyAmount). The
native purchase form, risk dialog, and password page are read through the
persistent UiAutomator2 server, which returns the hierarchy in ~0.1s instead
of the ~2s `uiautomator dump`. Clicks still use fast adb taps at the bounds
read from the hierarchy.
"""
import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "var/uia2"))
os.environ.setdefault("ANDROID_ADB_SERVER_PORT", "15039")
os.environ.setdefault("ADBUTILS_ADB_PATH", str(ROOT / "var/android-sdk/platform-tools/adb"))
os.environ.setdefault("ANDROID_SERIAL", "emulator-15554")

import uiautomator2 as u2

import fast_buy
import keychain_store
from secure_input import center, has, send_commands

DEVICE = None


def device():
    global DEVICE
    if DEVICE is None:
        DEVICE = u2.connect("emulator-15554")
    return DEVICE


def dump():
    return ET.fromstring(device().dump_hierarchy())


def wait_for(check, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            root = dump()
        except Exception:
            time.sleep(0.08)
            continue
        if check(root):
            return root
        time.sleep(0.08)
    raise fast_buy.Stop("等待页面元素超时。")


def stable_xy(needle, timeout=2.0):
    end = time.monotonic() + timeout
    prev = None
    while time.monotonic() < end:
        root = dump()
        if not has(root, needle):
            prev = None
            time.sleep(0.08)
            continue
        xy = fast_buy.locate_unique(root, needle)
        if prev == xy:
            return root, xy
        prev = xy
        time.sleep(0.08)
    raise fast_buy.Stop(f"元素位置不稳定：{needle}")


def digit_keys(root):
    keys = {}
    for node in root.iter("node"):
        if node.get("class") != "android.widget.Button":
            continue
        text = (node.get("text") or "").strip()
        if re.fullmatch(r"[0-9]", text):
            if text in keys:
                raise fast_buy.Stop("数字键重复。")
            keys[text] = center(node.get("bounds"))
    if set(keys) != set("0123456789"):
        raise fast_buy.Stop("数字键不完整。")
    return keys


def wait_result(timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            root = dump()
        except Exception:
            time.sleep(0.1)
            continue
        text = " ".join((n.get("text") or "") + " " + (n.get("content-desc") or "")
                        for n in root.iter("node"))
        for needle in ("提交成功", "申请失败", "密码错误", "购买成功"):
            if needle in text:
                return needle
        time.sleep(0.1)
    raise fast_buy.Stop("结果页没有出现可识别的提示。")


def run(code, amount, at=None, dry_run=False, confirm_wait=0.15):
    credentials = keychain_store.load()
    password = credentials.get("payment_password")
    if not isinstance(password, str) or not re.fullmatch(r"[0-9]{6}", password):
        raise fast_buy.Stop("钥匙串中没有有效的交易密码。")

    # Connect and warm the persistent server before the timed core.
    t = time.monotonic()
    device()
    warm = dump()
    if not (has(warm, "购买，点击可跳转") and has(warm, code)):
        raise fast_buy.Stop("请先把目标产品详情页打开。")
    print(f"uia2 已连接并预热 {time.monotonic() - t:.2f}s", flush=True)

    if at is not None:
        fast_buy.wait_until(at)

    began = time.monotonic()
    fast_buy.ensure_forward()
    fast_buy.js_prefill_and_buy(amount, code)

    root = wait_for(lambda root: has(root, "可用余额"), timeout=4.0)
    d = device()
    if not has(root, amount):
        d(className="android.widget.EditText").set_text(amount)
        time.sleep(0.20)
        d.press("back")
        time.sleep(0.30)
    d(text="同意协议下一步").click()
    if not d(text="一键输入").wait(timeout=3):
        raise fast_buy.Stop("风险弹窗没有出现。")
    d(text="一键输入").click()
    time.sleep(0.20)
    d(text="确认").click()

    root = wait_for(lambda r: has(r, "请输入取款密码") and has(r, "招商银行安全输入"), timeout=3.0)
    if not has(root, "￥" + amount):
        raise fast_buy.Stop(f"密码页金额不是 ￥{amount}，已停止。")

    if dry_run:
        print(f"dry run：到密码页约 {time.monotonic() - began:.2f} 秒；"
              "未输入密码、未提交。", flush=True)
        return

    keys = digit_keys(root)
    done_xy = fast_buy.locate_unique(root, "完成", exact=True)
    submit_xy = fast_buy.locate_unique(root, "确定", exact=True)
    # Six digits back-to-back, then only a short gap before 完成/确定. The
    # bounds come from the verified native hierarchy; clicks use fast adb taps.
    commands = [f"input tap {keys[d][0]} {keys[d][1]}" for d in password]
    commands.extend([f"sleep {confirm_wait}",
                     f"input tap {done_xy[0]} {done_xy[1]}",
                     "sleep 0.15",
                     f"input tap {submit_xy[0]} {submit_xy[1]}"])
    send_commands(commands)
    submitted = time.monotonic()
    print(f"已提交一次，核心流程约 {submitted - began:.2f} 秒；等待结果。", flush=True)

    time.sleep(1.0)
    try:
        result = wait_result(timeout=20.0)
        print(f"结果页提示：{result}", flush=True)
    except fast_buy.Stop as exc:
        print(f"未能确认结果：{exc}。请立即到招行查询交易记录，不要重试。", flush=True)
    print("请以银行交易记录为准；不要重复提交。", flush=True)


def main():
    parser = argparse.ArgumentParser(description="UiAutomator2 版单次快速购买")
    parser.add_argument("--code", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--at", help="start at local HH:MM:SS.mmm or ISO time")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-wait", type=float, default=0.15)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise fast_buy.Stop("产品代码格式不正确。")
    try:
        amount = f"{float(args.amount):.2f}"
    except ValueError:
        raise fast_buy.Stop("金额格式不正确。")
    if amount != "0.01":
        raise fast_buy.Stop("本脚本目前只允许 0.01 元。")
    run(args.code, amount, at=fast_buy.parse_at(args.at), dry_run=args.dry_run,
        confirm_wait=args.confirm_wait)


if __name__ == "__main__":
    try:
        main()
    except (fast_buy.Stop, RuntimeError, OSError, ValueError, KeyError,
            ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已出现提交动作，请先查询银行记录，勿重试。", file=sys.stderr)
        sys.exit(1)
