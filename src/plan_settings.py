"""计划调度内部参数；非敏感、与购买配置分开保存。

这些值只影响计划进程的排程、轮询和超时，不进入购买参数快照，也不改变
`settings_revision`。计划开始时把当时的值写入 `plan.json`，运行中的计划沿用
开始时的值；之后修改只影响下一份计划。
"""
import json
import os
import tempfile
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / "var/night/plan-settings.json"

DEFAULTS = {
    "arm_gap_minutes": 2,          # 下一项冷启动至少比上一项结束晚多久
    "first_end_slack_minutes": 2,  # 首发预计结束后再留的提交余量
    "end_timeout_minutes": 5,      # 单项超过预计结束多久就停止
    "grace_seconds": 15,           # 值守进程消失后等多久仍无终态才判失败/未知
    "poll_seconds": 2,             # 计划进程轮询值守任务的间隔
    "heartbeat_seconds": 10,       # 计划进程写 last_tick 的间隔
    "kill_wait_seconds": 10,       # SIGTERM 后等多久再 SIGKILL
}

LIMITS = {
    "arm_gap_minutes": (0, 60),
    "first_end_slack_minutes": (0, 60),
    "end_timeout_minutes": (1, 120),
    "grace_seconds": (0, 300),
    "poll_seconds": (1, 60),
    "heartbeat_seconds": (1, 300),
    "kill_wait_seconds": (1, 120),
}


def validate(values):
    if not isinstance(values, dict):
        raise RuntimeError("计划设置格式无效。")
    if set(values) - DEFAULTS.keys():
        raise RuntimeError("计划设置格式无效。")
    result = dict(DEFAULTS, **values)
    for key, value in result.items():
        lower, upper = LIMITS[key]
        if type(value) is not int or not lower <= value <= upper:
            raise RuntimeError(f"{key} 必须为 {lower}–{upper} 的整数。")
    if result["poll_seconds"] > result["heartbeat_seconds"]:
        raise RuntimeError("心跳间隔不能短于轮询间隔。")
    return result


def load():
    try:
        text = SETTINGS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return dict(DEFAULTS)
    except UnicodeError:
        raise RuntimeError("计划设置文件格式无效。") from None
    except OSError:
        raise RuntimeError("无法读取计划设置。") from None
    try:
        return validate(json.loads(text))
    except (ValueError, UnicodeError):
        raise RuntimeError("计划设置文件格式无效。") from None


def save(values):
    """Merge a partial update and atomically publish a complete 0600 file."""
    if not isinstance(values, dict):
        raise RuntimeError("计划设置格式无效。")
    result = validate(dict(load(), **values))
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="plan-settings-", suffix=".tmp",
                                            dir=SETTINGS.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as out:
                out.write(json.dumps(result, ensure_ascii=False, indent=1) + "\n")
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, SETTINGS)
        finally:
            temp.unlink(missing_ok=True)
    except OSError:
        raise RuntimeError("无法保存计划设置。") from None
    return result


def snapshot(raw):
    """Fill defaults for the plan worker; plan.json is written from validated values.

    The worker must not re-read the live file: a plan that has started keeps the
    values it started with. Ints are required so a corrupt plan cannot create a
    zero-length or negative sleep; range checks happen when values are written.
    """
    if not isinstance(raw, dict):
        return load()
    result = dict(DEFAULTS)
    for key in DEFAULTS:
        value = raw.get(key, DEFAULTS[key])
        if type(value) is not int:
            return load()
        result[key] = value
    return result


def view():
    return {"settings": load()}
