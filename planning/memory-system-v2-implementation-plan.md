# Memory System v2 — Implementation Plan

**Status:** Plan for review. Phase 0a infrastructure landed 2026-05-16; rest still no code.
**Created:** 2026-05-15
**Updated:** 2026-05-16 (added Phase 0 for tier-3 archive; folded in /forget /update commands, self-correction detection, supersession schema)
**Author:** Claude (Opus 4.7) + Shawn
**Depends on:** `planning/memory-system-v2-design.md` (decisions resolved 2026-05-15);
`planning/memory-corpus-audit-2026-05-14.md` (audit findings);
2026-05-16 cross-machine investigation refining tier-3 picture.

## 1. Scope

This plan sequences the implementation of the v2 design plus the operational
foundations the design depends on. It specifies *what gets built where*,
*in what order*, and *what gates each step*. It does not write code.

## 2. Sequencing recommendation

```
Phase 0 (tier-3 archive)  ─┐
                           ↓
                        Phase 2 ──→ Phase 5
                           ↑           │
Phase 1 (schema) ─────────┘            └─→ Phase 6 (parallel, cost-gated)
   │
   ├─→ Phase 3 (Conscious save)     parallel after Phase 1
   │
   └─→ Phase 4 (Typed links)        deferred until 1+2 stable
```

**Critical path:** Phase 0 + Phase 1 → Phase 2 → Phase 5. Phases 0 and 1 are
independent of each other (one is infrastructure, the other is schema) and can
land in parallel; Phase 2's verification uses tier-3 fallback from Phase 0 *and*
the new schema fields from Phase 1, so both must complete before Phase 2 fully
delivers. Phase 3 (conscious save) can ship as soon as Phase 1 lands. Phase 4
(typed links) is deferred until 1+2 prove out. Phase 6 (bake-off) is
cost-gated and independent.

**Rationale:** Phase 0 makes `session_id` a reliable tier-3 verification
anchor — the cross-machine investigation (2026-05-16) showed 92% of memory
session_ids resolve to a transcript on amd-tower or zbook, so the
three-tier architecture (summary → content → transcript) is sound but needs
operational consolidation. Phase 1+2 are the structural fix for the audit's
"53% lacks mechanical anchor" finding. Without tier-3 fallback, verification
is anchor-only and 53% of memories stay unverifiable; with tier-3 fallback,
verification covers ~92% of the corpus via transcript-grep when anchors are
absent. Phase 5 needs Phase 2's verification logic to run a drift sweep
meaningfully.

## 3. Phase 0 — Operationalise tier-3 archive (added 2026-05-16)

**Goal:** Make `session_id` a reliable tier-3 verification anchor by
establishing a single canonical, cross-machine-accessible archive of session
transcripts (main and subagent) — so Phase 2's verification logic can consult
the original conversation when a memory's mechanical anchors are absent or
fail to resolve.

### 3.1 0a — Local archive infrastructure

**Completed 2026-05-16:**

- amd-tower's venv now has `cc-session-toolkit` installed (was silently
  failing via ModuleNotFoundError, swallowed by the SessionEnd hook chain —
  zbook archived 361 sessions over six months while amd-tower captured 32
  stale March/April entries before going dark).
- `requirements.txt` declares Python deps for both machines.
- `setup.sh` reads from `requirements.txt` for fresh-machine bootstrap.
- `sync-symlinks.sh` Step 7 verifies declared deps on every daily-sync run and
  auto-installs missing ones — fresh machines, reformats, or a third working
  machine now need only `bash setup.sh` to reach a fully-functional
  archive-capturing state.

**Outstanding:**

