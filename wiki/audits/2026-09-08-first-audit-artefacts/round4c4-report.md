# Round 4c-4 report (session archive pipeline, PR #141)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4c-4 complete. Tree clean, scratch deleted (101,689 inodes freed; `/tmp` at 24%).

## Disposition

| ID | Disposition |
|---|---|
| **1** | fixed — `STALE_TEMP_MIN_AGE_SECONDS` pinned as a literal (`test_the_staleness_threshold_is_the_documented_one`) and the "fresh" fixture aged 60 s, so it is old enough that a shrunken threshold sweeps it and recent enough that the real one must not. `→ 1` now fails both that and `test_a_recent_temporary_is_left_alone` |
| **2** | fixed — directories are skipped and reported separately (stderr), and a path is appended to `swept` **only after** the unlink succeeds. Two tests: `test_a_directory_named_tmp_is_not_counted_as_swept` asserts the directory survives and the summary says `stale-temp=0`; `test_an_unremovable_temporary_is_not_counted_as_swept` covers the same ordering bug for a file that cannot be removed |
| **3** | fixed — `refuse_incomplete_source` warns loudly when `expected_size is None`, naming the cause (the entry predates size recording) and the repair (re-run `discover`). Still archives — a missing size is a degraded guard, not a refusal. `test_a_sizeless_manifest_entry_warns` + a quiet control |
| **4** | fixed — `--retry-failed`'s help now states the unbounded policy and why. `test_the_retry_help_states_the_unbounded_policy` renders the **real parser** rather than reading the source |
| **5** | fixed — status captured inside the branch (`rc=0; rclone … \|\| rc=$?`). `test_the_logged_status_is_rclone_s_own` asserts `rc=7` appears and `rc=0` does not |
| **6** | fixed — both branches now go through one `classify_failure_and_exit`. Three tests: a failing dry run exits 2 with "safe to retry" (not rclone's raw code); a dry-run immutable refusal exits 3; a successful dry run still exits 0 |
| **7** | fixed — two helpers replace the over-wide splits: `_function_body` (bounded by the next top-level definition) and `_comment_block_above`. Both escapes now fail: a marker planted in a function *below* `cmd_archive`, and the no-cap sentence moved to a comment far above the constant. Neither was caught before |
| **8** | fixed — the `*.tmp` exclusion is parametrised over both branches, like the copy/`--delete` assertions |

## One additional fix, found while testing item 6

`test_a_fresh_immutable_abort_is_still_classified` failed for a reason worth keeping: the pytest tmp directory is named after the test, so the canonical path contained the string "immutable" — and the classification greps the log slice, which includes **this script's own log lines**, and those embed the canonical and destination paths. Any store whose path contains that word would have made every transport failure report a corruption abort in production. The classifier now drops lines carrying the `r2-push:` prefix before matching, so only rclone's own output decides. `test_a_canonical_path_containing_the_word_does_not_misclassify` pins it; removing the filter fails both latch tests. An accident of test naming reproduced a real shape.

## Suite

Clean `git archive` copy of HEAD, HOME pinned, `--basetemp` isolated, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

```
3892 passed, 1 skipped, 3 deselected, 34 subtests passed in 155.75s (0:02:35)
```

**exit code 0.** The skip is `tests/test_codex_main_tripwire.py:117 — "no checkout to calibrate against"`, which needs a real `.git` that an archive extraction has not.

Same caveat as last round: with no `data/` submodule the canonical-store paths dangle, so the **store half of the hermeticity guard is inert** in both the clean copy and this worktree; only the source-tree half is strict. The banner says so on every run. Exercising the store half needs the live checkout.

## `git log --oneline main..HEAD`

```
1d2209f test(archive): narrow two source-search windows to what they claim
6a65ae3 fix(r2): report rclone's real status, and classify the dry run too
11383c5 fix(archive): announce a manifest entry with no recorded size
9eaa2f3 fix(normalise): count a temporary as swept only once it is gone
```

Four commits — items grouped by file and by the single behaviour each changes (1+2 the sweep, 3+4 the archive guard's reporting, 5+6+8 the R2 exit path, 7 the test windows). Not pushed.

## Live-behaviour risks

1. **The R2 push's exit codes change for previously-mishandled cases.** A failing `--dry-run` now exits 2 or 3 instead of rclone's raw status — in particular rclone's exit 1 no longer masquerades as this script's "precondition not met, skipped" (exit 1). Anything wrapping the dry run and treating 1 as benign will now see a real failure. That is the point, but it is a visible change.
2. **The logged `rc=` is now rclone's own** rather than always `0`. Log-scraping that matched `rc=0` will stop matching.
3. **A store path containing "immutable" no longer misclassifies** — if the canonical mount is ever moved under such a path, behaviour is now correct where it silently was not.
4. **`archive` will emit a new warning per sizeless manifest entry.** If the current `logs/bulk-archive-manifest.json` predates size recording, the next run logs one line per session and archives them exactly as before. Re-running `discover` clears the warnings and restores the shrink/growth checks.
5. **The `*.tmp` sweep counts differently.** Previously a directory or an unremovable file inflated `stale-temp` while `errors=0`; the count now reflects only files actually deleted, so the number may drop on a store where such paths exist — and a directory named `*.tmp` will now be reported on stderr each run until removed by hand.
6. **`--retry-failed`'s help text is longer**; no behaviour change.
