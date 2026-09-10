# Round 4c-8 report (session archive pipeline, PR #147 closing round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic. The coordinator verified the ordering
mutation independently (copyto moved above copy → the named test fails).

---

Round 4c-8 complete — the closing round on this branch. Tree clean, scratch deleted (109,048 inodes freed; `/tmp` at 15%).

## Disposition

| ID | Disposition |
|---|---|
| **M-A** | **fixed** — `_rclone_writing`'s stub (and the large-slice stub) now record argv per subcommand as the fixture stub does, so `_ran(sandbox, "copyto")` reports reality. The ordering test also asserts the copy *did* run, and a new positive control asserts `copyto` runs after a **successful** copy. **Verified**: moving `push_catalogue live` above the `rclone copy` now fails `test_the_catalogue_is_not_pushed_when_the_copy_fails`; before this change that mutation left the whole suite green |
| **L1** | fixed — the orphaned "Never upload a staged temporary" comment removed from `RCLONE_BASE_FLAGS`; one copy remains, attached to the `--exclude "*.tmp"` it describes |
| **L2** | fixed — the dead `n_sizeless = 0` removed from the dry-run path |
| **L3, L4, L5** | recorded, not changed, as instructed — noted in the commit body so they survive as a record: no fixture exceeds ten entries; the lint scans `scripts/` and `hooks/` but not `setup.sh` (clean today); the `\| head -1` SIGPIPE class is unlinted, its sole instance in `daily-sync-trigger.sh:144` being safe without `-e` |

M-A is worth naming plainly: it is the same defect class this audit removed from `test_bulk_archive.py` back in round 4c — an assertion that could not fail, protecting the one ordering property that keeps a derived index from being published over a failed archive copy. I wrote it two rounds ago and did not check that the negative could ever go positive. The lesson that keeps recurring here is that a test asserting *absence* needs a paired control proving the mechanism can register presence at all; that control now exists.

## Suite

Clean `git archive` copy of HEAD, HOME pinned, `--basetemp` isolated, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

```
4585 passed, 1 skipped, 19 deselected, 34 subtests passed in 164.45s (0:02:44)
```

**exit code 0.** The single skip is `test_codex_main_tripwire.py` ("no checkout to calibrate against" — a `git archive` export has no `.git`). The store half of the hermeticity guard is inert in an archive copy, as its banner states; only the source-tree half is strict there.

## `git log --oneline main..HEAD`

```
fbb5a2d test(r2): make the stub record argv, so the ordering test can fail
c9b1329 Merge remote-tracking branch 'origin/main' into claude/audit-round4c-5
032d48d Merge remote-tracking branch 'origin/main' into claude/audit-round4c-5
9d5e404 fix(archive): print the sizeless remedy in the dry run too
e813336 fix(r2): one grep, no pipe; and let the derived catalogue change
e06c5a2 fix(archive): guard the dry-run listing and tighten the sizeless report
3775a0a fix(r2): match rclone's level marker, not the start of the line
2a5c81e fix(archive): summarise sizeless manifest entries once per run
3fa6b85 fix(normalise): count sweep failures, and handle *.tmp symlinks
f78bacb fix(r2): classify on rclone's refusal wording, not the bare word
… 13 commits total (three are merges of origin/main)
```

One commit this round. **Not pushed.**

## Standing risk to carry into the merge

Unchanged from last round and still the one to watch: the daily push has been exiting 3 since 2026-09-09 10:28 over `CATALOG.json`, and this branch is what fixes it. On the first run after merge, confirm the log shows the `copyto CATALOG.json` line and no `ABORTED` — that is the signal the live breakage is closed. If an `ABORTED` does appear for some *other* path, it is now a real corruption signal rather than an artefact, and it needs a human before the next push.
