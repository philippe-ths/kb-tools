import json
import tempfile
import unittest
from pathlib import Path

from kb.querylog import QUERY_LOG_NAME, QueryLog


class QueryLogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _log(self, *, now=None):
        if now is None:
            return QueryLog.for_root(self.root, now=lambda: "2026-06-30T10:21:03Z")
        return QueryLog.for_root(self.root, now=now)

    def test_for_root_targets_dotfile_at_root(self):
        self.assertEqual(self._log().path, self.root / QUERY_LOG_NAME)

    def test_record_returns_and_writes_one_jsonl_entry(self):
        log = self._log()
        entry = log.record("kb_search", "agent memory", 10, 7)
        self.assertEqual(
            entry,
            {
                "ts": "2026-06-30T10:21:03Z",
                "tool": "kb_search",
                "query": "agent memory",
                "limit": 10,
                "results": 7,
            },
        )
        lines = log.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), entry)

    def test_record_appends_without_rewriting(self):
        log = self._log()
        log.record("kb_search", "alpha", 10, 1)
        log.record("kb_build_context", "beta", 5, 3)
        lines = log.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["query"] for line in lines], ["alpha", "beta"])
        self.assertEqual(json.loads(lines[1])["tool"], "kb_build_context")

    def test_unicode_query_is_preserved(self):
        log = self._log()
        log.record("kb_search", "café déjà", 10, 0)
        line = log.path.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("café déjà", line)
        self.assertEqual(json.loads(line)["query"], "café déjà")

    def test_read_missing_log_is_empty(self):
        self.assertEqual(self._log().read(), [])

    def test_read_returns_entries_oldest_first(self):
        log = self._log()
        for i in range(3):
            log.record("kb_search", f"q{i}", 10, i)
        self.assertEqual([e["query"] for e in log.read()], ["q0", "q1", "q2"])

    def test_read_limit_returns_most_recent(self):
        log = self._log()
        for i in range(5):
            log.record("kb_search", f"q{i}", 10, i)
        self.assertEqual([e["query"] for e in log.read(limit=2)], ["q3", "q4"])

    def test_read_non_positive_limit_returns_none(self):
        log = self._log()
        log.record("kb_search", "q0", 10, 0)
        self.assertEqual(log.read(limit=0), [])

    def test_read_skips_malformed_lines(self):
        log = self._log()
        log.record("kb_search", "good", 10, 1)
        with log.path.open("a", encoding="utf-8") as handle:
            handle.write("not json\n\n")
        log.record("kb_search", "also good", 10, 2)
        self.assertEqual([e["query"] for e in log.read()], ["good", "also good"])


if __name__ == "__main__":
    unittest.main()
