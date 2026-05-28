# Issue #53 — JSONL append-race: overnight investigation + plan

**Prepared:** 2026-04-21 late evening, for Shawn's 2026-04-22 AM review.
**Pattern:** two agents run serially — investigation then planning.

---

## TL;DR for the morning

1. **The 247/290 line-drop reshape did not happen.** Commit `5821591` was
   a clean 31-line append. `git show --numstat 5821591` shows 31 additions,
   zero deletions in `memories.jsonl`. The resolver was not invoked (no
   "stash pop raised conflicts" in `logs/daily-sync.log` for the 07:30
   run). The failure mode was a mundane non-fast-forward push rejection:
   HUMN8031 session's local base was `03a28ce`, origin had advanced to
   `5821591` via zbook's 07:30 cron, and git correctly refused.
   A `git pull --rebase` would have produced a clean rebase without
   conflict markers.
2. **The race class is still real.** A real mid-file rewrite (e.g. next
   invocation of `dedup-memories.py` or a reprocessing pass) racing with
   an append *would* produce conflict markers in the middle of JSONL,
   and the current whole-file resolver would collapse the entire file
   in a way that's correct today but fragile for tomorrow.
3. **Shawn's `/recall` silent-miss concern is load-bearing.** If any
   append is lost before `sync-to-postgres.py` runs (every 5 min),
   postgres never sees it; `/recall` returns stale. Worth a
   freshness marker.
4. **Planning agent recommends 3 mandatory items, all <2h each, total
   ≤6h.** Minimises technical debt per Shawn's brief.
5. **Issue #53** should be comment-and-edit, not close-and-replace. The
   hypothesis is correct; only the trigger narrative is misidentified.

