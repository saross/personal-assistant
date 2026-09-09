# Lens A (correctness) — tranche 4a: memory-store writers — HEAD 505ca8c

## Critical
1. dedup-memories.py:293 (write, ensure_ascii=False) + :98 (read, splitlines()) — un-escapes U+2028 / U+2029 / U+0085 that hooks/extraction-hook.py:1372 (json.dumps default) had escaped; splitlines() treats them as line breaks. Repro: one record with U+2028 → after run 1 the file had 3 lines by iteration, 4 by splitlines(); after run 2 the record was split into two malformed lines, unrecoverable. Same write defect at tag-gardening.py:591,647. sync-to-postgres.py:1370-1374 documents this hazard as hypothetical; the PG cursor is a splitlines() count, so the divergence also desynchronises the cursor from every file-iteration reader. CONFIRMED.
2. tag-gardening.py:744 — `orphans --action clean` rewrites protected memories/tag-vocabulary.txt with a bare write_text: no ensure_safe_to_rewrite, no lock, no temp+rename, no backup. The extraction hook appends under LOCK_SH (extraction-hook.py:390); a concurrent append is lost; daily-sync can commit a half-written file. /tags step 7 (commands/tags.md:145) invokes it routinely. CONFIRMED.
3. recover_anchors.py:434 + :302-352 — plan built outside the rewrite lock; apply_plans writes whole stale records (json.dumps(by_id[rid]["record"])) → a /forget + /update landing between plan and apply is reverted. archive-memories.py:359-361 re-reads inside the lock precisely to avoid this and the recover_anchors docstring claims parity. CONFIRMED.

## Medium
4. tag-gardening.py:676-687 and :744 — both vocabulary rewrites drop every `#` comment line (live file has 8 section headers). CONFIRMED.
5. tag-gardening.py:501 — bulk guard runs before the --dry-run branch (:557): a dry run takes the exclusive daily-sync.lock to exit and aborts with exit 2 on a dirty tree. dedup-memories.py:355 skips the guard on dry-run; the comment at :551 refers only to the JSONL flock. CONFIRMED.
6. dedup-memories.py:383 — logs "Backup is at: …memories.jsonl.bak.<date>"; nothing creates it. CONFIRMED.
7. recover_anchors.py:233 and :328 — json.loads(line) with no try; one malformed line aborts dry-run and apply with a traceback; at :328 after tmp is opened, orphaning memories.jsonl.tmp. CONFIRMED.
8. tag-gardening.py:692 — a tag merge never reaches PostgreSQL and the printed remedy ("Run sync-to-postgres.py") is wrong: that script is INSERT … ON CONFLICT DO NOTHING (:868) and reads only after the cursor. commands/tags.md:167+ correctly says a full rebuild is needed. No surgical UPDATE exists for tags. CONFIRMED-by-code.
9. Line-position cursor plus mid-file deletion silently skips unsynced records: sync-to-postgres.py:1354-1382 resets only when cursor_line > total_lines. A sweep removing K lines with a backlog of B unsynced records, K <= B, leaves K never-synced records below the cursor forever. monthly-archive syncs PG first; standalone archive-memories --apply or dedup-memories does not; no rewriter touches sync-cursors.json. SUSPECTED (no PG).
10. dedup-memories.py:160 vs :292 — re-id path records no old→new id mapping (`_dedup_origin` stripped before writing, never logged); surfaced.log, superseded_by, PG row + embedding under the old id are orphaned with no trail.
11. sync_memory_edit.py:55,107 — /update replaces content but leaves embedding intact; refill only WHERE embedding IS NULL (sync-to-postgres.py:1115, backfill-embeddings.py:126), so semantic recall matches the pre-edit text. Adding embedding=NULL to the UPDATE self-heals on the next cron tick. SUSPECTED.
12. tag-gardening.py:541 vs :581,634 — plan keys stored raw, matched lowercased: a loser with any uppercase replaces nothing while reporting "Tags retired: 1". CONFIRMED.
13. dedup-memories.py:244 vs :402 — one unclassified duplicate group aborts the whole run (invariant sys.exit(1) on any surviving duplicate id) though the comment says unclassified groups are kept verbatim. Fails closed but can never progress. CONFIRMED.

