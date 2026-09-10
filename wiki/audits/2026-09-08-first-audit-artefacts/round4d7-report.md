# Round 4d-7 report (machine glue, PR #149 second round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic.

---

Round 4d-7 complete. `origin/main` merged first (49 commits, docs only), two commits added, working tree clean, nothing pushed.

## Dispositions

| ID | Disposition |
|---|---|
| **M1** | fixed — `scripts/sync-symlinks.sh` step 1 no longer interpolates `$DATA_REMEDY` inline; it calls `say_data_remedy` like every other site, and refuses to assert "uninitialised but not empty" about a submodule git declined to describe. The advice is now emitted from exactly one place, which a source-level test pins. The test that was meant to catch this asserted the prefixed `"Remedy: remove"`; a new `assert_no_destructive_advice()` helper checks the **sentence** across stdout **and** stderr. Mutations killed: restoring the inline advice (1 test); disabling the step-1 status gate (1). |
| **M2** | fixed — a new `WOULD_INIT` flag records that step 1 initialises (or would). A fresh-clone preview now says the file is absent *only because the init was previewed rather than performed*, prints no remedy, and does not claim a real run would refuse — which was false, as the companion test asserts directly by running that state for real and composing. Mutations killed: disabling the branch (1); never setting `WOULD_INIT` (1). |
| **L-i** | fixed — the failed-query test moved to the front of `say_data_remedy`. It sat behind `-z "$submodule_state"`, so a git exiting 128 having printed nothing was reported as "no data submodule is declared". Mutation killed: reverting the ordering (3 tests). |
| **L-ii** | fixed — `assert_composed` requires each marker to occur **exactly once**. Comparing first-occurrence positions only, a duplicated layer satisfied every assertion while doubling the operator's global instructions. Mutations killed: duplicating the local layer (6 tests); the common layer (6). |
| **L-iii** | fixed — the trim-set extraction parses whole argument lists and *refuses* anything that is not an integer literal. I verified the blind spot directly rather than inferring it: the old regex reads `[13, 32, 160, 8199, 8239]` from an expression naming seven code points, because `char(9, 10)` matched nothing. Mutations killed: a narrowing written with a comma list (4 tests); a hex literal (4). |

Two existing tests were updated, both because behaviour legitimately changed: one asserted the now-removed inline string, and the other used an **empty** `data/` for the "broken clone" note — but an empty `data/` is the fresh-clone state, and that conflation was precisely the M2 defect.

## Suite

Clean `git archive HEAD` copy in a `mktemp -d`, `HOME` pinned inside it, `--basetemp` isolated inside it, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

`4490 passed, 1 skipped, 19 deselected, 34 subtests passed in 172.56s (0:02:52)` — **exit code 0**.

The one skip, listed with `-rs`: `test_codex_main_tripwire.py:117: no checkout to calibrate against` — the archive-export artefact. (The two `numpy` skips from round 4d-6 are gone; `main` moved under me.) The strict guard again reported its **store half is inert** in an archive export, so STRICT proves the source-tree half only. All temp copies deleted.

`git log --oneline main..HEAD`:

```
72f7f6f test: close two blind spots in the assertions themselves
e6e8686 fix(sync-symlinks): one site for the destructive advice
c0241a7 Merge remote-tracking branch 'origin/main' into claude/audit-round4d-6
c4cc548 Merge remote-tracking branch 'origin/main' into claude/audit-round4d-6
7fc6dd6 fix(sync-symlinks): a failed status query is not a verdict
cd7be94 test(sync-symlinks): pin the submodule-status pathspec
efdaf0b test(sync-symlinks): assert what step 7 composed, not that it did
7ff5d38 fix(sync-symlinks): a preview shows the remedy it previews
734a28d test(zotero): the SQL trim set must be whitespace only
```

Three files changed against the merge-base: `scripts/sync-symlinks.sh`, `tests/test_doi_matching.py`, `tests/test_machine_glue.py`.

## Live-behaviour risks

1. **A failed `git submodule status` now stops step 1 doing anything** and reports the state as unknown, where previously it fell through to the uninitialised branches. Strictly safer, but it is a new "do nothing and say so" path: on a machine with a broken git, `sync-symlinks.sh` will decline the submodule step rather than guess.
2. **A fresh-clone `--dry-run` reads differently** — it now says the init would supply the missing file, and prints no remedy. Anything grepping preview output for "a REAL run would" will no longer match in that state (correctly).
3. **The destructive advice is now unreachable except from a successful `git submodule status` reporting `-`.** If some workflow depended on seeing that sentence, it will see the "state is unknown" or "data/ IS initialised" text instead.
4. **No change on the live machine's normal path**: `data/` is initialised with `local.md` present, so step 1 reports "already initialised" and step 7 composes exactly as before.
