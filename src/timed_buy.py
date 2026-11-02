#!/usr/bin/env python3
"""Experimental, single-attempt purchase from an already prepared result list."""
import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import getpass
import re
import sys
import time
import xml.etree.ElementTree as ET
import subprocess

from secure_input import adb, center, has, screen, send_commands


class Stop(Exception):
    pass


def label(node):
    return (node.get("text") or "") + " " + (node.get("content-desc") or "")


def locate(root, needle, exact=False):
    found = []
    for node in root.iter("node"):
        text = label(node).strip()
        if (text == needle if exact else needle in text):
            try:
                xy = center(node.get("bounds"))
            except RuntimeError:
                continue
            found.append(xy)
    # A parent and a child may describe the same control; ambiguity must stop.
    found = list(dict.fromkeys(found))
    if len(found) != 1:
        raise Stop(f"页面控件无法唯一识别：{needle}")
    return found[0]


def tap(xy):
    adb("shell", "input", "tap", str(xy[0]), str(xy[1]))


def wait_page(check, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root = screen()
        if check(root):
            return root
        time.sleep(.2)
    raise Stop("等待页面超时；请检查模拟器，切勿盲目重试。")


def text_of_edit(node):
    return node.get("text") or ""


def matches_amount(text, amount):
    return re.search(r"(?<![\d.])" + re.escape(amount) + r"(?![\d.])", text) is not None


def contains_code(root, code):
    pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])")
    return any(pattern.search(label(n)) for n in root.iter("node"))


def get_password():
    secret = getpass.getpass("取款密码（只输入到本机终端）: ")
    if not re.fullmatch(r"[0-9]{6}", secret):
        raise Stop("取款密码必须是 6 位数字。")
    return secret


def security_keys(root):
    if not has(root, "请输入取款密码") or not has(root, "招商银行安全输入"):
        raise Stop("未识别到预期的招行安全键盘。")
    keys = {}
    for node in root.iter("node"):
        if node.get("class") != "android.widget.Button":
            continue
        digit = node.get("text", "")
        if re.fullmatch(r"[0-9]", digit):
            if digit in keys:
                raise Stop("数字键重复，无法确认布局。")
            keys[digit] = center(node.get("bounds"))
    if set(keys) != set("0123456789"):
        raise Stop("数字键不完整，无法输入。")
    return keys


def target_time(value):
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        try:
            t = datetime.strptime(value, "%H:%M:%S").time()
        except ValueError:
            raise Stop("时间必须为 HH:MM:SS 或 YYYY-MM-DDTHH:MM:SS。")
        when = datetime.combine(datetime.now().date(), t)
        if when <= datetime.now():
            raise Stop("时间已过；跨天任务请传入完整日期和时间。")
    if when.tzinfo is not None:
        raise Stop("请传入本机本地时间，不要带时区。")
    if when <= datetime.now():
        raise Stop("购买时间已过。")
    return when


