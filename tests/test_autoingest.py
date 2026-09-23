import json
import subprocess
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

from kb import autoingest
from kb.autoingest import (
    STATUS_FILENAME,
    AgentResult,
    AutoIngestError,
    evaluate_merge_gate,
    path_allowed,
    run_auto_ingest,
)
from kb.maintenance import CommandResult


def _verify(
    *,
    broken_links=0,
    missing_pages=0,
    orphan_pages=0,
    uncited_pages=0,
    sources_without_raw_link=0,
    broken_citations=0,
):
    return {
        "graph": {},
        "hygiene": {
            "broken_links": [{}] * broken_links,
            "missing_pages": [{}] * missing_pages,
            "orphan_pages": [{}] * orphan_pages,
        },
        "citations": {
            "uncited_pages": [{}] * uncited_pages,
            "sources_without_raw_link": [{}] * sources_without_raw_link,
            "broken_citations": [{}] * broken_citations,
        },
    }


def _validation(returncode=0, skipped=False, reason=""):
    return CommandResult(
        command=("bash", "x"),
        cwd=".",
        returncode=returncode,
        skipped=skipped,
        reason=reason,
    )


_OK_REVIEW = AgentResult(ok=True, blocking=False)


class PathAllowedTest(unittest.TestCase):
    def test_generated_layer_is_allowed(self):
        self.assertTrue(path_allowed("index.md"))
        self.assertTrue(path_allowed("log.md"))
        self.assertTrue(path_allowed("wiki/concept-x.md"))

    def test_cited_evidence_is_allowed(self):
        # A page and the raw source it cites merge together, so raw/ passes the
        # gate. What may reach the commit is bounded at staging time, not here.
        self.assertTrue(path_allowed("raw/x.md"))

    def test_other_paths_are_blocked(self):
        self.assertFalse(path_allowed("CLAUDE.md"))
        self.assertFalse(path_allowed("tools/kb/api.py"))
        self.assertFalse(path_allowed(".ai-policy/scripts/run-validation.sh"))


class MergeGateTest(unittest.TestCase):
    def test_all_green_merges(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md", "index.md", "log.md"],
            review=_OK_REVIEW,
        )
        self.assertTrue(gate.merge_ok)
        self.assertEqual(gate.reasons, [])

    def test_validation_failure_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(returncode=1),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md"],
            review=_OK_REVIEW,
        )
        self.assertFalse(gate.merge_ok)

    def test_skipped_validation_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(skipped=True, reason="disabled"),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md"],
            review=_OK_REVIEW,
        )
        self.assertFalse(gate.merge_ok)

    def test_warnings_hold(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(orphan_pages=1),
            changed_paths=["wiki/src-x.md"],
            review=_OK_REVIEW,
        )
        self.assertFalse(gate.merge_ok)

    def test_disallowed_path_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md", "tools/kb/api.py"],
            review=_OK_REVIEW,
        )
        self.assertFalse(gate.merge_ok)
        self.assertTrue(any("disallowed" in r for r in gate.reasons))

    def test_no_changes_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(),
            changed_paths=[],
            review=_OK_REVIEW,
        )
        self.assertFalse(gate.merge_ok)

    def test_blocking_review_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md"],
            review=AgentResult(ok=True, blocking=True, reason="unsupported claim"),
        )
        self.assertFalse(gate.merge_ok)

    def test_failed_review_holds(self):
        gate = evaluate_merge_gate(
            validation=_validation(),
            verification_after=_verify(),
            changed_paths=["wiki/src-x.md"],
            review=AgentResult(ok=False, reason="crash"),
        )
        self.assertFalse(gate.merge_ok)


_VAULT = {
    "index.md": (
        "# Index\n\n- [[wiki/overview]] : map\n- [[wiki/concept-a]] : a\n"
        "- [[wiki/src-seed]] : seed\n"
    ),
    "wiki/overview.md": "# Overview\n\nMap of [[concept-a]] and [[src-seed]].\n",
    "wiki/concept-a.md": "# A\n\nDrawn from [[src-seed]]; see [[overview]].\n",
    "wiki/src-seed.md": "# Seed source\n\nEvidence in [[raw/seed]].\n",
    "raw/seed.md": "# Seed\n",
    "raw/new-source.md": "# New source to ingest\n",
    # _stage_and_commit always runs `git add -- wiki index.md log.md`, which
    # fails outright when log.md has never existed. Every earlier test happened
    # to have an ingest agent that wrote it; the no-op and failing agents do
    # not, so the fixture has to carry it the way the real vault does.
    "log.md": "# Log\n\n## [2026-06-01] ingest | seed\n",
    ".ai-policy/scripts/run-validation.sh": "#!/bin/bash\nexit 0\n",
}


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _git_vault():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, content in _VAULT.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    _git(["branch", "-M", "main"], root)
    return tmp


