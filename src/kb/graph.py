"""In-memory graph index over the compiled wiki (Milestone 1, read-only).

Nodes are pages: ``index.md`` plus every ``wiki/*.md`` file. Edges are resolved
wikilinks between pages. The graph also surfaces hygiene signals: broken links
(targets that resolve to no file) and orphan pages (wiki pages with no incoming
link from another wiki page).

The graph is built on demand from a :class:`~kb.vault.Vault`; nothing is cached
to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .categories import Category, parse_categories
from .vault import Vault
from .wikilinks import WikiLink, parse_wikilinks, resolve_target

_TITLE = re.compile(r"^\s{0,3}#\s+(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_DELIM = "---"

INDEX_ID = "index"


def extract_title(text: str, fallback: str) -> str:
    """First level-1 heading in ``text``, else ``fallback``."""
    match = _TITLE.search(text)
    return match.group(1).strip() if match else fallback


def parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML-frontmatter parsing: scalar ``key: value`` properties only.

    Returns an empty dict when the page has no frontmatter block (a leading
    ``---`` line). Only flat ``key: value`` lines are captured, with
    surrounding quotes stripped; list and nested values are skipped since no
    consumer needs anything richer yet — this is deliberately minimal rather
    than a general YAML parser, matching how the rest of this module parses
    vault structure by hand instead of pulling in a dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return {}
    properties: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == _FRONTMATTER_DELIM:
            break
        if not line or line[0] in " \t-":
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            properties[key] = value
    return properties


@dataclass(frozen=True)
class LinkRef:
    """A wikilink from ``source`` resolved against the vault."""

    source: str
    target: str
    resolved: str | None
    alias: str | None
    heading: str | None

    @property
    def exists(self) -> bool:
        return self.resolved is not None

    @property
    def is_page(self) -> bool:
        """True when the resolved target is a graph node (index or wiki page)."""
        return self.resolved is not None and (
            self.resolved == INDEX_ID or self.resolved.startswith("wiki/")
        )


@dataclass
class Page:
    """A graph node and its outgoing links."""

    id: str
    title: str
    links: list[LinkRef] = field(default_factory=list)
    frontmatter: dict[str, str] = field(default_factory=dict)

    @property
    def is_wiki(self) -> bool:
        return self.id.startswith("wiki/")


@dataclass
class BrokenLink:
    source: str
    target: str


class KnowledgeGraph:
    """Pages, wikilinks, backlinks, broken links, orphans, and categories."""

    def __init__(
        self,
        pages: dict[str, Page],
        backlinks: dict[str, list[str]],
        categories: list[Category],
    ) -> None:
        self.pages = pages
        self.backlinks = backlinks
        self.categories = categories

    # -- construction ------------------------------------------------------

    @classmethod
    def build(cls, vault: Vault) -> "KnowledgeGraph":
        return cls.from_page_texts(vault.page_texts(), vault.all_markdown_ids())

    @classmethod
    def from_page_texts(
        cls,
        page_texts: dict[str, str],
        known_ids: set[str],
    ) -> "KnowledgeGraph":
        """Build a graph from already-loaded page texts.

        ``page_texts`` maps each graph-node page id (``index`` and
        ``wiki/*``) to its markdown, in the order nodes should be visited.
        ``known_ids`` is the link-existence set (every markdown id under the
        root, including ``raw/``). This is the seam the propose dry-run uses to
        build a graph over an in-memory overlay of the vault without writing.
        """
        pages: dict[str, Page] = {}
        for page_id, text in page_texts.items():
            links = [
                _to_ref(page_id, link, known_ids)
                for link in parse_wikilinks(text)
            ]
            pages[page_id] = Page(
                id=page_id,
                title=extract_title(text, page_id),
                links=links,
                frontmatter=parse_frontmatter(text),
            )
        backlinks = _compute_backlinks(pages)
        categories = parse_categories(page_texts.get(INDEX_ID, ""))
        return cls(pages, backlinks, categories)

    # -- queries -----------------------------------------------------------

    def outgoing(self, page_id: str) -> list[LinkRef]:
        page = self.pages.get(page_id)
        return list(page.links) if page else []

    def incoming(self, page_id: str) -> list[str]:
        return list(self.backlinks.get(page_id, []))

    def broken_links(self) -> list[BrokenLink]:
        """All wikilinks whose target resolves to no file, in page order."""
        broken: list[BrokenLink] = []
        for page in self.pages.values():
            for link in page.links:
                if not link.exists:
                    broken.append(BrokenLink(page.id, link.target))
        return broken

    def orphan_pages(self) -> list[str]:
        """Wiki pages with no incoming link from another wiki page.

        ``index.md`` is excluded as a link source: it catalogs every page, so
        counting it would make orphans always empty and useless for hygiene.
        """
        orphans: list[str] = []
        for page_id, page in self.pages.items():
            if not page.is_wiki:
                continue
            sources = [
                s
                for s in self.backlinks.get(page_id, [])
                if s != page_id and s != INDEX_ID and s.startswith("wiki/")
            ]
            if not sources:
                orphans.append(page_id)
        return sorted(orphans)

    def missing_page_targets(self) -> list[str]:
        """Distinct unresolved link targets, sorted (the 'missing pages')."""
        return sorted({b.target for b in self.broken_links()})

    def summary(self) -> dict[str, int]:
        total_links = sum(len(p.links) for p in self.pages.values())
        broken = self.broken_links()
        wiki_pages = sum(1 for p in self.pages.values() if p.is_wiki)
        return {
            "pages": len(self.pages),
            "wiki_pages": wiki_pages,
            "links": total_links,
            "resolved_links": total_links - len(broken),
            "broken_links": len(broken),
            "missing_pages": len(self.missing_page_targets()),
            "orphan_pages": len(self.orphan_pages()),
            "categories": len(self.categories),
        }


def _to_ref(source: str, link: WikiLink, known_ids: set[str]) -> LinkRef:
    return LinkRef(
        source=source,
        target=link.target,
        resolved=resolve_target(link.target, known_ids),
        alias=link.alias,
        heading=link.heading,
    )


def _compute_backlinks(pages: dict[str, Page]) -> dict[str, list[str]]:
    """Map each page id to the sorted, de-duplicated ids that link to it."""
    incoming: dict[str, set[str]] = {pid: set() for pid in pages}
    for page in pages.values():
        for link in page.links:
            if link.resolved in incoming and link.resolved != page.id:
                incoming[link.resolved].add(page.id)
    return {pid: sorted(sources) for pid, sources in incoming.items()}
