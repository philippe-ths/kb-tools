"""Knowledge-base tooling for graph/search, writes, and maintenance.

This package builds an in-memory graph index over the compiled `wiki/` layer
and `index.md`, provides lexical search and read/query operations, applies
guarded change sets, and orchestrates local maintenance reports.

Layers (see CONTEXT.md):
- `wiki/`  : compiled memory  (graph nodes live here, plus `index.md`)
- `raw/`   : immutable evidence (read-only; resolvable as link targets only)

The public operations live in `kb.api`. The graph and search live in `kb.graph`
and `kb.search`; guarded writes live in `kb.vault` and `kb.changes`; local
maintenance orchestration lives in `kb.maintenance`.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