- One-off archive of amd-tower's 91 currently-unarchived live transcripts via
  `cc-session-toolkit archive --backfill ~/.claude/projects/` (exact CLI
  flag to be verified against the toolkit's current help text).
- Spot-check zbook's archive log to confirm every-session capture continues
  to function after the 2026-05-02 Postgres rebuild that wiped the
  `sessions` table index.

### 3.2 0b — Canonical rpi-server archive

- Canonical store lives at
  `~/mnt/rpi-shares/cc-archives-consolidated/` on working machines
  (= `rpi-server:/opt/encrypted/workspace/shares/cc-archives-consolidated/`),
  uncompressed, single canonical location. Reached via the existing
  `mount-rpi-shares` SSHFS alias (resolved 2026-05-21; `mount-rpi-storage`
  is the catch-all that mounts shares + vantec + qnap together, but
  only `rpi-shares` is needed for the cc archive). Layout and READMEs
  published on the mount.
- Add an rsync step to `daily-sync.sh`: each machine pushes its
  `~/cc-archives/` to the rpi-server canonical directory. Conflict-free
  because each machine writes only its own session IDs into its own archive.
- Build a cross-machine session-id resolver
  (`scripts/resolve_session_id.py`): given a `session_id`, return the
  canonical archive path or `not-found`. Used by Phase 2's tier-3 fallback.
- Re-index the consolidated archive into Postgres `sessions` table — either
  by running `sync-sessions-to-postgres.py` against the SSHFS-mounted path
  from each machine, or as a periodic job on rpi-server itself. Decision
  deferred to implementation time.
- **Effort:** 1–2 sessions.

### 3.3 0c — Working-machine mirror (decide after 0b)

- Measure consolidated rpi-server size after 0b completes (expect ~5.8 GB
  uncompressed initially, growing).
- Decide whether each working machine pulls a full uncompressed mirror from
  rpi-server (3-way redundancy at the cost of disk space) or stays
  index-only (relies on rpi-server reachability for cross-machine lookups).
- If mirroring: add an rsync-pull step to `daily-sync.sh`.

### 3.4 0d — Verified cleanup of `~/.claude/projects/`

**Strictly gated.** Only after Phase 0b is stable AND a confidence period
(≥ 2 weeks of every-session-archives-correctly) is verified.

- Verification gate: every `session_id` in `memories.jsonl` must resolve to a
  file in the rpi-server canonical archive before any local deletion.
  Implemented as a precondition check in
  `scripts/cleanup-live-transcripts.py`.
- Lift the `cleanupPeriodDays: 99999` setting (or replace with a custom
  rotation policy in the same script). Both machines currently set this
  to ~273 years — appropriate while the archive isn't yet trusted as a
  durable source of truth.
- **Effort:** 1 session, gated.

### 3.5 0e — Stretch goal: Cloudflare R2 offsite backup

**Foundation complete 2026-05-16:** R2 bucket `pa-cc-archives` created;
rclone configured on all three machines (`r2archives` remote on amd-tower
and zbook, `r2-pa-cc-archives` on rpi-server) with per-machine API tokens
for granular revocability; smoke tests passed on each. Credentials live in
each machine's `~/personal-assistant/.env` (or `~/.config/rclone/rclone.conf`
on rpi-server, see below) at chmod 600; never committed.

**Outstanding (Phase 0e proper, awaits 0b):**

- rclone push from rpi-server → R2 daily.
- Working machines push to R2 when rpi-server is unreachable (travel mode);
  rpi-server reconciles R2 deltas on next sight.
- Cost: ~$1/year at current size; ~$5/year extrapolated over 3 years
  (pricing to be re-verified before commitment).
- **Effort:** 1 session after 0b is stable.

### 3.6 Effort summary: 3–5 sessions excluding the 0e stretch goal.

## 4. Phase 1 — Schema groundwork

**Goal:** Memory record gains the fields that v2 depends on. Atomic schema
bump, backwards-compatible reads.

### 4.1 Schema additions to the memory record

| Field | Type | Notes |
|---|---|---|
| `anchors` | array of `{type, ref, line?}` | `type` ∈ {`file`, `commit`, `zotero`, `url`}; required for guidance categories per change A |
| `verified` | string | `true` / `false` / `pending` / `stale` per change E.2 and G |
| `links` | array of `{relation, target_id}` | Phase 4 populates; field exists from Phase 1 |
| `why` | string (optional) | Change B; required for guidance categories |
| `how_to_apply` | string (optional) | Change B; required for guidance categories |
| `superseded_by` | string memory_id (optional) | The memory that replaces this one. Recall de-ranks. Set by `/forget` / `/update` and by Phase 4 cross-session supersession |
| `revisions` | array of `{revised_at, prior_content, reason}` | Audit trail when `/update` modifies content |
| `is_active` | boolean (default `true`) | Soft-delete flag set by `/forget`; recall filters by `is_active` by default |

