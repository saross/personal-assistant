# Lens B (test adequacy) — tranche 4a: memory-store writers — HEAD 505ca8c
Baseline: nine test files, 170 passed, 3 deselected; nothing written outside caches. 63 mutations.
Note: apply-decay.py is PostgreSQL-only (does not touch memories.jsonl).

## Critical
1. sync_memory_edit.py:107-110 — UPDATE WHERE clause untested (WHERE id!=%s stays green; test compares the constant with itself, fake cursor never executes). A /forget would blank content/confidence/verified/anchors on every other PG row.
2. recover_anchors.py:333 — whole write path untested: deleting `else: out.write(line)` (only modified records survive) stays green; also green: drop ensure_safe_to_rewrite (:317), lock -> nullcontext (:319), direct write instead of tmp+rename (:320), delete the `if not args.apply: return 0` gate (:441) so a dry run mutates and commits. apply_plans has no test.
3. dedup-memories.py — no test file. Unpinned: pick_summary_winner:129, reid_reprocess_collision:143, --dry-run gate main:325, guard/lock wiring :337/:356, size abort :381, atomic rename :296, invariant exits :404/:424. MEMORIES_FILE/LOG_DIR (:55-62) resolve to the real store from __file__.
4. tests/test_tag_gardening.py — a test that forgets to patch MEMORIES_JSONL rewrites the REAL canonical store and the suite stays green (reproduced in a copy: rewrote data/memories/memories.jsonl, tag-vocabulary.txt, wrote data/logs/tag-gardening.log, "37 passed"). Cause: autouse `_bypass_rewrite_guard` (tests/test_tag_gardening.py:31-56) noops ensure_safe_to_rewrite; conftest hermeticity guard (tests/conftest.py:220-260) watches only ~/.cache globs.

## Medium
5. tag-gardening.py:613 — malformed JSONL line dropped on JSONDecodeError (removing lines.append(line) green). archive-memories has the equivalent test; tag-gardening none.
6. tag-gardening.py:501-505, :603, :673, :662-664 — guard + atexit release, JSONL flock, vocabulary flock, tmp+rename atomicity all unpinned.
7. apply-decay.py:107, :111-112, :102 — decay predicate asserted by substring: NOW()-interval -> NOW()+interval; < -> > on commitment branch; AND is_active -> OR — all green.
8. apply-decay.py:88-93 — assert_schema_version call deletable (tests filter the meta query out).
9. archive-memories.py:337 (JSONL flock), :372 (atomic rename), :534 (--apply gate) — all green; dry run archives, rewrites, commits.
10. archive-memories.py:427-430 — Rewrite-Class: bulk trailer droppable (that trailer is what stops daily-sync's shrink detector resetting the archival commit).
11. archive-memories.py:441-442 — `git add --literal-pathspecs -- <paths>` -> `add -A` green; sweeps unstaged modifications.
12. recover_anchors.py:155 — corrected record can keep stale `verified` (test asserts plan["new_verified"], not the written field); :185 revisions overwritten vs appended untested.
13. recover_anchors.py:133 — "already resolves?" gate removable (recover stub returns None); :100 _is_relative_file_ref accepting absolute refs; :234 build_plans selecting verified=="true" — all green; build_plans untested.
14. sync_memory_edit.py:128 — `with conn, conn.cursor()` -> `with conn.cursor()` green: UPDATE discarded on close, "PostgreSQL reconciled" printed.
15. monthly-archive.py:112 (SANITY_ABS_CAP self-referential: test asserts CAP+1), :491-494 (post-apply sanity re-check deletable), :484-485 (partition HALT -> return 0 green).

## Low
16. tag-gardening.py:633 tag.lower() removable (fixtures all lowercase; build_tag_counts:117 lowercases).
17. tag-gardening.py:111 _get_tags field precedence inverted green (no fixture carries both tags and research_tags).
18. monthly-archive.py:236 naive-timestamp normalisation and :231 Z->+00:00: green; the Z test is vacuous on Python 3.13 (fromisoformat parses Z natively).
19. archive-memories.py:377 os.fsync and tag-gardening.py:691 _log_merge unobserved.

## Wiring / fixtures / negatives / default path
- Entry-point-to-disk tests exist for monthly-archive, archive-memories (apply_archive), sync_memory_edit (main exit codes only; reconcile_pg patched away). None for recover_anchors, tag-gardening (main never called; only cmd_* with hand-built Namespace), dedup-memories, apply-decay (main never called). No script exercised via subprocess/CLI.
- Fixtures: _production_record helpers in test_archive_memories.py:238 and test_monthly_archive.py:262 faithful to hooks/extraction-hook.py:1210 / anchor_verify.verify_memory:408; stale docstring line refs (:900 -> :1210, :1173 -> :1530). Shapes never in fixtures: verified "pending"; a record with NO anchors key; is_active/revisions (from /forget, /update). conftest.py:83 sample_memories is a ten-field record the pipeline cannot emit (no licence, extractor_model_id, source_message_uuid). test_monthly_archive.py:189 DECAY gives gotcha/pattern None whereas archive-memories docstring says category_config records 180 for them — no test exercises a permanent category with a finite window (what PERMANENT_OVERRIDES exists for). Every tag fixture lowercase.
- Negatives: good in archive-memories, monthly-archive, tag-gardening detectors. Missing: recover_anchors (stubs cannot fail), apply-decay (no "row NOT selected" test), tag-gardening merge (no byte-identical untouched-record test).
- Default path: no test exercises a production default. tag-gardening.py:42-51, dedup-memories.py:55-62, apply-decay.py:31-33, sync_memory_edit.py:50 bake real-repo paths from __file__ at import; archive-memories.py:81 / recover_anchors.py:64 use Path.home() (neutralised only by conftest's HOME repoint). Hermeticity guard covers ~/.cache only. Minimum fix: guard snapshots memories/memories.jsonl, memories/tag-vocabulary.txt, logs/ alongside ~/.cache; narrow _bypass_rewrite_guard from autouse to the tests that need it.
