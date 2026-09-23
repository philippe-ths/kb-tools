"""Dependency-free CLI over the knowledge-base operations.

Useful for manual inspection and verification without the MCP transport, e.g.::

    python -m kb --root /path/to/vault graph
    python -m kb --root /path/to/vault search "agent memory" --limit 5
    python -m kb --root /path/to/vault read wiki/overview
    python -m kb --root /path/to/vault hygiene
    python -m kb --root /path/to/vault context "prompt injection"

The vault root falls back to the KNOWLEDGE_BASE_ROOT environment variable.

Exit codes: 0 on success. 2 when a raised error stops the command before it
could complete (e.g. a git/gh/validation infrastructure failure). For
``auto-ingest`` specifically, a third code -- ``AUTO_INGEST_FAILURE_EXIT``,
currently 3 -- means the command ran to completion but the report it produced
has ``ok: false`` (e.g. every ingest agent call failed, status
``ingest-failed``); this is distinct from 2 because the run did not raise, it
just failed to land anything. No other subcommand uses this third code.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from .agents import claude_agent_runner
from .api import KnowledgeBase
from .autoingest import AutoIngestError, default_notifier, run_auto_ingest
from .changes import ChangeError
from .ingest import pending_report
from .install import InstallError, install_host
from .maintenance import (
    DEFAULT_BASE_REF,
    DEFAULT_PURPOSE,
    DEFAULT_WORKTREE_ROOT,
    MaintenanceError,
    prepare_worktree,
    render_pr_body,
    render_pr_commands,
    run_maintenance,
)
from .vault import VaultError

# Distinct from the generic raised-error exit (2): the auto-ingest command ran
# to completion and produced a report, but that report has `ok: false` (e.g.
# every ingest agent call failed -- status `ingest-failed`). See the module
# docstring. No other subcommand uses this code.
AUTO_INGEST_FAILURE_EXIT = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb", description=__doc__)
    parser.add_argument("--root", default=None, help="vault root directory")
    parser.add_argument(
        "--json", action="store_true", help="emit raw JSON instead of text"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("graph", help="graph summary and categories")
    sub.add_parser("hygiene", help="broken links, missing pages, orphans")
    sub.add_parser("verify", help="graph + citation hygiene audit")
    sub.add_parser("citations", help="citation hygiene only")
    sub.add_parser(
        "pending", help="raw sources awaiting autonomous ingestion"
    )

    p_search = sub.add_parser("search", help="lexical search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)

    p_read = sub.add_parser("read", help="read a page with its links")
    p_read.add_argument("page_id")

    p_ctx = sub.add_parser("context", help="assemble context for a query")
    p_ctx.add_argument("query")
    p_ctx.add_argument("--limit", type=int, default=5)

    p_propose = sub.add_parser(
        "propose", help="preview a JSON change set (diffs + verification), no write"
    )
    p_propose.add_argument(
        "changes", help="path to a JSON change-set file, or '-' for stdin"
    )

    p_apply = sub.add_parser("apply", help="commit a JSON change set to disk")
    p_apply.add_argument(
        "changes", help="path to a JSON change-set file, or '-' for stdin"
    )

    p_maintenance = sub.add_parser(
        "maintenance-run",
        help="audit, optionally preview/apply changes, validate, and report",
    )
    p_maintenance.add_argument(
        "--changes", help="path to a JSON change-set file, or '-' for stdin"
    )
    p_maintenance.add_argument(
        "--apply", action="store_true", help="write the supplied change set"
    )
    p_maintenance.add_argument(
        "--no-validation", action="store_true", help="skip repo validation"
    )
    p_maintenance.add_argument("--branch", help="maintenance branch name")
    p_maintenance.add_argument("--worktree", help="maintenance worktree path")
    p_maintenance.add_argument(
        "--report", help="write the rendered maintenance report markdown here"
    )

    p_worktree = sub.add_parser(
        "maintenance-worktree",
        help="plan or create a dedicated maintenance git worktree",
    )
    p_worktree.add_argument("--purpose", default=DEFAULT_PURPOSE)
    p_worktree.add_argument(
        "--date",
        help="run date in YYYY-MM-DD format; defaults to today's UTC date",
    )
    p_worktree.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    p_worktree.add_argument("--worktree-root", default=DEFAULT_WORKTREE_ROOT)
    p_worktree.add_argument(
        "--execute",
        action="store_true",
        help="actually run git worktree add; default only prints the plan",
    )
    p_worktree.add_argument(
        "--no-bootstrap-validation",
        action="store_true",
        help="do not copy ignored validation support files into the worktree",
    )

    p_ingest = sub.add_parser(
        "auto-ingest",
        help="detect, ingest, review, gate, and (if green) auto-merge new sources",
    )
    p_ingest.add_argument(
        "--no-merge",
        action="store_true",
        help="open the PR but never auto-merge, even when the gate is green",
    )
    p_ingest.add_argument(
        "--no-validation", action="store_true", help="skip repo validation"
    )
    p_ingest.add_argument(
        "--no-fetch", action="store_true", help="skip the base-ref git fetch"
    )
    p_ingest.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    p_ingest.add_argument("--worktree-root", default=DEFAULT_WORKTREE_ROOT)
    p_ingest.add_argument(
        "--date", help="run date in YYYY-MM-DD format; defaults to today's UTC date"
    )

    p_install = sub.add_parser(
        "install",
        help="print or write MCP host config and local schedule snippets",
    )
    p_install.add_argument(
        "--host",
        choices=("codex", "claude", "launchd", "all"),
        default="all",
    )
    p_install.add_argument("--python", help="interpreter for launching the kb server")
    p_install.add_argument(
        "--write",
        action="store_true",
        help="modify host config files instead of printing only",
    )
    p_install.add_argument(
        "--yes",
        action="store_true",
        help="required with --write to confirm global host config changes",
    )

    return parser


def _load_changes(source: str) -> list:
    text = sys.stdin.read() if source == "-" else open(source, encoding="utf-8").read()
    return json.loads(text)


def _run(kb: KnowledgeBase, args: argparse.Namespace) -> dict:
    if args.command == "graph":
        return kb.graph_summary()
    if args.command == "hygiene":
        return kb.hygiene()
    if args.command == "verify":
        return kb.verify()
    if args.command == "citations":
        return kb.citation_hygiene()
    if args.command == "pending":
        return pending_report(kb.vault)
    if args.command == "search":
        return kb.search(args.query, limit=args.limit)
    if args.command == "read":
        return kb.read_page(args.page_id)
    if args.command == "context":
        return kb.build_context(args.query, limit=args.limit)
    if args.command == "propose":
        return kb.propose(_load_changes(args.changes))
    if args.command == "apply":
        return kb.apply(_load_changes(args.changes))
    if args.command == "maintenance-run":
        changes = _load_changes(args.changes) if args.changes else None
        return run_maintenance(
            kb.vault.root,
            changes=changes,
            apply_changes=args.apply,
            validate=not args.no_validation,
            branch=args.branch,
            worktree=args.worktree,
        )
    raise AssertionError(f"unhandled command: {args.command}")  # pragma: no cover


def _run_without_kb(args: argparse.Namespace) -> dict | None:
    if args.command == "maintenance-worktree":
        run_date = date.fromisoformat(args.date) if args.date else None
        root = args.root or "."
        return prepare_worktree(
            root,
            purpose=args.purpose,
            run_date=run_date,
            worktree_root=args.worktree_root,
            base_ref=args.base_ref,
            execute=args.execute,
            bootstrap_validation=not args.no_bootstrap_validation,
        )
    if args.command == "auto-ingest":
        run_date = date.fromisoformat(args.date) if args.date else None
        root = args.root or "."
        # auto-ingest.out.log / .err.log are append-only and never rotated, so
        # without a marker, one run's output runs straight into the next with
        # no way to tell them apart. One line, on both streams, at run start.
        marker = f"=== kb auto-ingest run start {datetime.now(timezone.utc).isoformat()} ==="
        # stderr always; stdout only in text mode. The launchd job runs
        # `--json auto-ingest`, and stdout is then a single JSON document that
        # a consumer parses -- a marker line prepended to it would break them.
        print(marker, file=sys.stderr)
        if not getattr(args, "json", False):
            print(marker, file=sys.stdout)
        return run_auto_ingest(
            root,
            notify=default_notifier,
            ingest_agent=claude_agent_runner,
            review_agent=claude_agent_runner,
            run_date=run_date,
            worktree_root=args.worktree_root,
            base_ref=args.base_ref,
            auto_merge=not args.no_merge,
            validate=not args.no_validation,
            fetch=not args.no_fetch,
        )
    if args.command == "install":
        root = args.root or "."
        hosts = ("codex", "claude", "launchd") if args.host == "all" else (args.host,)
        return {
            "plans": [
                install_host(
                    host,
                    root,
                    python=args.python,
                    write=args.write,
                    yes=args.yes,
                ).to_dict()
                for host in hosts
            ]
        }
    return None


def _print_text(command: str, data: dict) -> None:
    if command == "graph":
        for key, value in data["summary"].items():
            print(f"{key:>16}: {value}")
        print("\ncategories:")
        for cat in data["categories"]:
            print(f"  {cat['path']} ({len(cat['pages'])})")
    elif command == "hygiene":
        broken = data["broken_links"]
        print(f"broken links: {len(broken)}")
        for b in broken:
            print(f"  {b['source']} -> {b['target']}")
        print(f"missing pages: {len(data['missing_pages'])}")
        for t in data["missing_pages"]:
            print(f"  {t}")
        print(f"orphan pages: {len(data['orphan_pages'])}")
        for o in data["orphan_pages"]:
            print(f"  {o}")
    elif command == "search":
        for r in data["results"]:
            print(f"[{r['score']:>3}] {r['id']} — {r['title']}")
            if r["snippet"]:
                print(f"        {r['snippet']}")
    elif command == "read":
        print(f"# {data['title']}  ({data['id']})")
        print(f"backlinks: {', '.join(data['backlinks']) or 'none'}")
        print(f"outgoing: {len(data['outgoing'])} links\n")
        print(data["text"])
    elif command == "context":
        print(f"query: {data['query']}\n")
        for p in data["pages"]:
            print(f"[{p['score']:>3}] {p['id']} — {p['title']}")
            if p["snippet"]:
                print(f"        {p['snippet']}")
        print(f"\nrelated: {', '.join(data['related']) or 'none'}")
    elif command == "verify":
        _print_verification(data)
    elif command == "citations":
        _print_citations(data)
    elif command == "pending":
        print(f"pending sources: {data['count']}")
        for source in data["pending"]:
            print(f"  {source}")
        if data["ignored_patterns"]:
            print(f"ignore patterns: {', '.join(data['ignored_patterns'])}")
    elif command == "auto-ingest":
        print(f"status: {data['status']}  ok: {data.get('ok')}  merged: {data['merged']}")
        if data.get("branch"):
            print(f"branch: {data['branch']}")
        if data.get("pr_url"):
            print(f"pr: {data['pr_url']}")
        for failure in data.get("failures") or []:
            print(f"  failure: {failure}")
        if data.get("gate"):
            gate = data["gate"]
            print(f"gate: {'MERGE' if gate['merge_ok'] else 'HOLD'}")
            for reason in gate["reasons"]:
                print(f"  - {reason}")
    elif command in ("propose", "apply"):
        _print_changes(command, data)
    elif command == "maintenance-run":
        body = render_pr_body(data)
        print(body, end="" if body.endswith("\n") else "\n")
        commands = render_pr_commands(data)
        if commands:
            print("\nremote actions, if approved separately:")
            for command_text in commands:
                print(f"  {command_text}")
    elif command == "maintenance-worktree":
        print(f"branch: {data['branch']}")
        print(f"worktree: {data['worktree']}")
        print(f"base ref: {data['base_ref']}")
        print(f"executed: {data['executed']}")
        print(f"bootstrapped: {', '.join(data['bootstrapped']) or 'none'}")
        print("command:")
        print("  " + " ".join(data["command"]))
        if data["result"] is not None:
            result = data["result"]
            print(f"return code: {result['returncode']}")
            if result["stdout"]:
                print(result["stdout"], end="" if result["stdout"].endswith("\n") else "\n")
            if result["stderr"]:
                print(result["stderr"], end="" if result["stderr"].endswith("\n") else "\n")
    elif command == "install":
        for plan in data["plans"]:
            print(f"host: {plan['host']}")
            print(f"target: {plan['target']}")
            print(f"written: {plan['written']}  changed: {plan['changed']}")
            print(plan["snippet"], end="" if plan["snippet"].endswith("\n") else "\n")
            print()


def _print_citations(citations: dict) -> None:
    for label, key in (
        ("uncited pages", "uncited_pages"),
        ("externally-sourced pages", "externally_sourced_pages"),
        ("sources missing a raw link", "sources_without_raw_link"),
    ):
        items = citations[key]
        print(f"{label}: {len(items)}")
        for item in items:
            print(f"  {item}")
    broken = citations["broken_citations"]
    print(f"broken citations: {len(broken)}")
    for b in broken:
        print(f"  {b['source']} -> {b['target']}")


def _print_verification(data: dict) -> None:
    for key, value in data["graph"].items():
        print(f"{key:>16}: {value}")
    hygiene = data["hygiene"]
    print(
        f"\nbroken links: {len(hygiene['broken_links'])}  "
        f"missing pages: {len(hygiene['missing_pages'])}  "
        f"orphan pages: {len(hygiene['orphan_pages'])}"
    )
    print("\ncitations:")
    _print_citations(data["citations"])


def _print_changes(command: str, data: dict) -> None:
    entries = data["operations"] if command == "propose" else data["applied"]
    verb = "would" if command == "propose" else "did"
    for entry in entries:
        print(f"{entry['action']} {verb} {entry['target']} ({entry['op']})")
        if command == "propose" and entry["diff"]:
            print(entry["diff"], end="" if entry["diff"].endswith("\n") else "\n")
    verification = data["verification"]
    if command == "propose":
        delta = verification["delta"]
        print(f"\nwarning delta: {delta['warnings']:+d}")
        for key, value in delta.items():
            if key != "warnings" and value:
                print(f"  {key}: {value:+d}")
    else:
        print("\npost-apply verification:")
        _print_verification(verification)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data = _run_without_kb(args)
        if data is None:
            kb = KnowledgeBase.open(args.root)
            data = _run(kb, args)
        if args.command == "maintenance-run" and args.report:
            Path(args.report).write_text(render_pr_body(data), encoding="utf-8")
    except (
        VaultError,
        ChangeError,
        InstallError,
        AutoIngestError,
        MaintenanceError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        _print_text(args.command, data)
    if args.command == "auto-ingest" and not data.get("ok", True):
        return AUTO_INGEST_FAILURE_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
