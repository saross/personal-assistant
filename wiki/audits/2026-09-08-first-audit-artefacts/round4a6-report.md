# Round 4a-6 report (hermeticity guard follow-ups, PR pending)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4a-6 complete. One commit, working tree clean, nothing pushed, no temp copies left.

## Disposition

| ID | Disposition |
|---|---|
| **M3** | fixed — `isolated_report` moved into `conftest.py:451` as **autouse**, so a test cannot forget it; the local opt-in fixture in the test file is gone. Three tests: `test_the_report_queue_is_isolated_for_every_test` (structural — asserts `autouse=True`, kills dropping it), `test_a_test_cannot_leak_a_basetemp_path_into_the_summary` (the counterfactual, driving the exact call that leaked), and `test_the_session_queue_holds_no_basetemp_path` (a session-level net naming any future escapee). |
| **M2** | fixed — `_appended_content_problem` now runs `_line_problem` on the unterminated tail too, and downgrades to in-progress only if it passes. `write("not json at all")` with no newline is a violation in both modes. Consequence worth noting: "in progress" now means *a complete, valid record whose newline has not landed* — a truncated JSON fragment is a violation, which is the stricter reading and matches the instruction. Two existing partial-line tests were updated to that shape; three new tests cover the garbage fragment (both modes) and the vocabulary equivalent. |
| **M1** | **behaviour unchanged, as instructed**; documented instead. `commands/audit.md` gains a titled paragraph, "The append allowance, and what it leaves uncaught", saying plainly that a well-formed append is tolerated **even under STRICT**, that a test forgetting to patch its path and appending a shape-correct record is therefore not caught in either mode, and what narrows it (always reported; the line must be a complete record with `id`/`content`/`created_at`). The conftest docstring says the same. **No proposal to close it** — see the risks below for why I do not think there is a safe one. |
| **L4/L5** | fixed — `_TOLERATED_NEW_LOG_SUFFIXES = (".log", ".json", ".jsonl")` and new **directories** under `logs/` are tolerated, advisory only (the real `data/logs/` holds `drift-sweep.jsonl`, `bulk-archive-manifest.json`, and `terra-enrich-responses/terra`). A file inside a newly tolerated directory is still judged on its own merits · 6 tests including the strict-mode counterpart. |
| **L6** | fixed — `describe_tolerated_kind` labels each entry: "a lock file", "a log rotation", "a new log file", "an append in progress" · parametrised over 7 shapes. |
| **L7** | fixed by making it **load-bearing** rather than dropping it: now that `.jsonl` is a tolerated new suffix, `_under_logs` is what stops a CREATED `memories.jsonl` reading as ordinary log output · `test_a_created_store_file_is_never_noise`, plus `test_under_logs_is_anchored_on_the_separator`. |
| **Survivors** | all killed — `.xz`, `.3.xz` and `.Z` added to the rotation parametrize (8 cases); `test_the_inert_banner_names_a_missing_directory`; `is_dir` vs `exists` in the coverage check; `_under_logs` separator anchoring; `partial.strip()` vs `partial`. |
| **L8, L9** | noted, not changed — see below. |

Eleven mutations applied and reverted; all killed.

## Suites

**Clean `git archive` copy with a populated synthetic store** (five well-formed records, a sectioned vocabulary, `extraction.log` and `daily-sync.log`), `env -i`, `HOME` pinned, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`, isolated `--basetemp`:

`3951 passed, 1 skipped, 3 deselected, 34 subtests passed in 156.67s (0:02:36)` — exit **0**.

**No `hermeticity` banner at all** (grep count 0), so the store half was live rather than inert, and all four store files were byte-identical afterwards (`md5sum -c`: 4× OK). The skip is `test_codex_main_tripwire.py:117: no checkout to calibrate against`.

**Worktree, real HOME, cwd in a temp directory**, same flags:

`3938 passed, 3 deselected in 160.75s (0:02:40)` — exit **0**. This one prints the INERT banner, correctly: the worktree's `data/` submodule is a stub, so the two store paths dangle and only the source-tree half was strict.

```
9a60123 fix(hermeticity): guard the report queue, judge partial appends
```

`main` moved 5 commits ahead during the runs; a merge will be needed before the PR, and the previous round's merge went through cleanly.

## Live-behaviour risks

- **M1's hole is now documented, not closed.** A test that appends a shape-correct record to the real `memories.jsonl` still passes in both modes. I considered three ways to distinguish the suite's append from the machine's and rejected all of them, so I am not proposing one: comparing the appended `created_at` against the run window fails whenever the hook writes a backdated record; checking the writer's pid needs a hook the appender does not offer; and holding an exclusive lock across the run would block the live system for two minutes. Each wrong answer fails *every* run in a live checkout, which is worse than the hole. The honest mitigation is the one now in place — the append is always reported with its byte count, so a reader who was not expecting one can act.
- **The advisory surface widened again.** New `.json`/`.jsonl` files and new directories under `logs/` no longer fail an advisory run. Each is still reported, and each is fatal under STRICT, but a test that creates `logs/something.json` will not be caught outside a clean copy.
- **"In progress" got stricter, which could bite.** A genuinely truncated JSON record — a crash mid-write — is now a violation rather than tolerated noise. That is the instructed behaviour and the right default, but if the extraction hook ever crashes mid-append in a shared checkout, the next suite run will fail on it until the corpus is repaired.
- **L8 (noted, not changed):** `_DEFERRED_REPORT` is never cleared between the source and store halves, so a stale entry from an earlier write would survive into the summary. The autouse isolation makes that unreachable from tests today, but the queue still has no lifecycle of its own.
- **L9 (noted, not changed):** an indented `#` comment is accepted in the vocabulary, because the comment test runs on the stripped line. Harmless — the extraction hook does not write indented comments — but it is a gap in the same shape rule M2 just tightened.
- **Live store untouched.** Nothing this round wrote to `~/personal-assistant/data`; both runs' guards were clean apart from the worktree's expected INERT banner.
