"""Tests for the `python -m kb` CLI entrypoint (`main()`).

Nothing else in this suite imports `kb.__main__`; this establishes that
surface. Kept small and direct, per issue #41: `run_auto_ingest` shells out to
git/gh/claude, so it is patched out here rather than run for real -- these
tests only exercise `main()`'s exit-code mapping for the `auto-ingest`
subcommand, which was previously untested.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from kb import __main__ as cli
from kb.autoingest import AutoIngestError


def _report(*, status, ok, **extra):
    return {
        "status": status,
        "ok": ok,
        "merged": status == "merged",
        "pending": [],
        "failures": [],
        **extra,
    }


class AutoIngestExitCodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        (Path(self.tmp.name) / "index.md").write_text("# Index\n", encoding="utf-8")

    def _run(self, argv=None):
        # main() writes the report to stdout and the run marker to stderr.
        # Captured here so the suite's own output stays clean: the auto-ingest
        # run embeds validation stdout in its report, so leaked test output
        # would end up inside every run report.
        argv = argv or ["--root", self.tmp.name, "--json", "auto-ingest"]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return cli.main(argv)

    def test_ok_run_exits_zero(self):
        with patch.object(
            cli, "run_auto_ingest", return_value=_report(status="idle", ok=True)
        ):
            self.assertEqual(self._run(), 0)

    def test_held_pr_run_exits_zero(self):
        # A held PR is `ok: True` -- the gate holding for human review is the
        # system working, not a failed run.
        with patch.object(
            cli, "run_auto_ingest", return_value=_report(status="pr-open", ok=True)
        ):
            self.assertEqual(self._run(), 0)

    def test_ingest_failed_run_exits_with_the_dedicated_code(self):
        report = _report(status="ingest-failed", ok=False, failures=["raw/x: boom"])
        with patch.object(cli, "run_auto_ingest", return_value=report):
            code = self._run()
        self.assertEqual(code, cli.AUTO_INGEST_FAILURE_EXIT)
        self.assertNotEqual(code, 0)
        self.assertNotEqual(code, 2)

    def test_raised_error_exits_two(self):
        with patch.object(
            cli, "run_auto_ingest", side_effect=AutoIngestError("push failed")
        ):
            self.assertEqual(self._run(), 2)

    def test_non_auto_ingest_command_is_unaffected_by_the_new_code(self):
        # The new exit code is scoped to `auto-ingest`; every other subcommand
        # keeps its existing 0/2 mapping.
        code = self._run(["--root", self.tmp.name, "--json", "graph"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
