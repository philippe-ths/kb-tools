"""Verification: graph hygiene + citation hygiene (Milestone 2, phase 1).

Phase 1 of the maintenance loop audits two things only (ADR 0001): graph hygiene
(broken links, missing pages, orphans, already computed by
:class:`~kb.graph.KnowledgeGraph`) and *citation hygiene*. Content consolidation
is explicitly deferred.

Citation hygiene is grounded in how this vault actually cites sources: ``src-*``
pages summarize a ``raw/`` document via ``[[raw/...]]``; concept and reference
pages cite the ``src-*`` page (or ``raw/``) they drew from. So a **citation** is
an outgoing link from a wiki page to either a ``src-*`` wiki page or a ``raw/``
target, and the checks are:

- **uncited page**: a non-``src`` wiki page (excluding ``overview``, the map)
  with no citation at all;
- **source missing a raw link**: a ``src-*`` page that has no resolvable
  ``[[raw/...]]`` wikilink to its evidence (a code-span path like
  ``\`raw/...\``` does not count: the graph cannot navigate it);
- **broken citation**: a ``raw/`` link whose target file does not exist.

Some pages are synthesised from external published literature rather than an
archived ``raw/`` document (e.g. academic papers cited by name in prose), and
archiving that literature into ``raw/`` is a human decision, not something
this rule can force. A page opts into that exception explicitly, via
frontmatter ``evidence: external`` — any other value, or its absence, is
treated as today. Such a page is never silently dropped: it is moved out of
``uncited_pages`` and counted in the separate ``externally_sourced_pages``
bucket, so the exemption stays visible rather than shrinking the warning
count for free. The exemption reaches only the uncited-page rule; a page
marked ``evidence: external`` with a broken ``raw/`` link still reports that
broken citation.

The report is a plain dict so the same structure feeds the CLI, the MCP server,
and (later) the autonomous runner's maintenance report.
"""

from __future__ import annotations

from .graph import INDEX_ID, KnowledgeGraph, LinkRef, Page

OVERVIEW_ID = "wiki/overview"
EXTERNAL_EVIDENCE_MARKER = "external"


def _basename(page_id: str) -> str:
    return page_id.rsplit("/", 1)[-1]


def is_src_page(page_id: str) -> bool:
    return page_id.startswith("wiki/") and _basename(page_id).startswith("src-")


def _links_to_src(link: LinkRef) -> bool:
    return link.resolved is not None and is_src_page(link.resolved)


def _targets_raw(link: LinkRef) -> bool:
    return link.target.strip().strip("/").startswith("raw/")


def is_externally_sourced(page: Page) -> bool:
    """True when the page opts out of the uncited rule via its frontmatter.

    Only the exact value ``evidence: external`` counts; any other value, or
    the property's absence, does not.
    """
    return page.frontmatter.get("evidence") == EXTERNAL_EVIDENCE_MARKER


def citation_report(graph: KnowledgeGraph) -> dict:
    """Citation-hygiene findings over a built graph."""
    uncited_pages: list[str] = []
    externally_sourced_pages: list[str] = []
    sources_without_raw_link: list[str] = []
    broken_citations: list[dict] = []

    for page_id, page in graph.pages.items():
        if page_id == INDEX_ID or not page.is_wiki:
            continue
        raw_links = [link for link in page.links if _targets_raw(link)]
        resolved_raw = [link for link in raw_links if link.exists]
        for link in raw_links:
            if not link.exists:
                broken_citations.append({"source": page_id, "target": link.target})

        if is_src_page(page_id):
            if not resolved_raw:
                sources_without_raw_link.append(page_id)
            continue

        if page_id == OVERVIEW_ID:
            continue
        has_src_citation = any(_links_to_src(link) for link in page.links)
        if not has_src_citation and not resolved_raw:
            if is_externally_sourced(page):
                externally_sourced_pages.append(page_id)
            else:
                uncited_pages.append(page_id)

    return {
        "uncited_pages": sorted(uncited_pages),
        "externally_sourced_pages": sorted(externally_sourced_pages),
        "sources_without_raw_link": sorted(sources_without_raw_link),
        "broken_citations": sorted(
            broken_citations, key=lambda b: (b["source"], b["target"])
        ),
    }


def graph_hygiene(graph: KnowledgeGraph) -> dict:
    """Broken links, missing-page targets, and orphan pages (graph side)."""
    return {
        "broken_links": [
            {"source": b.source, "target": b.target} for b in graph.broken_links()
        ],
        "missing_pages": graph.missing_page_targets(),
        "orphan_pages": graph.orphan_pages(),
    }


def verification_report(graph: KnowledgeGraph) -> dict:
    """The full phase-1 audit: graph stats + graph hygiene + citation hygiene."""
    return {
        "graph": graph.summary(),
        "hygiene": graph_hygiene(graph),
        "citations": citation_report(graph),
    }


def _warning_total(report: dict) -> int:
    hygiene = report["hygiene"]
    citations = report["citations"]
    return (
        len(hygiene["broken_links"])
        + len(hygiene["orphan_pages"])
        + len(citations["uncited_pages"])
        + len(citations["sources_without_raw_link"])
        + len(citations["broken_citations"])
    )


def report_delta(before: dict, after: dict) -> dict:
    """Net change in each warning bucket from ``before`` to ``after``.

    Positive means the proposed change introduces that warning; negative means
    it resolves one. ``warnings`` is the overall total delta.
    """
    return {
        "broken_links": len(after["hygiene"]["broken_links"])
        - len(before["hygiene"]["broken_links"]),
        "orphan_pages": len(after["hygiene"]["orphan_pages"])
        - len(before["hygiene"]["orphan_pages"]),
        "uncited_pages": len(after["citations"]["uncited_pages"])
        - len(before["citations"]["uncited_pages"]),
        "sources_without_raw_link": len(after["citations"]["sources_without_raw_link"])
        - len(before["citations"]["sources_without_raw_link"]),
        "broken_citations": len(after["citations"]["broken_citations"])
        - len(before["citations"]["broken_citations"]),
        "warnings": _warning_total(after) - _warning_total(before),
    }
