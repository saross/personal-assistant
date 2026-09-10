# Round 4a-8 report (hermeticity guard, PR #155 closing round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic.

---

Round 4a-8 complete. One commit on top of the merge; working tree clean, nothing pushed, no temp copies left.

## Disposition

| ID | Disposition |
|---|---|
| **C1** (critical) | **fixed** — the hook now pre-filters on `os.path.basename(path)` against the two watched names (two short string compares, no filesystem access, so the hot path is untouched) and only then calls `os.path.realpath`, which follows the symlink **and** anchors a relative path against the cwd at event time. `_AUDITED_PATHS` holds real paths; a new `_AUDITED_NAMES` holds the basenames. Four tests: a nested store laid out exactly as the repository is (`memories -> data/memories`) with the append made **through the symlink path**, a relative open after `chdir`, a read through the symlink that must stay silent, and one asserting `realpath` is **not** called for a non-matching basename. The `str(candidate.resolve())` → `str(candidate)` mutation now fails 3 tests; dropping `realpath` fails 3; dropping the basename filter fails 1. |
| **M2** | **corrected, cause established.** I re-verified by instrumenting all five routes on this interpreter: `Path.open`, `Path.read_text`, `open(Path)`, `open(str)` all arrive as `str`; only `open(b"…")` gives `bytes`. So the recorded claim was false in both halves. The true cause **is** C1 — the prototype compared the raw event string against the resolved store path while the repository writes through the symlink — and both the conftest comment and the test docstring now say so. `os.fspath` is kept and labelled as harmless defensiveness; the bytes branch is genuinely reachable. |
| **M1** | fixed — the `store_writes` advisory branches on the mode like the `tolerated` block: under STRICT it reads "and this run FAILED on it" instead of telling the operator to set a variable that is already set. Pinned by a nested STRICT run and its advisory counterpart. |
| **L2** | fixed — "none detectable" replaced everywhere with the measured figures: **+2.5 s per full run (≈ +1.6 %)** from the re-auditor's paired runs, and **≈ +0.5 µs per `open`** — I measured 0.588 µs over 40 000 opens here, corroborating their 0.45 µs. The note also records *why* the old claim was wrong (two unpaired runs on a loaded machine). |
| **L1** | **noted, with a partial fix.** I tried the stats route: registering a stand-in report in `terminalreporter.stats["error"]` does turn the line red — and then `summary_stats` calls private reporter API on the entry (`_get_verbose_word_with_markup`), which couples the guard to pytest internals for a cosmetic gain. `trylast` cannot help, because the line is built from the reporter's own counters, not from `session.exitstatus`. So the exit code stays correct and the guard now writes a red **"EXIT STATUS 1 — read the exit code, not the green summary line below it"** as the last thing before the stats line. The reason is recorded in the code, and the line is pinned by the nested leak test. |

Five mutations applied and reverted; all killed.

## Runs

| Run | Result |
|---|---|
| **1.** Clean archive copy, populated synthetic store **reached through the `memories` symlink**, STRICT | `4567 passed, 1 skipped, 19 deselected, 34 subtests passed in 563.86s` — exit **0**, **no banner** (store half live), all four store files byte-identical |
| **2.** Same, advisory, out-of-process append **via the symlink path** at t+60 s | `4567 passed, … in 165.89s` — exit **0**; `note: the live system appended to …/data/memories/memories.jsonl (+144 bytes)`; **audit hook silent**, which is the discrimination working — the write came from another process |
| **3.** Same, STRICT, out-of-process truncated append via the symlink | `4567 passed, …, 1 error in 164.62s` — exit **1**; `note: would be tolerated in advisory mode; fatal under PA_HERMETICITY_STRICT (an append in progress): …` |
| **4.** Worktree, real HOME, cwd in a temp dir, STRICT, hermeticity file only | `179 passed in 8.31s` — exit **0**, INERT banner as expected (the worktree's `data/` is a stub) |

Run 1's 563 s is machine load, not the guard: runs 2 and 3 on the same tree took 165 s each.

```
398290a fix(hermeticity): match the path form the repository writes through
f401ab8 Merge remote-tracking branch 'origin/main' into claude/audit-round4a-7
72177ca Merge remote-tracking branch 'origin/main' into claude/audit-round4a-7
dddae66 feat(hermeticity): catch an in-process write to the real store
bce57d2 fix(hermeticity): net wider-scoped leaks, tolerate truncated appends
```

`f401ab8` is this round's merge of `origin/main` (clean, no conflicts). The branch is 41 commits behind again — other rounds keep landing — so a further merge will be needed before the PR.

## What I'd want a reader to know

- **C1 means the audit hook shipped last round was watching nothing.** Every claim in the round 4a-7 report about M1 being "covered for the in-process case" was true only for a store reached by its real path. In this repository it never was. That is now fixed and pinned by a nested tree with the same symlink layout — the specific gap that let the bug through was that the old nested store was a plain directory.
- **The basename pre-filter is load-bearing for cost, not correctness.** Without it `realpath` — which stats every path component — would run on every one of the tens of thousands of opens a full run makes. The test that asserts `realpath` is *not* called for a non-matching name is there to keep that true.
- **L1 is a real cosmetic defect that survives.** A queue leak exits 1 while pytest's own last line reads green. Anything reading the exit code is fine; a human skimming the tail of the output could be misled, which is why the compensating red line is the last thing printed before it.
- **Live store untouched.** Nothing this round wrote to `~/personal-assistant/data`; run 4's guard reported the worktree's stub as inert, as it should.