def _make_runner(gh_calls):
    def runner(cmd, cwd=None, capture_output=True, text=True):
        if cmd[:2] == ["git", "fetch"] or cmd[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "gh":
            gh_calls.append(cmd)
            out = "https://example/pr/1\n" if cmd[1:3] == ["pr", "create"] else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=text)

    return runner


def _recording_runner(calls):
    """Like ``_make_runner`` but records every command, including git pushes.

    Lets a test assert on the exact merge/branch-cleanup command sequence, which
    is where the auto-merge worktree bugs lived.
    """

    def runner(cmd, cwd=None, capture_output=True, text=True):
        calls.append(list(cmd))
        if cmd[:2] == ["git", "fetch"] or cmd[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "gh":
            out = "https://example/pr/1\n" if cmd[1:3] == ["pr", "create"] else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=text)

    return runner


def _page_for(source):
    """The wiki src slug a fake ingest writes for a given raw source id."""
    return "wiki/src-" + source.rsplit("/", 1)[-1] + ".md"


def _ingest_agent(*, kind, worktree, root, source=None, sources=None):
    w = Path(worktree)
    # The fake refuses to invent evidence: it only writes a page if the raw
    # source is actually present in the worktree (mirroring a real ingest).
    if not (w / f"{source}.md").is_file():
        return AgentResult(ok=False, reason=f"source missing in worktree: {source}")
    page = w / _page_for(source)
    page.write_text(
        f"# {source}\n\nEvidence in [[{source}]]; see [[overview]].\n",
        encoding="utf-8",
    )
    overview = w / "wiki/overview.md"
    slug = _page_for(source).removeprefix("wiki/").removesuffix(".md")
    overview.write_text(
        overview.read_text(encoding="utf-8") + f"\nAlso [[{slug}]].\n",
        encoding="utf-8",
    )
    log = w / "log.md"
    existing = log.read_text(encoding="utf-8") if log.is_file() else ""
    log.write_text(existing + f"## [2026-06-16] ingest | {source}\n", encoding="utf-8")
    return AgentResult(ok=True, output="ingested")


def _git_vault_behind_remote():
    """A vault whose local `main` is behind `origin/main`.

    Reproduces the condition that produced PRs #31-#33: the human never pulls,
    so the local branch sits on an old commit while the remote has moved on.
    The remote-tracking ref is already correct, which is the point -- the run
    has the current base available and must actually use it.
    """
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name) / "work"
    remote = Path(tmp.name) / "remote.git"
    root.mkdir(parents=True)
    for rel, content in _VAULT.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    _git(["branch", "-M", "main"], root)
    _git(["init", "-q", "--bare", str(remote)], Path(tmp.name))
    _git(["remote", "add", "origin", str(remote)], root)
    _git(["push", "-q", "-u", "origin", "main"], root)
    behind = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True
    ).stdout.strip()
    # A page that exists only on the remote, standing in for a merged PR.
    (root / "wiki/concept-landed.md").write_text(
        "# Landed\n\nMerged upstream; see [[overview]].\n", encoding="utf-8"
    )
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "landed upstream"], root)
    _git(["push", "-q", "origin", "main"], root)
    ahead = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True
    ).stdout.strip()
    _git(["reset", "-q", "--hard", behind], root)
    return tmp, root, behind, ahead


