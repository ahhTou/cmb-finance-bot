import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

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
    def run_open(self, screens, shown=lambda code: True):
        clock = Clock()
        screens = iter(screens)
        with patch.object(fu.time, "monotonic", clock.monotonic), \
             patch.object(fu.time, "sleep", clock.sleep), \
             patch.object(fb, "open_buy_link") as opener, \
             patch.object(fb, "buy_page_shown", side_effect=shown), \
             patch.object(fb, "js_prefill_and_buy") as gobuy, \
             patch.object(fu, "dump", side_effect=lambda: next(screens)), \
             patch("builtins.print"):
            try:
                return fu.open_form("133045A", "0.01"), opener, gobuy, clock
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
        self.assertGreater(clock.now, fu.REOPEN_DEADLINE)
        self.assertLessEqual(opener.call_count, fu.REOPEN_DEADLINE / fu.REOPEN_AFTER + 2)

    def test_other_products_form_is_not_accepted(self):
        # A stale 133045A form on top must not count as the JX040229 form.
        checks = iter([False] * 30 + [True])
        root, _, _, clock = self.run_open([FORM] * 31, shown=lambda code: next(checks))
        self.assertIs(root, FORM)
        self.assertGreater(clock.now, 30 * 0.08 - 0.01)

    def test_never_calls_gobuy(self):
        _, opener, gobuy, _ = self.run_open([FORM])
        opener.assert_called_once_with("133045A", "0.01")
        gobuy.assert_not_called()


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
