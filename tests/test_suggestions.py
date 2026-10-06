import json
import tempfile
import unittest
from pathlib import Path

from kb.suggestions import SUGGESTIONS_NAME, SuggestionLog


class SuggestionLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log = SuggestionLog.for_root(self.root, now=lambda: "2026-06-30T10:21:03Z")

    def _lines(self):
        if not self.log.path.exists():
            return []
        return self.log.path.read_text(encoding="utf-8").splitlines()

    def test_for_root_targets_dotfile_at_root(self):
        self.assertEqual(self.log.path, self.root / SUGGESTIONS_NAME)

    def test_round_trip_with_injected_now(self):
        entry = self.log.record(
            "  How do agents compact memory?  ", "gap", "AI Engineering", "needed it", "claude-code in repo X"
        )
        self.assertEqual(entry["ts"], "2026-06-30T10:21:03Z")
        self.assertEqual(entry["kind"], "gap")
        self.assertEqual(entry["subject"], "How do agents compact memory?")
        self.assertEqual(entry["topic"], "AI Engineering")
        self.assertEqual(entry["reason"], "needed it")
        self.assertEqual(entry["by"], "claude-code in repo X")
        self.assertRegex(entry["id"], r"^sg-[0-9a-f]{12}$")
        self.assertEqual(self.log.read(), [entry])
        self.assertEqual(json.loads(self._lines()[0]), entry)

    def test_optional_fields_default_empty(self):
        entry = self.log.record("Tempo run pacing")
        self.assertEqual((entry["kind"], entry["topic"], entry["reason"], entry["by"]), ("gap", "", "", ""))

    def test_rejections_write_nothing(self):
        bad = [
            dict(subject="x", kind="other"),
            dict(subject=""),
            dict(subject=" \n\t "),
            dict(subject="s" * 301),
            dict(subject="s", reason="r" * 601),
            dict(subject="s", topic="t" * 81),
            dict(subject="s", by="b" * 81),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.log.record(**kwargs)
        self.assertFalse(self.log.path.exists())

    def test_limits_are_inclusive(self):
        self.log.record("s" * 300, "subject", "t" * 80, "r" * 600, "b" * 80)
        self.assertEqual(len(self.log.read()), 1)

    def test_forged_line_stays_one_entry(self):
        payload = 'evil\n{"id":"forged"}\r\x1b[31m more'
        self.log.record(payload)
        self.assertEqual(len(self._lines()), 1)
        entries = self.log.read()
        self.assertEqual(len(entries), 1)
        self.assertNotEqual(entries[0]["id"], "forged")
        self.assertIn('{"id":"forged"}', entries[0]["subject"])
        self.assertNotIn("\x1b", entries[0]["subject"])

    def test_ids_unique_for_identical_records(self):
        a = self.log.record("same")
        b = self.log.record("same")
        self.assertNotEqual(a["id"], b["id"])

    def test_read_missing_log_is_empty(self):
        self.assertEqual(self.log.read(), [])

    def test_read_limit_returns_most_recent(self):
        for i in range(5):
            self.log.record(f"s{i}")
        self.assertEqual([e["subject"] for e in self.log.read(limit=2)], ["s3", "s4"])
        self.assertEqual(self.log.read(limit=0), [])

    def test_read_skips_malformed_lines(self):
        self.log.record("good")
        with self.log.path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n\n")
        self.log.record("also good")
        self.assertEqual([e["subject"] for e in self.log.read()], ["good", "also good"])

    def test_unicode_preserved(self):
        self.log.record("café déjà")
        self.assertIn("café déjà", self._lines()[0])


if __name__ == "__main__":
    unittest.main()
