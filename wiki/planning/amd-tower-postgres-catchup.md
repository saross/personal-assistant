# amd-tower PostgreSQL post-refactor catchup

**Status:** Ready to action.
**Added:** 2026-04-14 (during post-travel multi-machine sync).
**Affected machine:** amd-tower-ubuntu only.
**Estimated time:** ~1–2 hours, dominated by embedding regeneration.
**Sequencing:** See "Coordination with dedup plan" below — order matters.

## Situation

The major memory system refactor (bulk-archive, pgvector embeddings,
sessions table, reprocessing, summary-column rollout, etc.) landed on
zbook between roughly 2026-04-02 and 2026-04-14. amd-tower was idle
for that entire window — the user was travelling, no scripts ran on it,
no schema changes were applied.

Today's git pull brought the post-refactor codebase to amd-tower
(`scripts/sync-to-postgres.py`, `schema.sql`, embedding helpers, etc.)
but did **not** apply schema changes to amd-tower's `claude_memories`
database. The result: amd-tower's database is at its 2026-04-02 schema,
while the script that runs against it expects the post-refactor schema.

This is not a recurring bug or mysterious regression. It is the routine
consequence of doing schema work on one machine while another sits
dormant.

## Symptoms

- `data/logs/sync-cron.log` on amd-tower contains, on every cron run:

  ```text
  ERROR: Database error during insert: column "summary" of relation "memories" does not exist
  WARNING: Insert returned 0 — cursor NOT advanced (PostgreSQL may be down)
  ```

- `data/memories/sync-cursors.json` on amd-tower has not advanced
  since 2026-04-02 23:19. The `postgres_sync_line` value is frozen.
- amd-tower's local `/recall` is silently working from a 12-day-stale
  postgres view of memories. Anything captured since 2026-04-02 is
  not searchable on amd-tower via the postgres path. (The JSONL FTS
  fallback in `fetch-memories.py` should still work.)

The `summary` column is *one* known divergence. There may be others
introduced by the refactor — pre-flight (Phase 0) confirms the full
schema delta before deciding the migration approach.

## Coordination with dedup plan

This task and `memory-store-dedup-and-rebuild.md` are independent bugs
but interact at execution time:

- The dedup plan's Phase 2 ("rebuild postgres") will crash on amd-tower
  with the same `column "summary" does not exist` error if executed
  before this catchup.
- Conversely, if this catchup runs **first** with a full rebuild against
  the *current* (duplicated) canonical, amd-tower will dutifully load
  all 8,161 duplicates over Ollama and waste hours of embedding compute.
- **Recommended order:** dedup plan first (on zbook, push deduped
  canonical), then this catchup (rebuilds amd-tower from the cleaned
  canonical in one pass). Saves time and avoids loading duplicates.
- **Alternative order:** catchup first (gets amd-tower functional but
  with duplicates), then dedup later (deduped canonical pushed, amd-tower
  picks it up via incremental sync — but pgvector embeddings on amd-tower
  will then be stale in the same way as zbook's, so the dedup plan's
  Phase 3 has to apply to both machines).
- The recommended order is cheaper and cleaner. Only deviate if amd-tower
  needs to be functional immediately for some reason.

## Phase 0 — Pre-flight (read-only, no changes)

