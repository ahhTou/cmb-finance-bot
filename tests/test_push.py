import contextlib
from email.message import Message
import io
import json
import sys
import threading
import urllib.error
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import push


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
