# Lens A (correctness) — tranche 7: memory readers, reports, anchors — HEAD 2a4b3bc

## Critical
1. anchor_verify.py:98-106 — `git log --all --max-count=1 -- <ref>` without --literal-pathspecs: a file ref with pathspec syntax matches as a PATTERN ("*.md" → true, ":(exclude)zzz" → true in a repo with no such file). Junk anchors mint verified=true then confidence=high (bind_confidence). 15 live records carry a glob-char file ref (aggregate count). CONFIRMED.
2. anchor_verify.py:195-222 with triage_anchors.py:50-88 — build_basename_index pools git ls-files from all 36 repos into one namespace with no repo attribution; unique_suffix_match returns matches[0] if unique ACROSS THE UNION, not within the memory's project: project A's dead src/util.py "recovers" to project B's pkg/src/util.py and verifies true. Reporting-only in drift-sweep/Tier-C, but recover_anchors.py:131-141,155 WRITES the foreign ref and flips verified false→true. CONFIRMED.
3. anchor_verify.py:93-95, 109-110, 258-259 — `except (FileNotFoundError, OSError): return "false"`: a missing git binary, unreadable repo, or unmounted mount yields "false", never "pending"; when every repo fails the aggregate is false (pending_seen only on TimeoutExpired). Contradicts the contract at :32-35 ("any internal error returns pending"). drift-sweep appends a permanent bogus trend line and exits 1; recover_anchors treats the ref as a candidate and (:150-155) writes recomputed verified/confidence back. CONFIRMED.

## Medium
4. memory-health-report.py:721 → audit-postgres-sync.py:246-250 — sys.exit(2) inside a reused library function (_read_postgres_active_map → assert_schema_version); build_report does not catch SystemExit, so a schema bump kills /memory-health with no report at all though sections A-C, E, G, H need no PG. CONFIRMED (fake PG).
5. memory-health-report.py:197-224 — `anchored` counts any truthy anchors, including 103 live records whose anchors are all unknown types that verify_memory:439-441 skips; [C] % anchored overstates verifiable coverage; a non-list anchors (string) iterates per character (12 "malformed" from one record). CONFIRMED.
6. drift-sweep.py:69-86 via memory-health-report.py:412-421 — `if created is None or created <= cutoff: continue`: a record with a missing/unparseable created_at is silently excluded from the "full back-set", defeating the docstring's "never ages out" (drift-sweep.py:14-20). Live incidence 0 today. CONFIRMED.
7. drift-sweep.py:79-86 — no floor on broad_repo_set(): a degraded repo set (other machine, ~/Code unpopulated, unmounted) makes every anchor false, appends that to the append-only trend log (fail_pct 75.0 with an empty set), exits 1; [H] shows the fabricated spike forever. CONFIRMED.
8. memory-health-report.py:63, :490-503 — quarantine_count() maps read_quarantine_entries(...) is None (unreadable/missing) to 0 and build_report:743-747 folds it into `clean`: an unreadable quarantine file prints "0 (expect 0)" and overall PASS; _sync_cursor.py:319-321 warns None "is emphatically not empty". QUARANTINE_FILE is the only path constant without the data/→symlink fallback (contrast :56-76). CONFIRMED by read.
9. audit-postgres-sync.py:139-168, 282-291 — compares id SETS only: identical ids with different content/is_active/verified → is_clean=True; 3 lines/2 ids vs 2 rows → clean; an orphan PG row reported but is_clean=True (AuditResult.is_clean:103-106 ignores only_in_postgres). Since the sync is ON CONFLICT DO NOTHING, content divergence is the expected failure mode and the audit cannot see it. CONFIRMED.
10. drift-sweep.py:83-85, memory-health-report.py:771-773 — unmemoised lambdas (siblings memoise: triage_anchors.py:120-138, recover_anchors.py:207-227); verify_file loops 36 repos, up to 2 git spawns each (timeout 3 s): one unresolvable ref costs up to 72 spawns / 108 s, repeated per duplicate ref across 5,537 anchored records; tier_c_audit:432 re-resolves each file anchor again. SUSPECTED.

