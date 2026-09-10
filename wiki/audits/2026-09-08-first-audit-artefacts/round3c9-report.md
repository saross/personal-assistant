# Round 3c-9 report (daily sync, follow-ups after PR #148)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

All items done; tree clean, nothing pushed, workspace removed.

## Dispositions

| ID | Disposition |
|---|---|
| **M1** | **fixed.** `_split_shell_line` replaces the heuristic: one walk per line tracking quote state, returning the code with any unquoted trailing comment removed plus a mask of which characters sit inside quotes. The opener must **start** outside quotes while the delimiter it names may be quoted — the shape this script's own heredoc uses. Three fixtures (trailing comment, double-quoted, single-quoted), each followed by a genuine offence |
| **M2** | **fixed.** All three fixtures plant **indented**, as every comment in this script is. Confirmed: dropping the leading-space trim now fails |
| **L-a** | **fixed.** `_quiet_grep_offenders` judges **every** quiet grep on a statement, each by whether *it* is downstream of a pipe; `||` is excluded. Both named shapes tested, plus a blameless-leading-grep case so the scan cannot become "report everything" |
| **L-b** | **fixed.** The terminator comparison keeps `.strip()`, pinned by an indented `<<-` fixture; the `(?<!<)` here-string guard is pinned by a planted bare-word here-string (inert against this script, which quotes every one) |
| **L-c** | **fixed (4 tests).** A `Rewrite-Class: bulk-extra`/`bulkish`/`bulk rewrite of…` trailer must not pass; a copy record must keep the `-z` field stream aligned; the **first** shortening commit is the one named; the **first** unmeasurable merge is the one named |

**Ten mutations verified this round**, all killed: five in the tokeniser/scan and four in the script, plus the here-string lookbehind.

## Two fixture traps I walked into

Both were caught by existing tests rather than by me reading carefully, which is the useful part:

1. My first tokeniser **blanked quoted spans wholesale** — which also blanked `<<'PYEOF'`'s own quoted delimiter, so the heredoc skip silently stopped working. The instrumented test from round 3c-8 failed immediately. Masking positions instead of blanking spans is the fix.
2. The first-unmeasurable-merge fixture **passed for the wrong reason**: its corpus-retiring trailered commit spans every drop by the stated rule (that is L6, deliberate), so both merges were dismissed and the run was *allowed*. Rebuilt with two trailered rewrites, neither of which spans.

## Measured suite

Clean `git archive` of `ef8e29f`, `HOME` pinned with a `.gitconfig` (identity, `init.defaultBranch=main`, `protocol.file.allow=always`), `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`, `--basetemp` isolated:

```
4445 passed, 3 skipped, 19 deselected, 34 subtests passed in 165.63s
EXIT=0
```

19 deselected from `pytest.ini`'s `-m "not integration"`. As in the last two rounds, the strict flag's **store half is inert** in an archive copy — only the source-tree half is exercised.

```
$ git log --oneline main..HEAD
ef8e29f test(daily-sync): pin four guards the series left unpinned
4a9793c test(daily-sync): tokenise shell lines properly for the lint
```

Merge-base `33afc07` — two clean commits.

## Live-behaviour risks

**None.** Every change this round is in `tests/`. `scripts/daily-sync.sh` is byte-identical to the merged PR #148, so the next cron tick behaves exactly as it does today.

What the round *did* establish is that four of that script's guards had no test behind them — the bulk trailer's end anchor, the copy-record field consumption, and both "which commit gets named" orderings. They are correct in the shipped code and now stay correct.

The standing residual is unchanged: `wiki/audits/2026-09-08-first-audit.md` still carries no rows for any finding from rounds 3c-1 through 3c-9. Nine rounds of durable record live only in commit messages and these reports.
