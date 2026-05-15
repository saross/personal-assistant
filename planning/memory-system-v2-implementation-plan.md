# Memory System v2 — Implementation Plan

**Status:** Plan for review. No code yet.
**Created:** 2026-05-15
**Author:** Claude (Opus 4.7) + Shawn
**Depends on:** `planning/memory-system-v2-design.md` (decisions resolved 2026-05-15);
`planning/memory-corpus-audit-2026-05-14.md` (audit findings).

## 1. Scope

This plan sequences the implementation of the 7 changes (A–G) in the v2 design
doc, plus the 5-step migration in section 4 of that doc. It specifies *what
gets built where*, *in what order*, and *what gates each step*. It does not
write code.

## 2. Sequencing recommendation

```
┌─ Phase 1 ─┐ ┌── Phase 2 ──┐ ┌──── Phase 5 ────┐
│  Schema   │→│ Verification │→│ Migration sweep │
└─────┬─────┘ │   pipeline   │ │  + bulk flag    │
      │       └──────┬───────┘ └─────────────────┘
      │              │
      │              └─→ ┌─ Phase 6 ─┐
      │                  │ Bake-off  │ (parallel, cost-gated)
      │                  └───────────┘
      │
      ├─→ Phase 3 (Conscious save)   ─ parallel
      │
      └─→ Phase 4 (Typed links)       ─ deferred until 1+2 prove out
```

**Critical path:** Phase 1 → Phase 2 → Phase 5. Phase 3 can run in parallel
after Phase 1 lands. Phase 6 is cost-gated and independent (its result may
swap the extractor model used in Phase 2, but Phase 2 ships against current
Haiku first). Phase 4 (links) is the most complex change and is deferred until
the foundation is stable.

**Rationale:** Phases 1+2 are the structural fix for the audit's headline
finding (53% unverifiable). They must ship together — new fields without a
verification pipeline are decoration; a verification pipeline without fields
has nothing to write into. Phase 5 needs Phase 2's verification logic to run a
drift sweep at all.

## 3. Phase 1 — Schema groundwork

**Goal:** Memory record gains the fields that v2 depends on. Atomic schema
bump, backwards-compatible reads.

### 3.1 Schema additions to the memory record

| Field | Type | Notes |
|---|---|---|
| `anchors` | array of `{type, ref, line?}` | `type` ∈ {`file`, `commit`, `zotero`, `url`}; required for guidance categories per change A |
| `verified` | string | `true` / `false` / `pending` / `stale` per change E.2 and G |
| `links` | array of `{relation, target_id}` | Phase 4 populates; field exists from Phase 1 |
| `why` | string (optional) | Change B; required for guidance categories |
| `how_to_apply` | string (optional) | Change B; required for guidance categories |

`VALID_CATEGORIES` gains `feedback` (change Q6 decision). Lone `preference`
entry re-categorised as `feedback` in Phase 5 step 2.

### 3.2 Files to modify

- `hooks/extraction-hook.py` — `VALID_CATEGORIES`, `format_memories`,
  `EXTRACTION_PROMPT` (just to surface new fields; *enforcement* lands in
  Phase 2)
- `commands/remember.md` — JSON example, argument parsing for new optional
  fields (`anchor:`, `why:`, `how_to_apply:` token prefixes)
- `scripts/schema.sql` — `ALTER TABLE memories ADD COLUMN` for each new
  field; rebuild `active_memories` view
- `scripts/memory_mcp.py` — `_row_to_memory` passes new columns through
- `scripts/fetch-memories.py` — JSONL load + filter handles missing fields
  gracefully (treats missing as null)
- `scripts/sync-to-postgres.py` — handles new fields on insert

### 3.3 Backwards compatibility

Old entries (~25,581 existing) have none of the new fields. Read paths must
treat absent fields as null and not penalise old entries in recall ranking
solely for missing v2 fields. Phase 5 (bulk flag) introduces explicit
de-weighting; until then, old entries rank as they did before.

### 3.4 Effort: 1–2 sessions

## 4. Phase 2 — Anchor + verification pipeline

