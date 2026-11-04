import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fast_buy as fb
import fast_buy_uia2 as fu


def tree(*texts):
    return ET.fromstring("<hierarchy>" + "".join(
        f'<node text="{t}" content-desc="" />' for t in texts) + "</hierarchy>")


FORM = tree("理财购买", "可用余额 ￥34,567.89", "同意协议下一步")
BLANK = tree()
ERROR = tree("TOPI101W - 购买失败，当前时间不在产品交易开放期")


class Clock:
    """monotonic() that advances on every sleep()."""
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.now += max(s, 0.01)


class OpenFormTest(unittest.TestCase):
    def run_open(self, screens, shown=lambda code: True, **opts):
        clock = Clock()
        screens = iter(screens)
        current = [BLANK]
        def read_screen():
            current[0] = next(screens)
            return current[0]
        def state(*args):
            if not shown('133045A'):
                return ''
            text = ' '.join(fb.label(n) for n in current[0].iter('node'))
            return next((e for e in fu.purchase_page.ERRORS if e in text),
                        'form' if '可用余额' in text else '')
        with patch.object(fu.time, "monotonic", clock.monotonic), \
             patch.object(fu.time, "sleep", clock.sleep), \
             patch.object(fb, "open_buy_link") as opener, \
             patch.object(fu.purchase_page, "snapshot", return_value=[]), \
             patch.object(fu.purchase_page, "outcome", side_effect=state), \
             patch.object(fb, "js_prefill_and_buy") as gobuy, \
             patch.object(fu, "dump", side_effect=read_screen), \
             patch("builtins.print"):
            try:
                return fu.open_form("133045A", "0.01", **opts), opener, gobuy, clock
            except fb.Stop as exc:
                return exc, opener, gobuy, clock

    def test_form_on_first_open(self):
        root, opener, gobuy, _ = self.run_open([BLANK, FORM])
        self.assertIs(root, FORM)
        self.assertEqual(opener.call_count, 1)
        gobuy.assert_not_called()

    def test_reopens_when_form_is_slow(self):
        never = [BLANK] * 1000
        root, opener, _, _ = self.run_open(never[:70] + [FORM])
        self.assertIs(root, FORM)
        self.assertEqual(opener.call_count, 2)

    def test_error_page_reopens_after_gap(self):
        root, opener, _, clock = self.run_open([ERROR] * 20 + [FORM])
        self.assertIs(root, FORM)
        self.assertEqual(opener.call_count, 2)
        self.assertLess(clock.now, fu.REOPEN_AFTER)   # did not wait the full 5 s

    def test_gives_up_after_deadline(self):
        exc, opener, _, clock = self.run_open([BLANK] * 100000)
        self.assertIsInstance(exc, fb.Stop)
        self.assertGreaterEqual(clock.now, fu.REOPEN_DEADLINE)
        self.assertLessEqual(opener.call_count, fu.REOPEN_DEADLINE / fu.REOPEN_AFTER + 2)

    def test_other_products_form_is_not_accepted(self):
        # A stale 133045A form on top must not count as the JX040229 form.
        checks = iter([False] * 30 + [True])
        root, _, _, clock = self.run_open([FORM] * 31, shown=lambda code: next(checks))
        self.assertIs(root, FORM)
        self.assertGreater(clock.now, 30 * 0.08 - 0.01)

    def test_window_parameters_bound_a_long_retry(self):
        # Redemption reopens for minutes; the deadline must stop the loop.
        exc, opener, _, clock = self.run_open([BLANK] * 100000, deadline=5.0,
                                              wait=1.5, gap=0.95)
        self.assertIsInstance(exc, fb.Stop)
        self.assertGreaterEqual(clock.now, 5.0)
        self.assertLess(clock.now, 7.0)
        self.assertLessEqual(opener.call_count, 5)

    def test_error_page_waits_for_the_gap(self):
        # A page younger than `gap` may still be the previous error page.
        root, opener, _, clock = self.run_open([ERROR] * 13 + [FORM], deadline=60.0,
                                              wait=1.5, gap=0.95)
        self.assertIs(root, FORM)
        self.assertGreaterEqual(clock.now, 0.95)
        self.assertEqual(opener.call_count, 2)

    def test_form_before_the_gap_is_still_accepted(self):
        root, opener, _, clock = self.run_open([BLANK, FORM], wait=1.5, gap=2.0)
        self.assertIs(root, FORM)
        self.assertLess(clock.now, 0.5)

    def test_login_page_stops_instead_of_polling_forever(self):
        login = tree("我的头像", "更多选项", "招商银行")
        with patch.object(fu, "screen_protected", return_value=True):
            exc, opener, _, _ = self.run_open([login] * 4, wait=1.5, gap=0.95)
        self.assertIsInstance(exc, fb.Stop)
        self.assertIn("登录页", str(exc))

    def test_normal_page_with_same_labels_is_not_a_login_page(self):
        # 我的 also shows these labels; only the blanked frame means login.
        mine = tree("我的头像", "更多选项", "账户总览")
        with patch.object(fu, "screen_protected", return_value=False):
            exc, _, _, _ = self.run_open([mine] * 40, wait=1.0, gap=0.5, deadline=1.4)
        self.assertIsInstance(exc, fb.Stop)
        self.assertNotIn("登录页", str(exc))

    def test_never_calls_gobuy(self):
        _, opener, gobuy, _ = self.run_open([FORM])
        opener.assert_called_once_with("133045A", "0.01")
        gobuy.assert_not_called()


