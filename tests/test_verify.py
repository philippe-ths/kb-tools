import tempfile
import unittest
from pathlib import Path

from kb.graph import KnowledgeGraph
from kb.vault import Vault
from kb.verify import (
    citation_report,
    is_src_page,
    report_delta,
    verification_report,
)

from .fixture import make_vault


def _graph_from(files: dict) -> KnowledgeGraph:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    try:
        return KnowledgeGraph.build(Vault.open(tmp.name))
    finally:
        tmp.cleanup()


class CitationReportFixtureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        graph = KnowledgeGraph.build(Vault.open(self._tmp.name))
        self.report = citation_report(graph)

    def test_uncited_pages_flag_pages_with_no_citation(self):
        self.assertIn("wiki/concept-beta", self.report["uncited_pages"])
        self.assertIn("wiki/concept-orphan", self.report["uncited_pages"])

    def test_cited_page_not_flagged(self):
        # concept-alpha links src-gamma and raw/evidence-a
        self.assertNotIn("wiki/concept-alpha", self.report["uncited_pages"])

    def test_overview_excluded_from_uncited(self):
        self.assertNotIn("wiki/overview", self.report["uncited_pages"])

    def test_src_without_raw_link_flagged(self):
        self.assertEqual(
            self.report["sources_without_raw_link"], ["wiki/src-gamma"]
        )

    def test_no_broken_citations(self):
        self.assertEqual(self.report["broken_citations"], [])


class CitationReportEdgeTest(unittest.TestCase):
    def test_broken_raw_citation_detected(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/concept-x]]\n",
                "wiki/concept-x.md": "# X\n\nEvidence in [[raw/missing]].\n",
            }
        )
        report = citation_report(graph)
        self.assertEqual(
            report["broken_citations"],
            [{"source": "wiki/concept-x", "target": "raw/missing"}],
        )

    def test_src_with_resolvable_raw_not_flagged(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/src-y]]\n",
                "wiki/src-y.md": "# Y\n\nSummary of [[raw/doc]].\n",
                "raw/doc.md": "# Doc\n",
            }
        )
        report = citation_report(graph)
        self.assertEqual(report["sources_without_raw_link"], [])
        self.assertEqual(report["broken_citations"], [])

    def test_is_src_page(self):
        self.assertTrue(is_src_page("wiki/src-foo"))
        self.assertFalse(is_src_page("wiki/concept-foo"))
        self.assertFalse(is_src_page("index"))


class ExternallySourcedPagesTest(unittest.TestCase):
    def test_marked_page_exempted_from_uncited(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/concept-x]]\n",
                "wiki/concept-x.md": (
                    "---\nevidence: external\n---\n\n"
                    "# X\n\nSynthesised from published literature.\n"
                ),
            }
        )
        report = citation_report(graph)
        self.assertEqual(report["externally_sourced_pages"], ["wiki/concept-x"])
        self.assertNotIn("wiki/concept-x", report["uncited_pages"])

    def test_unmarked_uncited_page_still_flagged(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/concept-x]]\n",
                "wiki/concept-x.md": "# X\n\nNo citation here at all.\n",
            }
        )
        report = citation_report(graph)
        self.assertEqual(report["uncited_pages"], ["wiki/concept-x"])
        self.assertEqual(report["externally_sourced_pages"], [])

    def test_bogus_marker_value_still_uncited(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/concept-x]]\n",
                "wiki/concept-x.md": (
                    "---\nevidence: nonsense\n---\n\n"
                    "# X\n\nNo citation here at all.\n"
                ),
            }
        )
        report = citation_report(graph)
        self.assertEqual(report["uncited_pages"], ["wiki/concept-x"])
        self.assertEqual(report["externally_sourced_pages"], [])

    def test_marked_page_with_broken_raw_link_still_reports_it(self):
        graph = _graph_from(
            {
                "index.md": "# I\n- [[wiki/concept-x]]\n",
                "wiki/concept-x.md": (
                    "---\nevidence: external\n---\n\n"
                    "# X\n\nSee [[raw/missing]] as well.\n"
                ),
            }
        )
        report = citation_report(graph)
        self.assertEqual(report["externally_sourced_pages"], ["wiki/concept-x"])
        self.assertNotIn("wiki/concept-x", report["uncited_pages"])
        self.assertEqual(
            report["broken_citations"],
            [{"source": "wiki/concept-x", "target": "raw/missing"}],
        )


class VerificationReportTest(unittest.TestCase):
    def test_report_has_graph_hygiene_and_citations(self):
        tmp = make_vault()
        self.addCleanup(tmp.cleanup)
        report = verification_report(KnowledgeGraph.build(Vault.open(tmp.name)))
        self.assertEqual(set(report), {"graph", "hygiene", "citations"})
        self.assertIn("broken_links", report["hygiene"])
        self.assertIn("uncited_pages", report["citations"])


class ReportDeltaTest(unittest.TestCase):
    def _report(self, **counts):
        return {
            "hygiene": {
                "broken_links": [0] * counts.get("broken_links", 0),
                "orphan_pages": [0] * counts.get("orphan_pages", 0),
            },
            "citations": {
                "uncited_pages": [0] * counts.get("uncited_pages", 0),
                "sources_without_raw_link": [0]
                * counts.get("sources_without_raw_link", 0),
                "broken_citations": [0] * counts.get("broken_citations", 0),
            },
        }

    def test_delta_sums_and_signs(self):
        before = self._report(uncited_pages=3, broken_links=1)
        after = self._report(uncited_pages=1, broken_links=2)
        delta = report_delta(before, after)
        self.assertEqual(delta["uncited_pages"], -2)
        self.assertEqual(delta["broken_links"], 1)
        self.assertEqual(delta["warnings"], -1)


if __name__ == "__main__":
    unittest.main()
