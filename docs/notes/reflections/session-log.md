---
priority: 5
scope: always
title: "Session Log"
audience: "researchers and future instances"
---

# Session Log — personal-assistant

Factual record of substantive sessions in the `personal-assistant`
project: what was done, decided, and produced. Summarise, don't
reflect — that's what session-reflection.md is for.

Each entry should be scannable: scope, major outputs, key decisions,
and any contextual assumptions that were load-bearing at the time
but may not be obvious from the git history.

Entries are numbered sequentially across sessions and dated.


## Entry 1 — 2026-04-16 (Thu afternoon) → 2026-04-18 (Sat morning)

### Scope

Two-day CC/Agent upskilling tutorial (Slot 3 focus, deadline Fri
2026-04-17) spanning three session instances: Thu evening (Day 1),
Fri (Day 2 + Paper B test runs), and Sat morning (catch-up recap +
/review + /reflect). Continuity via SessionStart resume hooks; the
work formed one arc despite three distinct session boundaries.

### Major outputs

**New agents (canonical in `agents/`, symlinked from `~/.claude/agents/`):**

- `lit-scout.md` — academic literature discovery agent; iterated v1 →
  v2 in response to a confabulation failure (see entry 1 in
  `abductive-reasoning.md`); v2 adds mandatory metadata-verification
  phase and adversarial-verifier sub-agent
- `lit-scout-verifier.md` — adversarial verifier in fresh context
  window, borrowed from map-reader-llm proposer-verifier pattern
- `prior-art-scout.md` — existing-implementation discovery agent
  (GitHub, GitLab, PyPI, HF, Stack Overflow, methodology lit)

**New helper script:**

- `scripts/lit-search.py` (~800 lines, 51 passing tests) — CrossRef /
  Semantic Scholar / OpenAlex CLI with 5 subcommands (metadata,
  references, citations, search, openalex-cited-by) plus `bibtex`
  via CrossRef content negotiation

**Infrastructure refactors:**

- Agent-organisation refactor: `agents/` canonical + symlinks, matches
  existing skills pattern
- `published/` convention established — curation layer for external
  readers (not an access gate); two patterns documented in the README
  (symlinks for public-origin content, canonical copies for
  private-origin like grimoire promotions)
- `setup.sh` expanded from 7 steps to 8 to create agent symlinks

**Planning / backlog:**

- `planning/lit-scout-improvements.md` (resilience + v1-audit deferrals)
- `planning/llm-reproducibility-headless-pipeline.md` (25-paper batch
  via `claude -p` shell scripts)
- `planning/dh-tools-monitoring-routine.md` (weekly scheduled routine
  for longitudinal DH tool ecosystem observation)
- `planning/llm-history-paper-split-execution.md` (A1-A3 then B0-B4
  task decomposition, including B0 Overleaf submodule setup)
- Four new backlog rows (the three above + persona-elicitation +
  workshop-repo)

**Research source material:**

- `data/notes/paper-b-working-notes.md` (first entry: the confabulation
  finding + methodological implication for Paper B's "researchers'
  workbench" contribution)
- `data/notes/lit-scout-case-study.md` (~4,500-word source for the
  paper's case-study section)
- 7 new entries in `notes/llm-craft.md` (the Day 1-2 tutorial
  learnings)
- `notes/grimoire/subagent-extraction-brief.md` (templated)
- `/tmp/paper-b-lit-scout-20260417.bib` (28 verified BibTeX entries
  for Paper B from the v2 run)

**Meta outputs (Sat catch-up):**

- `reports/weekly/2026-W16.md` + three collaborator reports
- `standups/2026-04-17.md` (Friday recap as catch-up, since no
  morning standup ran)
- Progress memory for Friday (8h, three projects)

### Key decisions

- **Proposer-verifier architecture for lit-scout.** Not "write a
  better prompt"; the fix is structural. Independent context window
  cannot share the proposer's narrative memory, which is what the
  same-context self-check could not escape.
- **`published/` as curation signal, not access gate.** Everything in
  the repo is already public; `published/` marks the polished subset
  worth pointing external readers at.
- **Commands intentionally not published.** Too entangled with the
  task system to externalise as symlinks. Revisit if a command ever
  warrants generalisation.
- **Task-sized focus slots (new convention, `tasks/SYSTEM.md`).**
  Slots hold tasks of 1h-1wk, not open-ended project framings.
  Days-in-focus counts against the current task; the project tag
  groups tasks. Motivated by the 2026-W16 review finding: Slot 1 was
  tracking as "day 18" while the current task had already rotated
  through three real milestones. Prompted by user feedback on the
  review's "approaching abandon threshold" framing.
- **Weekend-planning convention.** Tasks queued Sat/Sun start the
  clock Monday. Reviews happen Fri/Sat; the clock shouldn't penalise
  that rhythm.
- **Workshop / exploratory-infrastructure repo deferred** (added to
  backlog with rationale). The decision is *yes, but not immediately*
  — we'll see what the Latin inscriptions SPA work on Monday reveals
  before committing to the extra repo.

### Contextual assumptions

- **CC Max plan**, unlimited subscription-level usage — cost not a
  constraint for the proposer-verifier overhead (verifier roughly
  doubles metadata-call volume per invocation) or for parallel
  subagent experimentation.
- **Paper B has no repo yet** (task B0 in the split-execution plan);
  all Paper B material currently lives in `data/notes/` as private
  draft-level content.
- **Network was intermittent** during the Fri Paper B v2 run — a LAN
  drop mid-run lost ~10 minutes of prose output, although the
  BibTeX file (written to disk before the drop) survived. This shaped
  the "resilience gap" item in lit-scout-improvements.md.
- **Working machine**: zbook-ubuntu throughout.
- **One audit-subagent failure mode** encountered: when plan mode was
  still active from earlier, background subagents inherited the
  read-only restriction and produced "here is the plan" outputs
  rather than executing edits. Fix was to exit plan mode; subagents
  then executed normally. Noted in scratchpad as a pattern.

