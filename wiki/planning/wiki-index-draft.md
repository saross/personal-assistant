# Draft sketch: `wiki/index.md`

**Status:** design draft, not yet landed. This file sketches the top-level
wiki index that will be created during the pilot wiki migration (see
`continuity.md` workstream D, task "Pilot wiki migration on personal-assistant").

**At migration time:** the body of this file becomes `wiki/index.md`,
absorbing the tag vocabulary from `notes/_tags.md` in the process. This
draft stays in `planning/` as a record of the design pass, or moves to
`archive/planning/` once superseded.

The sketch is wrapped in a fenced block so the draft `index.md` text is
unambiguous and not parsed as headings of *this* planning doc.

---

```markdown
---
title: "Personal-assistant wiki — index"
tags: [index]
created: <migration-date>
updated: <migration-date>
status: seed
---

# Personal-Assistant Wiki

This wiki plays two roles, both hosted in one directory tree:

1. **PA project wiki** — design, documentation, and process artefacts
   for the personal-assistant system itself.
2. **Cross-project wiki** — curated knowledge, prompt patterns, and
   reference material that recurs across all of Shawn's projects.

The two layers share a directory because personal-assistant *is* the
cross-project hub. The sections below separate them.

## Ritual moments

Two automatic moments knit the wiki to the rest of the system:

- **`/handoff`** (per session-close, in a project) — updates continuity,
  captures observations, flags wiki-page candidates to `_inbox.md`,
  drafts user-observations, commits and pushes. Protocol:
  [`global-claude-md/handoff-protocol.md`](../global-claude-md/handoff-protocol.md).
- **`/weekly-review`** (cross-project, weekly) — clusters fresh memories
  and inbox candidates into draft wiki-page diffs for review.

A third ritual is implicit: **session-start** silently reads continuity
and de-weights the recall dump. Protocol:
[`global-claude-md/session-start-protocol.md`](../global-claude-md/session-start-protocol.md).

---

## PA project layer

| Artefact | Path | Job |
|---|---|---|
| Continuity | [continuity.md](continuity.md) | Cross-session state; the load-bearing handoff document |
| Working notes | [working-notes.md](working-notes.md) | Chronological observation log |
| Reflections | [reflections/](reflections/) | Structured periodic reflections |
| User observations | [user-observations.md](user-observations.md) | Curated meta-observations about how we work together |
| Planning | [planning/](planning/) | Design docs, implementation plans, audits |
| Documentation | [docs/](docs/) | System and infrastructure documentation |

## Cross-project layer

| Sub-collection | Path | Index | Job |
|---|---|---|---|
| Notes | [notes/](notes/) | [notes/index.md](notes/index.md) | Dated-entry topical pages — recurring lessons across projects |
| Grimoire | [grimoire/](grimoire/) | [grimoire/README.md](grimoire/README.md) | Curated prompt patterns and incantations |
| *(future)* Bibliographies | `bibliographies/` | — | Cross-project lit-search outputs not bound to a single project |
| *(future)* Agents | `agents/` | — | Subagent design, briefing templates, evaluation notes |
| *(future)* Skills | `skills/` | — | Slash-command skill design, deployment patterns |
| *(future)* CLAUDE.md | `claude-md/` | — | CLAUDE.md design patterns, models, glosses |
| *(future)* Scratchpads | `scratchpads/` | — | Scratchpad protocols and templates |
| *(future)* Templates | `templates/` | — | Project starter templates, notebook designs |
| *(future)* Glossary | `glossary/` | — | Cross-project terminology |

## Staging

- [`_inbox.md`](_inbox.md) — wiki-page candidates flagged at `/handoff`
  time. Processed at `/weekly-review` curation.

---

## Tag vocabulary

24 tags across four groupings. Apply 2–4 per page via frontmatter:

```yaml
---
tags: [llm-craft, anti-confabulation, audit-pattern]
---
```

### Craft scaffolding (artefact kinds — 8)

`prompts`, `agents`, `skills`, `hooks`, `claude-md`, `scratchpad`,
`memory-system`, `index`.

### Failure modes and mitigation patterns (5)

`anti-confabulation`, `anti-satisficing`, `audit-pattern`,
`bidirectional-verification`, `provenance`.

### Domain / topic areas (6)

`llm-craft`, `working-practices`, `coding-practices`,
`research-methodology`, `open-science`, `teaching`.

### Cross-cutting themes (5)

`session-shape`, `human-ai-collaboration`, `three-Ps`, `memory-systems`,
`paper-seed`.

**Full definitions and usage notes:** (the body of `notes/_tags.md`,
lifted into this section at migration time.)

---

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

- `status` defaults to `seed`; promote to `active` once the page has
  been used in anger, `stable` once it's settled, `archive` when it's
  retired (don't delete).

### Filename rules

- Lowercase-with-hyphens, `.md`.
- No dates in filenames — dates live in entry headings or frontmatter.
- Exceptions: convention-mandated uppercase (`README.md`); leading
  underscore for non-page files (`_inbox.md`, `_tags.md`).

### Page conventions per sub-collection

Each sub-collection's index documents its own conventions (dated-entry
format for notes, table-of-contents for grimoire, etc.). The
frontmatter shape and tag vocabulary are wiki-wide; everything else is
local.

### What does NOT live here

- Source code, data files, tests — these stay outside `wiki/` in the
  project root.
- Memory candidate pool — that's the JSONL corpus + `/recall`.
- Per-project artefacts of *other* projects — those live in
  `<other-project>/wiki/`. This wiki only hosts personal-assistant's
  own project layer plus cross-project resources.

---

## Open structural questions

- When `bibliographies/` should split out from `notes/` (probably after
  3–5 cross-project lit-searches accumulate).
- Whether sub-collections like `claude-md/` should index via
  `index.md` or `README.md` — currently grimoire uses README; new
  collections default to `index.md` unless there's a reason.
- Auto-loading at session-start: post-Vector-2, this file's "PA project
  layer" + "Cross-project layer" + tag vocabulary form the natural
  ~4 KB digest. Until then, consult on demand.
```