`VALID_CATEGORIES` gains `feedback` (change Q6 decision). Lone `preference`
entry re-categorised as `feedback` in Phase 5 step 2.

### 4.2 Files to modify

- `hooks/extraction-hook.py` — `VALID_CATEGORIES`, `format_memories`,
  `EXTRACTION_PROMPT` (surface new fields; *enforcement* lands in Phase 2)
- `commands/remember.md` — JSON example, argument parsing for new optional
  fields (`anchor:`, `why:`, `how_to_apply:` token prefixes)
- `commands/forget.md` — NEW: `/forget [id] [reason?]` soft-delete command
- `commands/update.md` — NEW: `/update [id] [new content]` revision command
- `scripts/schema.sql` — `ALTER TABLE memories ADD COLUMN` for each new
  field; rebuild `active_memories` view to filter `is_active = true`
- `scripts/memory_mcp.py` — `_row_to_memory` passes new columns through
- `scripts/fetch-memories.py` — JSONL load + filter handles missing fields
  gracefully (treats missing as null)
- `scripts/sync-to-postgres.py` — handles new fields on insert

### 4.3 New commands `/forget` and `/update` (L1 of memory correction)

Per the design-doc decision to support L1 (explicit forget/update),
L2 (self-correction in extraction, Phase 5.x), and L3 (cross-session
supersession, Phase 7) layers of memory correction:

- **`/forget [id] [reason?]`** — sets `is_active: false` on the memory.
  Preserves the entry (audit trail). Reason string stored in `revisions[]`
  with timestamp.
- **`/update [id] [new content]`** — replaces `content`; pushes prior
  content to `revisions[]` with timestamp and optional reason. If anchors
  change, confidence rebinds per Phase 2 rubric.
- **Both commands are usable autonomously by Claude** per the self-driving
  tenet — announce-and-execute, same shape as conscious save in Phase 3.
  Format: `Marking memory [id] as [forgotten|updated]: [reason]`. The
  `COMMAND_MARKERS` extension (Phase 3) covers the announce lines so the
  extraction hook doesn't re-extract them.

### 4.4 Backwards compatibility

Old entries (~25,581 existing) have none of the new fields. Read paths must
treat absent fields as null and not penalise old entries in recall ranking
solely for missing v2 fields. Phase 5 (bulk flag) introduces explicit
de-weighting; until then, old entries rank as they did before.

`is_active` is treated as `true` when absent — so old entries remain visible
to recall by default.

### 4.5 Effort: 2 sessions (was 1–2; +1 for the new commands)

## 5. Phase 2 — Anchor + verification pipeline

**Goal:** The structural fix. New writes land with anchors, anchors are
checked (mechanical first, tier-3 transcript fallback if needed), `verified`
and `confidence` are bound to the result.

### 5.1 Extraction-prompt update (change A)

`EXTRACTION_PROMPT` in `hooks/extraction-hook.py` gains:

- Explicit instruction: anchors must come from the transcript verbatim, never
  invented. If no anchor present, lower confidence or reword the memory to
  drop the false precision.
- Per-category anchor requirements: `decision`, `progress`, `architecture`,
  `gotcha`, `provenance`, `completion` *must* have at least one anchor;
  others optional.
- Demand structured `why` / `how_to_apply` for guidance categories per
  change B.
- **Self-correction detection (L2 of memory correction).** New explicit
  instruction: when the transcript contains a self-correction
  ("actually, X was wrong", "correcting myself", "on closer inspection, Y is
  the case"), extract only the corrected version, not the original claim. If
  the original claim has structural import, emit it with a
  `superseded_by` pointer to the corrected memory's id. *(Concrete example:
  the 2026-05-16 "422 transcripts lost" claim was extracted as
  `confidence: high` even though the cross-machine correction came four
  turns later. L2 detection would have caught this.)*

### 5.2 New module: `scripts/anchor_verify.py`

Functions:

- `verify_file(path: str, repo_set: list[Path]) → str` — returns `true` if
  file exists in any repo in the set (current or git history), `false`
  otherwise. Hand-rolled fast path: `stat` for current files, `git
  cat-file -e` for historical.
