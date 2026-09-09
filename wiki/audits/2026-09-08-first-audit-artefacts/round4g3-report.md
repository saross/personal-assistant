# Round 4g-3 report (style-analyser scripts, PR #128, third round)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4g-3 complete. All seven actionable items closed, one commit each, suite green from a clean copy.

## Disposition

| Item | Disposition |
|---|---|
| **1** (blocking) key location mismatch | **fixed** — `efficacy_score_judges.py:66` `KEY_DIR_DEFAULT = EXP / "private" / "judge-key"`, plus the module docstring (`:6`) and the fallback comment (`:282`); `grep private` is now 4, was 0. Exercised, not just asserted: `test_a_built_experiment_scores_at_the_defaults` (build → answer → `main([])` → exit 0) and `test_a_migrated_legacy_key_scores_at_the_defaults` (migrate → `main([])` → exit 0), with `test_the_scorer_looks_where_the_builder_writes` pinning `scorer.KEY_DIR_DEFAULT == builder.KEY_DIR` so a future divergence fails on the constant too |
| **2** sixth phase-1 consumer | **fixed** — `validate_announce_colon.py` checks `metric_schema` before reading rates; the tests' fixture builder stamps by default and takes `stamped=False` for the refusal case, so the gap cannot reopen the next time a test adds a results file. `test_an_unstamped_results_file_is_refused` (exit 2, no "corrected" line) and `test_a_stamped_results_file_is_still_scored` |
| **3** `--migrate-key` isolation | **fixed (test)** — `test_migrate_key_does_nothing_but_migrate` asserts exit 0 **and** byte-identical judge-directory contents. Mutation (deleting the `return`) applied to a scratch copy, confirmed to fail, file restored and diffed pristine |
| **4** phase 3 stamp unchecked | **fixed** — `phase5_evaluator` checks phase1 and phase3 in one loop; `efficacy_score` adds `args.phase3` to its candidates. Both import numpy at module scope, so the tests read the source and assert which `args.<name>` attributes reach a `metric_schema_error` call — stated in the docstrings as the stdlib-reachable half |
| **6** version-less stamp | **fixed (test)** — `test_a_stamp_without_a_version_is_refused`; mutation `stamp.get("version", METRIC_SCHEMA_VERSION)` confirmed to fail it, restored pristine |
| **7** untracked files and `dirty` | **fixed (test)** — `test_an_untracked_file_does_not_make_the_tree_dirty`; dropping `--untracked-files=no` confirmed to fail it, restored pristine |
| **8** error marker cleared too early | **fixed** — the `unlink` moved below `body.md`/`references.md`/`full.md`/`metadata.json`/`qa.json`, so the marker goes only once the outputs that supersede it exist. `test_an_interrupted_bundle_leaves_the_error_marker_in_place` fails the last write and asserts the marker survives; the old ordering was reinstated in a scratch copy and confirmed to fail it |
| **5** (record) | **recorded, unchanged** — see below |

## Item 5, recorded

numpy, scipy, scikit-learn and spaCy are absent from this venv, so **three of the six interlock consumers never execute their stamp check here** (`phase5_evaluator`, `efficacy_score`, `efficacy_build_reference` — all reachable only through modules that import numpy at module scope), and **every phase-5 item test from rounds 4g-2 and 4g-3 is integration-marked and deselected**. What runs here is the pure half: `style_support.metric_schema_error` itself, the two stdlib consumers (`phase3_promotion`, `phase3_guide_verifier`), the sixth (`validate_announce_colon`, added this round), and source-level assertions about what the numpy-bound `main`s check. **The requirements proposal stands**: add `numpy>=1.26`, `scipy>=1.11`, `scikit-learn>=1.4`, `spacy>=3.8,<3.9` and the `en_core_web_sm==3.8.0` pin, and 22 currently-deselected tests start running.

## Suite (clean `git archive HEAD` copy, `HOME` pinned, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`)

`4009 passed, 3 skipped, 19 deselected, 34 subtests passed in 160.03s (0:02:40)` — exit code **0**.

Strict mode is live and reports the expected inertia:

> `PA_HERMETICITY_STRICT=1, but the canonical store is not present here … The store half of the hermeticity guard is INERT in this run — an archive export has no data/ submodule … Only the source-tree half is strict.`

The 3 skips: two are my `importorskip("numpy")` phase-5 helpers, one is the pre-existing codex tripwire ("no checkout to calibrate against").

```
33a5159 fix(style-analyser): clear the error marker after the writes
aa9ea96 test(style-analyser): pin what makes a tree dirty
da94737 test(style-analyser): pin the version-less stamp refusal
afa5761 fix(style-analyser): check phase 3's stamp as well
d3a80bf test(style-analyser): pin that --migrate-key only migrates
ccc2a9a fix(style-analyser): check the stamp in the sixth consumer
916e223 fix(style-analyser): score where the key is now written
1f763e2 Merge branch 'main' into claude/audit-round4g
… 38 commits ahead of main in total (the 4g, 4g-2 and 4g-3 work)
```

Working tree clean, nothing pushed, one clean copy made and removed, all temp directories gone (`/tmp` at 60% inodes). The branch is **73 commits behind main** — other rounds have landed since; re-merge before review.

## Operator consequence, restated

**Every phase-1 consumer now refuses the live results file until phase 1 is re-run.** Six scripts — `phase3_promotion`, `phase3_guide_verifier`, `phase5_evaluator`, `efficacy_build_reference`, `efficacy_score`, and as of this round `validate_announce_colon` — exit **2** on a `phase1-results-clean.json` whose `metric_schema` is missing or below version 2, and the live file is unstamped and pre-fix. The order is: `phase1_pipeline.py --clean-corpus`, then `phase3_promotion.py`, then everything downstream. Until that happens the refusals are the interlock working, not a regression: four metrics changed meaning under names that stayed the same, and this is what stops a new-definition input being scored against an old-definition corpus.
