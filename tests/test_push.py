import contextlib
from datetime import datetime
from email.message import Message
import io
import json
import signal
import sys
import threading
import urllib.error
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import push
import watch_plan


class FakeNtfy:
    """In-memory urllib boundary: no listener, real network, or elapsed timeout."""

    def __init__(self, status=200, delay=0.0, location=None):
        self.status = status
        self.delay = delay
        self.location = location
        self.url = f"https://ntfy.example.com/mock-{id(self)}/"
        self.requests = []
        self.httpd = SimpleNamespace(waited=threading.Event())

    def open(self, request, timeout):
        headers = Message()
        for key, value in request.header_items():
            headers[key] = value
        self.requests.append({"path": "/", "headers": headers, "body": request.data})
        if self.delay:
            self.httpd.waited.set()
            raise TimeoutError("mock timeout")
        if self.status >= 300:
            raise urllib.error.HTTPError(request.full_url, self.status, "mock status", {}, None)
        return contextlib.nullcontext(SimpleNamespace(status=self.status))


class FlipStream:
    """Reaches EOF like a real pipe and changes the fake server status on the way."""

    def __init__(self, fake, status):
        self.fake = fake
        self.status = status

    def read(self, size):
        self.fake.status = self.status
        return b""


class SignalStream:
    """Delivers one signal to the handler installed while the watchdog reads."""

    def __init__(self, signum):
        self.signum = signum

    def read(self, size):
        signal.getsignal(self.signum)(self.signum, None)
        return b""      # only reached when no handler raises


def config(server, topic="test-topic", token="test-token"):
    return json.dumps({"server": server, "topic": topic, "token": token}).encode("utf-8")


