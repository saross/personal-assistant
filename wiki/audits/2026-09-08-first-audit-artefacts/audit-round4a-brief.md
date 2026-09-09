# Audit round 4a — memory-store writers — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4a`, branch
  `claude/audit-round4a`, at commit 8b13b05 (main). Suite at the branch point:
  2,372 passed, 3 deselected. Sibling agents run in other worktrees.
- Lens reports: `lensA-4a.md` (correctness) and `lensB-4a.md` (test adequacy)
  in this directory. Line numbers were taken at 505ca8c; verify before editing.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit
  it (the coordinator records dispositions from your final report).
- Scope: `scripts/dedup-memories.py`, `scripts/tag-gardening.py`,
  `scripts/recover_anchors.py`, `scripts/sync_memory_edit.py`,
  `scripts/archive-memories.py`, `scripts/apply-decay.py`,
  `scripts/monthly-archive.py`, `scripts/_timestamps.py`,
  `scripts/_schema_version.py`, their tests, and `tests/conftest.py` (the
  hermeticity guard only). You may add a small helper to
  `scripts/_sync_cursor.py` for A9. Do NOT touch `scripts/daily-sync.sh`,
  `scripts/daily-sync-trigger.sh`, their tests, `scripts/_bulk_rewrite_guard.py`
  internals, or the retrieval scripts (`fetch-memories`, `memory_mcp`,
  `surfacing_stats`, `log-recall`, `log-confab-flag`, `project_id`,
  `search-sessions`, `digest-preview`, `resolve_session_id`) — other agents own
  them right now.

## Must fix (Critical and Medium from both lenses)

Order: the criticals first, one commit each, then the mediums grouped by file.

A1 (critical) — record splitting. Every rewriter must serialise exactly as the
extraction hook does (`json.dumps(rec)` with the default `ensure_ascii=True`) so
that U+2028/U+2029/U+0085 stay escaped; every reader must split on `"\n"` only,
never `str.splitlines()`. Fix `dedup-memories.py` (write :293, read :98) and
`tag-gardening.py` (:591, :647); grep the whole tranche (and the readers you
touch) for `splitlines(` on JSONL content. Test: a record whose content holds
U+2028 survives two consecutive runs byte-identical, and the line count agrees
between iteration and a `"\n"` split. Also make the invariant checks count
lines by `"\n"`.

A2 (critical) — `tag-gardening orphans --action clean` (:744) must use the same
protection as `merge`: `ensure_safe_to_rewrite`, `lock_jsonl_for_rewrite` on the
vocabulary, temp-file in the same directory + flush + fsync + `os.rename`. A4:
both vocabulary rewrites must preserve `#` comment lines and blank lines in
place (only tag lines change). Test: a vocabulary with two section headers and a
blank line comes back with them in the same positions; a concurrent shared-lock
holder blocks the rewrite (use the real lock helper in a subprocess).

A3 (critical) — `recover_anchors.py`: plan inside the lock. `main()` must take
`ensure_safe_to_rewrite` + `lock_jsonl_for_rewrite`, then read, plan, and write
under that lock, as `archive-memories.py:359-361` does; or re-read inside the
lock and abort any plan whose record's content/`is_active`/`revisions` changed
since planning. Test (from B2 as well): a record edited between plan and apply
is not reverted; the untouched records are written back byte-identical; the
whole-file rewrite keeps every unplanned line (the B2 mutation that deletes the
verbatim `else: out.write(line)` must fail); the guard, the lock, the atomic
rename, and the `--apply` gate each have a test that kills their deletion.

A5 — `tag-gardening` dry run must not take the exclusive daily-sync lock or
fail on a dirty tree (mirror `dedup-memories.py:355`).

A6 + A10 — `dedup-memories.py`: every removed duplicate must be written, flushed,
and fsynced to a durable file BEFORE the corpus rename (a dated
`memories/dedup-removed-YYYY-MM-DD.jsonl` or similar under the store's
directory, appended, never truncated), and the log must name the real file. The
re-id path must append an `old_id -> new_id` mapping line to the same file (or
a sidecar) so `surfaced.log`, `superseded_by`, and the Postgres row can be
reconciled later. A13: an unclassified duplicate group must not abort the run —
keep it verbatim, exclude it from the invariant, report it by id, exit non-zero
only if NOTHING could be resolved. B3: create `tests/test_dedup_memories.py`
pinning: which duplicate survives, the re-id salt, `--dry-run` writes nothing,
guard and lock wiring, the shrink abort, the atomic rename, the removed-record
file, the mapping line, and both invariant exits.

