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


if __name__ == "__main__":
    unittest.main()
