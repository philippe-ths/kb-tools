"""Vault root resolution, file discovery, and guarded reads/writes.

The runtime root is resolved from an explicit ``--root`` argument first, then the
``KNOWLEDGE_BASE_ROOT`` environment variable (ADR 0001). Discovery and reads are
Milestone 1; the guarded writes (Milestone 2) are the single low-level seam every
mutation funnels through, so the raw/-is-immutable and no-path-escape rules are
enforced in one place regardless of which front end proposed the change.

Page identity is the POSIX-style path of a markdown file relative to the root,
without the ``.md`` suffix, e.g. ``index``, ``wiki/overview``,
``wiki/concept-agent-memory``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Directories that hold tooling/policy state rather than knowledge content. They
# are skipped when discovering markdown so vendored files never enter the graph
# or the link-existence set.
_SKIP_DIRS = {".git", ".obsidian", "node_modules", "tools"}

ENV_ROOT = "KNOWLEDGE_BASE_ROOT"


class VaultError(Exception):
    """Raised when the vault root cannot be resolved or read."""


def append_chunk(existing: str, text: str) -> str:
    """The exact text appended to ``existing`` for an append-only write.

    A newline separates the prior content from the block when one is missing,
    and the block is newline-terminated. Shared by the live writer and the
    propose dry-run so a proposed log append previews byte-for-byte.
    """
    prefix = "" if existing == "" or existing.endswith("\n") else "\n"
    suffix = "" if text.endswith("\n") else "\n"
    return f"{prefix}{text}{suffix}"


def resolve_root(root_arg: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the vault root.

    Precedence: explicit ``root_arg`` > ``KNOWLEDGE_BASE_ROOT`` env var. Raises
    ``VaultError`` if neither is provided or the path is not a directory.
    """
    candidate = root_arg if root_arg is not None else os.environ.get(ENV_ROOT)
    if not candidate:
        raise VaultError(
            "no vault root: pass --root or set the "
            f"{ENV_ROOT} environment variable"
        )
    root = Path(candidate).expanduser().resolve()
    if not root.is_dir():
        raise VaultError(f"vault root is not a directory: {root}")
    return root


def page_id_for(root: Path, path: Path) -> str:
    """Return the page id (relative, POSIX, no ``.md``) for a markdown file."""
    rel = path.resolve().relative_to(root)
    return rel.with_suffix("").as_posix()


@dataclass(frozen=True)
class Vault:
    """A guarded view of a knowledge-base vault rooted at ``root``."""

    root: Path

    @classmethod
    def open(cls, root_arg: str | os.PathLike[str] | None = None) -> "Vault":
        return cls(resolve_root(root_arg))

    # -- discovery ---------------------------------------------------------

    def index_file(self) -> Path | None:
        """Path to root-level ``index.md`` if it exists."""
        path = self.root / "index.md"
        return path if path.is_file() else None

    def wiki_files(self) -> list[Path]:
        """Sorted list of ``wiki/*.md`` files (compiled-memory pages)."""
        wiki_dir = self.root / "wiki"
        if not wiki_dir.is_dir():
            return []
        return sorted(p for p in wiki_dir.glob("*.md") if p.is_file())

    def page_files(self) -> list[Path]:
        """Graph nodes: ``index.md`` (if present) followed by ``wiki/*.md``."""
        pages: list[Path] = []
        index = self.index_file()
        if index is not None:
            pages.append(index)
        pages.extend(self.wiki_files())
        return pages

    def page_texts(self) -> dict[str, str]:
        """Map each graph-node page id to its markdown, in node order.

        Index first, then ``wiki/*`` sorted: the order the graph builds in.
        """
        return {
            page_id_for(self.root, path): path.read_text(encoding="utf-8")
            for path in self.page_files()
        }

    def all_markdown_ids(self) -> set[str]:
        """Page ids of every markdown file under the root, for link existence.

        Includes ``raw/`` and other content directories so that explicit
        ``[[raw/...]]`` links resolve, while skipping tooling/policy dirs.
        """
        ids: set[str] = set()
        for path in self._walk_markdown():
            ids.add(page_id_for(self.root, path))
        return ids

    def _walk_markdown(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune hidden and skip-listed directories in place.
            dirnames[:] = [
                d
                for d in dirnames
                if not d.startswith(".") and d not in _SKIP_DIRS
            ]
            for name in filenames:
                if name.endswith(".md"):
                    yield Path(dirpath) / name

    # -- reading -----------------------------------------------------------

    def _resolved_path(self, page_id: str) -> Path:
        """Resolve a page id to a markdown path, guarding against escape."""
        path = (self.root / f"{page_id}.md").resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise VaultError(f"path escapes vault root: {page_id}") from exc
        return path

    def exists(self, page_id: str) -> bool:
        """True when ``page_id`` resolves to an existing file under the root."""
        return self._resolved_path(page_id).is_file()

    def read_text(self, page_id: str) -> str:
        """Read a markdown file by page id. Guards against path escape."""
        path = self._resolved_path(page_id)
        if not path.is_file():
            raise VaultError(f"no such page: {page_id}")
        return path.read_text(encoding="utf-8")

    # -- writing (Milestone 2) ---------------------------------------------

    def _writable_path(self, page_id: str) -> Path:
        """Resolve a write target, refusing escapes and any ``raw/`` write.

        ``raw/`` is the immutable evidence layer (ADR 0001, CONTEXT.md); no
        write may ever land there, whatever the caller asked for.
        """
        path = self._resolved_path(page_id)
        first = path.relative_to(self.root).parts[0] if path != self.root else ""
        if first == "raw":
            raise VaultError(f"raw/ is immutable and cannot be written: {page_id}")
        return path

    def write_text(self, page_id: str, text: str) -> None:
        """Create or overwrite a markdown page. Refuses ``raw/`` and escapes."""
        path = self._writable_path(page_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def append_text(self, page_id: str, text: str) -> None:
        """Append ``text`` to a markdown file, never rewriting prior content.

        Used for the append-only ``log.md``. See :func:`append_chunk` for the
        exact bytes appended; the propose dry-run reuses it so its diff matches.
        """
        path = self._writable_path(page_id)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        with path.open("a", encoding="utf-8") as handle:
            handle.write(append_chunk(existing, text))
