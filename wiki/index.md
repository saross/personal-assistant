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

The four-artefact reorg is **in progress**. Authoritative plan:
[`../planning/wiki-index-draft.md`](../planning/wiki-index-draft.md);
state tracked in [continuity.md](continuity.md) workstream D.

| Artefact | Target | Where it is now |
|---|---|---|
| `continuity.md` | `wiki/continuity.md` | **moved here 2026-05-28** |
| `working-notes.md` | `wiki/working-notes.md` | **here** (since 2026-05-18) |
| `user-observations.md` | `wiki/user-observations.md` | **here** (since 2026-05-18) |
| `index.md` (this file) | `wiki/index.md` | **here** (2026-05-28) |
| `reflections/` | `wiki/reflections/` | still at `../docs/notes/reflections/` |
| Planning | `wiki/planning/` | still at `../planning/` |
| Documentation | `wiki/docs/` | still at `../docs/` |
| Cross-project `notes/`, `grimoire/` | *(undecided)* | `../notes/`, `../notes/grimoire/` — **private** (`data` submodule) |

**Open decision blocking the cross-project move:** the PA-project layer is
all public (main repo), but `notes/` + `grimoire/` are private (symlinked
into the `data` submodule). Moving them into a public `wiki/` would expose
private content. The cross-project layer therefore stays in `data/` until
the public/private boundary is decided.

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
| Reflections | [`../docs/notes/reflections/`](../docs/notes/reflections/) | Meta-research — session reflection, abductive-reasoning, session log (`/reflect`; research repos only) |
| User observations | [user-observations.md](user-observations.md) | Curated meta-observations about how we work together |
| Planning | [`../planning/`](../planning/) | Design docs, implementation plans, audits |
| Documentation | [`../docs/`](../docs/) | System and infrastructure documentation |

`working-notes.md` (research record) and `reflections/` (meta-research on
how the work and the collaboration unfold) are **separate layers with
separate owners** — never write Observations into reflection documents, and
never reflect into working-notes.

## Cross-project layer

Curated knowledge that recurs across projects. **Currently private** — lives
in the `data` submodule, reached via the repo-root symlinks. Stays there
pending the public/private decision noted above.

| Sub-collection | Path | Index | Job |
|---|---|---|---|
| Notes | [`../notes/`](../notes/) | [`../notes/index.md`](../notes/index.md) | Dated-entry **topical** pages — recurring lessons across projects (distinct from any one project's chronological working notes) |
| Grimoire | [`../notes/grimoire/`](../notes/grimoire/) | [`../notes/grimoire/README.md`](../notes/grimoire/README.md) | Curated prompt patterns and incantations |

## Tag vocabulary

A hand-curated, cross-collection tag vocabulary (24 tags in four groupings)
applies to all wiki pages — apply 2–4 per page via frontmatter. The
vocabulary currently lives at [`../notes/_tags.md`](../notes/_tags.md); it
lifts up into this file as the top-level reference when the cross-project
layer migrates.

```yaml
---
tags: [llm-craft, anti-confabulation, audit-pattern]
---
```

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
