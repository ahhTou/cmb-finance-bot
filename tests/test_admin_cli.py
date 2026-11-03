import contextlib
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import admin_cli as admin
import night_watch as nw


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        for name, value in [('STATE', state), ('TASK', state / 'task.json'), ('LOG', state / 'watch.log')]:
            self.stack.enter_context(patch.object(nw, name, value))
        self.stack.enter_context(patch.object(admin.keychain_store, 'credential_info', return_value={'state': 'configured'}))
        self.stack.enter_context(patch.object(admin.manage, "status_info", return_value={"emulator": {"running": False}}))
        self.stack.enter_context(patch.object(admin.notify, 'configured', return_value=False))

    def tearDown(self):
        self.stack.close()
        self.tmp.cleanup()

    def task(self, **kwargs):
        data = dict(version=2, phase='armed', task_id='one', generation='one',
                    armed_at='2026-11-03T09:00:00', code='TEST01', amount='0.01',
                    last_tick=(datetime.now() - timedelta(minutes=6)).isoformat())
        data.update(kwargs)
        nw.save_task(data)
        return data

    def call(self, *argv, stdin=''):
        out = io.StringIO()
        with patch.object(sys, 'stdin', io.StringIO(stdin)), contextlib.redirect_stdout(out):
            code = admin.main(list(argv))
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        return code, json.loads(lines[0])

    def test_status_stale_and_no_secrets(self):
        self.task()
        code, data = self.call('status')
        self.assertEqual(code, 0)
        self.assertTrue(data['stale'])
        self.assertEqual(data['credentials'], {'state': 'configured'})
        self.assertNotIn('payment_password', json.dumps(data))

    def test_argv_secret_rejected_without_echo(self):
        code, data = self.call('set-payment-password', '--new', 'do-not-echo')
        self.assertEqual(code, 1)
        self.assertNotIn('do-not-echo', json.dumps(data))

    def test_credential_payload_not_echoed(self):
        code, data = self.call('set-login-pattern', stdin='invalid-sensitive-text')
        self.assertEqual(code, 1)
        self.assertNotIn('invalid-sensitive-text', json.dumps(data))

    def test_credential_writes_blocked(self):
        for phase in ('preparing', 'firing'):
            self.task(phase=phase)
            with patch.object(admin.keychain_store, 'set_login_pattern') as setter:
                code, _ = self.call('set-login-pattern', stdin='{"new":"1235"}')
            self.assertEqual(code, 1)
            setter.assert_not_called()

    def test_credential_stdin_forwarded(self):
        with patch.object(admin.keychain_store, 'set_payment_password') as setter:
            code, data = self.call('set-payment-password', stdin='{"current":"111111","new":"222222"}')
        setter.assert_called_once_with('222222', '111111')
        self.assertEqual((code, data), (0, {'ok': True}))

    def test_stop_blocked_for_active_task(self):
        for phase in ('armed', 'preparing', 'firing'):
            self.task(phase=phase)
            with patch.object(admin.manage, 'stop') as stop:
                code, _ = self.call('emulator', 'stop')
            self.assertEqual(code, 1)
            stop.assert_not_called()

    def test_heartbeat_lifecycle(self):
        code, _ = self.call('agent-heartbeat', '--session', 'test', '--interval', '120')
        self.assertEqual(code, 1)
        self.assertFalse((nw.STATE / 'agent.json').exists())
        task = self.task()
        code, data = self.call('agent-heartbeat', '--session', 'test', '--interval', '120')
        self.assertEqual(code, 0)
        self.assertEqual(data['agent']['state'], 'watching')
        path = nw.STATE / 'agent.json'
        heartbeat = json.loads(path.read_text())
        heartbeat['last_seen'] = (datetime.now() - timedelta(seconds=241)).isoformat()
        admin.atomic_json(path, heartbeat)
        self.assertEqual(admin.agent_info(task)['state'], 'stale')
        task['armed_at'] = 'replacement'
        self.assertEqual(admin.agent_info(task)['state'], 'none')
        self.call('agent-release')
        self.assertFalse(path.exists())

    def test_immediate_real_arm_blocked(self):
        with patch.object(nw, 'arm_task') as arm:
            code, _ = self.call('arm', '--code', 'TEST01', '--amount', '0.01', '--now')
        self.assertEqual(code, 1)
        arm.assert_not_called()

    def test_device_timeouts_are_bounded(self):
        with patch.object(admin.manage, 'status_info', return_value={'emulator': {'running': True}}), \
             patch.object(nw, 'adb', side_effect=TimeoutError()) as adb:
            data = admin.device()
        self.assertFalse(data['booted'])
        self.assertTrue(all(call.kwargs['timeout'] == 5 for call in adb.call_args_list))

    def test_history_ignores_partial_tail(self):
        (nw.STATE / 'history.jsonl').write_text('{"phase":"done"}\n{"partial"')
        code, data = self.call('history')
        self.assertEqual(code, 0)
        self.assertEqual(data['records'], [{'phase': 'done'}])

class SystemParsingTest(unittest.TestCase):
    def test_system_samples_and_tls(self):
        samples = {
            ('/usr/bin/pmset', '-g', 'batt'): "Now drawing from 'AC Power'",
            ('/usr/bin/pmset', '-g'): 'sleep 0\ndisplaysleep 10',
            ('/usr/bin/pmset', '-g', 'assertions'): 'pid 321(caffeinate): [0x01] PreventUserIdleSystemSleep named: test',
            ('/usr/sbin/ioreg', '-r', '-k', 'AppleClamshellState'): 'unrelated machine data\n "AppleClamshellState" = No\n',
        }
        with patch.object(admin, 'command', side_effect=lambda args: samples[tuple(args)]), \
             patch.object(nw, 'load_task', return_value={'pid': 321}), \
             patch.object(admin.socket, 'create_connection'), patch.object(admin.ssl, 'create_default_context'), \
             patch.object(admin.time, 'monotonic', side_effect=[1.0, 1.25]):
            data = admin.system()
        self.assertTrue(data['on_ac'])
        self.assertTrue(data['watch_caffeinate'])
        self.assertTrue(data['network_ok'])
        self.assertEqual(data['network_s'], .25)
        self.assertNotIn('unrelated', data['clamshell'])

    def test_keychain_updates_reject_invalid_values_before_writing(self):
        sample = '{"login_pattern":"1235","payment_password":"111111"}'
        with patch.object(admin.keychain_store, 'find', return_value=sample), \
             patch.object(admin.keychain_store.sec, 'SecKeychainItemModifyAttributesAndData') as write:
            for field, value, current in [('payment_password', '222222', '333333'),
                                           ('login_pattern', '1111', None),
                                           ('payment_password', '123', '111111')]:
                with self.assertRaises(RuntimeError):
                    admin.keychain_store._update(field, value, current, service=b'test-only-service')
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
