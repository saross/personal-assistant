# Audit round 4e — bake-off and style tooling — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4e`, branch
  `claude/audit-round4e`, at main. Sibling agents own `tests/conftest.py`,
  `tests/test_hermeticity_fixture.py`, `tests/test_glue_scripts.py`, the
  daily sync, the memory-store writers, the retrieval scripts, the archive
  pipeline, and the external-services scripts — do NOT edit any of those.
- Lens reports: `lensA-6.md` (correctness, findings 1-25 → cite as AS1-AS25)
  and `lensB-6.md` (test adequacy, findings 1-14 and a minimum-suite
  specification → AST1-AST14) in this directory. Line numbers at 0d5fc39.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit it.
- Scope: `scripts/bake-off-metadata.py`, `scripts/resample-bake-off-manifest.py`,
  `scripts/analyse-wiki-vocabulary.py`, `agents/corpus-style-analyser.md`,
  `agents/corpus-style-analyser-v2.md`, the four path defaults named in AS14
  under `scripts/style-analyser/` (ONLY the path defaults — the rest of that
  directory is a later tranche), and NEW test files
  `tests/test_bake_off_metadata.py`, `tests/test_resample_bake_off_manifest.py`,
  `tests/test_analyse_wiki_vocabulary.py`, with shared fixtures under
  `tests/fixtures/` (currently empty).

## Absolute safety rules for this tranche

Never read transcript or response contents under `data/experiments/`,
`~/cc-archives/`, or `~/.claude/projects/` (the worktree's `data/` is empty
anyway — do not reach into `~/personal-assistant/data`). Never open `.env`.
No LLM, OpenAI, Gemini, Anthropic, Ollama, or HTTP call may execute — stub
`anthropic.Anthropic`, `google.genai.Client`, `urllib.request.urlopen`, and
`resolve_openai_key` at the boundary and assert the stub was or was not
called; add a socket-refusing autouse fixture to each new test file. Never
write under `~/.claude`, `~/.cache`, the repository's `logs/`, `data/`,
`reports/`, `wiki/`, or `notes/` — every output path in a test is a tmp dir.

## Must fix

Order: AS1, AS4, AST2 (the dedup inversion), AS7, AS6 first, one commit each.

AS1 (critical) — `bake-off-metadata.py:1126`: `--build-rubric` must REFUSE
(exit 2, message) when the template does not contain exactly the two markers
as a pair (allow blank lines and CRLF between them by matching with a regex),
and must never write the blind key when the body was not populated. Test:
already-populated rubric → refusal, nothing written; blank line between
markers → populated correctly; CRLF template → populated.

AS4 + AST3 (critical) — `resample-bake-off-manifest.py`: add argparse with
`--out` (required unless `--dry-run`), `--dry-run` (prints the plan, writes
nothing), `--seed` (default 42, recorded), `--archive-root`/`--live-root`
(defaults from `Path.home()`), and make `PA_DIR` `__file__`-derived; the
write is temp+replace and REFUSES to overwrite an existing manifest unless
`--force`. Entry-point tests through `main()`.

AST2 (critical) — `resample-bake-off-manifest.py:550-564`: prefer the
ARCHIVED copy when a session is resident in both pools (the comment's
stated intent); test with a dual-resident session (this test fails today).

AS7 (medium, policy) — `bake-off-metadata.py:1263-1278`: the live prompt
must present the model id, batch versus real-time, the request count, and
the estimated cost (the same figures the dry run prints) before `input()`;
`--yes` prints them and proceeds; stdin closed → clean refusal, not an
`EOFError` traceback (AST12). AS8: `--haiku-apply` is free — no prompt, but
print what it retrieves and say in the header that retrieval is ungated.
Tests: the negative (stdin "no" → nothing called, exit 0) and the positive.

AS6 — `custom_id` carries the full session id (or a hash of it); test two
ids sharing an 8-char prefix. AS2 — every discovered arm appears (no
truncation) and the blinding is a seeded full permutation per session (not
reverse-only); test with five arms and assert byte-identical keys across
runs. AS3 — raise the Sonnet constants to 3.00/15.00 as the comment
instructs and rewrite the comment with the new review date. AS9 — every
response write is temp+replace; a complete `{sid}.json` is never overwritten
by an `{"error": …}` and a re-run skips already-complete responses unless
`--force`; `_usage.json` is merged, not replaced. Tests with crash injection.
AS24 / AST6 — empty manifest → clean exit with a message (nothing written).
AS5 — `generated_at` stays, but reproducibility is total: `--as-of` (or a
frozen clock in tests) makes two runs byte-identical; test. AST7 / AS20 — an
under-filled stratum prints a shortfall line naming the bin and counts.
AS15 — shebang and the printed recovery hint use `venv/bin/python`. AS10 /
AST10 — `analyse-wiki-vocabulary.py` tolerates an empty or undated corpus
and non-string tags with a diagnostic; AS23 NFC-normalise and strip
consistently. AST1 — the analyser writes nothing anywhere (tree snapshot
test). AS14 — the four `scripts/style-analyser/` path defaults become
`__file__`-derived with a CLI override (only that change in those files).

Documents: AS11 (Safeguard 5 says §11), AS12 (21.45 and 1.605 from the
JSON, with the file path cited), AS13 (point Steps 1-2 at
`data/style-corpus/corpus-manifest.json` and say how to regenerate the tmp
extract), AS17/AS18/AS19/AS21/AS22 (docstring and definition counts and
vocabularies made true), the v2 reconciliation contradiction (pick the
Phase 4 rule and fix the template).

Tests: implement the minimum-suite specification in `lensB-6.md` for all
three scripts, including every negative it lists, with the shared fixtures
it describes.

## Record, do not change

AS16 (chars/4 token heuristic), AS25 (the committed manifest predates the
writer), the provenance gap (no model or prompt hash beside responses —
propose the fields in your report), `LAUNCH-PLAN.md:194` (in the private
submodule; note the claim needs correcting), and the untouched remainder of
`scripts/style-analyser/`.

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table, NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "the resampler now requires `--out`", "the rubric builder refuses a
populated template").
