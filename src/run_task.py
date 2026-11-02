#!/usr/bin/env python3
"""Run one task using user-maintained local plaintext credentials."""
import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import secure_input
import timed_buy
import keychain_store

def main():
    parser = argparse.ArgumentParser(description="启动单次理财任务")
    parser.add_argument("--code", required=True)
    parser.add_argument("--amount", required=True)
    parser.add_argument("--at", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", args.code):
        raise RuntimeError("产品代码格式不正确。")
    try:
        amount = Decimal(args.amount)
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise RuntimeError("金额必须是正数，最多两位小数。")
    when = timed_buy.target_time(args.at)
    credentials = keychain_store.load()
    pattern = credentials.get("login_pattern")
    password = credentials.get("payment_password")
    if not isinstance(pattern, str) or not re.fullmatch(r"[1-9]{4,9}", pattern) or len(set(pattern)) != len(pattern):
        raise RuntimeError("请自行在本地密码文件填写有效的九宫格编号。")
    if not isinstance(password, str) or not re.fullmatch(r"[0-9]{6}", password):
        raise RuntimeError("请自行在本地密码文件填写 6 位交易密码。")
    try:
        secure_input.login(pattern)
        pattern = None
        credentials = None
        print("登录手势已发送。请由 Agent 判断登录并准备目标产品搜索结果页。", flush=True)
        transient_failures = 0
        while (when - datetime.now()).total_seconds() > 20:
            try:
                root = secure_input.screen()
                transient_failures = 0
            except (RuntimeError, subprocess.SubprocessError, ET.ParseError):
                transient_failures += 1
                if transient_failures >= 3:
                    raise RuntimeError("连续三次无法读取页面。")
                time.sleep(1)
                continue
            if timed_buy.has(root, "手机银行搜索") and timed_buy.contains_code(root, args.code):
                print("已找到目标产品结果页，进入定时等待。", flush=True)
                timed_buy.run(args.code, f"{amount:.2f}", when, 5.0, provided_password=password)
                return
            time.sleep(1)
        raise RuntimeError("购买时间前 20 秒仍未准备好结果页，已停止。")
    finally:
        pattern = None
        password = None
        credentials = None

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, timed_buy.Stop, OSError, ValueError, KeyError, subprocess.SubprocessError, ET.ParseError) as exc:
        # Only our own fixed error messages are safe to print; other exceptions
        # may include command arguments or sensitive data.
        detail = str(exc) if type(exc) in (RuntimeError, timed_buy.Stop) else type(exc).__name__
        print(f"任务停止（{detail}）。请查看模拟器状态；如已提交，请先查询银行交易记录，勿重复购买。", file=sys.stderr)
        sys.exit(1)
