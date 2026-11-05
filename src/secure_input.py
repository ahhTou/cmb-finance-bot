#!/usr/bin/env python3
"""Locally prompt for credentials and operate the visible CMB login keyboard.

Run in a terminal controlled by the account owner, not through an agent tool.
This utility does not submit transactions.
"""
import argparse
import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SDK = Path(os.environ.get("ANDROID_SDK_ROOT", ROOT / "var/android-sdk"))
ADB = SDK / "platform-tools/adb"
BASE = [str(ADB), "-P", "15039", "-s", "emulator-15554"]

def adb(*args, stdin=None):
    return subprocess.run(BASE + list(args), input=stdin, text=True, capture_output=True,
                          timeout=20, check=True).stdout

def screen():
    data = adb("exec-out", "uiautomator", "dump", "/dev/tty")
    start, end = data.find("<?xml"), data.rfind("</hierarchy>")
    if start < 0 or end < 0:
        raise RuntimeError("无法读取当前页面控件。")
    return ET.fromstring(data[start:end + len("</hierarchy>")])

def has(root, text):
    return any(text in (n.get("text", "") + n.get("content-desc", ""))
               for n in root.iter("node"))


def has_id(root, resource_id):
    return any(n.get("resource-id") == resource_id for n in root.iter("node"))


# The native nine-dot login overlay. Observed 2026-11-05 over both the 我的
# page (PBMainActivity) and a purchase link (PBLoginActivity); the normal
# logged-in 我的 page has neither, so this does not depend on screenshot size.
LOGIN_VIEW_IDS = ("cmb.pb:id/vGestureInputArea", "cmb.pb:id/vGestureContentView")


def login_page(root):
    return (root is not None
            and all(has_id(root, resource_id) for resource_id in LOGIN_VIEW_IDS))

def center(bounds):
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        raise RuntimeError("键盘位置不可用。")
    x1, y1, x2, y2 = map(int, match.groups())
    if x2 <= x1 or y2 <= y1:
        raise RuntimeError("键盘位置无效。")
    return ((x1 + x2) // 2, (y1 + y2) // 2)

def send_commands(commands):
    # Feed commands through stdin, not argv. Coordinates can still be observable
    # by software with access to the device or process, so this is not isolation.
    adb("shell", "sh", stdin="set -e\n" + "\n".join(commands) + "\n")

def screencap_raw():
    return subprocess.run(BASE + ["exec-out", "screencap"], capture_output=True,
                          timeout=20, check=True).stdout

def screen_protected():
    """True when the PNG screencap is the tiny all-black protected frame.

    The bank's login page blanks the PNG capture while normal pages are tens of
    kilobytes. The raw screencap path is not used here: it can expose content
    that the PNG path blanks.
    """
    data = subprocess.run(BASE + ["exec-out", "screencap", "-p"], capture_output=True,
                          timeout=20, check=True).stdout
    if len(data) < 100:
        raise RuntimeError("无法判断截图状态。")
    return len(data) < 12000

def login(provided=None, root=None):
    """`root` lets a caller pass a tree it read itself: `uiautomator dump`
    fails while a UiAutomator2 server holds the UiAutomation connection."""
    if root is None:
        root = screen()
    if not login_page(root):
        raise RuntimeError("页面不是已观察到的招行九宫格登录页。")
    if not screen_protected():
        raise RuntimeError("当前页面可正常截图，可能已登录；未发送登录手势。")
    size = adb("shell", "wm", "size")
    if "Physical size: 320x640" not in size or "Override size:" in size:
        raise RuntimeError("模拟器分辨率已变化，无法安全使用已观察到的九宫格位置。")
    if provided is None:
        print("请在本终端输入九宫格编号（1–9，从左到右、从上到下），输入不会显示。")
        secret = getpass.getpass("登录图案: ")
    else:
        secret = provided
    try:
        if not re.fullmatch(r"[1-9]{4,9}", secret) or len(set(secret)) != len(secret):
            raise RuntimeError("图案需为 4–9 个不重复的数字。")
        points = [(79, 302), (159, 302), (239, 302),
                  (79, 382), (159, 382), (239, 382),
                  (79, 462), (159, 462), (239, 462)]
        positions = [points[int(c) - 1] for c in secret]
        # Each `input motionevent` is a separate process. Keep the finger down
        # long enough for the first dot to register, move in small steps, and
        # pause on every intermediate dot. A 0.12/0.04s cadence failed; the
        # slower 0.30/0.07/0.25s version logged in but took ~6.7s. This keeps
        # the dwell pauses and trims the step count and delays for ~5s.
        start_delay = 0.20
        step_delay = 0.05
        dot_dwell = 0.18
        steps_per_segment = 6
        commands = [f"input motionevent DOWN {positions[0][0]} {positions[0][1]}",
                    f"sleep {start_delay}"]
        for index, ((x1, y1), (x2, y2)) in enumerate(zip(positions, positions[1:])):
            for step in range(1, steps_per_segment + 1):
                x = round(x1 + (x2 - x1) * step / steps_per_segment)
                y = round(y1 + (y2 - y1) * step / steps_per_segment)
                commands.extend([f"input motionevent MOVE {x} {y}", f"sleep {step_delay}"])
            if index < len(positions) - 2:
                commands.append(f"sleep {dot_dwell}")
        x, y = positions[-1]
        commands.extend([f"sleep {dot_dwell}", f"input motionevent UP {x} {y}"])
        began = time.monotonic()
        send_commands(commands)
        elapsed = time.monotonic() - began
        print(f"已发送登录手势（约 {elapsed:.1f} 秒）；请在模拟器确认登录结果。")
    finally:
        secret = None

def payment():
    root = screen()
    if not has(root, "请输入取款密码") or not has(root, "招商银行安全输入"):
        raise RuntimeError("当前页面不是已观察到的招行交易密码键盘。")
    keys = {}
    for node in root.iter("node"):
        if node.get("class") != "android.widget.Button":
            continue
        text = node.get("text", "")
        if re.fullmatch(r"[0-9]", text):
            if text in keys:
                raise RuntimeError("数字按键重复，无法确认键盘布局。")
            keys[text] = center(node.get("bounds"))
    if set(keys) != set("0123456789"):
        raise RuntimeError("无法完整识别安全键盘，已停止。")
    secret = getpass.getpass("取款密码（不显示）: ")
    try:
        if not re.fullmatch(r"[0-9]{6}", secret):
            raise RuntimeError("取款密码应为 6 位数字。")
        commands = [f"input tap {keys[c][0]} {keys[c][1]}" for c in secret]
        send_commands(commands)
        print("已发送输入；请在模拟器确认密码位数并手动完成后续操作。")
    finally:
        secret = None

def main():
    parser = argparse.ArgumentParser(description="本机隐藏输入招行凭据")
    parser.add_argument("mode", choices=("login", "payment"))
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise RuntimeError("请在自己操作的本机终端运行，不能通过管道或 Agent 工具输入密码。")
    if not ADB.exists():
        raise RuntimeError("未找到项目 ADB。")
    (login if args.mode == "login" else payment)()

if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
