"""Append-only JSONL record of queries put to the knowledge base.

The MCP server records each query-shaped tool call (``kb_search``,
``kb_build_context``) to ``.kb-queries.jsonl`` at the vault root, one JSON
object per line. This is machine-local telemetry, gitignored and kept out of the
human-curated ``log.md``, so a later session can see what has actually been
asked of the wiki.

Pure standard library (no ``mcp`` dependency) so it tests without the server
venv. Recording is best-effort: see :meth:`QueryLog.record`, whose caller in
``server.py`` swallows write failures so a query never fails on telemetry.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

QUERY_LOG_NAME = ".kb-queries.jsonl"


def _utc_now_iso() -> str:
    """Second-precision UTC timestamp, e.g. ``2026-06-30T10:21:03Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class QueryLog:
    """Append-only JSONL writer for query telemetry at ``path``."""

    def __init__(self, path: Path, *, now=_utc_now_iso) -> None:
        self.path = Path(path)
        self._now = now

    @classmethod
    def for_root(cls, root: Path, *, now=_utc_now_iso) -> "QueryLog":
        """A query log at ``<root>/.kb-queries.jsonl``."""
        return cls(Path(root) / QUERY_LOG_NAME, now=now)

    def record(self, tool: str, query: str, limit: int, results: int) -> dict:
        """Append one query entry and return it.

        Writes a single JSON object terminated by a newline. Raises on I/O
        failure; the server wraps the call so logging never breaks a query.
        """
        entry = {
            "ts": self._now(),
            "tool": tool,
            "query": query,
            "limit": limit,
            "results": results,
        }
        line = json.dumps(entry, ensure_ascii=False)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return entry

    def read(self, limit: int | None = None) -> list[dict]:
        """Return recorded entries oldest-first.

        With ``limit`` set, return only the most recent ``limit`` entries (a
        non-positive limit returns none). A missing log yields ``[]`` and
        malformed lines are skipped, so a partially written tail never breaks
        a fetch.
        """
        if not self.path.is_file():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if limit is None:
            return entries
        return entries[-limit:] if limit > 0 else []