class PushTest(unittest.TestCase):
    def setUp(self):
        self.find = patch.object(push.keychain_store, "find")
        self.mock_find = self.find.start()
        self.addCleanup(self.find.stop)
        preferences = patch.object(push.push_settings, "load", return_value=push.push_settings.validate({}))
        self.mock_preferences = preferences.start()
        self.addCleanup(preferences.stop)
        self.servers = {}
        opener = patch.object(push._OPENER, "open", side_effect=self.open)
        self.mock_open = opener.start()
        self.addCleanup(opener.stop)
        # 退出时请求计划暂停：默认 mock，避免测试碰到真实的 plan.json。
        self.real_pause_plan = push._pause_plan_after_app_exit
        pause_plan = patch.object(push, "_pause_plan_after_app_exit", return_value=False)
        self.mock_pause_plan = pause_plan.start()
        self.addCleanup(pause_plan.stop)

    def open(self, request, timeout):
        return self.servers[request.full_url].open(request, timeout)

    def serve(self, status=200, delay=0.0, location=None):
        fake = FakeNtfy(status=status, delay=delay, location=location)
        self.servers[fake.url] = fake
        return fake

    def send(self, *args, **kwargs):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = push.send(*args, **kwargs)
        return result, err.getvalue()

    def test_200_sends_standard_json_and_checks_request(self):
        fake = self.serve(200)
        self.mock_find.return_value = config(fake.url)
        ok, err = self.send("测试标题", "正文内容", priority=5)

        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(len(fake.requests), 1)
        request = fake.requests[0]
        self.assertEqual(request["path"], "/")
        self.assertEqual(request["headers"].get("Authorization"), "Bearer test-token")
        self.assertEqual(request["headers"].get("Content-Type"), "application/json")
        body = json.loads(request["body"])
        self.assertEqual(body["topic"], "test-topic")
        self.assertEqual(body["title"], "[招行值守] 测试标题")
        self.assertEqual(body["message"], "正文内容")
        self.assertEqual(body["priority"], 5)

    def test_default_priority_is_three(self):
        fake = self.serve(200)
        self.mock_find.return_value = config(fake.url)
        ok, _ = self.send("状态", "已布防")
        self.assertTrue(ok)
        self.assertEqual(json.loads(fake.requests[0]["body"])["priority"], 3)

    def test_401_returns_false_and_reports_only_the_status(self):
        fake = self.serve(401)
        self.mock_find.return_value = config(fake.url)
        ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertIn("HTTP 401", err)
        self.assertNotIn("test-token", err)
        self.assertEqual(len(err.splitlines()), 1)

    def test_429_returns_false_and_reports_only_the_status(self):
        fake = self.serve(429)
        self.mock_find.return_value = config(fake.url)
        ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertIn("HTTP 429", err)
        self.assertEqual(len(err.splitlines()), 1)

    def test_timeout_returns_false_without_leaking_the_token(self):
        fake = self.serve(200, delay=1.0)
        self.mock_find.return_value = config(fake.url, token="secret-token-9")
        with patch.object(push, "TIMEOUT", 0.2):
            ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertIn("timeout", err.lower())
        self.assertNotIn("secret-token-9", err)
        self.assertEqual(len(err.splitlines()), 1)
        # The mocked transport records the attempt before raising a timeout.
        self.assertTrue(fake.httpd.waited.wait(1))

    def test_redirect_is_not_followed_and_reports_only_the_status(self):
        target = self.serve(200)
        redirect = self.serve(302, location=target.url)
        self.mock_find.return_value = config(redirect.url)
        ok, err = self.send("标题", "正文")

        self.assertFalse(ok)
        self.assertIn("HTTP 302", err)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertNotIn("test-token", err)
        # The redirect target must never receive the replayed request/token.
        self.assertEqual(len(redirect.requests), 1)
        self.assertEqual(target.requests, [])

    def test_unconfigured_is_silent(self):
        self.mock_find.side_effect = RuntimeError("钥匙串读取失败（系统状态 -25300）。")
        ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertEqual(err, "")

    def test_incomplete_config_is_unconfigured(self):
        self.mock_find.return_value = json.dumps({"server": "https://ntfy.example.com/"}).encode()
        self.assertFalse(push.configured())
        ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertEqual(err, "")

    def test_configured_true_with_valid_keychain_item(self):
        self.mock_find.return_value = config("https://ntfy.example.com")
        self.assertTrue(push.configured())
        with patch.object(push.keychain_store, "find", side_effect=RuntimeError("absent")):
            self.assertFalse(push.configured())

    def test_unexpected_exception_never_escapes(self):
        self.mock_find.return_value = config("https://ntfy.example.com/")
        with patch.object(push._OPENER, "open", side_effect=RuntimeError("boom")):
            ok, err = self.send("标题", "正文")
        self.assertFalse(ok)
        self.assertIn("RuntimeError", err)
        self.assertEqual(len(err.splitlines()), 1)

    def test_setup_saves_json_and_sends_a_test_push(self):
        saved = {}

        def put(payload, service):
            saved["payload"] = payload
            saved["service"] = service

        out = io.StringIO()
        with patch.object(push.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["https://ntfy.example.com", "topic-1"]), \
             patch.object(push.getpass, "getpass", return_value="secret-token"), \
             patch.object(push.keychain_store, "put", side_effect=put), \
             patch.object(push, "send_test", return_value={"sent": True}) as send, \
             contextlib.redirect_stdout(out):
            push.setup()

        self.assertEqual(saved["service"], push.SERVICE)
        self.assertEqual(json.loads(saved["payload"]),
                         {"server": "https://ntfy.example.com/",
                          "topic": "topic-1", "token": "secret-token"})
        send.assert_called_once_with()
        self.assertIn("测试推送已发送", out.getvalue())

    def test_setup_rejects_http_server_and_non_tty(self):
        with patch.object(push.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["http://ntfy.example.com", "topic-1"]), \
             patch.object(push.getpass, "getpass", return_value="secret-token"), \
             patch.object(push.keychain_store, "put") as put:
            with self.assertRaises(RuntimeError):
                push.setup()
        put.assert_not_called()
        with patch.object(push.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(RuntimeError):
                push.setup()

    def test_save_config_validates_and_overwrites(self):
        with patch.object(push.keychain_store, "put") as put:
            push.save_config(" https://ntfy.example.com ", " topic-1 ", " secret-token ")
        payload = put.call_args.args[0]
        self.assertEqual(put.call_args.kwargs, {"service": push.SERVICE})
        self.assertEqual(json.loads(payload),
                         {"server": "https://ntfy.example.com/",
                          "topic": "topic-1", "token": "secret-token"})

    def test_save_config_rejects_invalid_values_without_writing(self):
        with patch.object(push.keychain_store, "put") as put:
            for server, topic, token in [
                ("http://ntfy.example.com", "topic-1", "secret-token"),
                ("https://ntfy.example.com", "bad topic", "secret-token"),
                ("https://ntfy.example.com", "topic-1", ""),
                ("https://ntfy.example.com", "topic-1", "secret\n-token"),
                (None, "topic-1", "secret-token"),
            ]:
                with self.subTest(server=server, topic=topic), self.assertRaises(RuntimeError):
                    push.save_config(server, topic, token)
        put.assert_not_called()

    def test_config_info_returns_no_token(self):
        self.mock_find.return_value = config("https://ntfy.example.com")
        info = push.config_info()
        self.assertEqual(info, {"configured": True,
                                "server": "https://ntfy.example.com/",
                                "topic": "test-topic", "token_set": True})
        self.assertNotIn("test-token", json.dumps(info))

    def test_config_info_absent_or_invalid_is_unconfigured(self):
        for payload in (RuntimeError("absent"), b"{not-json",
                        json.dumps({"server": "https://ntfy.example.com/"}).encode()):
            self.mock_find.side_effect = payload if isinstance(payload, Exception) else None
            self.mock_find.return_value = None if isinstance(payload, Exception) else payload
            with self.subTest(payload=payload):
                self.assertEqual(push.config_info(), {"configured": False, "server": None,
                                                      "topic": None, "token_set": False})

    def test_clear_config_deletes_the_keychain_item(self):
        with patch.object(push.keychain_store, "delete") as delete:
            push.clear_config()
        delete.assert_called_once_with(service=push.SERVICE)

    def test_send_test_reports_success_and_http_failure_without_token(self):
        fake = self.serve(200)
        self.mock_find.return_value = config(fake.url, token="secret-token-9")
        self.assertEqual(push.send_test(), {"sent": True})
        self.assertNotIn("secret-token-9", json.dumps(push.send_test()))

        denied = self.serve(401)
        self.mock_find.return_value = config(denied.url, token="secret-token-9")
        result = push.send_test()
        self.assertEqual(result, {"sent": False, "error": "HTTP 401"})
        self.assertNotIn("secret-token-9", json.dumps(result))

    def test_send_test_unconfigured_raises(self):
        self.mock_find.side_effect = RuntimeError("钥匙串读取失败（系统状态 -25300）。")
        with self.assertRaises(RuntimeError):
            push.send_test()

    def test_disabled_global_never_reads_credentials_or_sends(self):
        self.mock_preferences.return_value = push.push_settings.validate({"enabled": False})
        self.assertEqual(self.send("标题", "正文", event="purchase_success"), (False, ""))
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_disabled_event_never_reads_credentials_or_sends(self):
        self.mock_preferences.return_value = push.push_settings.validate(
            {"events": {"purchase_success": False}})
        self.assertEqual(self.send("标题", "正文", event="purchase_success"), (False, ""))
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_legacy_calls_use_system_status_and_explicit_event_is_independent(self):
        fake = self.serve()
        self.mock_find.return_value = config(fake.url)
        self.mock_preferences.return_value = push.push_settings.validate(
            {"events": {"system_status": False}})
        self.assertEqual(self.send("状态", "旧调用"), (False, ""))
        self.mock_find.assert_not_called()
        self.assertTrue(self.send("成功", "交易委托已接受", event="purchase_success")[0])
        self.assertEqual(len(fake.requests), 1)

    def test_every_catalog_event_can_be_filtered_before_keychain_access(self):
        for key in push.push_settings.EVENT_KEYS:
            with self.subTest(event=key):
                self.mock_preferences.return_value = push.push_settings.validate(
                    {"events": {key: False}})
                self.assertFalse(self.send("标题", "正文", event=key)[0])
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_unknown_events_are_silent_and_do_not_fall_back(self):
        for event in ("purchase_typo", "", 1, [], {}):
            with self.subTest(event=event):
                self.assertEqual(self.send("标题", "正文", event=event), (False, ""))
        self.mock_preferences.assert_not_called()
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_unreadable_or_invalid_preferences_never_break_watch(self):
        for failure in (OSError("file failure"), RuntimeError("bad settings"),
                        ValueError("bad json"), Exception("unexpected")):
            with self.subTest(failure=type(failure).__name__):
                self.mock_preferences.side_effect = failure
                self.assertEqual(self.send("标题", "正文", event="health_warning"), (False, ""))
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_preferences_are_checked_fresh_for_each_notification(self):
        fake = self.serve()
        self.mock_find.return_value = config(fake.url)
        self.mock_preferences.side_effect = [
            push.push_settings.validate({}),
            push.push_settings.validate({"events": {"watch_started": False}}),
            push.push_settings.validate({"enabled": False}),
            push.push_settings.validate({}),
        ]
        results = [self.send("状态", "布防", event="watch_started")[0] for _ in range(4)]
        self.assertEqual(results, [True, False, False, True])
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(self.mock_find.call_count, 2)

    def test_test_push_bypasses_all_preferences_including_invalid_file(self):
        fake = self.serve()
        self.mock_find.return_value = config(fake.url)
        self.mock_preferences.side_effect = RuntimeError("corrupt preferences")
        self.assertEqual(push.send_test(), {"sent": True})
        self.mock_preferences.assert_not_called()
        self.assertEqual(len(fake.requests), 1)

    def test_unexpected_keychain_failure_is_silent(self):
        self.mock_find.side_effect = OSError("must not leak details")
        self.assertEqual(self.send("标题", "正文"), (False, ""))
        self.mock_open.assert_not_called()

    # Management app lifecycle -------------------------------------------

    def patch_now(self, moment):
        """Freeze push.datetime.now() so the body's time line is deterministic."""
        return patch.object(push, "datetime", SimpleNamespace(now=lambda: moment))

    def watch(self, fake, stream=None, sleep=None):
        """Run the watchdog against the in-memory transport, capturing stderr."""
        self.mock_find.return_value = config(fake.url)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = push.app_watch(stream=io.BytesIO(b"") if stream is None else stream,
                                    sleep=(lambda _: None) if sleep is None else sleep)
        return result, err.getvalue()

    def test_app_events_send_expected_title_body_and_priority(self):
        fake = self.serve(200)
        self.mock_find.return_value = config(fake.url)
        moment = datetime(2026, 1, 2, 3, 4, 5)
        with self.patch_now(moment):
            self.assertEqual(push.send_app_event("app_started"), (True, None))
            self.assertEqual(push.send_app_event("app_exited", uptime_seconds=3725),
                             (True, None))

        self.assertEqual(len(fake.requests), 2)
        bodies = [json.loads(request["body"]) for request in fake.requests]
        self.assertEqual([body["title"] for body in bodies],
                         ["[招行值守] 管理 App 已启动", "[招行值守] 管理 App 已退出"])
        self.assertEqual([body["priority"] for body in bodies], [3, 3])
        self.assertEqual(bodies[0]["message"],
                         "2026-01-02 03:04:05\n管理 App 已启动；值守与计划进程独立运行，不受影响。")
        self.assertEqual(bodies[1]["message"].splitlines(),
                         ["2026-01-02 03:04:05",
                          "管理 App 已退出；值守与计划进程继续运行，不受影响。",
                          "本次运行 1 小时 2 分 / 5 秒"])

    def test_app_events_disabled_never_read_credentials_or_send(self):
        for event in ("app_started", "app_exited"):
            with self.subTest(event=event):
                self.mock_preferences.return_value = push.push_settings.validate(
                    {"events": {event: False}})
                self.assertEqual(push.send_app_event(event), (False, "disabled"))
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_app_events_disabled_global_switch_never_reads_credentials(self):
        self.mock_preferences.return_value = push.push_settings.validate({"enabled": False})
        self.assertEqual(push.send_app_event("app_started"), (False, "disabled"))
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_app_events_unconfigured_reports_reason_without_network(self):
        self.mock_find.side_effect = RuntimeError("钥匙串读取失败（系统状态 -25300）。")
        self.assertEqual(push.send_app_event("app_started"), (False, "not_configured"))
        self.assertEqual(push.send_app_event("app_exited"), (False, "not_configured"))
        self.mock_open.assert_not_called()

    def test_unknown_app_events_are_silent(self):
        for event in ("app_typo", "", None, 1, []):
            with self.subTest(event=event):
                self.assertEqual(push.send_app_event(event), (False, "unknown_event"))
        self.mock_preferences.assert_not_called()
        self.mock_find.assert_not_called()
        self.mock_open.assert_not_called()

    def test_send_app_event_never_raises(self):
        with patch.object(push, "_dispatch", side_effect=RuntimeError("boom")):
            self.assertEqual(push.send_app_event("app_started"), (False, "RuntimeError"))

    def test_app_watch_sends_start_then_exit_on_eof(self):
        fake = self.serve(200)
        result, err = self.watch(fake)

        self.assertEqual(result, 0)
        self.assertEqual(len(fake.requests), 2)
        titles = [json.loads(request["body"])["title"] for request in fake.requests]
        self.assertEqual(titles, ["[招行值守] 管理 App 已启动", "[招行值守] 管理 App 已退出"])
        exit_message = json.loads(fake.requests[1]["body"])["message"]
        self.assertIn("管理 App 已退出；值守与计划进程继续运行，不受影响。", exit_message)
        self.assertRegex(exit_message, r"本次运行 \d+ 小时 \d+ 分 / \d+ 秒$")
        lines = err.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0],
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} app_started 已发送$")
        self.assertRegex(lines[1],
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} app_exited 已发送$")

    def test_app_watch_retries_the_exit_notification_three_times(self):
        fake = self.serve(200)
        delays = []
        result, err = self.watch(fake, stream=FlipStream(fake, 500), sleep=delays.append)

        self.assertEqual(result, 0)
        self.assertEqual(delays, [2, 5])
        self.assertEqual(len(fake.requests), 4)     # one start + three exit attempts
        titles = [json.loads(request["body"])["title"] for request in fake.requests]
        self.assertEqual(titles, ["[招行值守] 管理 App 已启动"] +
                         ["[招行值守] 管理 App 已退出"] * 3)
        lines = err.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("app_started 已发送", lines[0])
        self.assertIn("app_exited 发送失败：HTTP 500，2 秒后重试", lines[1])
        self.assertIn("app_exited 发送失败：HTTP 500，5 秒后重试", lines[2])
        self.assertIn("app_exited 发送失败：HTTP 500", lines[3])
        self.assertNotIn("test-token", err)

    def test_app_watch_sends_only_the_start_when_exit_event_is_disabled(self):
        fake = self.serve(200)
        self.mock_preferences.return_value = push.push_settings.validate(
            {"events": {"app_exited": False}})
        delays = []
        result, err = self.watch(fake, sleep=delays.append)

        self.assertEqual(result, 0)
        self.assertEqual(delays, [])
        self.assertEqual(len(fake.requests), 1)
        self.assertIn("管理 App 已启动",
                      json.loads(fake.requests[0]["body"])["title"])
        self.assertIn("app_exited 未发送：该通知已关闭", err)

    def test_app_watch_signal_during_read_sends_the_exit_notification(self):
        fake = self.serve(200)
        original = {signum: signal.getsignal(signum) for signum in push.EXIT_SIGNALS}
        for signum, handler in original.items():
            self.addCleanup(lambda s=signum, h=handler: signal.signal(s, h))
        self.assertTrue(issubclass(push.AppExitTriggered, Exception))

        result, err = self.watch(fake, stream=SignalStream(signal.SIGTERM))

        self.assertEqual(result, 0)
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(json.loads(fake.requests[1]["body"])["title"],
                         "[招行值守] 管理 App 已退出")
        self.assertIn("app_exited 已发送", err)
        for signum, handler in original.items():
            self.assertIs(signal.getsignal(signum), handler)

    def test_signal_handler_raises_app_exit_triggered(self):
        for signum in push.EXIT_SIGNALS:
            with self.subTest(signum=signum), self.assertRaises(push.AppExitTriggered):
                push._raise_app_exit(signum, None)

    def test_app_watch_unconfigured_logs_and_never_retries(self):
        fake = self.serve(200)
        self.mock_find.side_effect = RuntimeError("钥匙串读取失败（系统状态 -25300）。")
        delays = []
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = push.app_watch(stream=io.BytesIO(b""), sleep=delays.append)
        self.assertEqual(result, 0)
        self.assertEqual(delays, [])
        self.assertEqual(fake.requests, [])
        self.mock_open.assert_not_called()
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("app_started 未发送：推送未配置", lines[0])
        self.assertIn("app_exited 未发送：推送未配置", lines[1])

    def test_app_watch_treats_a_broken_pipe_as_exit(self):
        fake = self.serve(200)

        class BrokenStream:
            def read(self, size):
                raise OSError("pipe gone")

        result, _ = self.watch(fake, stream=BrokenStream())
        self.assertEqual(result, 0)
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(json.loads(fake.requests[1]["body"])["title"],
                         "[招行值守] 管理 App 已退出")

    def test_app_watch_requests_plan_pause_after_the_exit_notification(self):
        fake = self.serve(200)
        seen = {}
        self.mock_pause_plan.side_effect = lambda: seen.setdefault(
            "requests_at_pause", len(fake.requests))
        result, _ = self.watch(fake)
        self.assertEqual(result, 0)
        self.mock_pause_plan.assert_called_once()
        self.assertEqual(seen["requests_at_pause"], 2)   # 先发退出通知，再请求暂停

    def test_a_failing_plan_pause_never_changes_the_watchdog_result(self):
        fake = self.serve(200)
        self.mock_pause_plan.side_effect = RuntimeError("boom")
        result, err = self.watch(fake)
        self.assertEqual(result, 0)
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("app_exited 已发送", err)

    def test_plan_pause_helper_logs_one_diagnostic_and_never_raises(self):
        err = io.StringIO()
        with patch("watch_plan.pause_after_app_exit",
                   side_effect=RuntimeError("boom")), \
             contextlib.redirect_stderr(err):
            self.real_pause_plan()
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("计划自动暂停请求失败", lines[0])
        self.assertIn("RuntimeError", lines[0])
        err = io.StringIO()
        with patch("watch_plan.pause_after_app_exit", return_value=True) as pause, \
             contextlib.redirect_stderr(err):
            self.real_pause_plan()
        pause.assert_called_once()
        self.assertEqual(err.getvalue(), "")

    def test_redirect_handler_refuses_replaying_authorization(self):
        request = push.urllib.request.Request("https://ntfy.example.com/",
                                              headers={"Authorization": "Bearer test-token"})
        self.assertIsNone(push._NoRedirect().redirect_request(
            request, None, 302, "Found", {}, "https://other.example.com/"))

    def test_server_url_validation(self):
        self.assertEqual(push._server_url("https://ntfy.example.com"),
                         "https://ntfy.example.com/")
        self.assertEqual(push._server_url("https://ntfy.example.com/sub/"),
                         "https://ntfy.example.com/sub/")
        for bad in ("ntfy.example.com", "http://ntfy.example.com/",
                    "https://ntfy.example.com/?a=1", "https://user:pw@ntfy.example.com/"):
            with self.assertRaises(ValueError):
                push._server_url(bad)
        # Only test loopback HTTP is accepted; real setups must use https.
        self.assertEqual(push._server_url("http://127.0.0.1:8080",
                                          allow_loopback_http=True),
                         "http://127.0.0.1:8080/")


