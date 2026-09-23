# Local MCP knowledge base

We will expose this vault through a globally configured local MCP server so Claude Code and Codex can query it from any working directory while preserving the vault as the durable memory artifact. The server will be implemented in Python, use an MCP SDK, privilege the compiled `wiki/` layer before consulting `raw/`, and support read/write maintainer workflows through explicit propose/apply steps.

The long-term target includes an autonomous knowledge-base maintenance agent. It may push maintenance branches and open GitHub PRs without per-run approval only under a narrow project-policy exception: branch names must start with `kb-maintenance/`, no direct pushes to protected branches, no force-push, no edits under `raw/`, changes limited to generated wiki maintenance and control files, and external actions limited to GitHub branch push plus PR creation for this repository.

Autonomous maintenance may run as a Claude background loop using the knowledge-base MCP server as its substrate. Each maintenance loop stops when verification converges with no useful proposed changes remaining or when a fixed iteration/time/cost budget is reached. The normal autonomous trigger is a local weekly schedule on Sunday evening; hosted scheduling is out of scope until the local process is proven. If a weekly run produces changes, it opens a GitHub PR automatically. The PR is ready for review when verification passes cleanly, and draft when unresolved warnings remain.

Weekly maintenance runs use a separate git worktree under `~/.cache/kb-maintenance/worktrees/` so the autonomous process does not touch the human's active checkout or stash local work.

Autonomous maintenance branches use the pattern `kb-maintenance/YYYY-MM-DD-purpose`, with `wiki-health` as the default weekly purpose and numeric suffixes for collisions.

Phase 1 weekly audits cover graph hygiene and citation hygiene. Content consolidation is deferred until the graph and citation maintenance loop is proven. Before pushing or opening a PR, the agent runs MCP graph/citation verification and `./.ai-policy/scripts/run-validation.sh`.

Autonomous PR bodies include a maintenance report: summary, graph stats before and after, citation warnings fixed and remaining, validation output, and residual risks.

If validation fails after changes are made, the agent still pushes the maintenance branch and opens a draft PR with the failure details preserved in the maintenance report.

Knowledge-base automation lives under `tools/kb/`, including the MCP server, graph verification, maintenance runner, scheduling support, and PR preparation code.

The tooling includes an installer script for configuring both Claude and Codex MCP entries. The installer must ask before modifying global host configuration.

Implementation is split into three milestones: first graph/search/read-only MCP, then write workflow and verification, then autonomous weekly runner with worktree, PR automation, and installer.