- `verify_commit(hash_: str, repo_set: list[Path]) → str` — `git rev-parse`
  across the repo set.
- `verify_zotero(key: str) → str` — best-effort via the existing
  `scripts/zotero.py`; returns `pending` if API offline.
- `verify_memory(record: dict) → str` — top-level dispatcher; returns
  `true` if *all* anchors resolve, `false` if any resolve negatively,
  `pending` if any check timed out. **Tier-3 fallback** (depends on
  Phase 0): if anchors are absent or fail to resolve, call
  `resolve_session_id(record["session_id"])` to fetch the canonical
  transcript path, then grep the transcript for the memory's specific
  claim tokens. If the claim is *present* in the transcript, set
  `verified = "tier3"` (memory faithfully reflects what was said,
  even if no external anchor) and `confidence = "medium"`. If the
  claim is *absent* from the transcript, set `verified = "false"` —
  the extractor invented a claim that was never made.

Fail-soft: never reject the memory. Verification status is recorded; recall
ranking respects it.

### 5.3 Repo-set helper (change G)

Extend or replace `scripts/project_id.py`:

- `decode_project(project_field: str) → Path` — current behaviour
  (`-home-shawn-Code-foo` → `/home/shawn/Code/foo`).
- `repo_set() → list[Path]` — auto-discover all active project repos by
  walking a fixed set of root paths and finding `.git` directories within a
  bounded depth. Per the self-driving tenet, no manual list maintenance.
- `repo_set_for(project: str) → list[Path]` — returns the decoded path
  ordered first, then the rest of the repo set. Used by `anchor_verify.py`.

**Discovery roots and depths** (per Shawn's 2026-05-15 scope decision —
all active project directories):

| Root | Max depth | Catches |
|---|---|---|
| `~/Code/` | 2 | Top-level projects and `~/Code/teaching/*` |
| `~/personal-assistant/` | 1 | The PA repo |
| `~/personal-assistant/data/` | 1 | `pa-data` submodule |

Cache the discovered set with a session-lifetime TTL to avoid re-walking on
every hook invocation. Re-walk on TTL expiry or when verification of a
specific anchor would otherwise fail (lazy refresh). Discovery list is
configurable via a top-level constant — easy to extend without code changes
elsewhere.

### 5.4 Confidence binding (change F)

In `format_memories`, after `anchor_verify.verify_memory()` returns:

- `verified == "true"` *and* guidance-category fields complete → `confidence = "high"`
- `verified == "true"` but structural fields incomplete → `confidence = "medium"`
- `verified == "tier3"` (transcript-grep fallback succeeded) → `confidence = "medium"`
- `verified == "pending"` → `confidence = "medium"`
- `verified == "false"` or no anchors and no tier-3 hit → `confidence = "low"`

Haiku's self-rated `confidence` is discarded.

### 5.5 Hook integration

`hooks/extraction-hook.py` main flow becomes:

1. Parse transcript.
2. Extract via Haiku (or whichever model Phase 6 selects).
3. For each extracted memory: `anchor_verify.verify_memory()` (sync, fast).
4. `format_memories` binds `confidence` and `verified`.
5. Append.

Existence-check latency estimate: `stat` is microseconds; `git rev-parse` is
~5ms on a warm repo. At ~3–5 anchors per memory × ~3 memories per
extraction = ~45 anchor checks per hook run ≈ 250ms worst case. Tier-3
transcript-grep adds ~5–50ms per memory only when invoked (anchors absent or
failed), so ~150ms worst case across a batch. Negligible vs. the Haiku call
itself.

### 5.6 Effort: 3 sessions (was 2–3; +0.5 for tier-3 fallback, +0.5 for self-correction logic)

## 6. Phase 3 — Conscious "Claude can save" mode (change D)

**Goal:** Claude gains an autonomous capture trigger.

### 6.1 Directive

Add a section to `global-claude-md/memory-system-reference.md` (extracted
from the design-doc change D criteria) covering:

- *When to fire* — user articulates a durable preference/constraint; a
  non-obvious decision is made with rationale; an approach notably succeeds
  or fails; an error mode emerges with a correction.
- *Announce format* — `Saved to memory: [category] — [summary]`. Exact
  string so the COMMAND_MARKERS extension can pattern-match. Likewise for
  `/forget` and `/update` announce lines from Phase 1.
