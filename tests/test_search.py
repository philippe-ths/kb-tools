import unittest

from kb.api import KnowledgeBase
from kb.search import SearchIndex, _snippet, tokenize
from kb.vault import Vault

from .fixture import make_vault


class TokenizeTest(unittest.TestCase):
    def test_lowercase_alphanumeric(self):
        self.assertEqual(tokenize("Alpha, Beta-2!"), ["alpha", "beta", "2"])


class SnippetTest(unittest.TestCase):
    def test_frontmatter_is_skipped(self):
        text = "---\ntags: [memory, compute]\n---\n# Title\n\nReal prose about compute.\n"
        self.assertEqual(_snippet(text, ["compute"]), "Real prose about compute.")


class SearchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.index = SearchIndex.build(Vault.open(self._tmp.name))

    def test_finds_matching_page(self):
        results = self.index.search("orphan")
        self.assertTrue(results)
        self.assertEqual(results[0].page_id, "wiki/concept-orphan")

    def test_title_boost_ranks_title_match_first(self):
        # "beta" appears in beta's title and in alpha's body several times.
        top = self.index.search("beta")[0]
        self.assertEqual(top.page_id, "wiki/concept-beta")

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self.index.search(""), [])

    def test_limit_is_respected(self):
        self.assertLessEqual(len(self.index.search("the", limit=2)), 2)

    def test_snippet_is_populated_from_body(self):
        # "points" appears in beta's body, so the snippet quotes that line.
        result = self.index.search("points")[0]
        self.assertEqual(result.page_id, "wiki/concept-beta")
        self.assertIn("points", result.snippet.lower())

    def test_title_only_match_has_empty_snippet(self):
        # "orphan" appears only in the page title/heading, never in the body.
        result = self.index.search("orphan")[0]
        self.assertIn("orphan", result.matched_terms)
        self.assertEqual(result.snippet, "")

    def test_results_are_deterministic(self):
        self.assertEqual(
            [r.page_id for r in self.index.search("concept")],
            [r.page_id for r in self.index.search("concept")],
        )


class ApiSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.kb = KnowledgeBase.open(self._tmp.name)

    def test_search_shape(self):
        out = self.kb.search("alpha")
        self.assertEqual(out["query"], "alpha")
        self.assertIn("results", out)

    def test_read_page_shape(self):
        out = self.kb.read_page("wiki/concept-alpha")
        self.assertEqual(out["title"], "Alpha")
        self.assertIn("index", out["backlinks"])

    def test_graph_summary_shape(self):
        out = self.kb.graph_summary()
        self.assertEqual(out["summary"]["pages"], 6)
        self.assertEqual(len(out["categories"]), 3)

    def test_hygiene_shape(self):
        out = self.kb.hygiene()
        self.assertEqual(out["missing_pages"], ["concept-missing"])
        self.assertEqual(out["orphan_pages"], ["wiki/concept-orphan"])

    def test_build_context(self):
        out = self.kb.build_context("alpha")
        self.assertEqual(out["query"], "alpha")
        ids = [p["id"] for p in out["pages"]]
        self.assertIn("wiki/concept-alpha", ids)


if __name__ == "__main__":
    unittest.main()