class RiskStepTest(unittest.TestCase):
    """After 同意协议下一步 the page may reject the amount instead of asking
    for the password; that must be reported, not hidden as a timeout."""

    def run_wait(self, screens, timeout=2.0):
        clock = Clock()
        screens = iter(screens)
        with patch.object(fu.time, "monotonic", clock.monotonic), \
             patch.object(fu.time, "sleep", clock.sleep), \
             patch.object(fu, "dump", side_effect=lambda: next(screens)):
            try:
                return fu.wait_risk_or_error(timeout)
            except fb.Stop as exc:
                return exc

    def test_risk_dialog(self):
        self.assertEqual(self.run_wait([BLANK, tree("一键输入")]), "")

    def test_rejection_dialog_is_reported(self):
        dialog = tree("温馨提示", "TQHF0I4 - 购买金额不能小于产品单笔购买下限", "确认")
        self.assertIn("TQHF0I4", self.run_wait([BLANK, dialog]))

    def test_timeout(self):
        self.assertIsInstance(self.run_wait([BLANK] * 100, 1.0), fb.Stop)


class QuotaTest(unittest.TestCase):
    def test_over_quota_stops_before_marker_or_next_in_real_and_dry_run(self):
        for dry_run in (False, True):
            for quota, stops in [('200.06', True), ('0', True), ('3000', False),
                                 ('3000.01', False), (None, False)]:
                with self.subTest(quota=quota, dry_run=dry_run):
                    root = tree('3000', *([] if quota is None else [f'单笔可购买额度{quota}元']))
                    d, marker = MagicMock(), MagicMock()
                    with patch.object(fu.keychain_store, 'load', return_value={'payment_password': '111111'}), \
                         patch.object(fu, 'device', return_value=d), \
                         patch.object(fu, 'dump', return_value=BLANK), \
                         patch.object(fb, 'ensure_forward'), \
                         patch.object(fu.purchase_settings, 'load', return_value={'reopen_deadline': 87}), \
                         patch.object(fu, 'open_form', return_value=root) as opener, \
                         patch.object(fu, 'wait_risk_or_error', side_effect=fb.Stop('test boundary')), \
                         patch('builtins.print'):
                        with self.assertRaises(fb.Stop) as exc:
                            fu.run('TEST01', '3000', dry_run=dry_run, before_submit=marker)
                    opener.assert_called_once()
                    self.assertEqual(opener.call_args.kwargs['deadline'], 87)
                    if stops:
                        self.assertIn('高于页面可购额度', str(exc.exception))
                        marker.assert_not_called()
                        d.assert_not_called()
                    else:
                        marker.assert_called_once()
                        d.assert_called_once_with(text='同意协议下一步')

    def test_reads_single_order_quota(self):
        from decimal import Decimal
        self.assertEqual(fu.quota_amount(tree("单笔可购买额度200.06元")), Decimal("200.06"))
        self.assertEqual(fu.quota_amount(tree("单笔可购买额度 ￥1,200.50 元")), Decimal("1200.50"))
        self.assertEqual(fu.quota_amount(tree("单笔可购买额度12万元")), Decimal("120000"))

    def test_no_quota_label_is_unknown_not_zero(self):
        self.assertIsNone(fu.quota_amount(tree("可用余额 ￥1.00", "同意协议下一步")))


class BuyUrlTest(unittest.TestCase):
    def test_url_carries_code_and_amount(self):
        url = fb.BUY_URL.format(code="JX040229", amount="5000.00")
        self.assertIn("CodeInn=JX040229&FndInn=JX040229&CurDepositBuyAmount=5000.00", url)
        self.assertTrue(url.startswith("https://mobile.cmbchina.com/IEntrustFinance/"
                                       "subsidiaryfinancing/saentrustbuy.html?SaaCod=D07"))

    def test_buy_link_goes_through_app_scheme(self):
        with patch.object(fb, "adb") as adb:
            fb.open_buy_link("JX040229", "5000.00")
        args = adb.call_args[0]
        self.assertEqual(args[:5], ("shell", "am", "start", "-a", "android.intent.action.VIEW"))
        self.assertIn("cmbmobilebank://cmbls/FunctionJump/?action=gourl&src=https%3A%2F%2F", args[6])
        self.assertIn("CodeInn%3DJX040229", args[6])
        self.assertEqual(args[7], "cmb.pb")


if __name__ == "__main__":
    unittest.main()
