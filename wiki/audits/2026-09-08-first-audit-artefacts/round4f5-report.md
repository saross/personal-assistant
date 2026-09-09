# Round 4f-5 report (memory readers and anchors, follow-ups after PR #140)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4f-5 complete. Six commits on `claude/audit-round4f-5`, working tree clean, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **M3** history-probe handlers | **fixed (test)** — `TestTheHistoryProbeHasItsOwnErrorClasses` drives probe 1 to a clean miss so probe 2 is the one that fails, across transient / permanent / timeout, with a two-clean-probes control. Kills `except OSError: return "false"` |
| **M4** commit-path `unknown_seen` | **fixed (test)** — `test_a_vanished_repository_mid_scan_withholds_the_verdict` excludes a repository *inside* the scan (healthy at start, raises on its probe); asserts one probe and `pending` |
| **M2** `unusable` reaches no surface | **fixed** — `drift_trend` returns `latest_unusable` + `degraded_in_window`; `[H]` names the latest run's exclusions, counts degraded runs in the window, and asterisks those points in the fail% series. `TestTheDriftSectionSurfacesExclusions` |
| **M1** lazy exclusion discovery | **fixed** — `anchor_verify.probe_repos` asks each repository once (`git rev-parse --git-dir`) through the same classifier; called by `run_sweep` and tier C. `test_the_exclusion_list_is_complete_however_anchors_resolve` uses the re-auditor's shape (6 repos, one emptied mount, 20 early-resolving anchors) |
| **M5** flaky mount = permanent refusal | **fixed, option (b)** — see below |
| **M6** one repository is a set | **fixed** — `MIN_DISCOVERED_REPOS = 3` applies when the log offers no count; the WARN names "the built-in minimum"; `--min-repos` still wins. Four tests incl. yield-to-recorded-count and override |
| **L7** refusal with no override | **fixed** — the `RepoSetUnavailable` message says it has no override and what to do instead; tested |
| **L8** unreachable label | **fixed** — removed (a floor of 0 can never be breached) |
| **L9** `repos` vs `unusable` sets | **fixed** — the row carries `consulted` (the walked set, augmentation included) beside discovery-only `repos`; `_render` shows "N of M" |
| **L10** real Zotero keys | **fixed** — 11 occurrences of two real keys replaced in `tests/test_sync_to_zotero.py`. `hooks/extraction-hook.py:236`, `commands/read.md:135`, `commands/remember.md:157,172` left alone and flagged: they are prose examples for a human, not fixtures |
| **L11** untested resets | **fixed** — one test each for the sweep's and tier C's registry reset |
| **L12** `sorted` → `list` | **fixed** — the assertion now feeds `trend_line` an unsorted list |

## M5: option (b), and why

A degraded run is **recorded and flagged**, not refused. When the pending rate exceeds `MAX_PENDING_PCT` *and* the run knows which repositories it could not consult, the row is written with `degraded: true`; `last_repo_count` skips it, the `[H]` fail% series marks it, and both renderers say so. The floor is untouched for an **unexplained** pending rate.

Option (a) — dropping unknown-blocked refs from the denominator — was rejected on two grounds. The resolver carries no per-ref attribution, so it would have to be invented; and a row whose `fail_pct` was computed over a silently smaller population reads as an *improvement*, which is the mirror image of the fabricated spike AN7 fought.

## Suite

Clean `git archive HEAD` copy in `mktemp -d`, `HOME` pinned inside it, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`:

`3970 passed, 1 skipped, 3 deselected, 34 subtests passed in 162.88s (0:02:42)` — exit code **0**.

Same caveat as last round, and the guard now prints it itself: an archive export has no `data/` submodule, so the store half of `PA_HERMETICITY_STRICT` is inert; only the source-tree half was enforced.

```text
97632e4 docs(drift-sweep): the floor has a second source now
b7e3188 test(zotero): replace two real item keys with synthetic ones
e815a4d fix(memory-health): show excluded repositories in [H]
f612220 fix(drift-sweep): record a known gap, and refuse a lone repository
0b59e01 fix(anchors): ask every repository once, before resolving anchors
fb46317 test(anchors): reach the history probe's own error handlers
```

## Live-behaviour risks

1. **The trend log gains three fields and a new row class.** `consulted`, `degraded`, and a populated `unusable` appear from the next sweep on. Anything parsing that log outside this repo must ignore unknown keys, and a `degraded: true` row is *not* comparable with a clean one — `last_repo_count` and `[H]` already skip it, but a human reading raw rows should too.
2. **A degraded sweep now exits 0 and writes a row** where it previously exited 2 and wrote nothing. Cron alerting keyed on the exit code will go quiet for exactly the condition it used to shout about; the signal moved to the WARN line, the row's flag, and `[H]`. That is the trade option (b) makes explicit.
3. **`MIN_DISCOVERED_REPOS = 3` can refuse a first run on a sparse machine** — a fresh clone with only the assistant checkout and its data submodule discovers 2 and will refuse until `--min-repos` says otherwise. Intended, but it is a new way for a first sweep to fail.
4. **`probe_repos` adds one `git rev-parse` per discovered repository per sweep** (~36 processes here, against thousands of anchor probes). Negligible in time; it does mean a repository that is merely *slow* is now touched at sweep start.
5. **Exclusions will start appearing in `/memory-health` `[H]`** for anyone whose `~/Code` has a stale or unmounted directory. That is the point, but the first report after merge may name repositories the operator had forgotten about.
6. Unchanged from earlier rounds: an excluded repository makes its own anchors pending rather than false; short commit refs read pending; `audit-postgres-sync` and `/memory-health` fail on a PostgreSQL-only row.
