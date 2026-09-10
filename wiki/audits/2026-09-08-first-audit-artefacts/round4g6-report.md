# Round 4g-6 report (style-analyser scripts, PR #151 second round)

The fix agent's final report, copied verbatim from the session on 2026-09-10.
Every fixture named is synthetic.

---

Round 4g-6 complete. `origin/main` merged (clean, docs only), the critical closed, both mediums and all five lows done — two commits.

## Disposition

| Item | Disposition |
|---|---|
| **C1** (critical) check-then-reload | **fixed** — `efficacy_score.main` hands the loader an **explicit three-element literal list** (no comprehension), unpacks `phase1, phase3, reference_phase1` from its return, and feeds those payloads into `load_corpus_space`, whose signature now takes payloads rather than paths. `load_json` no longer appears anywhere in the module, so nothing re-reads a phase file after the check. `load_checked_payloads` keeps a `None` input in its position, which is what makes a fixed, unpackable list possible. Both named mutations now fail: `if p is not None` → `if p is None` (the list is asserted to be a literal of exactly the three `args.*` inputs) and `if problem:` → `if False:` (a new assertion requires an `if problem:` guard that returns non-zero). A second test pins that `load_json` is absent |
| **M1** deleted assertion | **fixed** — the phase-5 test asserts the loader's argument is a literal list whose `args.*` attributes are exactly `{phase1, phase3}`, plus the same guard check. `[args.phase1, args.phase1]` now fails |
| **M2** value comparison | **fixed** — derivation is checked **structurally** for all nine constants across the six scripts: each assignment's value must call one of `style_support`'s layout helpers. Reverting `efficacy_build_prompts.py` to its literal path now fails; comparing values could not see it, since the literal spells the same path |
| **Low** dead `EXP`/`PASSAGES` | **fixed** — removed from `efficacy_build_judge_tasks`; no test referenced them once M2's rewrite replaced the value comparison |
| **Low** unused `REPO_ROOT` | **fixed** — removed from `efficacy_build_reference` |
| **Low** last layout literal | **fixed** — `efficacy_score`'s `args.experiment_dir / "passages"` is now `style_support.passages_dir(args.experiment_dir)` |
| **Low** doc example | **fixed** — the agent document shows a complete command with `--manifest`, `--output-dir` and `--keys`. A doc-to-code test recovers the parser's options from `main`'s own `add_argument` calls (no `argparse` monkeypatching — patching that module's own name makes its `super()` lookup recurse) and asserts the example uses only flags that exist and includes every required one; a second test asserts the document names the marker filenames the code writes. The pre-fix example now fails both |
| **Low** newer-stamp wording | **fixed** — a `metric_schema` newer than the code now reads "The results are NEWER than the code reading them… Update the code (git pull) rather than re-running phase 1", instead of telling the operator their current results were superseded |

Every mutation was applied singly, confirmed to fail its test, and reverted with a pristine diff.

## Suite (clean `git archive HEAD` copy, `HOME` pinned, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`)

`4489 passed, 3 skipped, 19 deselected, 34 subtests passed in 163.98s (0:02:43)` — exit code **0**. Strict mode reports the store half inert in an export, as expected; the 3 skips are the two `importorskip("numpy")` phase-5 helpers and the codex tripwire.

```
f53f10e fix(style-analyser): check derivation structurally, fix the example
46a93b9 fix(style-analyser): score from the checked payloads
62ba76e Merge remote-tracking branch 'origin/main' into claude/audit-round4g-5
7f146ad Merge remote-tracking branch 'origin/main' into claude/audit-round4g-5
3fd442f feat(style-analyser): make the bundle markers consumable
b9d2160 fix(style-analyser): report a caller with no file
f8cca77 refactor(style-analyser): derive one experiment root everywhere
9590d40 test(style-analyser): cover the other failure path and the marker text
52d5bcd test(style-analyser): run the builder at its own defaults
4d5d314 fix(style-analyser): make the stamp check a runtime guarantee
```

Working tree clean, **0 behind main**, nothing pushed, one clean copy made and removed, all temp directories gone.

## Live-behaviour risks

1. **`efficacy_score`'s internals changed shape.** `load_corpus_space` now takes payloads and returns `(fs, X, loo, nlp)` rather than paths and a seven-tuple. Nothing else in the tranche calls it, but any外部 caller or notebook would break — worth a grep before merge if one exists outside this repository.
2. **A newer-than-code results file now gets different advice.** If phase 1 is ever bumped past version 2 and an older checkout reads it, the message says to update the code, not to re-run phase 1. That is the correct instruction, but it reverses what an operator would have been told yesterday.
3. **`extract_corpus` still warns at the start of every run** when leftover markers exist, and the agent document now instructs the analyser to skip those bundles — so a corpus with markers will silently shrink the paper set unless they are cleared first. The run reports which keys it skipped.
4. **The doc-to-code test binds the document to the parser.** Renaming a flag in `extract_corpus.main`, or a marker filename, now fails the suite until `agents/corpus-style-analyser-v2.md` follows. That is deliberate, and it is the only test in the tranche that can fail because of a documentation edit.

## Operator consequence, restated

**Every phase-1 consumer still refuses the live `phase1-results-clean.json` until phase 1 is re-run.** All six — `phase3_promotion`, `phase3_guide_verifier`, `phase5_evaluator`, `efficacy_build_reference`, `efficacy_score`, `validate_announce_colon` — exit **2** on a results file whose `metric_schema` is missing or below version 2, and the live file has no stamp. The order is `phase1_pipeline.py --clean-corpus`, then `phase3_promotion.py`, then everything downstream. Until that happens the refusals are the interlock working: four metrics changed meaning under names that stayed the same, and this is what stops a new-definition input being scored against an old-definition corpus. As of this round, `efficacy_score` genuinely scores the bytes it checked — previously it checked one copy of those files and scored a second read of them.
