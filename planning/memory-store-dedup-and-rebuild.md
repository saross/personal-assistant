# Memory store deduplication and rebuild

**Status:** Backlog — not urgent but has latent functional impact.
**Added:** 2026-04-14
**Discovered during:** IP address refresh session (grep for stale `192.168.1.188` references in memory store).

## Problem statement

The canonical memory store `~/personal-assistant/memories/memories.jsonl`
contains substantial duplication left over from the 2026-04-11 session
reprocessing pass. The duplication itself is cosmetic bloat — but because
`sync-to-postgres.py` uses `ON CONFLICT (id) DO NOTHING`, the reprocessed
improvements were silently discarded at the database layer. `/recall`
results and pgvector embeddings are therefore built from the *pre-reprocessing*
versions of affected records, not the improved versions.

In short: reprocessing updated the canonical store, but the derived query
layer still reflects the original extractions. The system is not broken,
but it is not getting the full benefit of the reprocessing work already done.

## Findings (as of 2026-04-14)

```text
Total JSONL records:      23,814
Unique ids:               15,653
Duplicated ids:            7,922   (52% of unique ids)
Redundant records:         8,161   (34.3% of file)
Differing-content dups:    8,094 / 8,122 pairs  (99.7%)
Malformed lines:               0
```

Duplication depth histogram:

| Copies | Ids affected |
|---|---|
| 2× | 7,806 |
| 3× | 65 |
| 4× | 15 |
| 5× | 11 |
| 6× | 17 |
| 7× | 5 |
| 8× | 3 |

Almost all duplicates are 2× — consistent with **one** reprocessing pass
running against a store that already contained the original extractions.
A small number of 3–8× cases likely indicate records that were reprocessed
more than once (e.g., during development iterations of the reprocessing
script) or that have complex session overlap.

## Root cause

`~/personal-assistant/scripts/sync-to-postgres.py` uses:

```sql
INSERT INTO memories (...) VALUES (...)
ON CONFLICT (id) DO NOTHING
```

This is the correct defensive pattern for incremental sync (prevents
re-inserting records already synced), but it is **first-write-wins** — any
later record with the same id, even if it has improved content, is silently
dropped. When reprocessing re-emitted records with the same `id` but
refined `content`, `summary`, `research_tags`, and `source_context`, those
improvements never reached postgres.

The canonical JSONL (being append-only) has both versions; the derived
postgres layer has only the first. Embeddings are computed from postgres
content, so they also reflect the pre-reprocessing state.

## Why this matters

- `/recall` semantic search ranks against embeddings that were computed from
  the older, less refined content. Queries that should have been improved
  by reprocessing are not.
- Category and tag refinements from reprocessing are invisible to category
  filters and `/tags` gardening.
- Any `/synthesise` or thematic aggregation passes over postgres are working
  from stale material.
- The JSONL is 34.3% larger than it needs to be, but disk space is not the
  concern — correctness is.

## Why this is NOT urgent

- The system is stable, not degrading. Duplication stopped growing when the
  one-off reprocessing pass finished.
- `/recall` still returns relevant results — just not the best available
  versions of them.
- There is no active failure mode. Users (Shawn and Claude) do not see the
  duplication directly.
- Fixing it is a one-time maintenance operation, not an ongoing task.

## Recommended scope

### Phase 0 — Pre-flight (read-only, no changes)

1. Confirm `rebuild-postgres.py` truncates and rebuilds (as opposed to
   incremental upsert). Read the script first — do not run it blind.
2. Sample 5–10 duplicate-id groups across different dates and categories.
   For each, compare the earliest and latest copy:
   - Is the later copy genuinely an improvement (better summary, more
     complete tags, cleaner source_context)?
   - Or is it sometimes a regression (e.g., reprocessing lost information)?
   - This decides the conflict-resolution policy in Phase 1.
3. Check whether any memory-extraction hooks are currently active that
   would append to `memories.jsonl` during the rewrite. Pause them if so.
4. Check `backfill-embeddings.py` to understand whether it re-embeds on
   content change, or only fills missing embeddings. This determines
   whether Phase 3 needs to null out embeddings first.

### Phase 1 — Canonical JSONL cleanup (single rewrite)

1. **Back up** to `memories.jsonl.bak.<YYYY-MM-DD>`. Keep at least one
   session (retain until you have verified Phase 4 passes).
2. Per-id conflict resolution: keep the **latest** copy — tentatively defined
   as the record with the highest `created_at` timestamp, with file order
   as tiebreak. Revisit this if Phase 0 step 2 shows regressions.
3. Write deduped output to a temp file. Validate:
   - Line count equals 15,653 (current unique-id count), adjusted for any
     concurrent writes that slipped through.
   - All lines parse as JSON.
   - No ids appear more than once.