- *Execute* — follow the `/remember` procedure: parse, normalise tags,
  generate ID, append to JSONL. Including the v2 fields (anchors etc.).

### 6.2 COMMAND_MARKERS extension

`scripts/_command_markers.py` gains the autonomous-save, autonomous-forget,
and autonomous-update announcement prefixes so `extraction-hook.py` skips
those assistant turns and avoids double-capture or re-extracting a turn
about a /forget.

### 6.3 Optional: brief mention in `global-claude-md/shared.md`

A one-line pointer to the criteria so the autonomous-save behaviour is
discoverable from the global CLAUDE.md, not buried in the reference doc.
Watch the 170-line cap.

### 6.4 Effort: 1 session

## 7. Phase 4 — Typed links (change C)

**Goal:** Memory corpus becomes a graph, not a bag. Also: provides L3 of the
memory-correction layers (cross-session supersession via the `supersedes`
and `contradicts` relations).

**Deferred until Phases 1+2 prove stable** — links depend on the v2 schema
and on the verification pipeline producing trustworthy `verified` status to
gate link creation.

### 7.1 Mechanisms (per design-doc change C)

1. **Primary: write-time linking.** `commands/remember.md` and
   `EXTRACTION_PROMPT` get explicit guidance — if writing memory revises or
   contradicts a specific prior memory whose ID is known, populate `links`.
2. **Secondary: gardening pass.** New script
   `scripts/link-gardening.py` analogous to `scripts/tag-gardening.py`. Runs
   periodically (cron/systemd timer). Auto-applies high-confidence links
   (above strict similarity threshold); logs ambiguous ones but does not
   block.
3. **Tertiary: semantic-assisted on write.** `scripts/memory_mcp.py` gains
   a `find_related(memory_id, k=5)` tool that returns near-neighbours via
   pgvector. Write paths consult it and auto-link above threshold.

### 7.2 Cross-session supersession (L3 of memory correction)

