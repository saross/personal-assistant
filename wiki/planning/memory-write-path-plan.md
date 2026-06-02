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
9. Verify the §8 measurement apparatus before 2026-06-13.
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
14. **Extraction selectivity tuning** — fewer, higher-value memories at source.
15. **Write-time semantic dedup** — embed + compare before insert (API-gated).
16. **Memory utility/access tracking** — log what gets surfaced/recalled;
    never-surfaced-in-N-months → archival candidate.
17. **Confidence-field hygiene** — use the `confidence` field or drop it.
18. **Memory-health standing report** — periodic counts / anchor-rate /
    malformed-rate / age / growth (extends item 9).
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
6. **Item 9 (verify §8 apparatus)** — cheap; de-risks the 2026-06-13 review.

Items 5, 6, 14, 15 (anything LLM/embedding-driven) are **API-gated** — present
model + batch + count + cost for approval before any run.