class StaleBaseTest(unittest.TestCase):
    """Issue #34: a run must branch from the remote, not a stale local branch."""

    def test_run_uses_the_remote_head_when_local_is_behind(self):
        tmp, root, behind, ahead = _git_vault_behind_remote()
        with tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                root,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                auto_merge=False,
            )
            self.assertEqual(result["status"], "pr-open")
            self.assertEqual(result["base_commit"], ahead)
            self.assertNotEqual(result["base_commit"], behind)

    def test_branch_is_a_descendant_of_the_remote_head(self):
        # The acceptance criterion: what is opened must merge cleanly into what
        # is already on the remote. A branch off a stale base is not a
        # descendant of the remote head, and arrives conflicting.
        tmp, root, _behind, ahead = _git_vault_behind_remote()
        with tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                root,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                auto_merge=False,
            )
            descends = subprocess.run(
                ["git", "merge-base", "--is-ancestor", ahead, result["branch"]],
                cwd=str(root),
                capture_output=True,
            )
            self.assertEqual(descends.returncode, 0, "branch does not include the remote head")

    def test_pr_is_opened_against_the_branch_name_not_the_tracking_ref(self):
        # `gh pr create --base origin/main` is not a valid base.
        tmp, root, _behind, _ahead = _git_vault_behind_remote()
        with tmp, tempfile.TemporaryDirectory() as wt:
            gh_calls = []
            run_auto_ingest(
                root,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner(gh_calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                auto_merge=False,
            )
            create = next(c for c in gh_calls if c[1:3] == ["pr", "create"])
            self.assertIn("main", create)
            self.assertNotIn("origin/main", create)


class EvidenceLandsWithPagesTest(unittest.TestCase):
    """Issue #35: the gate must judge the tree the merge will produce."""

    def test_cited_raw_source_is_committed_with_the_pages(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            (Path(tmp) / "raw/dropped.md").write_text(
                "# Dropped source\n", encoding="utf-8"
            )
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            self.assertIn("raw/dropped.md", result["changed_paths"])

    def test_raw_outside_the_pending_set_is_not_committed(self):
        # Widening the gate to raw/ must not let an agent commit arbitrary
        # evidence: only this run's pending sources may land.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            def stray_agent(*, kind, worktree, root, source=None, sources=None):
                out = _ingest_agent(
                    kind=kind, worktree=worktree, root=root, source=source, sources=sources
                )
                (Path(worktree) / "raw/stray.md").write_text("# Stray\n", encoding="utf-8")
                return out

            result = run_auto_ingest(
                tmp,
                ingest_agent=stray_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertNotIn("raw/stray.md", result["changed_paths"])

    def test_uncommitted_leftovers_in_the_worktree_hold_the_merge(self):
        # The invariant that keeps verification honest: what was verified is
        # what was committed. Anything left on disk means they diverged.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            def littering_agent(*, kind, worktree, root, source=None, sources=None):
                out = _ingest_agent(
                    kind=kind, worktree=worktree, root=root, source=source, sources=sources
                )
                (Path(worktree) / "stray-note.md").write_text(
                    "# Outside the staged paths\n", encoding="utf-8"
                )
                return out

            result = run_auto_ingest(
                tmp,
                ingest_agent=littering_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "pr-open")
            self.assertFalse(result["gate"]["merge_ok"])


class ReportBaselineTest(unittest.TestCase):
    """Issue #36: both halves of the report must describe the same vault."""

    def test_before_stats_come_from_the_base_not_the_working_tree(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            # Untracked page in the human's working tree; absent from the base.
            (Path(tmp) / "wiki/scratch.md").write_text(
                "# Scratch\n\nSee [[overview]].\n", encoding="utf-8"
            )
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                auto_merge=False,
            )
            before = result["report"]["verification"]["before"]["graph"]
            after = result["report"]["verification"]["after"]["graph"]
            # The scratch page exists only in the human's working tree. Read
            # the base from there and it inflates `before`, so an ingest that
            # only adds pages reports a fall -- the 96 -> 72 in PR #31.
            self.assertGreater(after["pages"], before["pages"])



class AutoIngestFlowTest(unittest.TestCase):
    def test_idle_when_nothing_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.md").write_text("# Index\n", encoding="utf-8")
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                fetch=False,
            )
            self.assertEqual(result["status"], "idle")
            self.assertFalse(result["merged"])

    def test_clean_ingest_auto_merges(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            gh_calls = []
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner(gh_calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            self.assertTrue(result["merged"])
            self.assertTrue(result["gate"]["merge_ok"])
            self.assertEqual(result["pending"], ["raw/new-source"])
            merges = [c for c in gh_calls if c[1:3] == ["pr", "merge"]]
            self.assertEqual(len(merges), 1)

    def test_worktree_is_removed_after_merge(self):
        # Bug: _cleanup_worktree used `git worktree remove`, which does not exist
        # before Git 2.17 (this repo targets 2.14), so the worktree was never
        # deleted. The removal must be version-tolerant.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            worktree = Path(wt) / "kb-maintenance--2026-06-16-ingest"
            self.assertFalse(
                worktree.exists(), "merged run must clean up its worktree"
            )

    def test_merge_avoids_delete_branch_and_cleans_refs(self):
        # Bug: `gh pr merge --delete-branch` from inside the worktree fails
        # ("'main' is already checked out") because gh switches the checkout off
        # the merged branch. Merge without it, then drop the refs explicitly.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            calls = []
            branch = "kb-maintenance/2026-06-16-ingest"
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_recording_runner(calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            merge = next(c for c in calls if c[1:3] == ["pr", "merge"])
            self.assertNotIn("--delete-branch", merge)
            self.assertIn(["git", "push", "origin", "--delete", branch], calls)
            remaining = subprocess.run(
                ["git", "branch", "--format", "%(refname:short)"],
                cwd=str(tmp),
                capture_output=True,
                text=True,
            ).stdout.split()
            self.assertNotIn(branch, remaining)

    def test_held_pr_keeps_its_branch(self):
        # A held-open PR (blocking review) must not have its branch deleted.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            calls = []
            branch = "kb-maintenance/2026-06-16-ingest"
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: AgentResult(
                    ok=True, blocking=True, reason="unsupported claim"
                ),
                runner=_recording_runner(calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "pr-open")
            self.assertNotIn(["git", "push", "origin", "--delete", branch], calls)

    def test_blocking_review_holds_pr_open(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            gh_calls = []
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: AgentResult(
                    ok=True, blocking=True, reason="unsupported claim"
                ),
                runner=_make_runner(gh_calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "pr-open")
            self.assertFalse(result["merged"])
            self.assertFalse(result["gate"]["merge_ok"])
            creates = [c for c in gh_calls if c[1:3] == ["pr", "create"]]
            merges = [c for c in gh_calls if c[1:3] == ["pr", "merge"]]
            self.assertEqual(len(creates), 1)
            self.assertEqual(len(merges), 0)


# --- Issue #40: worktree validation-gate isolation -------------------------
#
# `_git_vault()` above commits `.ai-policy/scripts/run-validation.sh` as
# TRACKED content and never sets `core.hooksPath`, so a git hook never fires
# against it -- this repo's real policy hooks live in a gitignored
# `.ai-policy/`/`.githooks/` wired in via `core.hooksPath`, which the plain
# fixture cannot exercise. The fixtures below build a vault where the real
# hook chain actually fires inside the maintenance worktree, the way it does
# against the live repo, so the regression is reachable at all.

_REAL_PRE_COMMIT_HOOK = """#!/usr/bin/env bash
set -eu

ROOT_DIR="$(git rev-parse --show-toplevel)"

"$ROOT_DIR/.ai-policy/scripts/check-protected-branch.sh"

# shellcheck disable=SC1091
. "$ROOT_DIR/.ai-policy/policy.env"

if [ "$REQUIRE_VALIDATION_BEFORE_COMMIT" = "true" ]; then
  "$ROOT_DIR/.ai-policy/scripts/check-validation.sh"
fi

exit 0
"""

_REAL_CHECK_PROTECTED_BRANCH_SH = """#!/usr/bin/env bash
set -eu

ROOT_DIR="$(git rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$ROOT_DIR/.ai-policy/policy.env"

CURRENT_BRANCH="$("$ROOT_DIR/.ai-policy/scripts/current-branch.sh")"

for branch in $PROTECTED_BRANCHES; do
  if [ "$CURRENT_BRANCH" = "$branch" ]; then
    echo "Blocked: branch '$CURRENT_BRANCH' is protected."
    echo "Create or switch to an issue-scoped branch before continuing."
    exit 2
  fi
done

exit 0
"""

_REAL_CURRENT_BRANCH_SH = """#!/usr/bin/env bash
set -eu

git symbolic-ref --quiet --short HEAD 2>/dev/null || true
"""

# Verbatim copy of .ai-policy/scripts/check-validation.sh (this repo's real,
# vendored policy hook), so the regression fixture exercises the exact
# fingerprint-mismatch logic that blocks a real weekly run.
_REAL_CHECK_VALIDATION_SH = """#!/usr/bin/env bash
set -eu

ROOT_DIR="$(git rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$ROOT_DIR/.ai-policy/policy.env"

STATE_FILE="$ROOT_DIR/$VALIDATION_STATE_FILE"

if [ ! -f "$STATE_FILE" ]; then
  echo "Blocked: no validation status found."
  echo "Run ./.ai-policy/scripts/run-validation.sh first."
  exit 2
fi

STATE_LINE="$(head -n 1 "$STATE_FILE")"
STATUS="${STATE_LINE%% *}"
RECORDED_FINGERPRINT=""
case "$STATE_LINE" in
  *' '*) RECORDED_FINGERPRINT="${STATE_LINE#* }" ;;
esac

if [ "$STATUS" = "passed" ]; then
  if [ -z "$RECORDED_FINGERPRINT" ]; then
    echo "Blocked: validation status records no working-tree fingerprint."
    echo "Run ./.ai-policy/scripts/run-validation.sh to record a current result."
    exit 2
  fi

  CURRENT_FINGERPRINT="$("$ROOT_DIR/.ai-policy/scripts/tree-fingerprint.sh")"

  if [ "$RECORDED_FINGERPRINT" = "$CURRENT_FINGERPRINT" ]; then
    exit 0
  fi

  echo "Blocked: the working tree has changed since validation passed."
  echo "The recorded pass was computed against different content, so it does not"
  echo "cover what is being committed or pushed."
  echo "  validated tree: $RECORDED_FINGERPRINT"
  echo "  current tree:   $CURRENT_FINGERPRINT"
  echo "Run ./.ai-policy/scripts/run-validation.sh and only continue once it passes."
  exit 2
fi

if [ "$STATUS" = "running" ]; then
  echo "Blocked: validation is still running."
  echo "Wait for it to finish or rerun ./.ai-policy/scripts/run-validation.sh."
  exit 2
fi

echo "Blocked: validation status is '$STATUS', not 'passed'."
echo "Run ./.ai-policy/scripts/run-validation.sh and only continue once it passes."
exit 2
"""

# Verbatim copy of .ai-policy/scripts/tree-fingerprint.sh.
_REAL_TREE_FINGERPRINT_SH = """#!/usr/bin/env bash
set -eu

ROOT_DIR="$(git rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$ROOT_DIR/.ai-policy/policy.env"
cd "$ROOT_DIR"

STATE_REL="$VALIDATION_STATE_FILE"

ALL_PATHS="$(
  git -c core.quotePath=false ls-files --cached --others --exclude-standard |
    LC_ALL=C sort -u |
    while IFS= read -r p; do
      if [ -n "$p" ] && [ "$p" != "$STATE_REL" ]; then
        printf '%s\\n' "$p"
      fi
    done
)"

QUOTED_PATHS="$(
  printf '%s\\n' "$ALL_PATHS" |
    while IFS= read -r p; do
      case "$p" in
        '"'*) printf '%s\\n' "$p" ;;
      esac
    done
)"

if [ -n "$QUOTED_PATHS" ]; then
  echo "tree-fingerprint: cannot fingerprint a tree containing these paths:" >&2
  printf '%s\\n' "$QUOTED_PATHS" >&2
  exit 1
fi

EXISTING_PATHS="$(
  printf '%s\\n' "$ALL_PATHS" |
    while IFS= read -r p; do
      if [ -n "$p" ] && [ -f "$p" ]; then
        printf '%s\\n' "$p"
      fi
    done
)"

{
  printf '%s\\n' "$ALL_PATHS"
  git -c core.quotePath=false ls-files --deleted | LC_ALL=C sort -u
  if [ -n "$EXISTING_PATHS" ]; then
    printf '%s\\n' "$EXISTING_PATHS" | git hash-object --stdin-paths
  fi
} | git hash-object --stdin
"""

# Verbatim copy of .ai-policy/scripts/run-validation.sh.
_REAL_RUN_VALIDATION_SH = """#!/usr/bin/env bash
set -eu

ROOT_DIR="$(git rev-parse --show-toplevel)"
# shellcheck disable=SC1091
. "$ROOT_DIR/.ai-policy/policy.env"

STATE_FILE="$ROOT_DIR/$VALIDATION_STATE_FILE"

mkdir -p "$(dirname "$STATE_FILE")"
printf "running" > "$STATE_FILE"

cleanup() {
  if [ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE")" = "running" ]; then
    printf "failed" > "$STATE_FILE"
  fi
}

trap cleanup EXIT INT TERM

if sh -c "$VALIDATION_COMMAND"; then
  printf 'passed %s\\n' "$("$ROOT_DIR/.ai-policy/scripts/tree-fingerprint.sh")" > "$STATE_FILE"
  trap - EXIT INT TERM
  echo "Validation passed."
  exit 0
else
  printf "failed" > "$STATE_FILE"
  trap - EXIT INT TERM
  echo "Validation failed."
  exit 1
fi
"""


def _policy_env(validation_command: str) -> str:
    return (
        'PROTECTED_BRANCHES="main master"\n'
        'REQUIRE_VALIDATION_BEFORE_COMMIT="true"\n'
        'REQUIRE_VALIDATION_BEFORE_PUSH="true"\n'
        'VALIDATION_STATE_FILE=".ai-policy/state/validation.status"\n'
        f'VALIDATION_COMMAND="{validation_command}"\n'
    )


def _git_vault_with_real_hooks(*, seed_stale_state: bool, validation_command: str = "true"):
    """A vault where the real policy pre-commit hook actually fires.

    Seeds a REAL gitignored `.ai-policy/` (the vendored scripts, `policy.env`,
    and -- when `seed_stale_state` -- a stale `state/validation.status`
    recording a pass for a fingerprint that matches nothing) plus a real
    `.githooks/pre-commit`, and sets `core.hooksPath=.githooks` on the repo so
    a commit inside a linked worktree (which shares this repo's git config)
    actually runs it -- reproducing what happens against the live vault.
    """

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    vault_files = dict(_VAULT)
    del vault_files[".ai-policy/scripts/run-validation.sh"]
    vault_files[".gitignore"] = ".ai-policy/\n.githooks/\n"
    for rel, content in vault_files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    _git(["branch", "-M", "main"], root)
    _git(["config", "core.hooksPath", ".githooks"], root)

    scripts = root / ".ai-policy/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    (root / ".ai-policy/policy.env").write_text(
        _policy_env(validation_command), encoding="utf-8"
    )
    for name, content in (
        ("check-protected-branch.sh", _REAL_CHECK_PROTECTED_BRANCH_SH),
        ("current-branch.sh", _REAL_CURRENT_BRANCH_SH),
        ("check-validation.sh", _REAL_CHECK_VALIDATION_SH),
        ("tree-fingerprint.sh", _REAL_TREE_FINGERPRINT_SH),
        ("run-validation.sh", _REAL_RUN_VALIDATION_SH),
    ):
        script_path = scripts / name
        script_path.write_text(content, encoding="utf-8")
        script_path.chmod(0o755)

    githooks = root / ".githooks"
    githooks.mkdir(parents=True, exist_ok=True)
    hook = githooks / "pre-commit"
    hook.write_text(_REAL_PRE_COMMIT_HOOK, encoding="utf-8")
    hook.chmod(0o755)

    if seed_stale_state:
        state_dir = root / ".ai-policy/state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "validation.status").write_text(
            "passed deadbeefbogusfingerprint\n", encoding="utf-8"
        )

    return tmp, root


class HookIsolationRegressionTest(unittest.TestCase):
    """Issue #40: the weekly auto-ingest run aborted at its commit step.

    A leaked, stale validation pass (defect A) plus committing before
    revalidating (defect B) made a real pre-commit hook block every run: the
    hook re-checked the leaked "passed <fingerprint>" against the current
    tree, found a mismatch, and exited 2 -- and `run_validation` never got a
    chance to refresh the state, because it ran after the commit attempt.
    """

    def test_leaked_validation_state_no_longer_blocks_the_commit(self):
        tmp, root = _git_vault_with_real_hooks(
            seed_stale_state=True, validation_command="true"
        )
        with tmp, tempfile.TemporaryDirectory() as wt:
            try:
                result = run_auto_ingest(
                    root,
                    ingest_agent=_ingest_agent,
                    review_agent=lambda **k: _OK_REVIEW,
                    runner=_make_runner([]),
                    run_date=date(2026, 6, 16),
                    worktree_root=wt,
                    base_ref="main",
                )
            except AutoIngestError as exc:
                self.fail(
                    "run_auto_ingest died instead of reaching a committed "
                    f"state (issue #40 regression): {exc}"
                )
            # A fresh worktree must not inherit the leaked stale pass, and
            # validation must have run (and refreshed the state) before the
            # commit was attempted, so the real hook let the commit through.
            self.assertIn(result["status"], ("merged", "pr-open"))
            self.assertNotEqual(result["status"], "validation-failed")


class ValidationOrderTest(unittest.TestCase):
    """Issue #40, fix B: validation must run before the commit is attempted.

    Observable only via the injected runner seam (there is no other hook to
    assert on): record every command the run issues and check that the
    validation script's command precedes the git commit command.
    """

    def test_validation_runs_before_the_commit_is_attempted(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            calls = []
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_recording_runner(calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            validation_idx = next(
                i
                for i, c in enumerate(calls)
                if c[:2] == ["bash", ".ai-policy/scripts/run-validation.sh"]
            )
            commit_idx = next(
                i for i, c in enumerate(calls) if c[:2] == ["git", "commit"]
            )
            self.assertLess(
                validation_idx,
                commit_idx,
                "validation must run before the commit is attempted",
            )


def _git_vault_failing_validation():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    vault_files = dict(_VAULT)
    vault_files[".ai-policy/scripts/run-validation.sh"] = "#!/bin/bash\nexit 1\n"
    for rel, content in vault_files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(["init", "-q"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "seed"], root)
    _git(["branch", "-M", "main"], root)
    return tmp


class ValidationFailureHoldsTest(unittest.TestCase):
    """Issue #40, fix B follow-on: a real validation failure at the new,
    earlier point must hold -- no commit, no push, no PR -- and leave the
    worktree in place for diagnosis rather than silently continuing."""

    def test_validation_failure_holds_without_commit_push_or_pr(self):
        with _git_vault_failing_validation() as tmp, tempfile.TemporaryDirectory() as wt:
            calls = []
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_recording_runner(calls),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "validation-failed")
            self.assertFalse(result["merged"])
            self.assertEqual(result["validation"]["returncode"], 1)
            self.assertFalse(
                any(c[:2] == ["git", "commit"] for c in calls),
                "a failed validation must not be followed by a commit",
            )
            self.assertFalse(any(c[:2] == ["git", "push"] for c in calls))
            self.assertFalse(any(c[0] == "gh" for c in calls))
            self.assertTrue(
                Path(result["worktree"]).exists(),
                "the worktree must be left in place for diagnosis",
            )


def _failing_ingest_agent(*, kind, worktree, root, source=None, sources=None):
    """Every call fails, as with a network/auth/timeout outage.

    Mirrors what `agents.py` actually returns on such an outage:
    `AgentResult(ok=False)`, never a raised exception. This is the case the
    orchestrator must not confuse with a genuinely quiet week.
    """

    return AgentResult(ok=False, reason=f"network timeout ingesting {source}")

def _noop_ingest_agent(*, kind, worktree, root, source=None, sources=None):
    """Agent call succeeds but writes nothing -- a benign no-op ingest."""

    return AgentResult(ok=True, output="nothing new to add")

def _push_failing_runner():
    """Like ``_make_runner`` but fails ``git push``, as a real push/network
    failure would. Everything else (fetch, gh, and the real git plumbing
    inside the worktree) behaves normally.
    """

    def runner(cmd, cwd=None, capture_output=True, text=True):
        if cmd[:2] == ["git", "fetch"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(cmd, 1, "", "push failed: simulated")
        if cmd[0] == "gh":
            out = "https://example/pr/1\n" if cmd[1:3] == ["pr", "create"] else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=text)

    return runner

class RunOutcomeOkFieldTest(unittest.TestCase):
    """Issue #41: every terminal status must self-classify via `ok`."""

    def test_idle_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.md").write_text("# Index\n", encoding="utf-8")
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                fetch=False,
            )
            self.assertEqual(result["status"], "idle")
            self.assertTrue(result["ok"])
            self.assertEqual(result["failures"], [])

    def test_no_diff_with_healthy_agents_is_no_changes_and_ok(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_noop_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "no-changes")
            self.assertTrue(result["ok"])
            self.assertEqual(result["failures"], [])

    def test_every_agent_call_failing_is_ingest_failed_and_not_ok(self):
        # The regression test for the worst gap in the issue: a total agent-
        # call failure (network/auth/timeout -- AgentResult(ok=False), never
        # raised) must not read the same as a genuinely quiet week.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_failing_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "ingest-failed")
            self.assertFalse(result["ok"])
            self.assertTrue(result["failures"])
            self.assertIn("raw/new-source", result["failures"][0])

    def test_held_pr_is_ok_not_a_failure(self):
        # The most likely thing to get wrong: the gate holding for human
        # review is the system working as designed, not a failed run.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: AgentResult(
                    ok=True, blocking=True, reason="unsupported claim"
                ),
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "pr-open")
            self.assertTrue(result["ok"])
            self.assertFalse(result["gate"]["merge_ok"])

    def test_clean_merge_is_ok(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            self.assertEqual(result["status"], "merged")
            self.assertTrue(result["ok"])
            self.assertEqual(result["failures"], [])

class StatusFileTest(unittest.TestCase):
    """Part 3: a durable run-status file that survives a launchd reboot reset."""

    def test_written_on_success_with_documented_fields(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            status = json.loads(
                (Path(tmp) / STATUS_FILENAME).read_text(encoding="utf-8")
            )
            self.assertIn("timestamp", status)
            self.assertTrue(status["ok"])
            self.assertEqual(status["status"], "merged")
            self.assertEqual(status["pending_count"], 1)
            self.assertEqual(status["branch"], result["branch"])
            self.assertEqual(status["pr_url"], result["pr_url"])
            self.assertEqual(status["failures"], [])

    def test_written_on_a_failed_run(self):
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            run_auto_ingest(
                tmp,
                ingest_agent=_failing_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
            )
            status = json.loads(
                (Path(tmp) / STATUS_FILENAME).read_text(encoding="utf-8")
            )
            self.assertFalse(status["ok"])
            self.assertEqual(status["status"], "ingest-failed")
            self.assertEqual(status["pending_count"], 1)
            self.assertTrue(status["failures"])

    def test_written_when_the_run_raises(self):
        # Push/gh/git-infra failures raise AutoIngestError rather than
        # returning a report. The status file must still land -- that is the
        # whole point of using try/finally around the raise.
        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            with self.assertRaises(AutoIngestError):
                run_auto_ingest(
                    tmp,
                    ingest_agent=_ingest_agent,
                    review_agent=lambda **k: _OK_REVIEW,
                    runner=_push_failing_runner(),
                    run_date=date(2026, 6, 16),
                    worktree_root=wt,
                    base_ref="main",
                )
            status = json.loads(
                (Path(tmp) / STATUS_FILENAME).read_text(encoding="utf-8")
            )
            self.assertFalse(status["ok"])
            self.assertEqual(status["status"], "error")
            self.assertTrue(status["failures"])
            # The branch was created before the push failed, so it is known.
            self.assertIsNotNone(status["branch"])

class NotifierTest(unittest.TestCase):
    """Part 4: a best-effort local notification, only on a failed run."""

    def test_fires_on_failure_not_on_success(self):
        calls = []

        def fake_notify(title, message):
            calls.append((title, message))

        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            run_auto_ingest(
                tmp,
                ingest_agent=_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                notify=fake_notify,
            )
        self.assertEqual(calls, [])

        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            run_auto_ingest(
                tmp,
                ingest_agent=_failing_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                notify=fake_notify,
            )
        self.assertEqual(len(calls), 1)
        title, message = calls[0]
        self.assertIn("kb auto-ingest", title)
        self.assertTrue(message)

    def test_the_default_is_silent_so_no_test_can_notify_for_real(self):
        """A failing run with no injected notifier must not shell out.

        Regression: `notify` used to fall back to the real notifier, so any
        test driving a failing run without passing a fake put an actual
        macOS banner on the screen. The live run gets its notifier from
        `__main__`, explicitly.
        """

        with mock.patch.object(autoingest, "default_notifier") as real:
            with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
                result = run_auto_ingest(
                    tmp,
                    ingest_agent=_failing_ingest_agent,
                    review_agent=lambda **k: _OK_REVIEW,
                    runner=_make_runner([]),
                    run_date=date(2026, 6, 16),
                    worktree_root=wt,
                    base_ref="main",
                )
        self.assertFalse(result["ok"])
        real.assert_not_called()

    def test_a_raising_notifier_does_not_change_the_outcome(self):
        def bad_notify(title, message):
            raise RuntimeError("notifier is broken")

        with _git_vault() as tmp, tempfile.TemporaryDirectory() as wt:
            result = run_auto_ingest(
                tmp,
                ingest_agent=_failing_ingest_agent,
                review_agent=lambda **k: _OK_REVIEW,
                runner=_make_runner([]),
                run_date=date(2026, 6, 16),
                worktree_root=wt,
                base_ref="main",
                notify=bad_notify,
            )
        self.assertEqual(result["status"], "ingest-failed")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
