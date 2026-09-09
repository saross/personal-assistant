# Round 4c-5 report (session archive pipeline, follow-ups after PR #141)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4c-5 complete. Tree clean, scratch deleted (104,595 inodes freed).

## Disposition

| ID | Disposition |
|---|---|
| **M1** | fixed — the fixture HOME is now `immutable-home` deliberately, so `CANON` (derived from `$HOME`) carries the word and every log line about the transfer contains it. The test asserts the word actually reaches the output before asserting the classification. **Deviation, see below** |
| **L1** | fixed — the match is narrowed to rclone's ERROR/NOTICE lines carrying its own refusal wording. Two sandbox tests: an `INFO : projects/-home-shawn-immutable-notes/… Copied (new)` line with exit 7 must give **2**; both of rclone's refusal phrasings must give **3** |
| **L2** | fixed — `sweep_stale_temporaries` returns `(swept, errors)`; `n_err` is seeded from it, so an unremovable temporary reaches the summary *and* the exit status. Both existing tests now assert the return code; a directory stays a skip (`errors=0`, exit 0), not an error |
| **L3** | fixed — `lstat` throughout: a symlink is judged by its **own** age and removed as a link, never followed. A dangling link is swept and reported distinctly (it was previously invisible for ever); a link to a directory is removed without touching the target. Four tests |
| **L4** | fixed — **decision: once per run**, with the count and the first three ids. A legacy manifest is sizeless throughout, so per-session warnings would bury the run's output while saying one thing; the repair (`discover`) is per manifest, not per session |
| **L5** | **decision: leave as-is**, documented as deliberate. rclone writes refusals to the `--log-file` we give it. If a future rclone reported one only on stderr the run exits 2 — the safe direction, because `--immutable` refuses again on retry rather than overwriting, so the cost is a wasted run. Teeing stderr in would put text we do not control into the append-only file the *next* run classifies against |

## Corrections to my round 4c-4 report

Two claims were wrong, and the auditor is right on both:

1. I wrote that the misclassification was "found because a test whose name contains the word created exactly such a path" and presented `test_a_canonical_path_containing_the_word_does_not_misclassify` as pinning the filter. **It pinned nothing.** Its fixture round-tripped a rename (`canonical.rename(marked); marked.rename(canonical)`), so the leaf never carried the word; `CANON` derives from `$HOME`, not from the test name; and pytest truncates tmp basenames to 30 characters. The protection was covered only by the accident that two *older* tests' truncated basenames happened to contain "immutable". I verified this by deleting the filter — all 29 tests passed.

2. **Deviation from M1's literal instruction.** M1 asked me to make deleting the `grep -v` fail the test. After L1's ERROR-level narrowing that is impossible: this script's own log lines are `[ts] r2-push: …` and can never match `^(ERROR|NOTICE)`, so the filter became unreachable — I confirmed deleting it still left everything green. Rather than keep a guard no test can fail (the dead-guard defect I removed in round 4c-3 L-1, and the exact shape that produced this confusion), I **removed the filter** and pinned the narrowing that now does the work. Relaxing the match back to `grep -qi immutable` fails **seven** tests, including the deliberate-HOME one; reading the whole log instead of this run's slice fails the stale-latch test. Both remaining discriminators are independently load-bearing.

## rclone wording, verified not recalled

The refusal strings were checked against the installed binary rather than from memory:

```
$ rclone version → v1.74.2
$ strings $(command -v rclone) | grep -i immutable
  "immutable file modified"                        PRESENT
  "Timestamp mismatch between immutable objects!"  PRESENT
  "Source and destination exist but do not match"  PRESENT
  "immutable file removed" / "…renamed"            absent
```

Both present phrasings are matched and both are covered by a test. A future rclone adding a third fails **safe** — exit 2, "safe to retry" — so the error is a wasted retry, never a corruption signal silently reported as an abort. That reasoning is in the code comment with the verification command.

## Suite

Clean `git archive` copy of HEAD, HOME pinned, `--basetemp` isolated, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

```
4308 passed, 3 skipped, 19 deselected, 34 subtests passed in 163.59s (0:02:43)
```

**exit code 0.** The three skips are environmental, none of them mine: `test_codex_main_tripwire.py:117` ("no checkout to calibrate against" — an archive export has no `.git`) and two `test_style_phase5.py` cases needing numpy, which the venv does not carry. The skip and deselect counts rose since last round because main has moved under me.

The store half of the hermeticity guard is still inert in an archive copy (no `data/` submodule); the banner says so on every run. Only the source-tree half is strict there.

## `git log --oneline main..HEAD`

```
2a5c81e fix(archive): summarise sizeless manifest entries once per run
3fa6b85 fix(normalise): count sweep failures, and handle *.tmp symlinks
f78bacb fix(r2): classify on rclone's refusal wording, not the bare word
```

Three commits — M1+L1 (one classifier change and the test that pins it), L2+L3 (one sweep function), L4+L5. Not pushed.

## Live-behaviour risks

1. **Transport failures that were reported as corruption aborts will now exit 2.** Any store path containing "immutable" — a project slug, a mount point — previously turned every failed push into exit 3 with "investigate before re-running". Those runs now correctly report "safe to retry". If someone has been ignoring exit 3 from this script, the signal is meaningful again.
2. **A genuine refusal is now recognised only by rclone's own wording.** If the deployed rclone differs from v1.74.2 and phrases it differently, a real refusal reports exit 2 and the push retries — it does not overwrite (`--immutable` refuses again), but the corruption signal would be delayed. Worth re-running the `strings` check after an rclone upgrade; the command is in the comment.
3. **`normalise --apply` now exits non-zero when a temporary cannot be removed.** A read-only mount or a permissions problem that previously reported `errors=0` and exit 0 will now fail the run. That is the point, but a wrapper treating this script's exit code as advisory will start seeing failures.
4. **`*.tmp` symlinks in the archive will be deleted** on the next `--apply` — including dangling ones that have been invisible until now. Only the link is removed, never its target. Run `--dry-run` first if any such links are load-bearing; they are reported distinctly in the output.
5. **The sizeless-manifest warning changes shape**: one summary line per run instead of one per session. A log scraper matching the old per-session text (`"manifest entry records no size"`) will stop matching; the new wording is `"N manifest entries recorded no size"`.