## Low
11. anchor_verify.py:181 — `(repo / expanded).exists()` without normalisation: "../outside.txt" → true for a file in no repo. CONFIRMED.
12. anchor_verify.py:267 — len(s) < 4 admits 4-char hex as a commit ref; verify_commit:245-253 accepts a hit in any of 36 repos. SUSPECTED.
13. memory-health-report.py:71-73 and surfacing_stats.py:42 — still ignore PA_SURFACED_LOG (carried follow-up (ii) unfixed at this HEAD). CONFIRMED.
14. memory-health-report.py:452-487 — pg_snapshot issues four schema-dependent queries before any assert_schema_version; no PG call in the tranche sets statement_timeout or a read-only transaction; a lock-contended DB hangs /memory-health.
15. recover_anchors.py:95-100 — absolute/tilde refs excluded from recovery; 659 live anchors are absolute or tilde-rooted; one written from ~/worktrees/… is unresolvable forever after the worktree is removed. SUSPECTED.
16. memory-health-report.py:110-133, 140-155, 190-224, 325-345 — no section filters is_active (9 live inactive); [A] prints the JSONL total beside the active_memories view count (two populations).
17. memory-health-report.py:335-344 — [G] top-5 ids from surfaced.log with no corpus membership check.
18. drift-sweep.py:111-119 — append_trend swallows every exception; with data/logs absent the sweep WARNs and the trend gains no row.

## Cross-file
- Three definitions of a line: sync-to-postgres.py:1354 splitlines (being changed on PR #123 to _sync_cursor's "\n"), _sync_cursor.py:852-867 "\n", audit-postgres-sync.py:150 file-handle iteration; the audit is insulated only because it works on ids.
- recover_anchors.py:430-433 passes --literal-pathspecs to git add/commit with a comment about globs, while anchor_verify.py:99-101 omits it on the pathspec that decides verification.
- project_id.repo_set() and triage_anchors.broad_repo_set() independently maintained but identical today (36 repos); adding a root to one desynchronises them.

## Verified correct
No shell=True/os.system; every git call an argv list. Empty-corpus arithmetic guarded everywhere. Exactly one write site in the tranche (drift-sweep.py:114-116). Privacy: ids, refs, counts only. verify_memory None-vs-false guard (:459-465) as documented over 7 malformed shapes. read_quarantine_entries the single parser. parse_confab_log excludes checked=0 rows. UK spelling clean.

## Answers
1. Reads: memory-health-report data/memories/memories.jsonl (fallback memories/), archive/*, quarantine-postgres-drops.jsonl, logs/{confab-flags.log,surfaced.log,drift-sweep.jsonl}, PG, git (--tier-c); drift-sweep memories.jsonl + git; triage_anchors ~/personal-assistant/data/memories/memories.jsonl + git; audit-postgres-sync memories.jsonl, ~/cc-archives/**/session.meta.json, archive/*.jsonl, PG; anchor_verify none. Writes: exactly one — drift-sweep.py:58,111-119 appends logs/drift-sweep.jsonl (inside data/). No report file; /memory-health is stdout-only.
2. Yes (critical 3): false not pending on transient failure; recover_anchors then writes.
3. Same counters via surfacing_stats.aggregate_surfacing/summarise (:702); top-5 re-implemented consistently; neither honours PA_SURFACED_LOG.
4. No: id sets, no cursor read, no lock; can say "in sync" with divergent content, duplicate lines, PG orphans; human-run only.
5. drift-sweep mutates only its trend log.
6. git calls gated by _GIT_TIMEOUT_S = 3 and shape gates, no --literal-pathspecs; triage git ls-files timeout 20, exceptions swallowed; memory-health-report two psycopg2.connect (:460 unguarded by schema check; :721 guarded but sys.exits), no statement_timeout, degrade to "PG sections skipped"; audit-postgres-sync three connects, schema-guarded with sys.exit(2), whole-column id pull. No network.
7. __file__-derived: memory-health-report.py:53-76 (read-only), drift-sweep.py:45,57,58 (LOG_PATH written; --log-path overrides), audit-postgres-sync.py:56,57,69, surfacing_stats.py:41-42. triage_anchors.py:142 and recover_anchors.py:87 hard-code Path.home()/personal-assistant (read the LIVE corpus from any copy; recover --apply guarded).
