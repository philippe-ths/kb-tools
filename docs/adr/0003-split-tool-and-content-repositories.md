# Split the tool and the content into separate repositories

The knowledge-base tooling moves out of the vault into its own public repository, `kb-tools`, packaged as the installable `kb` Python package with `kb` and `kb-server` commands. The vault stays a private repository and consumes the tool pinned to a release tag (`pip install git+https://github.com/philippe-ths/kb-tools@vX.Y.Z`).

The vault holds third-party source documents that cannot be redistributed and personal notes that should not be published, while the tooling holds nothing personal and is worth publishing. The tool already addressed the vault only through `--root` / `KNOWLEDGE_BASE_ROOT`, so the boundary existed in the code; this makes it a repository boundary. The public repository starts from a fresh history so no vault content is reachable from it.

The tool no longer assumes it lives inside the vault. The MCP server is launched by the interpreter that has `kb` installed, not by putting the vault on `PYTHONPATH`; this matters most for autonomous ingestion, whose worktrees are checkouts of the vault and contain no tool code. The launchd schedule invokes `python -m kb auto-ingest` directly with a restored `PATH` rather than a launcher script in the vault. The `mcp` dependency is pinned below 2.0, where the SDK renamed the API the server uses.

Considered: a git submodule, rejected because autonomous ingestion works in git worktrees and submodules make those fiddly; a sibling checkout on `PYTHONPATH`, rejected because nothing pins the version and launchd's minimal environment breaks it.

References to `tools/kb/` in ADRs 0001 and 0002 describe the layout at the time; the code they refer to is now the `kb` package.
