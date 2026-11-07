#!/usr/bin/env python3
"""Phone push alerts through an ntfy server (standard JSON publish API).

The server URL, topic and access token live together in a separate Keychain
item. The management app configures them in 设置 → 推送通知; the command
line fallback `python3 src/push.py setup` still prompts for the same values in
the account holder's own terminal. Messages never include screenshots,
passwords, tokens or Keychain contents.

The Tauri shell starts the watchdog `python3 -B src/push.py app-watch` with a
pipe on its stdin and keeps the write end open for the whole app lifetime. The
watchdog announces the app start, then blocks until the pipe closes — normal
quit, `pkill`, a crash and SIGKILL all close the write end, so EOF arrives
either way — and announces the exit with a few retries. SIGTERM/SIGINT/SIGHUP
are also handled as a best-effort fallback for system shutdown. The watch and
plan processes keep running independently; these notifications only describe
the management app itself.

Publish API (see https://docs.ntfy.sh/publish/#publish-as-json):

    POST <server>/                     (the server root, https only)
    Authorization: Bearer <token>
    Content-Type: application/json
    {"topic": "...", "title": "...", "message": "...", "priority": 3}

Any 2xx is success; 401/403 means the token is invalid or has no access to the
topic; 429 means the server rate-limited the request; anything else is a
failure. Redirects are never followed: urllib would replay the Authorization
header at the new URL, which may be another host or plain http, so every 3xx
counts as a failure. A failed push only returns False and never stops the
watch loop.
"""
import getpass
import json
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

import keychain_store
import push_settings

SERVICE = b"cmb-finance-bot.push.v1"
TIMEOUT = 5                              # seconds, per the watch's budget
TITLE_PREFIX = "[招行值守] "
TOPIC = re.compile(r"[-_A-Za-z0-9]{1,64}")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# Management app lifecycle messages: event -> (title, body line). The body
# starts with the local time, so a delayed notification stays readable.
APP_EVENTS = {
    "app_started": ("管理 App 已启动",
                    "管理 App 已启动；值守与计划进程独立运行，不受影响。"),
    "app_exited": ("管理 App 已退出",
                   "管理 App 已退出；值守与计划进程继续运行，不受影响。"),
}
# Reliability knobs for the exit notification only: they retry a failed ntfy
# publish and never affect purchase or watch behaviour, so they stay module
# constants instead of purchase settings.
APP_EXIT_ATTEMPTS = 3                    # total attempts, including the first
APP_EXIT_RETRY_DELAYS = (2, 5)           # seconds to wait before attempts 2 and 3
READ_BYTES = 4096                        # drain size; the watchdog discards input
EXIT_SIGNALS = tuple(getattr(signal, name) for name in ("SIGTERM", "SIGINT", "SIGHUP")
                     if hasattr(signal, name))
SILENT_REASONS = (None, "unknown_event", "disabled", "not_configured")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so the bearer token can never be replayed elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None     # HTTPError then reaches send(), which reports the code


_OPENER = urllib.request.build_opener(_NoRedirect())


