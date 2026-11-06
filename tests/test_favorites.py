import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import favorites


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = favorites.PATH
        favorites.PATH = Path(self.folder.name) / "favorites.json"

    def tearDown(self):
        favorites.PATH = self.original
        self.folder.cleanup()

    def test_add_list_rename_and_remove(self):
        favorites.add("JX040229", "招睿丰和 30 天")
        favorites.add("133045A", "月月宝")
        self.assertEqual([row["code"] for row in favorites.load()], ["JX040229", "133045A"])
        favorites.add("jx040229", "改名")
        self.assertEqual(len(favorites.load()), 2)
        self.assertEqual(favorites.load()[0]["title"], "改名")
        favorites.remove("JX040229")
        self.assertEqual([row["code"] for row in favorites.load()], ["133045A"])

    def test_invalid_code_or_title_is_rejected(self):
        for code, title in (("abc", "标题"), ("JX04-0229", "标题"), ("JX040229", ""),
                            ("JX040229", "   "), ("JX040229", "长" * 41)):
            with self.subTest(code=code, title=title), self.assertRaises(RuntimeError):
                favorites.add(code, title)

    def test_corrupt_file_loads_empty(self):
        favorites.PATH.write_text("not json", encoding="utf-8")
        self.assertEqual(favorites.load(), [])

    def test_saved_file_is_owner_only(self):
        favorites.add("JX040229", "标题")
        self.assertEqual(favorites.PATH.stat().st_mode & 0o777, 0o600)

    def test_file_ignores_unknown_fields_and_bad_rows(self):
        favorites.PATH.write_text(
            '[{"code":"JX040229","title":"好","amount":"1"},{"code":"x","title":"坏"},5]',
            encoding="utf-8")
        self.assertEqual(favorites.load(), [{"code": "JX040229", "title": "好"}])

    def test_test_item_is_saved_and_only_one_row_has_it(self):
        favorites.add("JX040229", "招睿丰和 30 天")
        favorites.add("133045A", "月月宝")
        favorites.set_test("jx040229", "0.01")
        self.assertEqual(favorites.test_item(),
                         {"code": "JX040229", "amount": "0.01", "title": "招睿丰和 30 天"})
        favorites.set_test("133045A", "100")
        self.assertEqual([row.get("test_amount") for row in favorites.load()], [None, "100.00"])
        self.assertEqual(favorites.test_item()["code"], "133045A")

    def test_renaming_keeps_the_test_item(self):
        favorites.add("JX040229", "旧标题")
        favorites.set_test("JX040229", "0.02")
        favorites.add("jx040229", "新标题")
        self.assertEqual(favorites.test_item(),
                         {"code": "jx040229", "amount": "0.02", "title": "新标题"})

    def test_test_item_requires_a_favourite_and_a_valid_amount(self):
        with self.assertRaises(RuntimeError):
            favorites.set_test("JX040229", "0.01")
        favorites.add("JX040229", "标题")
        for amount in ("", "0", "-1", "1.234", "abc"):
            with self.subTest(amount=amount), self.assertRaises(RuntimeError):
                favorites.set_test("JX040229", amount)
        self.assertIsNone(favorites.test_item())
        # No upper limit: above the old 50000 cap is accepted.
        favorites.set_test("JX040229", "60000")
        self.assertEqual(favorites.test_item(),
                         {"code": "JX040229", "amount": "60000.00", "title": "标题"})
        favorites.set_test("JX040229", "50000.01")
        self.assertEqual(favorites.test_item()["amount"], "50000.01")

    def test_clear_and_remove_clear_the_test_item(self):
        favorites.add("JX040229", "标题")
        favorites.set_test("JX040229", "0.01")
        favorites.clear_test()
        self.assertIsNone(favorites.test_item())
        favorites.set_test("JX040229", "0.01")
        favorites.remove("JX040229")
        self.assertIsNone(favorites.test_item())

    def test_load_normalizes_and_keeps_only_one_test_item(self):
        favorites.PATH.write_text(
            '[{"code":"A123","title":"a","test_amount":"0.01"},'
            '{"code":"B123","title":"b","test_amount":2},'
            '{"code":"C123","title":"c","test_amount":"bad"}]',
            encoding="utf-8")
        rows = favorites.load()
        self.assertEqual(rows[0]["test_amount"], "0.01")
        self.assertNotIn("test_amount", rows[1])
        self.assertNotIn("test_amount", rows[2])
        self.assertEqual(favorites.test_item(), {"code": "A123", "amount": "0.01", "title": "a"})


if __name__ == "__main__":
    unittest.main()
