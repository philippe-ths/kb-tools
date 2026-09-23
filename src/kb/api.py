"""Knowledge-base operations shared by the MCP server and the CLI.

This is the single seam every front end calls, so the MCP server and CLI stay
thin transport adapters (ADR 0001). Read operations return plain
JSON-serializable data. The Milestone 2 write path keeps "propose" (a
non-mutating diff + dry-run verification) and "apply" (the committing write)
distinct, and every mutation funnels through the guarded :class:`~kb.vault.Vault`
writers so ``raw/`` stays immutable and ``log.md`` stays append-only.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .changes import (
    INDEX_ID,
    LOG_ID,
    AppendLog,
    ChangeSet,
    WriteIndex,
    WritePage,
)
from .graph import KnowledgeGraph
from .search import SearchIndex
from .vault import Vault, append_chunk
from .verify import citation_report, report_delta, verification_report


@dataclass
class KnowledgeBase:
    """A vault plus its lazily-built graph and search index."""

    vault: Vault
    _graph: KnowledgeGraph | None = None
    _search: SearchIndex | None = None

    @classmethod
    def open(cls, root_arg=None) -> "KnowledgeBase":
        return cls(Vault.open(root_arg))

    def graph(self) -> KnowledgeGraph:
        if self._graph is None:
            self._graph = KnowledgeGraph.build(self.vault)
        return self._graph

    def search_index(self) -> SearchIndex:
        if self._search is None:
            self._search = SearchIndex.build(self.vault)
        return self._search

    def reload(self) -> None:
        """Drop cached graph/search so the next call re-reads the vault."""
        self._graph = None
        self._search = None

    # -- operations --------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> dict:
        results = self.search_index().search(query, limit=limit)
        return {
            "query": query,
            "results": [
                {
                    "id": r.page_id,
                    "title": r.title,
                    "score": r.score,
                    "matched_terms": r.matched_terms,
                    "snippet": r.snippet,
                }
                for r in results
            ],
        }

    def read_page(self, page_id: str) -> dict:
        text = self.vault.read_text(page_id)
        graph = self.graph()
        page = graph.pages.get(page_id)
        outgoing = [
            {"target": link.target, "resolved": link.resolved}
            for link in (page.links if page else [])
        ]
        return {
            "id": page_id,
            "title": page.title if page else page_id,
            "text": text,
            "outgoing": outgoing,
            "backlinks": graph.incoming(page_id),
        }

    def graph_summary(self) -> dict:
        graph = self.graph()
        return {
            "summary": graph.summary(),
            "categories": [
                {"path": c.path, "pages": c.page_targets} for c in graph.categories
            ],
        }

    def hygiene(self) -> dict:
        """Broken links, missing-page targets, and orphan pages."""
        graph = self.graph()
        return {
            "broken_links": [
                {"source": b.source, "target": b.target}
                for b in graph.broken_links()
            ],
            "missing_pages": graph.missing_page_targets(),
            "orphan_pages": graph.orphan_pages(),
        }

    # -- verification (Milestone 2) ----------------------------------------

    def verify(self) -> dict:
        """Phase-1 audit: graph stats, graph hygiene, and citation hygiene."""
        return verification_report(self.graph())

    def citation_hygiene(self) -> dict:
        """Citation-hygiene findings only (uncited, no-evidence, broken)."""
        return citation_report(self.graph())

    # -- write workflow (Milestone 2) --------------------------------------

    @staticmethod
    def _as_changeset(changes) -> ChangeSet:
        return changes if isinstance(changes, ChangeSet) else ChangeSet.from_dicts(changes)

    def _overlay_graph(self, changeset: ChangeSet) -> KnowledgeGraph:
        """Build a graph over disk pages plus the proposed edits, no write.

        Log appends do not touch a graph node, so they leave the overlay
        unchanged; only page and index writes move the graph.
        """
        texts = dict(self.vault.page_texts())
        known = set(self.vault.all_markdown_ids())
        for op in changeset.operations:
            if isinstance(op, WritePage):
                texts[op.page_id] = op.text
                known.add(op.page_id)
            elif isinstance(op, WriteIndex):
                texts[INDEX_ID] = op.text
                known.add(INDEX_ID)
        ordered: dict[str, str] = {}
        if INDEX_ID in texts:
            ordered[INDEX_ID] = texts[INDEX_ID]
        for page_id in sorted(p for p in texts if p.startswith("wiki/")):
            ordered[page_id] = texts[page_id]
        return KnowledgeGraph.from_page_texts(ordered, known)

    def _action_for(self, op) -> str:
        if isinstance(op, AppendLog):
            return "append"
        return "update" if self.vault.exists(op.target) else "create"

    def _diff_for(self, op) -> str:
        target = op.target
        old = self.vault.read_text(target) if self.vault.exists(target) else ""
        if isinstance(op, AppendLog):
            new = old + append_chunk(old, op.text)
        else:
            new = op.text
        return "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{target}.md",
                tofile=f"b/{target}.md",
            )
        )

    def propose(self, changes) -> dict:
        """Describe a change set as diffs + before/after verification, no write.

        Returns one entry per operation (target, action, unified diff) and the
        verification before and after the change as it *would* land, with the
        per-bucket warning delta. Nothing is written to disk.
        """
        changeset = self._as_changeset(changes)
        before = self.verify()
        after = verification_report(self._overlay_graph(changeset))
        operations = [
            {
                "op": op.kind,
                "target": op.target,
                "action": self._action_for(op),
                "diff": self._diff_for(op),
            }
            for op in changeset.operations
        ]
        return {
            "operations": operations,
            "verification": {
                "before": before,
                "after": after,
                "delta": report_delta(before, after),
            },
        }

    def apply(self, changes) -> dict:
        """Commit a change set to disk, then re-verify the resulting vault.

        Writes go through the guarded vault writers in operation order; page and
        index writes create or overwrite, log writes append only. The cached
        graph/search are dropped so the returned verification reflects disk.
        """
        changeset = self._as_changeset(changes)
        applied = []
        for op in changeset.operations:
            action = self._action_for(op)
            if isinstance(op, WritePage):
                self.vault.write_text(op.page_id, op.text)
            elif isinstance(op, WriteIndex):
                self.vault.write_text(INDEX_ID, op.text)
            elif isinstance(op, AppendLog):
                self.vault.append_text(LOG_ID, op.text)
            applied.append({"op": op.kind, "target": op.target, "action": action})
        self.reload()
        return {"applied": applied, "verification": self.verify()}

    def build_context(self, query: str, limit: int = 5, depth: int = 1) -> dict:
        """Assemble a navigable starting set for answering ``query``.

        Returns the top matching pages with snippets and their immediate graph
        neighbours, mirroring the Query flow in CLAUDE.md (consult the catalog,
        then read the relevant pages and their links).
        """
        graph = self.graph()
        results = self.search_index().search(query, limit=limit)
        selected = {r.page_id for r in results}
        pages = []
        related: set[str] = set()
        for r in results:
            outgoing = [
                link.resolved
                for link in graph.outgoing(r.page_id)
                if link.is_page
            ]
            backlinks = graph.incoming(r.page_id)
            if depth >= 1:
                related.update(outgoing)
                related.update(backlinks)
            pages.append(
                {
                    "id": r.page_id,
                    "title": r.title,
                    "score": r.score,
                    "snippet": r.snippet,
                    "outgoing": sorted(set(outgoing)),
                    "backlinks": backlinks,
                }
            )
        return {
            "query": query,
            "pages": pages,
            "related": sorted(related - selected),
        }
