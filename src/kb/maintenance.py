"""Milestone 3 maintenance runner, worktree planning, and PR reporting.

This module keeps the autonomous-maintenance substrate deterministic and local.
It can audit the vault, preview or apply an approved change set, run repository
validation, prepare a maintenance worktree command, and render the PR report
described in ADR 0001. It does not push branches or open pull requests; those
remote actions stay explicit human-approved steps.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .api import KnowledgeBase
from .verify import report_delta

DEFAULT_PURPOSE = "wiki-health"
DEFAULT_BASE_REF = "main"
DEFAULT_WORKTREE_ROOT = "~/.cache/kb-maintenance/worktrees"
VALIDATION_SCRIPT = ".ai-policy/scripts/run-validation.sh"
VALIDATION_BOOTSTRAP_PATHS = (
    ".ai-policy",
    ".codex",
    ".githooks",
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CommandResult:
    """Captured command result for report generation."""

    command: tuple[str, ...]
    cwd: str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "command": list(self.command),
            "cwd": self.cwd,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "skipped": self.skipped,
            "reason": self.reason,
        }


class MaintenanceError(Exception):
    """Raised when maintenance orchestration cannot complete safely."""


def _run_command(
    command: list[str],
    cwd: Path,
    runner: CommandRunner | None = None,
) -> CommandResult:
    runner = runner or subprocess.run
    completed = runner(command, cwd=str(cwd), capture_output=True, text=True)
    return CommandResult(
        command=tuple(command),
        cwd=str(cwd),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or DEFAULT_PURPOSE


def maintenance_branch_name(
    run_date: date | None = None,
    purpose: str = DEFAULT_PURPOSE,
    existing: Iterable[str] = (),
) -> str:
    """Return a collision-safe ``kb-maintenance/YYYY-MM-DD-purpose`` branch."""

    run_date = run_date or _today()
    stem = f"kb-maintenance/{run_date.isoformat()}-{_slug(purpose)}"
    existing_set = set(existing)
    if stem not in existing_set:
        return stem
    suffix = 2
    while f"{stem}-{suffix}" in existing_set:
        suffix += 1
    return f"{stem}-{suffix}"


def worktree_path_for(
    branch: str,
    worktree_root: str | Path = DEFAULT_WORKTREE_ROOT,
) -> Path:
    """Return the local worktree path for a maintenance branch."""

    root = Path(worktree_root).expanduser()
    return root / branch.replace("/", "--")


def _local_branches(repo_root: Path, runner: CommandRunner | None = None) -> list[str]:
    result = _run_command(
        ["git", "branch", "--format", "%(refname:short)"],
        repo_root,
        runner=runner,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _git_dir(repo_root: Path, runner: CommandRunner | None = None) -> Path:
    result = _run_command(["git", "rev-parse", "--git-dir"], repo_root, runner=runner)
    if result.returncode != 0:
        raise MaintenanceError(result.stderr.strip() or "not a git repository")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else (repo_root / path).resolve()


def _ensure_ref_namespace(
    repo_root: Path,
    branch: str,
    runner: CommandRunner | None = None,
) -> None:
    """Create the loose-ref namespace directory for older Git versions.

    Git 2.14 can create `feature/foo` only when `.git/refs/heads/feature`
    already exists. ADR 0001 requires `kb-maintenance/YYYY-MM-DD-purpose`, so
    execution prepares that namespace before running `git worktree add -b`.
    """

    if "/" not in branch:
        return
    git_dir = _git_dir(repo_root, runner=runner)
    namespace = git_dir / "refs/heads" / branch.rsplit("/", 1)[0]
    if namespace.exists() and not namespace.is_dir():
        raise MaintenanceError(f"ref namespace is blocked by a file: {namespace}")
    namespace.mkdir(parents=True, exist_ok=True)


def prepare_worktree(
    repo_root: str | Path,
    purpose: str = DEFAULT_PURPOSE,
    run_date: date | None = None,
    worktree_root: str | Path = DEFAULT_WORKTREE_ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    execute: bool = False,
    bootstrap_validation: bool = True,
    runner: CommandRunner | None = None,
) -> dict:
    """Plan, and optionally create, the weekly maintenance worktree."""

    root = Path(repo_root).resolve()
    existing = _local_branches(root, runner=runner)
    branch = maintenance_branch_name(run_date, purpose, existing)
    path = worktree_path_for(branch, worktree_root)
    command = ["git", "worktree", "add", "-b", branch, str(path), base_ref]
    result = None
    bootstrapped: list[str] = []
    if execute:
        _ensure_ref_namespace(root, branch, runner=runner)
        path.parent.mkdir(parents=True, exist_ok=True)
        command_result = _run_command(command, root, runner=runner)
        if command_result.returncode != 0:
            raise MaintenanceError(
                command_result.stderr.strip() or "git worktree add failed"
            )
        if bootstrap_validation:
            bootstrapped = bootstrap_validation_support(root, path)
        result = command_result.to_dict()
    return {
        "branch": branch,
        "worktree": str(path),
        "base_ref": base_ref,
        "command": command,
        "executed": execute,
        "bootstrapped": bootstrapped,
        "result": result,
    }


def bootstrap_validation_support(
    source_root: str | Path,
    worktree_root: str | Path,
    paths: Iterable[str] = VALIDATION_BOOTSTRAP_PATHS,
) -> list[str]:
    """Copy ignored AI Workflow support files into a maintenance worktree.

    The workflow support directories are intentionally not committed in this
    vault, but the policy validation command depends on them. A fresh git
    worktree therefore needs a local bootstrap copy before it can validate.
    """

    source = Path(source_root).resolve()
    target = Path(worktree_root).resolve()
    copied: list[str] = []
    for rel in paths:
        src = source / rel
        dst = target / rel
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(
                src,
                dst,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(rel)
    _exclude_leaked_validation_state(target)
    return copied


def _exclude_leaked_validation_state(worktree_root: Path) -> None:
    """Delete any recorded validation state the bootstrap copy just brought in.

    A fresh worktree must never inherit another checkout's recorded validation
    result: ``.ai-policy/state/`` holds a ``passed <fingerprint>`` line computed
    against a completely different tree, and ``copytree`` preserves it (mtime
    included) as if it were current. This is a deliberate, visible removal
    step -- not an ``ignore_patterns`` entry folded into the copy above -- so a
    fresh worktree always starts with no validation state at all. The policy
    gate then fails closed ("no validation status found") instead of trusting a
    foreign pass.
    """

    state_dir = worktree_root / ".ai-policy" / "state"
    shutil.rmtree(state_dir, ignore_errors=True)


def warning_counts(report: dict) -> dict:
    """Count every phase-1 warning bucket in a verification report."""

    hygiene = report["hygiene"]
    citations = report["citations"]
    counts = {
        "broken_links": len(hygiene["broken_links"]),
        "missing_pages": len(hygiene["missing_pages"]),
        "orphan_pages": len(hygiene["orphan_pages"]),
        "uncited_pages": len(citations["uncited_pages"]),
        "sources_without_raw_link": len(citations["sources_without_raw_link"]),
        "broken_citations": len(citations["broken_citations"]),
    }
    counts["total"] = sum(counts.values())
    return counts


def warning_count_delta(before: dict, after: dict) -> dict:
    """Count warning changes, including missing-page totals for reporting."""

    before_counts = warning_counts(before)
    after_counts = warning_counts(after)
    return {
        key: after_counts[key] - before_counts[key]
        for key in sorted(before_counts)
    }


def run_validation(
    repo_root: str | Path,
    runner: CommandRunner | None = None,
    enabled: bool = True,
) -> CommandResult:
    """Run the repository validation script used before PR preparation."""

    root = Path(repo_root).resolve()
    script = root / VALIDATION_SCRIPT
    if not enabled:
        return CommandResult(
            command=(),
            cwd=str(root),
            returncode=0,
            skipped=True,
            reason="validation disabled",
        )
    if not script.is_file():
        return CommandResult(
            command=("bash", VALIDATION_SCRIPT),
            cwd=str(root),
            returncode=0,
            skipped=True,
            reason=f"validation script not found: {VALIDATION_SCRIPT}",
        )
    return _run_command(["bash", VALIDATION_SCRIPT], root, runner=runner)


def build_report(
    *,
    repo_root: str | Path,
    mode: str,
    before: dict,
    after: dict,
    validation: CommandResult,
    operations: list[dict] | None = None,
    branch: str | None = None,
    worktree: str | None = None,
    residual_risks: list[str] | None = None,
) -> dict:
    """Build the machine-readable maintenance report."""

    operations = operations or []
    residual_risks = residual_risks or []
    before_counts = warning_counts(before)
    after_counts = warning_counts(after)
    delta = warning_count_delta(before, after)
    warning_keys = [key for key in delta if key != "total"]
    validation_passed = not validation.skipped and validation.returncode == 0
    changed = mode == "apply" and bool(operations)
    pr_state = "ready" if validation_passed and after_counts["total"] == 0 else "draft"
    if not changed:
        pr_state = "none"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(Path(repo_root).resolve()),
        "mode": mode,
        "branch": branch,
        "worktree": worktree,
        "changed": changed,
        "operations": operations,
        "warnings": {
            "before": before_counts,
            "after": after_counts,
            "delta": delta,
            "fixed": sum(abs(delta[key]) for key in warning_keys if delta[key] < 0),
            "introduced": sum(delta[key] for key in warning_keys if delta[key] > 0),
        },
        "verification": {"before": before, "after": after},
        "validation": validation.to_dict(),
        "pr": {
            "state": pr_state,
            "title": "Weekly KB maintenance"
            if branch is None
            else f"Weekly KB maintenance: {branch.rsplit('/', 1)[-1]}",
            "needs_remote_action": changed,
        },
        "residual_risks": residual_risks,
    }


def run_maintenance(
    repo_root: str | Path,
    changes: list[dict] | None = None,
    apply_changes: bool = False,
    validate: bool = True,
    branch: str | None = None,
    worktree: str | None = None,
    runner: CommandRunner | None = None,
) -> dict:
    """Audit the vault, optionally preview/apply a change set, and report."""

    kb = KnowledgeBase.open(repo_root)
    before = kb.verify()
    operations: list[dict] = []
    if changes is None:
        mode = "audit"
        after = kb.verify()
    elif apply_changes:
        mode = "apply"
        applied = kb.apply(changes)
        operations = applied["applied"]
        after = applied["verification"]
    else:
        mode = "propose"
        proposal = kb.propose(changes)
        operations = proposal["operations"]
        after = proposal["verification"]["after"]
    validation = run_validation(repo_root, runner=runner, enabled=validate)
    residual_risks = []
    if changes is not None and not apply_changes:
        residual_risks.append("changes were proposed only and were not written")
    if validation.skipped:
        residual_risks.append(validation.reason)
    return build_report(
        repo_root=repo_root,
        mode=mode,
        before=before,
        after=after,
        validation=validation,
        operations=operations,
        branch=branch,
        worktree=worktree,
        residual_risks=residual_risks,
    )


def _format_counts(counts: dict) -> str:
    ordered = (
        "broken_links",
        "missing_pages",
        "orphan_pages",
        "uncited_pages",
        "sources_without_raw_link",
        "broken_citations",
        "total",
    )
    return "\n".join(f"- {key}: {counts[key]}" for key in ordered)


def _format_graph_stats(stats: dict) -> str:
    ordered = (
        "pages",
        "wiki_pages",
        "links",
        "resolved_links",
        "broken_links",
        "missing_pages",
        "orphan_pages",
        "categories",
    )
    return "\n".join(f"- {key}: {stats[key]}" for key in ordered)


def render_pr_body(report: dict) -> str:
    """Render the autonomous-maintenance PR body from a report dict."""

    validation = report["validation"]
    stdout = validation["stdout"].strip() or "(no stdout)"
    stderr = validation["stderr"].strip() or "(no stderr)"
    operations = report["operations"]
    operations_text = (
        "\n".join(
            f"- {op.get('action', 'change')} {op.get('target')} ({op.get('op')})"
            for op in operations
        )
        if operations
        else "- No file changes were made."
    )
    risks = report["residual_risks"] or ["None known."]
    risk_text = "\n".join(f"- {risk}" for risk in risks)
    before_graph = report["verification"]["before"]["graph"]
    after_graph = report["verification"]["after"]["graph"]
    return f"""# Maintenance report

