# Personal-Assistant — Continuity (Living Doc)

**Purpose:** cross-session state, pending work, things to verify, and a
session-by-session log. Updated at the end of each session, in place
(no new file per session). Points at the durable planning docs;
doesn't duplicate them.

**How to update at session end:**

1. **Mark done items** in place — replace `[ ]` with `[x]` plus
   the date (e.g. `[x] 2026-05-17 verified`); do **not** delete.
2. **Add new items** to the relevant section as `[ ]` with a brief
   note. Promote anything urgent to the "Things to verify next
   session" list.
3. **Append a new "Session log" entry** at the bottom (most recent
   first). One paragraph max, plus a short bullet list of artefacts
   touched (commits, planning docs, scripts).
4. **Carry forward open questions** in the "Open decisions /
   questions" section. Resolved decisions move down to the session
   log entry where they were made.

---

## Active workstreams

### A. Memory System v2 — *forward pipeline shipped 2026-05-16*

The structural confabulation fix is live on amd-tower + zbook +
rpi-server. New memories now go through anchor verification and
confidence binding before they land in JSONL. See
`planning/memory-system-v2-design.md` for full design,
`planning/memory-system-v2-implementation-plan.md` for sequencing.

| Phase | Status |
|---|---|
| Phase 0 — operationalise tier-3 archive | **pending** (deferred 2026-05-16) |
| Phase 1 — schema + `/forget` + `/update` | **done 2026-05-16** (commits `03b86ad`, `d666470`) |
| Phase 2 — anchor verification + confidence binding | **done 2026-05-16** (commit `50e663b`) |
| Phase 3 — autonomous-save + correction markers | **done 2026-05-16** (commit `7078d39`) |
| Phase 4 — typed links + cross-session supersession (L3) | pending |
| Phase 5 — migration sweep + bulk-flag pass | pending |
| Phase 6 — extractor bake-off | pending (cost-gated) |

### B. Session-start payload reduction (Vector 2 / injection issue) — *acknowledged, not started*

Distinct from the v2 corpus work. The session-start hook injects
~43 KB of recall memories plus harness-injected auto-memory plus
skills listings plus tool schemas plus two CLAUDE.md files. Even
with the v2 confabulation fix shipped, an unverified high-volume
context injection can still drive subtle confabulation by priming
the model with stale or low-confidence specifics presented as
authoritative.

**Why this matters now:** Phase 2's anchor verification cleans the
write path; Vector 2 cleans the read/surfacing path. The two are
complementary — without Vector 2, even verified memories surfaced
authoritatively can drive primacy-effect errors.

**Status:**

- [x] 2026-05-15 Vector 2 explicitly acknowledged in design doc and
  impl plan; deferred to its own design pass
- [x] 2026-05-15 Vector 2 captured in
  `planning/memory-system-v2-future-extensions.md` section C with
  observed numbers + open questions for the eventual design
- [ ] Open a dedicated `planning/vector-2-design.md` and run a focused
  design session — should land before Phase 4/5 if at all possible

**Open questions for the eventual design** (carried forward from
future-extensions.md):

- Lazy vs eager loading at session start
- Channel budget (suggest ≤4 KB for the retrieval hook)
- Anti-confabulation framing in the dump itself (de-weight or omit
  unverified entries now that the v2 `verified` field exists)
- Differential surfacing — only memories whose anchors still resolve

### C. PA infrastructure background (continuous)

Shawn runs PA infrastructure sessions as a *secondary* concurrent
context while his primary foreground is elsewhere (research, teaching,
or business work). **Do not lecture Shawn about focus-slot
allocation when this session is PA-infrastructure** — it is
deliberately background. Focus-slot accountability lives in
`tasks/FOCUS.md`; check it before mentioning slot pressure.

---

## Things to verify on next session (priority queue)

Read these *before* starting new work. Most should take <5 min each.

- [ ] **First-firing of v2 extraction hook.** Phase 1–3 landed
  2026-05-16; the next `SessionEnd` / `PreCompact` is the first live
  test of `anchor_verify` + confidence binding in the hook chain.
  Check `~/personal-assistant/logs/extraction.log` for traceback
  noise. Query:
  ```sql
  SELECT COUNT(*) FILTER (WHERE verified IS NOT NULL) AS verified_set,
         COUNT(*) FILTER (WHERE anchors != '[]'::jsonb) AS with_anchors,
         COUNT(*) FILTER (WHERE created_at > '2026-05-16T07:00:00+00:00') AS post_v2
  FROM memories;
  ```
  `verified_set` should equal `post_v2`. `with_anchors / post_v2`
  is the rate at which Haiku is actually producing anchors per the
  updated prompt — a low rate is a signal to revisit the prompt.
