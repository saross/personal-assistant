---
title: "repo-standardise — skill spec (repo reorg + layout standardisation)"
tags: [infrastructure, coding-practices, skills]
created: 2026-06-10
updated: 2026-06-10
status: spec — derived from the paper-b worked example; not yet implemented
---

# `/repo-standardise` — skill spec

**Purpose:** bring any repo in the portfolio to the canonical layout — four-artefact wiki
(`wiki/{index,continuity,working-notes,user-observations}.md` + `reflections/` + `planning/`)
plus role-true top-level directories (`scripts/`, `sources/` or `data/`, `outputs/`,
`archive/`, workspace dirs) — separating plans, outputs, sources, code, and archive.

**Provenance:** specced 2026-06-10 from the paper-b reorg
(worked example: `~/Code/2026-mq-llm-dh-judgement-paper-b/wiki/planning/repo-reorg-proposal-2026-06-10.md`).
Generalises Task B in llm-reproducibility's `wiki/continuity.md` and the 2026-05-28 five-repo
relocation work item (paper-b, inscriptions, LLM-History-Paper, llm-reproducibility,
map-reader-llm).

---

## 1. Design reflections from the worked example

These are the decisions that generalise; the skill encodes them as rules.

1. **Classify by role, not by directory name.** The failure mode being corrected is
   *accretion*: `planning/` accumulates outputs because plans produce outputs and nobody
   moves them; continuity beacons get prepended to whatever doc the last session touched.
   The unit of analysis is the file (or coherent subtree), classified into roles:
   *manuscript/deliverable, workspace, source/input, output/derived, plan (live), plan
   (completed), governance/coordination, code, wiki artefact, archive candidate*.
2. **Liveness audit before anything moves.** For every plan/status doc: completed,
   superseded, or live? Evidence = status headers, git log dates, and whether the thing it
   plans now exists (e.g. a "tables backup" is dead once the tables exist in the workspace).
   In paper-b, 5/5 top-level planning docs were dead — typical, and the reason the audit
   pays for itself.
3. **Reference graph before move plan.** `git grep` every candidate path; classify each
   referencing file as **live** (code, READMEs, active indexes → update) or **historical**
   (session logs, completed plans → never rewrite; rewriting history-of-record docs
   falsifies provenance). In paper-b only 2 code files + .gitignore + 3 live docs needed
   updates; dozens of historical references were left alone.
4. **Path concordance table is mandatory.** A committed old→new map in `wiki/index.md`
   resolves every stale reference forever, and is what makes rule 3's "don't rewrite
   history" safe. Cheap to produce at reorg time, impossible to reconstruct later.
5. **Find the de-facto continuity beacon.** Un-migrated repos hide cross-session state in
   odd places ("START HERE" sections, pause notes, README warnings). Extraction into
   `wiki/continuity.md` is part of the migration, with a pointer left at the old site.
6. **Gitignored content needs `mv`, not `git mv`** — and ignore rules must move in the same
   commit as their targets so every commit leaves a consistent tree (paper-b: the
   copyrighted `_work/` page cache).
7. **Protected paths are absolute.** Submodules, anything synced to an external service
   (Overleaf, published symlinks), and other-session worktrees are never touched. Detect via
   `.gitmodules` + per-repo config; refuse rather than guess.
8. **Move-only discipline.** No content edits during a reorg (beacon extraction is
   cut-and-paste). Content fixes are separate commits/sessions — keeps the diff reviewable
   and `git log --follow` clean.
9. **Verification is a gate, not a hope.** Builds/tests that exist must pass; a final
   `git grep` for old paths must hit only `archive/` and the concordance; spot-check
   `--follow` history on moved files.
10. **Human gate between proposal and execution.** Layout taste (D-style decision points:
    consolidate vs minimal, archive vs keep) is the user's call. The skill's proposer output
    is a decision-point list, not a fait accompli.

## 2. Skill shape

**Form:** a skill (`SKILL.md`), not a standalone agent — it runs in-session with the user
available for the gate. Internally it MAY dispatch read-only survey subagents (Explore) for
large repos. A proposer/verifier split (per lit-scout / data-profile pattern) applies at the
verification phase: the verifier re-greps and re-checks moves in a fresh context.

**Name:** `repo-standardise` (UK spelling). Trigger phrases: "standardise this repo",
"reorganise the repo", "migrate to the wiki layout", "/repo-standardise".

**Phases:**

- **Phase 0 — preflight.** Clean working tree required; `0 behind` upstream; enumerate
  protected paths (`.gitmodules`, external-sync markers, per-repo `CLAUDE.md` constraints);
  detect collaborative-repo gating (branch+PR mandatory there).
- **Phase 1 — survey.** Inventory (tracked vs untracked vs ignored); directory sizes; README
  vs reality drift; locate wiki artefacts (current vs legacy layout); locate de-facto
  continuity beacons.
- **Phase 2 — classify.** Role classification table (rule 1) + liveness audit (rule 2) +
  reference graph (rule 3). Every checkable claim anchored (file:line, commit hash) per the
  anti-confabulation write-side rule.
- **Phase 3 — propose. STOP.** Write the proposal to `wiki/planning/repo-reorg-proposal-
  <date>.md` (this seeds `wiki/` if absent — established seed pattern). Decision points
  listed explicitly. Await the user's calls.
- **Phase 4 — execute.** Branch per D-decision; `git mv` batched into logical commits
  (wiki migration → outputs split → archive sweep → consolidation → code relocation →
  documentation); ignore-rule and path-constant updates ride in the same commit as their
  moves; concordance table written into `wiki/index.md`.
- **Phase 5 — verify.** Builds/tests; old-path grep; `--follow` spot-checks; ignored-path
  re-check. Verifier subagent re-runs these from a fresh context. Fail → fix before PR/push.
- **Phase 6 — document + close.** README rewrite; `archive/README.md`; continuity entry;
  commit/push per repo convention; offer `/handoff`-style summary.

## 3. Parameters

| Parameter | Default | Notes |
|---|---|---|
| repo path | cwd | |
| layout reference | `~/personal-assistant/wiki/index.md` ("PA project layer") | the canonical spec |
| protected paths | auto (`.gitmodules`) + user-supplied | Overleaf submodules, published symlinks |
| consolidation appetite | ask (minimal vs thoroughgoing) | maps to D-style decision points |
| branch policy | global git rules; branch+PR for large/collaborative | |
| archive policy | archive-don't-delete, categorical subdirs | global convention; throwaway temp files exempt |

## 4. Out of scope (v1)

- Content rewrites, frontmatter backfill on migrated pages beyond the four artefacts, and
  tag-vocabulary application — flag as follow-ups, don't do inline.
- Cross-repo orchestration (run per-repo; the five-repo backlog is five invocations).
- Non-git directories.

## 5. Open questions

- Should Phase 5's verifier be a formal subagent definition (like `data-profile-verifier`)
  or an inline checklist? Lean: inline for v1; promote if reorgs recur beyond the backlog.
- Does the skill also *maintain* (detect drift on already-migrated repos, e.g. outputs
  creeping back into `wiki/planning/`)? Lean: yes later — a cheap "drift check" mode reusing
  Phases 1–2 only.
- Home for the implemented skill: `~/.claude/skills/repo-standardise/` with promotion via
  `published/` Pattern A if it proves out.
