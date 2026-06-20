---
title: "Claude Observations — design + cross-repo rollout"
tags: [planning, infrastructure, reflection]
created: 2026-06-18
updated: 2026-06-20
status: plumbing-built; active repos seeded
---

# Claude Observations — design + cross-repo rollout

**Status:** design approved 2026-06-18 (Shawn); **skill plumbing built +
active repos seeded 2026-06-20.** Doc live in personal-assistant
(`wiki/claude-observations.md`, Obs 1–6). `/handoff` §4 and `/reflect` now
route observations by observer (see "Rollout" below). Dormant / infra-less
repos deferred until active.

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

## Rollout — built 2026-06-20

1. **Seed `claude-observations.md`** in each active repo. **Done (active +
   infra-ready):** `inscriptions` (`docs/notes/`, pre-existing 2026-06-20,
   left as-is), `paper-b` (`wiki/`), `map-reader-llm` (`docs/notes/`),
   `LLM-History-Paper` (`docs/notes/`). Seed = header + observer-axis table,
   no entries (the inscriptions instance was used as the concrete per-repo
   template — the matured rendering of the PA header). Placement convention:
   *beside* the reflections set, never inside `reflections/`.
   **Deferred (no reflections infra / dormant / mid-migration):**
   `fieldmark-docs-staging`, `voice-assistant`, `llm-reproducibility` —
   seed when each is next active.
2. **Skill plumbing (global skills).** **Done:**
   - `global-claude-md/handoff-protocol.md` §4 split into **4a**
     user-observations (gated candidates, as before) and **4b**
     claude-observations (default-keep, written directly). `commands/handoff.md`
     refinement updated to match.
   - `skills/reflect/SKILL.md` gained a "Claude-observations" step that writes
     claude-obs directly after the reflection docs.
   - **Symmetric dedup guard** in both: *either ritual may run first*; the
     second detects today's entries and augments rather than duplicating.
3. **Curation destination.** **Done:** created
   `notes/working-with-claude.md` as **one shared stub** — the single curated
   destination for *both* registers, populated at `/weekly-review` / `/retro`.

## Open questions — resolved 2026-06-20

- **Triggers / roles** → *both* `/handoff` and `/reflect` write claude-obs
  directly (no propose-review gate; write liberally), with a symmetric guard
  because Shawn habitually runs `/reflect` first — either may run first.
- **Per-repo vs aggregate** → *per-repo register* (the established pattern);
  cross-repo aggregation happens only at curation time, into
  `notes/working-with-claude.md`. No aggregation plumbing built (no volume yet).
- **Create `notes/working-with-claude.md` now** → *yes*, as one shared stub
  (it was a dangling pointer named by ~5 register files). Stays empty until a
  curation pass has volume to lift.
