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
- ``index.md`` is replaced as a whole (the maintainer regenerates the catalog);
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


Operation = WritePage | WriteIndex | AppendLog


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
