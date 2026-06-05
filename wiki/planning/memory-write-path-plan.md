# Memory system — write-path work plan

**Created:** 2026-05-31 (Workstream B). **Why now:** the read/surfacing path
is well-disciplined (Vector 2 / 2b / 2c); the write path — corpus health as it
scales — has had no work and is where the system is weak. This plan covers the
write-path work to pursue while the Vector 2 §8 review (2026-06-13) is pending.

## 1. Evidence (measured 2026-05-31, `data/memories/memories.jsonl`)

| Signal | Count | Reading |
|---|---|---|
| Total records | 29,944 | grows ~260/day |
| Pre-anchoring-epoch (`created_at` < 2026-05-16) | 25,916 (86.5 %) | unanchorable **by construction**, not suspect |
| Post-epoch | 4,028 | 1,129 anchored = 28 % of post-epoch |
| Anchored (any) | 1,129 (3.8 %) | earliest anchored 2026-05-16 (confirms epoch) |
| verified true / false / pending | 699 / 396 / 4 | false is anchored-but-unresolved |
| `verified=false` AND anchored | 397 | **noisy** wrongness signal (see §3) |
| Malformed commit refs (not a SHA) | 22 / 707 commit anchors (3 %) | extractor wrote strings like `rome-verification-script` as a commit `ref` |
| Exact duplicates (summary / content) | 2 / 1 | **negligible** — accretion is not literal duplication |
| `is_active=false` (forgotten) | 1 | correction loop essentially unused |
| Age | bulk 30–90 d; only 333 > 180 d | corpus is young |

## 2. The reframe — unverified ≠ wrong

The <4 % verification rate is **not** evidence that 96 % of the corpus is
wrong. Anchoring is a *forward-only* feature live since 2026-05-16, so 86.5 %
of records are unanchored purely because the machinery postdates them.
"Cut all unverified" would delete 86.5 % of the corpus for being older than
two weeks — amnesia, not hygiene.

## 3. There is no cheap, clean "wrong memory" signal

Every cheap signal is tiny, noisy, or structural-not-suspect:

- **`verified=false` anchored (397)** — mostly anchors that don't resolve from
  the check context (cross-repo refs, files deleted since, the 3 % malformed),
  **not** wrong content. The memory ("Rome count 65,435 verified…") is often
  fine; the *pointer* is stale/bad. Pruning on this deletes good memories.
- **Exact duplicates (2)** — dedup reclaims nothing; accretion is genuinely
  distinct (if low-value) atomic memories.
- **`is_active=false` (1)** — clean but tiny.
- **Malformed anchors (22)** — a real write-path bug, but small.
- **Pre-epoch unanchored (25,916)** — structural, not a wrongness signal.

**Verifying the mass cannot be done cheaply:** local re-resolution only touches
the 3.8 % that already carry anchors. The only path to verifying the back-corpus
is a retroactive LLM anchor-generation pass — **API-gated, thousands of calls,
a separate costed decision** (model + count + cost approval), never folded into
"pruning".

## 4. Strategy — structural, not a one-time purge

- **Safe + no-API (do soon):**
  - **Fix anchor-gen quality (item 11).** Validate at write time that a
    `commit` ref is a real SHA and a `file` ref exists; reject/flag malformed.
    Foundational — makes `verified` trustworthy as a downstream signal.
  - **Category retention policy (item 13).** Archive (NOT delete — per the
    archive-don't-delete rule) ephemeral categories (`progress` 5,093,
    `gotcha` 3,012) past an aggressive decay window, to a cold file. The real
    scale lever. Needs explicit per-bucket sign-off + care (live-append
    submodule).
- **At the source:** extraction selectivity (item 14) — fewer, higher-value
  memories; prevents accretion upstream of all cleanup.
- **API-gated, costed (deferred):** retroactive anchor-generation (item 6) to
  verify the back-corpus; write-time semantic dedup (item 15).

**Hard guardrails:** archive, never delete; no destructive write without
per-bucket approval; the corpus lives in the live-append `data` submodule, so
any corpus mutation must be done in a quiet window with explicit pathspecs.

## 5. Full backlog

**Tier 1 — high leverage, tractable**
1. ✅ Focus-aware + project-scoped digest (Vector 2c, shipped dark 2026-05-30).
2. Real pruning / TTL — archival sweep, not just a read-window.
3. Neutralise dead fixed-payload weight (harness auto-memory `MEMORY.md`;
   CLAUDE.md redundancy audit).

**Tier 2 — higher value, more work**
4. Activate the correction loop (`/forget`, `/update` actually used).
5. Consolidation / dedup pass (semantic — exact dups ≈ 0).
6. Grow forward anchor coverage (incl. the API-gated retroactive pass).
7. Replace the what-changed counter with something actionable.

