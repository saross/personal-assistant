# Round 4d-8 report (machine glue, PR #149 closing round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic.

---

Round 4d-8 complete. `origin/main` merged first (27 commits), one commit added as asked, working tree clean, nothing pushed.

## Dispositions

| ID | Disposition |
|---|---|
| **M-1** (blocking) | fixed — `destructive_advice()` now parses the `DATA_REMEDY=` literal out of `scripts/sync-symlinks.sh` (handling the backslash-continuation, splitting off the interpolated `$PA_DIR/data`) instead of hard-coding a fragment. The source-level test requires that literal to stay parseable, and a positive control asserts the derived text is actually printed. Verified against the auditor's own case: **reword alone passes** (a reword is legitimate), **reword + re-injected regression fails**. |
| **M-2** | fixed — the destructive branch of `say_data_remedy` gains a `WOULD_INIT -eq 0` conjunct. `$submodule_state` is captured once before step 1 and never re-read, so after a successful init it still says `-`; a submodule git had just cloned into was being told to delete itself whenever the recorded pa-data commit lacked `global-claude-md/local.md`. That state now gets "IS initialised … Do NOT delete … `git -C data status`". Test uses a stub `submodule update` that populates `data/memories/` but not `local.md`, and asserts the checkout survives. |
| **L-1** | fixed — the exit-0 non-empty case asserts the derived advice is printed from step 1. Mutation killed: deleting `say_data_remedy` at step 1 (and, separately, at the step-7 stop — 4 tests). |
| **L-4** | **decided: printed twice, and pinned at exactly two.** Each site is the only one that speaks in a state the other does not reach — step 1's is the only voice when `data/` is a non-submodule that happens to contain `local.md` (the run then succeeds and step 7 never fires); step 7's is the last thing in a cron log. Both read the same string from the same function, so they cannot drift. |

One thing worth flagging: with M-2's gate in place, the regression the auditor re-injected no longer prints the *destructive* line — it prints a **false** one, "data/ IS initialised", about an init that was only narrated. So the fresh-clone preview now asserts **no `Remedy:` of any kind**: nothing is wrong there, so there is nothing to remedy. That is what catches the regression.

Mutations killed: disabling the `WOULD_INIT` gate; deleting `say_data_remedy` from step 1; from the step-7 stop (4 tests); adding one to the fresh-clone preview, with and without a reword.

## Suite

Clean `git archive HEAD` copy in a `mktemp -d`, `HOME` pinned inside it, `--basetemp` isolated inside it, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

`4546 passed, 1 skipped, 19 deselected, 34 subtests passed in 168.82s (0:02:48)` — **exit code 0**.

The one skip, listed with `-rs`: `test_codex_main_tripwire.py:117: no checkout to calibrate against` — the archive-export artefact. The strict guard again reported its store half is inert in an archive export, so STRICT proves the source-tree half only. All temp copies deleted.

`git log --oneline main..HEAD`:

```
cee582c fix(sync-symlinks): never tell a fresh checkout to delete itself
43dbf93 Merge remote-tracking branch 'origin/main' into claude/audit-round4d-6
f8b071a Merge remote-tracking branch 'origin/main' into claude/audit-round4d-6
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

## Live-behaviour risk

One, and it is a narrowing: **the destructive advice is now unreachable in any run that initialised the submodule.** A machine that clones fresh, initialises `data/`, and finds `local.md` still missing will be told to look inside the submodule rather than to delete it. On the live checkout nothing changes — `data/` is initialised with `local.md` present, so step 1 reports "already initialised" and step 7 composes as before.
