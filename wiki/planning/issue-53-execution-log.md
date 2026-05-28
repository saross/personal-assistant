# Issue #53 — overnight execution log

**Executed:** 2026-04-21 23:56 – 2026-04-22 00:30 (Australia/Sydney)
**Status:** Mitigation landed. Awaiting Shawn's morning review.

## What ran

1. **Investigation agent** — root-caused the incident. Finding: no
   reshape occurred; commit `5821591` was a 31-line pure append. The
   247/290 numbers were explained by a combined diff-stat view (you
   confirmed this in your parallel CC session).
2. **Planning agent** — produced three-tier mitigation plan
   (`planning/issue-53-append-race-plan.md`). Approved as-is.
3. **Implementation** — M2, then M1, then M3. ~5h planned, ~30min
   actual (writing was fast; audit added value).
4. **/audit** — caught three critical bugs pre-ship:
   - M3 shrink check compared working-tree counts (always equal post-
     resolver) instead of committed-tree counts. Silent dead code.
   - `git -c core.editor=true rebase --continue` is version-fragile;
     the editor can still open. Needed `GIT_EDITOR=true` in env.
   - `push_with_retry` dispatched ALL rebase conflicts to the JSONL
     resolver, including `data` submodule-pointer conflicts in the
     parent repo. Resolver has no rule for submodule pointers.
5. **All three fixed** before commit.
6. **Cross-machine test**: zbook dry-run clean → zbook live sync
   clean → amd-tower pull + live sync (resolver fired on stash-pop
   conflicts, pushed cleanly) → zbook pull-back no-op.
7. **Issue #53 updated**: comment with full correction + status;
   body prefaced with misdiagnosis note; original text retained
   below for provenance.

## What shipped

Commit `67deb14` on saross/personal-assistant:

```
scripts/_bulk_rewrite_guard.py      NEW (M2 core)
scripts/daily-sync.sh                MODIFIED (M1 retry+rebase, M3 shrink check)
scripts/sync-to-postgres.py          MODIFIED (M3 timestamp marker)
scripts/fetch-memories.py            MODIFIED (M3 staleness warning)
scripts/dedup-memories.py            MODIFIED (M2 wiring)
scripts/backfill-summaries.py        MODIFIED (M2 wiring, sync + batch-apply paths)
scripts/reprocess-sessions.py        MODIFIED (M2 wiring on cmd_apply)
scripts/tag-gardening.py             MODIFIED (M2 wiring on cmd_merge)
```

Plus `data/config/sync.json` (config file with defaults, synced into
pa-data via the 2026-04-22 00:20 daily-sync).

## Config (rollback switches)

All in `data/config/sync.json`. Flip to `false` to disable without
touching code:

```json
{
  "retry_on_push_reject": true,        // disables M1
  "require_clean_origin_for_bulk": true, // disables M2 enforcement
  "detect_jsonl_shrink": true,         // disables M3 shrink check
  "recall_staleness_warning": true     // disables M3 /recall warning
}
```

After flipping, no restart needed — scripts re-read config on each
invocation.

## What you should see this morning

1. `/standup` runs normally. The extraction hook has been appending
   throughout the overnight work — the freshness warning should NOT
   fire yet (sync-to-postgres cron ran at 00:25 and will run again at
   00:30 — timestamp and cursor are fresh).
2. If you want to see the warning format, wait ~25 minutes after a
   /remember without a postgres-sync run in between.
3. The next cron-triggered daily-sync runs at 07:30 local on each
   machine. Both should complete without fanfare.
4. `logs/daily-sync.log` has tonight's runs; new lines include the
   `(attempt 1/3)` suffix from M1's retry counter.

## Open questions you may want to reconsider

The plan's `Open questions for Shawn` section was resolved with my
best judgement (documented in the comment header of each script).
Worth revisiting if anything behaves unexpectedly:

1. **Retry count 3 × 5s backoff.** If both machines' crons fire at
   07:30 simultaneously, one will lose the race and retry. 15s of
   headroom is plenty today, but if amd-tower ever gains a second
   cron rhythm, might need jittered backoff.
2. **Shrink threshold**: *any* net-negative counts as suspicious.
   Rationale: duplicates-being-deleted is already legitimate via the
   `Rewrite-Class: bulk` trailer, so unsignalled deletions should
   never happen. If this produces noise, raise the threshold or
   require a larger delta.
3. **/recall warning thresholds**: 20 lines AND 15 min (both
   required). Resolved the "or" framing in the plan body to "and"
   per open-question 3. If recall warnings fire too rarely (silent
   losses not caught), loosen to "or".
4. **Bulk-rewrite scripts' prints**: each bulk rewriter prints a
   reminder to commit with the trailer. If you forget, the shrink
   check catches it — so this is belt-and-braces rather than
   load-bearing.

## Next steps if all looks good

1. Close issue #53.
2. Optional: backlog entry for "post-session memory observability" —
   you noted the extraction hook appending 200 lines without
   visibility was itself a problem, separate from the race. Worth
   capturing as its own item (not in scope tonight).
3. NH items from the plan stay deferred unless their triggers fire.

## Files touched this session (for context)

- `planning/issue-53-append-race-plan.md` — original plan
- `planning/issue-53-execution-log.md` — this file
- All commit SHAs in `saross/personal-assistant` from `67deb14`
  backwards to `fbb61eb`
- `saross/pa-data` from `6e8d5c5` backwards

Good morning. Brian handover day — the Paper A window is protected.
