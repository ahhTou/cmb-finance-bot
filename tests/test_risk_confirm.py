import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import risk_confirm as risk
import fast_buy as fb
import fast_buy_uia2 as fu
from tests.test_open_form import tree


class RiskConfirmTest(unittest.TestCase):
    def test_candidate_requires_exact_product_amount_host_and_front_geometry(self):
        import json
        page = {'url': fb.BUY_URL.format(code='TEST01', amount='0.01'),
                'description': json.dumps(dict(visible=True,screenY=68,width=320,height=524))}
        self.assertTrue(risk.candidate(page,'TEST01','0.010'))
        self.assertFalse(risk.candidate(page,'OTHER','0.01'))
        self.assertFalse(risk.candidate(page,'TEST01','0.1'))
        self.assertFalse(risk.candidate(dict(page,url=page['url'].replace('mobile.cmbchina.com','example.com')),'TEST01','0.01'))
        self.assertFalse(risk.candidate(dict(page,description='invalid'),'TEST01','0.01'))

    def run_purchase(self, dry):
        form = tree('0.01','可用余额','同意协议下一步')
        password = tree('请输入取款密码','招商银行安全输入','￥0.01')
        events=[]
        with patch.object(fu,'device'),patch.object(fu,'dump',return_value=form), \
             patch.object(fu,'open_form',return_value=form),patch.object(fb,'ensure_forward'), \
             patch.object(fu.keychain_store,'load',return_value={'payment_password':'111111'}) as load, \
             patch.object(fu.risk_confirm,'run',side_effect=lambda *a,**k:events.append('risk')) as confirm, \
             patch.object(fu,'wait_for',return_value=password), \
             patch.object(fu,'enter_password',side_effect=lambda *a,**k:events.append('submit' if k.get('submit',True) else 'typed')) as enter, \
             patch.object(fu,'close_password_panel',side_effect=lambda *a,**k:events.append('close')), \
             patch.object(fu,'wait_result',return_value='提交成功') as result,patch.object(fu.time,'sleep'),patch('builtins.print'):
            fu.run('TEST01','0.01',dry_run=dry,before_submit=lambda:events.append('marker'))
            self.assertEqual(confirm.call_count,1)
            load.assert_called_once();enter.assert_called_once()
            if dry:
                result.assert_not_called()
        return events

    def test_dry_run_types_password_but_never_submits_and_closes_panel(self):
        self.assertEqual(self.run_purchase(True),['marker','risk','typed','close'])

    def test_real_path_retains_marker_before_risk_and_single_submit(self):
        self.assertEqual(self.run_purchase(False),['marker','risk','submit'])


class ResultPageTest(unittest.TestCase):
    def test_sold_out_result_page_is_recognized(self):
        # Real page text after 135005A on 11-05 09:00.
        page = tree('额度不足', '购买失败', '额度不足，小招将会火速增加额度')
        with patch.object(fu, 'dump', return_value=page):
            self.assertEqual(fu.wait_result(timeout=1), '购买失败：额度不足')
        with patch.object(fb, 'screen', return_value=page):
            self.assertEqual(fb.read_result(timeout=1), '购买失败：额度不足')

    def test_success_still_wins(self):
        with patch.object(fu, 'dump', return_value=tree('提交成功')):
            self.assertEqual(fu.wait_result(timeout=1), '提交成功')


class KnownPageTest(unittest.TestCase):
    """O1: with the page verify_prepared returned, no WebView scan and one connection."""

    def page(self, amount='0.01'):
        import json
        return {'url': fb.BUY_URL.format(code='TEST01', amount=amount), 'webSocketDebuggerUrl': 'ws://x',
                'description': json.dumps(dict(visible=True, screenY=68, width=320, height=524))}

    def test_known_page_skips_scan_and_rejects_mismatch(self):
        import asyncio
        with patch.object(risk, 'pages') as scan, patch('websockets.connect') as connect:
            with self.assertRaises(fb.Stop):
                asyncio.run(risk.confirm('TEST01', '0.01', page=self.page('0.02')))
            scan.assert_not_called()
            connect.assert_not_called()

    def test_known_page_is_rechecked_on_the_script_connection(self):
        import asyncio
        from unittest.mock import AsyncMock
        ws = MagicMock()
        ws.__aenter__ = AsyncMock(return_value=ws)
        ws.__aexit__ = AsyncMock(return_value=False)
        evaluated = []

        async def evaluate(self, expression):
            evaluated.append(expression)
            return False   # form not visible: must stop before injecting
        with patch.object(risk, 'pages') as scan, patch('websockets.connect', return_value=ws) as connect, \
             patch.object(risk.Client, 'evaluate', evaluate):
            with self.assertRaisesRegex(fb.Stop, '无法唯一确认'):
                asyncio.run(risk.confirm('TEST01', '0.01', page=self.page()))
        scan.assert_not_called()
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(evaluated, [risk.VISIBLE_FORM])
