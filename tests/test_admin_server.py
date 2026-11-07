"""Run with the server venv: .venv/bin/python -m unittest tests.test_admin_server"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
try:
    from fastapi.testclient import TestClient
    import admin_server as server
except ImportError:  # system Python without the server dependencies
    server = None


def done(payload, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(payload), stderr='')


@unittest.skipIf(server is None, 'fastapi not installed; use .venv/bin/python')
class ServerTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(server.config, token='t0ken', python='/usr/bin/python3')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.auth = {'Authorization': 'Bearer t0ken'}

    def call(self, method, path, **kwargs):
        return self.client.request(method, path, headers=self.auth, **kwargs)

    def test_rejects_missing_or_wrong_token(self):
        self.assertEqual(self.client.get('/api/status').status_code, 401)
        r = self.client.get('/api/status', headers={'Authorization': 'Bearer nope'})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.client.get('/api/health').status_code, 200)

    @patch('admin_server.subprocess.run')
    def test_status_runs_cli_and_returns_json(self, run):
        run.return_value = done({'ok': True, 'task': None})
        r = self.call('GET', '/api/status')
        self.assertEqual(r.json(), {'ok': True, 'task': None})
        argv = run.call_args.args[0]
        self.assertEqual(argv, ['/usr/bin/python3', '-B', 'src/admin_cli.py', 'status'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)

    @patch('admin_server.subprocess.run')
    def test_cli_error_becomes_400_with_message(self, run):
        run.return_value = done({'ok': False, 'error': '模拟器没有在运行。'}, code=1)
        r = self.call('POST', '/api/disarm')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {'error': '模拟器没有在运行。'})

    @patch('admin_server.subprocess.run')
    def test_timeout_and_garbage_output(self, run):
        run.side_effect = subprocess.TimeoutExpired('x', 1)
        self.assertEqual(self.call('POST', '/api/keep-awake').status_code, 504)
        run.side_effect = None
        run.return_value = subprocess.CompletedProcess([], 0, stdout='not json', stderr='')
        self.assertEqual(self.call('POST', '/api/keep-awake').status_code, 502)

    @patch('admin_server.subprocess.run')
    def test_arm_maps_body_to_flags(self, run):
        run.return_value = done({'ok': True, 'task': {}})
        self.call('POST', '/api/arm', json={
            'code': 'JX040229', 'amount': '0.01', 'at': '2026-11-05T09:00:00', 'dry_run': True,
            'prep_minutes': 7, 'settings_revision': 'abc', 'mode': 'redemption'})
        self.assertEqual(run.call_args.args[0][3:], [
            'arm', '--code', 'JX040229', '--amount', '0.01', '--mode', 'redemption',
            '--at', '2026-11-05T09:00:00', '--prep-minutes', '7', '--settings-revision', 'abc',
            '--dry-run'])
        self.call('POST', '/api/arm', json={'code': 'JX040229', 'amount': '1', 'now': True,
                                            'confirm_real_payment': True})
        self.assertEqual(run.call_args.args[0][3:], [
            'arm', '--code', 'JX040229', '--amount', '1', '--mode', 'first_launch', '--now',
            '--confirm-real-payment'])

    @patch('admin_server.subprocess.run')
    def test_favorite_test_endpoints(self, run):
        run.return_value = done({'ok': True, 'favorites': [], 'test_item': None})
        r = self.call('POST', '/api/favorites/test', json={'code': 'JX040229', 'amount': '0.02'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], [
            'favorites', '--set-test', 'JX040229', '--test-amount', '0.02'])
        r = self.call('DELETE', '/api/favorites/test')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['favorites', '--clear-test'])

    @patch('admin_server.subprocess.run')
    def test_buy_and_cancel_flags_and_timeouts(self, run):
        run.return_value = done({'ok': True, 'output': []})
        self.call('POST', '/api/buy', json={'code': 'JX040229', 'amount': '0.01'})
        self.assertEqual(run.call_args.args[0][-1], '--dry-run')
        self.assertEqual(run.call_args.kwargs['timeout'], 420)
        self.call('POST', '/api/cancel', json={'amount': '0.01', 'limit': 2, 'action': 'real'})
        self.assertEqual(run.call_args.args[0][3:], ['cancel', '--amount', '0.01', '--limit', '2', '--yes'])
        self.assertEqual(run.call_args.kwargs['timeout'], 300)

    @patch('admin_server.subprocess.run')
    def test_credentials_go_through_stdin_not_argv(self, run):
        run.return_value = done({'ok': True})
        self.call('POST', '/api/credentials/payment-password', json={'current': '111111', 'new': '222222'})
        argv = run.call_args.args[0]
        self.assertNotIn('111111', ' '.join(argv))
        self.assertNotIn('222222', ' '.join(argv))
        self.assertEqual(json.loads(run.call_args.kwargs['input']), {'current': '111111', 'new': '222222'})

    @patch('admin_server.subprocess.run')
    def test_push_preferences_routes_validate_boolean_options(self, run):
        run.return_value = done({'ok': True, 'enabled': True, 'events': {}, 'catalog': []})
        self.assertEqual(self.call('GET', '/api/push/preferences').status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['push-preferences'])
        body = {'enabled': False, 'events': {'purchase_success': False, 'purchase_unknown': True}}
        self.assertEqual(self.call('PUT', '/api/push/preferences', json=body).status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['push-preferences-save'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']), body)
        run.reset_mock()
        for body in ({'enabled': 'false'}, {'events': {'purchase_success': 1}}, {'unknown': True}):
            self.assertEqual(self.call('PUT', '/api/push/preferences', json=body).status_code, 422)
        run.assert_not_called()

    @patch('admin_server.subprocess.run')
    def test_push_routes_keep_the_token_out_of_argv(self, run):
        run.return_value = done({'ok': True, 'configured': True,
                                 'server': 'https://ntfy.example.com/',
                                 'topic': 'topic-1', 'token_set': True})
        r = self.call('GET', '/api/push')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['push'])

        r = self.call('PUT', '/api/push', json={
            'server': 'https://ntfy.example.com', 'topic': 'topic-1', 'token': 'secret-token'})
        self.assertEqual(r.status_code, 200)
        argv = run.call_args.args[0]
        self.assertEqual(argv[3:], ['push-save'])
        self.assertNotIn('secret-token', ' '.join(argv))
        self.assertEqual(json.loads(run.call_args.kwargs['input']),
                         {'server': 'https://ntfy.example.com',
                          'topic': 'topic-1', 'token': 'secret-token'})

        r = self.call('POST', '/api/push/test')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['push-test'])

        r = self.call('DELETE', '/api/push')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['push-clear'])

    @patch('admin_server.subprocess.run')
    def test_push_token_defaults_to_empty_and_timeout_is_bounded(self, run):
        run.return_value = done({'ok': True, 'configured': False,
                                 'server': None, 'topic': None, 'token_set': False})
        self.call('PUT', '/api/push', json={
            'server': 'https://ntfy.example.com', 'topic': 'topic-1'})
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['token'], '')
        self.assertEqual(run.call_args.kwargs['timeout'], 30)

    @patch('admin_server.subprocess.run')
    def test_plan_routes(self, run):
        run.return_value = done({'ok': True, 'plan': None})
        r = self.call('GET', '/api/plan')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['plan'])
        self.assertEqual(run.call_args.kwargs['timeout'], 30)
        item = {'code': 'JX040229', 'amount': '1000',
                'at': '2026-11-07T09:00:00', 'mode': 'redemption'}
        r = self.call('PUT', '/api/plan', json={'dry_run': True, 'items': [item]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(run.call_args.args[0][3:], ['plan-save'])
        self.assertEqual(json.loads(run.call_args.kwargs['input']),
                         {'dry_run': True, 'items': [item]})
        # mode 缺省为 first_launch。
        r = self.call('PUT', '/api/plan', json={'items': [
            {'code': 'JX040229', 'amount': '1', 'at': '2026-11-07T09:00:00'}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(run.call_args.kwargs['input'])['items'][0]['mode'],
                         'first_launch')
        run.reset_mock()
        self.assertEqual(self.call('POST', '/api/plan/start').status_code, 422)
        self.assertEqual(self.call('POST', '/api/plan/start', json={
            'confirm_real_payment': True}).status_code, 422)
        run.assert_not_called()
        versions = {'plan_id': 'plan-1', 'content_revision': 'content-1',
                    'settings_revision': 'settings-1'}
        self.call('POST', '/api/plan/start', json=versions)
        expected = ['plan-start', '--plan-id', 'plan-1', '--content-revision', 'content-1',
                    '--settings-revision', 'settings-1']
        self.assertEqual(run.call_args.args[0][3:], expected)
        self.call('POST', '/api/plan/start', json=dict(versions, confirm_real_payment=True))
        self.assertEqual(run.call_args.args[0][3:], expected + ['--confirm-real-payment'])
        self.call('POST', '/api/plan/disarm')
        self.assertEqual(run.call_args.args[0][3:], ['plan-disarm'])
        # 停计划进程 + 停当前 watch + 关 App 最坏约 34s，30s 会 504。
        self.assertEqual(run.call_args.kwargs['timeout'], 60)
        self.call('DELETE', '/api/plan')
        self.assertEqual(run.call_args.args[0][3:], ['plan-clear'])

    @patch('admin_server.subprocess.run')
    def test_plan_rejects_unknown_mode(self, run):
        r = self.call('PUT', '/api/plan', json={'items': [
            {'code': 'JX040229', 'amount': '1', 'at': '2026-11-07T09:00:00',
             'mode': 'leech'}]})
        self.assertEqual(r.status_code, 422)
        run.assert_not_called()

    @patch('admin_server.subprocess.run')
    def test_settings_rejects_odd_keys(self, run):
        run.return_value = done({'ok': True, 'settings': {}})
        self.assertEqual(self.call('PUT', '/api/settings', json={'--yes': 1}).status_code, 400)
        self.call('PUT', '/api/settings', json={'first_offset_ms': 200})
        self.assertEqual(run.call_args.args[0][3:], ['settings', '--first-offset-ms', '200'])


if __name__ == '__main__':
    unittest.main()
