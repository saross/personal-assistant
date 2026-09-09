# Lens B (test adequacy) — tranche 7: memory readers, reports, anchors — HEAD 2a4b3bc (unchanged at 7a3d861)
Baseline: tranche 164 passed; full suite 2451 + 2 non-recurring failures in tests/test_daily_sync_trigger.py (five later runs 2453 each). 68 mutations, 39 survived.

## Critical
C1. audit-postgres-sync.py:265 audit_memories, :319 audit_sessions, :365 audit_archive_parity, :165/:216 PG readers, :453 main — the reconciliation engine is unreached by any test: swapped set-difference direction, "in sync" on differing counts, hard-coded table instead of {table}, dropped `WHERE id = ANY(%s)`, inverted leaked_active (is True → is not True), never leaking, archived_not_in_pg from the wrong side, skipped schema guard, main() returning 0 with missing rows or a live leak — all 10 survive (P8 re-confirmed on the full suite).
C2. audit-postgres-sync.py:204-210, 252-260 — inserting `DELETE FROM memories WHERE FALSE` + conn.commit() → full suite green; no fake cursor drives these paths, so the no_live_postgres net never fires here.
C3. memory-health-report.py:660 build_report, :774 main — never called: main returning 0 on failed integrity, dropping the missing-corpus exit-2 guard, zeroing the quarantine count in the report, dropping archive-leak and duplicate-id terms from `clean` all survive; documented exit codes (:23-27) never asserted.
C4. memory-health-report.py:452 pg_snapshot — SQL never executed against anything: `WHERE is_active IS TRUE` → `IS NOT NULL`, `FROM active_memories` → `FROM memories` survive; the P2 recall invariant is unverifiable.
C5. triage_anchors.py:112 broad_repo_set returning [] survives the full suite (sole repo input to drift-sweep.py:77 and memory-health-report.py:754 → every anchor false, ~100 % drift, --alert-threshold exit 1). It resolves from Path.home(), not PA_DIR/__file__ (unlike drift-sweep.py:45, memory-health-report.py:48): from a ~/worktrees/ checkout it verifies against the wrong repository or none (runtime demo).

## Medium
M-a. anchor_verify.py:98-104 no --literal-pathspecs: `scripts/*.py`, `*.py`, `scripts/?eal.py`, `scripts/[r]eal.py`, `:(glob)**/real.py` all "true" with no such file; _looks_like_file_ref (:284) does not reject globs; triage_anchors.py:166 names globs as expected-false residual.
M-b. anchor_verify.py:65-111, :230-261 — .git chmod 000 → "false" not "pending"; bind_confidence pins low; contradicts :32-35; only TimeoutExpired maps to pending; no test distinguishes absent from could-not-check.
M-c. memory-health-report.py:70-71 SURFACED_LOG bound at import from PA_DIR vs surfacing_log.py:98-129 call-time PA_SURFACED_LOG: with the override set, section [G] reports "no surfacings logged yet" — the class test_memory_health_report.py:303 guards for the quarantine file is absent here.
M-d. triage_anchors.py:50 build_basename_index → {} survives; widening its except to bare Exception survives.
M-e. drift-sweep.py:69-86 run_sweep stubbed out of every test (test_drift_sweep.py:105): days=30 hard-coded (defeating :16-20), constant verify_file_ref, repos=[] survive.
M-f. drift-sweep.py:158 --memories never asserted honoured (load_records stubbed).
M-g. conftest.py:300-305 watch list omits data/reports/, data/notes/, data/memories/archive/memories-archive-*.jsonl, quarantine-postgres-drops.jsonl (a control write into logs/ is caught).
M-h. anchor_verify.py:459 removing the saw_any_valid_anchor guard survives ("true" with nothing checked).

## Low
L1 anchor_verify.py:230-261 no test passes a non-empty repo_set to verify_commit (first-repo-only / ignore repo_set survive). L2 memory-health-report.py:205 dropping .lower() on verified survives; "stale" (documented valid, memory-system-reference.md:52-54) silently → low, untested. L3 :120/:139/:415 naive timestamps rejected, growth boundary flipped, unparseable dates counted — survive. L4 :110 bare Exception in load_records survives. L5 :349 top-N [:5] → [:1] survives (fixture has 2). L6 three notions of a line (audit-postgres-sync.py:144 handle iteration incl. \r; sync-to-postgres.py:1354 splitlines; _sync_cursor.py:852 "\n"). L7 triage_anchors.py:141 main — injecting a corpus write survives ("never mutates" unenforced); :120 memoising on ref alone survives.

## Wiring / fixtures / negatives / default path
- anchor_verify and triage_anchors helpers well wired (9/12 and 6/11 mutations killed). drift-sweep main() driven with consequences (test_drift_sweep.py:108-141) but run_sweep stubbed. memory-health-report main/build_report/render_report never called anywhere; audit-postgres-sync main and all three audits never called (grep: only test_recover_anchors.py:503 hits build_basename_index of a different module). SQL strings unreached entirely.
- Fixtures missing (live counts of 42,896): verified absent (37,546; tests carry explicit None only), bool or mixed case, "stale"; anchors [] (42); revisions (835); is_active false (9); naive created_at (1); date-only; no created_at. No PG fixtures at all.
- Negatives present where tested (tier-C window, recovery split, decoy archive-runs, --no-log). Missing: clean corpus → PASS exit 0; leak → exit 1; triage main dry-run writes nothing; verified=true excluded from false-triage; quarantine_count reaches the rendered report.
- Default path: no tranche test writes real paths or opens PG (verified); no_live_postgres never fires here because nothing reaches connection code — unreachability, not the guard, protects these scripts; watch list gap M-g; nothing integration-marked.
