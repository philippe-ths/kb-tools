"""Host configuration snippets and guarded installer helpers for Milestone 3."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape


class InstallError(Exception):
    """Raised when an install operation is unsafe or unsupported."""


@dataclass(frozen=True)
class InstallPlan:
    host: str
    target: str
    snippet: str
    written: bool = False
    changed: bool = False

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "target": self.target,
            "snippet": self.snippet,
            "written": self.written,
            "changed": self.changed,
        }


def server_python(root: str | Path, python: str | None = None) -> str:
    """Return the interpreter used to launch the MCP server.

    Defaults to the interpreter running this code: it is the one that has the
    ``kb`` package installed, so the server imports from the install rather
    than from the vault, and works from any launch directory.
    """

    return python or sys.executable


def server_args(root: str | Path) -> list[str]:
    return ["-m", "kb.server", "--root", str(Path(root).resolve())]


def codex_snippet(root: str | Path, python: str | None = None) -> str:
    args = json.dumps(server_args(root))
    command = json.dumps(server_python(root, python))
    return (
        "[mcp_servers.knowledge-base]\n"
        f"command = {command}\n"
        f"args = {args}\n"
    )


def claude_snippet(root: str | Path, python: str | None = None) -> str:
    payload = {
        "mcpServers": {
            "knowledge-base": {
                "command": server_python(root, python),
                "args": server_args(root),
            }
        }
    }
    return json.dumps(payload, indent=2)


LAUNCHD_PATH = str(Path.home() / ".local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def launchd_plist(root: str | Path, python: str | None = None) -> str:
    root = Path(root).resolve()
    # launchd starts with a minimal PATH, so restore the entries the run's
    # claude, gh, and git calls need (ADR 0002).
    args = [server_python(root, python), "-m", "kb", "--root", str(root), "--json", "auto-ingest"]
    arg_items = "\n".join(f"    <string>{escape(arg)}</string>" for arg in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.knowledge-base.auto-ingest</string>
  <key>WorkingDirectory</key>
  <string>{escape(str(root))}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{escape(LAUNCHD_PATH)}</string>
  </dict>
  <key>ProgramArguments</key>
  <array>
{arg_items}
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>0</integer>
    <key>Hour</key>
    <integer>20</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>{escape(str(root / "auto-ingest.out.log"))}</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(root / "auto-ingest.err.log"))}</string>
</dict>
</plist>
"""


def _target_for(host: str, home: str | Path | None = None) -> Path:
    home_path = Path(home).expanduser() if home is not None else Path.home()
    if host == "codex":
        return home_path / ".codex/config.toml"
    if host == "claude":
        return home_path / "Library/Application Support/Claude/claude_desktop_config.json"
    if host == "launchd":
        return home_path / "Library/LaunchAgents/com.knowledge-base.auto-ingest.plist"
    raise InstallError(f"unsupported host: {host}")


def _snippet_for(host: str, root: str | Path, python: str | None = None) -> str:
    if host == "codex":
        return codex_snippet(root, python)
    if host == "claude":
        return claude_snippet(root, python)
    if host == "launchd":
        return launchd_plist(root, python)
    raise InstallError(f"unsupported host: {host}")


def plan_install(
    host: str,
    root: str | Path,
    home: str | Path | None = None,
    python: str | None = None,
) -> InstallPlan:
    target = _target_for(host, home)
    return InstallPlan(
        host=host,
        target=str(target),
        snippet=_snippet_for(host, root, python),
    )


def install_host(
    host: str,
    root: str | Path,
    *,
    home: str | Path | None = None,
    python: str | None = None,
    write: bool = False,
    yes: bool = False,
) -> InstallPlan:
    """Plan or perform a host-config install.

    Global host files are modified only when both ``write`` and ``yes`` are
    supplied. The CLI surfaces this as an explicit confirmation gate.
    """

    plan = plan_install(host, root, home=home, python=python)
    if not write:
        return plan
    if not yes:
        raise InstallError("refusing to modify host configuration without --yes")
    target = Path(plan.target)
    target.parent.mkdir(parents=True, exist_ok=True)
    changed = False
    if host == "codex":
        marker = "[mcp_servers.knowledge-base]"
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if marker not in existing:
            prefix = "" if existing == "" or existing.endswith("\n") else "\n"
            target.write_text(f"{existing}{prefix}\n{plan.snippet}", encoding="utf-8")
            changed = True
    elif host == "claude":
        data = {}
        if target.exists():
            data = json.loads(target.read_text(encoding="utf-8"))
        data.setdefault("mcpServers", {})
        before = json.dumps(data, sort_keys=True)
        data["mcpServers"]["knowledge-base"] = json.loads(plan.snippet)[
            "mcpServers"
        ]["knowledge-base"]
        changed = json.dumps(data, sort_keys=True) != before
        if changed:
            target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    elif host == "launchd":
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        if existing != plan.snippet:
            target.write_text(plan.snippet, encoding="utf-8")
            changed = True
    else:  # pragma: no cover
        raise InstallError(f"unsupported host: {host}")
    return InstallPlan(
        host=plan.host,
        target=plan.target,
        snippet=plan.snippet,
        written=True,
        changed=changed,
    )
