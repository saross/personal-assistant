# Audit round 4f — memory readers, reports, and anchors — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4f`, branch
  `claude/audit-round4f`, at main. Sibling agents own `tests/conftest.py`,
  `tests/test_hermeticity_fixture.py`, `tests/test_glue_scripts.py`, the daily
  sync, the retrieval scripts (`surfacing_stats.py` is theirs — for M-c touch
  ONLY `memory-health-report.py`, and only the one path line), the archive
  pipeline, the external-services scripts, and the bake-off tooling — do NOT
  edit any of those. `recover_anchors.py` was fixed in an earlier round; you
  may change it minimally where AN2/AN3 require (its consumer of "false").
- Lens reports: `lensA-7.md` (correctness, findings 1-18 → cite as AN1-AN18)
  and `lensB-7.md` (test adequacy, C1-C5, M-a..M-h, L1-L7 → cite as
  ANT1-ANT5, ANT-Ma.., ANT-L1..) in this directory. Line numbers at 2a4b3bc.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit it.
- Scope: `scripts/anchor_verify.py`, `scripts/triage_anchors.py`,
  `scripts/drift-sweep.py`, `scripts/memory-health-report.py`,
  `scripts/audit-postgres-sync.py`, minimal `scripts/recover_anchors.py`,
  their tests, and `commands/memory-health.md` (and any command that
  documents anchor verification) where a claim changes. Reuse
  `tests/_fake_pg.py` if it exists on main (it lands with PR #122; if absent,
  build a small fake cursor that evaluates the SQL against seeded rows and
  records every executed statement — a DELETE must be observable).

## Absolute safety rules

Never open a Postgres connection (a live `claude_memories` is reachable; the
suite's conftest now points PGHOST nowhere and refuses sockets — keep every
test patched anyway); never run any script against the real store or real
repositories; synthetic corpora and throwaway git repositories only; never
write under `~/.claude`, `~/.cache`, the repository's `logs/`, `data/`,
`reports/`, or `wiki/`.

## Must fix (Critical and Medium from both lenses)

Order: AN1, AN3, AN2, ANT1+ANT2, ANT3+ANT4, ANT5 first, one commit each.

AN1 (critical) — `anchor_verify.py:98-106`: `git log --all --max-count=1 --
<ref>` must run with `--literal-pathspecs` (and `_looks_like_file_ref` at
:284 must reject pathspec magic: leading `:`, `*`, `?`, `[`); `:181`'s
existence check must normalise and refuse a path that escapes the repository
(AN11). Tests: `scripts/*.py`, `:(glob)**/x.py`, `../outside` all "false";
a real file "true".

AN3 (critical) — transient failure is "pending", never "false": a missing
`git`, an unreadable repository, an unmounted mount, `OSError`,
`TimeoutExpired`, and a git exit code that is not 0/1/128-with-"did not
match" all yield "pending"; "false" only when every repository was checked
and the reference was absent in each. `bind_confidence` on "pending" must
not lower confidence. `recover_anchors.py:133` must treat only "false" as a
candidate. `drift-sweep` must not log a trend row when the pending rate is
above a floor (say 10 %) — log a "sweep unreliable" line instead (AN7 also:
refuse when the repository set is empty or smaller than the recorded set
from the last successful sweep). Tests for each failure class and the
aggregate.

AN2 (critical) — recovery within the memory's own project: the basename
index must carry the repository each path belongs to, and
`unique_suffix_match` must prefer a unique match inside the memory's
project (from `project_id.repo_set_for` or the memory's `project`) and only
fall back to the union when the memory has no project — and then label the
result `cross-repo` so `recover_anchors` never writes it without `--allow-
cross-repo`. Tests: project A's dead path with a same-suffix file in B →
not recovered; with a same-suffix file in A → recovered.

ANT1 + ANT2 (critical) — `audit-postgres-sync.py`: drive `audit_memories`,
`audit_sessions`, `audit_archive_parity`, and `main()` through a fake
connection whose cursor evaluates the SQL against seeded rows and records
every statement; assert the set differences in both directions, the
`{table}` choice, the `WHERE id = ANY(%s)` filter, `leaked_active`, the
schema guard, the exit codes, AND that no statement other than SELECT is
ever executed and no commit is issued (make the fake refuse any write —
the read-only intent becomes a property). AN9: compare content too — a
per-row fingerprint (content, is_active, verified) so divergent rows and
Postgres-only orphans count against `is_clean`; a duplicate id in the JSONL
is reported. AN4: `_read_postgres_active_map` must raise a typed exception
instead of `sys.exit(2)` so `build_report` can degrade to "PG sections
skipped: schema mismatch" — test that the report still prints.

ANT3 + ANT4 (critical) — `memory-health-report.py`: drive `build_report`,
`render_report`, and `main()` end to end against a synthetic corpus and the
fake connection; assert the documented exit codes, that a real quarantine
count, an archive leak, and a duplicate id each make the verdict FAIL, and
that the PG SQL selects the active view / `is_active IS TRUE` (mutation to
`memories` / `IS NOT NULL` fails). AN8: an unreadable or missing quarantine
file is reported as UNKNOWN and fails the verdict (not 0/PASS); give
`QUARANTINE_FILE` the same symlink fallback as its siblings. AN5: "anchored"
counts only records with at least one mechanically verifiable anchor; a
non-list `anchors` is one malformed record. AN6: records without a parseable
`created_at` stay in the back-set (treat as oldest). AN16: every section
filters `is_active` and says so; [A] labels the two populations. AN17: the
top-five surfaced ids are checked against the corpus. M-c: the surfaced-log
path is resolved at call time via `surfacing_log`'s shipped-path function
so the override is honoured (one line). AN14: a `statement_timeout` and a
read-only transaction on the report's connections; the schema check before
`pg_snapshot`'s queries.

ANT5 (critical) — `triage_anchors.broad_repo_set` resolves from `PA_DIR`
(`__file__`-derived) with the same discovery as `project_id.repo_set` — make
one the source of truth and have the other call it (cross-file note: they are
identical today); an empty set is an error, not `[]`; test that a worktree
copy finds the same repositories. ANT-Md: `build_basename_index` errors are
narrowed and logged. ANT-Me/Mf: `run_sweep` tested unstubbed against
throwaway repositories (full back-set, the repo set, the resolver), and
`--memories` honoured. AN10: memoise the resolvers in `drift-sweep` and
`memory-health-report` as the siblings do.

ANT-Mh: the `saw_any_valid_anchor` guard pinned. ANT-L1..L7 where cheap:
`verify_commit` with a repo set; `verified` case-folding and the "stale"
value handled explicitly (documented as valid); naive timestamps; growth
boundary; unparseable dates; narrow excepts; top-N; `triage_anchors.main`
never writes (tree snapshot test); memoisation key includes the type. AN12:
require at least 7 hex characters for a commit reference. AN18: the trend
appender reports its failure to stderr and exit code.

## Record, do not change

ANT-Mg (the conftest watch list — a sibling owns conftest; say what should
be added), AN15 (absolute and tilde anchors have no recovery path — propose
the rule), ANT-L6 (three line definitions — the sync's is being unified on
PR #123), the two-test flake in `tests/test_daily_sync_trigger.py` that
Lens B saw once (not yours; a separate agent is chasing it).

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table, NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "the next drift sweep may refuse and log 'unreliable' if a
repository is unmounted", "`/memory-health` now FAILs on an unreadable
quarantine file", "anchors that verified true through a glob will re-verify
false on the next sweep — N live records").