## Summary
- Mode: {report["mode"]}
- Branch: {report["branch"] or "(not assigned)"}
- Worktree: {report["worktree"] or "(not assigned)"}
- PR state: {report["pr"]["state"]}

## Operations
{operations_text}

## Graph stats before
{_format_graph_stats(before_graph)}

## Graph stats after
{_format_graph_stats(after_graph)}

## Citation warnings fixed and remaining
Fixed: {report["warnings"]["fixed"]}
Introduced: {report["warnings"]["introduced"]}

Remaining:
{_format_counts(report["warnings"]["after"])}

## Validation
- Command: {" ".join(validation["command"]) if validation["command"] else "(skipped)"}
- Return code: {validation["returncode"]}
- Skipped: {validation["skipped"]}
- Reason: {validation["reason"] or "(none)"}

```text
{stdout}
```

```text
{stderr}
```

## Residual risks
{risk_text}
"""


def render_pr_commands(report: dict, body_path: str = "maintenance-report.md") -> list[str]:
    """Return the explicit remote commands a human may approve separately."""

    branch = report["branch"]
    if not branch or not report["changed"]:
        return []
    draft_flag = " --draft" if report["pr"]["state"] == "draft" else ""
    title = report["pr"]["title"].replace('"', '\\"')
    return [
        f"git push -u origin {branch}",
        f'gh pr create{draft_flag} --title "{title}" --body-file {body_path}',
    ]
