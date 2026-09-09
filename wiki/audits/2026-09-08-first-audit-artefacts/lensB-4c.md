# Lens B (test adequacy) — tranche 4: session archive pipeline — HEAD b4d0c57
Baseline: tranche test files 92 passed; full suite 2357 passed used for the zero-test scripts; nothing written outside caches; ~/cc-archives untouched. 31 mutations survived; 5 positive controls killed.

## Critical
1. check-archive-drift.py has ZERO tests (only a stub in tests/daily_sync_harness.py:649): `missing = {}` at :173 and always-trivial at :133 both leave the FULL suite green. It is the sole tripwire for the 2026-07-28 77-session gap. Minimum suite: substantive unarchived session reported + gate written; <4,000-char session not; session younger than GRACE_HOURS not; archived session not; exit 2 when either store is missing; gate's first line is the count.
2. bulk-archive.py incremental skip and triviality predicate unpinned: :516 `if session_id in archived_ids` neutered → green; :535 is_trivial_session forced True and False → green; archived_session_ids_on_disk (:334) returning set() → green. discover_sessions never called by any test.
3. No test runs any cmd_* entry point of bulk-archive.py (cmd_archive :1003, cmd_verify :2181, cmd_subagents, cmd_enrich, main). Survivors: checkpoint update dropped at :1132 (resume re-archives everything); `except Exception` → `except BaseException: pass` at :1136; missing-transcript check blinded at :2211 (verify says clean over an archive whose transcripts are gone); rebuild_catalogue → {"sessions": []} at :2253 (CATALOG.json truncated); relocate_to_legacy_precedent no-op'd (:758).
4. normalise-archive-storage.py has zero tests and deletes transcripts: removing the sha256 round-trip verify in write_gz_verified (:89-91) green; adding raw.unlink() to the DIVERGENT branch (:158) green.

## Medium
5. search-archives-safe.sh: `if ! flock -n 9` (:177) → `if false` survives; emptying LIMIT_PREFIX (:132) survives. Sandbox run with a synthetic .gz: normal search exit 0 with path:lineno output; second invocation against a held lock exit 3 with REFUSED — observable in a second, untested.
6. push-archives-to-r2.sh: only test is the rclone-version probe (test_glue_scripts.py:466-511, S14); dropping --dry-run at :141 and the mount guard at :116 both survive (reasoned + green; the S14 test stops at the mount precondition).
7. _scan_archives.py: per-line truncation at :91 (and :190) removable; `except (OSError, EOFError, BadGzipFile)` at :118 → `except BaseException` survives.
8. reprocess-sessions.py: only COMMAND_MARKERS identity and timestamp shape are pinned (test_command_markers.py:146, test_timestamps.py). Survivors: already-extracted skip removed at :235; transcript read from the wrong session directory at :238; ensure_safe_to_rewrite neutered at :758; JSONDecodeError on a partial last line → entry = {} at :285.
9. validate-session-metadata.py (537 lines) zero tests: check_schema (:210) disabled → green. Minimum: one record per defect class (wrong project tag, empty provenance_summary with prose misfiled into process_summary, missing tag), --fail-on exit semantics, "manifest absent ⇒ skipped, never a pass".
10. backfill-summaries.py: post-write line-count invariant (:241) and temp+rename (:228) both removable, full suite green.
11. extract-transcript-text.py (re-export shim) and extraction-prompt-spotcheck.py zero tests (SUSPECTED): pin that every re-exported name at :42-51 resolves; pin that the default (no --run) makes zero API calls.

## Low
12. tests/test_bulk_archive.py: TestDiscoverSkipsFlat.test_flat_agents_excluded (:383-404) re-implements the filter in the test; TestVerifyDetectsIssues.test_detects_missing_jsonl (:415-433) asserts a file it declined to create does not exist. Neither can fail.
13. test_simple_path (:204-215) is a tautology (`None or Path`) and probes the operator's real filesystem via is_dir() on absolute paths (bulk-archive.py:180-205).
14. Cross-machine "largest wins" (bulk-archive.py:577) `>` → `<` survives (0-byte copy would win).

## Surviving mutations (all CONFIRMED)
bulk-archive.py:516 skip → False; :535 trivial → False/True; :334 set(); :577 > → <; :745 chunk loop → single 8 KiB read (subagent archives truncated); :750 count outside try; :1132 checkpoint dropped; :1136 BaseException pass; :1219 tool_result skip removed (tool output sampled as user prose); :1242 last = []; :2211 missing-JSONL check removed; :2253 catalogue → empty; :758 relocate no-op; :540 "subagents" → "no-such-dir" (every subagent silently unarchived).
check-archive-drift.py:173 missing = {}; :133 all trivial.
normalise-archive-storage.py:89 verify removed; :158 unlink in DIVERGENT.
_scan_archives.py:91 truncation removed; :118 BaseException.
search-archives-safe.sh:177 flock → false; :132 LIMIT_PREFIX=().
push-archives-to-r2.sh:141 --dry-run dropped; :116 mount guard → false.
validate-session-metadata.py:210 check_schema disabled.
reprocess-sessions.py:235; :238; :758; :285.
backfill-summaries.py:241; :228.

## Wiring / fixtures / negatives / default path
- Wiring: no script in the tranche has a test running its real entry point against a synthetic ~/.claude/projects tree and archive root asserting a consequence on disk. test_bulk_archive.py calls private helpers plus resolve_project_mapping. The actual write path (compression, metadata, catalogue) lives in cc_session_toolkit.archive under ~/Code/cc-session-toolkit — a separate checkout; no temp-file staging, os.replace, or lock found there; nothing in this repo pins it.
- Fixtures: synthetic transcripts (test_bulk_archive.py:36-87, :109-135) are {"message": {role, content}, "timestamp"} plus one {"type": "system", "cwd"}. Missing shapes production writes and the tranche reads: top-level type user/assistant (check-archive-drift.py:93 — under these fixtures every session scores zero chars); isMeta (extraction-hook.py:700,738,777,844); isSidechain (:701,731); uuid/parentUuid; sessionId; version; isCompactSummary (check-archive-drift.py:95); tool_result blocks (bulk-archive.py:1219); thinking blocks (reprocess-sessions.py:299); the toolkit's skipped types file-history-snapshot, queue-operation, custom-title, agent-name, last-prompt. bulk-archive._sample_user_messages (:1195-1231) never consults isMeta/isSidechain, so harness text and sub-agent prose are sampled as the user's own words into enrichment prompts.
- Negatives: only TestArchiveSubagents.test_returns_zero_for_no_subagents. No test that a non-substantive session is NOT archived, an archived one NOT re-archived, a grace-window session NOT flagged, a mid-write session skipped, or --dry-run writes nothing.
- Default path: conftest repoints HOME at import so Path.home()-derived constants are safe (bulk-archive.py:56-58, check-archive-drift.py:58-60, reprocess-sessions.py:58, normalise-archive-storage.py:116, _scan_archives.py:130, extraction-prompt-spotcheck.py:49-52). __file__-derived: LOG_DIR in bulk-archive.py:50, reprocess-sessions.py:53, backfill-summaries.py:55; MEMORIES_FILE in reprocess-sessions.py:56, backfill-summaries.py:54 — resolve to the real checkout; setup_logging() opens a FileHandler unconditionally. Today no test reaches them (CHECKPOINT_FILE/MANIFEST_FILE patched at test_bulk_archive.py:327/:335). Guard recommendation: fail on writes under PROJECT_ROOT/logs, PROJECT_ROOT/data, REAL_HOME/cc-archives (round 4a's conftest change already snapshots the store and logs/).
