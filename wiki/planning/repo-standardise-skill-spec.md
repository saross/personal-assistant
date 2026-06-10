---
title: "repo-standardise — skill spec (repo reorg + layout standardisation)"
tags: [infrastructure, coding-practices, skills]
created: 2026-06-10
updated: 2026-06-10
status: spec v2 — generalised from a 30-repo survey of ~/Code (2026-06-10); not yet implemented
---

# `/repo-standardise` — skill spec (v2)

**Purpose:** bring any repo in the portfolio to the canonical layout — four-artefact wiki
(`wiki/{index,continuity,working-notes,user-observations}.md` + `reflections/` + `planning/`)
plus role-true top-level directories (`scripts/`, `sources/` or `data/`, `outputs/`,
`archive/`, workspace dirs) — separating plans, outputs, sources, code, and archive.

**Provenance:** v1 specced 2026-06-10 from the paper-b reorg (worked example:
`~/Code/2026-mq-llm-dh-judgement-paper-b/wiki/planning/repo-reorg-proposal-2026-06-10.md`).
v2 same day, generalised from a sweep of all 31 git repos under `~/Code/` (method: per-repo
profile of layout markers, planning/ contents and liveness, tracked junk and heft, README
drift, beacon census — each count below re-verifiable by the stated command in the named
repo). Generalises Task B in llm-reproducibility's `wiki/continuity.md` and the 2026-05-28
five-repo relocation work item.

---

## 1. Failure-mode catalogue (empirical, 2026-06-10 survey)

What actually goes wrong, ranked roughly by frequency × severity in the portfolio. The skill's
classification phase tests for each of these explicitly.

### F1 — `planning/` as universal attractor

Present in every active research repo surveyed. `planning/` accretes, by observed sub-species:

| Sub-species | Observed instance (anchor) |
|---|---|
| Research outputs (scout reports, syntheses, reviews) | inscriptions: `planning/lit-scout-*/`, `prior-art-scout-*`, `gemini-statistical-review.md`; paper-b: `planning/section2-grounding/` (3.4 MB) |
| Deliverables | inscriptions: `planning/conference-talk-rac-trac-2026/` (16 MB) |
| Registered, external-facing documents | inscriptions: `planning/osf-amendment-*.{md,pdf}` ×~10, `preregistration-draft.md` |
| Run artefacts / data (JSON, CSV, baselines) | map-reader: `planning/condition-inventory*.json`, `era1-pv-stage-d-*.json`, `nas-migration-baseline-*.txt`; LLM-History-Paper: `planning/split/extraction-*.json` |
| Executable code | map-reader: `planning/run-phase3a-recovery.sh{,.template}` |
| Manuscript fragments | LLM-History-Paper: `planning/TODO.tex`, `SAR-*.tex`, `*-insertions-final.md` |
| Correspondence / consultation packs | inscriptions: `planning/martin-*.md` ×4 |
| Governance docs that belong in wiki/ | inscriptions: `planning/decision-log.md`, `research-intent.md` |
| Continuity beacons (see F2) | all of: inscriptions, map-reader, LLM-History-Paper, paper-b |
| Dated snapshot files never superseded in place | inscriptions: `backlog-2026-04-22.md` + `backlog-2026-05-03.md` |

Root cause: plans *produce* outputs, and the output lands beside the plan. The fix is the
outputs split + archive sweep; prevention is the cc-session-toolkit template fix (§7).

### F2 — continuity-beacon sprawl (plural, dated, scattered)

paper-b's single misplaced START-HERE was the *mild* case. Observed: four dated
`next-session-prompt-*.md` in inscriptions `planning/` plus a `continuity.md` inside
`docs/notes/reflections/`; three generations of `session-handover*.md` in LLM-History-Paper
`planning/`; `SESSION_HANDOVER.md` at blue-mountains repo root; per-workstream beacons
(`paper-writeup-continuity.md`, `section6-pipeline-continuity.md`). Rule: census all beacons,
reconcile into one `wiki/continuity.md` (latest wins; per-workstream beacons become sections
or linked pages), archive the rest, leave pointers.

### F3 — stalled partial migration

llm-reproducibility holds wiki/ seed + legacy `docs/notes/` + root `planning/`
*simultaneously*; Groundsite-EFN-Planning has `wiki/continuity.md` and nothing else of the
four artefacts. The skill must be **idempotent and resumable**: detect partial state in Phase
1 and finish the migration, never re-seed or duplicate.

### F4 — tracked heft and environment junk

llm-reproducibility tracks its entire venv (2,114 files; `git ls-files | grep -c '^venv/'`);
map-reader tracks 26,979 files including 91 over 5 MB; blue-mountains tracks 17 files over
5 MB; inscriptions `planning/` alone is 19 MB. Reorg ≠ data management: the skill *reports*
heft (a ranked table with `gitignore`/LFS/external-storage/regenerate options) and fixes only
unambiguous junk (bytecode, venv already in .gitignore) — data relocation is its own gated
decision.

### F5 — README missing or drifted

