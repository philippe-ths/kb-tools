# Knowledge Base

This context defines the language for the personal LLM wiki and its MCP-facing workflows.

## Language

**Compiled wiki**:
The generated `wiki/` layer that stores durable, synthesized knowledge for future questions.
_Avoid_: RAG corpus, document dump

**Evidence layer**:
The immutable `raw/` layer that stores source material used to verify or extend the compiled wiki.
_Avoid_: Primary memory, editable sources

**Knowledge-base lifecycle**:
The loop of ingesting sources, querying the compiled wiki, consolidating useful answers, auditing drift, and logging activity.
_Avoid_: Chat history, one-off retrieval

**Maintainer workflow**:
The complete update path for durable knowledge changes: append `log.md`, create or update `wiki/` pages, update `index.md`, and adjust related pages.
_Avoid_: Single-file write, isolated note update

**Graph index**:
A derived map of wiki pages, wikilinks, backlinks, orphan pages, missing pages, and related clusters used to navigate and maintain the compiled wiki.
_Avoid_: Search index, vector store

**Autonomous maintenance agent**:
A workflow that can audit the compiled wiki, propose maintenance, apply approved local changes, verify the result, and optionally prepare git history without being manually driven step by step.
_Avoid_: Chat assistant, passive MCP server

**Maintenance loop**:
An autonomous run that audits, applies approved maintenance, verifies the graph, and repeats until no useful changes remain or a fixed budget is reached.
_Avoid_: Infinite agent, scheduled job

**Maintenance worktree**:
A separate git worktree used by the autonomous maintenance agent so weekly runs do not touch the human's active checkout.
_Avoid_: Stash workflow, in-place weekly edits

**Knowledge-base tooling**:
The `kb` package (this repository) that implements the MCP server, graph verification, maintenance runner, scheduling support, and PR preparation.
_Avoid_: Hidden dotfile automation, generated wiki content
