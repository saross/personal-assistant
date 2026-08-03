# Published Skills

Claude Code skills recommended for external reuse. **Each entry is a
sanitised copy** of the canonical working version in `../../skills/` (or
`../../commands/`) — copies only, no symlinks, per the 2026-06-15 policy
in [`../README.md`](../README.md). Copies are refreshed at `/retro`
curation; the source may run ahead between refreshes.

## Format

Single-file `SKILL.md` snapshots. To use: place the content in
`~/.claude/skills/<name>/SKILL.md` (user-wide) or
`.claude/skills/<name>/SKILL.md` (project-specific), or register as a
slash command per your harness's conventions.

## Current entries

- **`audit.md`** — Code-audit command: two-lens fresh-context review
  (does-it-do-what-it-claims + assume-it-is-wrong test-adequacy), with
  two non-negotiables — commit before delegating, and never audit your
  own work in your own context. (Published 2026-08-03.)

- **`improve-prompt.md`** — Systematically improve a seed prompt using
  anti-satisficing techniques. Applies 16 field-tested techniques based
  on task classification. (Published 2026-08-03.)

- **`phase-gate.md`** — Experimental phase-boundary checkpoint. Use
  before committing API spend or compute to a new phase. Surfaces
  under-powered assumptions from prior phases. (Refreshed 2026-08-03.)

- **`review-implementation.md`** — Structured review protocol for
  catching suboptimal implementations and methodology choices —
  discovery failures (capabilities not considered) and exploitation
  failures (capabilities underused). Includes the study-design checklist
  (circularity, post-treatment conditioning, comparison confounds).
  (Refreshed 2026-08-03.)

## Adapting

Skills reference the conventions of their source system (planning
directories, register notes, observation logs, UK/Australian English).
Treat those as placeholders for your own equivalents; the review logic
is the portable part.
