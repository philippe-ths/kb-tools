"""A deterministic in-memory fixture vault for the test suite.

The fixture exercises every Milestone-1 signal: bare and explicit wikilinks,
aliases, a raw-layer link, a broken link, and an orphan page.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

_FILES: dict[str, str] = {
    "index.md": """# Index

## Concepts

### Greek
- [[wiki/concept-alpha]] : the alpha concept
- [[wiki/concept-beta]] : the beta concept
- [[wiki/concept-orphan]] : an orphan concept

## Sources
- [[wiki/src-gamma]] : a source

## Maps
- [[wiki/overview]] : the map
""",
    "wiki/overview.md": """# Overview

Links to [[concept-alpha]] and [[concept-beta]].
""",
    "wiki/concept-alpha.md": """# Alpha

Alpha references [[concept-beta]] and [[concept-beta|the beta alias]],
plus [[wiki/src-gamma]], evidence in [[raw/evidence-a]], the [[overview]],
and a [[concept-missing]] page that does not exist.

```
not a link: [[concept-ignored]]
```

Inline `[[also-ignored]]` here.
""",
    "wiki/concept-beta.md": """# Beta

Beta points back to [[concept-alpha]].
""",
    "wiki/concept-orphan.md": """# Orphan

This page links to [[concept-alpha]] but nothing links to it.
""",
    "wiki/src-gamma.md": """# Gamma source

Gamma cites [[concept-alpha]].
""",
    "raw/evidence-a.md": """# Evidence A

Immutable evidence.
""",
}


def make_vault() -> "tempfile.TemporaryDirectory[str]":
    """Create a temp vault, returning the TemporaryDirectory (root at .name)."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    for rel, content in _FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return tmp
