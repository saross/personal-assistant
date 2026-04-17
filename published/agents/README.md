# Published Agents

Subagent definitions recommended for external reuse. Each entry is a symlink
to the canonical version in `../../agents/`.

## Format

Claude Code agent definitions — Markdown files with YAML frontmatter. Place in
`~/.claude/agents/` (user-wide) or `.claude/agents/` (project-specific) to make
available to Claude Code.

## Current entries

- **`lit-scout.md`** — Systematic academic literature discovery with bibliography
  chaining via CrossRef, Semantic Scholar, and OpenAlex. Handles forward and
  backward citation chaining and checks against a local Zotero library.
  Requires companion script `scripts/lit-search.py`.

- **`prior-art-scout.md`** — Searches for existing implementations, libraries,
  tools, and approaches before building something new. Covers GitHub, GitLab,
  PyPI, Hugging Face, Stack Overflow, and methodological literature.

## Adapting

Both agents reference paths and tools specific to Shawn's setup (e.g.,
`/home/shawn/personal-assistant/venv/bin/python3`, `~/Zotero/zotero.sqlite`).
Adapt paths for your environment before use.