**Tier 3 — cheap safety/observability**
8. Drift-sweep as a standing job (re-resolve the ~1,129 anchored).
9. ✅ **Verify the §8 measurement apparatus — DONE 2026-06-02** (`4db5a9d`).
   Verdict: only measurement (1) (digest bytes) is review-ready —
   `digest.log` clean/unconfounded, n=26, median 1491 B / p95 1499 B,
   0 over budget (but the 1500-byte HARD cap makes the thresholds
   self-fulfilling; (1) really measures how hard the cap binds).
   (2) invocation rates broken three ways — **no pre-ship baseline**
   (instrumentation `809a89f` shipped on enablement day; §2 baseline is
   bytes-only, unrecoverable); **/recall was uninstrumented** (reads
   `memories.jsonl` directly, never hit `fetch-memories.py` — fixed this
   session, see below); sparse. (3) **no verifier apparatus exists**.
   (4) subjective/qualitative. **Fix shipped:** `scripts/log-recall.py`
   (best-effort) + `recall.md` mandatory log step + `tier-2-retrieval.md`
   correction (`source=recall` tag; autonomous lines source-less). +8
   tests, suite 961. **Review must reframe (2) → absolute post-ship
   counts + R1 binary (both paths); (3) needs a new apparatus (below) and
   is forward-only.**
10. Identifier-welding mitigation in the digest.

**Tier 4 — below the line (captured 2026-05-31)**
11. ✅ **Anchor-gen quality gate** — write-time ref validation, shipped
    `b6f85c1` (2026-05-31). `anchor_verify.wellformed_anchor()` drops anchors
    malformed for their type in the extraction hook. **Forward fix only** — the
    ~22 malformed anchors already in the corpus await a cleanup pass (item 12).
12. ✅ **Make `verified=false` actionable** — triage classifier, shipped
    `5edbdd4` (2026-05-31, `scripts/triage_anchors.py`, read-only). Of 402
    false-anchored records: 13 clean-after-strip (malformed), 8 cross-repo
    (re-verifiable), 381 unresolvable. **But the unresolvable bucket is
    overwhelmingly a verifier artefact, not wrong memories** — 446 relative +
    75 tilde (`~`) + 15 absolute file anchors `verify_file` can't resolve
    (no `~`/absolute support; HEAD-only, so deleted-since reads false), and
    only **7** commit refs resolve nowhere. **The genuinely-suspect set is
    tiny.** Surfaced item 20 (below).
13. ✅ **Category-specific retention policy — DESIGN DONE + signed off
    2026-06-01** (`wiki/planning/memory-retention-policy-proposal.md`,
    `bfaf0ab`). Re-derived counts at source (30,277 records). **Reframe:**
    decay already exists (read-time `active_memories` view); archival does
    not (physical eviction from the hot JSONL). Split into **Lever A**
    (behaviour-preserving — archive the **7,370** records (5.62 MB, ~24 %)
    already past their existing decay window; recall unchanged via the view)
    and **Lever B** (per-bucket policy). **Signed off:** Lever A approved;
    `gotcha`/`pattern` → **permanent** (guidance-bearing, NOT aggressive
    decay — pushback on the brief sustained); `progress` keeps 30 d; tier
    structure + cold store (`data/memories/archive/memories-archive-YYYY-MM.jsonl`)
    + `--include-archive` retrieval all adopted. **Corrected stale pointer:**
    `bulk-archive.py` archives *sessions*, not memories — no memory-archival
    tool exists. **Execution (next, gated):** build `scripts/archive-memories.py`
    on the `recover_anchors.py` template (dry-run default, `_bulk_rewrite_guard`
    + `lock_jsonl_for_rewrite`, verbatim passthrough, surgical PG
    `is_active=FALSE`); flip `gotcha`/`pattern` `decay_days 180→NULL` in
    `category_config`; staged sweep (`progress` alone first). Quiet
    (corpus-clean) window required; archive, never delete.
    **EXECUTION TOOL BUILT + audited 2026-06-02** (`9a5345a`,
    `scripts/archive-memories.py` + 30 tests; built in worktree, /audit run,
    boundary/crash-safety/PG-consistency fixes applied). Dry-run validated:
    `progress` past-30d = **4,061** (canonical JSONL; matches the PG interval
    predicate exactly). **Remaining = the gated `--apply`** in a quiet window
    (flush via `daily-sync.sh` first — a dry-run surfaced PG ~272 progress
    records behind the JSONL), plus the small `category_config` 180→NULL flip
    for `gotcha`/`pattern` and the `--include-archive` retrieval flag.
    **✅ EXECUTED 2026-06-02 (Shawn-watched quiet window).** Flushed via
    `daily-sync.sh`; `--apply --category progress` (4,094) then `--apply` rest
    (3,579) = **7,673 records archived** (~25 % of corpus) to
    `data/memories/archive/memories-archive-2026-06.jsonl` (data `034f1cc`,
    `761caf5`). **Recall invariance proven:** `active_memories` total + every
    per-category count IDENTICAL before/after the sweep (21,999). PG: 7,083
    archived rows set `is_active=FALSE`, **0 resurrected, 0 leak into recall**.
    Follow-ups done: `category_config` gotcha/pattern→NULL (live + `schema.sql`;
    un-hid 34 gotcha + 22 pattern) and `fetch-memories.py --include-archive`
    (parent `a5ac41b`, 4 tests). Surfaced **item 22** (sync-to-postgres shrink
    guard) — the cursor stranded above EOF after the shrink; a reset-to-0 +
    full re-scan reconciled it (and fixed 857 previously-unsynced live records).
