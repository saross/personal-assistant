---
title: "Personal-assistant wiki — index"
tags: [index]
created: 2026-05-28
updated: 2026-05-28
status: seed
---

# Personal-Assistant Wiki

This wiki plays two roles, hosted in one directory tree:

1. **PA project wiki** — the per-project artefacts (continuity, working
   notes, reflections, user observations, design docs) for the
   personal-assistant system itself. Every project gets its own `wiki/`;
   this is PA's.
2. **Cross-project hub** — curated knowledge, prompt patterns, and
   reference material that recurs across *all* of Shawn's projects. This
   layer lives here only because personal-assistant *is* the cross-project
   hub.

The two layers share a directory but are distinct. The sections below
separate them, and the per-project layer is the one that generalises to
every other repo.

## Migration status (2026-05-28)

The PA-project layer is **fully migrated** (2026-05-28): continuity,
working-notes, user-observations, reflections, planning, and docs all live
under `wiki/`; the old repo-root `planning/` and `docs/` are removed. The
cross-project layer stays private in `data/` by design (see below).
Authoritative plan:
[`planning/wiki-index-draft.md`](planning/wiki-index-draft.md); state tracked
in [continuity.md](continuity.md) workstream D.

| Artefact | Target | Where it is now |
|---|---|---|
| `continuity.md` | `wiki/continuity.md` | **moved here 2026-05-28** |
| `working-notes.md` | `wiki/working-notes.md` | **here** (since 2026-05-18) |
| `user-observations.md` | `wiki/user-observations.md` | **here** (since 2026-05-18) |
| `index.md` (this file) | `wiki/index.md` | **here** (2026-05-28) |
| `reflections/` | `wiki/reflections/` | **moved here 2026-05-28** (`/reflect` made layout-aware) |
| Planning | `wiki/planning/` | **moved here 2026-05-28** |
| Documentation | `wiki/docs/` | **moved here 2026-05-28** (`wiki/docs/open-science/`) |
| Cross-project `notes/`, `grimoire/` | stays private in `data/` (by design — see below) | `../notes/`, `../notes/grimoire/` — **private** (`data` submodule) |

**The cross-project layer stays private — by design, not indecision.** The
PA-project layer is all public (main repo), but `notes/` + `grimoire/` are
the **private working/scratch area** (symlinked into the `data` submodule),
kept private so prompts and patterns can be curated and de-risked before
sharing. Public sharing is a deliberate per-artefact promotion to
[`../published/`](../published/) — symlinks for public-origin skills/agents
(Pattern A), polished copies for grimoire prompts (Pattern B); see
[`../published/README.md`](../published/README.md). So the cross-project
layer is **not** moved into the public `wiki/`; it stays in `data/` and is
linked from here.

