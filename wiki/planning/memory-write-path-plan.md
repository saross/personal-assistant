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
11. **Anchor-gen quality gate** — write-time ref validation (3 % malformed).
12. **Make `verified=false` actionable** — triage classifier
    (malformed / cross-repo / deleted-since / genuinely-wrong).
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

## 6. Recommended sequence for the 2026-05-31 → 2026-06-13 window

1. **Item 11 (anchor-gen quality gate)** — no-API code fix; foundational, makes
   every downstream `verified` signal trustworthy. Start here.
2. **Item 12 (verified=false triage)** — turns the 397 into an actionable,
   classified set; read-only analysis, no deletion.
3. **Item 13 design (category retention policy)** — design + per-bucket
   numbers; execute archival only with explicit sign-off, in a quiet window.
4. **Item 9 (verify §8 apparatus)** — cheap; de-risks the 2026-06-13 review.

Items 5, 6, 14, 15 (anything LLM/embedding-driven) are **API-gated** — present
model + batch + count + cost for approval before any run.
