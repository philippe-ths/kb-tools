import unittest

from kb.changes import (
    AppendLog,
    ChangeError,
    ChangeSet,
    WriteIndex,
    WritePage,
)


class WritePageGuardTest(unittest.TestCase):
    def test_accepts_flat_wiki_page(self):
        op = WritePage("wiki/concept-new", "# New")
        self.assertEqual(op.page_id, "wiki/concept-new")
        self.assertEqual(op.target, "wiki/concept-new")

    def test_strips_md_suffix(self):
        self.assertEqual(WritePage("wiki/foo.md", "x").page_id, "wiki/foo")

    def test_rejects_raw_target(self):
        with self.assertRaises(ChangeError):
            WritePage("raw/evidence", "x")

    def test_rejects_index_as_page(self):
        with self.assertRaises(ChangeError):
            WritePage("index", "x")

    def test_rejects_log_as_page(self):
        with self.assertRaises(ChangeError):
            WritePage("log", "x")

    def test_rejects_nested_wiki_path(self):
        with self.assertRaises(ChangeError):
            WritePage("wiki/sub/page", "x")

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ChangeError):
            WritePage("wiki/../raw/x", "x")

    def test_rejects_absolute_and_empty(self):
        for bad in ("/wiki/x", "", "wiki/"):
            with self.assertRaises(ChangeError):
                WritePage(bad, "x")


class AppendLogGuardTest(unittest.TestCase):
    def test_accepts_nonempty(self):
        self.assertEqual(AppendLog("## entry").target, "log")

    def test_rejects_blank(self):
        for bad in ("", "   ", "\n\t"):
            with self.assertRaises(ChangeError):
                AppendLog(bad)


class ChangeSetSerializationTest(unittest.TestCase):
    def test_roundtrip_through_dicts(self):
        original = ChangeSet(
            (
                WritePage("wiki/a", "# A"),
                WriteIndex("# Index"),
                AppendLog("## log entry"),
            )
        )
        restored = ChangeSet.from_dicts(original.to_dicts())
        self.assertEqual(restored, original)

    def test_from_dicts_rejects_unknown_op(self):
        with self.assertRaises(ChangeError):
            ChangeSet.from_dicts([{"op": "delete_page", "page_id": "wiki/a"}])

    def test_from_dicts_rejects_non_list(self):
        with self.assertRaises(ChangeError):
            ChangeSet.from_dicts({"op": "write_index", "text": "x"})

    def test_empty_changeset_is_falsy(self):
        self.assertFalse(ChangeSet())
        self.assertTrue(ChangeSet((WriteIndex("x"),)))


if __name__ == "__main__":
    unittest.main()
