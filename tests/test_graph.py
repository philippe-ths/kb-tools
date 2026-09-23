import unittest

from kb.graph import KnowledgeGraph
from kb.vault import Vault

from .fixture import make_vault


class GraphTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.graph = KnowledgeGraph.build(Vault.open(self._tmp.name))

    def test_nodes_are_index_plus_wiki(self):
        self.assertIn("index", self.graph.pages)
        self.assertIn("wiki/concept-alpha", self.graph.pages)
        # raw files are resolvable targets but never graph nodes
        self.assertNotIn("raw/evidence-a", self.graph.pages)

    def test_titles_extracted(self):
        self.assertEqual(self.graph.pages["wiki/concept-alpha"].title, "Alpha")

    def test_backlinks_include_index_and_wiki_sources(self):
        back = self.graph.incoming("wiki/concept-alpha")
        for src in ("index", "wiki/overview", "wiki/concept-beta", "wiki/src-gamma"):
            self.assertIn(src, back)

    def test_backlinks_dedupe_repeated_source(self):
        # concept-alpha links to concept-beta twice (plain + alias)
        self.assertEqual(self.graph.incoming("wiki/concept-beta").count("wiki/concept-alpha"), 1)

    def test_broken_link_detected(self):
        broken = self.graph.broken_links()
        self.assertEqual(
            [(b.source, b.target) for b in broken],
            [("wiki/concept-alpha", "concept-missing")],
        )

    def test_missing_pages(self):
        self.assertEqual(self.graph.missing_page_targets(), ["concept-missing"])

    def test_raw_link_is_not_broken(self):
        targets = [b.target for b in self.graph.broken_links()]
        self.assertNotIn("raw/evidence-a", targets)

    def test_orphans_exclude_index_as_source(self):
        self.assertEqual(self.graph.orphan_pages(), ["wiki/concept-orphan"])

    def test_summary_counts(self):
        summary = self.graph.summary()
        self.assertEqual(summary["pages"], 6)
        self.assertEqual(summary["wiki_pages"], 5)
        self.assertEqual(summary["broken_links"], 1)
        self.assertEqual(summary["orphan_pages"], 1)
        self.assertEqual(summary["categories"], 3)

    def test_code_block_links_excluded(self):
        targets = [link.target for link in self.graph.outgoing("wiki/concept-alpha")]
        self.assertNotIn("concept-ignored", targets)
        self.assertNotIn("also-ignored", targets)


if __name__ == "__main__":
    unittest.main()
