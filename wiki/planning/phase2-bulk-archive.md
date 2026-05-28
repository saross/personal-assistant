# Phase 2: Bulk Archive of Historical Sessions

## Context

The progressive disclosure system has Phase 0 (auto-metadata fix) and Phase 1
(Tier 2 autonomous fetch) complete. Phase 2 archives 427 unarchived sessions
from `~/.claude/projects/` into `~/cc-archives/`, enriches them with
Haiku-generated metadata via Batch API (~$0.55), and syncs to PostgreSQL.
This unlocks session search in `/recall` and enables the future session
reprocessing step (testing local LLMs for full-transcript extraction).

Currently: 23 sessions archived (2.3% coverage). After: ~430+ (near 100%).

## Data Landscape (verified)

| Category | Count | Size |
|----------|------:|-----:|
| Main sessions | 427 | 4.2 GB |
| Nested subagents | 1,290 | 83 MB |
| Orphaned flat agents | 186 | 23 MB (skipped) |
| Already archived | 23 | 13 MB compressed |
| **Net to archive** | **~404 main + 1,290 subagents** | **~4.1 GB raw → ~800 MB compressed** |

19 project directories. Largest: fieldmark-docs-staging (111), map-reader-llm
(102), llm-reproducibility (71), personal-assistant (52).

## Approach: Archive first, enrich asynchronously

**Key architectural decision:** Separate archiving (pure I/O, no API cost)
from enrichment (Haiku Batch API). This means:

- Archive step runs at disk speed (~15–25 min for all sessions)
- Enrichment submits asynchronously (1–4h Batch API turnaround)
- Either step can be re-run independently
- Proven pattern: `backfill-session-metadata.py` already enriches after archive

## Implementation: `scripts/bulk-archive.py`

One script with four modes. Each is idempotent with checkpoint/resume.

### Mode 1: `discover`

Scan, filter, report. Zero side effects.

1. Walk `~/.claude/projects/` for `*.jsonl` files (excluding `agent-*.jsonl`
   at root level — orphaned flat agents with no parent linkage)
2. Resolve encoded project dirs to real paths (extract `cwd` from first JSONL
   entries; fallback to path reconstruction)
3. Call `extract_session_stats()` per session for trivial filtering
4. Check dedup against `~/cc-archives/CATALOG.json` via `get_archived_session_ids()`
5. Apply trivial filter via `is_trivial_session()` (default: <5 turns or <1 min)
6. Count nested subagents per session
7. Write manifest to `logs/bulk-archive-manifest.json`
8. Print summary (by project, sizes, estimated enrichment cost)

### Mode 2: `archive`

Compress and archive. No API calls. Supports `--dry-run`, `--limit N`, `--resume`.

1. Load manifest from discover (regenerate if missing)
2. Load checkpoint (`logs/bulk-archive-progress.json`) for resume
3. For each unarchived session:
   - Call `archive_session(session_path, stats_only=True, use_gzip=True,
     auto_metadata=False, archive_root=~/cc-archives/,
     project_name_override=<resolved>)`
   - Archive nested subagents: compress each `{session}/subagents/agent-*.jsonl`
     into `{archive_dir}/subagents/{agent_id}.jsonl.gz`
   - Update checkpoint file
4. Print progress every 10 sessions

Checkpoint structure:

```json
{
  "started_at": "...",
  "updated_at": "...",
  "archived_ids": ["uuid1", ...],
  "skipped_trivial_ids": ["uuid3", ...],
  "failed_ids": {"uuid4": "error message"},
  "stats": {"total_archived": 150, "total_subagents": 340}
}
```

### Mode 3: `enrich`

Haiku metadata generation via Batch API. Two sub-modes.

**`--batch-submit`:**

1. Walk `~/cc-archives/` for sessions where `auto_generated.purpose` contains
   "unavailable" or "requires interactive"
2. For each, decompress session JSONL, sample messages (reuse sampling logic
   from `generate_auto_metadata()` — first 2 + last 2 user messages + files)
3. Build Batch API requests with `populate-metadata.md` prompt
4. **Present API cost gate** (model, mode, count, cost)
5. Submit via `client.messages.batches.create()`
6. Save state to `logs/bulk-enrich-batch-state.json`

**`--batch-apply BATCH_ID`:**

1. Retrieve results, parse title/purpose/tags
2. Update each `session.meta.json` in place
3. Report: applied N, failed M

