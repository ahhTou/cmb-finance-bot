import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import manage


class ManageStartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        var = Path(self.tmp.name)
        (var / "avd" / "cmb_finance.avd").mkdir(parents=True)
        (var / "avd" / "cmb_finance.ini").write_text("")
        self.state = {}
        self.written = []
        self.calls = []
        self.alive = set()
        self.busy_ports = set()
        self.patches = [
            patch.object(manage, "VAR", var),
            patch.object(manage, "load", side_effect=lambda: dict(self.state)),
            patch.object(manage, "write", side_effect=self.written.append),
            patch.object(manage, "executable", side_effect=lambda rel: rel),
            patch.object(manage, "stop"),
            patch.object(manage.time, "sleep"),
            patch.object(manage.subprocess, "Popen", side_effect=self.popen),
            patch.object(manage, "free", side_effect=lambda port: port not in self.busy_ports),
            patch.object(manage, "owned", side_effect=lambda pid, tokens: pid in self.alive),
            patch.object(manage, "adb_service_pid", return_value=None),
            patch("builtins.print"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def popen(self, command, **kwargs):
        self.calls.append(command)
        if "-L" in command:                       # adb server binds its port
            self.busy_ports.add(manage.ADB_PORT)
        pid = 900 + len(self.calls)
        return types.SimpleNamespace(pid=pid, poll=lambda: None)

    def adb_state(self, pid=321):
        self.state["adb"] = {"pid": pid, "tokens": ["adb", "15039", "nodaemon"]}
        return self.state["adb"]

    def emulator_state(self, pid=654):
        self.state["emulator"] = {"pid": pid, "tokens": ["cmb_finance", "15554"]}
        return self.state["emulator"]

    def kinds(self):
        return ["emulator" if "-avd" in c else "adb" for c in self.calls]

    def test_reuses_a_running_adb_server(self):
        self.adb_state(pid=321)
        self.alive = {321}
        self.busy_ports = {15039}
        manage.start()
        self.assertEqual(self.kinds(), ["emulator"])   # no second adb server
        last = self.written[-1]
        self.assertEqual(last["adb"]["pid"], 321)       # kept for stop()
        self.assertIn("emulator", last)

    def test_drops_stale_records_and_starts_both(self):
        self.adb_state(pid=111)
        self.emulator_state(pid=222)
        self.alive = set()                              # both records are dead
        manage.start()
        self.assertEqual(self.kinds(), ["adb", "emulator"])
        last = self.written[-1]
        self.assertNotEqual(last["adb"]["pid"], 111)

    def test_refuses_when_the_emulator_is_alive(self):
        self.emulator_state(pid=222)
        self.alive = {222}
        with self.assertRaises(RuntimeError) as caught:
            manage.start()
        self.assertIn("模拟器已在运行", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_adopts_an_unrecorded_adb_server(self):
        self.busy_ports = {15039}
        with patch.object(manage, "adb_service_pid", return_value=777):
            manage.start()
        self.assertEqual(self.kinds(), ["emulator"])
        self.assertEqual(self.written[-1]["adb"], {"pid": 777, "tokens": ["adb", "15039", "nodaemon"]})

    def test_refuses_a_foreign_port_owner(self):
        self.busy_ports = {15039}
        with self.assertRaises(RuntimeError) as caught:
            manage.start()
        self.assertIn("15039", str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_refuses_busy_emulator_ports(self):
        self.busy_ports = {15554}
        with self.assertRaises(RuntimeError) as caught:
            manage.start()
        self.assertIn("模拟器端口", str(caught.exception))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
