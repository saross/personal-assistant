# Round 4a fix agent report (branch claude/audit-round4a; 16 commits b8a6547..33a5a40)
Dispositions (finding IDs from lensA-4a.md / lensB-4a.md):
A1 fixed dedup-memories.py:120,348; tag-gardening.py:643,728; monthly-archive.py:187 (escape U+2028; split on "\n") — tests test_two_runs_are_byte_identical, test_line_count_agrees_with_newline_split, test_separator_record_is_not_torn_apart, test_merge_keeps_separator_escaped, test_parse_jsonl_records_does_not_split_on_unicode_separator
A2 fixed tag-gardening.py:901 (guard + flock + re-read in lock), helper :120 — test_orphans_clean_invokes_the_guard, test_orphans_clean_waits_for_a_shared_lock_holder
A3 fixed recover_anchors.py:312,360 (re-check under lock), :176 — test_record_edited_since_planning_is_not_reverted
A4 fixed tag-gardening.py:120 rewrite_vocabulary — comments/blank lines preserved
A5 fixed tag-gardening.py:661 guard below the dry-run return
A6 fixed dedup-memories.py:66,367,507 dated append-only journal memories/dedup-removed-YYYY-MM-DD.jsonl, fsynced before the rename; false .bak line removed
A7 fixed recover_anchors.py:240,349 + try/finally unlink
A8 fixed tag-gardening.py:53,776 — UPDATE memories SET research_tags = %s WHERE id = %s (schema.sql:46 has no `tags` column); on PG failure exit non-zero after JSONL is safe, remedy rebuild-postgres.py
A9 fixed _sync_cursor.py:852,870,900; gates dedup-memories.py:444, archive-memories.py:551 — refuse when postgres_sync_line is behind the "\n" line count; absent cursor is not a backlog
A10 fixed dedup-memories.py:367 reid mapping lines in the journal
A11 fixed sync_memory_edit.py:120 embedding = NULL on content change
A12 fixed tag-gardening.py:584 plan keys lower-cased on load
A13 fixed dedup-memories.py:465,516 unclassified groups excluded from the invariant; exit non-zero only if nothing resolved
A15 tag-gardening.py:159,749 fsync; A16 :856 UTC ISO log; A17 sync_memory_edit.py:146 assert_schema_version; A18 apply-decay.py:42,113,146 PERMANENT_OVERRIDES; A20 recover_anchors.py:402 commit inside the guard lock
A14, A19, A21 recorded not changed
B1/B14 fake cursors execute the real SQL; B2 TestApplyPlans (5) + TestApplyGate; B3 new tests/test_dedup_memories.py (18); B4 conftest.py:300,308 canonical-store snapshot resolved through symlinks, :271 runtime PG refusal; bypass_rewrite_guard narrowed to 17 named tests; B5-B19 as named in the agent's table (SQLite shim runs decay_where with dialect translated, operators untouched; literal caps pinned; add -A killed by asserting the index).
NEW: (1) sync-to-postgres.py:451 maps only research_tags; a legacy `tags`-only record syncs with an empty array. (2) sync-to-postgres.py:1354 saves the cursor as a splitlines() count; the A9 gate counts "\n" — a raw separator already on disk makes the cursor larger than the count, so the gate reads "caught up" when it is not. (3) test_hermeticity_fixture's AST scan catches only a test calling psycopg2.connect; conftest.py:271 is now the runtime net.
INCIDENT: before e85ec48, eight tag-gardening merge tests opened a real connection to live claude_memories and committed an UPDATE ... WHERE id = %s with fixture ids mem-001..mem-303. Coordinator verified read-only: SELECT count(*) FROM memories WHERE id LIKE 'mem-%' = 0, so nothing matched.
Suite: 2454 passed, 3 deselected, exit 0.
Live risks: archive-memories --apply and dedup-memories refuse while the cursor is behind; /tags merge talks to PG and exits non-zero on failure after the JSONL is safe; orphans clean takes the exclusive lock and refuses on a dirty tree; vocabulary keeps comment positions, new tags appended; dedup writes a journal file into the data repo; /update clears the embedding; tests that reach psycopg2.connect unpatched or write the real store now fail.
