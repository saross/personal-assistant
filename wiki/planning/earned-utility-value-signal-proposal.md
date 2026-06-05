# Earned-utility value signal — scoping & design (item 16 / P9 (b))

**Created:** 2026-06-05 (Workstream B, out-of-hours). **Status:** SCOPING /
DESIGN ONLY — no code changed, no live change, no API. **Origin:** P9 closed
its part (a) (recall displays now show honest `verified` state, not the
misleading "Confidence: low"). P9 (b) is the next, deeper question Shawn
posed: can we build a *true value* signal — distinct from `verified`/anchored —
from **earned utility** (what actually gets surfaced/used), so that
"never surfaced in N months" becomes a value/archival signal? This document
scopes that. It is the analogue of the item-13 retention proposal and the
P3 extraction proposal: **diagnose + design + push back where the evidence
warrants, do NOT touch the live paths autonomously.**

Plan reference: `wiki/planning/memory-write-path-plan.md` §5 item 16, §6a P9.

---

## 1. What item 16 asks (verbatim from the plan)

> **Memory utility/access tracking** — log what gets surfaced/recalled;
> never-surfaced-in-N-months → archival candidate.

And the P9 design recommendation that revived it:

> A *true* value signal can't come from LLM self-rating (v2 abandoned it for
> exactly this reason); the principled source is **earned utility — track
> what actually gets surfaced/used**, orthogonal to "anchored".

The promise is real: `confidence` collapsed into a verification echo
(P9 finding), and `verified`/`anchors` measure *checkability*, not *worth*.
Earned utility is the one signal in the system that could measure worth
**behaviourally** — without asking an LLM to rate itself. That is exactly why
it is worth scoping carefully rather than building on the first plausible shape.

---

## 2. Evidence — what the surfacing paths actually log today (measured at source, 2026-06-05)

There are **three** paths by which a memory reaches a session. Re-derived from
the live code, not from the carry-forward premise:

| Path | Trigger | Pool it draws from | Log file | What the log records |
|---|---|---|---|---|
| **Session-start digest** | every session start (automatic) | **verified-true in-window only** (`digest.py:577,604` → `rank_verified`) + anchored-preferred fallback | `data/logs/digest.log` | aggregate per firing: `bytes`, `shown` (count), `verified_available`, `new/updated/forgotten`, `fallback/focus/scoped` — **no IDs** |
| **Autonomous depth-fetch** | model chooses to fetch (`fetch-memories.py`) | whole `active_memories` view (any memory) | `data/logs/fetch-memories.log` | per invocation: selector *names*, `limit`, `results` (count) — **no IDs** |
| **`/recall` command** | Shawn or model explicitly recalls | reads `memories.jsonl` directly | `data/logs/fetch-memories.log` (via `log-recall.py`, `source=recall`) | selector *names*, `limit`, `results` (count) — **no IDs** |