- [ ] **`/recall verified:true`** spot-check: a handful of post-v2
  memories should show `verified: true` (or `pending`); `verified:
  false` would mean Haiku invented an anchor that didn't resolve.
- [ ] **zbook + rpi-server hook health.** Both have v2 code; only
  amd-tower has Postgres so verification only writes to the DB on
  amd-tower. Check that hook firings on zbook didn't choke.

## Pending tasks (cross-session)

These survive across sessions. Mark `[x]` with date when done.

- [ ] **Backup cleanup**: remove one of the two pre-v2 backups (in
  `data/archive/pre-v2/` or `~/cc-archives/pre-v2/` on rpi-server)
  after ≥1 week of stable v2 operation. Default removal target:
  pa-data copy (keeps git lean; the 96 MB `claude_memories.dump` is
  the bulk).
- [ ] **Phase 0 — focused session**: archive layout consolidation.
  Sub-items:
  - [ ] Backfill amd-tower's 91 unarchived live transcripts
  - [ ] Reconcile two archive layouts (old `~/cc-archives/` vs new
    `<project>/archive/cc-sessions/`) when consolidating
  - [ ] Set up `~/cc-archives-consolidated/` on rpi-server NVMe
  - [ ] Add rsync step to `daily-sync.sh`
  - [ ] Build `scripts/resolve_session_id.py` (cross-machine resolver)
  - [ ] Decide on indexing pattern: rpi-side cron vs working-machine
    SSHFS-mounted index
- [ ] **Phase 0e — R2 wiring** (once Phase 0b stable): rclone push
  from rpi-server to R2 daily; working-machine push to R2 when
  rpi-server unreachable (travel mode); rpi-server reconciles on next
  sight. R2 credentials are configured on all three machines already
  (see `~/personal-assistant/.env` on amd-tower + zbook, and
  `~/.config/rclone/rclone.conf` on rpi-server).
- [ ] **Vector 2 — open design doc** (`planning/vector-2-design.md`)
  before Phase 4 begins.
- [ ] **Phase 4 — typed links** (combo of `/remember`-time linking +
  periodic gardening + semantic-assisted; all auto-applied per self-
  driving tenet)
- [ ] **Phase 5 — migration sweep** (drift-sweep cron, bulk-flag pass,
  targeted `inscriptions` revitalisation handling)
- [ ] **Phase 6 — extractor bake-off** (Haiku vs Gemini Flash vs
  Sonnet; cost-gated; methodology + cost estimate before any spend)

## Open decisions / questions

Resolved decisions move to the session-log entry where they were made.

*None currently open. All Phase 1–3 questions resolved 2026-05-15;
Phase 0 architecture resolved 2026-05-16.*

## Architectural decisions worth not re-litigating

Distilled from the design + planning docs so the next session doesn't
reopen settled questions:

- **JSONL is canonical**, Postgres is a derived/rebuildable query
  layer. Drop the DB and rebuild from JSONL via
  `scripts/rebuild-postgres.py`.
- **Custom memory system is canonical**; Anthropic's harness-injected
  auto-memory and `MEMORY.md` are *legacy* — never write to them.
  Routed via the write-side rule in `global-claude-md/shared.md`.
- **Session archive: full mirror everywhere.** rpi-server NVMe holds
  canonical `~/cc-archives-consolidated/<project>/<session>/`;
  working machines hold full local mirrors. R2 is offsite + travel
  bridge. Decided 2026-05-16.
- **Inscriptions** is *revitalisation* not abandonment. Drift sweep
  must distinguish revitalisation drift (preserve memory, mark
  `verified: stale`) from true staleness (`verified: false`).
- **Self-driving tenet**: the system must be ~99% self-driving. Rules
  out review-gated steps in the steady state. Manual review allowed
  at bootstrap and exceptional moments only.

## Reference docs