4. Atomic `mv` over the original. Leave the backup in place.

### Phase 2 — Rebuild postgres

1. Run `rebuild-postgres.py` (only after Phase 0 confirmed it does what we
   expect).
2. Verify `SELECT COUNT(*) FROM memories` matches deduped JSONL line count.
3. Spot-check a few known-reprocessed records: confirm that postgres now
   holds the reprocessed version, not the original.

### Phase 3 — Regenerate affected embeddings

The 7,922 records whose content changed during reprocessing need new
pgvector embeddings (vectors are content-derived).

1. Depending on what Phase 0 step 4 found:
   - If `backfill-embeddings.py` detects content changes: just run it.
   - If it only backfills missing embeddings: null the `embedding` column
     for the 7,922 affected ids first, then run the script.
2. Cost check: which embedding model? If local (sapphire Ollama), free
   but slow. If API-based (Voyage, OpenAI, etc.), this **hits the API
   Call Review Gate** — stop and get explicit approval first, with aggregate
   cost estimate.
3. Verify HNSW index is still valid after bulk update (pgvector HNSW does
   support dynamic updates, but large rewrites can degrade index quality
   — may want to `REINDEX` afterwards).

### Phase 4 — Verify

1. Run `/recall` on a few queries where you know reprocessing should have
   improved the result (e.g., queries that previously returned vague
   summaries). Compare to pre-rebuild behaviour.
2. Check `/tags` output: reprocessed tag refinements should now show up.
3. Run `apply-decay.py --dry-run` to confirm decay logic still behaves
   correctly against the deduped store.
4. Check that the memory-extraction hook can still append new records
   (don't want to discover later that the rewrite broke file permissions
   or the hook's append logic).

## Risks

1. **Append-only invariant broken temporarily.** Phase 1 rewrites the
   canonical event log. Mitigations: backup, temp-file+atomic-mv, keep
   `.bak` for ≥1 session, document the operation in a memory.
2. **Concurrent writers during rewrite.** If an extraction hook fires
   during Phase 1, the new record may land in the old file that's about
   to be replaced, or be lost in the rewrite. Mitigation: pause hooks or
   run during a quiet period; inspect the `.bak` afterwards to confirm
   nothing was lost.
3. **Wrong conflict-resolution policy.** If "latest wins" is the wrong
   call (i.e., reprocessing sometimes produced worse output), we would
   lose good data. Mitigation: Phase 0 step 2 — sample before committing.
4. **Embedding regen cost.** If the embedding model is API-based, the cost
   could be non-trivial. 7,922 records × ~500 tokens each = ~4M tokens.
   Mitigation: API Call Review Gate, use local model if available.
5. **Index degradation.** HNSW indexes can degrade under bulk updates.
   Mitigation: `REINDEX` after Phase 3, or drop and rebuild the index.
6. **Scope creep during execution.** While working in the memory store,
   the temptation to fix other things (stale tag vocabulary, orphaned
   session_ids, etc.) will be strong. Resist — do this task, nothing more.

## Decision deferred to execution time

- **Latest-wins vs first-wins vs merge**: decide after Phase 0 sampling.
- **API Call Review Gate for Phase 3**: quantify cost first, present to
  Shawn before running.
- **Run during or between focus blocks**: this is a ~30–90 minute
  maintenance task; schedule for a quiet window.

## Estimated time

- Phase 0: 15–20 min (reading scripts, sampling dups).
- Phase 1: 10–15 min (rewrite + validation).
- Phase 2: 5–10 min (rebuild + verification).
- Phase 3: variable (embedding regen — depends on model and count).
- Phase 4: 10–15 min (spot checks).

Total: 40–70 min excluding Phase 3 embedding regen time.

## Related context from this session

- Discovered while grepping `memories.jsonl` for stale `192.168.1.188`
  references (zbook-ubuntu IP changed to `.80`).
- A targeted fix for the zbook IP case was already applied via a new
  `/remember` correction memory (id `2026-04-14-64dff7d6373b`) rather than
  editing the JSONL — that fix does not need to be re-done as part of this
  cleanup; it exists at the same layer the rebuild will preserve.
- Corresponding doc fixes already landed in:
  - `~/personal-assistant/data/global-claude-md/network-resources.md`
  - `~/personal-assistant/data/global-claude-md/local.md`
  - `~/.claude/CLAUDE.md`

## Open questions

- Does `rebuild-postgres.py` also handle the `session_archive` table, or
  only `memories`? The reprocessing pass may have touched other tables.
- Are there snapshot/backup processes that copy `memories.jsonl` elsewhere?
  If so, those copies are also stale and may need to be refreshed after
  Phase 1.
- Did the 2026-04-11 session reprocessing pass emit records for the
  category_config or sync_state tables too, or only `memories`? Check
  `reprocess-sessions.py` to confirm.
