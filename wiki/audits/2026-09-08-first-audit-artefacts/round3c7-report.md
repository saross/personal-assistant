# Round 3c-7 report (daily sync, PR #139)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

All five items done; tree clean, nothing pushed, workspace removed.

## Dispositions

| ID | Disposition |
|---|---|
| **1** (medium) | **fixed.** Every unmeasurable merge is now logged as it is met (recorded, not fatal). **Ordering chosen: the merge is checked FIRST, and only a trailered commit whose own transition spans the *whole* observed drop dismisses it** — its parent held at least what origin holds *and* it kept at most what HEAD keeps, so there is no room left for the merge to have taken anything. Anything short of that and the merge is named: "some of this shrink is accounted for" is not "all of it is". The alternative (any trailer anywhere excuses the merge) *is* the finding. Tests: `test_a_trailer_that_owns_only_part_of_the_shrink_does_not_excuse_it`, `test_a_trailer_that_owns_the_whole_shrink_still_publishes`, `test_every_unmeasurable_merge_is_recorded_even_when_allowed` |
| **2** (low) | **fixed.** The lint works on **statements**: continuation lines and lines ending in `\|` are joined, heredoc bodies skipped (the embedded Python is not shell), trailing inline comments dropped. Pattern `grep\s+(-[A-Za-z]*q\|--quiet)`. Verified against all three evasions — trailing-operator pipe, `grep -Fqx`, `grep --quiet` — each now fails, and heredoc noise correctly does *not* trip it |
| **3** (low) | **fixed.** The vacuity guard asserts the exact **set** of functions allowed a quiet grep (`render_sync_gate`, `previously_recorded_stashes`, `has_bulk_rewrite_trailer`), each with its reason. Verified: a decorative fifth site fails it, and so does moving a site to a new function |
| **4** (low) | **fixed (test).** Three tests drive `render_sync_gate` over a seeded gate file. Verified by making the swap: `test_a_binary_line_retires_a_stale_line_about_the_same_stash` fails, so the `gate_claim_keys`↔`gate_subject_keys` transposition is now caught |
| **5** (low) | **fixed.** `encode_record_path` escapes newlines (backslash first, or a literal `\n` and a real newline would encode alike); both sides of every comparison run through it, so nothing is decoded. NUL was not an option — a shell variable cannot hold one. Tests: `test_a_path_with_a_newline_stays_one_record`, `test_a_fragment_cannot_impersonate_a_path`, `test_a_literal_backslash_n_is_not_a_newline` |

Each fix was verified by applying the mutation it is meant to catch and watching the named test fail — 10 checks in all, every one killed.

## One thing to note about the measured run

`PA_HERMETICITY_STRICT=1` printed a banner I had not seen before:

> PA_HERMETICITY_STRICT=1, but the canonical store is not present here … The store half of the hermeticity guard is **INERT** in this run — an archive export has no `data/` submodule, so those paths dangle. Only the source-tree half is strict.

So the strict flag is only half-effective in a `git archive` copy, by design and with a loud warning. Worth knowing when reading these numbers: the store half of that guard has not been exercised by any of my measured runs this series.

## Measured suite

Clean `git archive` of `a35f7e6`, `HOME` pinned to a temp dir with a `.gitconfig` (identity, `init.defaultBranch=main`, `protocol.file.allow=always`), `PA_HERMETICITY_STRICT=1`, `--basetemp` isolated:

```
3861 passed, 1 skipped, 3 deselected, 34 subtests passed in 155.56s
EXIT=0
```

The 3 deselected are `pytest.ini`'s `-m "not integration"` (PostgreSQL).

```
$ git log --oneline main..HEAD
a35f7e6 test(daily-sync): drive render_sync_gate, not just its keys
1d7e98a test(daily-sync): tokenise the quiet-grep lint, name its sites
d7c52ee fix(daily-sync): keep one path to one status record
102fb0e fix(daily-sync): never let a trailer vouch for another commit
```

Merge-base `6504b46` — four clean commits, no merges needed.

## Live-behaviour risks

- **Item 1 makes the shrink guard stricter in one shape and noisier in another.** A range holding an unmeasurable merge *plus* a trailered commit that owns only part of the shrink now exits 4 where it previously published. And every unmeasurable merge writes a log line even on a run that publishes — new output in `daily-sync.log`, not a gate line.
- **Item 5 changes the record format** the tracked-half guard compares. Paths are now escaped on both sides; a path containing a literal backslash encodes differently than before, so an in-flight comparison spanning the upgrade could read as "not mentioned" once. The consequence is a kept stash, not a dropped one.
- Items 2, 3 and 4 are test-only — no runtime behaviour changes.
- `wiki/audits/2026-09-08-first-audit.md` still has no rows for any finding from rounds 3c-1 through 3c-7; they live only in commit messages and these reports. That is now seven rounds of durable record sitting outside the durable record.
