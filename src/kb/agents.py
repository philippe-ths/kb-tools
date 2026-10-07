"""Live Claude-backed agent runner for autonomous ingestion (ADR 0002).

This is the default implementation of the ``AgentRunner`` seam in
:mod:`kb.autoingest`. It shells out to the ``claude`` CLI in headless
(``-p``) mode, with the knowledge-base MCP server scoped to the maintenance
worktree and tools restricted to that server. The orchestrator and gate never
depend on this module directly; tests inject fakes instead.

Each call is sealed: a model and effort chosen per role, a system prompt of
its own (the role plus the vault's ``kb-schema.md``), only the knowledge-base
MCP server, no built-in tools, no settings, skills or CLAUDE.md, run from an
empty directory. Ingest summarises one source, so it runs on Sonnet; the review
is the one truth check per run, so it keeps Opus. Each result carries the
call's cost and token usage from the CLI's JSON envelope.

The review runner fails closed: if it cannot positively confirm a clean verdict
it reports a blocking objection, so an unparseable or failed review holds the PR
open rather than letting it merge.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .autoingest import AgentResult
from .install import server_python

CLAUDE_BIN = "claude"

# A single headless claude call is bounded so a hung process cannot pin the
# unattended run forever; on expiry we synthesise a non-zero result and let the
# retry path handle it like any other failure.
CLAUDE_TIMEOUT_SECONDS = 900
# Model and effort per role, overridable by environment for a vault that
# wants different trade-offs (KB_INGEST_MODEL, KB_INGEST_EFFORT, KB_REVIEW_...).
INGEST_MODEL = os.environ.get("KB_INGEST_MODEL", "claude-sonnet-5-5")
INGEST_EFFORT = os.environ.get("KB_INGEST_EFFORT", "medium")
REVIEW_MODEL = os.environ.get("KB_REVIEW_MODEL", "claude-opus-5-5")
REVIEW_EFFORT = os.environ.get("KB_REVIEW_EFFORT", "high")
SCHEMA_FILE = "kb-schema.md"
# Transient CLI failures (overload, network, timeout) once parked an open PR
# with an empty-output "claude review failed". The review is read-only, so it
# is safe to retry with backoff. Ingest stays single-attempt: kb_apply_changes
# is not idempotent, so retrying a write that already partially landed could
# duplicate an appended log line.
REVIEW_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 15
# Conventional shell exit code for a timed-out command.
TIMEOUT_RETURNCODE = 124


def _mcp_config(root: Path, worktree: Path) -> str:
    payload = {
        "mcpServers": {
            "knowledge-base": {
                "command": server_python(root),
                "args": ["-m", "kb.server", "--root", str(worktree)],
            }
        }
    }
    return json.dumps(payload)


def _system_prompt(worktree: Path, role: str) -> str:
    """The role, then the vault's own conventions; nothing else from the vault."""

    schema_path = Path(worktree) / SCHEMA_FILE
    schema = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
    return (
        f"You are the {role} for a personal Obsidian knowledge base. You work only "
        "through the knowledge-base MCP tools. The vault's conventions follow.\n\n"
        + schema
    )


def _ingest_prompt(source: str) -> str:
    return (
        "Follow the ingest operation in kb-schema.md for exactly one source: "
        f"`{source}`. Read that raw source via the knowledge-base MCP tools, then "
        "build a change set with kb_propose_changes and commit it with "
        "kb_apply_changes that: writes or updates a wiki/ summary page, adds its "
        "catalog line with one add_index_entry op (pick the category from "
        "kb_graph_summary; never rewrite index.md with write_index), appends one "
        "log.md line, and links the page into the wiki: add a [[wikilink]] to it "
        "from at least one existing wiki page, the closest related one, or the "
        "topic's overview or map page when nothing is closer (index.md does not "
        "count). Cite the raw source. Only write under wiki/, index.md, and "
        "log.md; never edit raw/ or any code or policy file. You are done only "
        "when kb_verify reports no warning that was not there before you began, "
        "which is the check the merge gate applies; fix any it reports. Then "
        "output a one-line summary."
    )


def _review_prompt(sources: list[str]) -> str:
    cited = ", ".join(sources) if sources else "the sources just ingested"
    return (
        "You are an adversarial reviewer. Using only the knowledge-base MCP "
        "tools, read each wiki page that was just written or updated for these "
        f"sources ({cited}) with kb_read_page, and read the raw source each one "
        "cites. Try to refute the pages: unsupported claims, miscitations, "
        "contradictions with existing pages, fabricated detail. Also call "
        "kb_verify and treat any new warning as a problem. Respond with ONLY a "
        'JSON object on the final line: {"blocking": true|false, "reason": '
        '"<short>"}. Set blocking true if any new page makes a claim its cited '
        "source does not support."
    )


# Strict allowlist: knowledge-base MCP tools only. No Bash, no Write/Edit, and
# no bypassPermissions. The agent can read raw and wiki and propose/apply changes
# through the guarded vault writers (which refuse raw/ writes), but it cannot
# touch the filesystem directly. Default-deny is the primary sandbox; the merge
# gate is the backstop (ADR 0002).
ALLOWED_TOOLS = ",".join(
    f"mcp__knowledge-base__{name}"
    for name in (
        "kb_search",
        "kb_read_page",
        "kb_build_context",
        "kb_graph_summary",
        "kb_propose_changes",
        "kb_apply_changes",
        "kb_verify",
    )
)


