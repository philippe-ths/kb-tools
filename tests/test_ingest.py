import tempfile
import unittest
from pathlib import Path

from kb.ingest import (
    is_ignored,
    load_ignore_patterns,
    pending_report,
    pending_sources,
)
from kb.vault import Vault

_FILES = {
    "index.md": "# Index\n\n- [[wiki/src-cited]] : a source\n",
    "wiki/src-cited.md": "# Cited source\n\nEvidence in [[raw/cited]].\n",
    "raw/cited.md": "# Cited\n",
    "raw/uncited.md": "# Uncited new source\n",
    "raw/parked/skip.md": "# Parked\n",
    ".kb-ingest-ignore": "# parked\nraw/parked/*\n\n",
}


def _make(files=_FILES):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp


class PendingDetectionTest(unittest.TestCase):
    def test_pending_excludes_cited_and_ignored(self):
        with _make() as tmp:
            pending = pending_sources(Vault.open(tmp))
            self.assertEqual(pending, ["raw/uncited"])

    def test_pending_report_lists_patterns_and_cited(self):
        with _make() as tmp:
            report = pending_report(Vault.open(tmp))
            self.assertEqual(report["count"], 1)
            self.assertEqual(report["ignored_patterns"], ["raw/parked/*"])
            self.assertIn("raw/cited", report["cited_raw"])

    def test_no_raw_dir_is_empty(self):
        with _make({"index.md": "# Index\n"}) as tmp:
            self.assertEqual(pending_sources(Vault.open(tmp)), [])

    def test_new_raw_file_becomes_pending(self):
        with _make() as tmp:
            (Path(tmp) / "raw/fresh.md").write_text("# Fresh\n", encoding="utf-8")
            self.assertIn("raw/fresh", pending_sources(Vault.open(tmp)))


class IgnoreParsingTest(unittest.TestCase):
    def test_load_ignore_skips_comments_and_blanks(self):
        with _make() as tmp:
            self.assertEqual(load_ignore_patterns(tmp), ["raw/parked/*"])

    def test_missing_ignore_file_is_empty(self):
        with _make({"index.md": "# Index\n"}) as tmp:
            self.assertEqual(load_ignore_patterns(tmp), [])

    def test_is_ignored_glob_spans_slashes(self):
        self.assertTrue(is_ignored("raw/a/b/c.md", ["raw/a/*"]))
        self.assertFalse(is_ignored("raw/other.md", ["raw/a/*"]))


if __name__ == "__main__":
    unittest.main()