def run(code, amount, when, max_lateness, provided_password=None):
    root = screen()
    if not has(root, "手机银行搜索") or not contains_code(root, code):
        raise Stop("请先由 Agent 准备到包含目标产品代码的搜索结果页。")
    candidates = [n for n in root.iter("node") if code in label(n) and "理财" in label(n)]
    if not candidates:
        raise Stop("没有在列表中找到指定理财产品。")
    # Prefer the first result. Its product code is verified again on detail page.
    center(candidates[0].get("bounds"))
    print(f"已检查产品 {code}，金额 {amount} 元，等待 {when:%Y-%m-%d %H:%M:%S}。", flush=True)
    password = get_password() if provided_password is None else provided_password
    try:
        remaining = (when - datetime.now()).total_seconds()
        if remaining <= 0:
            raise Stop("输入密码时已错过购买时间。")
        deadline = time.monotonic() + remaining
        # Allow the display to sleep during the wait, but wake it shortly before
        # the target time. The screen is checked again before any purchase tap.
        while deadline - time.monotonic() > 20:
            time.sleep(min(deadline - time.monotonic() - 20, 5))
        adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        while True:
            delay = deadline - time.monotonic()
            if delay <= 0:
                break
            time.sleep(min(delay, .1))
        if (datetime.now() - when).total_seconds() > max_lateness:
            raise Stop("系统时间已超出允许延迟，未执行购买。")
        current = screen()
        if not has(current, "手机银行搜索") or not contains_code(current, code):
            raise Stop("等待期间页面已变化，未执行购买。")
        candidates = [n for n in current.iter("node") if code in label(n) and "理财" in label(n)]
        if not candidates:
            raise Stop("目标产品不在当前可见结果中。")
        xy = center(candidates[0].get("bounds"))
        if (datetime.now() - when).total_seconds() > max_lateness:
            raise Stop("页面核对后已超出允许延迟，未执行购买。")
        began = time.monotonic()
        tap(xy)
        detail = wait_page(lambda x: contains_code(x, code) and has(x, "购买，点击可跳转"))
        tap(locate(detail, "购买，点击可跳转"))
        form = wait_page(lambda x: has(x, "购买金额") and contains_code(x, code))
        fields = [n for n in form.iter("node") if n.get("class") == "android.widget.EditText" and "请输入" in label(n)]
        if len(fields) != 1:
            raise Stop("金额输入框无法唯一识别。")
        tap(center(fields[0].get("bounds")))
        adb("shell", "input", "text", str(amount))
        form = wait_page(lambda x: any(n.get("class") == "android.widget.EditText" and matches_amount(text_of_edit(n), amount) for n in x.iter("node")))
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        form = wait_page(lambda x: has(x, "同意协议下一步") and any(n.get("class") == "android.widget.EditText" and matches_amount(text_of_edit(n), amount) for n in x.iter("node")))
        tap(locate(form, "同意协议下一步"))
        risk = wait_page(lambda x: has(x, "一键输入") and has(x, "本人已阅读风险揭示"))
        tap(locate(risk, "一键输入"))
        risk = wait_page(lambda x: any(n.get("class") == "android.widget.EditText" and "本人已阅读风险揭示" in text_of_edit(n) for n in x.iter("node")))
        tap(locate(risk, "确认", exact=True))
        auth = wait_page(lambda x: has(x, "请输入取款密码") and has(x, "招商银行安全输入"))
        if not any(matches_amount(label(n), amount) for n in auth.iter("node")):
            raise Stop("密码页金额与指定金额不符。")
        keys = security_keys(auth)
        send_commands([f"input tap {keys[d][0]} {keys[d][1]}" for d in password])
        auth = screen()
        tap(locate(auth, "完成", exact=True))
        auth = wait_page(lambda x: has(x, "请输入取款密码") and has(x, "确定"))
        tap(locate(auth, "确定", exact=True))
        print(f"已提交一次，点击流程耗时约 {time.monotonic() - began:.1f} 秒；正在等待结果，请勿重复操作。", flush=True)
        result = wait_page(lambda x: has(x, "提交成功") or has(x, "申请失败") or has(x, "密码错误"), timeout=30)
        if has(result, "提交成功"):
            print("购买申请提交成功；最终成交以产品管理机构确认结果为准。")
        else:
            print("页面提示申请失败或密码错误；请到模拟器查看，不要自动重试。")
    finally:
        password = None


def main():
    p = argparse.ArgumentParser(description="招行理财单次定时购买（实验）")
    p.add_argument("--code", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--at", required=True)
    p.add_argument("--max-lateness", type=float, default=5.0)
    a = p.parse_args()
    if not sys.stdin.isatty():
        raise Stop("必须在你本人操作的本机终端输入密码。")
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", a.code):
        raise Stop("产品代码格式不正确。")
    try:
        amount = Decimal(a.amount)
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise Stop("金额必须是正数，最多两位小数。")
    if not 0 <= a.max_lateness <= 5:
        raise Stop("允许延迟必须在 0 到 5 秒之间。")
    run(a.code, f"{amount:.2f}", target_time(a.at), a.max_lateness)


if __name__ == "__main__":
    try:
        main()
    except (Stop, RuntimeError, OSError, subprocess.SubprocessError, ET.ParseError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        print("若已点击最终确定，请先查询银行记录，勿直接重试。", file=sys.stderr)
        sys.exit(1)
