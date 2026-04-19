# Published Skills

Claude Code skills recommended for external reuse. Each entry is a symlink to
the canonical version in `../../skills/`.

## Format

Claude Code skills — directories containing `SKILL.md` (the skill definition)
plus optional `references/` and auxiliary files. Place in `~/.claude/skills/`
(user-wide) or `.claude/skills/` (project-specific) to make available.

## Current entries

- **`improve-prompt/`** — Systematically improve a seed prompt using
  anti-satisficing techniques. Applies 16 field-tested techniques based on
  task classification.

- **`review-implementation/`** — Structured review protocol for catching
  suboptimal implementations and methodology choices. Surfaces both discovery
  failures (capabilities not yet considered) and exploitation failures
  (capabilities known but underused).

- **`phase-gate/`** — Experimental phase boundary checkpoint. Use before
  committing API spend or compute to a new experimental phase. Surfaces
  under-powered assumptions from prior phases.

- **`audit-config/`** — Pre-launch experimental configuration audit. Checks
  every config parameter against the preregistered protocol, known failure
  modes, and the filesystem.

- **`reflect/`** — End-of-session reflection protocol. Structured prompts
  for maintaining research observation logs and reflection documents.

- **`build-rubric/`** — Build assessment rubrics for marking student work.

## Adapting

Most skills are generic but some reference the author's workflow conventions
(UK/Australian English, specific file layouts). Review `SKILL.md` for each
before adopting.
