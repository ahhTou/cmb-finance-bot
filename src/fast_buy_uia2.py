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
from decimal import Decimal
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


FORM_WAIT = 20.0   # goBuy() → 理财购买 form
STEP_WAIT = 10.0   # risk popup, password page
REOPEN_AFTER = 5.0      # direct open: reload the buy page if no form by then
REOPEN_GAP = 1.0        # never reload faster than this
REOPEN_DEADLINE = 60.0  # give up reopening after this long
FORM_ERRORS = ("购买失败", "TOPI", "系统繁忙", "网络异常", "请稍后再试")


def dump():
    return ET.fromstring(device().dump_hierarchy())


def wait_for(check, timeout=3.0, what="页面元素"):
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
    raise fast_buy.Stop(f"等待{what}超时（{timeout:.0f} 秒）。")


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
        # 交易委托已接受: the scheduled-sale result page (JX040229, 11-03 09:00).
        for needle in ("提交成功", "申请失败", "密码错误", "购买成功", "交易委托已接受"):
            if needle in text:
                return needle
        time.sleep(0.1)
    raise fast_buy.Stop("结果页没有出现可识别的提示。")


def find_node(root, needle, exact=False):
    for n in root.iter("node"):
        text = ((n.get("text") or "") + " " + (n.get("content-desc") or "")).strip()
        if (text == needle if exact else needle in text):
            return n
    return None


def center_of(node):
    return center(node.get("bounds"))


def confirm_enabled(root):
    node = find_node(root, "确定", exact=True)
    return node is not None and node.get("enabled") == "true"


def close_password_panel():
    root = dump()
    btn = find_node(root, "密码框关闭")
    if btn is not None:
        x, y = center_of(btn)
        send_commands([f"input tap {x} {y}"])
        time.sleep(0.5)


def raw_digit_buttons(root):
    """Tolerant keypad read: does not raise while the panel is animating."""
    keys = {}
    for n in root.iter("node"):
        if n.get("class") == "android.widget.Button" and re.fullmatch(r"[0-9]", (n.get("text") or "").strip()):
            keys[(n.get("text") or "").strip()] = center(n.get("bounds"))
    return keys


def wait_keypad_stable(timeout=1.2):
    """Wait until all ten keys exist and their bounds stop changing."""
    prev = None
    end = time.monotonic() + timeout
    root = None
    keys = {}
    while time.monotonic() < end:
        root = dump()
        keys = raw_digit_buttons(root)
        if len(keys) == 10:
            sig = tuple(sorted(keys.items()))
            if sig == prev:
                return root, keys
            prev = sig
        else:
            prev = None
        time.sleep(0.04)
    root = root if root is not None else dump()
    return root, digit_keys(root)


def enter_password(password, confirm_wait=0.15):
    """Type the six digits, verify, and tap 确定 exactly once.

    The panel is detected while its slide-in animation may still be running;
    taps that arrive before the touch layer is ready are dropped (observed:
    5 of 6 digits registered). Rapid typing itself is fine once the panel is
    settled, so wait for stable keypad bounds before each typing attempt.

    After typing, 确定 must be enabled (it only is with six digits). If not,
    tapping the password field clears the partial input and reopens the
    keypad; wait for stability again, retype once. Never tap 确定 disabled.
    """
    root, keys = wait_keypad_stable()
    done_xy = center_of(find_node(root, "完成", exact=True))
    field_xy = center_of(find_node(root, "点击谈出密码键盘"))

    def type_digits(keys, done_xy):
        commands = [f"input tap {keys[d][0]} {keys[d][1]}" for d in password]
        commands.extend([f"sleep {confirm_wait}",
                         f"input tap {done_xy[0]} {done_xy[1]}"])
        send_commands(commands)
        time.sleep(0.15)

    type_digits(keys, done_xy)
    root = dump()
    if not confirm_enabled(root):
        # Reopen (and clear) the field, then retype on a settled panel.
        send_commands([f"input tap {field_xy[0]} {field_xy[1]}"])
        time.sleep(0.10)
        root, keys = wait_keypad_stable()
        done_xy = center_of(find_node(root, "完成", exact=True))
        type_digits(keys, done_xy)
        root = dump()
        if not confirm_enabled(root):
            close_password_panel()
            raise fast_buy.Stop("密码未满 6 位，已关闭密码框，未提交。")

    submit_xy = center_of(find_node(root, "确定", exact=True))
    send_commands([f"input tap {submit_xy[0]} {submit_xy[1]}"])


def open_form(code, amount):
    """Open the purchase form straight from the app's deep link and reopen it
    quickly when it does not show up or shows an error page. No detail page
    is needed. Nothing here confirms anything."""
    start = time.monotonic()
    opens = 0
    while True:
        fast_buy.open_buy_link(code, amount)
        opens += 1
        if opens > 1:
            print(f"第 {opens} 次打开购买页（{time.monotonic() - start:.1f}s）", flush=True)
        opened = time.monotonic()
        while time.monotonic() - opened < REOPEN_AFTER:
            try:
                root = dump()
            except Exception:
                root = None
            if root is not None:
                text = " ".join(fast_buy.label(n) for n in root.iter("node"))
                if ("可用余额" in text and "同意协议下一步" in text
                        and fast_buy.buy_page_shown(code)):
                    return root
                if any(e in text for e in FORM_ERRORS) and time.monotonic() - opened >= REOPEN_GAP:
                    print(f"购买页报错，重开：{next(e for e in FORM_ERRORS if e in text)}", flush=True)
                    break
            time.sleep(0.08)
        if time.monotonic() - start > REOPEN_DEADLINE:
            raise fast_buy.Stop(f"{REOPEN_DEADLINE:.0f} 秒内打开 {opens} 次，购买表单都没有出现。")


