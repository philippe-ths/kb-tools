"""Deterministic parsing of `index.md` categories.

`index.md` groups wiki pages under ``##`` sections and optional ``###``
subsections (see the catalog format in CLAUDE.md). Each bullet that carries a
wikilink is assigned to the section/subsection currently in scope. Parsing is a
single forward pass with no lookahead, so output is stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .wikilinks import parse_wikilinks

_BULLET_PREFIXES = ("- ", "* ", "+ ")


@dataclass
class Category:
    """A section (and optional subsection) of `index.md` and its pages."""

    section: str
    subsection: str | None
    page_targets: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"{self.section} / {self.subsection}" if self.subsection else self.section


def parse_categories(index_text: str) -> list[Category]:
    """Parse `index.md` text into ordered categories with their link targets.

    ``page_targets`` holds the raw wikilink target strings (e.g.
    ``wiki/concept-agent-memory``) in document order; resolution to page ids is
    the graph's responsibility. Sections with no linked pages are omitted.
    """
    categories: list[Category] = []
    current: Category | None = None
    section: str | None = None
    subsection: str | None = None

    def category_for(section: str, subsection: str | None) -> Category:
        nonlocal current
        if (
            current is not None
            and current.section == section
            and current.subsection == subsection
        ):
            return current
        current = Category(section=section, subsection=subsection)
        categories.append(current)
        return current

    for raw_line in index_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## ") and not line.startswith("### "):
            section = line[3:].strip()
            subsection = None
            current = None
            continue
        if line.startswith("### "):
            subsection = line[4:].strip()
            current = None
            continue
        if section is None:
            continue
        if not line.startswith(_BULLET_PREFIXES):
            continue
        links = parse_wikilinks(line)
        if not links:
            continue
        cat = category_for(section, subsection)
        for link in links:
            cat.page_targets.append(link.target)

    return [c for c in categories if c.page_targets]
