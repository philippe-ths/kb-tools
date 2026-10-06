"""Append-only JSONL record of research suggestions made by agents.

Any agent connected to the MCP server can record a gap (something the
knowledge base could not answer) or a subject worth researching through
``kb_suggest_research``. Entries go to ``.kb-suggestions.jsonl`` at the vault
root, one JSON object per line, machine-local and gitignored like the query
log. A separate process reads them later and plans research; nothing here
researches anything.

Suggestions come from arbitrary agents, so input is untrusted: fields are
length-limited and stripped of control and line-separator characters so an
entry can never span lines or carry terminal escapes.

Pure standard library (no ``mcp`` dependency) so it tests without the server
venv. Unlike query telemetry, a rejected or failed write is reported to the
caller: :meth:`SuggestionLog.record` raises, and ``server.py`` returns the error.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

SUGGESTIONS_NAME = ".kb-suggestions.jsonl"

KINDS = ("gap", "subject")

MAX_SUBJECT = 300
MAX_REASON = 600
MAX_TOPIC = 80
MAX_BY = 80

# ASCII and C1 control characters, plus the Unicode line/paragraph separators
# that ``str.splitlines`` treats as line breaks.
_UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f  ]")


def _utc_now_iso() -> str:
    """Second-precision UTC timestamp, e.g. ``2026-06-30T10:21:03Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(name: str, value: object, limit: int, *, required: bool = False) -> str:
    """Return ``value`` sanitised and checked against ``limit``; raise ValueError."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = _UNSAFE.sub(" ", value).strip()
    if required and not text:
        raise ValueError(f"{name} is required")
    if len(text) > limit:
        raise ValueError(f"{name} is too long ({len(text)} > {limit} characters)")
    return text


class SuggestionLog:
    """Append-only JSONL writer for research suggestions at ``path``."""

    def __init__(self, path: Path, *, now=_utc_now_iso) -> None:
        self.path = Path(path)
        self._now = now

    @classmethod
    def for_root(cls, root: Path, *, now=_utc_now_iso) -> "SuggestionLog":
        """A suggestion log at ``<root>/.kb-suggestions.jsonl``."""
        return cls(Path(root) / SUGGESTIONS_NAME, now=now)

    def record(
        self,
        subject: str,
        kind: str = "gap",
        topic: str = "",
        reason: str = "",
        by: str = "",
    ) -> dict:
        """Validate and append one suggestion, returning the entry.

        Raises ValueError (writing nothing) for a ``kind`` other than ``gap`` or
        ``subject``, an empty ``subject``, or any over-length field. Raises on
        I/O failure too; the caller reports both. The ``id`` is stable once
        written and unique per call, so a reader can track each suggestion.
        """
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        subject = _clean("subject", subject, MAX_SUBJECT, required=True)
        topic = _clean("topic", topic, MAX_TOPIC)
        reason = _clean("reason", reason, MAX_REASON)
        by = _clean("by", by, MAX_BY)
        ts = self._now()
        digest = hashlib.sha256(
            f"{ts}\0{subject}\0{secrets.token_hex(8)}".encode("utf-8")
        ).hexdigest()
        entry = {
            "id": "sg-" + digest[:12],
            "ts": ts,
            "kind": kind,
            "subject": subject,
            "topic": topic,
            "reason": reason,
            "by": by,
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
