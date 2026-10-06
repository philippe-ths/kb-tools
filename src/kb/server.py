"""MCP server exposing knowledge-base read, verify, and write operations.

A thin transport adapter over :class:`kb.api.KnowledgeBase` (ADR 0001). It owns
no query logic; every tool delegates to the shared API seam and returns plain
JSON-serializable data. Write tools still go through the propose/apply workflow
and guarded vault writers.

The graph and search index are built on demand and cached for the process; call
``kb_reload`` after editing the vault to rebuild them.

Run (stdio transport), from the repository root::

    kb-server --root "$PWD"

The root falls back to the KNOWLEDGE_BASE_ROOT environment variable.
"""

from __future__ import annotations

import argparse
import sys

from mcp.server.fastmcp import FastMCP

from .api import KnowledgeBase
from .querylog import QueryLog
from .suggestions import SuggestionLog
from .vault import VaultError

INSTRUCTIONS = (
    "Access to a personal Obsidian LLM wiki. The compiled `wiki/` layer and "
    "`index.md` are the durable knowledge; `raw/` is immutable evidence. Use "
    "kb_search or kb_build_context to find pages, kb_read_page to read one with its "
    "links, kb_graph_summary for the catalog, and kb_hygiene/kb_verify for graph and "
    "citation hygiene. To change the wiki, build a change set and call kb_propose_changes "
    "to preview diffs and before/after verification without writing, then "
    "kb_apply_changes to commit it. A change is one of: "
    "{op:'write_page', page_id:'wiki/<name>', text} to create/update a wiki page, "
    "{op:'write_index', text} to replace index.md, {op:'append_log', text} to append "
    "to the append-only log.md. raw/ can never be written. Call kb_reload after the "
    "vault changes on disk outside this server. kb_search and kb_build_context calls "
    "are recorded; kb_fetch_queries reads that history back. kb_suggest_research "
    "records a research suggestion and kb_fetch_suggestions reads them back."
)


def build_server(kb: KnowledgeBase) -> FastMCP:
    mcp = FastMCP("knowledge-base", instructions=INSTRUCTIONS)
    query_log = QueryLog.for_root(kb.vault.root)
    suggestion_log = SuggestionLog.for_root(kb.vault.root)

    def _record(tool: str, query: str, limit: int, result: dict) -> None:
        """Record a query best-effort; never fail a tool call on telemetry.

        ``kb_search`` returns its hits under ``results`` and ``kb_build_context``
        under ``pages``; count whichever is present.
        """
        try:
            hits = result.get("results")
            if hits is None:
                hits = result.get("pages") or []
            query_log.record(tool, query, limit, len(hits))
        except Exception as exc:  # pragma: no cover - telemetry is non-critical
            print(f"query-log write failed: {exc}", file=sys.stderr)

    @mcp.tool()
    def kb_search(query: str, limit: int = 10) -> dict:
        """Lexical full-text search over index.md and wiki pages.

        Returns ranked results with page id, title, score, matched terms, and a
        prose snippet.
        """
        result = kb.search(query, limit=limit)
        _record("kb_search", query, limit, result)
        return result

    @mcp.tool()
    def kb_read_page(page_id: str) -> dict:
        """Read one page by id (e.g. 'wiki/overview').

        Returns its markdown text, resolved outgoing links, and backlinks.
        """
        return kb.read_page(page_id)

    @mcp.tool()
    def kb_graph_summary() -> dict:
        """Graph statistics and the index.md category structure."""
        return kb.graph_summary()

    @mcp.tool()
    def kb_hygiene() -> dict:
        """Broken links, missing-page targets, and orphan pages."""
        return kb.hygiene()

    @mcp.tool()
    def kb_build_context(query: str, limit: int = 5) -> dict:
        """Assemble a navigable starting set for a query.

        Returns the top matching pages with snippets plus their immediate graph
        neighbours, to decide what to read next.
        """
        result = kb.build_context(query, limit=limit)
        _record("kb_build_context", query, limit, result)
        return result

    @mcp.tool()
    def kb_verify() -> dict:
        """Phase-1 audit: graph stats, graph hygiene, and citation hygiene.

        Citation hygiene reports uncited wiki pages, source pages with no raw
        evidence, and broken raw/ citations.
        """
        return kb.verify()

    @mcp.tool()
    def kb_propose_changes(changes: list[dict]) -> dict:
        """Preview a change set without writing.

        Each change is {op:'write_page', page_id, text} | {op:'write_index', text}
        | {op:'append_log', text}. Returns a unified diff and create/update/append
        action per operation, plus verification before and after the change as it
        would land (with the warning delta). Nothing is written.
        """
        return kb.propose(changes)

    @mcp.tool()
    def kb_apply_changes(changes: list[dict]) -> dict:
        """Commit a change set to disk, then re-verify.

        Same change shape as kb_propose_changes. Writes go through the guarded
        vault writers: raw/ is never written and log.md is append-only. Returns
        the applied operations and the post-apply verification.
        """
        return kb.apply(changes)

    @mcp.tool()
    def kb_fetch_queries(limit: int = 50) -> dict:
        """Read back recorded queries (kb_search / kb_build_context calls).

        Returns the most recent ``limit`` entries oldest-first, each
        {ts, tool, query, limit, results}, with ``count`` being how many were
        returned. Use it to see what has actually been asked of the wiki.
        """
        entries = query_log.read(limit=limit)
        return {"count": len(entries), "entries": entries}

    @mcp.tool()
    def kb_suggest_research(
        subject: str,
        kind: str = "gap",
        topic: str = "",
        reason: str = "",
        by: str = "",
    ) -> dict:
        """Tell the owner's research process about a gap in the knowledge base.

        Call this when the knowledge base could not answer something your work
        needed (kind "gap"), or when a subject the owner's work keeps touching
        should be in the knowledge base (kind "subject"). One suggestion per gap.
        Phrase `subject` as one plain sentence saying what is not yet known.
        `topic` is optional (e.g. "AI Engineering", "Running and cardio"); `reason`
        and `by` (who you are, e.g. "claude-code in repo X") are optional too.
        Suggestions are read by a research process later; nothing is researched
        now. Do not include secrets or personal data about third parties.
        Returns {recorded, id, entry}, or {recorded: false, error} if rejected.
        """
        try:
            entry = suggestion_log.record(subject, kind, topic, reason, by)
        except (ValueError, OSError) as exc:
            return {"recorded": False, "error": str(exc)}
        return {"recorded": True, "id": entry["id"], "entry": entry}

    @mcp.tool()
    def kb_fetch_suggestions(limit: int = 50) -> dict:
        """Read back recorded research suggestions (kb_suggest_research calls).

        Returns the most recent ``limit`` entries oldest-first, each
        {id, ts, kind, subject, topic, reason, by}, with ``count`` being how many
        were returned.
        """
        entries = suggestion_log.read(limit=limit)
        return {"count": len(entries), "entries": entries}

    @mcp.tool()
    def kb_reload() -> dict:
        """Rebuild the in-memory graph and search index from disk."""
        kb.reload()
        return kb.graph_summary()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb.server", description=__doc__)
    parser.add_argument("--root", default=None, help="vault root directory")
    args = parser.parse_args(argv)
    try:
        kb = KnowledgeBase.open(args.root)
    except VaultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    build_server(kb).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
