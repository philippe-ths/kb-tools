import json
import tempfile
import unittest
from pathlib import Path

from kb.install import InstallError, install_host, plan_install


class InstallPlanTest(unittest.TestCase):
    def test_codex_plan_prints_mcp_server_snippet(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_install("codex", tmp, home=tmp, python="python3")
            self.assertIn("[mcp_servers.knowledge-base]", plan.snippet)
            self.assertIn("kb.server", plan.snippet)
            self.assertFalse(plan.written)

    def test_write_requires_explicit_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InstallError):
                install_host("codex", tmp, home=tmp, write=True)

    def test_launchd_plan_escapes_xml_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "a&b"
            root.mkdir()
            plan = plan_install("launchd", root, home=tmp, python="python3")
            self.assertIn("a&amp;b", plan.snippet)

    def test_codex_write_appends_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / ".codex/config.toml"
            target.parent.mkdir()
            target.write_text("# existing\n", encoding="utf-8")
            first = install_host(
                "codex",
                tmp,
                home=home,
                python="python3",
                write=True,
                yes=True,
            )
            second = install_host(
                "codex",
                tmp,
                home=home,
                python="python3",
                write=True,
                yes=True,
            )
            text = target.read_text(encoding="utf-8")
            self.assertTrue(first.changed)
            self.assertFalse(second.changed)
            self.assertEqual(text.count("[mcp_servers.knowledge-base]"), 1)

    def test_claude_write_merges_mcp_servers(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = (
                home
                / "Library/Application Support/Claude/claude_desktop_config.json"
            )
            target.parent.mkdir(parents=True)
            target.write_text(
                json.dumps({"mcpServers": {"other": {"command": "x"}}}),
                encoding="utf-8",
            )
            result = install_host(
                "claude",
                tmp,
                home=home,
                python="python3",
                write=True,
                yes=True,
            )
            data = json.loads(target.read_text(encoding="utf-8"))
            self.assertTrue(result.changed)
            self.assertIn("other", data["mcpServers"])
            self.assertEqual(
                data["mcpServers"]["knowledge-base"]["command"], "python3"
            )


if __name__ == "__main__":
    unittest.main()
