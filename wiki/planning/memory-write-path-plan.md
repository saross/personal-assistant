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
13. **Category-specific retention policy** — populate `decay_days` per category
    at write (set on 10 records today); archive past-decay.
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
21. **Write-side anchor hygiene** *(NEW, surfaced by item 20, no-API)* — the
    272 unique relative refs still false after item 20 decompose as: **143
    (53 %) prefix-mismatch** (real file, anchor dropped its dir prefix —
    `continuity.md` vs `wiki/continuity.md`); **68 genuinely-absent** (incl.
    batch IDs / hex fragments mis-typed as `file`); **48 prose-as-file-anchor**
    (`scoring table (7 sessions, 42 cells)`); **13 directory** refs. Two cheap
    fixes: **(a)** tighten the item-11 `file` gate to reject obvious non-paths
    (refs containing spaces, bare hex/IDs, slash-command names); **(b)** a
    prefix-recovery resolver pass that accepts a basename suffix-match **only on
    a unique hit** (collision-guarded, to avoid mis-resolving to the wrong
    file). (a) is the safer first step. **This — not item 20 — is what would
    make `verified=false` trustworthy as a prune signal.**

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
4. **Item 21 (write-side anchor hygiene)** — NEXT, no-API. The actual blocker
   on trusting `verified=false`: tighten the `file` gate (reject prose / IDs /
   slash-commands), then collision-guarded prefix-recovery. **Precedes any
   item-13 pruning** (item 20 was necessary but not sufficient).
5. **Item 13 design (category retention policy)** — design + per-bucket
   numbers; execute archival only with explicit sign-off, in a quiet window.
6. **Item 9 (verify §8 apparatus)** — cheap; de-risks the 2026-06-13 review.

Items 5, 6, 14, 15 (anything LLM/embedding-driven) are **API-gated** — present
model + batch + count + cost for approval before any run.
