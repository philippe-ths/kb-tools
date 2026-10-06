"""The propose/apply change-set model (Milestone 2, write workflow).

A :class:`ChangeSet` is a reviewable, JSON-serializable description of a
maintainer-workflow update (CONTEXT.md): create or update ``wiki/`` pages,
replace ``index.md``, and append to ``log.md``. It is a *pure value*: building
or validating one never touches disk. "Propose" turns a change set into a diff
plus a dry-run verification (see :mod:`kb.verify`); "apply" writes it through the
guarded :class:`~kb.vault.Vault` writers.

The write rules are enforced here at construction, structurally, so an illegal
change set cannot be represented:

- pages may only be written under ``wiki/`` (flat, no nested paths);
- ``index.md`` is replaced as a whole, or gains one entry in an existing
  category (so a single ingest need not read or rewrite the whole catalog);
- ``log.md`` is reachable *only* through append, so prior entries can never be
  rewritten;
- nothing here can target ``raw/`` (also re-checked at the vault write seam).
"""

from __future__ import annotations

from dataclasses import dataclass

INDEX_ID = "index"
LOG_ID = "log"

WRITE_PAGE = "write_page"
WRITE_INDEX = "write_index"
APPEND_LOG = "append_log"
ADD_INDEX_ENTRY = "add_index_entry"


class ChangeError(Exception):
    """Raised when a proposed change violates a vault write rule."""


def _validate_wiki_page_id(page_id: str) -> str:
    """Return a clean ``wiki/<name>`` page id or raise ``ChangeError``."""
    if not isinstance(page_id, str):
        raise ChangeError(f"page id must be a string: {page_id!r}")
    pid = page_id.strip()
    if pid.endswith(".md"):
        pid = pid[: -len(".md")]
    if not pid:
        raise ChangeError("empty page id")
    if pid != pid.strip("/") or "\\" in pid:
        raise ChangeError(f"page id must be a clean relative path: {page_id!r}")
    parts = pid.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ChangeError(f"page id must not contain '.' or '..': {page_id!r}")
    if parts[0] != "wiki":
        raise ChangeError(
            f"pages may only be written under wiki/: {page_id!r}"
        )
    if len(parts) != 2:
        raise ChangeError(f"wiki pages are flat (wiki/<name>): {page_id!r}")
    return pid


@dataclass(frozen=True)
class WritePage:
    """Create or overwrite a single ``wiki/<name>`` page with ``text``."""

    kind = WRITE_PAGE
    page_id: str
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "page_id", _validate_wiki_page_id(self.page_id))

    @property
    def target(self) -> str:
        return self.page_id

    def to_dict(self) -> dict:
        return {"op": WRITE_PAGE, "page_id": self.page_id, "text": self.text}


@dataclass(frozen=True)
class WriteIndex:
    """Replace ``index.md`` wholesale with ``text``."""

    kind = WRITE_INDEX
    text: str

    @property
    def target(self) -> str:
        return INDEX_ID

    def to_dict(self) -> dict:
        return {"op": WRITE_INDEX, "text": self.text}


@dataclass(frozen=True)
class AppendLog:
    """Append a block to the append-only ``log.md``."""

    kind = APPEND_LOG
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ChangeError("append_log text is empty")

    @property
    def target(self) -> str:
        return LOG_ID

    def to_dict(self) -> dict:
        return {"op": APPEND_LOG, "text": self.text}


@dataclass(frozen=True)
class AddIndexEntry:
    """Add one bullet to an existing ``index.md`` category, e.g. category
    ``Sources / AI agents`` and entry ``- [[wiki/src-x]] : one-line summary``.
    The rest of the catalog is left byte-for-byte as it was."""

    kind = ADD_INDEX_ENTRY
    category: str
    entry: str

    def __post_init__(self) -> None:
        entry = (self.entry or "").strip()
        if "\n" in entry or "\r" in entry:
            raise ChangeError("add_index_entry entry must be a single line")
        if not entry.startswith("- ") or "[[" not in entry:
            raise ChangeError("add_index_entry entry must be a '- [[wiki/...]] : summary' bullet")
        if not (self.category or "").strip():
            raise ChangeError("add_index_entry needs a category")
        object.__setattr__(self, "entry", entry)
        object.__setattr__(self, "category", self.category.strip())

    @property
    def target(self) -> str:
        return INDEX_ID

    def to_dict(self) -> dict:
        return {"op": ADD_INDEX_ENTRY, "category": self.category, "entry": self.entry}


def insert_index_entry(index_text: str, category: str, entry: str) -> str:
    """``index_text`` with ``entry`` after the last bullet of ``category``.

    The category is a path as ``kb_graph_summary`` reports it (``Section`` or
    ``Section / Subsection``). Adding an entry already present changes nothing.
    """
    lines = index_text.splitlines(keepends=True)
    if any(line.strip() == entry for line in lines):
        return index_text
    section = subsection = None
    last_bullet = None
    known = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("## ") and not line.startswith("### "):
            section, subsection = line[3:].strip(), None
            continue
        if line.startswith("### "):
            subsection = line[4:].strip()
            continue
        if section is None or not line.startswith(("- ", "* ", "+ ")):
            continue
        path = f"{section} / {subsection}" if subsection else section
        if path not in known:
            known.append(path)
        if path == category:
            last_bullet = i
    if last_bullet is None:
        raise ChangeError(f"no index category {category!r}; categories: {', '.join(known)}")
    newline = "" if lines[last_bullet].endswith("\n") else "\n"
    lines.insert(last_bullet + 1, newline + entry + "\n")
    return "".join(lines)


Operation = WritePage | WriteIndex | AppendLog | AddIndexEntry


def _operation_from_dict(item: dict) -> Operation:
    if not isinstance(item, dict):
        raise ChangeError(f"each change must be an object: {item!r}")
    op = item.get("op")
    if op == WRITE_PAGE:
        return WritePage(page_id=item.get("page_id", ""), text=item.get("text", ""))
    if op == WRITE_INDEX:
        return WriteIndex(text=item.get("text", ""))
    if op == APPEND_LOG:
        return AppendLog(text=item.get("text", ""))
    if op == ADD_INDEX_ENTRY:
        return AddIndexEntry(category=item.get("category", ""), entry=item.get("entry", ""))
    raise ChangeError(f"unknown change op: {op!r}")


@dataclass(frozen=True)
class ChangeSet:
    """An ordered set of write operations, applied in order."""

    operations: tuple[Operation, ...] = ()

    @classmethod
    def from_dicts(cls, items) -> "ChangeSet":
        if not isinstance(items, (list, tuple)):
            raise ChangeError("changes must be a list of operations")
        return cls(tuple(_operation_from_dict(i) for i in items))

    def to_dicts(self) -> list[dict]:
        return [op.to_dict() for op in self.operations]

    def __bool__(self) -> bool:
        return bool(self.operations)
