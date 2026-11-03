import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import fast_buy as fb


class AmountTest(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(fb.parse_amount("5000"), "5000.00")
        self.assertEqual(fb.parse_amount("0.01"), "0.01")
        self.assertEqual(fb.parse_amount("5,000"), "5000.00")
        for bad in ("0", "-1", "0.001", "abc", "nan", "60000"):
            with self.assertRaises(fb.Stop):
                fb.parse_amount(bad)

    def test_password_page_formats(self):
        # 2026-11-02 dry run: 5000 shows as ￥5,000.00; 0.01 as ￥0.01
        self.assertIn(Decimal("5000.00"), fb.yuan_amounts("请输入取款密码 ￥5,000.00 招商银行安全输入"))
        self.assertIn(Decimal("0.01"), fb.yuan_amounts("￥0.01"))
        self.assertIn(Decimal("0.01"), fb.yuan_amounts("¥ 0.01"))

    def test_no_prefix_match(self):
        self.assertNotIn(Decimal("5000"), fb.yuan_amounts("￥50,000.00"))
        self.assertNotIn(Decimal("5000"), fb.yuan_amounts("可用余额 15000.00"))   # no ￥ sign

    def test_form_amount_with_separators(self):
        form = "购买金额 ¥ 5,000.00 可用余额 ￥23,456.78"
        self.assertIn(Decimal("5000.00"), fb.plain_amounts(form))
        self.assertIn(Decimal("0.01"), fb.plain_amounts("¥ 0.01"))
        self.assertNotIn(Decimal("5000.00"), fb.plain_amounts("购买金额 请输入 可用余额 ￥23,456.78"))


if __name__ == "__main__":
    unittest.main()
