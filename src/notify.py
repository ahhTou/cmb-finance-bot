#!/usr/bin/env python3
"""Plain-text email alerts through QQ Mail SMTP.

The sender address and SMTP authorization code live in a separate Keychain
item; the account holder stores them with `python3 src/notify.py setup` in
their own terminal. Messages never include screenshots or credentials.
"""
import getpass
import json
import re
import smtplib
import socket
import sys
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

import keychain_store

SERVICE = b"cmb-finance-bot.smtp.v1"
HOST, PORT = "smtp.qq.com", 465
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def load():
    data = json.loads(keychain_store.find(service=SERVICE))
    if not all(isinstance(data.get(k), str) and data[k] for k in ("sender", "code", "to")):
        raise RuntimeError("钥匙串里的邮件配置不完整，请重新运行 notify.py setup。")
    return data


def configured():
    try:
        load()
    except (RuntimeError, ValueError):
        return False
    return True


def send(subject, body):
    """Send one alert. Returns False instead of raising: a failed email must
    never stop the watch loop. Without email setup this is a silent no-op."""
    if not configured():
        return False
    try:
        cfg = load()
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header("[招行值守] " + subject, "utf-8")
        msg["From"] = formataddr(("cmb-finance-bot", cfg["sender"]))
        msg["To"] = cfg["to"]
        with smtplib.SMTP_SSL(HOST, PORT, timeout=20) as smtp:
            smtp.login(cfg["sender"], cfg["code"])
            smtp.sendmail(cfg["sender"], [cfg["to"]], msg.as_string())
        return True
    except (OSError, RuntimeError, ValueError, smtplib.SMTPException, socket.timeout) as exc:
        print(f"邮件发送失败：{type(exc).__name__}", file=sys.stderr, flush=True)
        return False


def setup():
    if not sys.stdin.isatty():
        raise RuntimeError("请在自己的本机终端运行。")
    sender = input("发件 QQ 邮箱: ").strip()
    to = input("收件邮箱（回车同发件）: ").strip() or sender
    code = getpass.getpass("QQ 邮箱 SMTP 授权码（不显示）: ").strip()
    if not EMAIL.fullmatch(sender) or not EMAIL.fullmatch(to) or not code:
        raise RuntimeError("邮箱或授权码格式不正确。")
    payload = json.dumps({"sender": sender, "code": code, "to": to}).encode("utf-8")
    code = None
    try:
        item = keychain_store.add(payload, service=SERVICE)
        keychain_store.core.CFRelease(item)
    except RuntimeError:
        raise RuntimeError("写入失败；若已存在旧条目，请先在“钥匙串访问”里删除 "
                           "cmb-finance-bot.smtp.v1 再重试。")
    print("已保存。正在发送测试邮件…")
    print("测试邮件已发送，请查收。" if send("测试邮件", "邮件通知配置成功。")
          else "测试邮件发送失败，请检查授权码和网络。")


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["setup"]:
            setup()
        elif sys.argv[1:] == ["test"]:
            sys.exit(0 if send("测试邮件", "邮件通知正常。") else 1)
        else:
            raise RuntimeError("用法：notify.py setup | test")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
