# Autonomous ingestion with guarded auto-merge

We will extend the autonomous knowledge-base maintenance agent (ADR 0001) from graph/citation hygiene into autonomous content ingestion of new `raw/` sources, and we will allow the agent to merge its own pull requests automatically, but only behind a deterministic guard. The human's only routine task becomes adding source material to `raw/`; the system detects, synthesizes, verifies, and merges without per-run approval in the happy path.

This supersedes two limits in ADR 0001: that "content consolidation is deferred until the graph and citation maintenance loop is proven", and that autonomous external actions are "limited to GitHub branch push plus PR creation". ADR 0001's other constraints remain in force.

## Trigger and detection

The normal trigger remains a local weekly schedule (Sunday evening) plus manual invocation. On each run the agent computes the set of *pending* sources: markdown files under `raw/` that no `wiki/` page cites via a `[[raw/...]]` wikilink and that are not matched by a glob in a root-level `.kb-ingest-ignore` file. Detection is stateless: it derives the pending set from the current vault and the ignore file rather than from a separate manifest that could drift. `.kb-ingest-ignore` is how deliberately-parked material (for example the bulk AI Engineering source archive and `raw/assets/`) stays out of the autonomous queue.

## Ingestion

For each pending source the agent runs the `CLAUDE.md` ingest workflow inside a dedicated `kb-maintenance/` worktree: read the source, write or update a `wiki/` summary page, update `index.md`, update related concept/entity pages with cross-links, and append a `log.md` line. All writes funnel through the guarded vault writers and the propose/apply workflow, so the `raw/`-immutable, `log.md`-append-only, and flat-`wiki/` rules are enforced in code.

A worktree is a clean checkout of the base commit, so a freshly-dropped (still untracked) raw source is absent there. The orchestrator therefore copies each pending raw file into the worktree before ingestion, and stages the generated layer (`wiki/`, `index.md`, `log.md`) together with this run's own pending sources. A page and the evidence it cites land in the same commit.

The run branches from the remote-tracking ref rather than the local base branch. A local branch only advances when someone pulls, so in a vault whose human reads in Obsidian and never pulls it pins every run to the same commit; three consecutive runs then branch from one stale base, each re-ingesting what the previous had already landed.

An earlier revision of this ADR excluded raw inputs from the commit, on the reasoning that a just-dropped source could then be ingested without its evidence appearing in the diff. That was wrong in a way the gate could not see: verification reads the worktree, where the copied evidence resolves every citation, while the merge carries only the pages. Four PRs merged reporting zero warnings and left 23 broken citations on `main`. The gate now also requires the worktree to be clean after the commit, so verification cannot again pass on a tree the merge will not produce.

The ingest and review agents run under a strict default-deny tool allowlist limited to the knowledge-base MCP tools (no `Bash`, no direct file writes, no `bypassPermissions`). The agent can read raw and wiki content and propose/apply changes through the guarded writers, but cannot otherwise touch the filesystem. Default-deny is the primary sandbox; the merge gate is the backstop, not the only line of defence.

## Adversarial self-review

Before any merge, an independent review pass attempts to refute each new or changed page against its cited raw source: unsupported claims, miscitations, contradictions with existing pages. The reviewer returns a structured verdict. A blocking objection forces the PR to stay open for the human. This is the only check that targets truth rather than structure, and it is deliberately fallible; it lowers but does not remove the risk of a confident-wrong synthesis.

## The guarded auto-merge gate

The agent pushes the branch and opens a PR. It auto-merges only when every one of the following deterministic conditions holds; otherwise the PR is left open for human review:

- repository validation (`./.ai-policy/scripts/run-validation.sh`) passes,
- post-change graph and citation verification report zero total warnings and introduce no new warning of any bucket,
- the diff touches only `wiki/`, `index.md`, `log.md`, and `raw/`; never code, policy, or any other path,
- the worktree is clean after the commit, so what was verified is what will merge,
- the adversarial review returns no blocking objection.

The gate fails closed: any error, timeout, ambiguity, or unmet condition results in no merge and an open PR. Merge uses a non-force squash merge of the `kb-maintenance/` branch into `main`; protected-branch direct pushes and force-pushes remain forbidden.

## Residual risk and recovery

A structurally clean, well-formed, but factually wrong page can pass the gate and merge unread. This is the accepted cost of zero-touch operation. Mitigations: every claim cites its raw source, the adversarial reviewer catches the obvious cases, the weekly cadence bounds blast radius, and git history makes any merge auditable and revertible. The human may at any time inspect open PRs, the merge log, or revert a merged page.

## Scope

This ADR covers autonomous ingestion of markdown sources and guarded auto-merge. Non-markdown sources (PDFs, images) still require a human or a separate extraction step before they enter the pending queue. Hosted (non-local) scheduling remains out of scope. The deterministic detection, gate evaluation, and orchestration flow live under `tools/kb/` with unit tests using injected command and agent runners; the live agent, git, and `gh` calls are driven through those injectable seams.
