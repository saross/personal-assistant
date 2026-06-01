# Memory retention policy — item 13 design proposal

**Created:** 2026-06-01 (Workstream B, RETENTION thread).
**Status:** ✅ **APPROVED 2026-06-01** — all six decisions signed off (see §9).
Design phase complete; execution (build `scripts/archive-memories.py` →
dry-run → gated `--apply` in a quiet window) is the next step.
**No mutation in this phase.** No Application Programming Interface (API) calls.
Execution (the archival sweep) is a separate, explicitly-gated step.
**Plan parent:** `wiki/planning/memory-write-path-plan.md` (item 13).

All record counts below were **re-derived at source on 2026-06-01** from
`data/memories/memories.jsonl` (30,277 records, 26.2 MB). They are
point-in-time; the corpus grows ~260/day. Re-run the queries in §9 before
executing.

---

## 1. What this is

The corpus is ~30 k records and grows ~260/day, dominated by ephemeral
categories. This proposal designs a **per-category retention/archival
policy**: which categories are evicted from the live hot file once stale,
on what window, to a cold store that keeps them retrievable but out of the
live append/scan/sync loop. **Archive, never delete** (per the
archive-don't-delete rule).

The standing caveat from items 20/21 holds and is load-bearing: **do NOT
prune on `verified=false`.** The residual `verified=false` set (~224) is
mostly genuinely-gone files, not wrong memories. This policy targets
**category retention**, not deletion-by-verification-status.

---

## 2. What already exists (read before reinventing)

The crucial reframe, which reshapes the whole design:

> **Decay already exists. Archival does not.** "Decay" is a *read-time*
> filter; "archival" is a *physical eviction* from the hot file. They are
> different operations and the gap between them is exactly the lever.

Concretely:

- **`category_config` (`scripts/schema.sql:195`)** defines a per-category
  `decay_days`. Today: `progress`/`context`/`commitment`/`blocker_real` 30,
  `waiting_for` 14, `system_friction` 60, `completion`/`system_success` 90,
  `gotcha`/`pattern` 180; everything else `NULL` (permanent).
- **`active_memories` view (`scripts/schema.sql:262`)** dynamically excludes
  any record past `created_at + decay_days` (commitments from
  `COALESCE(deadline_at, created_at)`). **Recall already hides past-decay
  records** — `scripts/fetch-memories.py` queries this view first.
- **`scripts/apply-decay.py`** materialises that same predicate as
  `is_active = FALSE` in PostgreSQL. **PostgreSQL-only; it never touches the
  canonical JavaScript Object Notation Lines (JSONL).**
- **Per-record `decay_days` override** exists on the JSONL but is set on
  only **15** records — effectively unused. Canonical decay lives in
  `category_config`, not per record.

So the past-decay records are **already invisible to recall** (via the view)
— yet they still sit in the live `memories.jsonl`, which is the
extraction-hook append target, the daily-sync input, the git-tracked object,
and the recall **fallback** source (`fetch-memories.py`'s JSONL-grep path,
used when PostgreSQL is down, is **decay-blind** and returns them). They are
dead weight in the hot file with no recall benefit.

**No memory-archival tool exists yet.** Note the pointer in the item-13
brief calling `scripts/bulk-archive.py` "the archival sweep" is **stale** —
that script archives *Claude Code sessions* into `~/cc-archives/`, not
memories. The execution tool for this item must be **built** (see §8); the
correct template is `scripts/recover_anchors.py` (item 21b-act), not
`bulk-archive.py`. Likewise `scripts/push-archives-to-r2.sh` pushes the
*session* archive to Cloudflare R2; memories need no R2 path (see §7).

---

## 3. Evidence (re-derived at source, 2026-06-01)

### 3.1 Age distribution (all 30,277 records)

| Age (days) | Records |
|---|---|
| 0–30 | 6,790 |
| 31–90 | 16,052 |
| 91–180 | 7,102 |
| 181–365 | 333 |
| 365+ | 0 |

The corpus is young (nothing older than a year). Growth, not age, is the
problem.

### 3.2 Per-category: total, records past the *current* decay window, weight

| Category | Total | Past current decay | Current decay_days | Live MB |
|---|---:|---:|---|---:|
| decision | 6,835 | 0 | permanent | 6.31 |
| **progress** | 5,164 | **3,902** | 30 | 4.12 |
| gotcha | 3,054 | 27 | 180 | 2.67 |
| architecture | 2,707 | 0 | permanent | 2.43 |
| **commitment** | 2,071 | **1,528** | 30 (from deadline) | 1.60 |
| **context** | 1,621 | **1,248** | 30 | 1.32 |
| pattern | 1,468 | 15 | 180 | 1.27 |
| source_insight | 1,113 | 0 | permanent | 1.01 |
| error_mode | 947 | 0 | permanent | 0.85 |
| prompt_effectiveness | 788 | 0 | permanent | 0.69 |
| limitation | 715 | 0 | permanent | 0.61 |
| methodology | 706 | 0 | permanent | 0.66 |
| self_reflection | 385 | 0 | permanent | 0.35 |
| **waiting_for** | 381 | **285** | 14 | 0.28 |
| completion | 354 | 76 | 90 | 0.32 |
| surprise | 354 | 0 | permanent | 0.31 |
| hypothesis | 315 | 0 | permanent | 0.28 |
| provenance | 261 | 0 | permanent | 0.24 |
| **blocker_real** | 226 | **162** | 30 | 0.19 |
| system_success | 223 | 51 | 90 | 0.19 |
| system_evolution | 170 | 0 | permanent | 0.15 |
| system_friction | 142 | 76 | 60 | 0.12 |
| openness | 113 | 0 | permanent | 0.10 |
| ethics | 50 | 0 | permanent | 0.04 |
| contact | 43 | 0 | permanent | 0.03 |
| feedback | 28 | 0 | permanent | 0.04 |
| slip | 21 | 0 | permanent | 0.02 |
| blocker_excuse | 21 | 0 | permanent | 0.02 |

---

## 4. Two separable levers

The single most useful structural insight for sign-off: there are **two
independent decisions**, and conflating them overstates the risk.

- **Lever A — behaviour-preserving sweep.** Archive records *already past
  their existing decay window*. Because recall already excludes them, this
  changes **nothing** about what `/recall` or the digest returns through the
  primary (PostgreSQL) path. It only stops carrying dead weight in the hot
  file. **No new windows; no policy change.** This is the safe ~25 % win.
- **Lever B — retention-policy redesign.** Change *which categories* are
  ephemeral and *what windows* they decay on. This **does** change recall
  (a tighter `progress` window hides more; promoting `gotcha` to permanent
  keeps more). This is where per-bucket sign-off genuinely matters.

You can approve A without B, or both. A is reversible (records are in the
git-versioned archive partition; restore = move the line back). B is a
policy change applied going forward by editing `category_config`.

---

## 5. Lever A — behaviour-preserving sweep

Archive every record already past its current `category_config.decay_days`
(commitments measured from `deadline_at`, matching the view).

**Volume: 7,370 records (5.62 MB), ~24 % of the corpus.**

| Category | Records | MB |
|---|---:|---:|
| progress | 3,902 | 2.97 |
| commitment | 1,528 | 1.14 |
| context | 1,248 | 0.99 |
| waiting_for | 285 | 0.20 |
| blocker_real | 162 | 0.13 |
| system_friction | 76 | 0.06 |
| completion | 76 | 0.07 |
| system_success | 51 | 0.04 |
| gotcha | 27 | 0.02 |
| pattern | 15 | 0.01 |

**Effect on recall:** none via PostgreSQL (the `active_memories` view
already excludes these). The one honest behaviour *change* is the
degraded-mode JSONL fallback: it currently returns past-decay records
(decay-blind); after the sweep it will not — which makes the fallback
**consistent** with the primary path rather than diverging from it. Net:
behaviour-preserving for the path that matters, behaviour-correcting for the
fallback.

**Why do it even though recall already hides them:** the 5.62 MB live to all
of: every extraction-hook append (rewrite-lock contention window), every
daily-sync pass, the git object size of the `data` submodule, and the
recall fallback scan. Eviction shrinks all four with zero recall cost.

---

## 6. Lever B — retention-policy redesign (per-bucket)

Proposed three-tier structure. **The contentious cells are flagged ⚠ and
are the real subject of sign-off.**

### Tier P — Permanent (never archive)

Research value, guidance value, or accountability value. **No change** from
today's `NULL`:

`decision`, `architecture`, `source_insight`, `error_mode`,
`prompt_effectiveness`, `limitation`, `methodology`, `self_reflection`,
`surprise`, `hypothesis`, `provenance`, `system_evolution`, `openness`,
`ethics`, `contact`, `feedback`, `slip`, `blocker_excuse`.

### Tier E — Ephemeral, aggressive archival

Status/scaffolding with little value once stale. Keep current windows (they
are already sensible); the change is that past-window records are now
**evicted**, not merely hidden.

| Category | Current | Proposed window | Rationale |
|---|---|---|---|
| progress | 30 | **30** (or 14 ⚠) | Status updates; the firehose. 14 reclaims +442. |
| context | 30 | **30** | Background; ephemeral by definition. |
| waiting_for | 14 | **14** | Resolves once unblocked. |
| blocker_real | 30 | **30** | Transient external blockers. |

### Tier M — Medium ephemeral, archival on a longer window

Feed a downstream consumer (accountability, `/retro`) before becoming
redundant.

| Category | Current | Proposed window | Rationale |
|---|---|---|---|
| commitment | 30 (from deadline) | **30** | Resolved/stale 30 d past deadline; `slip` keeps the permanent broken-commitment record. |
| completion | 90 | **90** | Canonical closure is the weekly-review Completions section (since 2026-05-24); these are now redundant. |
| system_friction | 60 | **60** | Consumed by monthly `/retro`; archive after. |
| system_success | 90 | **90** | Consumed by monthly `/retro`; archive after. |

### ⚠ The one place I push back on the brief

The item-13 brief names **`gotcha`** (with `progress`) as an
aggressive-decay candidate. **I recommend against decaying `gotcha`
aggressively, and against decaying `pattern` aggressively.** Both are
**guidance-bearing** — they are in the extraction hook's `GUIDANCE_CATEGORIES`
(`feedback`, `decision`, `gotcha`, `methodology`, `pattern`, `error_mode`),
the set that earns a confidence bump and is meant to *steer* future work. A
`gotcha` ("X silently corrupts Y") is exactly the kind of memory whose value
*outlasts* a 30-day window. Empirically they are also not where the bloat is:
only **27** `gotcha` and **15** `pattern` records are past even their current
180-day window.

**Recommendation:** move `gotcha` and `pattern` to **Tier P (permanent)**,
or at most a long 365-day window — *not* aggressive decay. (At 90 days they
would reclaim 821 + 408 = 1,229 records, but at the cost of evicting live
guidance — a bad trade.) This is decision D3 in §9.

`progress`, by contrast, is the right aggressive target: 3,902 already past
30 days, no guidance role, pure status scaffolding.

---

## 7. Cold-store design

**Location.** A git-versioned archive partition inside the `data`
submodule, beside the live corpus:

```text
data/memories/archive/memories-archive-YYYY-MM.jsonl   # monthly partitions
```

Monthly partitioning mirrors the existing `tasks/done/YYYY-MM.md` and
`reports/weekly/` conventions, bounds file sizes, and makes "what was
archived when" trivially auditable. The `data` submodule already has an
offsite remote (`saross/pa-data`), so **git history is the durable archive**
— no Cloudflare R2 path is needed (R2 mirrors *session* archives, which are
not in git). Archived records are full-text greppable on disk.

**Recall exclusion.** Three points, all already satisfied or trivial:

1. The archived line is removed from live `memories.jsonl`, so the recall
   JSONL-fallback (which reads only that file) no longer sees it.
2. The PostgreSQL row is set `is_active = FALSE, decayed_at = NOW()` for the
   archived ids, so `active_memories` excludes it (it already did, by decay
   predicate; this makes it explicit and rebuild-safe).
3. The extraction hook and digest append/scan only the live file; archived
   records never re-enter the hot loop.

**Retrievability.** Add a `--include-archive` flag to `fetch-memories.py`
(and by extension `/recall`) that also greps the archive partitions when a
query explicitly asks for cold history. Default off. This keeps the archive
*retrievable on demand* but *out of the default surfacing path*, which is
exactly the contract ("excluded from recall but kept retrievable").

---

## 8. Execution design (for the gated step — NOT this phase)

Build `scripts/archive-memories.py`, modelled **closely** on
`scripts/recover_anchors.py` (the proven guarded-corpus-mutation template):

- **Dry-run default**; `--apply` required to mutate; `--category`/`--window`
  overridable for staged rollout (e.g. `progress` first, alone).
- **Guarded** by `_bulk_rewrite_guard.ensure_safe_to_rewrite` (origin==local
  on the `data` submodule, clean protected files, daily-sync flock) and
  wrapped in `lock_jsonl_for_rewrite` so concurrent appends drain and block
  for the rewrite window. Commit carries the `Rewrite-Class: bulk` trailer.
- **Minimal diff:** kept records written back **verbatim** (original line
  bytes); archived records appended **verbatim** to the month partition (no
  re-serialisation — preserve provenance exactly).
- **Audit trail:** an archival manifest (ids, category, age, source line) +
  the git commit in `data`. (Unlike `recover_anchors`, no `revisions` entry
  — the record is preserved unaltered in the partition, not edited.)
- **PostgreSQL:** surgical `UPDATE memories SET is_active=FALSE,
  decayed_at=NOW() WHERE id = ANY(...)` for archived ids. No delete (rebuild
  stays possible); no embedding work.
- **Staged:** run `progress` alone first, verify recall + digest unchanged,
  then the rest. Quiet window = corpus-clean state (flush via
  `scripts/daily-sync.sh` first; the guard blocks on a dirty corpus).

This is a corpus mutation → it runs **only after per-bucket sign-off**, in a
quiet window, never as part of design.

---

## 9. Decisions — ✅ signed off 2026-06-01

| # | Decision | Recommendation | **Resolution (2026-06-01)** |
|---|---|---|---|
| **D1** | Approve **Lever A** (archive the 7,370 already-past-decay records, behaviour-preserving)? | **Yes** — safe ~24 % reclaim, no recall change. | ✅ **Approved.** |
| **D2** | Adopt **Lever B** tier structure (§6) for `category_config`, going forward? | **Yes**, with D3 amendment. | ✅ **Adopted as proposed.** |
| **D3** | `gotcha` + `pattern`: aggressive decay (per brief) **or** permanent/365 d (my pushback)? | **Permanent** (or 365 d) — they are guidance. | ✅ **Permanent** — moved to Tier P. |
| **D4** | `progress` window: keep **30** or tighten to **14** (+442 records)? | **30** to start; revisit after watching one cycle. | ✅ **Keep 30 d.** |
| **D5** | Cold store = monthly partitions under `data/memories/archive/`? | **Yes** — git history is the durable offsite copy. | ✅ **Adopted.** |
| **D6** | Retrievability via `fetch-memories.py --include-archive` (default off)? | **Yes.** | ✅ **Adopted.** |

**Final policy (for the execution step):**

- **Tier P (permanent, never archive):** all of today's `NULL` categories
  **plus `gotcha` and `pattern`** (D3). `category_config.decay_days` for
  `gotcha`/`pattern` changes `180 → NULL`.
- **Tier E (aggressive):** `progress` 30 (D4), `context` 30, `waiting_for`
  14, `blocker_real` 30 — windows unchanged; past-window records now evicted.
- **Tier M (longer):** `commitment` 30 (from deadline), `completion` 90,
  `system_friction` 60, `system_success` 90 — unchanged; evicted past window.
- **Cold store:** `data/memories/archive/memories-archive-YYYY-MM.jsonl`.
- **Retrieval:** `fetch-memories.py --include-archive` (default off).
- **Staged rollout:** `progress` swept alone first; verify recall + digest
  unchanged before the rest.

Re-derive the live counts before executing (the corpus grows ~260/day):

```bash
# per-category total + past-current-decay, at source
venv/bin/python3 - <<'PY'
# (the §3.2 query — see this file's git history for the full script)
PY
```

---

## 10. Gates and guardrails (recap)

- **Design + mechanical archival are no-API.** If any embedding/LLM step
  appears (e.g. semantic dedup, item 15), **STOP** for the API review gate
  (model + batch + count + cost).
- **Archive, never delete.** Records move to the git-versioned partition;
  nothing is destroyed.
- **Corpus mutation is gated:** per-bucket sign-off + a quiet (corpus-clean)
  window; flush via `daily-sync.sh` first (the bulk guard blocks on a dirty
  corpus). Don't manually commit live `memories.jsonl`/`tag-vocabulary` —
  daily-sync owns it.
- **Do NOT prune on `verified=false`** — the residual (~224) is genuinely-gone
  files, not wrong memories (items 20/21).
- The **2026-06-13 §8 review** still gates enabling the Vector 2b/2c
  sentinels; this work does not perturb `~/.pa-digest-stage1`,
  `~/.pa-scratchpad-budget`, `~/.pa-digest-focus`, or that window.

---

## 11. Appendix — window sensitivity (the knob)

Records past window *W*, per candidate category (2026-06-01). Use this to
read the cost of any window choice in D3/D4.

| Category | 14 | 30 | 60 | 90 | 180 | 365 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| progress | 4,344 | 3,902 | 2,216 | 998 | 51 | 0 | 5,164 |
| context | 1,403 | 1,248 | 713 | 391 | 16 | 0 | 1,621 |
| waiting_for | 285 | 239 | 119 | 57 | 3 | 0 | 381 |
| blocker_real | 202 | 162 | 84 | 50 | 0 | 0 | 226 |
| commitment | 1,768 | 1,528 | 849 | 392 | 20 | 0 | 2,071 |
| completion | 256 | 208 | 127 | 76 | 0 | 0 | 354 |
| system_friction | 128 | 107 | 76 | 48 | 3 | 0 | 142 |
| system_success | 179 | 152 | 87 | 51 | 4 | 0 | 223 |
| gotcha | 2,635 | 2,354 | 1,512 | 821 | 27 | 0 | 3,054 |
| pattern | 1,226 | 1,076 | 718 | 408 | 15 | 0 | 1,468 |

(`commitment` measured from `deadline_at` where present, else `created_at`,
matching the `active_memories` view.)
