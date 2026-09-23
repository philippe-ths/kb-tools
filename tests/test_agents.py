"""Tests for the live claude-backed agent runner (kb.agents).

These cover the retry/timeout hardening around the headless ``claude`` calls:
the read-only review retries transient failures, the write-side ingest does
not, and a timeout is surfaced as a normal non-zero result. The real
subprocess is never spawned; the single-shot invoker is patched.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kb import agents


def _cp(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        ["claude"], returncode, stdout=stdout, stderr=stderr
    )


class _FakeInvoker:
    """Returns a queued sequence of CompletedProcess results, one per call."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def __call__(self, cmd, worktree):
        self.calls += 1
        return self._results.pop(0)


class McpConfigTest(unittest.TestCase):
    def test_server_starts_from_a_content_only_worktree(self):
        # The ingest worktree holds vault content and no tool code, so the
        # configured server must import kb from the install, not the cwd.
        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp)
            (worktree / "wiki").mkdir()
            entry = json.loads(agents._mcp_config(worktree, worktree))[
                "mcpServers"
            ]["knowledge-base"]
            completed = subprocess.run(
                [entry["command"], *entry["args"], "--help"],
                cwd=tmp,
                env={"PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)


class RunClaudeRetryTest(unittest.TestCase):
    def test_retries_until_success(self):
        fake = _FakeInvoker([_cp(1, stderr="overloaded"), _cp(0, stdout="ok")])
        sleeps = []
        with mock.patch.object(agents, "_invoke_claude_once", fake):
            completed = agents._run_claude(
                "p", Path("/wt"), Path("/root"), attempts=3, sleeper=sleeps.append
            )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(fake.calls, 2)
        # One backoff slept between the two attempts.
        self.assertEqual(sleeps, [agents.RETRY_BACKOFF_SECONDS])

    def test_exhausts_attempts_and_returns_last_failure(self):
        fake = _FakeInvoker([_cp(1), _cp(1), _cp(1)])
        with mock.patch.object(agents, "_invoke_claude_once", fake):
            completed = agents._run_claude(
                "p", Path("/wt"), Path("/root"), attempts=3, sleeper=lambda s: None
            )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(fake.calls, 3)

    def test_default_is_single_attempt(self):
        fake = _FakeInvoker([_cp(1), _cp(0)])
        with mock.patch.object(agents, "_invoke_claude_once", fake):
            completed = agents._run_claude(
                "p", Path("/wt"), Path("/root"), sleeper=lambda s: None
            )
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(fake.calls, 1)

    def test_backoff_grows_per_attempt(self):
        fake = _FakeInvoker([_cp(1), _cp(1), _cp(0)])
        sleeps = []
        with mock.patch.object(agents, "_invoke_claude_once", fake):
            agents._run_claude(
                "p", Path("/wt"), Path("/root"), attempts=3, sleeper=sleeps.append
            )
        self.assertEqual(
            sleeps,
            [agents.RETRY_BACKOFF_SECONDS, agents.RETRY_BACKOFF_SECONDS * 2],
        )


class InvokeTimeoutTest(unittest.TestCase):
    def test_timeout_becomes_nonzero_result(self):
        def boom(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1, stderr="partial")

        with mock.patch.object(agents.subprocess, "run", boom):
            completed = agents._invoke_claude_once(["claude"], Path("/wt"))
        self.assertEqual(completed.returncode, agents.TIMEOUT_RETURNCODE)
        self.assertIn("timeout", completed.stderr)


class ReviewRunnerTest(unittest.TestCase):
    def test_review_uses_review_attempts(self):
        captured = {}

        def fake_run(prompt, worktree, root, *, attempts=1, sleeper=None):
            captured["attempts"] = attempts
            envelope = json.dumps({"result": '{"blocking": false, "reason": "ok"}'})
            return _cp(0, stdout=envelope)

        with mock.patch.object(agents, "_run_claude", fake_run):
            result = agents.claude_agent_runner(
                kind="review", sources=["s"], worktree=Path("/wt"), root=Path("/root")
            )
        self.assertEqual(captured["attempts"], agents.REVIEW_ATTEMPTS)
        self.assertTrue(result.ok)
        self.assertFalse(result.blocking)
        self.assertEqual(result.reason, "ok")

    def test_review_failure_is_blocking_with_exit_code(self):
        with mock.patch.object(
            agents, "_run_claude", return_value=_cp(124, stderr="timed out")
        ):
            result = agents.claude_agent_runner(
                kind="review", sources=["s"], worktree=Path("/wt"), root=Path("/root")
            )
        self.assertFalse(result.ok)
        self.assertTrue(result.blocking)
        self.assertIn("124", result.reason)

    def test_review_unparseable_verdict_holds_merge(self):
        with mock.patch.object(
            agents, "_run_claude", return_value=_cp(0, stdout="no json here")
        ):
            result = agents.claude_agent_runner(
                kind="review", sources=["s"], worktree=Path("/wt"), root=Path("/root")
            )
        # Zero exit but no verdict: fail closed.
        self.assertTrue(result.ok)
        self.assertTrue(result.blocking)


class IngestRunnerTest(unittest.TestCase):
    def test_ingest_is_single_attempt(self):
        captured = {}

        def fake_run(prompt, worktree, root, *, attempts=1, sleeper=None):
            captured["attempts"] = attempts
            return _cp(0, stdout='{"result": "done"}')

        with mock.patch.object(agents, "_run_claude", fake_run):
            result = agents.claude_agent_runner(
                kind="ingest", source="s", worktree=Path("/wt"), root=Path("/root")
            )
        self.assertEqual(captured["attempts"], 1)
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "done")

    def test_ingest_failure_is_not_blocking_but_reports_exit(self):
        with mock.patch.object(
            agents, "_run_claude", return_value=_cp(2, stderr="boom")
        ):
            result = agents.claude_agent_runner(
                kind="ingest", source="s", worktree=Path("/wt"), root=Path("/root")
            )
        self.assertFalse(result.ok)
        self.assertFalse(result.blocking)
        self.assertIn("2", result.reason)


if __name__ == "__main__":
    unittest.main()
