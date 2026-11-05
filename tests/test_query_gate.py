import asyncio
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import query_gate as gate
import purchase_settings as settings
import fast_buy


class GateTest(unittest.TestCase):
    def test_schedule_offsets_and_window(self):
        when = datetime(2026, 11, 5, 9)
        start, end = gate.schedule(when, 'first_launch', {})
        self.assertEqual(start, when + timedelta(milliseconds=200))
        self.assertEqual((end-start).total_seconds(), 90)
        start, end = gate.schedule(when, 'redemption', {})
        self.assertEqual(start, when - timedelta(milliseconds=200))
        self.assertEqual(end, start + timedelta(minutes=2))

    def test_settings_migration_and_invalid_bounds(self):
        migrated = settings.validate({'reopen_deadline': 90})
        self.assertEqual(migrated['cold_start_minutes'], 7)
        self.assertEqual(migrated['first_max_retries'], 5)
        self.assertEqual(migrated['reopen_deadline'], 90)
        # 0 is the valid "立即" setting; -1, booleans and >60 stay rejected.
        self.assertEqual(settings.validate({'cold_start_minutes': 0})['cold_start_minutes'], 0)
        self.assertEqual(settings.validate({'cold_start_minutes': 60})['cold_start_minutes'], 60)
        for value in ({'cold_start_minutes': -1}, {'cold_start_minutes': True},
                      {'cold_start_minutes': 61},
                      {'first_max_retries': -1}, {'irregular_window_minutes': 61},
                      {'irregular_retry_min_ms': 251, 'irregular_retry_max_ms': 250},
                      {'irregular_advance_ms': -1}, {'unknown': 1},
                      {'irregular_slow_min_ms': 2001},
                      {'irregular_idle_min_ms': 5000, 'irregular_idle_max_ms': 4000},
                      {'irregular_burst_seconds': 66},
                      {'irregular_ramp_seconds': 91}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                settings.validate(value)

    def test_backoff_defaults_and_config(self):
        values = settings.validate({})
        self.assertEqual((values['irregular_retry_min_ms'], values['irregular_retry_max_ms']), (300, 500))
        self.assertEqual(gate.backoff(values), dict(
            burstMs=60000, rampMs=65000, idleMs=90000,
            burst=[300, 500], slow=[1000, 2000], idle=[2500, 4000]))

    def test_blank_target_logs_in_before_waiting_for_the_container(self):
        target = {'id': 'T', 'url': gate.STAGING_URL,
                  'description': json.dumps({'visible': True, 'width': 320, 'height': 640})}
        login = MagicMock(return_value=True)
        with patch.object(gate, 'pages', side_effect=[[], [target]]), \
             patch.object(fast_buy, 'adb'):
            self.assertIs(asyncio.run(gate.blank_target(login=login)), target)
        self.assertEqual(login.call_count, 1)

    def test_prepared_form_uses_raw_quota_and_never_reopens_or_marks_over_quota(self):
        import fast_buy_uia2 as fu
        from tests.test_open_form import tree
        root = tree('3000', '可用余额', '同意协议下一步')
        marker, verify = MagicMock(), MagicMock(return_value=root)
        with patch.object(fu.keychain_store, 'load', return_value={'payment_password': '111111'}), \
             patch.object(fu, 'device'), patch.object(fu, 'dump', return_value=root), \
             patch.object(fu.fast_buy, 'ensure_forward'), patch.object(fu, 'open_form') as opener, \
             patch('builtins.print'):
            with self.assertRaises(fast_buy.Stop):
                fu.run('TEST01', '3000', prepared_form=root, product_quota='2999.99',
                       verify_form=verify, before_submit=marker)
        verify.assert_called_once()
        opener.assert_not_called()
        marker.assert_not_called()

    def test_wait_binding_wakes_on_page_signal_and_times_out_otherwise(self):
        ws = MagicMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=[
            json.dumps({'method': 'Runtime.consoleAPICalled', 'params': {}}),
            json.dumps({'method': 'Runtime.bindingCalled', 'params': {'name': gate.READY_BINDING}})])
        client = gate.Client(ws)
        self.assertTrue(asyncio.run(client.wait_binding(gate.READY_BINDING, 1)))
        self.assertEqual(client.bindings, set())

        async def silent():
            await asyncio.sleep(10)
        ws.recv = AsyncMock(side_effect=silent)
        self.assertFalse(asyncio.run(gate.Client(ws).wait_binding(gate.READY_BINDING, .05)))

    def test_binding_seen_during_a_call_is_kept_for_the_next_wait(self):
        ws = MagicMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(side_effect=[
            json.dumps({'method': 'Runtime.bindingCalled', 'params': {'name': gate.READY_BINDING}}),
            json.dumps({'id': 1, 'result': {}})])
        client = gate.Client(ws)

        async def flow():
            await client.call('Runtime.evaluate')
            return await client.wait_binding(gate.READY_BINDING, .01)
        self.assertTrue(asyncio.run(flow()))

    def test_verify_prepared_reuses_tree_and_reports_page(self):
        import fast_buy_uia2 as fu
        from tests.test_open_form import tree
        task = {'code': 'TEST01', 'amount': '3000', 'mode': 'first_launch',
                'query_gate_target': 'T', 'query_gate_token': 'tok', 'query_gate_origin': 1.0}
        url = fast_buy.BUY_URL.format(code='TEST01', amount='3000')
        page = {'id': 'T', 'url': url, 'webSocketDebuggerUrl': 'ws://x',
                'description': json.dumps({'visible': True, 'screenY': 68})}
        state = {'token': 'tok', 'origin': 1.0, 'form': True, 'hidden': False,
                 'status': 'ready', 'url': url}
        root = tree('可用余额', '同意协议下一步')
        found = {}
        with patch.object(gate, 'pages', return_value=[page]), \
             patch('asyncio.run', side_effect=lambda coro: (coro.close(), state)[1]), \
             patch.object(fu, 'dump') as dump:
            self.assertIs(gate.verify_prepared(task, root=root, found=found), root)
        dump.assert_not_called()
        self.assertIs(found['page'], page)

    def test_paused_unexpected_request_is_failed_before_send(self):
        ws = MagicMock()
        ws.send = AsyncMock()
        ws.recv = AsyncMock(return_value=json.dumps({
            'method': 'Fetch.requestPaused', 'params': {'requestId': 'unsafe'}}))
        with self.assertRaises(fast_buy.Stop):
            asyncio.run(gate.Client(ws).call('Runtime.evaluate'))
        sent = [json.loads(c.args[0]) for c in ws.send.call_args_list]
        self.assertEqual(sent[-1]['method'], 'Fetch.failRequest')
        self.assertEqual(sent[-1]['params']['requestId'], 'unsafe')
