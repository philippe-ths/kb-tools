"""Autonomous ingestion orchestrator with guarded auto-merge (ADR 0002).

The orchestrator detects pending ``raw/`` sources, ingests each one inside a
dedicated ``kb-maintenance/`` worktree via an injected agent, validates, commits,
runs an adversarial review, evaluates a deterministic fail-closed merge gate, and
pushes/opens/merges the pull request. Every side effect runs through an
injectable seam:

* ``CommandRunner`` (reused from :mod:`kb.maintenance`) executes git/gh.
* ``AgentRunner`` runs the ingest and review agents.

so the detection, gate evaluation, and control flow are unit-testable with fakes
while the live run shells out to ``git``, ``gh``, and ``claude``.

Validation runs *before* the commit. The worktree inherits the host repo's
``core.hooksPath``, so its pre-commit hook re-checks the recorded validation
result against the tree being committed; a result recorded after that commit can
never satisfy the hook that already ran. A validation failure therefore holds the
run at ``status: "validation-failed"`` before anything is committed, pushed, or
opened, and leaves the worktree in place for diagnosis.

The gate is the safety boundary. It merges only when validation passes,
verification shows zero total warnings, the diff is confined to the generated
wiki/control files, and the adversarial review raises no blocking objection.
Anything else leaves the PR open for the human (ADR 0002, ai-workflow.md).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .api import KnowledgeBase
from .ingest import pending_sources
from .maintenance import (
    DEFAULT_BASE_REF,
    DEFAULT_WORKTREE_ROOT,
    CommandResult,
    CommandRunner,
    MaintenanceError,
    _run_command,
    build_report,
    prepare_worktree,
    render_pr_body,
    run_validation,
    warning_counts,
)
from .vault import Vault

INGEST_PURPOSE = "ingest"
# Repo-relative paths a guarded auto-merge is allowed to touch. Anything else
# blocks the merge, so an agent that strays outside the generated layer cannot
# auto-land changes to code, policy, or raw/.
ALLOWED_MERGE_FILES = {"index.md", "log.md"}
# `raw/` is admitted so a page and its cited evidence merge together. The commit
# only ever contains this run's own pending sources (see _stage_and_commit), so
# the prefix widens what may land, not what the agent may put there.
ALLOWED_MERGE_PREFIXES = ("wiki/", "raw/")
# Only these paths are ever staged for the auto-ingest commit, plus this run's
# own pending raw sources (added per-run in _stage_and_commit). A generated page
# and the evidence it cites must land together, or the merged branch carries
# citations pointing at files that are not in the repository (ADR 0002).
STAGE_PATHS = ("wiki", "index.md", "log.md")

# Durable run-status file, written to the repo root on every completed run
# (success or failure), including when the run raises. Unlike launchd's
# `runs`/`last exit code` counters -- which reset on reboot -- this file
# survives, so a future session's preflight can read what actually happened
# instead of trusting launchd.
STATUS_FILENAME = ".kb-autoingest-status.json"


class AutoIngestError(MaintenanceError):
    """Raised when autonomous ingestion cannot proceed safely."""


@dataclass(frozen=True)
class AgentResult:
    """Outcome of an injected agent invocation.

    ``ok`` is False when the agent failed to run or complete. ``blocking`` is set
    by a review agent when it raises an objection that must stop the merge.
    """

    ok: bool
    output: str = ""
    blocking: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "output": self.output,
            "blocking": self.blocking,
            "reason": self.reason,
        }


class AgentRunner(Protocol):
    def __call__(
        self,
        *,
        kind: str,
        worktree: Path,
        root: Path,
        source: str | None = None,
        sources: list[str] | None = None,
    ) -> AgentResult: ...


# Same injection shape as `CommandRunner`: a plain callable, defaulting to
# `None` at the public API and resolved to a real implementation only at the
# point of use, so tests can pass a fake without touching the real notifier.
Notifier = Callable[[str, str], None]


def default_notifier(title: str, message: str) -> None:
    """Real ``Notifier``: a macOS notification banner via ``osascript``.

    Best-effort by construction (bounded timeout, no exception handling of its
    own) -- ``_notify_failure`` is the layer responsible for swallowing
    whatever this raises, matching the fail-open contract in Part 4.
    """

    def _escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    )
    subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=10
    )


def _notify_failure(
    notify: Notifier | None, *, report: dict | None, error: Exception | None
) -> None:
    """Fire a best-effort local notification for a failed run.

    Never raises and never affects the run's outcome: a missing ``osascript``,
    a non-macOS host, a non-zero exit, a timeout, or a test fake that raises on
    purpose are all swallowed here.
    """

    # Silent unless a notifier is supplied. The real one shells out to
    # osascript and puts a banner on a human's screen, so it must never be
    # what a caller gets by accident: any test that drives a failing run
    # without injecting a fake would otherwise notify for real. `__main__`
    # wires in `default_notifier` explicitly for the live run.
    if notify is None:
        return
    notifier = notify
    if error is not None:
        message = f"kb auto-ingest raised: {error}"
    else:
        status = (report or {}).get("status", "unknown")
        failures = (report or {}).get("failures") or []
        detail = "; ".join(failures) if failures else "see " + STATUS_FILENAME
        message = f"kb auto-ingest {status}: {detail}"
    try:
        notifier("kb auto-ingest failed", message)
    except Exception:
        pass


def path_allowed(rel_path: str) -> bool:
    """True when a changed path is inside the generated wiki/control layer."""

    if rel_path in ALLOWED_MERGE_FILES:
        return True
    return any(rel_path.startswith(prefix) for prefix in ALLOWED_MERGE_PREFIXES)


@dataclass
class GateDecision:
    merge_ok: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"merge_ok": self.merge_ok, "reasons": list(self.reasons)}


def evaluate_merge_gate(
    *,
    validation: CommandResult,
    verification_after: dict,
    changed_paths: list[str],
    review: AgentResult,
    uncommitted: list[str] | None = None,
) -> GateDecision:
    """Deterministic fail-closed gate (ADR 0002).

    Returns ``merge_ok`` only when every condition holds; otherwise lists the
    specific reasons the merge is withheld so they can be recorded on the PR.
    """

    reasons: list[str] = []

    if validation.skipped:
        reasons.append(f"validation skipped: {validation.reason or 'unknown reason'}")
    elif validation.returncode != 0:
        reasons.append(f"validation failed (exit {validation.returncode})")

    counts = warning_counts(verification_after)
    if counts["total"] != 0:
        reasons.append(f"verification has {counts['total']} warning(s)")

    disallowed = sorted(p for p in changed_paths if not path_allowed(p))
    if disallowed:
        reasons.append("diff touches disallowed paths: " + ", ".join(disallowed))

    if not changed_paths:
        reasons.append("no changes were produced")

    if not review.ok:
        reasons.append(f"adversarial review did not complete: {review.reason or 'error'}")
    elif review.blocking:
        reasons.append(f"adversarial review raised a blocking objection: {review.reason}")

    # Verification reads the worktree, so anything still uncommitted means it
    # judged a state the merge will not produce. That is how the gate came to
    # report zero warnings on branches that landed broken citations.
    if uncommitted:
        reasons.append(
            "worktree has uncommitted changes after the commit, so verification "
            "did not read the merged tree: " + ", ".join(sorted(uncommitted))
        )

    return GateDecision(merge_ok=not reasons, reasons=reasons)


def _resolve_base_commit(
    repo_root: Path, base_branch: str, runner: CommandRunner | None
) -> str:
    """Resolve the commit a run should branch from and diff against.

    The remote-tracking ref, not the local branch: a local branch only advances
    when someone pulls, so in a repo whose human never pulls it pins every run
    to the same old commit and each PR arrives conflicting with the last.
    Falls back to the local branch when there is no remote-tracking ref, which
    is the case for a repo with no remote.
    """

    for ref in (f"origin/{base_branch}", base_branch):
        result = _run_command(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            repo_root,
            runner=runner,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise AutoIngestError(f"cannot resolve a base commit for {base_branch!r}")


def _uncommitted_paths(worktree: Path, runner: CommandRunner | None) -> list[str]:
    """Paths still dirty or untracked in the worktree after the commit."""

    result = _run_command(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        worktree,
        runner=runner,
    )
    if result.returncode != 0:
        return ["<git status failed>"]
    return [line[3:].strip() for line in result.stdout.splitlines() if line.strip()]


def _changed_paths(
    worktree: Path, base_ref: str, runner: CommandRunner | None
) -> list[str]:
    result = _run_command(
        ["git", "diff", "--name-only", base_ref, "HEAD"], worktree, runner=runner
    )
    if result.returncode != 0:
        raise AutoIngestError(result.stderr.strip() or "git diff failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _require(result: CommandResult, message: str) -> CommandResult:
    if result.returncode != 0:
        raise AutoIngestError(result.stderr.strip() or message)
    return result


def _stage_raw_inputs(root: Path, worktree: Path, pending: list[str]) -> None:
    """Copy each pending raw source into the worktree as a read-only input.

    The worktree is a clean checkout of the base ref, so a newly-dropped
    (untracked) raw file is absent there. Copying it in lets the agent read its
    evidence; it is never staged (see :data:`STAGE_PATHS`), so it cannot reach
    the commit.
    """

    for source in pending:
        src = root / f"{source}.md"
        if not src.is_file():
            continue
        dst = worktree / f"{source}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _stage_and_commit(
    worktree: Path,
    message: str,
    runner: CommandRunner | None,
    pending: list[str] | None = None,
) -> bool:
    """Stage the generated layer plus this run's evidence. False if nothing staged.

    ``pending`` names this run's raw sources by path stem. They are staged
    individually rather than by prefix so that widening the merge gate to admit
    ``raw/`` cannot be used to land raw content the run did not claim.
    """

    paths = [*STAGE_PATHS, *(f"{source}.md" for source in pending or ())]
    _require(
        _run_command(["git", "add", "--", *paths], worktree, runner=runner),
        "git add failed",
    )
    staged = _run_command(
        ["git", "diff", "--cached", "--name-only"], worktree, runner=runner
    )
    if not staged.stdout.strip():
        return False
    _require(
        _run_command(["git", "commit", "-m", message], worktree, runner=runner),
        "git commit failed",
    )
    return True


def _ingest_failures(ingested: list[dict]) -> list[str]:
    """One line per source the ingest agent did not complete.

    Used to draw the line between a benign no-op (`no-changes`: agents ran ok,
    just produced no diff) and a failed one (`ingest-failed`: sources were
    pending, ingestion was attempted, and nothing landed because the agent
    calls failed). Also surfaced verbatim as the top-level `failures` field so
    a reader does not have to walk `ingested[i]["reason"]`.
    """

    return [
        f"{item['source']}: {item.get('reason') or 'agent did not complete'}"
        for item in ingested
        if not item["ok"]
    ]


def run_auto_ingest(
    repo_root: str | Path,
    *,
    ingest_agent: AgentRunner,
    review_agent: AgentRunner,
    runner: CommandRunner | None = None,
    run_date: date | None = None,
    worktree_root: str | Path = DEFAULT_WORKTREE_ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    auto_merge: bool = True,
    validate: bool = True,
    fetch: bool = True,
    notify: Notifier | None = None,
    status_path: str | Path | None = None,
) -> dict:
    """Detect, ingest, review, gate, and (if green) auto-merge pending sources.

    Every completed run -- success or failure, including a raised
    ``AutoIngestError`` -- writes a durable JSON status file (``status_path``,
    default ``<repo_root>/.kb-autoingest-status.json``) so a future session's
    preflight can read what actually happened instead of trusting launchd's
    `runs`/`last exit code` counters, which reset on reboot. A failed run
    (top-level ``ok: False``, or a raised error) also fires a best-effort local
    notification through ``notify``; a broken notifier is swallowed and never
    changes the run's outcome (see :func:`_notify_failure`). ``notify`` defaults
    to ``None``, meaning silent: the CLI passes :func:`default_notifier` for the
    live run so no test can fire a real banner by omission.
    """

    root = Path(repo_root).resolve()
    progress: dict = {"pending": None, "branch": None, "pr_url": None}
    report: dict | None = None
    error: Exception | None = None
    try:
        report = _execute(
            root,
            ingest_agent=ingest_agent,
            review_agent=review_agent,
            runner=runner,
            run_date=run_date,
            worktree_root=worktree_root,
            base_ref=base_ref,
            auto_merge=auto_merge,
            validate=validate,
            fetch=fetch,
            progress=progress,
        )
        return report
    except Exception as exc:
        error = exc
        raise
    finally:
        _write_status_file(root, status_path, report=report, error=error, progress=progress)
        failed = error is not None or (report is not None and not report.get("ok", True))
        if failed:
            _notify_failure(notify, report=report, error=error)


def _execute(
    root: Path,
    *,
    ingest_agent: AgentRunner,
    review_agent: AgentRunner,
    runner: CommandRunner | None,
    run_date: date | None,
    worktree_root: str | Path,
    base_ref: str,
    auto_merge: bool,
    validate: bool,
    fetch: bool,
    progress: dict,
) -> dict:
    """The orchestration itself, wrapped by :func:`run_auto_ingest` for Part 3/4.

    ``progress`` is filled in as fields become known, so the wrapper still has
    something to record in the status file if this raises before returning.
    """

    vault = Vault.open(root)
    pending = pending_sources(vault)
    progress["pending"] = pending
    if not pending:
        return {"status": "idle", "pending": [], "merged": False, "ok": True, "failures": []}

    if fetch:
        # Best-effort refresh of the base ref; a failure here is not fatal.
        _run_command(["git", "fetch", "origin", base_ref], root, runner=runner)

    # `base_ref` names the branch the PR targets; `base_commit` is what this run
    # actually branches from and diffs against. They differ whenever the local
    # branch is behind the remote, which is the normal state of a repo whose
    # human reads the vault but never pulls.
    base_commit = _resolve_base_commit(root, base_ref, runner)

    plan = prepare_worktree(
        root,
        purpose=INGEST_PURPOSE,
        run_date=run_date,
        worktree_root=worktree_root,
        base_ref=base_commit,
        execute=True,
        runner=runner,
    )
    branch = plan["branch"]
    progress["branch"] = branch
    worktree = Path(plan["worktree"])

    ingested: list[dict] = []
    merged = False
    keep_worktree = False
    try:
        _stage_raw_inputs(root, worktree, pending)

        # Snapshot the base before ingestion, from the worktree. Reading the
        # repo root instead compares the run's result against the human's
        # working directory, so uncommitted vault edits show up as deltas of a
        # run that never touched them.
        before = KnowledgeBase.open(worktree).verify()

        for source in pending:
            result = ingest_agent(
                kind="ingest", source=source, worktree=worktree, root=root
            )
            ingested.append({"source": source, **result.to_dict()})

        # A run where ingestion was attempted and every agent call failed must
        # not read the same as a quiet week: `_stage_and_commit` returning
        # False is ambiguous on its own (agents.py returns AgentResult(ok=False)
        # rather than raising), so the boundary is decided here from the
        # collected per-source results, not from the empty diff alone.
        failures = _ingest_failures(ingested)

        # Validate before attempting the commit, not after. The worktree's
        # pre-commit hook (wired via core.hooksPath in the host repo) re-checks
        # a recorded validation result against the tree at commit time; a
        # result recorded after the commit can never satisfy a hook that already
        # ran. Validating here also means a real failure holds before anything
        # is committed, pushed, or opened as a PR, rather than surfacing as a
        # git-commit failure the hook raised for an unrelated reason.
        validation = run_validation(worktree, runner=runner, enabled=validate)
        if not validation.skipped and validation.returncode != 0:
            # Held for diagnosis: leave the worktree in place (skip cleanup)
            # rather than deleting the only copy of what failed to validate.
            keep_worktree = True
            return {
                "status": "validation-failed",
                "pending": pending,
                "branch": branch,
                "worktree": str(worktree),
                "ingested": ingested,
                "validation": validation.to_dict(),
                "merged": False,
                # Without these two the wrapper's `report.get("ok", True)`
                # would read this hold as a success: no notification, exit 0,
                # and a status file disagreeing with both.
                "ok": False,
                "failures": failures
                + [f"validation failed (exit {validation.returncode})"],
            }

        commit_message = f"kb auto-ingest: {len(pending)} source(s)"
        if not _stage_and_commit(worktree, commit_message, runner, pending):
            _cleanup_worktree(root, worktree, runner)
            if failures:
                return {
                    "status": "ingest-failed",
                    "pending": pending,
                    "branch": branch,
                    "ingested": ingested,
                    "merged": False,
                    "ok": False,
                    "failures": failures,
                }
            return {
                "status": "no-changes",
                "pending": pending,
                "branch": branch,
                "ingested": ingested,
                "merged": False,
                "ok": True,
                "failures": [],
            }

        changed = _changed_paths(worktree, base_commit, runner)
        review = review_agent(
            kind="review", sources=pending, worktree=worktree, root=root
        )
        after = KnowledgeBase.open(worktree).verify()
        uncommitted = _uncommitted_paths(worktree, runner)

        gate = evaluate_merge_gate(
            validation=validation,
            verification_after=after,
            changed_paths=changed,
            review=review,
            uncommitted=uncommitted,
        )

        report = build_report(
            repo_root=worktree,
            mode="apply",
            before=before,
            after=after,
            validation=validation,
            operations=[{"op": "auto-ingest", "target": s, "action": "ingest"} for s in pending],
            branch=branch,
            worktree=str(worktree),
            residual_risks=gate.reasons,
        )
        body = _pr_body(report, gate, review, changed)

        _require(
            _run_command(
                ["git", "push", "-u", "origin", branch], worktree, runner=runner
            ),
            "git push failed",
        )
        pr = _create_pr(worktree, branch, base_ref, pending, body, runner)
        progress["pr_url"] = pr

        if auto_merge and gate.merge_ok:
            # No --delete-branch: gh switches the checkout to the default branch
            # to drop the merged branch, which fails inside a linked worktree
            # ("'main' is already checked out"). Merge only here; the branch refs
            # are cleaned up below, once the worktree is pruned.
            _require(
                _run_command(
                    ["gh", "pr", "merge", branch, "--squash"],
                    worktree,
                    runner=runner,
                ),
                "gh pr merge failed",
            )
            merged = True
    finally:
        # keep_worktree is set only for the validation-failed hold above, where
        # the worktree is deliberately left in place for diagnosis instead of
        # being cleaned up here.
        if not keep_worktree:
            _cleanup_worktree(root, worktree, runner)
            if merged:
                _delete_merged_branch(root, branch, runner)

    # `pr-open` is the gate holding a change for human review -- the system
    # working as designed, not a failure -- so both terminal states here are
    # `ok: True`. `failures` still reports any individual agent call that
    # failed even though the run as a whole reached a PR.
    return {
        "status": "merged" if merged else "pr-open",
        "pending": pending,
        "branch": branch,
        "pr_url": pr,
        "ingested": ingested,
        "review": review.to_dict(),
        "changed_paths": changed,
        "base_commit": base_commit,
        "gate": gate.to_dict(),
        "merged": merged,
        "report": report,
        "ok": True,
        "failures": failures,
    }


def _write_status_file(
    root: Path,
    status_path: str | Path | None,
    *,
    report: dict | None,
    error: Exception | None,
    progress: dict,
) -> None:
    """Persist the durable run-status file described in Part 3.

    Best-effort: a failure to build or write this file must never mask the
    run's real outcome, so this swallows everything rather than letting an
    exception here replace one already propagating out of the `finally` block
    in :func:`run_auto_ingest`.
    """

    path = Path(status_path) if status_path is not None else root / STATUS_FILENAME
    try:
        payload = _status_payload(report=report, error=error, progress=progress)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except Exception:
        pass


def _status_payload(
    *, report: dict | None, error: Exception | None, progress: dict
) -> dict:
    timestamp = datetime.now(timezone.utc).isoformat()
    if report is not None:
        pending = report.get("pending") or []
        return {
            "timestamp": timestamp,
            "ok": bool(report.get("ok", False)),
            "status": report.get("status", "unknown"),
            "pending_count": len(pending),
            "branch": report.get("branch"),
            "pr_url": report.get("pr_url"),
            "failures": list(report.get("failures", [])),
        }
    # The run raised before producing a report (e.g. push/gh/git-infra
    # failures). `progress` carries whatever was learned before that point.
    pending = progress.get("pending") or []
    return {
        "timestamp": timestamp,
        "ok": False,
        "status": "error",
        "pending_count": len(pending),
        "branch": progress.get("branch"),
        "pr_url": progress.get("pr_url"),
        "failures": [str(error)] if error is not None else [],
    }


def _create_pr(
    worktree: Path,
    branch: str,
    base_ref: str,
    pending: list[str],
    body: str,
    runner: CommandRunner | None,
) -> str:
    title = f"kb auto-ingest: {len(pending)} source(s)"
    body_path = worktree / "auto-ingest-pr.md"
    body_path.write_text(body, encoding="utf-8")
    result = _run_command(
        [
            "gh",
            "pr",
            "create",
            "--base",
            base_ref,
            "--head",
            branch,
            "--title",
            title,
            "--body-file",
            str(body_path),
        ],
        worktree,
        runner=runner,
    )
    _require(result, "gh pr create failed")
    return result.stdout.strip()


def _pr_body(
    report: dict, gate: GateDecision, review: AgentResult, changed: list[str]
) -> str:
    lines = [render_pr_body(report), "", "## Auto-merge gate"]
    lines.append(f"- decision: {'MERGE' if gate.merge_ok else 'HOLD (PR left open)'}")
    if gate.reasons:
        lines.append("- withheld because:")
        lines.extend(f"  - {reason}" for reason in gate.reasons)
    lines.append("")
    lines.append("## Adversarial review")
    lines.append(f"- completed: {review.ok}  blocking: {review.blocking}")
    if review.reason:
        lines.append(f"- note: {review.reason}")
    lines.append("")
    lines.append("## Changed files")
    lines.extend(f"- {path}" for path in changed)
    return "\n".join(lines) + "\n"


def _cleanup_worktree(
    root: Path, worktree: Path, runner: CommandRunner | None
) -> None:
    """Remove a maintenance worktree in a way that works on old Git.

    ``git worktree remove`` only exists from Git 2.17, but this repo targets Git
    2.14 (see ``_ensure_ref_namespace`` in maintenance.py). Deleting the working
    directory and pruning the administrative entry is equivalent and
    version-independent. Best-effort: a cleanup failure must never mask the run's
    real outcome.
    """

    shutil.rmtree(worktree, ignore_errors=True)
    _run_command(["git", "worktree", "prune"], root, runner=runner)


def _delete_merged_branch(
    root: Path, branch: str, runner: CommandRunner | None
) -> None:
    """Drop the local and remote refs for a branch whose PR has merged.

    Runs only after the worktree is pruned, so the branch is no longer checked
    out and ``git branch -D`` succeeds. Best-effort: the PR is already merged, so
    a failure here is cosmetic and must not raise.
    """

    _run_command(["git", "branch", "-D", branch], root, runner=runner)
    _run_command(["git", "push", "origin", "--delete", branch], root, runner=runner)