### Mode 4: `verify`

Integrity checks. Supports `--fix-catalogue`.

1. Verify each CATALOG.json entry has matching archive directory
2. Check for orphaned archives not in catalogue
3. With `--fix-catalogue`: rebuild via `rebuild_catalogue()`
4. Trigger PostgreSQL sync: run `sync-sessions-to-postgres.py --full-resync`
5. Report totals and any issues

## Execution Sequence

| Stage | Command | Time | API Cost |
|-------|---------|------|----------|
| 1. Discover | `python3 scripts/bulk-archive.py discover` | 5 min | $0 |
| 2. Review manifest | (human reviews output) | 2 min | $0 |
| 3. Archive | `python3 scripts/bulk-archive.py archive` | 15–25 min | $0 |
| 4. Verify + fix | `python3 scripts/bulk-archive.py verify --fix-catalogue` | 2 min | $0 |
| 5. Submit enrich | `python3 scripts/bulk-archive.py enrich --batch-submit` | 1 min | ~$0.55 |
| 6. (wait for batch) | | 1–4 hours | |
| 7. Apply enrich | `python3 scripts/bulk-archive.py enrich --batch-apply BATCH_ID` | 1 min | $0 |
| 8. Final sync | `python3 scripts/sync-sessions-to-postgres.py --full-resync` | 1 min | $0 |
| 9. Test `/recall` | manual test | 2 min | $0 |

**Active time: ~30–40 min + async batch wait.**

## Key Functions to Implement

1. `resolve_project_mapping()` — encoded dir → (project_root, project_name)
2. `discover_sessions()` — build manifest with stats, filtering, dedup
3. `archive_all()` — main loop with checkpoint/resume
4. `archive_subagents()` — compress subagent JSONLs into archive dir
5. `build_enrich_requests()` — collect unenriched sessions, build batch payloads
6. `apply_enrich_results()` — parse Haiku responses, update meta.json files
7. `verify_archives()` — integrity check + catalogue rebuild

## Dependencies (existing — no toolkit changes needed)

From `cc_session_toolkit.archive`:
- `archive_session()`, `extract_session_stats()`, `is_trivial_session()`
- `get_archived_session_ids()`, `get_session_id()`
- `generate_auto_metadata()` (reference for message sampling logic)

From `cc_session_toolkit.catalogue`:
- `rebuild_catalogue()`, `update_catalogue()`

## Files to Create/Modify

| File | Action |
|------|--------|
| `scripts/bulk-archive.py` | **Create** — the main script (~400–500 lines) |
| `tests/test_bulk_archive.py` | **Create** — unit tests |

No modifications to cc-session-toolkit needed.

## Tests

- `test_resolve_project_mapping()` — mock encoded dirs, verify mapping
- `test_discover_skips_trivial()` — trivial filter works
- `test_discover_skips_archived()` — dedup against catalogue
- `test_discover_skips_flat_agents()` — orphaned agents excluded
- `test_archive_subagents()` — subagent compression + meta
- `test_checkpoint_resume()` — archive, interrupt, resume, no duplicates
- `test_build_enrich_requests()` — correct sessions selected
- `test_verify_detects_orphans()` — finds archives not in catalogue

## Verification

1. Run `discover` — confirm session count matches expectation (~404 net)
2. Run `archive --dry-run` on first 5 sessions — verify output structure
3. Run `archive --limit 10` — verify archives appear in `~/cc-archives/`
4. Run `verify` — confirm no integrity issues
5. Run full `archive` — verify checkpoint resume works (ctrl-C mid-run, restart)
6. Run `enrich --batch-submit` — verify cost gate presented correctly
7. After batch completes, run `--batch-apply` — verify meta.json updated
8. Run PostgreSQL sync — verify `/recall` returns session results
9. Run full test suite — verify 224+ tests still pass

## Risks

- **Disk space:** 4.1 GB → ~800 MB compressed. 74 GB free. No concern.
- **Large files:** 21 sessions >50 MB. `archive_session()` streams gzip, bounded memory. ~2–3s each.
- **CATALOG.json global vs per-project:** Current catalogue is global at `~/cc-archives/CATALOG.json`. The `update_catalogue()` function takes a project_name param — need to pass correct project per session or rebuild at the end.
- **Concurrent archiving hooks:** `is_already_archived()` + catalogue dedup handles this.
