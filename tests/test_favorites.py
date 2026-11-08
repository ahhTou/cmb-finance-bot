import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import favorites


def quota(**fields):
    """One valid quota-time entry; tests override only the fields under test."""
    entry = {"kind": "regular", "weekdays": [1], "time": "09:00"}
    entry.update(fields)
    return entry


QUOTA_ROWS = [
    {"id": "q1a2b3c4d5", "kind": "issue", "date": "2026-11-07", "time": "09:00",
     "amount_wan": "5000", "note": "首发 5000 万"},
    {"id": "q6f7a8b9c0", "kind": "bargain", "weekdays": [1, 2, 3, 4, 5, 6],
     "time": "00:15", "note": "额度不定"},
    {"id": "q0d1e2f3a4", "kind": "regular", "weekdays": [1, 2, 3, 4],
     "time": "09:00", "amount_wan": "100", "note": ""},
]


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

    def stored(self):
        return json.loads(favorites.PATH.read_text(encoding="utf-8"))

    def seed_settings(self):
        favorites.save([{"code": "JX040229", "title": "标题", "test_amount": "0.02",
                         "quota_times": [dict(entry) for entry in QUOTA_ROWS]}])

    def test_public_constants_match_the_contract(self):
        self.assertEqual(favorites.MAX_ITEMS, 100)
        self.assertEqual(favorites.MAX_QUOTA_TIMES, 50)
        self.assertEqual(favorites.TITLE_MAX, 40)
        self.assertEqual(favorites.NOTE_MAX, 100)
        self.assertEqual(favorites.KINDS, ("issue", "bargain", "regular"))
        self.assertTrue(favorites.CODE.fullmatch("A123"))
        self.assertEqual(favorites.ANNUALIZED_MIN, -100)
        self.assertEqual(favorites.ANNUALIZED_MAX, 1000)

    def test_v1_file_without_quota_times_still_loads(self):
        favorites.PATH.write_text(
            '[{"code":"JX040229","title":"旧收藏"},'
            '{"code":"133045A","title":"月月宝","test_amount":"0.01"}]',
            encoding="utf-8")
        self.assertEqual(favorites.load(), [
            {"code": "JX040229", "title": "旧收藏"},
            {"code": "133045A", "title": "月月宝", "test_amount": "0.01"},
        ])
        self.assertEqual(favorites.test_item(),
                         {"code": "133045A", "amount": "0.01", "title": "月月宝"})

    def test_quota_times_save_and_load_round_trip(self):
        rows = [{
            "code": "JX040229", "title": "理财 A", "test_amount": "0.01",
            "quota_times": [
                {"id": "q1a2b3c4d5", "kind": "issue", "date": "2026-11-07",
                 "time": "09:00", "amount_wan": "5000", "note": "首发 5000 万"},
                {"id": "q6f7a8b9c0", "kind": "bargain",
                 "weekdays": [6, 1, 2, 3, 4, 5, 6], "time": "00:15",
                 "note": "额度不定"},
                {"id": "q0d1e2f3a4", "kind": "regular", "weekdays": [4, 3, 2, 1],
                 "time": "09:00", "amount_wan": "100", "note": ""},
            ],
        }]
        expected = [{
            "code": "JX040229", "title": "理财 A", "test_amount": "0.01",
            "quota_times": [
                {"id": "q1a2b3c4d5", "kind": "issue", "date": "2026-11-07",
                 "time": "09:00", "amount_wan": "5000", "note": "首发 5000 万"},
                {"id": "q6f7a8b9c0", "kind": "bargain",
                 "weekdays": [1, 2, 3, 4, 5, 6], "time": "00:15",
                 "note": "额度不定"},
                {"id": "q0d1e2f3a4", "kind": "regular", "weekdays": [1, 2, 3, 4],
                 "time": "09:00", "amount_wan": "100"},
            ],
        }]
        self.assertEqual(favorites.save(rows), expected)
        self.assertEqual(favorites.load(), expected)
        self.assertEqual(self.stored(), expected)
        self.assertEqual(favorites.test_item(),
                         {"code": "JX040229", "amount": "0.01", "title": "理财 A"})

    def test_quota_time_fields_are_omitted_when_empty(self):
        saved = favorites.save([{
            "code": "JX040229", "title": "标题", "quota_times": [
                {"id": "qIssue1", "kind": "issue", "date": "2026-11-07",
                 "time": "09:00", "weekdays": [1, 2], "amount_wan": None,
                 "note": "   "},
                {"id": "qRepeat1", "kind": "bargain", "date": "2026-11-07",
                 "weekdays": [7, 1], "time": "00:15"},
                {"id": "qRepeat2", "kind": "regular", "date": "2026-11-07",
                 "weekdays": [5], "time": "09:00", "amount_wan": "0.50"},
            ],
        }])
        issue, bargain, regular = saved[0]["quota_times"]
        self.assertEqual(issue, {"id": "qIssue1", "kind": "issue",
                                 "date": "2026-11-07", "time": "09:00"})
        self.assertNotIn("weekdays", issue)
        self.assertNotIn("amount_wan", issue)
        self.assertNotIn("note", issue)
        self.assertEqual(bargain, {"id": "qRepeat1", "kind": "bargain",
                                   "weekdays": [1, 7], "time": "00:15"})
        self.assertNotIn("date", bargain)
        self.assertEqual(regular, {"id": "qRepeat2", "kind": "regular",
                                   "weekdays": [5], "time": "09:00",
                                   "amount_wan": "0.5"})
        self.assertNotIn("date", regular)

    def test_bad_quota_entries_are_dropped_individually(self):
        favorites.PATH.write_text(json.dumps([
            {"code": "JX040229", "title": "好收藏", "quota_times": [
                {"id": "qKEEP01", "kind": "regular", "weekdays": [1],
                 "time": "09:00"},
                {"kind": "weekly", "weekdays": [1], "time": "09:00"},
                "junk",
                {"kind": "issue", "date": "2026-02-30", "time": "09:00"},
                {"kind": "bargain", "weekdays": [], "time": "00:15"},
                {"kind": "regular", "weekdays": [2], "time": "8:00"},
                {"kind": "regular", "weekdays": [3], "time": "10:00",
                 "amount_wan": "1.234"},
                {"kind": "regular", "weekdays": [4], "time": "11:00"},
            ]},
            {"code": "133045A", "title": "另一条"},
            {"code": "bad", "title": "坏行"},
        ], ensure_ascii=False), encoding="utf-8")
        rows = favorites.load()
        self.assertEqual([row["code"] for row in rows], ["JX040229", "133045A"])
        self.assertEqual(len(rows[0]["quota_times"]), 2)
        self.assertEqual(rows[0]["quota_times"][0],
                         {"id": "qKEEP01", "kind": "regular",
                          "weekdays": [1], "time": "09:00"})
        self.assertRegex(rows[0]["quota_times"][1]["id"], r"^q[a-f0-9]{10}$")
        self.assertEqual(rows[0]["quota_times"][1]["weekdays"], [4])
        self.assertNotIn("quota_times", rows[1])
        saved = favorites.save(rows)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]["quota_times"], rows[0]["quota_times"])

    def test_quota_ids_are_kept_or_generated(self):
        saved = favorites.save([{
            "code": "JX040229", "title": "标题", "quota_times": [
                quota(id="Keep-1_aZ"),
                quota(),
                quota(id="bad id"),
                quota(id="Keep-1_aZ"),
                quota(id="x" * 25),
            ],
        }])
        ids = [entry["id"] for entry in saved[0]["quota_times"]]
        self.assertEqual(ids[0], "Keep-1_aZ")
        self.assertEqual(len(ids), len(set(ids)))
        for generated in ids[1:]:
            self.assertRegex(generated, r"^q[a-f0-9]{10}$")
        self.assertEqual(favorites.load(), saved)
        self.assertEqual(favorites.save(saved), saved)

    def test_save_item_keeps_valid_ids(self):
        rows = favorites.save_item({"code": "JX040229", "title": "标题",
                                    "quota_times": [
                                        quota(id="Keep-1_aZ"),
                                        quota(id="dup-01"),
                                        quota(id="dup-01"),
                                    ]})
        ids = [entry["id"] for entry in rows[0]["quota_times"]]
        self.assertEqual(ids[0], "Keep-1_aZ")
        self.assertEqual(ids[1], "dup-01")
        self.assertRegex(ids[2], r"^q[a-f0-9]{10}$")
        self.assertEqual(favorites.load(), rows)

    def test_quota_time_validation_failures_keep_the_file(self):
        cases = [
            ("非法 kind", [quota(kind="daily")], "额度时间类型不正确。"),
            ("kind 为 null", [quota(kind=None)], "额度时间类型不正确。"),
            ("缺 time", [{"kind": "regular", "weekdays": [1]}],
             "额度时间格式不正确。"),
            ("time 24:00", [quota(time="24:00")], "额度时间格式不正确。"),
            ("time 9:00", [quota(time="9:00")], "额度时间格式不正确。"),
            ("time 09:60", [quota(time="09:60")], "额度时间格式不正确。"),
            ("time 非字符串", [quota(time=900)], "额度时间格式不正确。"),
            ("首发缺 date", [{"kind": "issue", "time": "09:00"}],
             "额度日期格式不正确。"),
            ("首发 date 非真实日期",
             [{"kind": "issue", "date": "2026-02-30", "time": "09:00"}],
             "额度日期格式不正确。"),
            ("首发 date 格式不对",
             [{"kind": "issue", "date": "2026-1-1", "time": "09:00"}],
             "额度日期格式不正确。"),
            ("周重复缺 weekdays", [{"kind": "bargain", "time": "00:15"}],
             "额度星期格式不正确。"),
            ("周重复空 weekdays", [quota(weekdays=[])], "额度星期格式不正确。"),
            ("星期 0", [quota(weekdays=[0])], "额度星期格式不正确。"),
            ("星期 8", [quota(weekdays=[8])], "额度星期格式不正确。"),
            ("星期非 int", [quota(weekdays=[1, "2"])], "额度星期格式不正确。"),
            ("星期是 bool", [quota(weekdays=[True])], "额度星期格式不正确。"),
            ("备注超长", [quota(note="长" * 101)], "备注最多 100 个字符。"),
            ("条目不是 dict", ["junk"], "额度时间格式不正确。"),
            ("条目是 null", [None], "额度时间格式不正确。"),
            ("超过 50 条", [quota()] * 51, "额度时间最多 50 条。"),
            ("quota_times 不是 list", "junk", "额度时间格式不正确。"),
            ("quota_times 是 null", None, "额度时间格式不正确。"),
        ]
        for label, entries, message in cases:
            with self.subTest(label=label):
                self.seed_settings()
                before = favorites.PATH.read_text(encoding="utf-8")
                with self.assertRaises(RuntimeError) as caught:
                    favorites.save_item({"code": "JX040229", "title": "改名",
                                         "quota_times": entries})
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(favorites.PATH.read_text(encoding="utf-8"),
                                 before)

    def test_quota_amount_wan_validation_and_normalization(self):
        for value, expected in [("5000", "5000"), (5000, "5000"), (0.5, "0.5"),
                                ("0.50", "0.5"), (5000.50, "5000.5"),
                                ("1000000", "1000000"), (1000000, "1000000"),
                                ("0.01", "0.01")]:
            with self.subTest(value=value):
                saved = favorites.save_item({
                    "code": "JX040229", "title": "标题",
                    "quota_times": [quota(amount_wan=value)]})
                self.assertEqual(saved[0]["quota_times"][0]["amount_wan"],
                                 expected)
        favorites.save([])
        before = favorites.PATH.read_text(encoding="utf-8")
        for value in (0, "0", -1, "-0.01", "1.234", 1000000.01, 1000001,
                      "abc", "", True, "NaN"):
            with self.subTest(bad_value=value):
                favorites.save([])
                with self.assertRaises(RuntimeError) as caught:
                    favorites.save_item({
                        "code": "JX040229", "title": "标题",
                        "quota_times": [quota(amount_wan=value)]})
                self.assertEqual(str(caught.exception), "额度数量格式不正确。")
                self.assertEqual(favorites.PATH.read_text(encoding="utf-8"),
                                 before)

    def test_save_item_requires_title_for_new_codes(self):
        self.assertFalse(favorites.PATH.exists())
        for payload, message in [
            ({"code": "NEW001"}, "新增收藏需要同时提供标题。"),
            ({"code": "NEW001", "title": ""}, "标题须为 1–40 个字符。"),
            ({"code": "NEW001", "title": "   "}, "标题须为 1–40 个字符。"),
            ({"code": "bad", "title": "标题"},
             "产品代码须为 4–20 位字母或数字。"),
            ("not a dict", "收藏设置格式无效。"),
        ]:
            with self.subTest(payload=payload), \
                    self.assertRaises(RuntimeError) as caught:
                favorites.save_item(payload)
            self.assertEqual(str(caught.exception), message)
            self.assertFalse(favorites.PATH.exists())
        rows = favorites.save_item({"code": "NEW001", "title": " 新收藏 ",
                                    "unknown": 1})
        self.assertEqual(rows, [{"code": "NEW001", "title": "新收藏"}])
        self.assertEqual(self.stored(), rows)

    def test_save_item_appends_new_codes_and_updates_in_place(self):
        favorites.save([{"code": "AAAA", "title": "a"},
                        {"code": "BBBB", "title": "b"}])
        rows = favorites.save_item({"code": "CCCC", "title": "c"})
        self.assertEqual([row["code"] for row in rows],
                         ["AAAA", "BBBB", "CCCC"])
        rows = favorites.save_item({"code": "bbbb", "title": "新 b"})
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["title"], "新 b")
        self.assertEqual(rows[1]["code"].lower(), "bbbb")
        self.assertEqual(rows[2]["code"], "CCCC")

    def test_save_item_partial_updates_keep_the_rest(self):
        original_ids = [entry["id"] for entry in QUOTA_ROWS]

        self.seed_settings()
        rows = favorites.save_item({"code": "JX040229",
                                    "quota_times": [quota(time="10:00")]})
        self.assertEqual(rows[0]["title"], "标题")
        self.assertEqual(rows[0]["test_amount"], "0.02")
        self.assertEqual([entry["time"] for entry in rows[0]["quota_times"]],
                         ["10:00"])

        self.seed_settings()
        rows = favorites.save_item({"code": "JX040229", "title": "新标题"})
        self.assertEqual(rows[0]["title"], "新标题")
        self.assertEqual(rows[0]["test_amount"], "0.02")
        self.assertEqual([entry["id"] for entry in rows[0]["quota_times"]],
                         original_ids)

        self.seed_settings()
        rows = favorites.save_item({"code": "JX040229", "test_amount": "1.5"})
        self.assertEqual(rows[0]["test_amount"], "1.50")
        self.assertEqual(rows[0]["title"], "标题")
        self.assertEqual([entry["id"] for entry in rows[0]["quota_times"]],
                         original_ids)

    def test_save_item_moves_the_test_item(self):
        favorites.save([{"code": "A123", "title": "a", "test_amount": "0.01"},
                        {"code": "B123", "title": "b"}])
        rows = favorites.save_item({"code": "B123", "test_amount": "2"})
        self.assertEqual(rows[0].get("test_amount"), None)
        self.assertEqual(rows[1]["test_amount"], "2.00")
        self.assertEqual(favorites.test_item(),
                         {"code": "B123", "amount": "2.00", "title": "b"})
        rows = favorites.save_item({"code": "A123", "test_amount": "0.03"})
        self.assertEqual(rows[0]["test_amount"], "0.03")
        self.assertNotIn("test_amount", rows[1])
        self.assertEqual(favorites.test_item()["code"], "A123")

    def test_save_item_null_or_empty_clears_only_this_test_amount(self):
        for value in (None, ""):
            with self.subTest(value=value):
                favorites.save([{"code": "A123", "title": "a",
                                 "test_amount": "0.01"},
                                {"code": "B123", "title": "b"}])
                rows = favorites.save_item({"code": "B123",
                                            "test_amount": value})
                self.assertEqual(rows[0]["test_amount"], "0.01")
                self.assertEqual(favorites.test_item()["code"], "A123")
                rows = favorites.save_item({"code": "A123",
                                            "test_amount": value})
                self.assertNotIn("test_amount", rows[0])
                self.assertEqual(rows[1]["title"], "b")
                self.assertIsNone(favorites.test_item())

    def test_save_item_empty_quota_times_clears_the_list(self):
        self.seed_settings()
        rows = favorites.save_item({"code": "JX040229", "quota_times": []})
        self.assertNotIn("quota_times", rows[0])
        self.assertEqual(rows[0]["title"], "标题")
        self.assertEqual(rows[0]["test_amount"], "0.02")
        self.assertNotIn("quota_times", self.stored()[0])

    def test_save_item_enforces_max_items_but_updates_existing(self):
        favorites.save([{"code": f"C{index:04d}", "title": "t"}
                        for index in range(favorites.MAX_ITEMS)])
        before = favorites.PATH.read_text(encoding="utf-8")
        with self.assertRaises(RuntimeError) as caught:
            favorites.save_item({"code": "NEW999", "title": "x"})
        self.assertEqual(str(caught.exception), "收藏数量已达上限。")
        self.assertEqual(favorites.PATH.read_text(encoding="utf-8"), before)
        rows = favorites.save_item({"code": "c0000", "title": "改名"})
        self.assertEqual(len(rows), favorites.MAX_ITEMS)
        self.assertEqual(rows[0]["title"], "改名")

    def test_annualized_text_normalizes_display_values(self):
        cases = [("3", "3.00%"), (3, "3.00%"), ("3.00%", "3.00%"),
                 ("2.85%", "2.85%"), (" 2.85 %", "2.85%"),
                 ("-1.2", "-1.20%"), ("-1.20%", "-1.20%"),
                 (2.85, "2.85%"), (0, "0.00%"), ("0.5", "0.50%"),
                 ("3%", "3.00%"), ("-100", "-100.00%"),
                 (1000, "1000.00%"), ("1000.00%", "1000.00%")]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(favorites.annualized_text(value), expected)

    def test_annualized_text_rejects_invalid_values(self):
        format_error = "近期年化格式不正确。"
        range_error = "近期年化须为 -100 到 1000 之间的数字，最多两位小数。"
        for value in (True, False, "abc", "", "  ", None, [], {}):
            with self.subTest(value=value), \
                    self.assertRaises(RuntimeError) as caught:
                favorites.annualized_text(value)
            self.assertEqual(str(caught.exception), format_error)
        for value in ("1.234", "2.855", "-100.01", "1000.01", 1001, -101):
            with self.subTest(value=value), \
                    self.assertRaises(RuntimeError) as caught:
                favorites.annualized_text(value)
            self.assertEqual(str(caught.exception), range_error)

    def test_recent_annualized_loaded_and_bad_values_dropped(self):
        favorites.PATH.write_text(json.dumps([
            {"code": "AA01", "title": "a", "recent_annualized": "2.85%"},
            {"code": "BB02", "title": "b", "recent_annualized": "3"},
            {"code": "CC03", "title": "c", "recent_annualized": 2.85},
            {"code": "DD04", "title": "d", "recent_annualized": "abc"},
            {"code": "EE05", "title": "e", "recent_annualized": "1.234"},
            {"code": "FF06", "title": "f", "recent_annualized": "1001"},
            {"code": "GG07", "title": "g", "recent_annualized": True},
            {"code": "HH08", "title": "h"},
            {"code": "II09", "title": "i", "recent_annualized": None},
            {"code": "JJ10", "title": "j", "recent_annualized": ""},
        ], ensure_ascii=False), encoding="utf-8")
        self.assertEqual(favorites.load(), [
            {"code": "AA01", "title": "a", "recent_annualized": "2.85%"},
            {"code": "BB02", "title": "b", "recent_annualized": "3.00%"},
            {"code": "CC03", "title": "c", "recent_annualized": "2.85%"},
            {"code": "DD04", "title": "d"},
            {"code": "EE05", "title": "e"},
            {"code": "FF06", "title": "f"},
            {"code": "GG07", "title": "g"},
            {"code": "HH08", "title": "h"},
            {"code": "II09", "title": "i"},
            {"code": "JJ10", "title": "j"},
        ])

    def test_recent_annualized_save_round_trip(self):
        saved = favorites.save([
            {"code": "JX040229", "title": "标题", "recent_annualized": " 2.85 %"},
            {"code": "133045A", "title": "无年化"},
            {"code": "999999", "title": "非法年化", "recent_annualized": "abc"},
        ])
        self.assertEqual(saved, [
            {"code": "JX040229", "title": "标题", "recent_annualized": "2.85%"},
            {"code": "133045A", "title": "无年化"},
            {"code": "999999", "title": "非法年化"},
        ])
        self.assertEqual(favorites.load(), saved)
        self.assertEqual(self.stored(), saved)

    def test_save_item_sets_overwrites_and_clears_recent_annualized(self):
        rows = favorites.save_item({"code": "JX040229", "title": "标题",
                                    "recent_annualized": " 2.85 %"})
        self.assertEqual(rows[0]["recent_annualized"], "2.85%")
        self.assertEqual(self.stored()[0]["recent_annualized"], "2.85%")

        rows = favorites.save_item({"code": "NEW001", "title": "新收藏",
                                    "recent_annualized": 3})
        self.assertEqual(rows[-1], {"code": "NEW001", "title": "新收藏",
                                    "recent_annualized": "3.00%"})

        rows = favorites.save_item({"code": "JX040229",
                                    "recent_annualized": "-1.2"})
        self.assertEqual(rows[0]["recent_annualized"], "-1.20%")

        rows = favorites.save_item({"code": "JX040229", "title": "改名"})
        self.assertEqual(rows[0]["recent_annualized"], "-1.20%")

        for value in (None, ""):
            with self.subTest(clear=value):
                favorites.save([{"code": "JX040229", "title": "标题",
                                 "recent_annualized": "2.85%"}])
                rows = favorites.save_item({"code": "JX040229",
                                            "recent_annualized": value})
                self.assertNotIn("recent_annualized", rows[0])
                self.assertNotIn("recent_annualized", self.stored()[0])
                self.assertEqual(favorites.load()[0]["title"], "标题")

    def test_recent_annualized_is_independent_of_other_settings(self):
        self.seed_settings()
        rows = favorites.save_item({"code": "JX040229",
                                    "recent_annualized": "2.85%"})
        self.assertEqual(rows[0]["test_amount"], "0.02")
        self.assertEqual([entry["id"] for entry in rows[0]["quota_times"]],
                         [entry["id"] for entry in QUOTA_ROWS])

        rows = favorites.save_item({"code": "JX040229",
                                    "quota_times": [quota(time="10:00")]})
        self.assertEqual(rows[0]["recent_annualized"], "2.85%")
        self.assertEqual(rows[0]["test_amount"], "0.02")

        rows = favorites.save_item({"code": "JX040229", "test_amount": "1.5"})
        self.assertEqual(rows[0]["recent_annualized"], "2.85%")
        self.assertEqual(rows[0]["title"], "标题")

    def test_save_item_invalid_recent_annualized_keeps_the_file(self):
        self.seed_settings()
        before = favorites.PATH.read_text(encoding="utf-8")
        for value, message in [("abc", "近期年化格式不正确。"),
                               ("1.234", "近期年化须为 -100 到 1000 之间的"
                                         "数字，最多两位小数。"),
                               (True, "近期年化格式不正确。")]:
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError) as caught:
                    favorites.save_item({"code": "JX040229", "title": "改名",
                                         "recent_annualized": value})
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(favorites.PATH.read_text(encoding="utf-8"),
                                 before)
        with self.assertRaises(RuntimeError):
            favorites.save_item({"code": "NEW001", "title": "新",
                                 "recent_annualized": "abc"})
        self.assertEqual(favorites.PATH.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