When the gardening pass detects two memories with substantially overlapping
specifics where one explicitly contradicts the other (e.g. one says "X
exists at path A", a later one says "X actually exists at path B"),
auto-apply `supersedes` link. The earlier memory's `superseded_by` field
is also set, mirroring the L1 `/update` behaviour. Recall ranks down
superseded entries automatically.

### 7.3 Effort: 3–4 sessions

## 8. Phase 5 — Migration (design-doc section 4)

**Goal:** Existing 25k corpus migrated to v2 schema state without retroactive
anchor pass (deferred unless drift sweep shows it warranted).

Depends on Phase 2 verification pipeline (and therefore on Phase 0 for the
tier-3 fallback the drift sweep can use).

### 8.1 Targeted schema fix (Section 4 step 2 of design doc)

- Add `feedback` to `VALID_CATEGORIES` in
  `hooks/extraction-hook.py` and `commands/remember.md`.
- Re-categorise memory `2026-04-18-f9944e9bf2a3` (lone `preference`) as
  `feedback`. One-line JSONL edit; preserve `id`/`session_id` etc.

### 8.2 Periodic drift sweep (Section 4 step 3 of design doc)

New script `scripts/drift-sweep.py`:

- Iterates the whole corpus.
- For each entry with anchors, calls `anchor_verify.verify_memory()`.
- Updates `verified` status; if anchor previously resolved and now does not,
  applies the revitalisation-vs-staleness distinction (change G): permanent
  categories → `verified: stale` (preserve, mild de-weight); transient
  categories → `verified: false` (stronger de-weight).
- Quarterly cron (or systemd timer). Logs summary.

### 8.3 Bulk flag (Section 4 step 4 of design doc)

One-off script `scripts/bulk-flag-unverified.py`:

- For permanent-category entries with no anchors, set `verified: false`.
- Run once after Phase 2 lands.

### 8.4 Reassess (Section 4 step 5 of design doc)

Hold open. After the sweep + bulk-flag run, evaluate whether a retroactive
anchor pass on high-value permanent categories is worth the API cost.

### 8.5 Effort: 1–2 sessions

## 9. Phase 6 — Extractor-model bake-off (change E.4)

**Goal:** Empirically decide whether Haiku 4.5 remains the right extractor,
or whether Gemini 2.5 Flash or Sonnet 4.6 wins on the anchor-recall /
confabulation / cost trade-off.

**Cost-gated.** Per global CLAUDE.md API Call Review Gate, the bake-off
plan must be presented for approval *before* any API spend, with: model
set, sample size, total call count per model, cost per call (precisely
calculated from current pricing — do not guess), total cost. Approval for
the bake-off does not imply approval for ongoing use of the winner.

### 9.1 Methodology (subject to approval)

- Sample N representative recent sessions (target N=30, post-4.7 cohort).
- For each session, re-extract with: Haiku 4.5 (current), Gemini 2.5 Flash,
  Sonnet 4.6.
- Metrics per model: anchor recall (against a hand-coded ground truth on
  ~5 sessions), per-memory unverifiable rate (run extracted memories
  through Phase 2 `anchor_verify`), per-call latency, per-call cost.
- Total calls: 30 × 3 = 90 + cost-of-pre-flight pilot.

### 9.2 Files

- `scripts/extractor-bakeoff.py` — one-off; reads the session sample,
  invokes each model, writes a comparison report.

### 9.3 Outcome

Either retain Haiku or swap to the winner by changing `HAIKU_MODEL` in
`hooks/extraction-hook.py` (and renaming the constant).

### 9.4 Effort: 1 session prep + 1 session run+analysis (after cost approval)

## 10. Cross-cutting concerns

### 10.1 Backwards compatibility

- New fields are optional everywhere. JSONL readers must tolerate missing
  fields. Postgres `ADD COLUMN` uses default null.
- Recall ranking must not penalise pre-v2 entries solely for missing v2
  fields *until* Phase 5 explicit bulk-flag pass.
- `is_active` defaults to `true` when absent, so existing entries remain
  visible to recall.

### 10.2 Postgres migration

- `ALTER TABLE memories ADD COLUMN` for each new field. Default null
  (except `is_active`, default `true`). Fast on a 25k-row table.
- Rebuild `active_memories` view to expose new columns AND filter
  `is_active = true`.
- Consider GIN indexes on JSONB `anchors` and `links` arrays once queries
  need them (defer until a query pattern emerges).
- Back up the database (`pg_dump claude_memories`) before any `ALTER`.
- The 2026-05-02 rebuild that wiped the `sessions` table is a precedent for
  why Postgres migrations need explicit recovery plans — record the rebuild
  script's path in the migration notes.

### 10.3 Tests

No test suite is currently visible in the repo. Per the 2026-05-15 decision
("optimal, not minimal — stop at diminishing returns"), this work introduces
a properly-scoped pytest suite alongside the v2 changes, and defers further
test-tooling work to the future-extensions doc.

**Test infrastructure**

- Runner: `pytest` (+ `pytest-mock` for mocks).
- Layout: `tests/` at repo root; `tests/fixtures/` for sample memories,
  sample transcripts, and a tiny git repo fixture used by `anchor_verify`.
- Config: `pyproject.toml` `[tool.pytest.ini_options]` (or `pytest.ini`).
- Local entrypoint: `make test` target (and/or a `scripts/test.sh`).
- Dependencies: declared in `requirements.txt` (pytest already there
  since 2026-05-16; pytest-mock to add).
- CI/CD: **deferred** to the future-extensions doc (local-first repo, manual
  test runs are acceptable for now).

**Test plan — what gets coverage**

Unit tests (pure functions, dependencies mocked):

- `tests/test_anchor_verify.py` — `verify_file` (current path, git-history
  path, missing, repo-set traversal); `verify_commit` (current branch,
  history, partial-hash, missing); `verify_zotero` (mocked API hit/miss/
  offline → `pending`); `verify_memory` (all-resolve, any-fail, any-pending,
  malformed, empty anchors); **tier-3 fallback** (anchors absent + session
  transcript hit, anchors absent + session transcript miss, anchors absent
  + session not in archive → unresolvable).
- `tests/test_resolve_session_id.py` — cross-machine session resolver
  (NEW, Phase 0): hits in canonical archive, hits in local archive only,
  not-found path, repo-set traversal of the consolidated tree.
- `tests/test_repo_set.py` — discovery walks expected roots, respects depth
  bounds, caches correctly, lazy-refresh on miss; `repo_set_for` orders
  decoded path first.
- `tests/test_normalise_tags.py` — covers existing `normalise_tag` and
  `normalise_tags` logic (currently untested); plural/underscore/uppercase/
  punctuation cases.
- `tests/test_confidence_binding.py` — change F rubric maps all
  `verified` × structural-completeness combinations correctly, including
  the `tier3` value.
- `tests/test_project_decode.py` — `decode_project` round-trip,
  edge cases (paths with hyphens, submodules).

Integration tests (real filesystem in `/tmp`, mocked external APIs):

- `tests/test_extraction_hook.py` — full round-trip on a fixture transcript:
  parse → Haiku-mocked → format → verify (against a fixture repo and
  fixture transcript archive) → bind → append → JSONL is valid → cursor
  advances. Includes the self-correction case: transcript contains
  "actually X was wrong"; assert only corrected memory extracted.
- `tests/test_remember.py` — `/remember`-style invocation with all new
  token prefixes (`anchor:`, `why:`, `how_to_apply:`); JSON record
  validates; vocabulary updates.
- `tests/test_forget_update.py` — `/forget` and `/update` (NEW) preserve
  audit trail; soft-delete sets `is_active = false`; recall hides
  superseded entries by default; revisions array populated correctly.
- `tests/test_drift_sweep.py` — dry-run mode against a fixture corpus does
  not mutate; reports expected DRIFT/STALE counts; revitalisation-vs-
  staleness distinction applied per change G.
- `tests/test_bulk_flag.py` — applies `verified: false` to the right rows;
  idempotent on second run.
- `tests/test_jsonl_append.py` — concurrent appends preserve all records
  (covers the existing `_shared_locked_append_fd` flock dance, currently
  untested).
- `tests/test_command_markers.py` — extraction hook skips autonomous-save,
  autonomous-forget, autonomous-update announcement turns (Phase 3);
  `/remember` exchanges still skipped.
- `tests/test_sync_symlinks.py` (NEW) — Step 7 dep verification:
  imports succeed → no-op; an import fails → triggers install; venv
  missing → warn.

Smoke tests (do things still start / parse):

- `tests/test_compose_global.py` — `compose-global-claude-md.sh` produces
  output under 170 lines and contains all expected sections.
- `tests/test_python_syntax.py` — every `.py` in `hooks/` and `scripts/`
  compiles (catches typos before runtime).

Phase 4 tests (added with Phase 4):

- `tests/test_link_gardening.py` — deterministic output on fixture corpus;
  auto-apply threshold respected; cross-session supersession detection.
- `tests/test_find_related.py` — returns expected neighbours on a small
  fixture index.

**Where diminishing returns kick in (deliberately not tested)**

- Trivial pass-through code (envelope helpers, getter functions, single-
  line wrappers).
- Python stdlib usage (we don't test that `json.loads` parses JSON).
- Live external APIs (Anthropic, Gemini, Zotero) — always mocked in tests;
  the bake-off (Phase 6) is the only place real API calls happen, and
  that's gated on cost approval.
- Postgres — fixture tests against an in-memory or temp database are too
  costly to set up given the small DB surface; instead, rely on the
  smoke-level "schema applies cleanly" check at migration time.
- Coverage-percentage targets — aim instead for "every new public function
  has at least one test"; coverage tooling itself is deferred.
- UI-style behaviour (announcement format strings) — covered indirectly via
  `test_command_markers.py`.

**Total estimated test files at end of v2:** ~16 (was 14; +1 for
`test_resolve_session_id`, +1 for `test_forget_update`, +1 for
`test_sync_symlinks`; gardening test absorbed L3 supersession coverage).
**Effort:** ~1 session to bootstrap pytest infra + write the first test
file with realistic fixtures; subsequent test files are ~30–60 minutes
each, written alongside the code they cover, not as a post-hoc batch.

Deferred test-tooling extensions (CI, property-based testing, performance
benchmarks, coverage tooling) live in
`planning/memory-system-v2-future-extensions.md`.

### 10.4 Documentation

- `global-claude-md/memory-system-reference.md` needs updating after each
  phase (schema additions, conscious-save criteria, forget/update commands,
  link relations).
- `commands/remember.md` updated for new token prefixes and JSON shape;
  `commands/forget.md` and `commands/update.md` created.
- A short v2 architecture note in
  `global-claude-md/infrastructure-reference.md` would help future Claudes
  navigate. Correct the stale `archive/cc-sessions/` reference in the
  global Reference Docs table to `~/cc-archives/` (and post-Phase-0b, to
  `~/mnt/rpi-shares/cc-archives-consolidated/` — the resolved destination
  per 2026-05-21).

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Postgres migration breaks recall | Low | High | Backup + rollback plan; test on a copy first |
| Hook latency degrades from existence checks | Low | Medium | Measured: ~250ms worst case for anchor checks + ~150ms worst case for tier-3 fallback; negligible vs. Haiku call |
| Bake-off ongoing cost too high | Medium | Medium | Cost gate before any spend; Sonnet may be priced out |
| /remember backwards compat — old invocations | Low | Low | New fields are optional; old commands still work |
| Schema drift between extraction-hook and /remember | Medium | Medium | Land schema changes atomically; reference single source of field list |
| Anchor verification false-negatives (file renamed mid-session) | Medium | Low | Fail-soft, drift sweep catches later |
| Auto-memory MD system still gets written despite CLAUDE.md directive | Medium | Low | Monitor `~/.claude/projects/.../memory/` after a few sessions; tighten if needed |
| rpi-server unreachable during Phase 2 hook run | Medium | Low | Tier-3 fallback is opportunistic — failure to reach archive doesn't fail extraction, just records `verified: pending` |
| Phase 0d cleanup deletes transcripts that aren't in archive | Low | High | Verification gate; ≥2-week confidence period; per-file existence check before any rm |
| amd-tower archive backlog (91 transcripts) loses some during Phase 0a delay | Low | Low | `cleanupPeriodDays: 99999` already prevents this; backfill safe to run anytime |

## 12. Pre-implementation actions

**Completed 2026-05-16:**

- ✓ `requirements.txt` declared with `anthropic`, `psycopg2-binary`,
  `pytest`, `mcp`, `pyzotero`, `cc-session-toolkit`.
- ✓ `setup.sh` reads from requirements.txt.
- ✓ `sync-symlinks.sh` Step 7 auto-heals missing deps.
- ✓ amd-tower's venv now has `cc_session_toolkit` installed (editable from
  `~/Code/cc-session-toolkit`).
- ✓ zbook pulled the changes; Step 7 verified all six deps present.
- ✓ R2 bucket `pa-cc-archives` created; rclone configured + smoke-tested on
  all three machines with per-machine API tokens (Phase 0e foundation).
- ✓ rpi-server bootstrapped: GitHub SSH key generated and added to account;
  `~/personal-assistant/` cloned; `setup.sh` run (venv + deps + symlinks);
  rclone configured.

**Outstanding before Phase 0b starts:**

1. Backfill-archive amd-tower's 91 live transcripts via cc-session-toolkit
   (Phase 0a outstanding item).
2. Spot-check zbook's archive log to confirm SessionEnd hook fires cleanly.

**Outstanding before Phase 1 starts:**

3. **Backup memories.jsonl + tag-vocabulary.txt** to `archive/pre-v2/`
   (data submodule).
4. **Backup the Postgres DB**: `pg_dump claude_memories > backup-pre-v2.sql`.

**Outstanding before Phase 6 (bake-off):**

5. Bake-off cost estimate with current per-model pricing — not a Phase 1
   blocker.

## 13. Out of scope / explicitly deferred

- **Session-start payload reduction (vector 2 from design doc).** Separate
  workstream. Shawn (2026-05-15): "at some point we do need to deal with the
  injection issues" — acknowledged. The 43.6 KB context injection observed
  on 2026-05-14 remains a known problem; tackling it requires its own
  design pass (which channels to load lazily, how to gate the
  session-start retrieval hook, payload-budget targets). Not blocked by v2;
  v2 does not preclude it.
- Recall ranking algorithm changes beyond anchor-resolution gating.
- MCP server write tools — staying read-only.
- Retroactive anchor pass on the existing 25k — held until Phase 5 outcome.

A consolidated register of deferred work lives in
`planning/memory-system-v2-future-extensions.md`.
