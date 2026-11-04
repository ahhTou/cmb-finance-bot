import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import fast_buy as fb
import fast_buy_uia2 as fu
import purchase_page as pp
from tests.test_open_form import Clock, FORM, ERROR, BLANK


def page(**changes):
    result = dict(id='target', origin=2, ready=True, front=True, form=True,
                  error='', url=fb.BUY_URL.format(code='TEST01', amount='3000'))
    result.update(changes)
    return result


class DocumentEvidenceTest(unittest.TestCase):
    def test_new_document_and_exact_product_and_amount_required(self):
        baseline = {('target', 1)}
        self.assertEqual(pp.outcome([page()], baseline, 'TEST01', '3000.00'), 'form')
        for changes in ({'origin': 1}, {'ready': False}, {'front': False},
                        {'form': False}, {'url': fb.BUY_URL.format(code='OTHER1', amount='3000')},
                        {'url': fb.BUY_URL.format(code='TEST01', amount='30')},
                        {'url': 'https://example.org/saentrustbuy.html'}):
            with self.subTest(changes=changes):
                self.assertEqual(pp.outcome([page(**changes)], baseline, 'TEST01', '3000'), '')
        self.assertEqual(pp.outcome(None, baseline, 'TEST01', '3000'), '')
        self.assertEqual(pp.outcome([page(), page(id='ambiguous')], baseline, 'TEST01', '3000'), '')

    def test_stale_sold_out_page_is_not_a_retry_signal(self):
        error = page(url='https://mobile.cmbchina.com/IEntrustFinance/sfoveramount.html',
                     error='额度不足', form=False)
        self.assertEqual(pp.outcome([error], {('target', 2)}, 'TEST01', '3000'), '')
        self.assertEqual(pp.outcome([error], {('target', 1)}, 'TEST01', '3000'), '额度不足')

    def test_background_target_becoming_visible_is_not_fresh(self):
        self.assertEqual(pp.outcome([page()], {('target', None)}, 'TEST01', '3000'), '')

    def test_error_takes_priority_over_form(self):
        self.assertEqual(pp.outcome([page(error='购买失败')], set(), 'TEST01', '3000'), '购买失败')

    def test_fresh_lists_only_new_frontmost_documents(self):
        baseline = {('target', 1)}
        self.assertEqual([p['id'] for p in pp.fresh([page()], baseline)], ['target'])
        self.assertEqual(pp.fresh([page(origin=1)], baseline), [])
        self.assertEqual(pp.fresh([page(front=False)], baseline), [])
        self.assertEqual(pp.fresh(None, baseline), [])

    def run_open(self, snapshots, screens, deadline=20):
        clock = Clock()
        with patch.object(fu.time, 'monotonic', clock.monotonic), \
             patch.object(fu.time, 'sleep', clock.sleep), \
             patch.object(fu.purchase_page, 'snapshot', side_effect=snapshots), \
             patch.object(fu, 'dump', side_effect=screens), \
             patch.object(fb, 'open_buy_link') as opener, patch('builtins.print'):
            try:
                result = fu.open_form('TEST01', '3000', deadline=deadline, wait=15)
            except fb.Stop as exc:
                result = exc
        return result, opener

    def test_old_error_does_not_interrupt_slow_new_form(self):
        old = page(origin=1, form=False, error='购买失败')
        result, opener = self.run_open([[old]] * 40 + [[page()]], [ERROR] * 39 + [FORM])
        self.assertIs(result, FORM)
        self.assertEqual(opener.call_count, 1)

    def test_same_product_stale_form_is_not_accepted(self):
        old = page(origin=1)
        result, opener = self.run_open([[old]] * 30 + [[page()]], [FORM] * 30)
        self.assertIs(result, FORM)
        self.assertEqual(opener.call_count, 1)

    def test_no_cdp_baseline_does_not_open_or_submit(self):
        result, opener = self.run_open(lambda: None, [], deadline=1)
        self.assertIsInstance(result, fb.Stop)
        self.assertIn('CDP', str(result))
        opener.assert_not_called()

    def test_total_deadline_rejects_late_form(self):
        clock = Clock()
        with patch.object(fu.time, 'monotonic', clock.monotonic), \
             patch.object(fu.time, 'sleep', clock.sleep), \
             patch.object(pp, 'snapshot', side_effect=[[], [page()]]), \
             patch.object(fu, 'dump', side_effect=lambda: (clock.sleep(2), FORM)[1]), \
             patch.object(fb, 'open_buy_link'), patch('builtins.print'):
            with self.assertRaises(fb.Stop):
                fu.open_form('TEST01', '3000', deadline=1)


if __name__ == '__main__':
    unittest.main()
