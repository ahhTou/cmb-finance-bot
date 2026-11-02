#!/usr/bin/env python3
"""Local Keychain storage; credential values never appear in command arguments."""
import ctypes
import ctypes.util
import getpass
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parent.parent
PLAIN = ROOT / "config/credentials.json"
SERVICE = b"cmb-finance-bot.credentials.v1"
ACCOUNT = b"local-user"
ERR_NOT_FOUND = -25300
ERR_DUPLICATE = -25299

sec = ctypes.CDLL(ctypes.util.find_library("Security"))
core = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
sec.SecKeychainAddGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
    ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
sec.SecKeychainAddGenericPassword.restype = ctypes.c_int32
sec.SecKeychainFindGenericPassword.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
    ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
sec.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
sec.SecKeychainItemFreeContent.restype = ctypes.c_int32
sec.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
sec.SecKeychainItemDelete.restype = ctypes.c_int32
sec.SecKeychainItemModifyAttributesAndData.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
sec.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
core.CFRelease.argtypes = [ctypes.c_void_p]

def valid(data):
    if not isinstance(data, dict):
        return False
    pattern, password = data.get("login_pattern"), data.get("payment_password")
    return bool(isinstance(pattern, str) and re.fullmatch(r"[1-9]{4,9}", pattern)
                and len(set(pattern)) == len(pattern) and isinstance(password, str)
                and re.fullmatch(r"[0-9]{6}", password))

def find(service=SERVICE, account=ACCOUNT):
    length = ctypes.c_uint32()
    content = ctypes.c_void_p()
    item = ctypes.c_void_p()
    status = sec.SecKeychainFindGenericPassword(None, len(service), service, len(account), account,
                                               ctypes.byref(length), ctypes.byref(content), ctypes.byref(item))
    if status != 0:
        raise RuntimeError(f"钥匙串读取失败（系统状态 {status}）。")
    try:
        data = ctypes.string_at(content, length.value)
        return data
    finally:
        sec.SecKeychainItemFreeContent(None, content)
        if item:
            core.CFRelease(item)

def add(data, service=SERVICE, account=ACCOUNT):
    item = ctypes.c_void_p()
    buf = ctypes.create_string_buffer(data)
    status = sec.SecKeychainAddGenericPassword(None, len(service), service, len(account), account,
                                              len(data), buf, ctypes.byref(item))
    if status != 0:
        raise RuntimeError(f"钥匙串写入失败（系统状态 {status}）。")
    return item

def migrate():
    info = PLAIN.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("明文凭据文件必须是仅当前用户可访问的普通文件。")
    with PLAIN.open(encoding="utf-8") as f:
        data = json.load(f)
    if not valid(data):
        raise RuntimeError("请检查本地凭据文件格式。")
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    item = add(payload)
    try:
        if find() != payload:
            raise RuntimeError("钥匙串回读验证失败。")
        current = PLAIN.lstat()
        if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) != (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size):
            raise RuntimeError("本地文件在迁移期间发生变化，未删除。")
        PLAIN.unlink()
    except BaseException:
        # Keep the verified Keychain entry on failure; never delete a possible
        # sole good copy. The plaintext file is only removed after verification.
        raise
    finally:
        if item:
            core.CFRelease(item)
    print("钥匙串写入和回读验证成功，项目中的明文文件已删除。")

def load():
    data = json.loads(find())
    if not valid(data):
        raise RuntimeError("钥匙串凭据格式无效。")
    return data

def update_login():
    if not sys.stdin.isatty():
        raise RuntimeError("请在本机终端输入新的九宫格图案。")
    data = load()
    first = getpass.getpass("新九宫格编号（输入不显示）: ")
    second = getpass.getpass("再次输入新九宫格编号: ")
    if first != second:
        raise RuntimeError("两次输入不一致。")
    data["login_pattern"] = first
    if not valid(data):
        raise RuntimeError("九宫格编号格式无效。")
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    length, content, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
    status = sec.SecKeychainFindGenericPassword(None, len(SERVICE), SERVICE, len(ACCOUNT), ACCOUNT,
                                                ctypes.byref(length), ctypes.byref(content), ctypes.byref(item))
    if status != 0:
        raise RuntimeError(f"无法读取钥匙串条目（系统状态 {status}）。")
    try:
        buf = ctypes.create_string_buffer(payload)
        status = sec.SecKeychainItemModifyAttributesAndData(item, None, len(payload), buf)
        if status != 0:
            raise RuntimeError(f"无法更新钥匙串条目（系统状态 {status}）。")
    finally:
        sec.SecKeychainItemFreeContent(None, content)
        core.CFRelease(item)
    if find() != payload:
        raise RuntimeError("更新后的读取验证失败。")
    print("九宫格凭据已更新并验证；支付密码未更改。")

if __name__ == "__main__":
    try:
        if len(sys.argv) == 2 and sys.argv[1] == "update-login":
            update_login()
        elif len(sys.argv) == 1:
            migrate()
        else:
            raise RuntimeError("未知操作。")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"迁移未完成：{exc}", file=sys.stderr)
        sys.exit(1)
