# Lens A (correctness) — tranche 6: bake-off and style tooling — HEAD 0d5fc39

## Critical
1. bake-off-metadata.py:1126 — `template.replace("<!--BEGIN-SESSIONS-->\n<!--END-SESSIONS-->", …)` is a no-op on an already-populated rubric (or any separation between markers), but the blinding key at :1136 is regenerated from the current filesystem regardless: after adding a provider arm and re-running, the body still shows the old arms under A-D while the key claims a new mapping — every blinded score decodes to the wrong model; "Wrote populated rubric" printed either way. CONFIRMED.

## Medium
2. bake-off-metadata.py:1054 — zip(("A","B","C","D"), order) truncates to four arms while --provider offers six; a fifth arm vanishes from rubric AND key. Also the "flip" is order.reverse() only: letter A is always one of two providers (weaker than the comment at 1043-1050 claims). CONFIRMED.
3. bake-off-metadata.py:112-113 — SONNET prices 2.00/10.00 with a comment (106-110) saying they go stale on 1 Sep 2026 and must become 3.00/15.00; today is 8 Sep. Estimates under-count by 33 %. CONFIRMED.
4. resample-bake-off-manifest.py:52 — PA_DIR hardcoded absolute; MANIFEST_PATH (54-57) points at the live private submodule from any copy or cwd; no argparse, no --out/--seed/--dry-run; :518 write_text unconditional, non-atomic. Running a copy destroys the manifest the committed 2026-05-18 responses were generated against. CONFIRMED.
5. resample-bake-off-manifest.py:470 (+ :487 notes) — generated_at from now(): same seed and pool do not reproduce byte for byte (picks identical). CONFIRMED.
6. bake-off-metadata.py:293 — custom_id = f"sess-{session_id[:8]}"; haiku_submit:472 builds {custom_id: session_id} which collapses duplicates; realistic because resample:277 sets session_id = p.stem for sub-agent transcripts (long shared prefixes). One session's output written under another's id. CONFIRMED.
7. bake-off-metadata.py:1263-1278 — the live prompt names no model id, count, batch-vs-real-time, or cost (estimate printed only on --dry-run); --yes skips even that. Violates the API Call Review Gate. CONFIRMED.
8. bake-off-metadata.py:1251 — --haiku-apply reaches batches.retrieve/results before the confirmation block with no prompt (free, but LAUNCH-PLAN.md:194 asserts every live command prompts). CONFIRMED.
9. bake-off-metadata.py:668, 826, 922, 838, 932 — every response write is a bare write_text; a re-run overwrites a complete {sid}.json with {"error": …} on failure; _usage.json replaced wholesale; no already-present skip. CONFIRMED.
10. analyse-wiki-vocabulary.py:191, 196, 149 — max/min(valid_dates) ValueError on an empty or undated corpus; counter[tag.lower().strip()] AttributeError on a non-string tag; /weekly-review step 5b aborts. CONFIRMED.
11. agents/corpus-style-analyser-v2.md:657 — Safeguard 5 says aspirational lives in §9 only, but the v2.2 layout (380-393) puts it at §11 (§9 = voice-tic cross-reference). CONFIRMED.
12. agents/corpus-style-analyser-v2.md:765-767 — "21.16 is the correct value" contradicts the file's own Appendix E (~442, 21.45) and data/style-corpus/phase1-results-clean.json aggregate.sentence_stats.mean = 21.45; :770 "1.884 → 1.295" contradicts the file's 1.605 and the JSON. CONFIRMED.
13. agents/corpus-style-analyser-v2.md:574, 581, 620 — Steps 1-2 require /tmp/style-corpus-extract/manifest.json (tmpfs, wiped on reboot, no regeneration instructions); a durable equivalent exists at data/style-corpus/corpus-manifest.json and is not pointed to. CONFIRMED.
14. scripts/style-analyser/phase3_promotion.py:38-39, 370 — PHASE1/OUT are RELATIVE `data/style-corpus/…` with no override; same in phase4_exemplar_scorer.py:27,249 and defaults in phase3_guide_verifier.py:520-521, phase5_evaluator.py:109-111; the documented invocations (v2 585-612) give absolute script paths and no cd. Run from another cwd, Step 3 fails or writes into the wrong tree. CONFIRMED (read).
15. bake-off-metadata.py:1 + :482 — shebang /usr/bin/env python3 and the printed recovery hint use system python3, which lacks cc_session_toolkit (extract-transcript-text.py:41 imports it unconditionally), anthropic, google.genai; only venv/bin/python works. CONFIRMED.

