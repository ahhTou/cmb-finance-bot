"""Notification routing: pure mocks and source validation, no credentials or network."""
import ast
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import night_watch as nw
import push_settings


class NotificationEventsTest(unittest.TestCase):
    def test_alert_logs_even_if_phone_delivery_is_filtered(self):
        with patch.object(nw.push, 'send', return_value=False) as send, \
             patch.object(nw, 'log') as log:
            nw.alert('购买失败', '未提交', 5, event='purchase_failed')
        log.assert_called_once_with('通知：购买失败')
        self.assertEqual(send.call_args.kwargs, {'event': 'purchase_failed'})
        self.assertEqual(send.call_args.args[2], 5)

    def test_result_notifications_follow_transaction_outcomes(self):
        cases = [
            ({'phase': 'done', 'result': '提交成功'}, 'purchase_success'),
            ({'phase': 'done', 'result': '购买失败：额度不足'}, 'purchase_failed'),
            ({'phase': 'done', 'result': '未提交：查询窗口已结束'}, 'purchase_failed'),
            ({'phase': 'done', 'result': '演练完成', 'dry_run': True}, 'drill_completed'),
            ({'phase': 'done', 'result': '结果未知', 'fired_at': 'set'}, 'purchase_unknown'),
            ({'phase': 'firing', 'fired_at': 'set'}, 'purchase_unknown'),
        ]
        for task, event in cases:
            with self.subTest(task=task):
                self.assertEqual(nw.purchase_event(task), event)

    def test_every_watch_and_plan_alert_declares_a_known_event(self):
        observed = set()
        for filename in ('night_watch.py', 'watch_plan.py'):
            tree = ast.parse((ROOT / 'src' / filename).read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call = node.func
                is_alert = (isinstance(call, ast.Name) and call.id == 'alert') or (
                    isinstance(call, ast.Attribute) and call.attr == 'alert')
                if is_alert:
                    event = next((item.value for item in node.keywords if item.arg == 'event'), None)
                    self.assertIsNotNone(event, f'{filename}:{node.lineno} has no event')
                    if isinstance(event, ast.Constant):
                        self.assertIn(event.value, push_settings.EVENT_KEYS)
                        observed.add(event.value)
                # Thread targets carry their event in kwargs instead of calling alert here.
                if isinstance(call, ast.Attribute) and call.attr == 'Thread':
                    target = next((item.value for item in node.keywords if item.arg == 'target'), None)
                    if isinstance(target, ast.Name) and target.id == 'alert':
                        kwargs = next((item.value for item in node.keywords if item.arg == 'kwargs'), None)
                        self.assertIsInstance(kwargs, ast.Dict)
                        event = ast.literal_eval(kwargs)['event']
                        self.assertIn(event, push_settings.EVENT_KEYS)
                        observed.add(event)
        self.assertTrue({'watch_cancelled', 'plan_cancelled', 'preparation_ready', 'query_started'} <= observed)

    def test_mock_catalog_matches_backend_notification_choices(self):
        mock = json.loads((ROOT / 'desktop/src/mocks/push-preferences.json').read_text())
        self.assertEqual(mock['catalog'], list(push_settings.EVENTS))
        self.assertEqual({key: mock[key] for key in ('enabled', 'events')}, push_settings.validate({}))


if __name__ == '__main__':
    unittest.main()
