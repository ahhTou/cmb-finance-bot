import contextlib
from datetime import datetime, timedelta
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import timed_buy as t


def page(*items):
    root = ET.Element("hierarchy")
    for text, kind in items:
        ET.SubElement(root, "node", {"text": text, "class": kind, "bounds": "[20,100][220,150]"})
    return root


TEXT = "android.widget.TextView"
EDIT = "android.widget.EditText"
results = page(("手机银行搜索", TEXT), ("理财 133045A", TEXT))
detail = page(("133045A", TEXT), ("购买，点击可跳转至购买页", TEXT))
empty_form = page(("133045A", TEXT), ("购买金额", TEXT), ("请输入", EDIT))
filled = page(("0.01, 请输入", EDIT), ("同意协议下一步", TEXT))
risk = page(("一键输入", TEXT), ("本人已阅读风险揭示", TEXT))
risk_done = page(("本人已阅读风险揭示", EDIT), ("确认", TEXT))
auth = page(("请输入取款密码", TEXT), ("招商银行安全输入", TEXT), ("￥0.01", TEXT),
            ("完成", TEXT), ("确定", TEXT), *[(str(n), TEXT) for n in range(10)])
for node in auth:
    if node.get("text") == "确定":
        node.set("bounds", "[100,200][200,250]")
success = page(("申请购买提交成功", TEXT))


class TimedBuyTest(unittest.TestCase):
    def run_flow(self, result=success):
        pages = [results, results, detail, empty_form, filled, filled, risk, risk_done,
                 auth, auth, auth, result]
        taps = []
        with patch.object(t, "screen", side_effect=pages), patch.object(t, "tap", side_effect=taps.append), \
             patch.object(t, "adb", return_value=""), patch.object(t, "send_commands") as send, \
             patch.object(t, "get_password", return_value="123456"), \
             patch.object(t.time, "sleep", return_value=None), \
             patch.object(t.time, "monotonic", side_effect=[1, 3] + [4] * 100), \
             contextlib.redirect_stdout(io.StringIO()):
            t.run("133045A", "0.01", datetime.now() + timedelta(seconds=1), 5)
        return taps, send

    def test_single_submit_success(self):
        taps, send = self.run_flow()
        self.assertEqual(taps.count((150, 225)), 1)
        send.assert_called_once()

    def test_identity_and_amount_boundaries(self):
        self.assertTrue(t.contains_code(results, "133045A"))
        self.assertFalse(t.contains_code(page(("133045AB", TEXT)), "133045A"))
        self.assertTrue(t.matches_amount("￥0.01", "0.01"))
        self.assertFalse(t.matches_amount("￥10.01", "0.01"))

    def test_missing_keyboard_stops(self):
        with self.assertRaises(t.Stop):
            t.security_keys(page(("请输入取款密码", TEXT)))


if __name__ == "__main__":
    unittest.main()
