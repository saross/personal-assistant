# Round 4d-6 report (machine glue, lows after PR #138)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4d-6 complete: 5 commits on `claude/audit-round4d-6`, working tree clean, clean merge against `main`, nothing pushed.

## Dispositions

| ID | Disposition |
|---|---|
| **L1** | fixed — `tests/test_doi_matching.py` `test_every_trimmed_character_is_whitespace` asserts every `char(n)` in the shipped expression satisfies `chr(n).isspace()`. The count test only looked at whitespace points *absent* from the set, so a non-whitespace addition was invisible to it. Mutation killed: adding `char(48)`. |
| **L5** | fixed — `scripts/sync-symlinks.sh:378` the `--dry-run` branch now calls `say_data_remedy`. A preview of an initialised-but-incomplete submodule was withholding the "Do NOT delete" line while the real run printed it. 2 tests, one asserting preview and real run give the *same* remedy whatever the state. Mutation killed: dropping the call (2 tests). |
| **L4** | fixed — both dry-run notes pinned, in both directions: a worktree preview must say "belongs to the main" and must **not** claim "a REAL run would refuse at step 1" (which is false — the real worktree run exits 0). Mutation killed: swapping the two branches (5 tests). |
| **L7** | fixed — one `assert_composed()` helper checks all three layer markers are present **and in order**, taking the local marker as a parameter (`LOCAL-SECTION` where no init ran, the stub's `MARKER-LOCAL` where it did — a distinction worth keeping visible, since it separates the two paths those tests exist for). Applied at five sites. Mutations killed: dropping the local layer (5 tests); swapping common and overlay (5). |
| **L2** | fixed — the stub git now honours the pathspec as real git does, which is what makes two-submodule cases representable; two tests cover `vendor` uninitialised ahead of an initialised `data` and the reverse. Mutation killed: dropping `-- data` (2 tests). |
| **L3** | fixed (test-only, as scoped) — a **directory-shaped** `data/.git` case in the composer tests. The `-e` in `compose-global-claude-md.sh:191` already shipped from round 4d-5; nothing exercised its breadth. Mutation killed: `-e` → `-f`. |
| **L9** | fixed (the concrete half) — `git submodule status`'s **exit status** is now captured alongside its output, and the destructive remedy requires both `-` and status 0. A failed query gets its own "state is unknown, do not delete on the strength of it" message. Mutations killed: ignoring the status; dropping the conjunct. The divergence half (this script asks git, the composer asks the filesystem) is recorded in a comment with the reasoning for leaving it: reconciling them means giving the composer a git dependency it does not have, and the composer already takes the conservative side. |
| **L8** | fixed — `submodule_state` and `SUBMODULE_STATUS_OK` are declared with safe defaults near the top, so a future call above the assignment cannot abort under `set -u`. The defaults read as "no submodule declared", which never selects the destructive branch. |
| **L6** | recorded in a comment beside the regex, as scoped: the pattern needs a literal `/.git/` component, so a relative pointer or a bare-repo worktree pointer would not match. Also recorded is why the asymmetry is tolerable — a false negative costs a declined init, a false positive skips a needed one. |

Every fix was verified by applying the mutation and watching the named test fail.

## Suite

Clean `git archive HEAD` copy in a `mktemp -d`, `HOME` pinned inside it, `--basetemp` inside it, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

`4377 passed, 3 skipped, 19 deselected, 34 subtests passed in 189.40s (0:03:09)` — **exit code 0**.

The three skips, listed with `-rs` rather than assumed:

- `test_codex_main_tripwire.py:117: no checkout to calibrate against` — the usual archive-export artefact.
- `test_style_phase5.py:781` and `:865: could not import 'numpy'` — from test files that arrived on `main` during this round, not from anything here.

The strict guard again reported its **store half is inert** in an archive export ("only the source-tree half is strict"), so STRICT proves the source-tree half only. All three temp directories deleted.

`git log --oneline main..HEAD`:

```
7fc6dd6 fix(sync-symlinks): a failed status query is not a verdict
cd7be94 test(sync-symlinks): pin the submodule-status pathspec
efdaf0b test(sync-symlinks): assert what step 7 composed, not that it did
7ff5d38 fix(sync-symlinks): a preview shows the remedy it previews
734a28d test(zotero): the SQL trim set must be whitespace only
```

Three files touched: `scripts/sync-symlinks.sh`, `tests/test_doi_matching.py`, `tests/test_machine_glue.py`. (`scripts/compose-global-claude-md.sh` needed no change — I verified its `-e` test at line 191 came in with PR #138.)

## Live-behaviour risks

1. **A dry run now prints the remedy too.** Output on a broken checkout is longer; nothing that parses it should break, but the preview and the real run now emit the same remedy lines.
2. **A failed `git submodule status` changes the advice, not the outcome.** The run still exits 1 when `local.md` is missing; it just no longer offers to delete `data/` on the strength of a query that failed. Strictly safer.
3. **No behaviour change on the live machine's normal path.** `data/` is initialised there with `local.md` present, so step 1 still reports "already initialised" and step 7 composes as before.
4. **`git submodule status` output is now consumed with its exit status**, so a git that writes to stdout and fails is treated as a failure rather than as data — a stricter reading than before, and one that could newly surface a broken git installation as "state is unknown" rather than as a confident (wrong) verdict.
