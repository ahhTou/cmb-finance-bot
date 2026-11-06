import contextlib
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import admin_cli as admin
import night_watch as nw
import watch_plan


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(patch.object(admin.purchase_settings, 'SETTINGS', state / 'purchase-settings.json'))
        for name, value in [('STATE', state), ('TASK', state / 'task.json'), ('LOG', state / 'watch.log')]:
            self.stack.enter_context(patch.object(nw, name, value))
        self.stack.enter_context(patch.object(admin.keychain_store, 'credential_info', return_value={'state': 'configured'}))
        self.stack.enter_context(patch.object(admin.manage, "status_info", return_value={"emulator": {"running": False}}))
        self.stack.enter_context(patch.object(admin.notify, 'configured', return_value=False))
        self.stack.enter_context(patch.object(admin.favorites, 'PATH', state / 'favorites.json'))

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

    def test_retry_settings_persist_and_reject_invalid_updates(self):
        code, data = self.call('settings')
        self.assertEqual(data['settings'], admin.purchase_settings.DEFAULTS)
        code, data = self.call('settings', '--reopen-deadline', '120', '--drill-form-deadline', '30')
        self.assertEqual(code, 0)
        self.assertEqual(data['settings'], dict(admin.purchase_settings.DEFAULTS, reopen_deadline=120, drill_form_deadline=30))
        for value in ('0', '-1', '301', '1.5'):
            code, _ = self.call('settings', '--reopen-deadline', value)
            self.assertEqual(code, 1)
        self.assertEqual(self.call('settings')[1]['settings'], data['settings'])

    def test_argv_secret_rejected_without_echo(self):
        code, data = self.call('set-payment-password', '--new', 'do-not-echo')
        self.assertEqual(code, 1)
        self.assertNotIn('do-not-echo', json.dumps(data))

    def test_favorites_test_item_cli(self):
        code, data = self.call('favorites', '--add', 'JX040229', '--title', '标题')
        self.assertEqual(code, 0)
        self.assertIsNone(data['test_item'])
        code, data = self.call('favorites', '--set-test', 'JX040229', '--test-amount', '0.02')
        self.assertEqual(code, 0)
        self.assertEqual(data['test_item'],
                         {'code': 'JX040229', 'amount': '0.02', 'title': '标题'})
        code, data = self.call('favorites', '--test')
        self.assertEqual(data['test_item']['amount'], '0.02')
        code, _ = self.call('favorites', '--set-test', 'JX040229')
        self.assertEqual(code, 1)
        code, data = self.call('favorites', '--clear-test')
        self.assertEqual(code, 0)
        self.assertIsNone(data['test_item'])

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

    def test_immediate_real_arm_requires_explicit_payment_confirmation(self):
        with patch.object(nw, 'arm_task', return_value={'dry_run': False}) as arm:
            code, data = self.call('arm', '--code', 'TEST01', '--amount', '100', '--now',
                                   '--confirm-real-payment')
        self.assertEqual(code, 0)
        self.assertFalse(data['task']['dry_run'])
        self.assertEqual(arm.call_args.args, ('TEST01', '100', None, False, None, True))

    def test_immediate_dry_run_needs_no_payment_confirmation(self):
        with patch.object(nw, 'arm_task', return_value={'dry_run': True}) as arm:
            code, _ = self.call('arm', '--code', 'TEST01', '--amount', '100', '--now', '--dry-run')
        self.assertEqual(code, 0)
        self.assertTrue(arm.call_args.args[3])

    def test_arm_passes_redemption_window(self):
        with patch.object(nw, 'arm_task', return_value={'mode': 'redemption'}) as arm:
            code, data = self.call('arm', '--code', 'JX040229', '--amount', '3000',
                                   '--at', '2026-11-04T00:15:00', '--mode', 'redemption',
                                   '--window-minutes', '5')
        self.assertEqual(code, 0)
        self.assertEqual(arm.call_args.kwargs['mode'], 'redemption')
        self.assertEqual(arm.call_args.kwargs['window_minutes'], 5)
        self.assertEqual(data['task']['mode'], 'redemption')

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
        self.assertEqual(data['total'], 1)

    def test_history_limit_and_order(self):
        rows = [{'phase': 'done', 'n': i} for i in range(25)]
        (nw.STATE / 'history.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n')
        code, data = self.call('history', '--limit', '5')
        self.assertEqual(code, 0)
        self.assertEqual([r['n'] for r in data['records']], [24, 23, 22, 21, 20])
        self.assertEqual(data['total'], 25)
        self.assertEqual(data['shown'], 5)
        code, data = self.call('history', '--limit', '0')
        self.assertEqual([r['n'] for r in data['records']][:3], [24, 23, 22])
        self.assertEqual(len(data['records']), 25)

    def test_log_returns_tail_and_path(self):
        nw.LOG.parent.mkdir(parents=True, exist_ok=True)
        nw.LOG.write_text('\n'.join(f'line {i}' for i in range(10)))
        code, data = self.call('log', '--lines', '3')
        self.assertEqual(code, 0)
        self.assertEqual(data['lines'], ['line 7', 'line 8', 'line 9'])
        self.assertEqual(data['total'], 10)
        self.assertEqual(data['path'], str(nw.LOG))

    def test_cancel_blocks_active_task(self):
        self.task(phase='armed')
        with patch.object(admin.subprocess, 'run') as run:
            code, _ = self.call('cancel', '--list')
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_cancel_blocks_live_process_after_terminal_phase(self):
        self.task(phase='done', pid=999)
        with patch.object(admin.nw, 'alive', return_value=True), \
             patch.object(admin.subprocess, 'run') as run:
            code, _ = self.call('cancel', '--list')
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_cancel_rejects_real_without_confirmation(self):
        with patch.object(admin.subprocess, 'run') as run:
            code, _ = self.call('cancel', '--limit', '1')
        self.assertEqual(code, 1)
        run.assert_not_called()

    def test_cancel_list_returns_output(self):
        completed = subprocess.CompletedProcess([], 0, stdout='可撤单 1 笔：\n  - TEST01\n', stderr='')
        with patch.object(admin.subprocess, 'run', return_value=completed) as run:
            code, data = self.call('cancel', '--list')
        self.assertEqual(code, 0)
        self.assertEqual(data['output'], ['可撤单 1 笔：', '  - TEST01'])
        args = run.call_args.args[0]
        self.assertIn('--list', args)
        self.assertIn('--amount', args)

    def test_cancel_real_requires_yes_and_passes_limit(self):
        completed = subprocess.CompletedProcess([], 0, stdout='完成：本次共撤 1 笔。\n', stderr='')
        with patch.object(admin.subprocess, 'run', return_value=completed) as run:
            code, data = self.call('cancel', '--limit', '1', '--yes')
        self.assertEqual(code, 0)
        self.assertEqual(data['output'], ['完成：本次共撤 1 笔。'])
        self.assertIn('--limit', run.call_args.args[0])
        self.assertIn('1', run.call_args.args[0])

    def test_buy_requires_explicit_mode_and_dry_run_is_a_drill(self):
        code, _ = self.call('buy', '--code', 'TEST01', '--amount', '0.01')
        self.assertEqual(code, 1)
        module = types.ModuleType('fast_buy_uia2')
        calls = []
        admin.purchase_settings.save({'drill_form_deadline': 25})
        module.run = lambda code, amount, dry_run, **kwargs: calls.append(
            (code, amount, dry_run, kwargs))
        with patch.dict(sys.modules, {'fast_buy_uia2': module}):
            code, data = self.call('buy', '--code', 'TEST01', '--amount', '0.01', '--dry-run')
        self.assertEqual(code, 0)
        self.assertEqual([(c, a, d) for c, a, d, _ in calls], [('TEST01', '0.01', True)])
        self.assertEqual(calls[0][3]['form_deadline'], 25)
        self.assertEqual(calls[0][3]['settings']['drill_form_deadline'], 25)
        self.assertEqual(data['output'], [])

    def test_confirmed_direct_buy_submits_once_without_arming(self):
        module = types.ModuleType('fast_buy_uia2')
        module.run = Mock(return_value='提交成功')
        admin.purchase_settings.save({'reopen_deadline': 90, 'drill_form_deadline': 15})
        with patch.dict(sys.modules, {'fast_buy_uia2': module}), \
             patch.object(nw, 'arm_task') as arm, patch.object(nw, 'spawn_watch') as spawn:
            code, data = self.call('buy', '--code', 'TEST01', '--amount', '100',
                                   '--confirm-real-payment')
        self.assertEqual(code, 0)
        self.assertEqual(data['result'], '提交成功')
        self.assertEqual(module.run.call_args.args, ('TEST01', '100.00'))
        self.assertEqual(module.run.call_args.kwargs['form_deadline'], 90)
        self.assertEqual(module.run.call_args.kwargs['settings']['reopen_deadline'], 90)
        self.assertFalse(module.run.call_args.kwargs['dry_run'])
        arm.assert_not_called()
        spawn.assert_not_called()
        self.assertFalse(nw.TASK.exists())

    def test_direct_buy_failure_is_not_retried(self):
        module = types.ModuleType('fast_buy_uia2')
        module.run = Mock(side_effect=nw.fast_buy.Stop('结果未知，请查交易记录。'))
        with patch.dict(sys.modules, {'fast_buy_uia2': module}):
            code, data = self.call('buy', '--code', 'TEST01', '--amount', '100',
                                   '--confirm-real-payment')
        self.assertEqual(code, 1)
        self.assertIn('结果未知', data['error'])
        module.run.assert_called_once()

    def test_direct_buy_rejects_conflicting_modes(self):
        code, _ = self.call('buy', '--code', 'TEST01', '--amount', '100',
                            '--confirm-real-payment', '--dry-run')
        self.assertEqual(code, 1)

    def test_real_direct_buy_blocks_live_watch_and_all_active_phases(self):
        module = types.ModuleType('fast_buy_uia2')
        module.run = Mock()
        for phase in ('armed', 'preparing', 'waiting', 'firing', 'done'):
            self.task(phase=phase, pid=123)
            with self.subTest(phase=phase), patch.dict(sys.modules, {'fast_buy_uia2': module}), \
                 patch.object(nw, 'alive', return_value=phase == 'done'):
                code, _ = self.call('buy', '--code', 'TEST01', '--amount', '100',
                                    '--confirm-real-payment')
                self.assertEqual(code, 1)
        module.run.assert_not_called()

    def test_buy_blocks_active_task(self):
        self.task(phase='preparing')
        with patch.dict(sys.modules, {'fast_buy_uia2': types.ModuleType('fast_buy_uia2')}):
            code, _ = self.call('buy', '--code', 'TEST01', '--amount', '0.01', '--dry-run')
        self.assertEqual(code, 1)

    def plan_payload(self, dry_run=True, minutes=90):
        when = (datetime.now() + timedelta(minutes=minutes)).replace(microsecond=0)
        return json.dumps({'dry_run': dry_run, 'items': [
            {'code': 'JX040229', 'amount': '1000', 'at': when.isoformat(),
             'mode': 'first_launch'}]})

    def test_plan_view_and_save(self):
        code, data = self.call('plan')
        self.assertEqual(code, 0)
        self.assertIsNone(data['plan'])
        self.assertEqual(data['problems'], [])
        code, data = self.call('plan-save', stdin=self.plan_payload())
        self.assertEqual(code, 0)
        item = data['plan']['items'][0]
        self.assertEqual((item['code'], item['amount']), ('JX040229', '1000.00'))
        self.assertEqual(data['plan']['phase'], 'idle')
        self.assertIn('prep_at', item)
        self.assertIn('end_at', item)
        code, data = self.call('plan-save', stdin='{"items": [')
        self.assertEqual(code, 1)
        self.assertIn('格式', data['error'])
        self.assertNotIn('Traceback', json.dumps(data))

    def test_plan_start_requires_real_payment_confirmation(self):
        self.assertEqual(self.call('plan-save', stdin=self.plan_payload(dry_run=False))[0], 0)
        with patch.object(nw.subprocess, 'Popen') as popen:
            code, data = self.call('plan-start')
        self.assertEqual(code, 1)
        self.assertIn('真实计划必须明确确认实际付款', data['error'])
        popen.assert_not_called()

    def test_plan_start_spawns_worker_and_rejects_second_start(self):
        self.assertEqual(self.call('plan-save', stdin=self.plan_payload())[0], 0)
        fake = types.SimpleNamespace(pid=4321)
        with patch.object(nw.subprocess, 'Popen', return_value=fake) as popen:
            code, data = self.call('plan-start')
        self.assertEqual(code, 0)
        self.assertEqual(data['plan']['phase'], 'running')
        argv = popen.call_args.args[0]
        self.assertIn('watch_plan.py', ' '.join(argv))
        self.assertIn('--generation', argv)
        self.assertTrue(popen.call_args.kwargs['start_new_session'])
        with patch.object(nw, 'alive', return_value=True):
            code, data = self.call('plan-start')
        self.assertEqual(code, 1)
        self.assertIn('正在运行', data['error'])

    def running_plan(self):
        when = (datetime.now() + timedelta(minutes=90)).replace(microsecond=0)
        import watch_plan as wp
        plan = wp.save({'dry_run': True, 'items': [
            {'code': 'JX040229', 'amount': '1000', 'at': when.isoformat(),
             'mode': 'first_launch'}]})
        plan.update(phase='running', pid=4321, generation='gen-plan',
                    settings_revision=wp._settings_revision())
        wp.save_plan(plan)
        return plan

    def test_plan_running_blocks_other_actions(self):
        self.running_plan()
        commands = [
            ('buy', '--code', 'TEST01', '--amount', '0.01', '--dry-run'),
            ('cancel', '--list'),
            ('emulator', 'stop'),
            ('resume', '--reason', 'test'),
        ]
        for argv in commands:
            with self.subTest(argv=argv), patch.object(nw, 'alive', return_value=True):
                code, data = self.call(*argv)
                self.assertEqual(code, 1)
                self.assertIn('计划正在运行', data['error'])

    def test_plan_disarm_and_clear(self):
        self.assertEqual(self.call('plan-save', stdin=self.plan_payload())[0], 0)
        code, data = self.call('plan-disarm')
        self.assertEqual(code, 1)
        self.assertIn('没有在运行', data['error'])
        code, data = self.call('plan-clear')
        self.assertEqual(code, 0)
        self.assertIsNone(data['plan'])
        self.assertFalse((Path(nw.STATE) / 'plan.json').exists())

class SystemParsingTest(unittest.TestCase):
    def test_caffeinate_child_details_match_only_the_task_pid(self):
        for owner, expected in [(321, True), (3210, False), (99, False)]:
            assertions = ('pid 999(caffeinate): PreventUserIdleSystemSleep\n'
                          f' Details: caffeinate asserting forever (pid {owner})\n')
            with self.subTest(owner=owner), \
                 patch.object(admin, 'command', return_value=assertions), \
                 patch.object(nw, 'load_task', return_value={'pid': 321}), \
                 patch.object(admin.socket, 'create_connection', side_effect=OSError):
                self.assertEqual(admin.system()['watch_caffeinate'], expected)

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
