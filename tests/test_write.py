import unittest
from pathlib import Path

from kb.api import KnowledgeBase
from kb.vault import Vault, VaultError

from .fixture import make_vault


class VaultWriterGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.vault = Vault.open(self._tmp.name)

    def test_refuses_to_write_under_raw(self):
        with self.assertRaises(VaultError):
            self.vault.write_text("raw/evidence-a", "tampered")
        # the original evidence is untouched
        self.assertIn("Immutable", (self.root / "raw/evidence-a.md").read_text())

    def test_refuses_to_append_under_raw(self):
        with self.assertRaises(VaultError):
            self.vault.append_text("raw/evidence-a", "tampered")

    def test_refuses_path_escape(self):
        with self.assertRaises(VaultError):
            self.vault.write_text("../outside", "x")

    def test_write_creates_then_overwrites(self):
        self.vault.write_text("wiki/new-page", "# First")
        self.assertEqual((self.root / "wiki/new-page.md").read_text(), "# First")
        self.vault.write_text("wiki/new-page", "# Second")
        self.assertEqual((self.root / "wiki/new-page.md").read_text(), "# Second")

    def test_append_is_append_only(self):
        self.vault.append_text("log", "## first")
        self.vault.append_text("log", "## second")
        text = (self.root / "log.md").read_text()
        self.assertEqual(text, "## first\n## second\n")


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.kb = KnowledgeBase.open(self._tmp.name)

    def test_apply_creates_page_and_reports_action(self):
        result = self.kb.apply(
            [{"op": "write_page", "page_id": "wiki/concept-delta", "text": "# Delta"}]
        )
        self.assertEqual(result["applied"][0]["action"], "create")
        self.assertEqual((self.root / "wiki/concept-delta.md").read_text(), "# Delta")

    def test_apply_update_overwrites_existing(self):
        result = self.kb.apply(
            [{"op": "write_page", "page_id": "wiki/concept-beta", "text": "# Beta v2"}]
        )
        self.assertEqual(result["applied"][0]["action"], "update")
        self.assertEqual((self.root / "wiki/concept-beta.md").read_text(), "# Beta v2")

    def test_apply_write_index_replaces(self):
        self.kb.apply([{"op": "write_index", "text": "# New index\n"}])
        self.assertEqual((self.root / "index.md").read_text(), "# New index\n")

    def test_apply_append_log_preserves_prior(self):
        self.kb.apply([{"op": "append_log", "text": "## [2026-06-14] one"}])
        self.kb.apply([{"op": "append_log", "text": "## [2026-06-14] two"}])
        log = (self.root / "log.md").read_text()
        self.assertEqual(log, "## [2026-06-14] one\n## [2026-06-14] two\n")

    def test_apply_reload_reflects_new_page_in_graph(self):
        self.kb.apply(
            [{"op": "write_page", "page_id": "wiki/concept-zeta", "text": "# Zeta"}]
        )
        self.assertIn("wiki/concept-zeta", self.kb.graph().pages)


class ProposeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.kb = KnowledgeBase.open(self._tmp.name)

    def test_propose_does_not_write(self):
        self.kb.propose(
            [{"op": "write_page", "page_id": "wiki/ghost", "text": "# Ghost"}]
        )
        self.assertFalse((self.root / "wiki/ghost.md").exists())

    def test_propose_reports_action_and_diff(self):
        result = self.kb.propose(
            [{"op": "write_page", "page_id": "wiki/ghost", "text": "# Ghost\n"}]
        )
        op = result["operations"][0]
        self.assertEqual(op["action"], "create")
        self.assertIn("+# Ghost", op["diff"])

    def test_propose_dry_run_predicts_new_uncited_page(self):
        # A new wiki page that cites nothing adds one uncited-page warning.
        before = self.kb.verify()["citations"]["uncited_pages"]
        result = self.kb.propose(
            [{"op": "write_page", "page_id": "wiki/lonely", "text": "# Lonely\n"}]
        )
        delta = result["verification"]["delta"]
        self.assertEqual(delta["uncited_pages"], 1)
        # propose did not mutate the live verification
        self.assertEqual(self.kb.verify()["citations"]["uncited_pages"], before)

    def test_propose_dry_run_resolves_missing_raw_link(self):
        # src-gamma has no raw link; adding one clears its warning.
        before = self.kb.verify()["citations"]["sources_without_raw_link"]
        self.assertIn("wiki/src-gamma", before)
        new_text = "# Gamma source\n\nNow cites [[raw/evidence-a]].\n"
        result = self.kb.propose(
            [{"op": "write_page", "page_id": "wiki/src-gamma", "text": new_text}]
        )
        self.assertEqual(
            result["verification"]["delta"]["sources_without_raw_link"], -1
        )


if __name__ == "__main__":
    unittest.main()
