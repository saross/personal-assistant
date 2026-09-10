# Round 4c-7 report (session archive pipeline, PR #147 third round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic.

---

Round 4c-7 complete. Tree clean, scratch deleted (108,635 inodes freed).

## Disposition

| ID | Disposition |
|---|---|
| **C-1** (blocking) | **fixed** — one `grep -qE` over a here-string, no pipe. Reproduced before and after at every scale (table below). Plus a repository-scope lint that found **two more instances of the same class in the same script** |
| **Addendum** (live) | **fixed** — `CATALOG.json` excluded from the immutable copy and pushed separately without `--immutable`. Exact invocations quoted below |
| **M-1** | fixed — the comment now separates what the deployed log *attests* (level **and** wording, at both ERROR and NOTICE for the same event) from the defensive `Timestamp mismatch` match, labelled unattested: it exists in the binary's strings, its level is unverified, and it occurs **0** times in the log |
| **M-2** | fixed — `--log-format date,time` pinned in the flags, with the reason: it is rclone's own default so nothing changes today, but `RCLONE_LOG_FORMAT` or `--use-json-log` would reshape every line and silently reproduce C1 |
| **Lows** | fixed — the dry run now prints the "re-run discover" remedy itself (it returns before the summary that carried it, so the old comment described a path that could not run); `entry.get("turns", "?")` is tested; **SIZELESS_IDS_SHOWN** noted as pinned by the pre-existing literal test, which is why both tests are kept |

## C-1 — before and after, at scale

The defect is invisible below one pipe buffer, which is why every one-line stub passed:

| stub | before | after |
|---|---|---|
| refusal first, 0 trailing marker lines | 3 | 3 |
| refusal first, 100 trailing | 3 | 3 |
| refusal first, **1,000** trailing | **2** ← wrong | **3** |
| refusal first, 5,000 trailing | — | 3 |
| refusal **last**, 1,000 leading | 3 | 3 |
| 5,000 marker lines, **no** refusal | 2 | 2 |

`grep -q` exits at its first match, the upstream grep dies of SIGPIPE, and under `pipefail` the *matched* pipeline returns 141 — so the `if` took the false branch. Refusal-last passes because the quiet grep then reads to the end before matching. The deployed log holds 4,658 `ERROR :` lines in 2.5 MB, so the failing regime is the ordinary one.

**The lint found two more.** `tests/test_pipefail_grep_lint.py` scans every `pipefail` script under `scripts/` and `hooks/`, importing the tokeniser and matcher from `test_daily_sync_stash_helpers.py` rather than copying them. On first run it failed on `push-archives-to-r2.sh:179` (`df … | tail -1 | grep -q`) and `:184` (`listremotes | grep -q`). Neither had bitten yet; both were one busy output away. Fixed the same way rather than allow-listed — the allow-list is empty, and has tests that every entry names a real file, carries a reason, and still suppresses something.

## The addendum — exact new invocations

Immutable bulk copy (catalogue excluded, anchored at the transfer root):

```
rclone copy --log-format date,time --s3-no-check-bucket --s3-disable-checksum \
  --fast-list --transfers 16 --checkers 16 --stats 30s --stats-one-line \
  --log-file "$LOG_FILE" --log-level INFO \
  --exclude "*.tmp" --exclude "/CATALOG.json" --immutable \
  "$CANON/" "$DEST/"
```

Then, only after that succeeds — no `--immutable`, because a replace is the intent:

```
rclone copyto --log-format date,time --s3-no-check-bucket --s3-disable-checksum \
  --fast-list --transfers 16 --checkers 16 --stats 30s --stats-one-line \
  --log-file "$LOG_FILE" --log-level INFO \
  "$CANON/CATALOG.json" "$DEST/CATALOG.json"
```

Verified by inspection of the recorded argv: `--immutable` appears on the `copy` and on nothing else. Absent catalogue → skipped, exit 0, "nothing to publish". Copy fails → `copyto` never runs (the index can never describe objects that failed to upload). `copyto` fails → exit **2** with "the archive copy SUCCEEDED, only the derived index is stale", never 3. Dry run previews both with `--dry-run` on each.

## Suite

Clean `git archive` copy of HEAD, HOME pinned, `--basetemp` isolated, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

```
4529 passed, 1 skipped, 19 deselected, 34 subtests passed in 169.58s (0:02:49)
```

**exit code 0.** The one skip is `test_codex_main_tripwire.py` (an archive export has no `.git`); the numpy skips are gone since main moved. The store half of the hermeticity guard remains inert in an archive copy, as its banner states.

## `git log --oneline main..HEAD`

```
9d5e404 fix(archive): print the sizeless remedy in the dry run too
e813336 fix(r2): one grep, no pipe; and let the derived catalogue change
d86b4c6 Merge remote-tracking branch 'origin/main' into claude/audit-round4c-5
fe9c570 Merge …
e06c5a2 fix(archive): guard the dry-run listing and tighten the sizeless report
3775a0a fix(r2): match rclone's level marker, not the start of the line
1286407 Merge …
2a5c81e fix(archive): summarise sizeless manifest entries once per run
3fa6b85 fix(normalise): count sweep failures, and handle *.tmp symlinks
f78bacb fix(r2): classify on rclone's refusal wording, not the bare word
```

Two new commits. The C-1 fix and the addendum share one because they change the same function and flag list; the message describes both separately. Not pushed.

## Live-behaviour risks

1. **The daily push should go back to exit 0 on the next run.** It has failed with exit 3 every run since 2026-09-09 10:28 over `CATALOG.json`. Worth confirming on the first run after merge that the log shows the `copyto` line and no ABORTED.
2. **The catalogue's R2 object becomes mutable again** — as it was before the `--immutable` flag, and as it must be for a derived index. Every other object stays immutable; a session transcript or metadata changing still raises the corruption signal.
3. **A real refusal will now actually be detected.** On this branch since round 4c-5 it could not be, at any realistic log size. If there is genuine corruption in the canonical store beyond the catalogue, the next push will exit 3 and say so — that is the point, but it may look like a new failure.
4. **The new lint may fail on scripts I have not touched.** It scans every `pipefail` script under `scripts/` and `hooks/`; it passes on the tree as it stands, but a script merged from another agent's branch carrying `| grep -q` will now fail the suite. That is intended (the class has shipped twice), and the allow-list with reasons is the escape hatch.
5. **`--log-format date,time` is now explicit.** If anyone was setting `RCLONE_LOG_FORMAT` deliberately for this script, it no longer takes effect.