**One exception, decided 2026-05-29:** the tag *vocabulary* itself is
innocuous and now lives in this file (see [Tag vocabulary](#tag-vocabulary)
below) as its canonical home. `_inbox.md` and all `notes/`/`grimoire/`
*content* stay private.

## Ritual moments

Three moments knit the wiki to the rest of the system:

- **`/handoff`** (per session-close, in a project) — updates continuity,
  captures observations to `working-notes.md`, flags wiki-page candidates,
  drafts user-observations, commits and pushes. Protocol:
  [`../global-claude-md/handoff-protocol.md`](../global-claude-md/handoff-protocol.md).
- **`/weekly-review`** (cross-project, weekly) — *(planned)* clusters fresh
  memories and inbox candidates into draft wiki-page diffs for review.
- **session-start** (implicit) — reads `wiki/continuity.md` (falling back to
  the legacy `planning/continuity.md` in unmigrated projects) and de-weights
  the recall dump. Protocol:
  [`../global-claude-md/session-start-protocol.md`](../global-claude-md/session-start-protocol.md).

## PA project layer

The per-project artefacts. This shape is what every other repo's `wiki/`
should look like (minus the cross-project layer below).

| Artefact | Path | Job |
|---|---|---|
| Continuity | [continuity.md](continuity.md) | Cross-session state for *this* project; the load-bearing handoff document |
| Working notes | [working-notes.md](working-notes.md) | Research notes — empirical, chronological lab notebook (`/observe`, `/handoff`) |
| Reflections | [`reflections/`](reflections/) | Meta-research — session reflection, abductive-reasoning, session log (`/reflect`; research repos only) |
| User observations | [user-observations.md](user-observations.md) | Curated meta-observations about how we work together |
| Planning | [`planning/`](planning/) | Design docs, implementation plans, audits |
| Documentation | [`docs/`](docs/) | System and infrastructure documentation |

`working-notes.md` (research record) and `reflections/` (meta-research on
how the work and the collaboration unfold) are **separate layers with
separate owners** — never write Observations into reflection documents, and
never reflect into working-notes.

## Cross-project layer

Curated knowledge that recurs across projects. **Private by decision
(2026-05-29)** — the notes pages, grimoire, and `_inbox.md` live in the
`data` submodule, reached via the repo-root symlinks, and stay there. Only
the tag vocabulary was lifted out into this file (below).

| Sub-collection | Path | Index | Job |
|---|---|---|---|
| Notes | [`../notes/`](../notes/) | [`../notes/index.md`](../notes/index.md) | Dated-entry **topical** pages — recurring lessons across projects (distinct from any one project's chronological working notes) |
| Grimoire | [`../notes/grimoire/`](../notes/grimoire/) | [`../notes/grimoire/README.md`](../notes/grimoire/README.md) | Curated prompt patterns and incantations |

## Tag vocabulary

A hand-curated, cross-collection tag vocabulary applies to all wiki pages —
apply **2–4 per page** via frontmatter. This file is its **canonical home**
(lifted from the private `notes/_tags.md` on 2026-05-29; that file is now a
redirect stub). Deliberately separate from the noisier auto-applied
memory-tag vocabulary (~28k tags, mostly singletons); wiki tags are
hand-curated and surface only on pages we have decided to keep.

```yaml
---
tags: [llm-craft, anti-confabulation, audit-pattern]
---
```

**24 tags in four groupings.** (A 2026-05-29 empirical validation —
[`planning/wiki-vocabulary-validation-2026-05-29.md`](planning/wiki-vocabulary-validation-2026-05-29.md)
— recommends ADD `agent-orchestration` + `infrastructure` and MERGE
`memory-systems` → `memory-system`, `three-Ps` → `provenance`; **pending
`/weekly-review` ratification**, so the list below is still the live 24.)

### Craft scaffolding (artefact kinds — 8)

What kind of craft artefact the page is about. Applies across notes,
grimoire, and future scaffolding sub-collections.

- `prompts` — prompt patterns, incantations (grimoire-style)
- `agents` — subagent design, briefing, evaluation
- `skills` — slash-command skills, when to invoke, format
- `hooks` — session lifecycle hooks (session-start, pre-compact, etc.)
- `claude-md` — `CLAUDE.md` design, conventions, what belongs in one
- `scratchpad` — scratchpad protocols, decay, format
- `memory-system` — memory architecture, retrieval, write strategy
- `index` — index-page design, navigation patterns

### Failure modes and mitigation patterns (5)

Cross-cutting craft patterns that recur across artefact kinds.

- `anti-confabulation` — Opus 4.7 fragment-welding, anchor verification, read-side scepticism
- `anti-satisficing` — closing exits in prompts, precision over politeness
- `audit-pattern` — adversarial review, claims inventories, bidirectional checks
- `bidirectional-verification` — cross-checking source ↔ derived artefacts
- `provenance` — RDA IG Three Ps (Prompt, Process, Provenance), RO-Crate

### Domain / topic areas (6)

The intellectual territory a page covers.

- `llm-craft` — practical LLM working knowledge
- `working-practices` — time, focus, session shape
- `coding-practices` — engineering, tooling, debugging
- `research-methodology` — research workflow patterns
- `open-science` — FAIR, RO-Crate, data sharing, RDA work
- `teaching` — pedagogy, class delivery, marking

### Cross-cutting themes (5)

Recurring threads that span domains and artefact kinds.

- `session-shape` — pacing, wind-down, capacity, should-vs-must
- `human-ai-collaboration` — interaction patterns at the relationship level
- `three-Ps` — RDA IG framework (Prompt, Process, Provenance)
- `memory-systems` — collaborative memory architecture and trade-offs
- `paper-seed` — drafts and seeds for academic papers

### Notes on use

- **Multi-axis is fine.** A page can carry tags from any combination of the
  four groupings. `llm-craft + anti-confabulation + audit-pattern` is normal.
- **Descriptive, not categorical.** Tags surface what the page is *about*,
  not which folder it lives in.
- **Adding a tag.** Allowed when an existing tag would obscure rather than
  describe. New tags happen at `/weekly-review` curation time (not in
  arbitrary sessions); record the addition in the History below.
- **Memory-tag overlap.** Some labels overlap with memory-system tags
  (`anti-confabulation`, `memory-systems`). Fine — the vocabularies are
  scoped separately even when they share words.
- **Budget.** Aim for 20–30 total. Current count is 24. Past 30, the list
  does less work; reach for refactor before reaching for more.

### History

- **2026-05-18** — Initial set of 24 tags, drafted during workstream D
  design pass; pre-staged in `notes/_tags.md`.
- **2026-05-29** — Empirical validation against the memory corpus +
  `notes/_inbox.md`
  ([`planning/wiki-vocabulary-validation-2026-05-29.md`](planning/wiki-vocabulary-validation-2026-05-29.md);
  re-runnable via `scripts/analyse-wiki-vocabulary.py`). Recommended delta
  pending `/weekly-review` ratification (see note above).
- **2026-05-29** — Vocabulary lifted from the private `notes/_tags.md` to
  this file as its canonical home; `_tags.md` reduced to a redirect stub.

## Conventions

### Frontmatter shape

Every wiki page carries:

```yaml
---
title: "Page Title"
tags: [tag-1, tag-2, tag-3]
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: seed | active | stable | archive
---
```

`status` defaults to `seed`; promote to `active` once used in anger,
`stable` once settled, `archive` when retired (do not delete).

### Filename rules

- Lowercase-with-hyphens, `.md`.
- No dates in filenames — dates live in entry headings or frontmatter.
- Exceptions: convention-mandated uppercase (`README.md`); leading
  underscore for non-page files (`_inbox.md`, `_tags.md`).

### What does NOT live here

- Source code, data files, tests — these stay outside `wiki/`.
- The memory candidate pool — that is the JSONL corpus plus `/recall`.
- Per-project artefacts of *other* projects — those live in
  `<other-project>/wiki/`. This wiki hosts personal-assistant's own project
  layer plus the cross-project resources.
