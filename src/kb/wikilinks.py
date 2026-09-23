"""Parsing and resolution of Obsidian-style wikilinks.

Supported forms (observed in this vault):
- ``[[concept-agent-memory]]``        bare name -> ``wiki/concept-agent-memory``
- ``[[wiki/overview]]``               explicit path relative to the root
- ``[[raw/lesson-x]]``                explicit path into the evidence layer
- ``[[target|alias text]]``           display alias after a pipe
- ``[[target#heading]]``              heading anchor (parsed, not yet resolved)

Links inside fenced code blocks and inline code spans are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WIKILINK = re.compile(r"\[\[([^\[\]]+?)\]\]")
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True)
class WikiLink:
    """A single parsed wikilink occurrence.

    ``target`` is the link path with alias and heading stripped. ``alias`` is the
    display text after ``|`` (or ``None``). ``heading`` is the ``#`` anchor (or
    ``None``). ``start``/``end`` are character offsets into the original text.
    """

    target: str
    alias: str | None
    heading: str | None
    start: int
    end: int

    @property
    def raw(self) -> str:
        inner = self.target
        if self.heading is not None:
            inner = f"{inner}#{self.heading}"
        if self.alias is not None:
            inner = f"{inner}|{self.alias}"
        return f"[[{inner}]]"


def _mask_code(text: str) -> str:
    """Blank out code spans, preserving length so offsets stay valid."""

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    masked = _FENCED_CODE.sub(blank, text)
    masked = _INLINE_CODE.sub(blank, masked)
    return masked


def parse_wikilinks(text: str) -> list[WikiLink]:
    """Return every wikilink in ``text``, in source order, ignoring code."""
    masked = _mask_code(text)
    links: list[WikiLink] = []
    for match in _WIKILINK.finditer(masked):
        inner = match.group(1).strip()
        if not inner:
            continue
        alias: str | None = None
        if "|" in inner:
            inner, alias = inner.split("|", 1)
            inner, alias = inner.strip(), alias.strip()
        heading: str | None = None
        if "#" in inner:
            inner, heading = inner.split("#", 1)
            inner, heading = inner.strip(), heading.strip()
        if not inner:
            continue
        links.append(
            WikiLink(
                target=inner,
                alias=alias or None,
                heading=heading or None,
                start=match.start(),
                end=match.end(),
            )
        )
    return links


def resolve_target(target: str, known_ids: set[str]) -> str | None:
    """Resolve a link target string to an existing page id, or ``None``.

    A target containing ``/`` is treated as a path relative to the root. A bare
    target is resolved to ``wiki/<target>`` first, then to a root-level
    ``<target>`` (e.g. ``[[index]]``). Resolution is by exact page id; existence
    is checked against ``known_ids``.
    """
    norm = target.strip().strip("/")
    if not norm:
        return None
    if "/" in norm:
        return norm if norm in known_ids else None
    for candidate in (f"wiki/{norm}", norm):
        if candidate in known_ids:
            return candidate
    return None