**Goal:** The structural fix. New writes land with anchors, anchors are
checked, `verified` and `confidence` are bound to the result.

### 4.1 Extraction-prompt update (change A)

`EXTRACTION_PROMPT` in `hooks/extraction-hook.py` gains:

- Explicit instruction: anchors must come from the transcript verbatim, never
  invented. If no anchor present, lower confidence or reword the memory to
  drop the false precision.
- Per-category anchor requirements: `decision`, `progress`, `architecture`,
  `gotcha`, `provenance`, `completion` *must* have at least one anchor;
  others optional.
- Demand structured `why` / `how_to_apply` for guidance categories per
  change B.

### 4.2 New module: `scripts/anchor_verify.py`

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
  `pending` if any check timed out.

Fail-soft: never reject the memory. Verification status is recorded; recall
ranking respects it.

### 4.3 Repo-set helper (change G)

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

### 4.4 Confidence binding (change F)

In `format_memories`, after `anchor_verify.verify_memory()` returns:

- `verified == "true"` *and* guidance-category fields complete → `confidence = "high"`
- `verified == "true"` but structural fields incomplete → `confidence = "medium"`
- `verified == "pending"` → `confidence = "medium"`
- `verified == "false"` or no anchors → `confidence = "low"`

Haiku's self-rated `confidence` is discarded.

### 4.5 Hook integration

`hooks/extraction-hook.py` main flow becomes:

1. Parse transcript.
2. Extract via Haiku (or whichever model Phase 6 selects).
3. For each extracted memory: `anchor_verify.verify_memory()` (sync, fast).
4. `format_memories` binds `confidence` and `verified`.
5. Append.

Existence-check latency estimate: `stat` is microseconds; `git rev-parse` is
~5ms on a warm repo. At ~3–5 anchors per memory × ~3 memories per
extraction = ~45 anchor checks per hook run ≈ 250ms worst case. Negligible
vs. the Haiku call itself.

### 4.6 Effort: 2–3 sessions

## 5. Phase 3 — Conscious "Claude can save" mode (change D)

**Goal:** Claude gains an autonomous capture trigger.

### 5.1 Directive

Add a section to `global-claude-md/memory-system-reference.md` (extracted
from the design-doc change D criteria) covering:

- *When to fire* — user articulates a durable preference/constraint; a
  non-obvious decision is made with rationale; an approach notably succeeds
  or fails; an error mode emerges with a correction.
- *Announce format* — `Saved to memory: [category] — [summary]`. Exact
  string so the COMMAND_MARKERS extension can pattern-match.
- *Execute* — follow the `/remember` procedure: parse, normalise tags,
  generate ID, append to JSONL. Including the v2 fields (anchors etc.).

### 5.2 COMMAND_MARKERS extension

`scripts/_command_markers.py` gains the autonomous-save announcement prefix
so `extraction-hook.py` skips those assistant turns and avoids double-capture.

### 5.3 Optional: brief mention in `global-claude-md/shared.md`

A one-line pointer to the criteria so the autonomous-save behaviour is
discoverable from the global CLAUDE.md, not buried in the reference doc.
Watch the 170-line cap.

### 5.4 Effort: 1 session

## 6. Phase 4 — Typed links (change C)

**Goal:** Memory corpus becomes a graph, not a bag.

**Deferred until Phases 1+2 prove stable** — links depend on the v2 schema
and on the verification pipeline producing trustworthy `verified` status to
gate link creation.

### 6.1 Mechanisms (per design-doc change C)

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

### 6.2 Effort: 3–4 sessions

## 7. Phase 5 — Migration (design-doc section 4)

**Goal:** Existing 25k corpus migrated to v2 schema state without retroactive
anchor pass (deferred unless drift sweep shows it warranted).

Depends on Phase 2 verification pipeline.

### 7.1 Targeted schema fix (Section 4 step 2)

- Add `feedback` to `VALID_CATEGORIES` in
  `hooks/extraction-hook.py` and `commands/remember.md`.
- Re-categorise memory `2026-04-18-f9944e9bf2a3` (lone `preference`) as
  `feedback`. One-line JSONL edit; preserve `id`/`session_id` etc.

