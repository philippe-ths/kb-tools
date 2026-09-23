import subprocess
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from kb.maintenance import (
    bootstrap_validation_support,
    maintenance_branch_name,
    prepare_worktree,
    render_pr_body,
    render_pr_commands,
    run_maintenance,
)

from .fixture import make_vault


def _completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class BranchNamingTest(unittest.TestCase):
    def test_default_branch_name_uses_adr_pattern(self):
        branch = maintenance_branch_name(date(2026, 6, 15))
        self.assertEqual(branch, "kb-maintenance/2026-06-15-wiki-health")

    def test_branch_name_adds_numeric_suffix_for_collision(self):
        branch = maintenance_branch_name(
            date(2026, 6, 15),
            existing=(
                "kb-maintenance/2026-06-15-wiki-health",
                "kb-maintenance/2026-06-15-wiki-health-2",
            ),
        )
        self.assertEqual(branch, "kb-maintenance/2026-06-15-wiki-health-3")


class WorktreePlanTest(unittest.TestCase):
    def test_prepare_worktree_dry_run_uses_collision_safe_branch(self):
        def runner(args, **kwargs):
            if args[:2] == ["git", "branch"]:
                return _completed(args, stdout="kb-maintenance/2026-06-15-wiki-health\n")
            self.fail(f"unexpected command: {args}")

        plan = prepare_worktree(
            ".",
            run_date=date(2026, 6, 15),
            worktree_root="/tmp/kb-worktrees",
            execute=False,
            runner=runner,
        )
        self.assertEqual(plan["branch"], "kb-maintenance/2026-06-15-wiki-health-2")
        self.assertFalse(plan["executed"])
        self.assertIn("git", plan["command"][0])
        self.assertIsNone(plan["result"])

    def test_execute_prepares_ref_namespace_for_slash_branch(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git_dir = repo / ".git"
            (git_dir / "refs/heads").mkdir(parents=True)
            (repo / ".ai-policy/scripts").mkdir(parents=True)
            (repo / ".ai-policy/scripts/run-validation.sh").write_text(
                "#!/usr/bin/env bash\n",
                encoding="utf-8",
            )
            (repo / ".codex").mkdir()
            (repo / ".codex/hooks.json").write_text("{}", encoding="utf-8")
            calls = []

            def runner(args, **kwargs):
                calls.append(args)
                if args[:2] == ["git", "branch"]:
                    return _completed(args)
                if args == ["git", "rev-parse", "--git-dir"]:
                    return _completed(args, stdout=".git\n")
                if args[:3] == ["git", "worktree", "add"]:
                    self.assertTrue((git_dir / "refs/heads/kb-maintenance").is_dir())
                    Path(args[5]).mkdir(parents=True)
                    return _completed(args, stderr="Preparing worktree\n")
                self.fail(f"unexpected command: {args}")

            plan = prepare_worktree(
                repo,
                run_date=date(2026, 6, 15),
                worktree_root=repo / "worktrees",
                execute=True,
                runner=runner,
            )
            self.assertTrue(plan["executed"])
            self.assertEqual(plan["result"]["returncode"], 0)
            self.assertIn(".ai-policy", plan["bootstrapped"])
            self.assertTrue(
                (
                    Path(plan["worktree"])
                    / ".ai-policy/scripts/run-validation.sh"
                ).is_file()
            )
            self.assertIn(["git", "rev-parse", "--git-dir"], calls)

    def test_bootstrap_validation_support_copies_only_present_paths(self):
        with TemporaryDirectory() as source_tmp, TemporaryDirectory() as target_tmp:
            source = Path(source_tmp)
            target = Path(target_tmp)
            (source / ".ai-policy/scripts").mkdir(parents=True)
            (source / ".ai-policy/scripts/run-validation.sh").write_text(
                "echo ok\n",
                encoding="utf-8",
            )
            copied = bootstrap_validation_support(source, target)
            self.assertEqual(copied, [".ai-policy"])
            self.assertEqual(
                (target / ".ai-policy/scripts/run-validation.sh").read_text(
                    encoding="utf-8"
                ),
                "echo ok\n",
            )

    def test_bootstrap_validation_support_excludes_leaked_state(self):
        # Issue #40, defect A: a fresh worktree must never inherit another
        # checkout's recorded validation result. `.ai-policy/state/` holds a
        # "passed <fingerprint>" line computed against a different tree, so
        # copying it in makes the new worktree trust a foreign pass instead of
        # starting with no recorded state at all.
        with TemporaryDirectory() as source_tmp, TemporaryDirectory() as target_tmp:
            source = Path(source_tmp)
            target = Path(target_tmp)
            (source / ".ai-policy/scripts").mkdir(parents=True)
            (source / ".ai-policy/scripts/run-validation.sh").write_text(
                "echo ok\n", encoding="utf-8"
            )
            (source / ".ai-policy/state").mkdir(parents=True)
            (source / ".ai-policy/state/validation.status").write_text(
                "passed deadbeefbogusfingerprint\n", encoding="utf-8"
            )
            (source / ".githooks").mkdir(parents=True)
            (source / ".githooks/pre-commit").write_text(
                "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
            )

            copied = bootstrap_validation_support(source, target)

            self.assertIn(".ai-policy", copied)
            self.assertIn(".githooks", copied)
            self.assertFalse(
                (target / ".ai-policy/state").exists(),
                "bootstrap must not copy another checkout's validation state",
            )
            # Everything else about .ai-policy, plus .githooks, still copies.
            self.assertEqual(
                (target / ".ai-policy/scripts/run-validation.sh").read_text(
                    encoding="utf-8"
                ),
                "echo ok\n",
            )
            self.assertTrue((target / ".githooks/pre-commit").is_file())

    def test_bootstrap_validation_support_is_safe_with_no_leaked_state(self):
        # A source root with no recorded state at all (the common case for a
        # fresh checkout) must bootstrap cleanly with nothing to exclude.
        with TemporaryDirectory() as source_tmp, TemporaryDirectory() as target_tmp:
            source = Path(source_tmp)
            target = Path(target_tmp)
            (source / ".ai-policy/scripts").mkdir(parents=True)
            (source / ".ai-policy/scripts/run-validation.sh").write_text(
                "echo ok\n", encoding="utf-8"
            )
            copied = bootstrap_validation_support(source, target)
            self.assertEqual(copied, [".ai-policy"])
            self.assertFalse((target / ".ai-policy/state").exists())


class MaintenanceRunTest(unittest.TestCase):
    def setUp(self):
        self._tmp = make_vault()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_audit_mode_makes_no_change_and_needs_no_pr(self):
        report = run_maintenance(self.root, validate=False)
        self.assertEqual(report["mode"], "audit")
        self.assertFalse(report["changed"])
        self.assertEqual(report["pr"]["state"], "none")

    def test_apply_mode_reports_fixed_citation_warning(self):
        changes = [
            {
                "op": "write_page",
                "page_id": "wiki/src-gamma",
                "text": "# Gamma source\n\nGamma cites [[raw/evidence-a]].\n",
            }
        ]
        report = run_maintenance(
            self.root,
            changes=changes,
            apply_changes=True,
            validate=False,
            branch="kb-maintenance/2026-06-15-wiki-health",
        )
        self.assertEqual(report["mode"], "apply")
        self.assertTrue(report["changed"])
        self.assertEqual(report["warnings"]["delta"]["sources_without_raw_link"], -1)
        self.assertEqual(report["warnings"]["fixed"], 1)
        self.assertEqual(report["pr"]["state"], "draft")
        self.assertIn(
            "raw/evidence-a",
            (self.root / "wiki/src-gamma.md").read_text(encoding="utf-8"),
        )

    def test_propose_mode_does_not_emit_remote_commands(self):
        changes = [
            {
                "op": "write_page",
                "page_id": "wiki/src-gamma",
                "text": "# Gamma source\n\nGamma cites [[raw/evidence-a]].\n",
            }
        ]
        report = run_maintenance(
            self.root,
            changes=changes,
            apply_changes=False,
            validate=False,
            branch="kb-maintenance/2026-06-15-wiki-health",
        )
        self.assertEqual(report["mode"], "propose")
        self.assertFalse(report["changed"])
        self.assertEqual(render_pr_commands(report), [])
        self.assertNotIn(
            "raw/evidence-a",
            (self.root / "wiki/src-gamma.md").read_text(encoding="utf-8"),
        )

    def test_pr_body_and_commands_surface_review_information(self):
        changes = [
            {
                "op": "write_page",
                "page_id": "wiki/src-gamma",
                "text": "# Gamma source\n\nGamma cites [[raw/evidence-a]].\n",
            }
        ]
        report = run_maintenance(
            self.root,
            changes=changes,
            apply_changes=True,
            validate=False,
            branch="kb-maintenance/2026-06-15-wiki-health",
        )
        body = render_pr_body(report)
        commands = render_pr_commands(report)
        self.assertIn("## Graph stats before", body)
        self.assertIn("## Citation warnings fixed and remaining", body)
        self.assertIn("## Validation", body)
        self.assertIn("git push -u origin kb-maintenance/2026-06-15-wiki-health", commands)
        self.assertIn("--draft", commands[1])


if __name__ == "__main__":
    unittest.main()
