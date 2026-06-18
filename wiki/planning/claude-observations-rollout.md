---
title: "Claude Observations — design + cross-repo rollout"
tags: [planning, infrastructure, reflection]
created: 2026-06-18
updated: 2026-06-18
status: design-approved
---

# Claude Observations — design + cross-repo rollout

**Status:** design approved 2026-06-18 (Shawn). Doc live in personal-assistant
(`wiki/claude-observations.md`, seeded with Obs 1–3). Cross-repo build-out
**pending — out-of-hours** (not to eat the pre-Europe paper sprint).

## What

A **Claude-owned** register of "how we work together" observations, with
**default-keep** semantics — the symmetric counterpart to
`user-observations.md`, but these persist by default rather than awaiting
Shawn's accept/discard. See the PA instance header for full semantics.

## Why (history — so we don't re-make the old mistake)

An "LLM observations" doc existed early and was deprecated ~2026-03-15 because,
*in the LLM-research repos*, observations about the LLM-as-data blurred with
collaboration observations when both lived in `working-notes.md` (memory trail:
"LLM observations and working notes create categorical ambiguity… blurs
finding/collaboration boundary in LLM research projects"). Shawn's diagnosis
(2026-06-18): **the problem was the mixing, not the notes.** Sequestered in
their own document, these are safe — including in the research repos.

## Design (agreed 2026-06-18)

- **Default-keep** — not gated on Shawn's acceptance; he may read, respond, or prune.
- **Bidirectional** — `[me]` how I should work with Shawn; `[you]` how Shawn
  could work with me (critical-friend critique of prompting, missed
  automation/leverage, larger-picture critique of the *shape* of our
  interaction — explicitly invited by Shawn); `[shape]` structural/session-level.
- **Boundary rule** — claude-observations = collaboration dynamics;
  `working-notes.md` = artefacts/system/research findings;
  `reflections/session-reflection.md` = narrative texture of a session.
- **Format** — numbered, dated entries; summary line + body + subject tag.

## Rollout (pending, out-of-hours)

1. **Seed `claude-observations.md`** (or the repo's reflections-equivalent) in
   each active repo: paper-b, inscriptions, map-reader-llm,
   fieldmark-docs-staging, llm-history-paper, voice-assistant,
   llm-reproducibility. Use the PA header as the template.
2. **Skill plumbing (global skills — edit carefully):**
   - `/handoff` step 4: split the single observation step into (a)
     *user*-observation candidates (gated, as now) and (b) *claude*-observations
     (default-keep, written directly).
   - `/reflect`: add a step to append claude-observations (Shawn: "triggered
     either by handoff or reflect").
3. **Curation destination:** `user-observations.md` is supposed to feed
   `notes/working-with-claude.md` — which **does not exist yet**. Decide whether
   claude-observations feed the same curated note or stay standalone.

## Open questions

- Both `/handoff` and `/reflect` as triggers, or split roles (handoff drafts,
  reflect curates)?
- One register per repo, or a cross-repo aggregate at curation time?
- Create `notes/working-with-claude.md` now (the user-observations curation
  target is also missing), or defer until there's volume to curate?