def _invoke_claude_once(
    cmd: list[str], worktree: Path
) -> subprocess.CompletedProcess:
    """One headless claude call, bounded by ``CLAUDE_TIMEOUT_SECONDS``.

    A timeout is normalised to a non-zero ``CompletedProcess`` rather than a
    raised exception, so callers treat it like any other failed run.
    """

    # An empty working directory, so no CLAUDE.md or project settings load;
    # the agent reaches the vault only through the MCP server.
    try:
        with tempfile.TemporaryDirectory(prefix="kb-agent-") as empty:
            return subprocess.run(
                cmd,
                cwd=empty,
                capture_output=True,
                text=True,
                timeout=CLAUDE_TIMEOUT_SECONDS,
            )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        note = f"claude call exceeded {CLAUDE_TIMEOUT_SECONDS}s timeout"
        stderr = f"{stderr}\n{note}".strip()
        return subprocess.CompletedProcess(
            cmd, TIMEOUT_RETURNCODE, stdout=stdout, stderr=stderr
        )


def _run_claude(
    prompt: str,
    worktree: Path,
    root: Path,
    *,
    attempts: int = 1,
    sleeper: Callable[[float], None] = time.sleep,
    role: str = "ingest agent",
    model: str = INGEST_MODEL,
    effort: str = INGEST_EFFORT,
) -> subprocess.CompletedProcess:
    """Run a headless claude call, retrying transient failures.

    Returns the first zero-exit result, or the last failure after ``attempts``
    tries. Retries use a linear backoff; ``attempts=1`` disables retrying.
    Only safe-to-repeat (read-only) calls should pass ``attempts > 1``.
    """

    cmd = [
        CLAUDE_BIN,
        "-p",
        prompt,
        "--output-format",
        "json",
        "--mcp-config",
        _mcp_config(root, worktree),
        "--strict-mcp-config",
        "--allowedTools",
        ALLOWED_TOOLS,
        "--tools",
        "",
        "--permission-mode",
        "default",
        "--model",
        model,
        "--effort",
        effort,
        "--system-prompt",
        _system_prompt(worktree, role),
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    completed = _invoke_claude_once(cmd, worktree)
    attempt = 1
    while completed.returncode != 0 and attempt < attempts:
        sleeper(RETRY_BACKOFF_SECONDS * attempt)
        completed = _invoke_claude_once(cmd, worktree)
        attempt += 1
    return completed


def _result_text(completed: subprocess.CompletedProcess) -> str:
    """Pull the assistant text out of the claude --output-format json envelope."""

    try:
        envelope = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return completed.stdout
    if isinstance(envelope, dict):
        return str(envelope.get("result", completed.stdout))
    return completed.stdout


def _usage(completed: subprocess.CompletedProcess) -> dict:
    """Cost and token usage from the claude JSON envelope; empty when absent."""

    try:
        envelope = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError, TypeError):
        return {}
    if not isinstance(envelope, dict):
        return {}
    usage = envelope.get("usage") or {}
    return {
        "cost_usd": envelope.get("total_cost_usd"),
        "duration_ms": envelope.get("duration_ms"),
        "turns": envelope.get("num_turns"),
        "input_tokens": usage.get("input_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
    }


def _parse_verdict(text: str) -> tuple[bool, str]:
    """Return (blocking, reason). Fail closed when no clean verdict is found."""

    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            verdict = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if "blocking" in verdict:
            return bool(verdict["blocking"]), str(verdict.get("reason", ""))
    return True, "no parseable review verdict; holding merge"


def claude_agent_runner(
    *,
    kind: str,
    worktree: Path,
    root: Path,
    source: str | None = None,
    sources: list[str] | None = None,
) -> AgentResult:
    """Default ``AgentRunner``: drive ingest or review through the claude CLI."""

    if kind == "ingest":
        # Single attempt: a write that partially landed must not be replayed.
        completed = _run_claude(_ingest_prompt(source or ""), worktree, root)
        if completed.returncode != 0:
            return AgentResult(
                ok=False,
                output=completed.stderr,
                reason=f"claude ingest failed (exit {completed.returncode})",
                usage=_usage(completed),
            )
        return AgentResult(ok=True, output=_result_text(completed), usage=_usage(completed))

    if kind == "review":
        # Read-only, so retry transient CLI failures before holding the merge.
        completed = _run_claude(
            _review_prompt(sources or []),
            worktree,
            root,
            attempts=REVIEW_ATTEMPTS,
            role="adversarial reviewer",
            model=REVIEW_MODEL,
            effort=REVIEW_EFFORT,
        )
        if completed.returncode != 0:
            return AgentResult(
                ok=False,
                output=completed.stderr,
                blocking=True,
                reason=f"claude review failed (exit {completed.returncode})",
                usage=_usage(completed),
            )
        text = _result_text(completed)
        blocking, reason = _parse_verdict(text)
        return AgentResult(
            ok=True, output=text, blocking=blocking, reason=reason, usage=_usage(completed)
        )

    raise ValueError(f"unknown agent kind: {kind}")
