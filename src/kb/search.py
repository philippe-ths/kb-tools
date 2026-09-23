"""Lexical full-text search over `index.md` and `wiki/*.md`.

Phase 1 is deliberately lexical: no embeddings, no vector store (CONTEXT.md
"Graph index" / project-context "Scope"). Pages are tokenized into lowercase
alphanumeric terms; a query scores each page by term frequency with a title
boost. Results are deterministic: ranked by score, then by page id.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .graph import extract_title
from .vault import Vault, page_id_for

_TOKEN = re.compile(r"[a-z0-9]+")
_TITLE_BOOST = 3


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, in order."""
    return _TOKEN.findall(text.lower())


@dataclass
class SearchResult:
    page_id: str
    title: str
    score: int
    matched_terms: list[str]
    snippet: str


@dataclass
class _Doc:
    page_id: str
    title: str
    text: str
    body_counts: Counter
    title_counts: Counter


class SearchIndex:
    """An in-memory lexical index over the vault's pages."""

    def __init__(self, docs: list[_Doc]) -> None:
        self._docs = docs

    @classmethod
    def build(cls, vault: Vault) -> "SearchIndex":
        docs: list[_Doc] = []
        for path in vault.page_files():
            page_id = page_id_for(vault.root, path)
            text = path.read_text(encoding="utf-8")
            title = extract_title(text, page_id)
            docs.append(
                _Doc(
                    page_id=page_id,
                    title=title,
                    text=text,
                    body_counts=Counter(tokenize(text)),
                    title_counts=Counter(tokenize(title)),
                )
            )
        return cls(docs)

    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        terms = list(dict.fromkeys(tokenize(query)))  # unique, order-preserving
        if not terms:
            return []
        results: list[SearchResult] = []
        for doc in self._docs:
            score = 0
            matched: list[str] = []
            for term in terms:
                hits = doc.body_counts.get(term, 0)
                title_hits = doc.title_counts.get(term, 0)
                if hits or title_hits:
                    matched.append(term)
                score += hits + _TITLE_BOOST * title_hits
            if score > 0:
                results.append(
                    SearchResult(
                        page_id=doc.page_id,
                        title=doc.title,
                        score=score,
                        matched_terms=matched,
                        snippet=_snippet(doc.text, matched),
                    )
                )
        results.sort(key=lambda r: (-r.score, r.page_id))
        return results[: max(0, limit)]


def _strip_frontmatter(lines: list[str]) -> list[str]:
    """Drop a leading YAML frontmatter block delimited by ``---`` fences."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1 :]
    return lines


def _snippet(text: str, terms: list[str], width: int = 200) -> str:
    """First body line containing a matched term, trimmed to ``width``.

    Headings, horizontal rules, and a leading YAML frontmatter block are skipped
    so snippets quote prose rather than metadata.
    """
    if not terms:
        return ""
    termset = set(terms)
    for raw_line in _strip_frontmatter(text.splitlines()):
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if termset & set(tokenize(line)):
            return line[:width] + ("…" if len(line) > width else "")
    return ""