**Open question for Shawn:** where did the 247/290 numbers come from?
Possibly a `git diff --stat` computed against a stale base (e.g.
pre-yesterday's manual-merge state), which would show the accumulated
diff over several commits as if it were one reshape. Worth one
round-trip before design work starts — if the numbers were real against
a different base, the investigation's finding needs revisiting.

---

## Investigation agent — key findings

### What the reshape was

There was no reshape. `git show --numstat 5821591`:

```
31  0  memories/memories.jsonl
32  0  memories/tag-vocabulary.txt
 4  0  reports/time-log.csv
21  0  reports/work-log.md
93  0  standups/2026-04-20.md
```

Pre-commit `memories.jsonl` blob: 18,845 lines. Post-commit: 18,876
lines. The raw diff is anchored at line 18844 — 31 new extraction-hook
memories with `created_at` spanning 2026-04-20T02:11:32 to
13:19:00 UTC, plus 32 new tag-vocabulary lines. Zero deletions, zero
reordering, zero id rewriting.

The largest single-commit JSONL delta in origin/main across 2026-04-17
through 2026-04-21 is 39 insertions (`bb29e9a`, 2026-04-20 morning).
Nothing in the window matches a 247-line drop.

### Timeline (Australia/Sydney)

| Time | Machine | Event |
|------|---------|-------|
| 2026-04-20 12:07:55 | zbook | daily-sync runs; pushes `6cb687d` |
| 2026-04-20 12:09:37 | zbook | second daily-sync run; ff to `b54c94c` |
| 2026-04-20 12:14:37 | zbook | manual commit `03a28ce` |
| 2026-04-21 07:30:03 | zbook | cron fires; stash/pull/pop clean; commits `5821591`; pushes at 07:30:07 |
| 2026-04-21 ~15:30 UTC | amd-tower (HUMN8031 session) | /remember session begins; local base = `03a28ce`; origin already at `5821591` |
| 2026-04-21 18:52:18 local | amd-tower | After extract-reset-reapply, commits `3d6c310` (memories) then `e6d1e89` (grimoire) |
| 2026-04-21 19:06:43 local | amd-tower | Commits `efde4bc` (backlog entry for #53) |

You confirmed the machine ("That's from the ANU HUMN8031 session") —
matches the `project: -home-shawn-Code-ANU-HUMN8031-2026` tag on the
/remember JSON.

### Canonical state is clean

Origin/main at `3d6c310` has both /remember entries appended at lines
18875–18876 (ids `2026-04-21-b69748e73340`,
`2026-04-21-d094c17f851b`). tag-vocabulary has both new lines. Grimoire
in `e6d1e89`. No corruption, no silent loss from the recovery.

**Uncertain:** whether amd-tower's extraction hook fired between its
last pull and the `git reset --hard origin/main`. If yes, those
captures were destroyed by the reset. Resolving needs a grep of
amd-tower's `~/personal-assistant/logs/extraction.log` for entries in
that window. Recommend checking in the morning.

### Resolver assessment

The resolver did not run today — nothing to misbehave on. But a static
review surfaced one latent property worth flagging:

- `resolve-merge-conflicts.py` operates on the whole file, not just the
  conflict region. If the file contains *pre-existing* duplicates
  anywhere (not from the conflict), it collapses them too. Today this
  is fine because ids are globally unique by construction. It would be
  fragile if bulk rewrites started producing in-place line rewrites.

### Latent risks (investigation)

1. Real mid-file reshape would produce real conflicts. No rewriter on
   cron today, but `dedup-memories.py` exists and could fire manually
   at any time.
2. Extraction-hook appends during the `stash → pull → pop` window
   (small but non-zero).
3. Two cron runs within seconds on different machines if timezones
   align. Today both cron at 07:30 Australia/Sydney — the risk is
   mitigated only by clock drift.
4. Sessions that lose their push race and recover via `git reset
   --hard` can destroy local extraction-hook appends.

---

## Planning agent — recommended changes

### Mandatory (3 items, ≤2h each)

**M1. Make `daily-sync.sh` resilient to non-fast-forward push.**
The exact failure mode from 2026-04-21. Wrap `git push` at line 156
in a bounded retry (3 attempts, 5s backoff). On rejection: `git fetch
origin main`, `git pull --rebase origin main` (append-only rebases
cleanly; if rebase conflicts, invoke the resolver and `git rebase
--continue`), then re-push. Hard-fail on final attempt.

**M2. Gate bulk rewriters behind a pre-flight check.**
Shared helper (`scripts/_bulk_rewrite_guard.py`) imported by
`dedup-memories.py`, `reprocess-sessions.py`, `backfill-*.py`. Before
any in-place rewrite of `memories.jsonl`:
1. `git fetch origin main`
2. Abort unless `HEAD == origin/main` AND working tree clean on
   `memories.jsonl`
3. Acquire the same flock file daily-sync uses
4. Emit a commit with `Rewrite-Class: bulk` trailer so observability
   (M3) can distinguish legitimate net-deletion commits from
   accidents.

**M3. Post-sync invariant check + /recall freshness marker.**
Two small additions:
- `daily-sync.sh`: capture `wc -l memories.jsonl` before/after the
  resolver + commit block. If net delta is negative AND the HEAD
  commit message lacks the `Rewrite-Class: bulk` trailer, write
  `data/logs/daily-sync-SHRINK-$DATE.txt` and exit 4. Converts
  "silent reshape" from invisible to loud.
- `sync-to-postgres.py`: write `postgres_last_jsonl_line` and
  `postgres_last_sync_ts` to `data/memories/sync-cursors.json`.
- `/recall` (`scripts/fetch-memories.py`): compare cursor to current
  line count. If >20 unsynced lines OR >15 min stale, prepend a
  one-line warning.

### Execution order

1. **M2 first** — gates the highest-severity future failure
   (rewrite×append). Independent of M1/M3.
2. **M1 second** — addresses the concrete incident.
3. **M3 last** — depends on M2's trailer convention and on M1's
   stable rebase behaviour.

No item takes >2h. Total ≤6h.

### Nice-to-have (deferred behind triggers)

- **NH1** Pre-push hook mirror of M1 retry logic. Trigger: first
  manual push rejection post-M1.
- **NH2** Per-machine journal files (`memories.d/<host>-<date>.jsonl`)
  with periodic consolidator. Trigger: second race incident within 6
  months, OR Cowork adoption.
- **NH3** Scope resolver to conflict hunks only. Trigger: whole-file
  dedup mis-behaves, OR second file added to resolver where it's
  unsafe.
- **NH4** Migrate writes to `memory_mcp.py` write tools. Already on
  backlog, triggered by Cowork.

### Rejected

- Pre-append `git fetch` on every hook — too much overhead for an
  annual race.
- Postgres-as-source-of-truth — violates "JSONL canonical" constraint.
- Tombstone / line-hash self-rebasing appends — over-engineered.
- Maintenance-window handshake — no always-on broker.
- Per-machine journals *now* — premature for current race frequency.

### Rollback posture

Each mandatory item guarded by one config value:

- M1: `retry_on_push_reject: true|false`
- M2: `require_clean_origin_for_bulk: true|false`
- M3: `detect_jsonl_shrink: true|false` and `recall_staleness_warning:
  true|false` independently

All flippable without code changes.

### Open questions for Shawn

1. **M1 retry count.** 3 attempts × 5s, or 5 with jittered backoff?
   (Recommended: 3 × 5s.)
2. **M2 flock scope.** Reuse `logs/daily-sync.lock`, or separate
   `bulk-rewrite.lock`? (Recommended: reuse — bulk rewrite and
   scheduled sync must not overlap.)
3. **M3 shrink threshold.** Is any negative delta suspicious, or
   only below a size (e.g. >5 lines)? (Recommended: any net negative
   without trailer — silent shrinks should be rare.)
4. **M3 recall threshold.** 20 lines / 15 min — tighter? (Recommended
   as stated — cron is every 5 min; >15 min means ≥2 failures.)
5. **Guard helper as Python module vs sourced bash preamble?**
   (Recommended: Python — all bulk rewriters are already Python.)
6. **Extraction hook: keep non-fetching append, or gain post-append
   push?** (Recommended: keep as-is. M1 + daily-sync guarantees no
   append is lost, only delayed to next sync.)

### Recommendation on issue #53 and backlog

**Comment-and-edit, not close-and-replace.**

- Post a comment on #53 summarising the investigation
  ("2026-04-21 was a non-fast-forward push, not a reshape; race
  class described remains real but has not yet fired").
- Edit the issue body's "Pattern observed" section to label the
  2026-04-21 narrative as a misdiagnosis (keeping text for
  provenance).
- Append a "Mitigation plan" section linking to this file once
  approved.
- Backlog entry for "Deduplicate memories.jsonl and rebuild
  postgres/embeddings" should note that M2 is a prerequisite for
  any future bulk-rewrite invocation.
- Close #53 only after M1/M2/M3 land.

---

## What I'd do next pending your review

1. Answer the open questions above.
2. Reconcile the 247/290 numbers if that reveals something the
   investigation missed.
3. Check amd-tower's extraction.log for captures between the last
   pull and the `git reset --hard` — to rule out silent extraction
   loss during recovery.
4. Execute M2 → M1 → M3 in order.
5. Update issue #53 with the comment + edited pattern section.
6. Close out after all three items land.

Estimated total work if approved as-is: ≤6h implementation + /audit
review + cross-machine testing. Achievable in one focused day, fitting
around the Thursday Paper A handover and the Inscriptions Day 1 on
Wednesday afternoon.
