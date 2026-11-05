import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import secure_input


def page(*resource_ids):
    root = ET.fromstring("<hierarchy></hierarchy>")
    for resource_id in resource_ids:
        ET.SubElement(root, "node", {"resource-id": resource_id})
    return root


class LoginPageTest(unittest.TestCase):
    def test_both_login_contexts_share_the_gesture_views(self):
        # Captured 2026-11-05: the 我的 overlay (PBMainActivity) and the
        # purchase login (PBLoginActivity) both expose these two views.
        self.assertTrue(secure_input.login_page(page(*secure_input.LOGIN_VIEW_IDS)))

    def test_one_view_or_the_normal_my_page_is_not_login(self):
        self.assertFalse(secure_input.login_page(page(secure_input.LOGIN_VIEW_IDS[0])))
        normal = ET.fromstring(
            '<hierarchy><node text="我的头像"/><node text="更多选项"/></hierarchy>')
        self.assertFalse(secure_input.login_page(normal))
        self.assertFalse(secure_input.login_page(None))

    def test_login_draws_only_on_the_gesture_page(self):
        root = page(*secure_input.LOGIN_VIEW_IDS)
        with patch.object(secure_input, "screen_protected", return_value=True), \
             patch.object(secure_input, "adb", return_value="Physical size: 320x640"), \
             patch.object(secure_input, "send_commands") as send, \
             patch("builtins.print"):
            secure_input.login("1235", root=root)
        self.assertEqual(send.call_count, 1)

    def test_login_refuses_a_text_only_page_without_drawing(self):
        normal = ET.fromstring(
            '<hierarchy><node text="我的头像"/><node text="更多选项"/></hierarchy>')
        with patch.object(secure_input, "screen_protected", return_value=True), \
             patch.object(secure_input, "adb", return_value="Physical size: 320x640") as adb, \
             patch.object(secure_input, "send_commands") as send:
            with self.assertRaises(RuntimeError):
                secure_input.login("1235", root=normal)
        send.assert_not_called()
        adb.assert_not_called()


if __name__ == "__main__":
    unittest.main()
