"""Stateless detection of raw sources pending autonomous ingestion (ADR 0002).

A raw markdown file is *pending* when no compiled ``wiki/`` page cites it via a
``[[raw/...]]`` wikilink and it is not matched by a glob in the root-level
``.kb-ingest-ignore`` file. Detection is derived entirely from the current vault
plus the ignore file, so there is no separate manifest that can drift out of
sync with what has actually been synthesized.

The ignore file is one glob per line; blank lines and ``#`` comments are
skipped. Globs are matched (``fnmatch`` semantics, so ``*`` spans ``/``) against
each candidate's root-relative POSIX path including the ``.md`` suffix, e.g.
``raw/ai-engineering-sources/foo.md``. A typical ignore file::

    # bulk archive parked for manual handling
    raw/ai-engineering-sources/*
    raw/assets/*
"""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path

from .graph import KnowledgeGraph
from .vault import Vault, page_id_for

IGNORE_FILE = ".kb-ingest-ignore"
RAW_PREFIX = "raw/"


def load_ignore_patterns(root: str | Path) -> list[str]:
    """Return the glob patterns from ``.kb-ingest-ignore``, if it exists."""

    path = Path(root) / IGNORE_FILE
    if not path.is_file():
        return []
    patterns: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.append(stripped)
    return patterns


def is_ignored(rel_path: str, patterns: list[str]) -> bool:
    """True when ``rel_path`` matches any ignore glob."""

    return any(fnmatch(rel_path, pattern) for pattern in patterns)


def raw_markdown_ids(vault: Vault) -> list[str]:
    """Sorted page ids of every markdown file under ``raw/``."""

    raw_dir = vault.root / "raw"
    if not raw_dir.is_dir():
        return []
    ids: list[str] = []
    for dirpath, dirnames, filenames in os.walk(raw_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.endswith(".md"):
                ids.append(page_id_for(vault.root, Path(dirpath) / name))
    return sorted(ids)


def cited_raw_ids(graph: KnowledgeGraph) -> set[str]:
    """Raw page ids that any wiki page references via a resolved wikilink."""

    cited: set[str] = set()
    for page in graph.pages.values():
        if not page.is_wiki:
            continue
        for link in page.links:
            if link.resolved and link.resolved.startswith(RAW_PREFIX):
                cited.add(link.resolved)
    return cited


def pending_sources(vault: Vault, graph: KnowledgeGraph | None = None) -> list[str]:
    """Raw markdown ids that are neither cited by a wiki page nor ignored."""

    graph = graph or KnowledgeGraph.build(vault)
    patterns = load_ignore_patterns(vault.root)
    cited = cited_raw_ids(graph)
    pending: list[str] = []
    for raw_id in raw_markdown_ids(vault):
        if raw_id in cited:
            continue
        if is_ignored(f"{raw_id}.md", patterns):
            continue
        pending.append(raw_id)
    return pending


def pending_report(vault: Vault, graph: KnowledgeGraph | None = None) -> dict:
    """Structured pending-ingest summary for the CLI and orchestrator."""

    graph = graph or KnowledgeGraph.build(vault)
    pending = pending_sources(vault, graph)
    return {
        "pending": pending,
        "count": len(pending),
        "ignored_patterns": load_ignore_patterns(vault.root),
        "cited_raw": sorted(cited_raw_ids(graph)),
    }