def _server_url(value, allow_loopback_http=False):
    """Validate and normalize the publish URL (POST target is the server root)."""
    parts = urllib.parse.urlsplit((value or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("推送服务器地址必须是 https 地址。")
    if parts.scheme != "https":
        if not (allow_loopback_http and parts.hostname in LOOPBACK):
            raise ValueError("推送服务器地址必须是 https 地址。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("推送服务器地址不能带账号、查询参数或锚点。")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc,
                                    parts.path.rstrip("/") + "/", "", ""))


def load():
    data = json.loads(keychain_store.find(service=SERVICE))
    if not isinstance(data, dict) or not all(
            isinstance(data.get(k), str) and data[k].strip()
            for k in ("server", "topic", "token")):
        raise RuntimeError("钥匙串里的推送配置不完整，请重新配置推送。")
    if not TOPIC.fullmatch(data["topic"]) or "\n" in data["token"] or "\r" in data["token"]:
        raise RuntimeError("钥匙串里的推送配置无效，请重新配置推送。")
    # Plain http is accepted only for loopback, so send() can be tested
    # against a local fake server; save_config() always requires https.
    return {"server": _server_url(data["server"], allow_loopback_http=True),
            "topic": data["topic"], "token": data["token"]}


def save_config(server, topic, token):
    """Validate and save the push config, overwriting any existing item.

    The token never leaves this process through argv, logs or errors.
    """
    if not all(isinstance(value, str) for value in (server, topic, token)):
        raise RuntimeError("推送配置格式无效。")
    server = server.strip()
    topic = topic.strip()
    token = token.strip()
    try:
        server = _server_url(server)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from None
    if not TOPIC.fullmatch(topic):
        raise RuntimeError("频道名只能包含字母、数字、- 和 _，最长 64 个字符。")
    if not token or "\n" in token or "\r" in token:
        raise RuntimeError("访问令牌不能为空或包含换行。")
    payload = json.dumps({"server": server, "topic": topic, "token": token},
                         separators=(",", ":")).encode("utf-8")
    try:
        keychain_store.put(payload, service=SERVICE)
    except RuntimeError as exc:
        raise RuntimeError(f"保存推送配置失败：{exc}") from None


def clear_config():
    """Remove the Keychain item; already absent is not an error."""
    try:
        keychain_store.delete(service=SERVICE)
    except RuntimeError as exc:
        raise RuntimeError(f"清除推送配置失败：{exc}") from None


def config_info():
    """Non-secret view of the saved config. Never includes the token itself."""
    try:
        cfg = load()
    except (RuntimeError, ValueError):
        return {"configured": False, "server": None, "topic": None, "token_set": False}
    return {"configured": True, "server": cfg["server"], "topic": cfg["topic"],
            "token_set": bool(cfg["token"])}


def configured():
    try:
        load()
    except (RuntimeError, ValueError):
        return False
    return True


def _priority(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 3
    return value if 1 <= value <= 5 else 3


def _deliver(cfg, title, body, priority=3):
    """Publish once. Returns (sent, reason) where reason is status or type name."""
    try:
        payload = json.dumps({"topic": cfg["topic"],
                              "title": TITLE_PREFIX + str(title),
                              "message": str(body),
                              "priority": _priority(priority)},
                             ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            cfg["server"], data=payload, method="POST",
            headers={"Authorization": "Bearer " + cfg["token"],
                     "Content-Type": "application/json"})
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            if 200 <= response.status < 300:
                return True, None
            return False, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:        # network/TLS/timeout/anything: never raise
        return False, type(exc).__name__


def _dispatch(event, title, body, priority=3):
    """Deliver one event if enabled; returns (sent, reason) and never raises.

    reason is None after a successful publish, "unknown_event", "disabled"
    (the global switch or that event is off; unreadable preferences count as
    closed), "not_configured" (no usable Keychain item) or the publish failure
    (HTTP status / exception type name). Reasons only expose codes or type
    names, never credential contents.
    """
    event = "system_status" if event is None else event
    if not isinstance(event, str) or event not in push_settings.EVENT_KEYS:
        return False, "unknown_event"
    try:
        preferences = push_settings.load()
        if not preferences["enabled"] or not preferences["events"][event]:
            return False, "disabled"
    except Exception:
        return False, "disabled"
    try:
        cfg = load()
    except Exception:
        return False, "not_configured"
    return _deliver(cfg, title, body, priority)


def send(title, body, priority=3, event=None):
    """Send an enabled event, reading preferences anew before touching Keychain.

    Legacy calls without an event use system_status. Unknown events are rejected
    silently. Disabled events, invalid preferences and missing credentials return
    False; no notification failure may interrupt the watch. Errors only expose
    status codes or exception type names, never credential contents.
    """
    sent, reason = _dispatch(event, title, body, priority)
    if not sent and reason not in SILENT_REASONS:
        print(f"推送发送失败：{reason}", file=sys.stderr, flush=True)
    return sent


def send_test():
    """Send one test alert; returns {'sent': True} or {'sent': False, 'error': ...}.

    Always bypasses notification preferences, including the global switch.
    A missing/invalid config raises instead, so the caller can tell "not
    configured" apart from "configured but the server rejected the push"."""
    try:
        cfg = load()
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(str(exc)) from None
    sent, reason = _deliver(cfg, "测试推送", "推送通知配置成功。")
    return {"sent": True} if sent else {"sent": False, "error": reason}


# Management app lifecycle ------------------------------------------------

class AppExitTriggered(Exception):
    """Raised from the read loop's signal handler to start the exit notification."""


def _stamp():
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def _uptime_text(seconds):
    """Human-readable management app uptime, e.g. 本次运行 1 小时 2 分 / 5 秒."""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"本次运行 {hours} 小时 {minutes} 分 / {secs} 秒"


def send_app_event(event, uptime_seconds=None):
    """Push one management-app lifecycle event; returns (sent, reason).

    The body starts with the local time and the event line; app_exited appends
    the app's uptime when the caller knows it. Priority is 3: these are status
    updates, not transaction results. Never raises and never includes the
    server URL or token.
    """
    if not isinstance(event, str) or event not in APP_EVENTS:
        return False, "unknown_event"
    try:
        title, line = APP_EVENTS[event]
        body = f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{line}"
        if event == "app_exited" and uptime_seconds is not None:
            body += "\n" + _uptime_text(uptime_seconds)
        return _dispatch(event, title, body, 3)
    except Exception as exc:        # push must never break the watchdog
        return False, type(exc).__name__


def _log_lifecycle(event, result):
    """One stderr line per lifecycle send, in the format push.log expects."""
    sent, reason = result
    if sent:
        detail = "已发送"
    elif reason == "disabled":
        detail = "未发送：该通知已关闭"
    elif reason == "not_configured":
        detail = "未发送：推送未配置"
    elif reason == "unknown_event":
        detail = "未发送：未知事件"
    else:
        detail = f"发送失败：{reason}"
    print(f"{_stamp()} {event} {detail}", file=sys.stderr, flush=True)


def _send_app_exit(sleep, uptime_seconds):
    """Send app_exited, retrying transient delivery failures.

    A failure that the user's preference can explain (event closed, not
    configured, unknown event) is never retried; HTTP/network failures are
    retried APP_EXIT_ATTEMPTS times in total. The management app is already
    gone, so this is the only chance to say it exited.
    """
    result = send_app_event("app_exited", uptime_seconds=uptime_seconds)
    sent, reason = result
    attempt = 1
    while not sent and reason not in SILENT_REASONS and attempt < APP_EXIT_ATTEMPTS:
        delay = APP_EXIT_RETRY_DELAYS[min(attempt - 1, len(APP_EXIT_RETRY_DELAYS) - 1)]
        print(f"{_stamp()} app_exited 发送失败：{reason}，{delay} 秒后重试",
              file=sys.stderr, flush=True)
        sleep(delay)
        result = send_app_event("app_exited", uptime_seconds=uptime_seconds)
        sent, reason = result
        attempt += 1
    _log_lifecycle("app_exited", result)


def _raise_app_exit(signum, frame):
    raise AppExitTriggered()


def _install_exit_handlers():
    """Route SIGTERM/SIGINT/SIGHUP into AppExitTriggered; return saved handlers."""
    previous = {}
    for signum in EXIT_SIGNALS:
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, _raise_app_exit)
        except (OSError, ValueError):
            previous.pop(signum, None)      # not the main thread: EOF still works
    return previous


def _restore_exit_handlers(previous):
    for signum, handler in previous.items():
        try:
            signal.signal(signum, handler)
        except (OSError, ValueError):
            pass


def app_watch(stream=None, sleep=None):
    """Watch the management app lifetime and push start/exit notifications.

    The Tauri shell starts this process with a pipe on stdin and keeps the
    write end open for its whole lifetime, so a blocked read reaches EOF when
    the shell goes away — Cmd-Q, `pkill`, a crash and SIGKILL all close the
    write end in the kernel. SIGTERM/SIGINT/SIGHUP are also caught while
    reading as a best-effort fallback for system shutdown. Tests inject
    `stream` and `sleep`, so this never touches the terminal or waits.
    """
    stream = sys.stdin.buffer if stream is None else stream
    sleep = time.sleep if sleep is None else sleep
    started_at = time.monotonic()

    _log_lifecycle("app_started", send_app_event("app_started"))

    previous = _install_exit_handlers()
    try:
        while True:
            try:
                chunk = stream.read(READ_BYTES)
            except AppExitTriggered:
                break
            except (OSError, ValueError):       # pipe already gone: same as EOF
                break
            if not chunk:
                break
    finally:
        _restore_exit_handlers(previous)

    _send_app_exit(sleep, time.monotonic() - started_at)
    return 0


def setup():
    if not sys.stdin.isatty():
        raise RuntimeError("请在自己的本机终端运行。")
    server = input("ntfy 服务器地址（https，例如 https://ntfy.example.com/）: ").strip()
    topic = input("频道名（topic）: ").strip()
    token = getpass.getpass("访问令牌（不显示）: ").strip()
    save_config(server, topic, token)
    token = None
    print("已保存。正在发送测试推送…")
    print("测试推送已发送，请在手机上查看。" if send_test()["sent"]
          else "测试推送发送失败，请检查地址、频道和令牌。")


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["setup"]:
            setup()
        elif sys.argv[1:] == ["test"]:
            result = send_test()
            if result["sent"]:
                sys.exit(0)
            print(f"推送发送失败：{result['error']}", file=sys.stderr)
            sys.exit(1)
        elif sys.argv[1:] == ["app-watch"]:
            sys.exit(app_watch())
        else:
            raise RuntimeError("用法：push.py setup | test | app-watch")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
