# Knowledge base schema

You maintain a personal LLM wiki. Obsidian is the viewer; you are the maintainer.

## Layers
- `raw/` : immutable source documents. Read these, never edit them.
- `wiki/` : markdown pages you generate and own. Summaries, entity pages,
  concept pages, comparisons, an overview.
- This file : the conventions you follow. We co-evolve it.

## Wiki conventions
- One page per entity or concept. Filenames in kebab-case.
- Link related pages with [[wikilinks]] generously. Avoid orphan pages.
- Cite the raw source(s) a claim came from. Prefer block references
  (`[[src-page#^id]]`) when a claim maps to a specific line of a source.
- Optional YAML frontmatter on each page: tags, date, source_count.
- Author every page with the `obsidian-markdown` skill as the syntax authority:
  wikilinks, `> [!type]` callouts, `![[embeds]]`, block references, and typed
  frontmatter properties. Use callouts for warnings/contradictions/notes rather
  than plain prose so they surface in Obsidian.

## Operations

### Ingest (when I add a source to raw/)
1. Read the source. If it is a web page/URL, extract clean markdown with the
   `defuddle` skill (`defuddle parse <url> --md -o raw/<slug>.md`) and treat that
   archived file as the immutable evidence; skip defuddle for `.md` URLs. Note
   key takeaways.
2. Write/update a summary page in wiki/, authored with the `obsidian-markdown` skill.
3. Update index.md (link + one-line summary, by category).
4. Update related entity and concept pages. Add cross-links, using block
   references for line-specific claims.
5. Flag any contradictions with existing pages using a callout
   (`> [!warning] Contradiction`) that links both sides.
6. Append a line to log.md: `## [YYYY-MM-DD] ingest | <title>`.

### Query (when I ask a question)
1. Read index.md first to find relevant pages.
2. Read those pages, answer with citations.
3. Offer to file good answers back into the wiki as new pages, authored with the `obsidian-markdown` skill.
4. Append a line to log.md: `## [YYYY-MM-DD] query | <question>`.

### Lint (when I ask for a health check)
Report: contradictions, stale claims, orphan pages, missing concept
pages, missing cross-links. Suggest new questions and sources to pursue.

## Index and log
- index.md : root-level catalog of every generated wiki page. Update on every ingest.
- log.md : root-level append-only history for the whole vault. Never rewrite past entries.
