# Audit round 4g — style-analyser scripts — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4g`, branch
  `claude/audit-round4g`, at main. Sibling agents own `tests/conftest.py`,
  `tests/test_hermeticity_fixture.py`, `tests/test_glue_scripts.py`,
  `requirements.txt` (do NOT edit it — propose the change in your report), and
  every script outside `scripts/style-analyser/`. Round 4e (branch
  `claude/audit-round4e`, running) is changing ONLY the relative path-default
  constants and their CLI overrides in `phase3_promotion.py:38-39`,
  `phase3_guide_verifier.py:520-521`, `phase4_exemplar_scorer.py:27,249`, and
  `phase5_evaluator.py:109-111` — do NOT touch those lines; everything else in
  those files is yours. The two `agents/corpus-style-analyser*.md` documents
  are also round 4e's — do not edit them; report any claim they make that
  your fixes falsify.
- Lens reports: `lensA-8.md` (correctness, findings 1-33 → cite as ST1-ST33)
  and `lensB-8.md` (test adequacy, C1-C7, M1-M7, L1-L6, plus the minimum-suite
  specification → STT1-STT7, STT-M1.., STT-L1..) in this directory. Line
  numbers at 2a4b3bc.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit it.
- Scope: the fourteen scripts under `scripts/style-analyser/` and NEW test
  files under `tests/style_analyser/` (create the package with an `__init__.py`
  or use a flat `tests/test_style_*.py` naming — check how `pytest.ini`
  collects) with shared fixtures under `tests/fixtures/style/`.

## Absolute safety rules

Never read corpus text, exemplars, judge outputs, or responses under
`data/style-corpus/`, `data/experiments/`, or any Zotero storage; never open
`.env`; no network, LLM, or Ollama call (there are none in the tranche — keep
it so, and add a socket-refusing autouse fixture to each new test file
anyway); never write under `~/.claude`, `~/.cache`, or the repository's
`logs/`, `data/`, `reports/`, `wiki/`. Heavy dependencies (`numpy`, `scipy`,
`sklearn`, `spacy`) are NOT in the venv (STT7): do NOT install anything.
Tests for the four heavy modules use `pytest.importorskip` and are marked
`integration`; where a module's pure functions can be split from its numpy
use, test the pure half unconditionally. Eight modules import on stdlib —
test those fully.

## Must fix (Critical and Medium from both lenses)

Order: ST1+ST2, ST3, ST4+STT6, ST5, STT5 first, one commit each.

ST1 + ST2 (critical) — `efficacy_score_judges.py`: parse each judgement
through a tolerant reader (bare JSON, fenced, prose → a typed
`unusable` record, never an exception); require `choice ∈ {A, B}` — a tie,
refusal, or empty choice is `unusable` and counted separately, never as a
baseline win; a duplicated `pair_id` is an error; a missing pair is reported
as incomplete; an empty file is a diagnostic with non-zero exit; the topic
list comes from the mapping, not a hard-coded list (STT-M6); ST13: the two
orders of one pair are one paired observation — report n as pairs, add an
exact binomial or sign test with its p-value, and derive the provenance line
from the data. Tests for every shape.

ST3 (critical) — `efficacy_build_judge_tasks.py`: the mapping is written
OUTSIDE the judge directory (a sibling `judge-key/` the judge is never
pointed at), pair ids are assigned by a seeded shuffle with the seed
recorded in the key, the A/B order is randomised per pair (not alternating),
and byte-identical duplicate files are avoided (each unordered pair emitted
once with its order recorded in the key); STT-M5: refuse to `rmtree` a
directory containing `judgments.jsonl` unless `--force`. Tests: the key is
not under the judge root; no filename in the judge root carries a condition;
a second run with the same seed is identical; `rmtree` refused.

