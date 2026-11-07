import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import push


class Handler(BaseHTTPRequestHandler):
    """Local fake ntfy server: records each request and answers with a set status."""

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            self.server.requests.append(
                {"path": self.path, "headers": self.headers, "body": body})
            if self.server.delay:
                self.server.waited.set()
                threading.Event().wait(self.server.delay)
            self.send_response(self.server.status)
            if self.server.location:
                self.send_header("Location", self.server.location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        except OSError:
            pass    # the client already timed out and closed the socket

    def log_message(self, *args):
        pass


class FakeNtfy:
    def __init__(self, status=200, delay=0.0, location=None):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.status = status
        self.httpd.delay = delay
        self.httpd.location = location
        self.httpd.waited = threading.Event()
        self.httpd.requests = []
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    @property
    def requests(self):
        return self.httpd.requests

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2)


def config(server, topic="test-topic", token="test-token"):
    return json.dumps({"server": server, "topic": topic, "token": token}).encode("utf-8")


class PushTest(unittest.TestCase):
    def setUp(self):
        self.find = patch.object(push.keychain_store, "find")
        self.mock_find = self.find.start()
        self.addCleanup(self.find.stop)

    def serve(self, status=200, delay=0.0, location=None):
        fake = FakeNtfy(status=status, delay=delay, location=location)
        self.addCleanup(fake.close)
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
        # The fake did receive the request, so this is a real timeout path.
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
        item = object()

        def add(payload, service):
            saved["payload"] = payload
            saved["service"] = service
            return item

        out = io.StringIO()
        with patch.object(push.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["https://ntfy.example.com", "topic-1"]), \
             patch.object(push.getpass, "getpass", return_value="secret-token"), \
             patch.object(push.keychain_store, "add", side_effect=add), \
             patch.object(push.keychain_store, "core"), \
             patch.object(push, "send", return_value=True) as send, \
             contextlib.redirect_stdout(out):
            push.setup()

        self.assertEqual(saved["service"], push.SERVICE)
        self.assertEqual(json.loads(saved["payload"]),
                         {"server": "https://ntfy.example.com/",
                          "topic": "topic-1", "token": "secret-token"})
        self.assertEqual(send.call_args.args[0], "测试推送")
        self.assertIn("测试推送已发送", out.getvalue())

    def test_setup_rejects_http_server_and_non_tty(self):
        with patch.object(push.sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["http://ntfy.example.com", "topic-1"]), \
             patch.object(push.getpass, "getpass", return_value="secret-token"), \
             patch.object(push.keychain_store, "add") as add:
            with self.assertRaises(RuntimeError):
                push.setup()
        add.assert_not_called()
        with patch.object(push.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(RuntimeError):
                push.setup()

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


if __name__ == "__main__":
    unittest.main()