## Low
14. archive-memories.py:366-378 — files fsynced, parent directories not. SUSPECTED.
15. tag-gardening.py:663,683 — write_text + os.rename with no flush/fsync; whole corpus built in memory.
16. tag-gardening.py:703 — merge log stamped naive local datetime.now(); every other log is UTC ISO.
17. sync_memory_edit.py — never calls assert_schema_version, though _schema_version.py:26-31 says every PG-touching script must.
18. apply-decay.py:105-118 — permanence solely from category_config.decay_days IS NOT NULL; schema.sql:228-236 seeds gotcha/pattern NULL with ON CONFLICT DO NOTHING so a legacy 180 cannot be repaired by re-seeding; no PERMANENT_OVERRIDES net. Defence-in-depth asymmetry.
19. archive-memories.py:328 — partition month from datetime.now(timezone.utc): an AEST run in the first 10-11 h of a local month writes to the previous month's partition. (Decision: UTC vs local.)
20. recover_anchors.py:351 — commits after release_lock(); archive-memories.py:381-389 moved the commit inside the guard lock (S15) to stop daily-sync committing the rewrite without the Rewrite-Class: bulk trailer. Same window open here.
21. archive-memories.CORPUS/ARCHIVE_DIR and recover_anchors.CORPUS are Path.home()-derived: an --apply from a copy or worktree targets the live store (documented as deliberate; latent).

## Cross-file
- Schema use consistent; commitment ages from COALESCE(deadline_at, created_at) identically in apply-decay (SQL), archive-memories.should_archive, monthly-archive.record_age_days, strict >.
- _timestamps.py imported by no mutator here; each rolls its own ISO parsing (agree by luck).
- JSON serialisation not uniform: hook and recover_anchors json.dumps(rec); dedup and tag-gardening ensure_ascii=False (finding 1).
- PG change detection is line position only (no content hash, no updated stamp); every in-place edit needs its own surgical UPDATE; tag-gardening has none.
- Adjacent: hooks/extraction-hook.py:1375 ignores os.write's return value; a short write could leave a final line without newline, and all rewriters preserve the last line verbatim, so the next append concatenates onto it.

## Verified correct
should_archive boundaries and edge cases; CRLF round-trips; blank/unparseable lines preserved by partition_corpus, dedup, tag-gardening merge; partition append flushed+fsynced before the corpus rename; _partition_ids idempotent; LOCK_EX held across read-modify-rename in dedup, tag-gardening merge, archive-memories, recover_anchors (planning read excepted); temp files in the target directory; no injection; no __file__-derived import-time writes; UK spelling clean.

## Answers
1. Deletion: archive-memories copies to partition (fsync) before rename — correct; dedup: no archive, no backup, false log (6); tag-gardening merge/orphans clean: vocabulary entries and comments, no copy (2, 4); recover_anchors records removed refs in revisions; apply-decay deletes nothing.
2. apply-decay: permanent iff decay_days NULL; clock created_at (commitment: COALESCE(deadline_at, created_at)); malformed date → whole UPDATE caught at :151, nothing decays that cycle.
3. dedup: longest summary wins (ties: earliest line); byte-identical keep first; losers share the winner's id; reprocess-collision path mints new ids with no mapping (10).
4. tag-gardening: no PG effect; wrong remedy (8); partial failure between JSONL and vocabulary rewrites leaves them inconsistent; orphans (the unguarded writer) is the repair.
5. monthly-archive: UTC month boundary; strict >; re-run idempotent by id; wrapper flock.
6. recover_anchors clobbers a concurrent human edit (3); fix: re-read and re-plan inside the lock.
7. No import-time writes; archive-memories/recover_anchors pin CORPUS to Path.home() (21).
