# Archival cadence (write-path item 13 / P2)

**Created:** 2026-06-02 (workstream B, latest PA). **Status (updated
2026-06-04): VALIDATED + CRON-READY.** The first `--apply` ran Shawn-watched
on 2026-06-04 (158 records archived; invariance + PG-drift gates passed;
recall invariant held). It surfaced one gap — daily-sync leaves the archival
commit unpushed on a clean tree — now fixed: step 9 `git -C data push`es it
directly and re-verifies. Safe to add the monthly cron line below.

## Why

The item-13 retention sweep (2026-06-02) archived 7,673 records (~25 % of the
corpus) but was **one-shot**. The corpus re-bloats continuously: ~260 new
records/day, plus multi-machine sync reconciliation that re-surfaces
past-decay records. **Evidence:** a dry-run hours after the sweep already
found **46** fresh archival candidates (20 `progress`, 11 `context`, 8
`commitment`, 5 `blocker_real`, 1 `system_success`, 1 `waiting_for`). Without
a recurring sweep, the hot `memories.jsonl` grows without bound and the
item-13 win decays.

## What was built

`scripts/monthly-archive.py` — a single guarded command that wraps the
*proven, manual* item-13 procedure. **Safe by default:** with no `--apply` it
mutates nothing (reports the plan + a sanity verdict only).

### The apply sequence (each step a hard gate)

1. **preflight** — refuses to run unless invoked from the MAIN checkout
   (`~/personal-assistant`); the wrapped tool hard-codes the main-tree corpus,
   so a worktree run would mis-resolve lock/log paths and break mutual
   exclusion. (Verified: running from a worktree aborts with exit 2.)
2. **flush** — `daily-sync.sh` commits/pulls/pushes pending appends and clears
   the dirty-protected-files state the bulk guard blocks on.
3. **sync PG** — `sync-to-postgres.py` (item-22 self-heals the cursor on the
   shrink the apply will cause).
4. **dry-run + SANITY gate** — refuses to apply if the proposed count is
   negative, exceeds an absolute cap (10,000), or exceeds 25 % of the active
   corpus — so a corrupt `category_config` can never nuke the corpus.
5. **apply** — `archive-memories.py --apply` (rewrites JSONL, appends the
   monthly cold partition, sets PG `is_active=FALSE`, commits the data
   submodule).
6. **INVARIANCE gate** — independently re-derives, for **every record the
   apply actually archived** (extracted from the partition delta), whether it
   is strictly past its decay window at a single pinned `as_of`. This is a
   *different code path* from the tool, immune to the live-`NOW()` drift that
   the first review caught, and it inspects the real archived records (not
   aggregate counts). Any in-window, permanent-category (`gotcha`/`pattern`),
   no-decay, or unparseable record ⇒ recall regression ⇒ **HALT before push**.
7. **PG-drift gate** — confirms the archived ids now read `is_active=FALSE` in
   PG; if PG was unreachable during the apply they would not (the tool exits 0
   anyway) ⇒ HALT before push.
8. **re-sync PG**, then **push** (`daily-sync.sh`) with a verification that the
   data submodule actually landed (`@{u}..HEAD == 0`).

Halts are **safe and recoverable**: the archival is an atomic, fsync'd, local
commit in the `data` submodule — `git -C data revert` undoes it.

### Exit codes

`0` success · `1` lock busy · `2` preflight/prereq failed · `3` sanity gate ·
`4` invariance regression · `5` apply crashed · `6` PG drift · `7` uncaught
exception (verify state by hand).

### Tests + review

22 unit tests cover the pure helpers (sanity gate, the time-pinned invariance
gate including the strict boundary, permanent/no-decay/unparseable cases,
`Z`-stamped timestamps). The `--apply` orchestration was adversarially
reviewed **twice** (a CRITICAL + 3 HIGH found and fixed on the first pass; the
second pass confirmed no CRITICAL/HIGH remain, with all residuals failing in
the safe direction — see the 2026-06-02 continuity entry for the audit trail).

## First run (Shawn-watched) — do this before cron-enabling

```bash
cd ~/personal-assistant
venv/bin/python3 scripts/monthly-archive.py            # 1. preview (dry-run)
venv/bin/python3 scripts/monthly-archive.py --apply    # 2. the real sweep, watched
```

Watch the log (`data/logs/monthly-archive.log`): confirm the sanity verdict,
that the invariance + PG-drift gates pass, and that the push verifies. If
anything halts (exit 4/5/6/7), investigate before trusting the cadence.

## Cron (ready to enable — the watched run completed 2026-06-04)

Add to the user crontab (alongside the existing 5-min sync + weekly decay),
monthly at 04:00 on the 1st (clear of the Sun 03:00 decay):

```cron
0 4 1 * * cd /home/shawn/personal-assistant && venv/bin/python3 scripts/monthly-archive.py --apply >> data/logs/monthly-archive-cron.log 2>&1
```

A non-zero exit (4/5/6/7) leaves a loud line in the log + the cron stderr; the
archival, if committed, is local and revertable. Consider piping a non-zero
exit to a notification if you want to be paged on a halt.
