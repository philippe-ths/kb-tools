# kb-tools

Tooling for a personal LLM wiki in the pattern Andrej Karpathy described: a folder of plain markdown that a coding agent reads, writes and keeps current, browsed in Obsidian. This package puts a graph, a search index, guarded writes and an MCP server over such a vault, and runs an autonomous ingestion loop that files new sources by itself behind a fail-closed merge gate.

There is no RAG here, no embeddings and no vector store, by decision rather than omission. Retrieval is lexical and in memory: term frequency with a title boost and a one-hop walk along wikilinks. The pattern is knowledge compiled into pages an agent can read whole, not chunks retrieved by similarity.

My own vault is private: it holds third-party papers I cannot redistribute and personal notes. It consumes this package pinned to a release tag. [`examples/vault/`](examples/vault) is a small slice of it so you can run everything below.

## The vault it expects

- `raw/` is the evidence layer: immutable source material. Nothing in the tooling can write here; the guard is in code, not convention.
- `wiki/` is the compiled layer: synthesised pages, each citing the sources it was written from. Agents maintain it; a human reads it.
- `index.md` is the map the agent routes questions through; `log.md` is append-only history.

[`templates/kb-schema.md`](templates/kb-schema.md) is the schema an agent follows to maintain a vault like this, and [`docs/CONTEXT.md`](docs/CONTEXT.md) is the glossary.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/kb --root examples/vault verify            # graph + citation audit
.venv/bin/kb --root examples/vault search "goodhart"
.venv/bin/kb --root examples/vault read wiki/concept-software-engineering-laws
.venv/bin/python -m unittest discover -s tests -t .  # runs against a temporary fixture vault
```

Or install it into another project: `pip install git+https://github.com/philippe-ths/kb-tools@v1.0.0`.

The root falls back to `KNOWLEDGE_BASE_ROOT`. Add `--json` before the subcommand for machine-readable output.

## The MCP server

`kb-server --root /path/to/vault` exposes ten tools over stdio to Claude Code, Codex or Claude Desktop. `kb install --host claude` (or `codex`) prints the host config; `--write --yes` applies it.

| Tool | Does |
| --- | --- |
| `kb_search` | lexical search over `index.md` and `wiki/` |
| `kb_read_page` | one page with its outgoing links and backlinks |
| `kb_build_context` | a bundle of pages for a question |
| `kb_graph_summary` | the catalogue: categories, counts, orphans, broken links |
| `kb_hygiene` | graph hygiene report |
| `kb_verify` | graph plus citation audit |
| `kb_propose_changes` | unified diff per operation and before/after verification, over an in-memory overlay; writes nothing |
| `kb_apply_changes` | commit a change set through the guarded writers, then re-verify on disk |
| `kb_fetch_queries` | the recorded search history |
| `kb_reload` | re-read the vault after an outside change |

A change set is JSON: `write_page` under a flat `wiki/`, `write_index`, or `append_log`. Those are the only three writes that exist. `raw/` cannot be written, `log.md` can only be appended, and a path that escapes the vault is refused.

## Autonomous ingestion

`kb --root <vault> auto-ingest`, scheduled weekly through launchd (`kb install --host launchd`):

1. Find pending sources: any `raw/*.md` no wiki page cites, minus the vault's `.kb-ingest-ignore`.
2. Branch from the remote base into a `kb-maintenance/` worktree, so the human's checkout is never touched.
3. For each source, a **writer** agent (Claude CLI, headless) synthesises a cited page and commits it together with the source it cites.
4. An independent **reviewer** agent reads the diff adversarially and returns a structured JSON verdict.
5. A deterministic merge gate decides. It merges only when validation passes, verification shows zero warnings and zero new warnings, the diff touches only `wiki/`, `index.md`, `log.md` and `raw/`, the worktree is clean after the commit, and the reviewer raised no blocking objection. Anything else leaves the pull request open for the human.

Both agents run under a hard-coded allowlist of the `kb_*` tools and nothing else: no Bash, no Write, no Edit. The git, `gh` and agent calls sit behind injectable seams, so the gate's logic is unit-tested without a model in the loop. If the vault has a validation script at `.ai-policy/scripts/run-validation.sh` it runs as part of the gate; otherwise validation is recorded as skipped.

## Layout

| Module | Responsibility |
| --- | --- |
| `vault.py` | root resolution, file discovery, reads, and the guarded writers |
| `wikilinks.py` | wikilink parsing and target resolution |
| `categories.py` | `index.md` category parsing |
| `graph.py` | in-memory graph: links, backlinks, broken links, orphans |
| `search.py` | lexical search index |
| `changes.py` | change-set model and write-rule guards |
| `verify.py` | graph and citation audit, before/after deltas |
| `maintenance.py` | maintenance runs, worktree planning, PR reports |
| `ingest.py`, `autoingest.py`, `agents.py` | pending-source detection, the ingestion orchestrator and merge gate, the Claude CLI runner |
| `install.py` | MCP host config and launchd snippets |
| `api.py` | `KnowledgeBase` facade every front end calls |
| `__main__.py`, `server.py` | the CLI and the MCP server, both thin adapters over `api.py` |

The core is standard-library Python 3.10+; only the MCP server needs the `mcp` SDK.

## Decisions

- [0001](docs/adr/0001-local-mcp-knowledge-base.md): a local MCP knowledge base with propose/apply writes.
- [0002](docs/adr/0002-autonomous-ingest-guarded-auto-merge.md): autonomous ingestion with a guarded auto-merge.
- [0003](docs/adr/0003-split-tool-and-content-repositories.md): this package split out of the private vault.

## License

MIT. The example vault's content is included for demonstration.