## Low
16. bake-off-metadata.py:322, 367 — len(user_message)//4 assumes ASCII; Greek/Cyrillic run 1-2 tokens/char; recorded as authoritative in the manifest. SUSPECTED.
17. bake-off-metadata.py:3-8, 71 — docstring says two arms (Haiku 4.5 vs Gemini 3.5 Flash); GEMINI_MODEL = gemini-3.6-flash; six arms exist. CONFIRMED.
18. bake-off-metadata.py:703, 766 — docstring claims thinking_budget=0 symmetry (it sets thinking_level: minimal at :597) and that the tier actually used is reported (nothing records the flex→default fallback). CONFIRMED.
19. resample:17-18 vs :61 — docstring floor 100 tokens, MIN_TOKENS = 1000. CONFIRMED.
20. resample:427 — under-filled stratum silent (WARNING at 384 only when empty). CONFIRMED.
21. agents/corpus-style-analyser.md:30 vs :191 — status vocabulary …/aspirational vs …/derived-by-inference. CONFIRMED.
22. v2.md:13, 516, 473, 639, 663 — "fifth status" but six listed (36-38); "Five scripts" but phase4_exemplar_scorer.py named at 823 and 14 .py files exist; "§§1-8" three times after the relayout. CONFIRMED.
23. analyse-wiki-vocabulary.py:149, 159 — no NFC normalisation; wiki_tag_support omits .strip(). SUSPECTED.
24. bake-off-metadata.py:978 — requests[0] IndexError on an empty manifest. CONFIRMED.
25. data/experiments/bake-off-metadata-2026-05-18/sample-manifest.json generated_at is a bare date "2026-05-17" while the writer emits a tz-aware datetime: the committed manifest was not produced by the committed script. CONFIRMED (keys only).

## Cross-file
- v1 vs v2 agent definitions disagree on section count (§§1-8 vs §§1-11), status vocabulary (4 vs 6), pipeline (v1 no scripts, pdftotext; v2 deprecates that); v2 self-inconsistent on reconciliation (Phase 4 ~301 "superseded; do not cite" vs claim template ~507 "awaits reconciliation").
- Response ↔ manifest provenance one-directional and breakable: no model id, prompt hash, or manifest hash recorded next to responses; the manifest can be regenerated in place; nothing links responses-2026-07-28/ to the manifest that produced it.

## Verified correct
No public-tree leakage (all outputs under data/experiments; notes/reports/logs are symlinks into data); nothing writes memories.jsonl or tag-vocabulary.txt; no network/LLM/Ollama under scripts/style-analyser/; no session sampled twice (bins partition Scored); haiku_submit's printed --out-dir matches haiku_apply; marker pairs cannot collide; blind_key.pop order fine; no US spellings.

## Answers
1. External calls all in bake-off-metadata.py: batches.create (457), .retrieve (498), .results (511); messages.create (900: claude-haiku-4-5-20251001 / claude-sonnet-5); genai generate_content (570, gemini-3.6-flash); urllib POST api.openai.com/v1/responses (752, gpt-5.6-luna / gpt-5.6-terra). All billed paths behind the input() at 1263 (names nothing; --yes skips); --haiku-apply (1251) ungated. resample, analyse-wiki-vocabulary, scripts/style-analyser/: zero external calls.
2. Not reproducible: seed fixed (42) and recorded, sampling deterministic, but generated_at breaks byte-identity, the pool is never hashed, no model/prompt/manifest hash in the response tree.
3. No output lands in the public tree; stdout residual: dry_run_report prints the first 400 chars of request 1 (~150 chars of transcript).
4. analyse-wiki-vocabulary reads only data/memories/memories.jsonl, writes stdout only — safe any time; crashes on empty/undated corpus or non-string tag.
5. The definitions partly disagree (cross-file) and disagree with the scripts they name.
6. __file__-derived: bake-off:151 (PA_DIR for .env), :64, :180; analyse-wiki-vocabulary:53. The dangerous ones are NOT: resample:52 hardcoded absolute; style-analyser phase3/phase4/phase5 RELATIVE paths (cwd-dependent).
7. Nothing here writes memories.jsonl or tag-vocabulary.txt.
NOTE for the coordinator: scripts/style-analyser/ holds 14 .py files that no tranche has audited (only their path defaults were noticed here).