14. **Extraction selectivity tuning** — fewer, higher-value memories at source.
    **DIAGNOSED + PROPOSAL 2026-06-04** (`wiki/planning/extraction-selectivity-
    proposal.md`; see §6a item 3). Hook over-extracts ~4–7× (median 33/session
    vs the prompt's 2–8 target); proposal = prompt fix (primary) + confidence
    gate + high backstop cap. Awaiting sign-off; no live change made.
15. **Write-time semantic dedup** — embed + compare before insert (API-gated).
16. **Memory utility/access tracking** — log what gets surfaced/recalled;
    never-surfaced-in-N-months → archival candidate.
17. **Confidence-field hygiene** — use the `confidence` field or drop it.
18. ✅ **Memory-health standing report — REPORT ENGINE BUILT 2026-06-04**
    (`scripts/memory-health-report.py`, read-only, +14 tests, suite 1019;
    cadence/delivery still Shawn's call — see §6a item 6 for the section map
    and the live snapshot). — periodic counts / anchor-rate /
    malformed-rate / age / growth (extends item 9). **Now also houses
    Tier C (decided 2026-06-02): the write-time fresh-anchor-fail rate** —
    of the anchored memories written this period, the fraction whose
    `file`/`commit` anchor resolves nowhere (working tree + git history),
    auto-classified recoverable-prefix vs genuinely-absent via
    `anchor_verify.unique_suffix_match`. **Reframed as a corpus-health
    metric, NOT a Vector-2 efficacy signal** (it measures write-path
    anchor confab, not response-path prose welding — that's Tier B). The
    uncommitted-this-session confound is handled by `verify_file`'s
    working-tree stat (`anchor_verify.py:181`); residual noise is
    prefix-mismatch / cross-repo, both classifiable. Cheap when item 18
    is built (reuses `verify_memory` + `unique_suffix_match`); only
    legible aggregated over time, hence here not standalone.
19. **Anchor-type expansion** — dataset-id, PR/issue, memory-to-memory refs.
20. ✅ **`verify_file` path/history hardening** *(no-API, shipped 2026-05-31)*
    — `verify_file` now `expanduser()`s a leading `~`, and absolute (incl.
    expanded-tilde) paths that miss on disk fall back to git history for any
    repo that contains them (`_git_knows_path`: `HEAD` + `git log --all`). Two
    pre-existing realities corrected the original framing: absolute-path stat
    and relative `git log --all` history were **already** present (unchanged
    since `50e663b`), so the only genuine resolver gaps were tilde expansion
    and the absolute→git fallback. **Result (triage re-run):** tilde broad-false
    file anchors **75 → 7**; ~40 records moved unresolvable → cross-repo
    (`cross-repo` 8 → 50, `unresolvable` 383 → 343). **But `verified=false` is
    STILL not a clean prune signal** — the residual is dominated by **write-side**
    anchor junk, not verifier gaps (see item 21). Genuine wrongness signal stays
    tiny: **7** commit refs resolve nowhere.
21. **Write-side anchor hygiene** *(surfaced by item 20, no-API)* — the 272
    unique relative refs still false after item 20 decompose as: **143 (53 %)
    prefix-mismatch** (real file, anchor dropped its dir prefix — `continuity.md`
    vs `wiki/continuity.md`); **68 genuinely-absent** (incl. batch IDs / hex
    fragments mis-typed as `file`); **48 prose-as-file-anchor** (`scoring table
    (7 sessions, 42 cells)`); **13 directory** refs. Two fixes:
    - ✅ **(a) Tighten the `file` gate** *(shipped 2026-05-31, `c27d6a4`)* —
      `wellformed_anchor` → `_looks_like_file_ref` rejects prose, slash-command
      names, and bare object ids, keying on path structure (separator/extension)
      not on spaces (so Zotero PDFs and extensionless real files still pass).
      Forward gate; also reclassifies existing junk in the triage:
      `clean-after-strip` **13 → 48**, `unresolvable` **343 → 311**, relative
      broad-false file anchors **452 → 405**.
    - ✅ **(b) Collision-guarded prefix recovery — diagnostic** *(shipped
      2026-05-31, `7dbee3f`)* — `anchor_verify.unique_suffix_match` (pure,
      collision-guarded: recovers a prefix-dropped ref **only on a unique
      path-suffix hit**) + a read-only `recovery_status` breakdown in
      `triage_anchors.py`. **Measured:** of **225** unique relative refs that
      resolve nowhere, **118 (52 %) recoverable** (real file at a unique suffix
      — `preregistration-draft.md` → `planning/preregistration-draft.md`), **17
      (8 %) ambiguous** (basename collision), **90 (40 %) absent**. Kept
      read-only on purpose: `unique_suffix_match` is **not** wired into the live
      `verify_file` (fuzzy matching would erode the `verified` signal), and no
      ref is rewritten.
    - ✅ **(b-act) Applied the corpus fix** *(shipped 2026-05-31, data
      `a792240`, parent `6cd6666`)* — `scripts/recover_anchors.py` (dry-run
      default; `--apply` guarded by `_bulk_rewrite_guard` + `lock_jsonl_for_rewrite`,
      verbatim-passthrough minimal diff, `revisions` audit entry, surgical
      postgres `UPDATE`). Re-verified each modified record via the **exact
      production path** (`verify_memory` over `repo_set()`; `bind_confidence`).
      **Applied to 218 records:** 155 flipped `false → true`, 41 → unanchored
      (`None`, all-junk-stripped), 21 refs corrected but a hard anchor keeps
      false, 1 → pending. Daily-sync flushed first (the "quiet window"); 218 PG
      rows updated in lockstep; corpus integrity verified (30,235 records, 0
      unparseable).

    **Net result (post-apply triage):** `verified=false` anchored **404 → 224**;
    **`clean-after-strip` 48 → 0** and **prefix-recovery `recoverable` 118 → 0**
    — the corpus is now clean of all *mechanically-fixable* `verified=false`
    noise. The irreducible residual is **7** commit-refs-nowhere + **93** absent
    + **17** ambiguous (basename collision) + 10 absolute + 7 tilde — no cheap
    fix remains. **`verified=false` is now a trustworthy (small, genuine)
    signal.** Items 20 + 21 (a+b+act) together delivered it; **item 13 pruning
    must still target retention/archival, not deletion-by-`verified=false`** (the
    residual is mostly genuinely-gone files, not wrong memories).
22. ✅ **`sync-to-postgres.py` shrink guard — DONE 2026-06-02** *(surfaced by
    item-13 execution, no-API)*. `_sync_cursor.detect_jsonl_shrink()` existed
    but `sync-to-postgres.py` never called it, so when `memories.jsonl` shrank
    below the saved `postgres_sync_line` cursor (as after every archival sweep),
    `_sync_locked` hit `cursor_line >= total_lines`, logged "No new memories",
    and **stranded the cursor above EOF** — silently skipping subsequent appends
    until the file regrew (the D-C3-class bug the helper was written to catch).
    **Fixed:** `_sync_locked` detects the shrink right after counting lines
    (`cursor_line > total_lines`); on shrink it logs a WARN, resets the cursor
    to 0, and full-re-scans (`ON CONFLICT DO NOTHING` → cheap + idempotent). 3
    regression tests (stranded→rescan, in-bounds→no reset, exact-EOF→clean
    no-op). Live: clean no-op at EOF, no false trigger. No longer needs the
    manual workaround on future sweeps. **A follow-up /audit (same session)
    found the first cut — calling `detect_jsonl_shrink` — counted lines by
    file-handle iteration, which diverges from the `splitlines()` count the
    cursor is saved with (on embedded Unicode separators surviving an
    `ensure_ascii=False` rewrite), risking a spurious shrink WARN every cycle;
    switched to the inline `cursor_line > total_lines` check (same count as the
    saved cursor + the slice, and drops the redundant second file read).**

## 6. Recommended sequence for the 2026-05-31 → 2026-06-13 window

1. ✅ **Item 11 (anchor-gen quality gate)** — DONE 2026-05-31 (`b6f85c1`).
   No-API code fix; foundational, makes every downstream `verified` signal
   trustworthy going forward.
2. ✅ **Item 12 (verified=false triage)** — DONE 2026-05-31 (`5edbdd4`).
   Read-only; found `verified=false` is dominated by verifier artefacts, not
   wrong memories (see §5 item 12).
3. ✅ **Item 20 (`verify_file` path/history hardening)** — DONE 2026-05-31.
   No-API; tilde expansion + absolute→git fallback. Re-ran the item-12 triage:
   tilde false-anchors 75 → 7, but `verified=false` is **still** not a clean
   prune signal — the residual is write-side junk (item 21), not verifier gaps.
4. ✅ **Item 21 (write-side anchor hygiene)** — DONE 2026-05-31 (no-API).
   **(a)** file-gate tightening (`c27d6a4`; `clean-after-strip` 13 → 48,
   `unresolvable` 343 → 311). **(b)** prefix-recovery diagnostic (`7dbee3f`):
   118/225 still-false relative refs (52 %) are safely recoverable. **Net:**
   `verified=false` is now legible — genuinely-suspect set ≈ 9 commit-refs +
   a slice of 90 absent; the rest is recoverable/strippable/cross-repo, not
   wrong memories. **(act)** corpus fix applied 2026-05-31 (`recover_anchors.py`;
   data `a792240`, parent `6cd6666`): 218 records (155 false→true), PG in
   lockstep. Post-apply: `verified=false` 404 → 224; `clean-after-strip` and
   `recoverable` both → 0. `verified=false` is now a trustworthy small signal.
5. ✅ **Item 13 design (category retention policy) — DONE + signed off
   2026-06-01.** Proposal `wiki/planning/memory-retention-policy-proposal.md`
   (`bfaf0ab`); per-bucket numbers re-derived at source. Lever A approved
   (archive 7,370 past-decay records, behaviour-preserving);
   `gotcha`/`pattern` kept permanent; cold store + retrieval adopted.
   **Next = execution** (build `scripts/archive-memories.py`, gated, quiet
   window). **NB:** the residual `verified=false` (224, mostly genuinely-gone
   files) is NOT a prune signal — item 13 targets retention/archival, not
   verified-status.
6. ✅ **Item 13 EXECUTED 2026-06-02** — 7,673 records archived (~25 % of
   corpus), recall provably unchanged (`active_memories` invariant); both
   follow-ups (`gotcha`/`pattern`→permanent, `--include-archive`) + the bug it
   surfaced (item 22) done; all session code re-audited. See §5 item 13 + the
   2026-06-02 continuity entries. **This also delivers Tier-1 item 2** (real
   pruning/TTL — an archival sweep, not just a read-window).
7. ✅ **Item 9 (verify §8 apparatus) — DONE 2026-06-02** (`4db5a9d`). Found
   only measurement (1) review-ready; instrumented the /recall blind spot
   in (2); flagged the dead baseline + the missing (3) apparatus. See §5
   item 9 + the 2026-06-02 continuity entry.

## 6a. Prioritised next steps (post item-13, set 2026-06-02)

1. ✅ **P1 — item 9: verify the §8 measurement apparatus — DONE 2026-06-02**
   (`4db5a9d`). Only measurement (1) review-ready; instrumented the
   /recall blind spot in (2) (`source=recall`); baseline for (2) is dead;
   (3) has no apparatus. **P1.5 (surfaced by item 9, per Shawn's ask): automated
   confab-flag tracking for (3) — ✅ BUILT + shipped 2026-06-02
   (`353a45a`).** `scripts/log-confab-flag.py` parses the per-claim
   `corrections.jsonl` the three verifier agents already emit and tallies
   `checked` / `flagged` (`status=fail`) / `confab`
   (`failure_type=confabulation`) / `kinds` to `data/logs/confab-flags.log`
   (best-effort); all three verifier agent defs self-log their tally as a
   final Bash side-effect. +10 tests, suite 971. **Limits:** forward-only
   (no pre-ship data → does not rescue 2026-06-13), verifier-deliverable-
   scoped (selection-biased), instruction-based, narrow kind (citation /
   repo / dataset confab, not prose welding — deferred Tier C). Auto-
   feeds item 18 once a standing report exists. No-API.
   **Tier B (`/confab` manual capture) — ✅ BUILT + shipped 2026-06-02
   (`aa62095`):** `commands/confab.md` + a `--detail` field on the helper;
   logs the prose path/identifier/count welding the verifiers don't see,
   as `source=user-correction checked=0` (absolute-count-only, excluded
   from the rate). Same log file. **Tier C — FOLDED INTO item 18
   (decided 2026-06-02).** The `verify_file` trace confirmed the
   uncommitted-this-session confound is already handled (working-tree stat,
   `anchor_verify.py:181`), so the write-time fresh-anchor-fail rate is a
   clean automatic signal — but it measures write-path anchor confab, not
   the response-path prose welding Vector 2 targets, so it's a
   corpus-health metric (item 18), not a third efficacy tier. Build it
   when item 18 is built; see §5 item 18.
2. **P2 — recurring archival cadence — ✅ BUILT 2026-06-02 (`69e69f6`),
   awaiting a Shawn-watched first `--apply`.** `scripts/monthly-archive.py`
   wraps the proven item-13 sweep (flush → sanity-gate → apply →
   invariance-gate → PG-drift-gate → verified push) as a safe-by-default
   command (dry-run unless `--apply`); the invariance gate independently
   re-verifies every archived record is past-decay at a pinned `as_of`
   (immune to live-`NOW()` drift). Twice adversarially reviewed (CRITICAL
   + 3 HIGH fixed pass 1; pass 2 clean, residuals fail safe); 22 tests,
   suite 996; dry-run from main validated (would archive 47). **Remaining:
   Shawn watches the first `--apply`, then adds the monthly cron line.**
   Doc: `wiki/planning/archival-cadence-2026-06-02.md`. No-API.
3. **P3 — item 14: extraction selectivity tuning — ❌ PROPOSAL REFUTED BY
   VALIDATION 2026-06-05 (no live change ever made); needs rework.** A $1.17
   Haiku spot-check + a confidence-pipeline source check killed the two main
   levers: **(1)** the prompt is empirically weak (paired 50-window run:
   per-run median 5→4, **11.4 % reduction**, zero-floor *backfired* 14→11
   empties, noise-dominated −7..+9 swings); **(2)** sidelining `confidence=low`
   is **INVALID** — the hook overrides Haiku's rating with
   `bind_confidence(verified)` (`hooks/extraction-hook.py:1073`), so `low` ≈
   "no verified anchor" (only ~6 % anchored), NOT low value — the step-change
   0 %→81 % low tracks the v2 anchor rollout, and sidelining would hide 63–79 %
   of recent memories. **Reframe:** session volume = runs-per-session (median
   10, max 152) × per-run (3–5); the prompt only touches the modest per-run, not
   the real driver. Rework toward **runs-per-session / firing cadence / dedup**,
   or deprioritise (archival P2 already manages growth). Full write-up: the
   "Validation outcome" section of `extraction-selectivity-proposal.md`.
   Surfaced **P9** (confidence-overloading). *Original proposal body (below)
   preserved as audit trail.* — Measured the over-extraction at source: the hook produces a **median 33**
   memories/session (mean 57, max 378) against the prompt's stated "2–8"
   target — **86 % of sessions over-target, 99 % of memories from them.** A
   volume problem, not terse junk (content median 286 chars). `decision` is
   27 % of recent output (~60/day); **Haiku already self-flags the low-value
   tail `confidence: low` (19 %)** but that signal is discarded. Proposal
   (`wiki/planning/extraction-selectivity-proposal.md`, rev. 2026-06-05b).
   **Per-run reframe (the key finding):** extraction runs **per ≤30-message
   window** off the cursor, not per session — and per window Haiku is *already*
   restrained (median **3**/run, p90 6). The 33/session is `~10 runs × 3`; the
   multiplier is **runs-per-session**, not per-window greed. So the levers:
   **(1)** prompt = a per-window **zero-floor + value bar** (NOT a session
   count) — "most excerpts are worth `[]`"; goal: per-run median 3 → ~1
   (≈3× fewer/session); primary *at-source* lever (API-gated to validate, or
   observe via P6); **(2)** confidence-aware **sideline (NOT delete)** — exclude
   `confidence='low'` from `active_memories` + cold-store it; reversible, no-API,
   ~19 %; **(3)** backstop = a **per-run cap ~10** (clean; max observed/run is
   12), optional ~150 session catastrophe-guard. **Rejected:** the blunt
   per-session cap (30–40 hits ~half of sessions; top-12 drops 81 %, 87 %
   permanent) **and** a write-time hard-delete of `low` (carve-outs barely fire
   — 8 % anchored, `superseded_by`=0 — and 62 % of `low` is permanent-category
   with 2,400 carrying `why`/`how_to_apply`). **Numbers signed off 2026-06-05.
   Still open:** API spot-check vs ship-and-observe (provisional: spot-check);
   all-three-together vs stage (provisional: together). **Implementation no-API;
   prompt validation API-gated.**
4. **P4 — item 3: neutralise dead fixed-payload weight — ✅ MOSTLY DONE
   2026-06-02.** `MEMORY.md` (harness auto-memory) neutralised 589→262 B/session
   (reversible; backup kept; content also in JSONL). CLAUDE.md redundancy
   audit → proposal `data/notes/claude-md-redundancy-audit-2026-06-02.md`
   (`data 0da8376`): ~610 B SAFE + ~1,505 B judgment trims, two stale claims.
   **SAFE set (A1/B1/C1-SAFE) + D1/D2 rewords APPLIED 2026-06-03**
   (`73932d4` + `data a43d5df`; composed + verified, 12,545→12,157 B).
   **Deferred to Shawn:** E1 (tighten the project Concurrent-sessions
   section, ~700 B — logged in continuity) + C1-JUDGMENT (collapse the
   network guardrails). Global file is auto-generated from `shared.md` +
   `local.md`. No-API.
5. **P5 — write-side dup-id hygiene (NEW, surfaced by the item-13 sweep) —
   ✅ DIAGNOSED 2026-06-04; dup-id hypothesis REFUTED, no remediation
   required.** The framing ("PG behind the JSONL for *non-lag* reasons —
   dup-id / quarantine") was wrong on both counts. Measured at source:
   - **No dup ids.** Live JSONL (23,683) and the cold partition (7,831) each
     have **zero** duplicate ids and zero overlap — the 2026-04-14
     `dedup-memories.py` one-shot plus the item-13 sweep already cleared
     them. `only_in_canonical` is 0–8 at any moment (the normal unsynced tail
     that the 5-min cron drains).
   - **No quarantine.** `data/memories/quarantine-postgres-drops.jsonl` was
     **never created** — the quarantine-on-drop path has not fired in the
     system's lifetime (0 poison drops).
   - **The "590 archived ids never in PG" is real but inert.** Of a 40-record
     sample, **40/40 have content genuinely absent from PG** (0 present under
     a different id) → they are **true never-synced records, not dup-collapse**.
     Date cluster: 540 in 2026-04 (from 2026-04-14 on), 50 in 2026-05;
     source=extraction (582)+manual (8); **0 reprocessing**. Root cause: the
     **pre-item-22 stranded-cursor leak** — the 2026-04-14 dedup shrank the
     JSONL, the line-cursor stranded above EOF, and the incremental sync
     silently skipped appends until reset (a second window in May). The
     past-decay victims were swept to cold storage on 2026-06-02 before the
     post-sweep full re-scan reconciled the *live* survivors (the documented
     857). **Impact: zero** — the 590 are preserved verbatim in
     `memories-archive-2026-06.jsonl` (no data loss) and are past-decay AND
     archived, so excluded from `active_memories` regardless; cold-readable
     via `fetch-memories.py --include-archive`.
   - **Forward leak is closed:** item-22 shrink guard (resets cursor +
     full re-scan on shrink, 2026-06-02), the #55 advisory lock (concurrent-
     sync race), and quarantine-on-drop (never fired).
   - **Deliverable:** `scripts/audit-postgres-sync.py --archive-parity` — a
     read-only standing check reconciling cold-store partitions vs PG, which
     reports the (benign) archived-not-in-PG count and **fails (exit 1) only
     on a recall leak** (an archived id still `is_active=TRUE`; live run:
     0 leaked, exit 0). +6 tests, suite 1005. This is the reproducible anchor
     for the finding and the building block P6/item 18 folds in.
   - **Optional, NOT done (Shawn's call):** backfill the 590 into PG as
     `is_active=FALSE` for completeness — declined by default (zero value:
     past-decay + archived + already cold-readable; would add 590 inert rows).
6. **P6 — item 18: memory-health standing report — ✅ REPORT ENGINE BUILT
   2026-06-04; cadence/delivery is the one remaining decision (Shawn's
   call).** `scripts/memory-health-report.py` (read-only; mutates nothing —
   no locks, no PG writes, no cursor changes; safe to run during concurrent
   extraction). Six sections: **[A]** corpus size & composition (live JSONL +
   PG counts, by-category/source, dup-id tripwire), **[B]** growth & churn
   (`created_at` 1d/7d/30d windows + `archive-runs.jsonl` archival volume),
   **[C]** anchor health (anchored %, verified true/false/pending, malformed
   via `wellformed_anchor`), **[D]** sync & archive integrity (live↔PG tail,
   the P5 `audit_archive_parity()`, dup-id + quarantine tripwires; PASS/FAIL,
   exit 1 on a real leak), **[E]** confab-flag rate (§8 measurement 3 — parses
   `confab-flags.log`, verifier rate Σflagged/Σchecked separate from the
   absolute-only manual catches), **[F]** **Tier C** write-time fresh-anchor-
   fail rate (opt-in `--tier-c`; `verify_memory` over `broad_repo_set`, with
   the failing file-ref split classifying ONLY genuinely-failing anchors —
   recoverable/ambiguous/absent). `--json` for machine output. +14 tests,
   suite 1019. **Live (2026-06-04, point-in-time):** corpus 23,701 / 0 dup-ids
   / integrity PASS / archive parity 7,831·7,241·590·0-leaked; anchored 6.4 %
   (verified t1136/f321/p50); Tier-C 275/1,507 = 18.2 % fail (absent 193 /
   recoverable 76 / ambiguous 65). **Cadence DONE 2026-06-04 (Shawn's pick —
   "command like this, but also add to the weekly-review ritual"):**
   (1) `/memory-health` slash command (`commands/memory-health.md`, symlinked
   live; passes `--tier-c`/`--json` through), and (2) folded into
   `/weekly-review` — a step-2 run instruction + a "Memory-System Health"
   template section so corpus-health trends surface week-over-week. A periodic
   cron was **deliberately NOT added** (Shawn chose command + weekly-review),
   and the §8 digest window is left untouched (no session-start one-liner
   during the measurement period). **P6 COMPLETE.** No-API.
7. **P7 — memory-extraction model eval: Haiku vs Gemini (NEW 2026-06-05,
   Shawn's ask).** Re-evaluate **quality vs cost for memory *creation*** —
   should the extraction hook (`hooks/extraction-hook.py`, currently Claude
   **Haiku 4.5**) move to **Gemini** (e.g. `gemini-3.5-flash`), mirroring the
   cc-session-toolkit *auto-metadata* switch (2026-05-22)? **Explicitly
   SEPARATE from P3** (item 14): P3 changes the *prompt*; P7 changes the
   *model*. Validate the P3 prompt on the current model (Haiku) FIRST, to
   isolate prompt-effect from model-effect; then scope a Haiku-vs-Gemini
   bake-off (cost/token + extraction quality on a shared sample).
   **API-gated** (both models) — present model/batch/count/cost before any run.
   Context for the origin of this item: Shawn believed extraction was already
   on Gemini; investigation (2026-06-05) showed that was the *auto-metadata*
   toolkit, not the memory hook — the two share a constant named
   `EXTRACTOR_MODEL_ID`. Memory extraction is, and has always been, Haiku 4.5.
8. **P8 — `/forget` & `/update` don't propagate to PostgreSQL (BUG, surfaced
   2026-06-05).** `sync-to-postgres.py` is INSERT-only (`ON CONFLICT (id) DO
   NOTHING`) and `is_active` is not among `JSONL_FIELDS`, so a JSONL
   `is_active=false` (forget) or `content` edit (update) to an **existing** row
   **never reaches PG**. `daily-sync.sh` does not rebuild PG. So the PG-reading
   recall paths (session-start digest + `fetch-memories.py` autonomous
   retrieval, via the `active_memories` view) **silently ignore `/forget` and
   `/update`** until a manual `rebuild-postgres.py`. (The `/recall` *command*
   reads the JSONL directly, so it may respect the edit — verify.) Both
   commands' "PostgreSQL sync is automatic — next tick picks up the JSONB
   change" claim is **false** for existing rows. Also multi-machine: a surgical
   PG fix only corrects the local PG; other machines stay stale until they
   rebuild. **Fix options:** (a) have `/forget`+`/update` do a surgical PG
   `UPDATE` in lockstep (the `recover_anchors.py` / `archive-memories.py`
   pattern) — cleanest; (b) make sync reconcile `is_active`+`content`+
   `revisions` for existing rows; (c) scheduled `rebuild-postgres`. Today's two
   corrections (`d2befeae` update, `52451aba` forget) were **PG-reconciled by
   hand on this machine** (verified: `52451aba` now 0 in `active_memories`).
   No-API.
9. **P9 — `confidence` is overloaded (verification, not value) — ✅ INVESTIGATED
   2026-06-05; no acute bug, but the field is incoherent + mislabelled.** Since
   v2 (`2026-05-16`) the hook overwrites Haiku's self-rating with
   `bind_confidence(verified)` (`verified∈{false,None}→low`, `pending→medium`,
   `true→high`); only ~5–6 % are anchored, so `low` ≈ "no verified anchor".
   **Consumer audit (the worry — does any recall path treat `low` as low-value
   and suppress unanchored memories?): NO.** All consumers verified read-only:
   - **digest.py** ranks by `verified` + tag-overlap + recency, *explicitly
     never* `confidence` (`:17–18`); fallback even *prefers* anchored
     (`has_anchors`, `:246–253`). Confidence unused.
   - **fetch-memories.py** queries `active_memories` (is_active + decay, no
     confidence clause), filters category/tag, orders by recency / embedding
     similarity; `confidence` is **display-only** (`:662,676`).
   - **/recall** filters `is_active=TRUE` + category/tag; `confidence`
     display-only (`recall.md:47,68`).
   - **active_memories view**: is_active + decay; no confidence predicate.
   So the v2 designers already knew confidence ≠ value. **Real residuals
   surfaced instead:** (a) **`confidence` is temporally incoherent** — of 18,023
   active `high`, only 1,207 are `verified=true`, so ~16,800 `high` are *pre-v2
   Haiku self-ratings* (uninformative — 93 % high incl. confabulations), while
   post-v2 `high`=verified-echo; same field, two meanings (a 2nd code path at
   `extraction-hook.py:~1084` also appends raw-Haiku confidence without
   binding). (b) **It's mislabelled in display** — `/recall`/`fetch-memories`
   show "Confidence: low" where a human/LLM reads "low value" but it means
   "unanchored". (c) **The whole verification apparatus is anchor-gated** — the
   digest surfaces from the ~5 % `verified=true` pool (1,207, enough to fill the
   byte-budgeted digest) + anchored-preferred fallback, so it **deliberately
   favours the anchored 5 %** (anti-confab) and the unanchored 93 % rarely reach
   the digest — by design, via `verified`, not a confidence bug.
   **Design recommendation (for the "separate value from anchored?" question):**
   the fields are *already* separate (`confidence` / `verified` / `anchors`);
   the mess is that `confidence` became a redundant verification-echo and is
   shown as if it were value. **(1)** Relabel/drop `confidence` in recall
   displays (don't let it read as value) — cheap. **(2)** A *true* value signal
   can't come from LLM self-rating (v2 abandoned it for exactly this reason); the
   principled source is **earned utility — item 16 (track what actually gets
   surfaced/used)**, orthogonal to "anchored". **(3)** The bigger lever is
   **anchor coverage** (~5–6 %): the digest surfaces from a 5 % pool, so raising
   coverage (forward-anchoring / item 6) does more than any confidence reform.
   No code changed — design decision pending Shawn. No-API.

**Lower:** items 4 (correction loop), 7 (actionable what-changed counter),
10 (identifier-welding), 8 (drift-sweep job), 17, 19.

Items 5, 6, 15 (anything LLM/embedding-driven — semantic dedup, the
retroactive anchor-gen pass to verify the back-corpus) are **API-gated** —
present model + batch + count + cost for approval before any run.