### 7.2 Periodic drift sweep (Section 4 step 3)

New script `scripts/drift-sweep.py`:

- Iterates the whole corpus.
- For each entry with anchors, calls `anchor_verify.verify_memory()`.
- Updates `verified` status; if anchor previously resolved and now does not,
  applies the revitalisation-vs-staleness distinction (change G): permanent
  categories → `verified: stale` (preserve, mild de-weight); transient
  categories → `verified: false` (stronger de-weight).
- Quarterly cron (or systemd timer). Logs summary.

### 7.3 Bulk flag (Section 4 step 4)

One-off script `scripts/bulk-flag-unverified.py`:

- For permanent-category entries with no anchors, set `verified: false`.
- Run once after Phase 2 lands.

### 7.4 Reassess (Section 4 step 5)

Hold open. After the sweep + bulk-flag run, evaluate whether a retroactive
anchor pass on high-value permanent categories is worth the API cost.

### 7.5 Effort: 1–2 sessions

## 8. Phase 6 — Extractor-model bake-off (change E.4)

**Goal:** Empirically decide whether Haiku 4.5 remains the right extractor,
or whether Gemini 2.5 Flash or Sonnet 4.6 wins on the anchor-recall /
confabulation / cost trade-off.

**Cost-gated.** Per global CLAUDE.md API Call Review Gate, the bake-off
plan must be presented for approval *before* any API spend, with: model
set, sample size, total call count per model, cost per call (precisely
calculated from current pricing — do not guess), total cost. Approval for
the bake-off does not imply approval for ongoing use of the winner.

### 8.1 Methodology (subject to approval)

- Sample N representative recent sessions (target N=30, post-4.7 cohort).
- For each session, re-extract with: Haiku 4.5 (current), Gemini 2.5 Flash,
  Sonnet 4.6.
- Metrics per model: anchor recall (against a hand-coded ground truth on
  ~5 sessions), per-memory unverifiable rate (run extracted memories
  through Phase 2 `anchor_verify`), per-call latency, per-call cost.
- Total calls: 30 × 3 = 90 + cost-of-pre-flight pilot.

### 8.2 Files

- `scripts/extractor-bakeoff.py` — one-off; reads the session sample,
  invokes each model, writes a comparison report.

### 8.3 Outcome

Either retain Haiku or swap to the winner by changing `HAIKU_MODEL` in
`hooks/extraction-hook.py` (and renaming the constant).

### 8.4 Effort: 1 session prep + 1 session run+analysis (after cost approval)

## 9. Cross-cutting concerns

### 9.1 Backwards compatibility

- New fields are optional everywhere. JSONL readers must tolerate missing
  fields. Postgres `ADD COLUMN` uses default null.
- Recall ranking must not penalise pre-v2 entries solely for missing v2
  fields *until* Phase 5 explicit bulk-flag pass.

### 9.2 Postgres migration

- `ALTER TABLE memories ADD COLUMN` for each new field. Default null. Fast
  on a 25k-row table.
- Rebuild `active_memories` view to expose new columns.
- Consider GIN indexes on JSONB `anchors` and `links` arrays once queries
  need them (defer until a query pattern emerges).
- Back up the database (`pg_dump claude_memories`) before any `ALTER`.

### 9.3 Tests

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
- Dependencies: add to the existing `venv/` requirements file.
- CI/CD: **deferred** to the future-extensions doc (local-first repo, manual
  test runs are acceptable for now).

**Test plan — what gets coverage**

Unit tests (pure functions, dependencies mocked):

- `tests/test_anchor_verify.py` — `verify_file` (current path, git-history
  path, missing, repo-set traversal); `verify_commit` (current branch,
  history, partial-hash, missing); `verify_zotero` (mocked API hit/miss/
  offline → `pending`); `verify_memory` (all-resolve, any-fail, any-pending,
  malformed, empty anchors).
- `tests/test_repo_set.py` — discovery walks expected roots, respects depth
  bounds, caches correctly, lazy-refresh on miss; `repo_set_for` orders
  decoded path first.