Missing: ANU-HUMN8031-2026, audio-to-text-pipeline, prompts, 2026-mq-llm-dh-ideation-writing,
client-materials. Drifted (README last commit vs repo last commit): cc-session-toolkit
(2026-02-08 vs 2026-05-29), LLM-History-Paper (2026-02-03 vs 2026-05-29), llm-reproducibility
(2025-11-29 vs 2026-06-10), map-reader (2026-02-08 vs 2026-06-10), paper-b (2026-04-24 vs
2026-06-10). Drift is near-universal in active repos; Phase 6 rewrites or creates.

### F6 — naming-standard violations and loose root files

`ETL_Documents/`, `Images_Report/`, `Scoping_Document.md` (Groundsite); `GPT55-*.md`
(inscriptions); `SESSION_HANDOVER.md`, `visualizations/` (blue-mountains); `SHAWN.md`
(map-reader). Loose root .md beyond convention in 8 repos. Renames only in solo repos, always
via concordance; collaborative repos get a flag, not a rename (others' links break).

### F7 — pseudo-archives and missing archives

inequality-modelling's entire content sits in `old/`; several repos have no `archive/` at
all so completed material stays in place (F1). Normalise to `archive/` with categorical
subdirs per the global convention.

### F8 — cross-repo and external reference liability (new protected-path class)

Two observed mechanisms: (a) **cross-repo**: paper-b's `coordination/README.md` hardcodes
refresh-copy paths into LLM-History-Paper's `paper-a-handoff/` — reorganising LLM-History-
Paper would silently break paper-b's refresh protocol; (b) **external**: inscriptions' OSF
amendment PDFs/mds in `planning/` may be link targets from the OSF registration — a moved
path can break a *registered* research record's pointer. Phase 2 must grep sibling repos for
the target repo's path, and treat registered/external-facing artefacts as move-with-extreme-
care (verify nothing external links the in-repo path before moving; otherwise leave a
redirect stub or do not move).

### F9 — the repo already knows

map-reader carries `planning/repo-cleanup-backlog.md`. Existing cleanup backlogs, TODO
files, and `wiki/continuity.md` task lists are **inputs** to Phase 2 — ingest them, don't
rediscover (and mark their items done with dates per the checklist convention).

## 2. Design rules

Rules 1–10 from v1 (paper-b worked example) stand: classify by role not directory name;
liveness audit before moving; live-vs-historical reference split (never rewrite
history-of-record docs); mandatory path concordance in `wiki/index.md`; beacon extraction;
`mv` not `git mv` for ignored content, ignore rules ride the same commit; protected paths
absolute (submodules, external sync); move-only discipline; verification as gate; human gate
between proposal and execution.

v2 additions from the survey:

11. **Beacon reconciliation** (F2): merge plural beacons into one `wiki/continuity.md`,
    dated-latest-wins, per-workstream beacons become sections; archive superseded beacons.
12. **Idempotency** (F3): every phase re-runnable on a half-migrated repo; presence checks,
    never blind creation.
13. **Heft report, don't heft fix** (F4): large/derived data gets a ranked report with
    options; only unambiguous junk is auto-fixed.
14. **Cross-repo reference graph** (F8): before proposing moves, `git grep` *sibling repos*
    for the target repo's name/path; broken cross-repo protocols listed as decision points.
15. **Registered-artefact caution** (F8): preregistrations, OSF amendments, anything plausibly
    link-targeted from outside the repo is move-with-verification or not-moved.
16. **Ingest existing backlogs** (F9).
17. **Tier before treating** (§3): not every repo gets the full protocol.
18. **Naming fixes are solo-repo-only** (F6) and always concorded.

## 3. Repo tiers (triage, Phase 0)

| Tier | Criteria | Treatment | Survey examples |
|---|---|---|---|
| **Full** | active, solo-or-led, research/teaching, layout debt | all phases | inscriptions, map-reader-llm, llm-reproducibility, ANU-HUMN8031-2026, blue-mountains, paper-b (in progress) |
| **Restricted** | collaborative (authors > ~2 or org remote) | additive only by default: seed wiki/, report; moves need explicit collaborator-aware approval, branch+PR mandatory | LLM-History-Paper (Brian), fieldmark-docs-staging, Groundsite-EFN-Planning, client-materials |
| **Light** | small or low-debt | README + `wiki/continuity.md` seed; skip the full structure (don't impose nine directories on a 3-file repo) | voice-assistant, talks, 2026-mq-llm-dh-ideation-writing, prompts, audio-to-text-pipeline, ebook-library |
| **Tombstone** | dormant > ~1 year | status-note README ("dormant since X; see Y") only | colour-names (2021), inequality-modelling (2020), personal-scripts |
| **Skip** | external/work/fork | nothing | FAIMS3, faims-android, raid-*, theseus-ship, UserToDev, write-like-me |

Tier assignment is proposed in Phase 0 output and confirmed by the user.

## 4. Skill shape

**Form:** a skill (`SKILL.md`), run in-session with the user available for gates. MAY
dispatch read-only survey subagents (Explore) for large repos. Verification phase may use a
fresh-context verifier (proposer/verifier pattern per lit-scout / data-profile).

**Name:** `repo-standardise`. Triggers: "standardise this repo", "reorganise the repo",
"migrate to the wiki layout", "/repo-standardise". Modes: full run; `--drift-check`
(Phases 0–2 only, report drift on an already-migrated repo); `--survey` (portfolio-wide
Phase 0 triage table, the §1-style sweep).

**Phases:**

- **Phase 0 — triage + preflight.** Lifecycle/tier call (§3); clean tree; `0 behind`;
  protected paths (`.gitmodules`, external-sync markers, registered artefacts, per-repo
  `CLAUDE.md` constraints); collaborative detection (remote org, `git shortlog -sn`).
- **Phase 1 — survey.** Inventory (tracked/untracked/ignored); heft audit (F4); layout
  markers incl. partial-migration state (F3); README drift (F5); **beacon census** (F2);
  loose-root and naming scan (F6); existing-backlog harvest (F9).
- **Phase 2 — classify.** Role table (F1 sub-species as the checklist); liveness audit;
  in-repo reference graph; **cross-repo grep of siblings** (F8). Every claim anchored
  (file:line, command, commit) per the anti-confabulation write-side rule.
- **Phase 3 — propose. STOP.** Proposal to `wiki/planning/repo-reorg-proposal-<date>.md`
  (seeds wiki/ if absent); explicit decision points; tier confirmation; await the user.
- **Phase 4 — execute.** Branch per decision; `git mv` in logical commit batches (wiki
  migration → outputs split → archive sweep → consolidation → code relocation →
  documentation); ignore rules and path constants ride with their moves; concordance into
  `wiki/index.md`; beacon reconciliation (rule 11).
- **Phase 5 — verify.** Builds/tests; old-path grep hits only `archive/` + concordance;
  `git log --follow` spot-checks; ignored paths still ignored; cross-repo protocols intact.
  Fresh-context verifier re-runs. Fail → fix before PR/push.
- **Phase 6 — document + close.** README rewrite/create; `archive/README.md`; continuity
  entry; commit/push per repo convention (restricted tier: PR, never direct push).

## 5. Parameters

| Parameter | Default | Notes |
|---|---|---|
| repo path | cwd | |
| layout reference | `~/personal-assistant/wiki/index.md` ("PA project layer") | canonical spec |
| tier | auto-proposed, user-confirmed | §3 |
| protected paths | auto (`.gitmodules`, registered artefacts) + user-supplied | F8 |
| sibling search root | `~/Code` + `~/personal-assistant` | for cross-repo grep |
| consolidation appetite | ask (minimal vs thoroughgoing) | |
| branch policy | global git rules; branch+PR for full-tier moves and all restricted-tier work | |
| archive policy | archive-don't-delete, categorical subdirs | throwaway temp files exempt |

## 6. Initial target roster (from the 2026-06-10 survey)

Priority order for full-tier runs, by debt × activity: **inscriptions** (worst `planning/`
offender: 107 files, 19 MB, 6 subdirs, 4 beacons, OSF artefacts — F8 care needed),
**map-reader-llm** (27k tracked files, heft report essential, existing cleanup backlog to
ingest), **llm-reproducibility** (resume stalled migration; venv untracking already specced
in its `wiki/continuity.md`), **ANU-HUMN8031-2026** (no README, legacy notes; teaching-repo
AI-policy constraints apply), **blue-mountains** (root beacon, naming violations, heft).
Restricted-tier: LLM-History-Paper (coordinate with Brian; paper-b refresh protocol depends
on its paths — F8), fieldmark-docs-staging, Groundsite-EFN-Planning. Light-tier batch
thereafter. paper-b completes under its own proposal (D1–D5).

## 7. Prevention (out of skill scope, worth doing)

The legacy `docs/notes/` layout originates in the cc-session-toolkit template (root cause
noted 2026-05-28). Fix the template so *new* repos start on the wiki layout — cure here,
prevention there. cc-session-toolkit itself is light-tier debt (README drift only).

## 8. Out of scope (v1 implementation)

- Content rewrites; frontmatter backfill beyond the four artefacts; tag application.
- Data management beyond the heft report (LFS adoption, external storage moves).
- Cross-repo orchestration (run per-repo; `--survey` mode is read-only).
- Non-git directories (n.b. ~/Code root itself holds 5 homeless analysis .md files —
  flagged for manual disposition, not the skill's job).

## 9. Open questions

- Verifier: formal subagent definition vs inline checklist? Lean inline for v1; promote if
  the roster proves it out.
- `--drift-check` cadence: ad hoc, or wired into `/weekly-review`?
- Registered-artefact verification (F8b): is checking OSF link targets automatable
  (fetch the registration page) or a user-confirm step? Lean user-confirm for v1.
- Home for the implemented skill: `~/.claude/skills/repo-standardise/` with promotion via
  `published/` Pattern A if it proves out.