ST4 + STT6 (critical) — `phase3_guide_verifier.py`: the count-over-words
check compares the claimed number with the metric the claim names (map the
feature word to the aggregate key; unknown feature → FAIL "cannot verify");
wire `extract_per_1k_aggregates` so per-1k rate claims are checked; a claim
in a section not in `SECTION_TO_METRICS` is reported as UNVERIFIED and
counts as a failure for the exit code unless `--allow-unverified`; ST6 the
sub-cluster downgrade requires the claim itself to name a sub-cluster
(structured parse, not a keyword in a snippet); ST7 Zotero keys checked
only against the known key set (as check 6 does); STT-M1 the precedence bug
and the silent no-row case become explicit; STT-M2 deterministic ordering
(sorted, never `set` order); ST28 dead code and the unreachable allow-list
resolved. Tests: each check FAILs on its own defect and PASSes on a clean
claim; `PYTHONHASHSEED=0` and `=1` give identical bytes.

ST5 (critical) — `phase1_pipeline.py`: `hapax_ratio` over types as
documented (or rename it `hapax_per_token` everywhere it is consumed —
choose the documented definition and say what changes downstream); ST8
passive as presence per sentence (bounded 0..1) with the per-verb count
kept under a distinct name; ST9 nominalisation per 1k over the same
alphabetic token count as every other per-1k rate; ST15 the reference
header needs a heading marker or an exact short line, and `process_paper`
must not strip already-clean `body.md`; STT5 empty corpus is a diagnostic,
not a `StatisticsError`; ST19 NFC-normalise input; ST20 `mattr_100` below
the window returns `None` (or flags), never plain TTR silently; ST21
"exclude" matching only as a whole word / explicit flag; ST23 the documented
counts made true. Tests against the 8-sentence fixture in `lensB-8.md` with
its known counts, using an injected fake `nlp` (no spaCy).

STT5 also covers `phase3_promotion.py`: ST25 a length mismatch between
`paper_keys` and `per_paper_rates` is an error; ST26 always-positive
continuous metrics do not auto-promote via the presence rule (say what rule
applies instead); the five verdict boundaries pinned; `n_occ=0` rendered as
0.

ST10 — `efficacy_build_reference.py`: windows measured on citation-stripped
text so the length match holds; the `min-words` guard applied post-strip.
ST11/ST12 + STT3 — `phase5_evaluator.py`: the held-out sanity paper is
scored against a fit that excludes it; the sanity verdict is False when any
fixture is "not farther". ST27 — `efficacy_analyse.feature_profile` uses
only paired topics. STT-M4 — the experiment directory is created after the
guide is read. STT-M7 — the manifest lands inside `--output-dir`; `--keys`
on an EXCLUDED paper is refused without `--include-excluded`; and the
import-time `sys.exit` becomes a lazy import so the module is importable.
ST14 / STT2 — the two validators read `data/style-corpus/extracted/<key>/
body.md` (the current layout) with a `--corpus-dir` override, guard the
missing file, and exit non-zero when the sample is empty; document that
they are human-audit printers. ST16/ST17/ST18/ST22/ST24/ST31/ST32 and
STT-L1..L5 where cheap.

Every output write in the tranche: temp-file-then-rename, and `--dry-run` on
every writer (writes zero bytes; tests assert). Provenance (cross-file): each
output JSON gains a `provenance` block — script name, git commit if
available, spaCy model version when used, input file hashes, seed. Tests:
the block is present and the hashes match the fixtures.

Tests: implement the minimum-suite specification in `lensB-8.md` for the
eight stdlib-only modules in full, and the pure halves of the four heavy
modules; mark the numpy/spaCy-dependent tests `integration` with
`importorskip`. Every negative it lists.

## Record, do not change

STT7 (dependencies missing from the venv — propose the `requirements.txt`
addition and the `en_core_web_sm` pin in your report), ST30 (absolute
thresholds on short passages — propose), ST33 (documented sentence filter),
the provenance gap for judge model ids (generation happened outside these
scripts — say what field the generator should record), the two agent
documents (round 4e's).

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table, NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "the published hapax and passive figures change definition; the
guide's numbers must be re-derived", "the judge task layout changes; the
existing judgments.jsonl pairs no longer map").