- `tests/test_normalise_tags.py` — covers existing `normalise_tag` and
  `normalise_tags` logic (currently untested); plural/underscore/uppercase/
  punctuation cases.
- `tests/test_confidence_binding.py` — change F rubric maps all
  `verified` × structural-completeness combinations correctly.
- `tests/test_project_decode.py` — `decode_project` round-trip,
  edge cases (paths with hyphens, submodules).

Integration tests (real filesystem in `/tmp`, mocked external APIs):

- `tests/test_extraction_hook.py` — full round-trip on a fixture transcript:
  parse → Haiku-mocked → format → verify (against a fixture repo) → bind →
  append → JSONL is valid → cursor advances.
- `tests/test_remember.py` — `/remember`-style invocation with all new
  token prefixes (`anchor:`, `why:`, `how_to_apply:`); JSON record
  validates; vocabulary updates.
- `tests/test_drift_sweep.py` — dry-run mode against a fixture corpus does
  not mutate; reports expected DRIFT/STALE counts; revitalisation-vs-
  staleness distinction applied per change G.
- `tests/test_bulk_flag.py` — applies `verified: false` to the right rows;
  idempotent on second run.
- `tests/test_jsonl_append.py` — concurrent appends preserve all records
  (covers the existing `_shared_locked_append_fd` flock dance, currently
  untested).
- `tests/test_command_markers.py` — extraction hook skips autonomous-save
  announcement turns (Phase 3); `/remember` exchanges still skipped.

Smoke tests (do things still start / parse):

- `tests/test_compose_global.py` — `compose-global-claude-md.sh` produces
  output under 170 lines and contains all expected sections.
- `tests/test_python_syntax.py` — every `.py` in `hooks/` and `scripts/`
  compiles (catches typos before runtime).

Phase 4 tests (added with Phase 4):

- `tests/test_link_gardening.py` — deterministic output on fixture corpus;
  auto-apply threshold respected.
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

**Total estimated test files at end of v2:** ~14. **Effort:** ~1 session
to bootstrap pytest infra + write the first test file with realistic
fixtures; subsequent test files are ~30–60 minutes each, written
alongside the code they cover, not as a post-hoc batch.

Deferred test-tooling extensions (CI, property-based testing, performance
benchmarks, coverage tooling) live in
`planning/memory-system-v2-future-extensions.md`.

### 9.4 Documentation

- `global-claude-md/memory-system-reference.md` needs updating after each
  phase (schema additions, conscious-save criteria, link relations).
- `commands/remember.md` updated for new token prefixes and JSON shape.
- A short v2 architecture note in
  `global-claude-md/infrastructure-reference.md` would help future Claudes
  navigate.

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Postgres migration breaks recall | Low | High | Backup + rollback plan; test on a copy first |
| Hook latency degrades from existence checks | Low | Medium | Measured: ~250ms worst case, negligible vs. Haiku call |
| Bake-off ongoing cost too high | Medium | Medium | Cost gate before any spend; Sonnet may be priced out |
| /remember backwards compat — old invocations | Low | Low | New fields are optional; old commands still work |
| Schema drift between extraction-hook and /remember | Medium | Medium | Land schema changes atomically; reference single source of field list |
| Anchor verification false-negatives (file renamed mid-session) | Medium | Low | Fail-soft, drift sweep catches later |
| Auto-memory MD system still gets written despite CLAUDE.md directive | Medium | Low | Monitor `~/.claude/projects/.../memory/` after a few sessions; tighten if needed |

## 11. Pre-implementation actions

Before Phase 1 starts:

1. **Backup memories.jsonl + tag-vocabulary.txt** to `archive/pre-v2/`
   (data submodule).
2. **Backup the Postgres DB**: `pg_dump claude_memories > backup-pre-v2.sql`.
3. **Decide on tests** (section 9.3) — yes/no/deferred.
4. **Bake-off (Phase 6) cost estimate** — only when ready to run that phase.
   Not a Phase 1 blocker.

## 12. Out of scope / explicitly deferred

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
