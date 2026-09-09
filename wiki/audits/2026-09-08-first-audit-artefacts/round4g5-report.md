# Round 4g-5 report (style-analyser scripts, follow-ups after PR #144)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

## Correction first

My round 4g-4 report claimed that reverting `efficacy_score_judges.py:66` `KEY_DIR_DEFAULT` "fails the constant test AND both round trips". **That was wrong.** The re-auditor is right, and I have re-run both mutations to confirm the corrected claim:

- **Reverting the constant alone** (`KEY_DIR_DEFAULT = EXP / "judge-key"`) fails **only** `test_the_scorer_looks_where_the_builder_writes`. The round trips read the argparse default, not the constant.
- **Reverting only the scorer's argparse default** (`:408-409`) fails **both round trips** and **not** the constant test.

What produced the wrong claim: I applied both edits in one mutation script and reported the combined result as if it were the constant's. The lesson I should have applied — and now have, throughout this round — is to mutate exactly one line and record which tests fall.

## Disposition

| Item | Disposition |
|---|---|
| **M-a1** position was a proxy | **fixed, option (a)** — `style_support.load_checked_payloads(paths)` loads every phase file and returns **no payloads at all** on any failure, so a caller holding payloads is holding checked ones by construction. Both mains call it as their first statement after argparse and take phase1/phase3 (and the optional reference) from it; it subsumes the old existence checks. Six behavioural tests run here without numpy, including `test_one_stale_file_withholds_every_payload`; the AST assertions are now minimal (called exactly once, given every phase input, before any consumer). All four named defeats are structurally impossible: there is no loop to hoist, condition, or empty |
| **M-b1** builder defaults unguarded | **fixed** — the build round trip calls `builder.main` with only its *inputs* (`--extracted-dir`, `--seed`), leaving judge dir, key dir **and** passages dir at their defaults, and reads the key back from wherever the builder put it. Reverting `efficacy_build_judge_tasks.py:303-308` now fails it, printing the wrong location. spaCy stubbed; topics, contrasts and reference key invented |
| **Survivor** — exception failure path | **fixed** — `test_a_crashing_extractor_leaves_only_the_error_marker` drives an extractor that raises; neutering the unlink on that return now fails |
| **Survivor** — marker content | **fixed** — the interruption test asserts the marker names the key and says to re-run; an empty body now fails |
| **L-b2** "one base" was judge-only | **fixed (full derivation, not a narrowed docstring)** — `passages_dir()` added, and all six scripts derive the root from `style_support`. Tests assert each script's constant equals `experiment_root()` (`efficacy_score`'s read from source, since it imports numpy) and that repointing the base moves judge, key and passages together |
| **L-b3** dead `EXP` | **fixed** — removed, along with the three `REPO_ROOT` constants the change left unused |
| **L-c1** `_calling_script() is None` fell back | **fixed** — records no commit and a note naming the reason; tested by calling `provenance_block` from `exec`'d source. Restoring the fallback fails it |
| **L-c2** vacuous in an export | **fixed** — the test builds its own throwaway repository and asserts both halves, so `script_path` is shown to do the work |
| **L-d1** nothing consumed the markers | **fixed** — `extract_corpus` scans the output tree before starting and warns, naming keys and marker; silent on a clean tree. The agent document now tells its reader to skip or re-extract any paper carrying either marker, what each means, and to report which keys were skipped |
| **L-e1** docstring indentation | **fixed** — the `script_path` paragraph is back inside `provenance_block`'s docstring |

Every fix was mutated one line at a time, confirmed to fail the new test, and the file restored and diffed pristine.

## Suite (clean `git archive HEAD` copy, `HOME` pinned, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`)

`4387 passed, 3 skipped, 19 deselected, 34 subtests passed in 197.95s (0:03:17)` — exit code **0**. Strict mode reports the store half inert in an export, as expected. The 3 skips are the two `importorskip("numpy")` phase-5 helpers and the codex tripwire.

```
3fd442f feat(style-analyser): make the bundle markers consumable
b9d2160 fix(style-analyser): report a caller with no file
f8cca77 refactor(style-analyser): derive one experiment root everywhere
9590d40 test(style-analyser): cover the other failure path and the marker text
52d5bcd test(style-analyser): run the builder at its own defaults
4d5d314 fix(style-analyser): make the stamp check a runtime guarantee
```

Working tree clean, nothing pushed, one clean copy made and removed, all temp directories gone. Branch is 14 commits behind `main`.

## Live-behaviour risks

1. **Unchanged headline: every phase-1 consumer refuses the live results file until phase 1 is re-run** (`phase1_pipeline.py --clean-corpus` → `phase3_promotion.py` → downstream). The refusal message now comes from the checked loader and reads slightly differently, and a *missing* file now reports `Input not found:` rather than `Phase 1 input not found:`.
2. **`--validate` and the scorer stop earlier on a bad input.** Both now refuse before spaCy is loaded or a corpus matrix is built, so failures are faster and quieter — but any wrapper matching the old message strings needs updating.
3. **`extract_corpus` prints a warning block at the start of every run** when leftover markers exist. On the live tree this may name papers from earlier interrupted runs; that is information, not a new failure, and the run continues.
4. **The agent now skips marked bundles** — if the live extraction carries leftover markers, the next style-guide run will exclude those papers and say so. Clear or re-extract them first if a full 18-paper corpus is wanted.
5. **Provenance blocks for scripts run via `python -c` or `exec` now record no commit** plus a note, where they previously recorded `style_support`'s commit. Nothing in the pipeline runs that way today.