**The central instrumentation finding** (refines the carry-forward "build on
the existing recall logging"): all three logs record **counts, not memory
IDs**. The surfaced records are *in hand* at every log site —
`DigestResult.entries` is the list of surfaced dicts (`digest.py:109,117`),
`_log_invocation(args, results)` receives the `results` list
(`fetch-memories.py:805`) — but each site writes only `len(...)`. So the
existing logs are the right **sites**, but **cannot today attribute surfacing
to specific memories.** Item 16 is blocked on a per-ID capture that does not
yet exist.

**Corroborating facts (at source):**

- The memory record schema has **no** `surfaced_count` / `last_surfaced_at` /
  `access_count` field (grep over `memories.jsonl` = 0). Earned utility is
  genuinely un-instrumented; there is nothing at the record level to build on.
- `fetch-memories.log` holds **6 lines total** (first 2026-05-30). The active
  paths have essentially **no history yet**.
- `digest.log` holds ~26 firings over ~6 days (~4–5/day), ~4 entries each.

---

## 3. The reframe — three honest constraints (this is the substance)

### 3.1 "Surfaced" is earned *retrieval*, not earned *use* — a proxy with a ceiling

The log can prove a memory was **returned** to a session. It cannot prove the
memory **informed the response**. True "use" would require attributing the
generated text back to the source memory — the same hard problem as the
prose-welding detection deferred in the §8 work (Tier C). So "earned utility"
here is really **earned retrieval**: a *proxy* for value, with a real ceiling.
This is the same honesty that killed the P3 confidence premise — name the
ceiling up front rather than overclaim the signal.

### 3.2 Passive surfacing (digest) and active retrieval (fetch/recall) are different signals — do not pool them

- **Digest surfacing is passive and anchored-biased.** The digest draws only
  from the **verified-true in-window pool** (~5–6 % of the corpus is anchored;
  `verified_available` runs ~470–540 in the logs). The ranker is deterministic
  on `verified` + tag-overlap + recency. So digest-surfacing counts concentrate
  on the **same few hundred anchored-and-recent memories, repeatedly** — they
  largely **re-derive the anchor signal**, not independent worth. A memory
  shown 50× by the digest mostly means "anchored and recent," which we already
  know from `verified`.
- **Active retrieval is intent-driven and unconfounded by the anchored pool.**
  `fetch-memories` / `/recall` can return *any* `active_memories` record, not
  just verified-true ones, and they fire because the model or Shawn *decided*
  the memory was needed. This is the signal closest to real value.

**Design consequence:** an earned-utility score must **weight active retrieval
far above passive digest surfacing** (or exclude digest from "value" entirely
and treat it only as reach/exposure). Pooling them would let the anchored-5 %
bias dominate the very signal we built to escape it.

### 3.3 Absence-of-surfacing is confounded — "never surfaced → archive" is the P3/P9 trap, inverted

The plan's literal framing ("never-surfaced-in-N-months → archival candidate")
turns **absence** into an eviction trigger. Absence is heavily confounded:

- The digest **structurally cannot surface 94 % of the corpus** (unanchored →
  never in the verified-true pool). "Never surfaced via digest" would therefore
  read as "low value" for exactly the **unanchored-but-valuable** population P9
  warned against suppressing. This is the **same trap as the P3 confidence-gate
  and the P9 confidence-as-value confusion**: keying on anchor-presence and
  calling it value.
- The active logs are **nearly empty** (6 fetch lines; recall just instrumented
  2026-06-02). Today ~100 % of the corpus is "never actively retrieved," so the
  absence signal has **zero discriminating power** — using it would be
  equivalent to "archive everything," gated only by the decay clock that item 13
  already runs. It adds nothing over decay and risks a great deal.

**Recommendation: invert the polarity.** Do not use absence to *condemn*; use
**presence to *protect***. Same data, opposite and safe direction. A memory
that was *actively retrieved* recently has proven live utility its
category-decay clock cannot see, so **spare it from the next archival sweep**.
This:

- only ever **protects**, never newly condemns → it **cannot** suppress the
  unanchored 93 % (the confound bites only when absence drives eviction);
- uses the **active** signal (§3.2), unconfounded by the anchored-pool bias;
- composes cleanly with the existing decay/archival machinery (item 13) as a
  **stay-of-execution**, not a new death sentence.

---

## 4. Architecture — append-only side-log + offline aggregation (NOT a record field)

Two candidate shapes; the first is rejected on evidence.

### 4.1 Rejected: a per-memory `surfaced_count` / `last_surfaced_at` field on the record

- **P8 makes it invisible where it matters.** `sync-to-postgres.py` is
  INSERT-only (`ON CONFLICT DO NOTHING`) and does not reconcile existing-row
  field changes (P8, surfaced 2026-06-05). The digest and autonomous-fetch
  paths read **PostgreSQL** (`active_memories` view), so a count written back
  onto the JSONL record would **never reach the readers** until a manual
  `rebuild-postgres`. The signal would be stale by construction on the very
  paths that consume it.
- **It rewrites the hot corpus on every surfacing.** Incrementing a field on
  every session start (≥4 records/firing) means a guarded bulk-rewrite of the
  live-append `memories.jsonl` continuously — write-amplification, lock
  contention with extraction, and exactly the kind of hot-path mutation the
  `_bulk_rewrite_guard` / `lock_jsonl_for_rewrite` machinery exists to make
  *rare*. Wrong tool.

### 4.2 Adopted: an append-only `surfaced.log`, aggregated on demand

Mirror the established pattern — `confab-flags.log`, `fetch-memories.log`,
`digest.log` are all append-only side-logs aggregated by a read-only reporter
(`memory-health-report.py`). One more line per surfaced ID:

```
<iso-timestamp>\tid=<memory-id>\tpath=digest|fetch|recall\trank=<n>\tsession=<id?>
```

- **Capture sites (the IDs are already in hand — §2):**
  - digest → in `build_session_digest` (`session-start-retrieval.py:1222`),
    iterate `result.entries`, one line each, `path=digest`.
  - autonomous fetch → in `_log_invocation` (`fetch-memories.py:805`),
    iterate `results`, `path=fetch`.
  - `/recall` → the one gap: `recall.md` passes only `--results <N>` to
    `log-recall.py`; capturing recall IDs needs the command to **emit the
    surfaced IDs** to the logger (a new `--ids` pass-through). Small, but it is
    the one site where the ID is not already at the existing log call.
- **Aggregation:** a read-only pass (a new `memory-health-report.py` section,
  or a standalone `scripts/surfacing-stats.py`) scans `surfaced.log` →
  per-memory `{active_retrievals, digest_exposures, last_active_at,
  last_any_at}`. No PG write, no record mutation → **P8 does not apply**, and
  it is safe to run during concurrent extraction (same posture as
  `memory-health-report.py`).
- **Privacy:** consistent with the existing logs. They deliberately record
  selector *names* not query text; a memory **ID** is metadata about Shawn's
  *own* record (it already appears throughout the corpus + PG), not external
  search content. One-line note in the design, not a blocker.
- **Volume (aggregate check, per CLAUDE.md):** ~20 digest ID-rows/day +
  a handful of active rows ≈ <300 rows/day even at 10× today's load. A months-
  long log is a few MB; aggregation is a linear scan. No capacity concern.

---

## 5. The safe use, concretely — utility as a stay-of-execution on item 13

The only consumption this proposal endorses (and only after data accrues, §6):

> In the item-13 / `monthly-archive.py` sweep, before evicting a past-decay
> record, check `surfaced.log`: if it was **actively retrieved** (`path` in
> {fetch, recall}) within the last **K** days, **spare it this cycle** and
> re-evaluate next month.

Properties: reversible (it only *delays* archival, never deletes); protective-
only (cannot condemn the unanchored majority); reuses the existing, twice-
audited sweep; needs no PG write. Digest exposure is **excluded** from the
spare test (§3.2 — it re-derives the anchor signal); only *active* retrieval
earns a stay. An optional, weaker secondary use: surface per-memory active-
retrieval counts in the `/memory-health` report as a descriptive "most-used
memories" view — observational, drives no automated action.

**Explicitly NOT endorsed:** "never surfaced in N months → archive" as a
standalone trigger (§3.3). If Shawn ever wants an absence-driven eviction, it
must be gated behind (a) months of accrued active-retrieval history and (b) a
long log-only dry-run, exactly as the P3 true-delete was gated — and even then
it should fire only on the **anchored** subset, where absence is not confounded
by pool-ineligibility.

---

## 6. Recommended sequence — instrument now (forward-only), design consumption later

The signal needs a **long accrual window** before it discriminates (§3.3: the
active logs are near-empty today). The cheapest, lowest-risk move is to **start
accruing now** and defer all consumption logic until there is data — the same
forward-only instrumentation pattern already used for confab-flags
(2026-06-02) and recall-logging (2026-06-02), neither of which rescued the
2026-06-13 §8 review and both of which were shipped anyway to start the clock.

- **Stage 1 — instrument (cheap, no consumption, no risk, no API).** Add the
  per-ID `surfaced.log` writes at the three capture sites (§4.2) + the
  `--ids` pass-through for `/recall`; add the read-only aggregator. Behaviour-
  preserving: best-effort writes that never raise (the confab-flags/recall
  contract), no change to what any path *surfaces*, no consumption. This is
  the only part worth building soon — and only if Shawn greenlights it as an
  out-of-hours increment.
- **Stage 2 — consume (deferred until ≥ a few months of active-retrieval
  history exist).** Design and wire the stay-of-execution into the archival
  sweep (§5). Do not design the threshold (K days) until the accrued
  distribution is visible — picking K now would be guessing, the mistake §3.3
  warns against.

**This is a design pass; nothing here is yet a build.** Stage 1 is scoped and
ready to build on Shawn's word, but is not started.

---

## 7. Open calls for Shawn

1. **Build Stage-1 instrumentation now, or hold at design?** Stage 1 is a
   small, forward-only, no-API increment that starts the accrual clock; its
   only cost is that the signal is useless until months pass. Hold = no log
   exists when Stage 2 is eventually wanted (clock starts later). Provisional
   lean: **build Stage 1** (cheap, and the clock only ever helps once started).
2. **Log shape:** a **new `surfaced.log`** (clean separation, recommended) vs
   extending `digest.log`/`fetch-memories.log` with an `ids=` field (fewer
   files, but bloats lines and complicates the existing §8 parsers). Lean: new
   file.
3. **`/recall` ID capture:** worth the `--ids` pass-through (§4.2) so the
   strongest-intent path is covered, or accept that `/recall` contributes only
   a count and lean on `fetch`/digest? Lean: add it — `/recall` is the highest-
   value-per-event signal.
4. **Aggregator home:** a new section in `memory-health-report.py` (surfaces in
   the weekly review automatically) vs a standalone `scripts/surfacing-stats.py`.
   Lean: a `--surfacing` section in the health report, off by default like
   `--tier-c`.

---

## 8. Guardrails (carried from the prior write-path work)

- **Append-only side-log, never a record-field write** (§4.1 — P8 +
  hot-corpus rewrite).
- **Presence protects; absence never condemns** (§3.3). No absence-driven
  eviction without a long dry-run, and only on the anchored subset.
- **Active retrieval ≫ passive digest exposure** in any value score (§3.2).
- **Best-effort instrumentation** — every log write swallows its own failures;
  it must never degrade the surfacing path (the confab-flags / recall-log
  contract).
- **No API, no live-surfacing change** anywhere in Stage 1; Stage-2 thresholds
  wait for data.
- **Honest ceiling:** this measures earned *retrieval*, a proxy, not earned
  *use* (§3.1) — label it as such wherever it is displayed.