| Topic | Path | Read when… |
|---|---|---|
| v2 design + 8 resolved decisions | `planning/memory-system-v2-design.md` | New session continuing v2 work; want to know why a choice was made |
| Empirical basis for v2 | `planning/memory-corpus-audit-2026-05-14.md` | Need to cite specific audit findings, e.g. 53% unverifiable |
| v2 implementation plan + phases | `planning/memory-system-v2-implementation-plan.md` | Sequencing decisions; per-phase file lists; risks register |
| Deferred-work register | `planning/memory-system-v2-future-extensions.md` | Something feels like it should already exist but doesn't |
| Current FOCUS slots | `tasks/FOCUS.md` | Knowing whether to mention slot pressure (don't if PA work is deliberate background) |

---

## Recent session logs

*Most recent at top. One paragraph + bullets per entry.*

### 2026-05-16 (Sat) — Phases 1–3 of memory v2 shipped

Long session pushing the forward pipeline of the v2 confabulation fix.
Pre-v2 backups taken to two locations (`data/archive/pre-v2/` and
`~/cc-archives/pre-v2/` on rpi-server). Schema migrated v1→v2 (seven
new fields plus `feedback` category; pre-existing `subagent_count`
bug fixed in passing). `sync-to-postgres.py` updated for the new
column list and Json-wrapped JSONB values. New slash commands
`/forget` and `/update` implement memory-correction L1.
`scripts/anchor_verify.py` is the new mechanical verifier module;
`project_id.py` extended with `repo_set` auto-discovery. The
extraction hook now runs every extracted memory through
`verify_memory` and replaces Haiku's self-rated confidence with the
binding rubric. `EXTRACTION_PROMPT` updated to request anchors and
handle self-correction (L2). `COMMAND_MARKERS` extended for
autonomous-save / forget / update announce lines (L1 autonomous
path, Phase 3). Test suite 648 → 680 passing.

Phase 0 was deferred during the session when toolkit-layout discovery
showed two archive locations active (`~/cc-archives/` historical and
`<project>/archive/cc-sessions/` current) — reconciliation deserves a
focused session. Architecture decision made: **full mirror everywhere**
with R2 as offsite + travel bridge. R2 credentials configured on all
three machines using per-machine API tokens (rpi-server's hyphenated
remote name `r2-pa-cc-archives` keeps creds in `rclone.conf` directly;
amd-tower + zbook use env-var pathway with remote `r2archives`).

- Commits: `2b71151`, `17dc5bc` (backups); `03b86ad`, `d666470`
  (Phase 1); `50e663b` (Phase 2); `7078d39` (Phase 3); plus earlier
  `c5d3c36` (impl-plan v2 with Phase 0 added)
- Planning docs created/updated: `memory-system-v2-design.md` (resolved
  decisions added), `memory-system-v2-implementation-plan.md` (Phase 0
  added, completed-block updated, R2 foundation marked done),
  `memory-system-v2-future-extensions.md` (new register),
  `memory-corpus-audit-2026-05-14.md` (audit), this file
- Code: `scripts/schema.sql`, `scripts/_schema_version.py`,
  `scripts/sync-to-postgres.py`, `scripts/anchor_verify.py` (new),
  `scripts/project_id.py`, `scripts/_command_markers.py`,
  `hooks/extraction-hook.py`, `commands/remember.md`,
  `commands/forget.md` (new), `commands/update.md` (new),
  `global-claude-md/memory-system-reference.md`
- Tests: `tests/test_anchor_verify.py` (new, 32 tests);
  schema_version bumps in `test_sync_script`, `test_apply_decay`,
  `test_rebuild_postgres`, `test_sync_sessions`,
  `test_command_markers`

### 2026-05-15 (Fri) — v2 design resolved + R2 infrastructure

Resolved all 8 open questions from the 2026-05-14 design draft;
folded decisions into the design doc. Added Phase 0 to the
implementation plan. R2 setup on amd-tower and zbook with per-machine
API tokens. Self-healing venv infrastructure shipped (requirements.txt
+ sync-symlinks Step 7 + setup.sh updates) — fixes amd-tower's silent
SessionEnd archive failure (cc_session_toolkit was missing from venv).

- Commits: `85c832a` (write-anchor rule), `0177189` (audit + design),
  `10c36b2` (impl + future-extensions), `7d097af` (self-healing
  venv), plus rpi-server bootstrap commits

### 2026-05-14 (Thu) — Investigation + design draft

Cross-machine sync between amd-tower and zbook (the original purpose
of the day). Then triggered into the v2 design work after Shawn raised
the verifier's recurring confabulation hits. Corpus audit run as
background agent; produced the empirical basis. Design doc drafted
with 8 open questions; implementation plan drafted with 6 phases.
Three-tier model investigation began; established that tier-3 archive
is operationally broken (then corrected: 92% cross-machine
resolution).

- Commits: `1f01781` (teaching-contexts CLAUDE.md), plus the merge
  + sync commits and the audit/design docs