def run(code, amount, at=None, dry_run=False, confirm_wait=0.15, mark=None, direct=True):
    """One purchase. `mark(name, monotonic_time)` is an optional read-only
    timing hook; it never changes the flow."""
    def note(name, when):
        if mark is not None:
            mark(name, when)

    credentials = keychain_store.load()
    password = credentials.get("payment_password")
    if not isinstance(password, str) or not re.fullmatch(r"[0-9]{6}", password):
        raise fast_buy.Stop("钥匙串中没有有效的交易密码。")

    # Connect and warm the persistent server before the timed core.
    t = time.monotonic()
    # No button check: before the sale time the detail page may show no buy
    # button at all. js_prefill_and_buy() only accepts the page whose XRIPINN
    # matches `code`, which is the product check.
    device()
    dump()
    print(f"uia2 已连接并预热 {time.monotonic() - t:.2f}s", flush=True)

    if at is not None:
        fast_buy.wait_until(at)

    began = time.monotonic()
    note("start", began)
    fast_buy.ensure_forward()
    note("forward", time.monotonic())
    # Pre-submit waits are generous: nothing is confirmed yet, and at 00:30
    # (flaky Wi-Fi, detail page idle 14 min) the form took over 4 s.
    if direct:
        root = open_form(code, amount)
        note("gobuy", time.monotonic())
    else:
        fast_buy.js_prefill_and_buy(amount, code)
        note("gobuy", time.monotonic())
        root = wait_for(lambda root: has(root, "可用余额"), timeout=FORM_WAIT, what="购买表单")
    note("form", time.monotonic())
    d = device()
    # The form shows large amounts as 5,000.00; a text match on "5000.00"
    # missed it and retyped the amount, costing seconds. The password page
    # check below still catches a wrong amount.
    if Decimal(amount) not in fast_buy.plain_amounts(
            " ".join(fast_buy.label(n) for n in root.iter("node"))):
        if direct:
            # The link carries the amount; a mismatch means this is not the
            # form we opened. Never type an amount into it.
            raise fast_buy.Stop(f"购买表单金额不是 {amount}，可能不是刚打开的表单，已停止。")
        d(className="android.widget.EditText").set_text(amount)
        time.sleep(0.20)
        d.press("back")
        time.sleep(0.30)
    d(text="同意协议下一步").click()
    note("next", time.monotonic())
    if not d(text="一键输入").wait(timeout=STEP_WAIT):
        raise fast_buy.Stop("风险弹窗没有出现。")
    note("risk", time.monotonic())
    d(text="一键输入").click()
    note("fill", time.monotonic())
    time.sleep(0.20)
    d(text="确认").click()
    note("confirm", time.monotonic())

    root = wait_for(lambda r: has(r, "请输入取款密码") and has(r, "招商银行安全输入"),
                    timeout=STEP_WAIT, what="密码页")
    note("password", time.monotonic())
    # Compare numerically: large amounts may be shown as ￥5,000.00, and a
    # substring test would let ￥5000 match ￥50000.00.
    shown = fast_buy.yuan_amounts(" ".join(fast_buy.label(n) for n in root.iter("node")))
    if Decimal(amount) not in shown:
        raise fast_buy.Stop(f"密码页金额不是 ￥{amount}（页面显示 {sorted(shown)}），已停止。")

    if dry_run:
        print(f"dry run：到密码页约 {time.monotonic() - began:.2f} 秒；"
              "未输入密码、未提交。", flush=True)
        return

    # Six digits back-to-back, then only a short gap before 完成. Bounds come
    # from the verified native hierarchy; enter_password() also verifies that
    # all six digits landed before tapping 确定.
    enter_password(password, confirm_wait=confirm_wait)
    submitted = time.monotonic()
    note("submit", submitted)
    print(f"已提交一次，核心流程约 {submitted - began:.2f} 秒；等待结果。", flush=True)

    time.sleep(1.0)
    result = None
    try:
        result = wait_result(timeout=20.0)
        note("result", time.monotonic())
        print(f"结果页提示：{result}", flush=True)
    except fast_buy.Stop as exc:
        note("result_missing", time.monotonic())
        print(f"未能确认结果：{exc}。请立即到招行查询交易记录，不要重试。", flush=True)
    print("请以银行交易记录为准；不要重复提交。", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="UiAutomator2 版单次快速购买")
    parser.add_argument("--code", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--at", help="start at local HH:MM:SS.mmm or ISO time")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm-wait", type=float, default=0.15)
    parser.add_argument("--via-gobuy", action="store_true",
                        help="在已打开的详情页上调用 goBuy()，不用 App 链接直接打开购买页")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise fast_buy.Stop("产品代码格式不正确。")
    amount = fast_buy.parse_amount(args.amount)
    run(args.code, amount, at=fast_buy.parse_at(args.at), dry_run=args.dry_run,
        confirm_wait=args.confirm_wait, direct=not args.via_gobuy)


if __name__ == "__main__":
    try:
        main()
    except (fast_buy.Stop, RuntimeError, OSError, ValueError, KeyError,
            ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已出现提交动作，请先查询银行记录，勿重试。", file=sys.stderr)
        sys.exit(1)
