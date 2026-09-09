# Round 4g-4 report (style-analyser scripts, follow-ups after PR #128)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4g-4 complete — four commits, one per item, all mutations confirmed to fail before and pass after.

## Disposition

| Item | Disposition |
|---|---|
| **M1** stamp checks pinned by membership, not position | **fixed (tests)** — both assertions now name the calls that *consume* a phase-1/phase-3 payload (`build_validation_report`, `resolve_feature_space`, `build_corpus_matrix`, `evaluate_text`, `build_gate`; and `load_corpus_space`, `evaluate_text`, `evaluation_to_dict`) and assert the stamp loop's line precedes the earliest of them. Both named moves were reapplied and now fail: phase 5's below the validate `return` fails `test_the_stamp_check_runs_before_anything_consumes_the_corpus`; the scorer's below `load_corpus_space` fails two tests. Restored pristine |
| **L2** round trips patched both constants | **fixed** — the layout moved into `style_support` (`experiment_root`, `judge_dir`, `private_dir`, `judge_key_dir`); both scripts derive their constants *and* their argparse defaults from it at call time, and the tests repoint the **one shared base**. With `KEY_DIR_DEFAULT` reverted to `EXP / "judge-key"`, all three tests now fail — the constant test *and* both round trips (previously only the constant test). **Correction to my round 4g-3 report: the claim "exercised, not just asserted" was wrong.** The round trips were passing because the fixture handed the writer and the reader the same answer; they exercise the agreement only as of this commit |
| **L3** provenance always described `style_support.py` | **fixed** — `provenance_block` takes `script_path`, defaulting to the caller's `__file__` inferred from the calling frame, so the "must be tracked" branch is now reachable for every caller. A brand-new uncommitted script records no commit and a "not tracked" note; once committed it records its own HEAD. Tested by running a throwaway script inside a throwaway repository, untracked then tracked. Mutation (bare `git_state()`) confirmed to fail both new tests |
| **L4** per-file atomicity, no bundle marker | **fixed** — `extraction-incomplete.txt` is written atomically before any output and removed after the last, so an interruption anywhere between leaves evidence. The two deliberate failure returns remove it as they write `extraction-error.txt` (one marker, not two), and `--dry-run` writes nothing. Four tests, including the named case: crash after `body.md`, before `qa.json`, with no prior failure. Mutation (dropping the start-of-run write) confirmed to fail it |
| **L5, L6** | noted, no change — the worktree's `data/` submodule is unpopulated so the store half of the guard is inert there (the run says so, quoted below), and round reports live on `main` by design |

## Suite (clean `git archive HEAD` copy, `HOME` pinned, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`)

`4282 passed, 3 skipped, 19 deselected, 34 subtests passed in 161.28s (0:02:41)` — exit code **0**.

Strict mode reports its own limits, as expected in an export:

> `PA_HERMETICITY_STRICT=1, but these watched store paths are missing or dangling here … The store half of the hermeticity guard is INERT in this run; only the source-tree half is strict.`

The 3 skips are unchanged: two `importorskip("numpy")` phase-5 helpers and the pre-existing codex tripwire.

```
2a9034e fix(style-analyser): leave evidence of a partial bundle
af6a360 fix(style-analyser): record the calling script's commit
0037ed2 refactor(style-analyser): describe the judge layout once
325d5a1 test(style-analyser): pin the stamp check's position
```

Working tree clean, nothing pushed, one clean copy made and removed, all temp directories gone. Branch is 22 commits behind `main`.

## Live-behaviour risks

1. **Unchanged and still the headline: every phase-1 consumer refuses the live results file until phase 1 is re-run.** All six exit 2 on a `phase1-results-clean.json` with no `metric_schema`, and the live file has none. Order: `phase1_pipeline.py --clean-corpus`, then `phase3_promotion.py`, then everything downstream.
2. **Provenance blocks change content** (L3): they now describe the *calling script's* repository state. Expect `git_commit: null` with a `git_note` for any script that is new or not yet committed — that is the guard becoming reachable, not a failure, but it will look different in the first outputs after merge.
3. **A new file appears in extraction output directories** (L4): `extraction-incomplete.txt` during a run, removed on completion. Any QA sweep or rsync filter over `data/style-corpus/extracted/` should learn the name — and if one is found after a run, the bundle beside it is genuinely partial and that key should be re-extracted.
4. **`--key-dir` and `--judge-dir` defaults are computed at call time** from `style_support.EXPERIMENT_DEFAULT` (L2). Behaviour at the defaults is identical; anything that imported `builder.KEY_DIR` expecting an import-time constant still gets one, but the argparse default no longer follows a patched module constant — only a patched shared base.