1. **Schema diff.** On amd-tower, list every table and every column in
   `claude_memories`:

   ```bash
   psql claude_memories -c "\dt"
   psql claude_memories -c "\d memories"
   psql claude_memories -c "\d sessions"  # may not exist
   ```

   Compare against `scripts/schema.sql`. Note every difference:
   - Missing tables (`sessions` is the most likely candidate from the
     refactor — Phase 2 archive work introduced it).
   - Missing columns (`summary` on `memories` is known; check for others
     like `embedding`, `prompt_summary`, `process_summary`, etc.).
   - Missing indexes (HNSW on `embedding`, FTS on session summary).
   - Missing extensions (`pgvector`/`vector` may not be installed on
     amd-tower's PostgreSQL).
2. **Verify zbook is the correct target.** On zbook, run the same
   introspection. Confirm zbook's live schema matches `schema.sql`.
   If zbook itself diverges from `schema.sql`, the source of truth is
   in question and that needs resolution first.
3. **Check pgvector extension.** `SELECT * FROM pg_extension WHERE extname = 'vector';`
   on amd-tower. If missing, the extension package may need to be
   installed (`apt install postgresql-XX-pgvector` or similar) before
   any catchup can succeed.
4. **Check Ollama availability on amd-tower.** Embedding regen will run
   through Ollama. If amd-tower's Ollama is down or doesn't have
   `nomic-embed-text` pulled, sort that out before starting the rebuild.
5. **Check current row counts.** `SELECT COUNT(*) FROM memories;` on
   both machines. Difference is the size of the backlog.
6. **Read `rebuild-postgres.py` end-to-end.** Confirm what it does and
   does not handle (truncate? drop+recreate? apply schema.sql? handle
   the sessions table?). The script is the load-bearing piece for
   this whole task — do not run it blind.

Report Phase 0 findings before proceeding to Phase 1. Some findings
may invalidate the proposed Phase 1 approach.

## Phase 1 — Decide migration vs full rebuild

Two options after Phase 0 findings are in:

**Option A — Schema migrate.** Run targeted `ALTER TABLE ADD COLUMN
IF NOT EXISTS` statements for each missing column, `CREATE TABLE IF
NOT EXISTS` for missing tables. Keep existing rows. Then run
`sync-to-postgres.py` to catch up the cursor by replaying JSONL since
2026-04-02. Faster but only safe if Phase 0 confirmed the divergence
is purely additive (no renames, no type changes, no constraint shifts).

**Option B — Full rebuild.** Drop and recreate `claude_memories` from
`schema.sql`, run `sync-to-postgres.py` from line 0. Slower but
guaranteed-correct against the canonical schema. Matches the
"PostgreSQL is derived" philosophy. Embedding regen for ~24k records
through local Ollama is the dominant cost — estimate based on
nomic-embed-text throughput on amd-tower's hardware.

**Default to Option B** unless Phase 0 shows the changes are minor
and additive. Option A's speed advantage is small once Phase 0 takes
its share of time, and Option B avoids any risk of leaving subtle
schema drift behind.

## Phase 2 — Execute

For Option B (the recommended path):

1. **Backup.** `pg_dump claude_memories > /tmp/claude_memories-amd-tower-pre-catchup-$(date +%s).sql`.
   Keep until verification passes.
2. **Drop and recreate.**

   ```bash
   psql -c "DROP DATABASE IF EXISTS claude_memories;"
   psql -c "CREATE DATABASE claude_memories;"
   psql claude_memories < scripts/schema.sql
   ```

3. **Verify schema applied cleanly.** Re-run the Phase 0 introspection
   commands. amd-tower's schema should now exactly match zbook's.
4. **Reset the sync cursor.** Set `postgres_sync_line` in
   `data/memories/sync-cursors.json` to `0` on amd-tower. (Do not commit
   this — sync cursors are machine-local and should be in `.gitignore`;
   confirm they are.)
5. **Run sync-to-postgres.py.** Expect a long run — full table reload
   plus embedding generation for every record.

   ```bash
   venv/bin/python3 scripts/sync-to-postgres.py 2>&1 | tee /tmp/catchup-sync.log
   ```

6. **Run sync-sessions-to-postgres.py.** The sessions table also needs
   to be populated from `~/cc-archives/`. This is independent of the
   memories sync and may have its own issues to surface.

For Option A (only if Phase 0 supports it):

1. Apply targeted DDL for each missing column/table (write the exact
   statements out before running them; do not improvise).
2. Run `sync-to-postgres.py` normally — incremental from the existing
   cursor. Expect the 12-day backlog (smaller than full rebuild).
3. If new columns were added, the existing rows have NULL values for
   those columns. Decide whether to backfill (e.g., regenerate
   `summary` from existing content) or accept NULL for historical
   records.

## Phase 3 — Verify

1. **Row counts match.** `SELECT COUNT(*) FROM memories;` on amd-tower
   and zbook should be equal (or off by whatever was extracted on zbook
   in the time it took the rebuild to run — re-sync once more if so).
2. **Cursor advanced.** `data/memories/sync-cursors.json` on amd-tower
   has `postgres_sync_line` matching the canonical line count.
3. **Embeddings populated.** `SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL;`
   on amd-tower should match the row count (or be very close —
   nomic-embed-text occasionally drops one).
4. **Same query, same answers.** Pick 3–5 known-good `/recall` queries.
   Run them on both machines. The top-N memory ids should be identical
   (or ranking-equivalent, allowing for tied scores).
5. **Tag stats match.** `scripts/tag-gardening.py stats` should produce
   identical output on both machines (within whatever the script
   considers stable).
6. **No errors in the next cron run.** Wait one cron interval, check
   `data/logs/sync-cron.log` on amd-tower. Should be silent or report
   "no new records".

## Phase 4 — Prevent recurrence

The current state is fixable but the design that produced it is
fragile: schema changes propagate through git but require manual
out-of-band application on each database. The right long-term fix is
documented in `memory-store-dedup-and-rebuild.md`'s "Proper fix" section
and is essentially the same problem viewed from a different angle.
Briefly:

1. **Schema diff at startup.** `sync-to-postgres.py` reads `schema.sql`,
   introspects the live table, and runs `ALTER TABLE ADD COLUMN IF NOT
   EXISTS` for any columns in `schema.sql` missing from the live table.
   Cheap, idempotent, handles 90% of refactor cases. Doesn't handle
   drops/renames/type changes — but those are rare here.
2. **Or numbered migrations.** `scripts/migrations/0001_*.sql`,
   `0002_*.sql`, applied in order with a tracking table. Standard
   pattern. More work to set up, handles all schema changes properly.

Either approach prevents this catchup task from being needed again
the next time a schema change ships while one machine sits idle.
Defer the choice until after this catchup is complete and we have
hands-on context for what would have made it unnecessary.

## Risks

1. **Refactor changed more than just `summary`.** Phase 0 schema diff
   exists specifically to surface this. Do not skip it.
2. **pgvector extension may be missing on amd-tower.** Installing
   PostgreSQL extensions sometimes requires apt packages and a server
   restart — non-trivial on a machine the user doesn't want to reboot
   often (per global guardrails: "Never reboot rpi-server or sapphire";
   amd-tower is rebootable but still worth flagging).
3. **Embedding regen wall-clock.** ~24k records through local Ollama
   is hours, not minutes. Schedule the rebuild for a quiet block.
4. **Ollama model availability.** If amd-tower's Ollama doesn't have
   `nomic-embed-text` pulled, the rebuild will fail mid-run. Check in
   Phase 0.
5. **Wrong sequencing with dedup plan.** See "Coordination" section
   above. Running this catchup first wastes embedding compute.
6. **Cursor file in git.** If `data/memories/sync-cursors.json` is
   tracked rather than gitignored, resetting it for the rebuild will
   create a spurious commit and propagate to zbook. Phase 2 step 4
   verifies this before touching the file.

## Acceptance criteria

- [ ] Phase 0 schema diff complete; full delta documented (not just `summary`).
- [ ] Decision recorded: Option A or Option B, with rationale.
- [ ] Backup taken before any destructive operation.
- [ ] amd-tower's `claude_memories` schema matches `schema.sql` exactly.
- [ ] Row counts on amd-tower and zbook match (within reasonable tolerance).
- [ ] Cursor on amd-tower advanced to current canonical line count.
- [ ] Embeddings populated on amd-tower.
- [ ] Same `/recall` query returns same ids on both machines.
- [ ] No schema errors in the next two cron runs after completion.
- [ ] Phase 4 prevention mechanism scheduled (separate task) so this is
      not needed again.

## Related

- `memory-store-dedup-and-rebuild.md` — independent bug, same general
  area (postgres derived layer needs maintenance), should run before
  this catchup to avoid loading duplicates.
- Recovered memories from session `17293117-1ad8-4ec2-a285-21998a6933a0`
  on 2026-04-02 (ids `2026-04-02-a2fbaed2a501` and `2026-04-02-3a3959cc2e7b`)
  document an earlier attempt to fix the same schema drift; the fix
  appears to have been over-optimistic and did not actually persist.
  Worth reading before Phase 0 to avoid repeating that mistake.