---

## Notes for the migration

- The body above is the canonical sketch. Migration steps that touch it:
  1. Create `wiki/` directory.
  2. Move `planning/`, `docs/`, `continuity.md`, `working-notes.md`,
     `reflections/`, `user-observations.md` into `wiki/`.
  3. **Do NOT move `notes/` or `grimoire/` into `wiki/`.** They are the
     **private** working area (`data` submodule) and stay there so prompts
     can be curated/de-risked before sharing. Public sharing is positive-
     action promotion to `published/` (Pattern B copies for grimoire; see
     `published/README.md`), never wholesale relocation into the public
     `wiki/`. The public `wiki/index.md` links to them where they live.
  4. `notes/_inbox.md` and `notes/_tags.md`: per-file privacy review needed.
     `_inbox.md` holds in-progress project candidates → likely stays private
     in `data/`. `_tags.md` (the curated tag vocabulary) is innocuous → may
     lift into the public `wiki/index.md` "Tag vocabulary" section. Decide
     at migration time; do not blanket-move.
  5. Update `notes/index.md` to drop the "How this layer fits" section
     (covered by `wiki/index.md`), keep page list + conventions +
     what-doesn't-live-here.
  6. Update `global-claude-md/handoff-protocol.md` `_inbox.md` references
     only if `_inbox.md` actually moves (per step 4 it likely stays at
     `notes/_inbox.md` in `data/`).
  7. Update `wiki/continuity.md` workstream-D status and reference paths
     (continuity.md itself moved planning/ → wiki/ on 2026-05-28).
  8. Update slash commands that reference `notes/` paths (audit needed:
     `/craft`, `/observe`, others).
  9. Run a repo-wide grep for `notes/` and `planning/` references; fix.
- Resolve lit-scout file destinations per `continuity.md` (table
  recorded during 2026-05-18 session): bibs to projects, evaluations to
  `wiki/docs/lit-scout-evaluations/`, magnetometer (v4.3) archived.
- Move `general/2026-03-15-persona-affordance...md` to
  `map-reader-llm/wiki/` and `paper-b-working-notes.md` +
  `lit-scout-case-study.md` to the Paper B project wiki.

## Relocating misplaced working-notes.md files (added 2026-05-28)

A cleanup task spanning several repos (not a single shared file —
`working-notes.md` is always **per project**). In each repo, `working-notes.md`
is the **research-notes** layer and must sit at `wiki/working-notes.md` (new) or
`docs/notes/working-notes.md` (legacy — a *sibling* of `reflections/`), never
*inside* `reflections/` (that directory is the meta-research layer, owned by
`/reflect`). A historical workaround put it inside `reflections/` as an
end-of-session catch-all; `/handoff` now supersedes that role.

Survey 2026-05-28 (`find` across `~/personal-assistant` + `~/Code/*`):

| Location | Projects |
|---|---|
| `wiki/working-notes.md` (correct, new) | personal-assistant, Groundsite-EFN |
| `docs/notes/reflections/working-notes.md` (**misplaced**) | inscriptions, LLM-History-Paper, llm-reproducibility, map-reader-llm, 2026-mq-…-paper-b |
| `docs/notes/working-notes.md` (correct legacy) | none |

Steps (later — do per project as each adopts the wiki layout, no rush):

1. `git mv` each misplaced `docs/notes/reflections/working-notes.md` →
   `wiki/working-notes.md` (or `docs/notes/working-notes.md` if the project
   isn't on the wiki layout yet). Preserve history.
2. **Fix the root cause:** cc-session-toolkit ships a `working-notes.md`
   template at `src/cc_session_toolkit/data/reflections/working-notes.md`, so
   newly-scaffolded projects keep landing it inside `reflections/`. Move the
   template out of `reflections/` (or stop scaffolding it there) so the
   misplacement stops regenerating.
3. obs-writer / `/observe` / `/reflect` were made layout-aware 2026-05-28
   (obs-writer + observe locate `wiki/` → `docs/notes/` → misplaced
   `reflections/`; `/reflect` excludes working-notes.md from processing), so
   reads/writes keep working throughout the transition.

## Open questions for the migration session

- Order: do PA-project layer first (lower risk; doesn't touch
  cross-project files), or cross-project first (more disruptive but
  unblocks `_tags.md` lift)?
- Slash-command audit: which commands reference `notes/` paths and
  need updating in lockstep?
- Should `grimoire/README.md` be renamed to `grimoire/index.md` for
  consistency with `notes/index.md`? README is a stronger convention;
  index.md is more uniform. (Leaning README.)
