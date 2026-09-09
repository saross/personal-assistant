# Round 3c-8 report (daily sync, follow-ups after PR #139)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

All items done; tree clean, nothing pushed, workspace removed.

## Dispositions

| ID | Disposition |
|---|---|
| **M1** | **fixed (test + comment).** `test_a_trailer_that_started_high_but_ended_high_excuses_nothing` — origin 5, trailered 5→4, the corpus retired, an unmeasurable merge holding 2. **My first fixture did not kill the mutant**: I built the merge off to one side, which takes the trailered commit out of the range the guard scans, so the mutation survived for a reason unrelated to the rule. Rebuilt as the linear chain the finding describes; **both** conditions are now confirmed load-bearing by mutating each in turn. L6/L7 recorded beside the rule with their reasoning |
| **M2** | **fixed.** The opener is matched before any redirection, in all four spellings, with `<<<` excluded. **Instrumented**: a scratch copy with a real `\| grep -q` planted inside the Python must not trip the lint — and restoring the end anchor makes it trip, which is the proof the skip is reached. Docstring corrected: it claimed heredoc bodies "are skipped entirely"; they were not |
| **L2** | **fixed.** An opener is honoured only in command position. The fixture plants a `<<NOTES` comment *and* a genuine offence after it, and requires the offence to still be found |
| **L1** | **fixed.** Pattern widened to `\b(z\|e\|f)?grep(\s+--?[A-Za-z-]+)*\s+(-[A-Za-z]*q\|--quiet\|--silent)`, held to eight planted spellings. The docstring no longer claims "every spelling" — that is not something a regex can promise; it names the set the tests hold it to |
| **L3** | **fixed.** The vacuity guard asserts the **count per function** (`render_sync_gate`: 1, `previously_recorded_stashes`: 2, `has_bulk_rewrite_trailer`: 1). Confirmed by deleting one of the two greps inside `previously_recorded_stashes` |
| **L4** | **fixed.** Three fixtures for the rename branch, including a newline in the **original** path; both the raw-source and raw-query mutations confirmed caught |
| **L5** | **partly fixed.** Two of the three `render_sync_gate` tests assert the **exact** rendered list; `tail -n +2`→`cat` now fails. **`grep -qxF`→`-qF` is equivalent under the present key vocabulary** — every key is either the literal `unattributed` or a fixed-width `stash:<sha8>`, and none is a substring of another, so no fixture can provoke it. `-x` is defence against a future key that is a prefix of one; recorded in the commit rather than given a fabricated test |
| **L6, L7** | **noted in the script**, beside the span rule, with the reasoning: a trailered commit that empties the corpus spans every drop there could be and so dismisses any merge beside it (that is what declaring a bulk rewrite to nothing means), while two consecutive partial rewrites that together cover the drop do not, because neither spans it alone — the conservative direction and the only one that stays checkable |

Sixteen mutations verified across the round; two survive deliberately and are documented (the `-qxF` anchoring above, and last round's `--no-renames`-on-the-diff).

## Two process notes

- I committed L5's edits inside the L4 commit by staging the file whole, and the message described only L4. I amended it to say what is actually there. That is the third time this series a commit or check has mis-stated its own contents — worth a standing habit of `git show --stat` before writing the message.
- The strict-hermeticity banner is more explicit this round and confirms what I flagged last time: in a `git archive` copy the **store half of the guard is inert**, so these measured numbers exercise only the source-tree half.

## Measured suite

Clean `git archive` of `b222df1`, `HOME` pinned with a `.gitconfig` (identity, `init.defaultBranch=main`, `protocol.file.allow=always`), `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`, `--basetemp` isolated:

```
4324 passed, 3 skipped, 19 deselected, 34 subtests passed in 191.94s
EXIT=0
```

19 deselected from `pytest.ini`'s `-m "not integration"` (up from 3 — main has grown integration-marked tests since round 3c-7).

```
$ git log --oneline main..HEAD
b222df1 test(daily-sync): pin the rename encoding and the rendered gate
0263cf8 test(daily-sync): widen the quiet-grep pattern, count per site
d986afc test(daily-sync): make the lint's heredoc skip actually work
8d2d208 test(daily-sync): pin both ends of the span rule
```

Merge-base `d07c174` — four clean commits.

## Live-behaviour risks

**None.** Every change this round is in `tests/`, apart from a comment block in `scripts/daily-sync.sh` recording the L6/L7 reasoning. No runtime path changed, so the next cron tick behaves exactly as the merged PR #139 does.

The residual risk is the one the round did not touch: `wiki/audits/2026-09-08-first-audit.md` still carries no rows for any finding from rounds 3c-1 through 3c-8. Eight rounds of durable record now live only in commit messages and these reports.
