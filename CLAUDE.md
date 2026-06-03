# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This is the personal assistant system — a cross-project hub for memory, task management, and accountability.

## Repository Structure

Public repo at `~/personal-assistant/` plus a private `data/` submodule (`saross/pa-data`) containing memories, tasks, notes, reports, standups, scratchpads, and logs. Symlinks at repo root (`memories → data/memories`, etc.) preserve path compatibility. Hooks, commands, skills, scripts, and planning live in the public repo.

### Concurrent sessions — label your workstream

This repo is a hub for **several independent workstreams** (memory /
scratchpad system, style-guide construction, task-system tooling, …) that
are often edited by **concurrent Claude sessions sharing one working
tree**. Because `git add <shared-file>` (e.g. `wiki/continuity.md`) sweeps
*all* pending edits to that file — including another session's — every
session must **label its workstream** so the audit trail stays legible:

- **Commit subjects/bodies:** name the workstream, e.g.
  `docs(style-guide): …`, or a `Workstream G (style-guide)` line in the body.
- **`wiki/continuity.md` session-log headers:** suffix the date with the
  workstream tag — `### 2026-05-30 (Sat, latest G) — …` (G = style-guide)
  vs `(Sat, latest PA) — …` (PA = memory/scratchpad system).
- **Edits & commits:** confine each session to its own sections/rows.
  `git add <path>` is **not enough** — a concurrent session may have
  *already staged* its files in the shared index, and a plain
  `git commit` then sweeps them into your commit (this has happened: a
  style-guide fix commit once absorbed another session's Vector-2c
  work). Commit with an explicit pathspec — `git commit -- <path> …` —
  which commits only those paths and ignores anything else staged.
  Confirm `git diff --cached --name-only` shows only your files, and
  `git fetch` + `0 behind`, before committing.
- **Genuinely simultaneous infra work → worktree, not branch.** If two
  workstreams must run at once, give the second its own git worktree
  (separate directory = separate index + HEAD, so the sweep above becomes
  impossible). Routine per-session branches do **not** work here — one
  checkout shares a single HEAD/index/working tree, so `git checkout` would
  clobber the other session's files. Deliberate escape hatch, not the
  default (it trades the index race for merge overhead on the shared docs):

      git worktree add ../pa-<workstream> -b <workstream>
      cd ../pa-<workstream>   # work + commit on the branch, then PR/merge to main
      git worktree remove ../pa-<workstream>

This convention is **specific to this repo** — it exists only because one
repo covers many unrelated things. It does not apply to single-purpose
repos.

## Task System

### Philosophy

- Maximum 3 **actionable tasks** in active focus (FOCUS.md) — not projects
- Focus slots track concrete deliverables (e.g., "results write-up"), not project umbrellas
- Projects are grouping tags in the `Project` field, not the unit of tracking
- Backlog holds scoped tasks ready for promotion, not abstract project buckets
- Finish before starting
- Sequential beats parallel
- Confrontational accountability
- System adapts based on evidence

### Key Files

- `tasks/FOCUS.md` — Current focus (THE critical file)
- `tasks/SYSTEM.md` — System configuration (tune the parameters)
- `tasks/inbox.md` (working in-tray — pending items only), `tasks/inbox-archive.md` (killed / superseded captures + pre-2026-05-24 historical dispositions), `tasks/backlog.md`, `tasks/waiting-for.md`, `tasks/collaborators.md`

### Closure record

**The weekly review's Completions section is the canonical weekly closure
record** (since 2026-05-24). `/recap` captures closures in the day's
"Committed vs Actual" table; `/weekly-review` reconciles those + FOCUS.md
slot rotations into the canonical Completions section. `/retro` then
aggregates the month's Completions sections into a "Closures Roll-Up" — the
multi-week index.

`tasks/done/YYYY-MM.md` is **retired** as a canonical source. Historical
files (Feb–early May 2026) remain in place as audit trail; no new rows are
appended. `/done` still rotates focus slots and prompts for refocus, but no
longer writes to `tasks/done/`.

### Inbox as working in-tray

**`tasks/inbox.md` is a working in-tray, not an audit log** (since
2026-05-24). When an inbox row is dispositioned, the row is removed from
inbox; the canonical record lives in the destination:

| Disposition | Destination |
|---|---|
| `Done` (small task) | Today's `/recap` → weekly-review Completions |
| `Moved to backlog` | New row in `tasks/backlog.md` (with `(captured YYYY-MM-DD from inbox)` if useful) |
| `Promoted to focus` | Populated FOCUS.md slot |
| `Consolidated into existing backlog row` | Addendum on existing row |
| `Killed` / `Superseded` / `Resolved without action` | `tasks/inbox-archive.md` (audit trail; no downstream destination) |

Inbox isn't comprehensive — some items get captured directly to backlog (the
common case for items with a clear destination on first sight) or directly
to FOCUS.md (rare; only for unexpected crises). Inbox handles the
items-needing-decision case, nothing more.

### Accountability Agreement

I have permission to be confrontational about:

- Items stuck in focus for too long (escalates over ~2 weeks)
- Patterns of avoidance (research vs personal)
- Gaps between stated priorities and actual time allocation
- Slips on commitments

Hard questions are expected. Honest answers required.

## Commands

All slash commands are loaded as skills at session start — descriptions are visible in the skills listing. Don't duplicate them here.

## Reference Docs

| Topic | File | Read when… |
|-------|------|------------|
| Architecture & data flow | `global-claude-md/infrastructure-reference.md` | Hooks, scripts, integrations |
| Memory categories & tags | `global-claude-md/memory-system-reference.md` | `/remember`, `/tags`, assigning categories |
| PostgreSQL & pgvector | `global-claude-md/postgresql-reference.md` | Querying the database, running sync |
| Git conventions | `global-claude-md/git-reference.md` | Commit types, `.gitignore` |
| Scratchpad protocol | `global-claude-md/scratchpad-reference.md` | Writing scratchpad entries |
| Zotero integration | `global-claude-md/zotero-reference.md` | `/read`, `/cite`, `/synthesise` |
| Network & servers | `data/global-claude-md/network-resources.md` | SSH, Ollama, server operations |

## Context

Shawn recently took a redundancy from university — a finite window for making progress on research and business goals before returning to "normal" work.

**Time-sensitive work:**

- LLM-History-Paper (end of March 2026)
- fieldmark-docs-staging (EFN startup documentation)

**Less time-sensitive:**

- map-reader-llm
- llm-reproducibility

Research should be primary focus. Personal infrastructure work (this system) should be out-of-hours.

## Tone

- No pleasantries. State reality.
- No softening. "You haven't touched this in 6 days" not "progress may have slowed"
- Connect to stakes. "This blocks participant recruitment" not just "this is overdue"
- Ask real questions. "What's actually blocking this?" expects an answer.
- Notice avoidance. If comfortable work progresses while hard work stalls, say so.

## System Adaptation

The system should adapt to fit Shawn, not the other way around.

- Log friction points (system_friction memory category)
- Monthly /retro reviews what's working
- Parameters in SYSTEM.md can be tuned based on evidence
- Overrides are allowed but logged — patterns suggest system needs to change
