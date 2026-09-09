# Round 4d-5 report (machine glue, PR #138, second round)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4d-5 complete: 3 commits added to `claude/audit-round4d-4` (PR #138), working tree clean, clean merge against `main`, nothing pushed.

## Dispositions

| ID | Disposition |
|---|---|
| **C1** (blocking) | fixed — `scripts/sync-symlinks.sh:250` `say_data_remedy()` picks by `$submodule_state`: the destructive "remove data/ entirely" is reachable **only** when git reports no checkout, so nothing of the operator's can be inside it; an initialised submodule gets `git -C data status` plus an explicit "Do NOT delete"; no declared submodule gets a third message. `compose-global-claude-md.sh:186` now branches on whether the submodule has a **checkout** (`data/.git`) rather than on emptiness — an initialised submodule is also non-empty, which is what made its test wrong. 6 tests, incl. one asserting the `memories.jsonl` the old advice would have destroyed is still there. Mutations killed: restoring the single ungated remedy (2), collapsing the composer's checkout branch (1). |
| **M-a** | fixed — the `DRY_RUN -eq 0` gate moved off the whole pre-check and onto the STOP alone, so a preview now sets `SKIP_COMPOSE` instead of running a composer that must die. Worktree + `--allow-worktree` + `--dry-run` → exit 0, `SKIPPED`, step 8 reached, nothing written. Mutation killed: restoring the gate (2 tests). |
| **L-c** | decided and pinned — a dry run on a broken clone **narrates to step 8 and exits 0**, saying "a REAL run would refuse at step 1". A preview changes nothing, so it must not fail, and one that stops two thirds of the way through is not a preview. |
| **M-b** | fixed — the git stub now creates `data/global-claude-md/local.md` and `data/.git` on `submodule update`, as real git does. The four tests that were inspecting runs which exited 1 now assert **exit 0**, `[8/8]`, and a composed `CLAUDE.md`. |
| **Survivor (i)** | fixed — both remedy branches pin their text (`Remedy: remove` + the rationale for the uninitialised case; the non-destructive wording for the initialised one). Mutation killed: deleting the remedy line (3 tests). |
| **Survivor (ii)** | fixed — a "data/ present but empty" composer case. Mutation killed: dropping the `ls -A` conjunct. |
| **Survivor (iii)** | fixed — a recording wrapper in front of the composer inside the sandbox (reached by a symlink in the sandbox's own `scripts/`, so `PA_DIR` still resolves there) makes consultation observable; exit status and step 8 pinned. Mutations killed: replacing either passthrough with `:` (1 and 4 tests). |
| **L-a** | fixed — recounted against the shipped set: **22**, not 24, and `U+2007` is in the expression so the `U+2000`–`U+200A` run has a gap. The comment now enumerates `U+2000`–`U+2006`, `U+2008`–`U+200A`, and the test parses the `char()` list out of the source, recomputes over the whole of Unicode, and compares with the number claimed. Mutations killed: restoring the stale count; removing `U+2007`. |
| **L-b** | fixed (was note-only; the exact test turned out to be trivial) — `.git` must be a file **whose pointer names `/.git/worktrees/`**. A submodule checkout's says `/.git/modules/`, and both shapes were confirmed against this worktree and the live `data/`. This needs no git binary, which matters because step 1 runs before anything has established git works. Mutations killed: bare `-f`; loosened pattern. |

Every fix was verified by applying the mutation and watching the named test fail.

## Suite

Clean `git archive HEAD` copy in a `mktemp -d`, `HOME` pinned inside it, `--basetemp` inside it, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

`3874 passed, 1 skipped, 3 deselected, 34 subtests passed in 158.30s (0:02:38)` — **exit code 0**.

Two qualifications, both printed by the run itself rather than inferred:

- The strict guard reported that its **store half is inert** in an archive export ("an archive export has no data/ submodule, so those paths dangle. Only the source-tree half is strict"). So STRICT here proves the source-tree half only; exercising the store half needs the live checkout or a worktree with the submodule populated.
- The one skip is `test_codex_main_tripwire.py:117: no checkout to calibrate against` — the same archive artefact as previous rounds, re-confirmed by running that file alone.

All three temp directories deleted.

`git log --oneline main..HEAD` (this round's three on top of round 4d-4's seven and the merge):

```
24daadd fix(sync-symlinks): distinguish a worktree from a submodule
251d2c4 docs(zotero): recount the divergence against the shipped set
31efd4f fix(sync-symlinks): never advise deleting a live submodule
610c971 Merge branch 'main' into claude/audit-round4d-4
f759d9f test(syncthing): pin the early return on a missing folder
5642a41 test(inventory): pin --project . against the containment check
4d92dfd test(sync-symlinks): pin --quiet on the submodule line
4ea42dc docs(zotero): count the trim divergence, and cover two more
4638ab0 fix(compose): catch dangling and relative routes to the live file
2c5130c fix(sync-symlinks): give the remedy that works, and stop early
3986a48 fix(sync-symlinks): read the checkout, not the flag
```

## Live-behaviour risks

1. **The step-1 stop cannot fire on the live machine as it stands.** I checked read-only: `~/personal-assistant/data/global-claude-md/local.md` is present and `data/.git` exists. Should `local.md` ever go missing there, `sync-symlinks.sh` now exits 1 at step 1 — and, thanks to C1, tells the operator to look inside the submodule rather than delete it.
2. **A dry run on a broken checkout now exits 0** where it previously exited 1. Anything treating `sync-symlinks.sh --dry-run`'s status as a health check will read differently; the diagnosis is in the output, not the status.
3. **Worktree detection is narrower.** A `.git` file whose pointer is neither shape (a hand-made or unusual layout) is now treated as an ordinary clone, so its `data/` may be initialised where before it would have been skipped.
4. **The composer's error text changed** for two of three states; anything grepping its stderr for "Remove" will now miss the initialised case, which is the point.
5. **Unchanged from round 4d-4:** `--allow-worktree` on a real worktree still relinks `~/.claude` at the worktree and skips step 7 — a deliberately mixed state the operator opts into, now reachable under `--dry-run` too without an error.
