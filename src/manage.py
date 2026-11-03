#!/usr/bin/env python3
"""Manage only this project's emulator and dedicated ADB server."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var"
SDK = Path(os.environ.get("ANDROID_SDK_ROOT", str(VAR / "android-sdk"))).expanduser()
AVD_NAME = "cmb_finance"
ADB_PORT = 15039
EMU_PORT = 15554
STATE = VAR / "processes.json"

def env():
    e = os.environ.copy()
    bundled_java = VAR / "amazon-corretto-21.jdk" / "Contents" / "Home"
    if bundled_java.is_dir():
        e["JAVA_HOME"] = str(bundled_java)
    e.update(ANDROID_HOME=str(SDK), ANDROID_SDK_ROOT=str(SDK),
             ANDROID_USER_HOME=str(VAR / "android-user"), ANDROID_AVD_HOME=str(VAR / "avd"),
             ANDROID_ADB_SERVER_PORT=str(ADB_PORT))
    return e

def executable(relative):
    path = SDK / relative
    if not path.is_file():
        raise RuntimeError(f"缺少 {path}；请先按照 README 配置 Android SDK。")
    return str(path)

def command(pid):
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""

def owned(pid, tokens):
    if not isinstance(pid, int) or pid <= 0:
        return False
    cmd = command(pid)
    return bool(cmd) and all(token in cmd for token in tokens)

def load():
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())

def write(state):
    VAR.mkdir(parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2))
    os.chmod(temp, 0o600)
    temp.replace(STATE)

def free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0

def status():
    state = load()
    for key in ("adb", "emulator"):
        item = state.get(key, {})
        running = owned(item.get("pid", -1), item.get("tokens", ["__missing__"]))
        print(f"{key}: {'运行中' if running else '未运行'}")
    print(f"SDK: {SDK}")
    print(f"项目数据: {VAR}")

def adb_service_pid():
    """PID of a running project ADB server, even one we did not record.

    A crashed emulator leaves this server behind, and an `adb` call made
    outside `start` can create an unrecorded one. Both must be reused rather
    than treated as "another process is already running".
    """
    try:
        result = subprocess.run(["ps", "-axo", "pid=,command="],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    needle = str(SDK / "platform-tools" / "adb")
    for line in result.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if needle not in command:
            continue
        if "15039" in command and "nodaemon" in command and command.rstrip().endswith("server"):
            try:
                return int(pid)
            except ValueError:
                continue
    return None


def start():
    VAR.mkdir(parents=True, exist_ok=True)
    old = load()
    running = {key: item for key, item in old.items()
               if owned(item.get("pid", -1), item.get("tokens", ["__missing__"]))}
    if "emulator" in running:
        raise RuntimeError("模拟器已在运行，请先执行 status 或 stop。")
    adb = executable("platform-tools/adb")
    emulator = executable("emulator/emulator")
    if not (VAR / "avd" / f"{AVD_NAME}.ini").exists():
        raise RuntimeError("尚未创建项目虚拟设备；请按照 README 执行 create-avd。")
    config = VAR / "avd" / f"{AVD_NAME}.avd" / "config.ini"
    if config.exists():
        lines = [line for line in config.read_text().splitlines() if not line.startswith("hw.keyboard=")]
        config.write_text("\n".join(lines + ["hw.keyboard=yes"]) + "\n")
    if not all(free(p) for p in (EMU_PORT, EMU_PORT + 1)):
        raise RuntimeError("模拟器端口已被占用，请检查 15554、15555。")
    if "adb" not in running and not free(ADB_PORT):
        pid = adb_service_pid()
        if pid is None:
            raise RuntimeError("15039 端口被其他程序占用；先停掉它再启动模拟器。")
        running["adb"] = {"pid": pid, "tokens": ["adb", str(ADB_PORT), "nodaemon"]}
        print("接管已在运行的 ADB 服务。")
    log = open(VAR / "emulator.log", "ab", buffering=0)
    state = dict(running)   # stale records are dropped
    try:
        if "adb" not in running:
            p = subprocess.Popen([adb, "-L", f"tcp:{ADB_PORT}", "nodaemon", "server"],
                                 env=env(), stdout=log, stderr=log, start_new_session=True)
            state["adb"] = {"pid": p.pid, "tokens": ["adb", str(ADB_PORT), "nodaemon"]}
            write(state)
            for _ in range(50):
                if p.poll() is not None:
                    raise RuntimeError("ADB 启动失败，请查看 var/emulator.log。")
                if not free(ADB_PORT):
                    break
                time.sleep(.1)
            else:
                raise RuntimeError("等待 ADB 超时。")
        else:
            print("复用已在运行的 ADB 服务。")
        p = subprocess.Popen([emulator, "-avd", AVD_NAME, "-port", str(EMU_PORT), "-no-snapshot"],
                             env=env(), stdout=log, stderr=log, start_new_session=True)
        state["emulator"] = {"pid": p.pid, "tokens": [AVD_NAME, str(EMU_PORT)]}
        write(state)
        time.sleep(2)
        if p.poll() is not None:
            raise RuntimeError("模拟器启动失败，请查看 var/emulator.log。")
        print("启动请求已提交。模拟器开机可能需要几分钟；使用 status 查看进程。")
    except Exception:
        stop()
        raise
    finally:
        log.close()

def stop():
    state = load()
    for key in ("emulator", "adb"):
        item = state.get(key, {})
        pid = item.get("pid", -1)
        if owned(pid, item.get("tokens", ["__missing__"])):
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                if not owned(pid, item["tokens"]):
                    break
                time.sleep(.1)
            else:
                print(f"{key} 尚未退出，保留记录，请检查 PID {pid}。")
                continue
            print(f"已停止 {key}。")
        state.pop(key, None)
    if state:
        write(state)
    else:
        STATE.unlink(missing_ok=True)
        print("项目进程已关停。")

def create_avd():
    manager = executable("cmdline-tools/latest/bin/avdmanager")
    executable("emulator/emulator")
    image = "system-images;android-35;google_apis;arm64-v8a"
    if (VAR / "avd" / f"{AVD_NAME}.ini").exists():
        raise RuntimeError("项目虚拟设备已存在；不会覆盖数据。")
    (VAR / "avd").mkdir(parents=True, exist_ok=True)
    subprocess.run([manager, "create", "avd", "-n", AVD_NAME, "-k", image,
                    "-p", str(VAR / "avd" / f"{AVD_NAME}.avd")],
                   input="no\n", text=True, env=env(), check=True)

def main():
    parser = argparse.ArgumentParser(description="招行理财自动化项目管理")
    parser.add_argument("action", choices=["status", "create-avd", "start", "stop"])
    args = parser.parse_args()
    {"status": status, "create-avd": create_avd, "start": start, "stop": stop}[args.action]()

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)


def status_info():
    state = load()
    return {key: {"running": owned(state.get(key, {}).get("pid", -1),
                                  state.get(key, {}).get("tokens", ["__missing__"])),
                  "pid": state.get(key, {}).get("pid")}
            for key in ("adb", "emulator")}