A7 — `recover_anchors.py` tolerates a malformed line at :233 and :328 (preserve
it verbatim like every sibling; never leave `memories.jsonl.tmp` behind on
abort — use try/finally).

A8 — `tag-gardening merge` must reach PostgreSQL: after the JSONL rewrite issue
a surgical `UPDATE memories SET tags = %s, research_tags = %s WHERE id = %s`
(check `schema.sql` for the real column names and types) for every touched id,
inside one transaction, via the same connection pattern as
`sync_memory_edit.py`; on any Postgres failure print the correct remedy (a full
rebuild, per `commands/tags.md:167`) and exit non-zero AFTER the JSONL is safe.
No live connection in tests: a fake connection/cursor that records executed SQL
and parameters, and a test that the WHERE clause is `id = %s` (B1's class).

A9 — refuse a line-deleting rewrite while Postgres has an unsynced backlog:
before `archive-memories.py --apply` and `dedup-memories.py` rewrite, compare
the memories cursor in `sync-cursors.json` (see `_sync_cursor.py` for the
reader) with the file's `"\n"` line count; if the cursor is behind, exit
non-zero with "run sync-to-postgres.py first" and write nothing.
`monthly-archive.py` already syncs first — verify its gate still passes. Test
both scripts: backlog → refused, nothing written; no backlog → proceeds.

A11 — `sync_memory_edit.py`: when `content` changes, the UPDATE also sets
`embedding = NULL` so the next cron tick re-embeds; A17: call
`assert_schema_version`. B1 + B14: the fake cursor must execute the real SQL
string — pin `WHERE id = %s` (a mutation to `!=` fails), the parameter order,
and that the transaction is committed (`with conn` — a mutation dropping it
fails: assert `conn.commit()` or the context manager was entered).

A12 — `tag-gardening` plan keys lower-cased on load (:541) so a loser with
uppercase actually replaces; B16/B17: tests with mixed-case tags and a record
carrying both `tags` and `research_tags`.

B4 (critical, tests) — extend the conftest hermeticity guard to snapshot and
compare `memories/memories.jsonl`, `memories/tag-vocabulary.txt`, and `logs/`
in the repo tree (resolve through the symlinks) alongside `~/.cache`; narrow
`_bypass_rewrite_guard` in `tests/test_tag_gardening.py` from autouse to the
tests that need it. Prove it: a throwaway test that rewrites the real path in a
copy must be REFUSED or flagged by the guard (delete the throwaway afterwards).

B5–B15 (tests) — kill every surviving mutation listed in `lensB-4a.md` for the
files in scope: malformed-line preservation in tag-gardening merge; guard,
flocks, atomic rename in tag-gardening and archive-memories; the `--apply`
gates; the `Rewrite-Class: bulk` trailer; `git add --literal-pathspecs --
<paths>` (a pre-existing unstaged modification must NOT land); the apply-decay
predicate (execute the SQL text through a small checker — at minimum assert
the exact operators `NOW() - interval`, `<`, and `AND m.is_active = TRUE` in
their clauses, or better run it against a sqlite shim with the interval
arithmetic replaced); the schema-version call; recover_anchors `verified`,
`revisions` append, the "already resolves" gate, `_is_relative_file_ref`,
`build_plans`; monthly-archive's caps and halts (pin the literal cap, the
post-apply re-check, and the partition halt); B18 (make the `Z` test meaningful
on Python 3.13 or delete its false rationale); B19 (fsync and the merge log).

## Load-bearing lows — fix

A15 (fsync in tag-gardening), A16 (UTC ISO stamp in the merge log), A20
(commit inside the guard lock in recover_anchors, as archive-memories S15),
A18 (add a `PERMANENT_OVERRIDES` net to apply-decay's SQL or a pre-check that
refuses to run when `category_config` says a permanent category decays).

## Record, do not change (decisions for Shawn)

A19 (partition month UTC vs local), A21 (`Path.home()`-pinned CORPUS), A14
(directory fsync), the cross-file `_timestamps` adoption, and the adjacent
extraction-hook `os.write` note. Mention each in your report.

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table (finding ID → fixed
with file:line and test name, or not fixed with reason), NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "the next `/tags` run will refuse until sync-to-postgres has run").