class KeychainPutTest(unittest.TestCase):
    """The overwrite path used when the Keychain item already exists; all ctypes calls are mocked."""

    def test_put_replaces_existing_item_then_verifies_readback(self):
        new = b'{"new":2}'
        with patch.object(push.keychain_store, "find", side_effect=[b'{"old":1}', new]) as find, \
             patch.object(push.keychain_store, "_replace") as replace, \
             patch.object(push.keychain_store, "add") as add:
            push.keychain_store.put(new, service=b"test-service")
        replace.assert_called_once_with(new, service=b"test-service",
                                        account=push.keychain_store.ACCOUNT)
        add.assert_not_called()
        self.assertEqual(find.call_count, 2)

    def test_put_creates_missing_item(self):
        new = b'{"new":2}'
        with patch.object(push.keychain_store, "find",
                          side_effect=[RuntimeError("absent"), new]) as find, \
             patch.object(push.keychain_store, "add", return_value=None) as add, \
             patch.object(push.keychain_store, "_replace") as replace:
            push.keychain_store.put(new, service=b"test-service")
        add.assert_called_once_with(new, service=b"test-service",
                                    account=push.keychain_store.ACCOUNT)
        replace.assert_not_called()
        self.assertEqual(find.call_count, 2)

    def test_put_rejects_readback_mismatch(self):
        with patch.object(push.keychain_store, "find", side_effect=[b'{"old":1}', b"other"]), \
             patch.object(push.keychain_store, "_replace"):
            with self.assertRaises(RuntimeError):
                push.keychain_store.put(b'{"new":2}', service=b"test-service")

    def test_delete_absent_item_is_not_an_error(self):
        with patch.object(push.keychain_store.sec, "SecKeychainFindGenericPassword",
                          return_value=push.keychain_store.ERR_NOT_FOUND):
            self.assertFalse(push.keychain_store.delete(service=b"test-service"))


if __name__ == "__main__":
    unittest.main()
