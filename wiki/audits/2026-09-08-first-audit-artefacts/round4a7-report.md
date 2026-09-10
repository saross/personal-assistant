# Round 4a-7 report (hermeticity guard, follow-ups after PR #143)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4a-7 complete. Two commits, working tree clean, nothing pushed, no temp copies left.

## Disposition

| ID | Disposition |
|---|---|
| **M-f1** | fixed — the nested terminal test now asserts the rendered label (`"(a lock file)"`, and that `"a lock file or a rotation"` is absent), and a **second class** goes through the same call site (`test_the_new_log_label_reaches_the_terminal`, a new `.jsonl` → `"(a new log file)"`), so no single literal can satisfy both. |
| **M-a1** | fixed — the check moved into `pytest_sessionfinish`, which runs after every fixture of **every scope**: a queue entry under `--basetemp` or the factory's root (both, and their realpaths) is dropped, reported in red, and **fails the session**. The vacuous test is deleted; three nested tests replace it — the session-scoped-fixture leak (reproduces the finding, now non-zero exit), a real change passing through untouched, and one run carrying **both**, proving only the leak is dropped. |
| **M-b1** | fixed — an unterminated tail is now judged **structurally**: for `memories.jsonl` it must open a JSON object, for the vocabulary it must be a bare-tag prefix. Advisory reports it as in-progress; STRICT is fatal for both. All four cells parametrised, plus the realistic "one whole record then a cut-off one". The docstring (which was false) states the rule and why. |
| **L-d1** | fixed — all three sentences. `conftest.py` and `commands/audit.md` now list the advisory exceptions to "a new file is a failure either way", and the over-stated "anything looser fails" is replaced with what is actually true (a whitespace-only line passes; an unterminated JSON-opening tail is in-progress). |
| **L-e1** | fixed — a directory is labelled by what it **is**, so `run.2` is `"a new directory"`, not a rotation · `test_a_new_directory_is_labelled_as_one`. |
| **L-f2** | fixed — the dead rotation arm inside the suffix branch is deleted, with a comment saying why it could never fire. I found and deleted a second dead branch of the same class while there: the newline test in the new prefix rule, whose input is the last element of a `"\n"` split. |
| **L-g1** | fixed — under STRICT the note reads "would be tolerated in advisory mode; fatal under PA_HERMETICITY_STRICT", pinned by a nested run that greps for it and for the absence of the old wording. |
| **PROPOSAL** | **shipped.** Criteria met, so I implemented it behind the STRICT/advisory split with tests. |

Nineteen mutations applied and reverted across the round; all killed.

## The audit-hook proposal — measured, then shipped

Prototyped on a scratch copy first, as asked. **Overhead: none detectable** — a full run with the hook took 179.5 s against 185.3 s for the same tree without it, inside run-to-run noise on a machine running other agents' suites. **Detection works**, but the first prototype found nothing at all, for two reasons now pinned by tests:

- `Path.open` hands the audit event a **`PosixPath`, not a `str`**, so `isinstance(raw, str)` misses the commonest route into the store entirely.
- `os.open` raises the same `open` event with **`mode=None`** and the real flags, so checking only the mode string misses every `os.open`.

The shipped version resolves via `os.fspath`, consults mode **and** flags, arms only when the store exists, and guards against stacking a second permanent hook. Advisory mode names the offending test; STRICT fails the run. Failure mode is under-detection only — a subprocess or a C-level write evades it — so it cannot fail a live checkout falsely, which is what makes it safe to leave armed. M1 is no longer "documented and open" in `commands/audit.md`; it is "covered for the in-process case", with the residue stated.

Run 2 below is the discrimination working end to end: an **out-of-process** well-formed append was reported as a live-system append and the run passed, with the audit hook silent.

## Runs (all on the committed tree)

| Run | Result |
|---|---|
| **1.** Clean archive copy, populated synthetic store, STRICT | `4364 passed, 3 skipped, 19 deselected, 34 subtests passed in 170.97s` — exit **0**, **no banner**, all four store files byte-identical (`md5sum -c`: 4× OK) |
| **2.** Same, advisory, background well-formed append at t+45 s | `4364 passed, … in 168.69s` — exit **0**; summary: `note: the live system appended to …/memories.jsonl (+144 bytes)` |
| **3.** Same, STRICT, background truncated append at t+45 s | `4364 passed, …, 1 error in 162.58s` — exit **1**; summary: `note: would be tolerated in advisory mode; fatal under PA_HERMETICITY_STRICT (an append in progress): …` |
| **4.** Worktree, real HOME, cwd in a temp dir, STRICT | `4351 passed, 2 skipped, 19 deselected in 159.90s` — exit **0**, INERT banner as expected (the worktree's `data/` is a stub) |

```
dddae66 feat(hermeticity): catch an in-process write to the real store
bce57d2 fix(hermeticity): net wider-scoped leaks, tolerate truncated appends
```

**One thing you should know about run 4.** My first attempt at it failed with `1 failed, 4012 passed, 338 errors`, concentrated in `test_zotero.py`. Re-running the identical command passed cleanly (the figure above). This is the same transient I hit in round 4a-3: sibling agents running suites concurrently contend for `/tmp` and for pytest's shared `/tmp/pytest-of-shawn` namespace. `/tmp` is at 13% now, so I could not reproduce it. I am reporting the passing run because it is the reproducible one, but the failure is worth knowing about — if a re-audit sees a burst of `test_zotero` errors, check machine load before suspecting the code.

## Live-behaviour risks

- **`sys.addaudithook` is permanent for the process.** Nothing can remove it, so a mistake here would be un-disarmable within a run. The guard is `event != "open"` first and a two-element set membership second, and it never raises — but it now runs on every file open in the suite, which is a new always-on cost centre even though it measured as free.
- **The audit hook watches paths resolved at session start.** A test that repoints `_CANONICAL_FILES` is *not* watched — correct, since only the real store matters — but it also means the hook silently covers nothing in an archive copy, exactly where STRICT is otherwise armed.
- **Under-detection is real.** A test that shells out to a script which appends to the store is invisible to the hook and, if the append is well-formed, invisible to the snapshot too. That is the residue of M1 and it is now written down in both places rather than implied.
- **"In progress" is now broader than it was an hour ago.** A truncated append is tolerated in advisory mode again, which is what the extraction hook's single `os.write` actually produces on a short write — but it means advisory mode accepts a corrupt final line until the writer finishes or the file is repaired.
- **`main` is 69 commits ahead.** A merge is needed before the PR; the previous two went through cleanly, but that is a large gap and `tests/conftest.py` is a file other rounds also touch.
- **Live store untouched.** Nothing this round wrote to `~/personal-assistant/data`; its mtime moves only with the extraction hook's own appends.
