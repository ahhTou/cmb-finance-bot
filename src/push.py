#!/usr/bin/env python3
"""Phone push alerts through an ntfy server (standard JSON publish API).

The server URL, topic and access token live together in a separate Keychain
item. The management app configures them in 设置 → 凭据 → 推送通知; the command
line fallback `python3 src/push.py setup` still prompts for the same values in
the account holder's own terminal. Messages never include screenshots,
passwords, tokens or Keychain contents.

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
import sys
import urllib.error
import urllib.parse
import urllib.request

import keychain_store

SERVICE = b"cmb-finance-bot.push.v1"
TIMEOUT = 5                              # seconds, per the watch's budget
TITLE_PREFIX = "[招行值守] "
TOPIC = re.compile(r"[-_A-Za-z0-9]{1,64}")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


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


def send(title, body, priority=3):
    """Send one alert. Returns False instead of raising: a failed push must
    never stop the watch loop. Without push setup this is a silent no-op.

    The only thing ever written to stderr is an HTTP status or an exception
    type name, so the token cannot leak into the log."""
    try:
        cfg = load()
    except (RuntimeError, ValueError):
        return False
    sent, reason = _deliver(cfg, title, body, priority)
    if not sent:
        print(f"推送发送失败：{reason}", file=sys.stderr, flush=True)
    return sent


def send_test():
    """Send one test alert; returns {'sent': True} or {'sent': False, 'error': ...}.

    A missing/invalid config raises instead, so the caller can tell "not
    configured" apart from "configured but the server rejected the push"."""
    try:
        cfg = load()
    except (RuntimeError, ValueError) as exc:
        raise RuntimeError(str(exc)) from None
    sent, reason = _deliver(cfg, "测试推送", "推送通知配置成功。")
    return {"sent": True} if sent else {"sent": False, "error": reason}


def setup():
    if not sys.stdin.isatty():
        raise RuntimeError("请在自己的本机终端运行。")
    server = input("ntfy 服务器地址（https，例如 https://ntfy.example.com/）: ").strip()
    topic = input("频道名（topic）: ").strip()
    token = getpass.getpass("访问令牌（不显示）: ").strip()
    save_config(server, topic, token)
    token = None
    print("已保存。正在发送测试推送…")
    print("测试推送已发送，请在手机上查看。" if send("测试推送", "推送通知配置成功。")
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
        else:
            raise RuntimeError("用法：push.py setup | test")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        sys.exit(1)
