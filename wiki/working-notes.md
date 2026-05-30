---
title: "Personal-Assistant — Working Notes"
tags: [index]
created: 2026-05-18
updated: 2026-05-18
status: seed
---

# Personal-Assistant Working Notes

Chronological lab notebook for the personal-assistant project. Empirical
observations from sessions: measurements, confirmed behaviours, surprises
that change how we'd approach similar work. Distinct from `continuity.md`
(state) and `reflections/` (meta-observations).

Format: dated entries with pithy headlines. Capture the *measurement* or
the *principle*, not the recounting.

---

## 2026-05-18: Gemini 3 Flash needs `thinking_budget=0` for structured-JSON generation

Gemini 3 Flash Preview is a reasoning model. With default thinking enabled,
thinking tokens consume the output budget before any visible JSON is
emitted. First bake-off round (10 sessions, `max_output_tokens=1024`,
default thinking) produced **0/10 parseable JSONs** — every response was
truncated mid-`purpose` field at consistent positions (~100 chars of
visible output).

Fix: set `config={"thinking_config": {"thinking_budget": 0}}` in the
`generate_content` call. Validation: re-ran same 10 sessions, same budget,
got **10/10 successes** with substantive output.

Also gives apples-to-apples comparison with Haiku (which has no thinking
mode), so it's the right choice for the auto-metadata pipeline regardless.

Anchored at: `scripts/bake-off-metadata.py` `gemini_call_once()`; bake-off
artefacts in `data/experiments/bake-off-metadata-2026-05-18/`
(`responses-gemini-baseline/` = thinking-on failures;
`responses-gemini-tuned-v1/` and later = thinking-off successes).

## 2026-05-18: Haiku Batch produces conversational text on long transcripts when instructions are in the user message

Failure mode discovered during 2026-05-18 bake-off round 2: on 5 of 10
sessions, Haiku 4.5 returned regular conversational text instead of the
required JSON — *"I saw the caveat. No response needed — just standing
by if you need anything else for the training materials. All files are
now aligned: ✓ run-sheet-basic-training-condensed.md…"*. The model
treated `[assistant]` markers in the distilled transcript as chat turns
and continued the conversation.

Root cause: structural. Instructions came before the transcript in a
single user message; after 100K+ tokens of transcript ending in an
`[assistant]` block, recency made the conversation-continuation reading
dominant.

Fix (validated): three changes in concert —

1. Move instructions to `system=` parameter (separate context layer).
2. Wrap the distilled transcript in `<transcript>…</transcript>` tags.
3. Replace `[user]` / `[assistant]` markers with neutral dividers like
   `--- User ---` / `--- Assistant ---`.
4. Put an output-format reminder *after* the closing transcript tag, so
   the last thing the model sees is "begin with `{`".

Validation: bake-off round 4 with redesigned prompt: **0/10 conversational
failures** (versus 5/10 in round 2). Effect replicated across both Haiku
and Gemini.

Anchored at: `scripts/extract-transcript-text.py` (the new dividers);
`scripts/bake-off-metadata.py` `_build_user_message()` (the wrapping);
`haiku_build_batch_requests()` and `gemini_call_once()` (the system-prompt
plumbing).

## 2026-05-18: Editable installs are mandatory when a sibling venv consumes the toolkit

The PA hook calls `~/personal-assistant/venv/bin/python3 -m cc_session_toolkit.cli ...`
— so the toolkit lives in the *PA* venv, but the source tree is at
`~/Code/cc-session-toolkit/`. Before today, `cc-session-toolkit 0.1.0`
was installed in PA's venv as a regular (non-editable) wheel. That
meant every change to `~/Code/cc-session-toolkit/src/` was invisible to
the hook until I re-ran `pip install` — and silently so.

Verified during F1 wire-up: after editing `archive.py` and re-running
the hook, the new code path didn't execute. `pip show` revealed the
non-editable install at the venv site-packages dir.

Fix: `~/personal-assistant/venv/bin/pip install -e ~/Code/cc-session-toolkit`.
Now `pip show` reports the editable install pointing at `~/Code/...`,
and source-tree changes are picked up immediately.

Implication: any cross-repo dev where machine M's venv consumes a
toolkit from repo R needs editable installs on M, *or* a tagged-release
+ reinstall step in the dev loop. zbook and rpi-server still have the
old non-editable wheel — they need the same `pip install -e` before
relying on the new path there.

Anchored at: `~/Code/cc-session-toolkit/pyproject.toml`;
`~/personal-assistant/venv/lib/python3.13/site-packages/cc_session_toolkit/__init__.py`
(now a symlink to the editable source).

## 2026-05-18: Real-world distilled-transcript sizes confirm Gemini's context-window advantage

Smoke-test on three real archived PA sessions after wiring up
`transcript_text.extract_transcript_text`:

| Session | Distilled chars | Estimated tokens |
|---|---:|---:|
| 2026-05-17 implement-quick-steps... | 512,412 | ~128,103 |
| 2026-05-16 vector-2-design... | 241,112 | ~60,278 |
| 2026-05-14 sync-personal-assistant... | 646,258 | ~161,564 |

All three were on gz-compressed JSONL. Two of three exceed Haiku's
200K-token context window; the 161K case is uncomfortably close. With
Gemini Flex's 1M-token window all three fit one-shot with multiple-x
headroom.

This is the empirical case for the chunking-vs-one-shot architectural
decision: had F1 stuck with Haiku, ~30% of PA's session corpus would
have needed chunking + cross-chunk stitching just for routine
auto-metadata. The bake-off had pre-screened to *in-window* sessions;
real-world traffic does not.

Anchored at: `~/cc-archives/personal-assistant/2026-05-{14,16,17}*/session.jsonl.gz`;
`cc_session_toolkit/transcript_text.py:estimate_tokens`.

## 2026-05-18: Auto-metadata bake-off iteration trajectory — diminishing-returns curve

Five rounds of prompt iteration scored against a fixed 42-cell rubric
(7 in-window sessions × 6 fields). Each round added ~1.2-1.7K tokens to
the system prompt; per-call cost lift was ~4% per iteration because
transcript token cost dominates.

| Round | Prompt | Haiku wins | Gemini wins | Ties |
|---|---|---:|---:|---:|
| 2 | base | 29 (69%) | 1 (2%) | 12 (29%) |
| 3 | v1 tuned (specifics requirement + comparisons table) | 11 (26%) | 12 (29%) | 19 (45%) |
| 4 | v2 tuned (+ structural reqs: sequencing, rejected alternatives, contrastive numbers, user voice, conceptual characterisation, session-shape labelling) | 7 (17%) | 17 (40%) | 18 (43%) |
| 5 | v2 + title named-entity rule | (not re-scored; spot-check confirmed 3825319a title regression fixed) | — | — |

Marginal gain per round shrank from 18 cells (base → v1) to 4 cells
(v1 → v2). Round 5 fixed a single regression without re-scoring the
full rubric.

Implication: for similar prompt-tuning problems, expect ~3 iterations
before diminishing returns. Stopping criterion: when residual gaps look
stylistic / model-intrinsic rather than addressable, productionise.

Anchored at: `data/experiments/bake-off-metadata-2026-05-18/` (all
prompts, response sets, populated rubrics).


## 2026-05-20: F3 backfill scope is 32 sessions, not 307

The "307 historic sessions" figure in earlier continuity entries was a
misread: it is the **total unique main-thread session count across all
amd-tower archive locations**, not the subset needing F3. The
F3-needing subset (`auto_generated.purpose == "Auto-metadata unavailable"`)
is exactly 32. This matches the refined cost estimate computed by
`scripts/backfill-session-metadata.py --cost-sample-size 20` ($1.26
mean / $2.79 p90 worst-case envelope). Inventory at
`planning/archive-inventory-2026-05-20.md`.


## 2026-05-20: Two parallel background agents on the same repo, zero conflicts

Ran C2+C3+C4 agent and M7-M15+Lows cleanup agent concurrently against
`~/personal-assistant/`. Coordination: explicit file-ownership rules
in the prompts (C2/C3/C4 owned `extraction-hook.py`,
`sync-symlinks.sh`, `data/.gitignore`; cleanup owned everything else).
Both agents instructed to `git pull --rebase` before pushing.

Result: cleanup agent's pull was a no-op (sibling's commits had
already landed); zero rebase conflicts; 14 PA commits + 2 toolkit
commits + 1 pa-data commit shipped in one window.

Pattern is reusable for future multi-agent work on shared repos:
split scope by file ownership, dispatch in parallel, defensive
rebase. Anchored at this continuity entry plus commit log
`87abe5d..0ec0a7b` (PA), `41758a3..6ac9fe2` (toolkit).


## 2026-05-20: Worktree-archives can hold canonical bytes that per-project archives stub

map-reader-llm's per-project `archive/cc-sessions/` is full of Git LFS
pointer stubs (87 sessions). The canonical bytes live at
`.claude/worktrees/agent-a59a9dae0bff3f27b/archive/cc-sessions/` — the
worktree was created when LFS smudge was active, so it has real
content. Any tool reading the per-project layer (cc-session-toolkit
backfill, rsync to consolidated store, grep across transcripts) gets
pointer-text not session content, and most fail silently or with
cryptic errors.

**Inventory pre-flight is what surfaced this** — would have been easy
to miss until consolidation failed mid-rsync.

Future: any project using Git LFS for archive content needs explicit
verification that the per-project layer has been LFS-pulled, OR migrate
to the new architecture where `archive/cc-sessions/` is gitignored and
lives only on the consolidated mount (per the 2026-05-20 architectural
decision). LLM-History-Paper has the same pattern with 49 pointer
stubs in its `archive/cc-sessions/`. Anchored at
`planning/archive-inventory-2026-05-20.md`.


## 2026-05-22: Anti-confabulation discipline applied to empirical-construction agents

When generating something that *feels* generative (a style guide, a
literature taxonomy, a methodological framework), the standard
anti-confabulation rule — re-verify checkable specifics at source —
needs structural enforcement, not just intent. The
`corpus-style-analyser` agent (`~/.claude/agents/corpus-style-analyser.md`)
enforces this via:

- Explicit per-claim status fields (`attested` / `attested-rarely` /
  `absent-when-searched` / `aspirational` / `derived-by-inference`).
- Required ≥2 verbatim quotations with paper key + section locator
  per attested claim.
- Separate evidence ledger (Appendix C) so each numbered claim in
  the body can be falsified by re-reading the named passage.
- An aspirational section explicitly walled off from corpus, so
  "things the agent thinks should be in the guide" cannot leak into
  the empirical sections without a status downgrade.

Result: claims are empirically falsifiable by re-reading the named
source. Generalises to any agent that constructs claims from a
corpus, not just style — works for taxonomies, methodological
frameworks, lit-review summaries. Run-1 output at
`notes/style-guides/academic/style-guide-academic-2026-05-22.md`
demonstrates the scaffolding in practice on 18 papers / 139k words.


## 2026-05-22: Background-agent + parent-session-reconciliation pattern for HIL empirical work

For tasks that have a batch-y empirical pass AND a human-judgement
reconciliation pass, splitting them across an agent invocation (batch,
runs while you do other work) and a future parent-session (interactive
Q&A) outperforms a single long interactive session. Run-1 of the
style guide demonstrated this: agent built the empirical guide +
aspirational section in ~14 minutes background while Shawn worked on
the inscriptions talk; reconciliation against prior conscious guides
is captured as an inbox follow-up for a fresh-eyes session.

Two specific benefits over single-session:

1. **Lower handoff cost than expected.** The agent's output file is
   the durable artefact; no conversation state needs to be carried
   forward. Reconciliation can happen any time, in any session.
2. **Fresh-eyes for the judgement pass.** Reconciliation under tired
   attention at the tail of a long session is materially worse than
   reconciliation under fresh attention in a new session, especially
   for taste-driven decisions (style, voice, methodology).

Pattern generalises beyond style guides: any task with structure
"agent extracts/analyses, human judges" benefits from the split.
Captured in agent definition under "Reconciliation with prior style
guides — NOT YOUR JOB".


## 2026-05-22 (late evening): Reference-list contamination is the default failure mode for stylometry on academic prose

Ran `Hiro-Inagawa/write-like-me`'s `scripts/stylometry.py` against the
same 18-paper Zotero corpus that produced corpus-style-analyser run-1.
Two concrete leakages visible in the output: (a) co-author surnames
`sobotkova` (56) and `ross` (52) appeared in the top-20 sentence-initial
words; (b) URL fragments `doi` (2.054/1k), `https` (1.891/1k), `org`
(1.284/1k) appeared in the top-30 distinctive content words. Roughly 5%
of the corpus passing through `compute_features` was reference-list noise.

Write-like-me's markdown stripper (`stylometry.py:115-160`) catches
frontmatter, code fences, inline code, tables, image tags, and inline
`[N]` citations — but does not detect the references-section boundary
in academic prose. Run-1 stripped references explicitly per paper (per
its `Run notes` section); the difference is visible in the corpus
footprint — 116,842 words (write-like-me) vs 139,105 words (run-1), a
~16% delta that's mostly write-like-me's *over*-stripping of legitimate
markdown structure combined with *under*-stripping of references.

Generalises: any stylometry tool that doesn't ship an explicit
academic-references heuristic will leak reference-list content into
sentence-initial-word and top-content-word distributions when fed
academic papers. The corrective for v2 of corpus-style-analyser is an
explicit references-section regex (`^(References|Bibliography|Works\s+Cited|Literature\s+Cited)\b`
case-insensitive, truncate after the last occurrence) with a fallback
heuristic that detects high-density `Author, A. (Year)` patterns. The
fallback matters: ~30% of academic publishers use venue-specific
synonyms or omit the heading entirely.

This is general for tool-evaluation, not just stylometry: when running a
genre-agnostic tool against domain-specific text, check the input/output
mass balance before trusting the distributional outputs.


## 2026-05-22 (late evening): Multi-author benchmark suites need scrutiny before applying to single-author voice work

The Wang et al. 2025 "Catch Me If You Can" evaluation ensemble (arXiv
2509.14543) was on the corpus-style-analyser v2 adoption shortlist as
a way to measure whether the produced style guide actually moves LLM
output toward Shawn's voice. The Plan agent's investigation of the
open-source release at `github.com/jaaack-wang/llms-implicit-writing-styles-imitation`
(MIT, 5 stars, last push 2026-01-16) surfaced a structural mismatch:
three of the four metrics — authorship attribution accuracy, authorship
verification, and AI-detection rate — are designed for *multi-author*
benchmarks. AA and AV ask "is this text by author X vs Y" or "are
these two texts by the same author"; both require ≥2 authors to
discriminate against. The Shawn corpus has one. AI-detection requires
external services (GPTZero). Only the style-matcher metric (Mahalanobis
distance over stylometric feature space) ports cleanly.

The adopted scope for Phase 5 of v2 is therefore a **reduced two-metric
CC-only suite**: Mahalanobis distance over Phase-1 features + the
8-metric tolerance gate from write-like-me's `references/07-verification.md`.
Both run on CPU with no external API. Optional GPTZero appendix for
generation-time AI-detection scores (~$0.05/1000 words external API
spend, opt-in).

Generalises: benchmark-shaped evaluation ensembles often assume the
discriminative-classification frame (which-of-N-classes is this?) that
fits academic benchmark datasets but not within-author personalisation
work. Before adopting a published ensemble, check whether the metrics
were designed for the *between-class* problem or the *within-class
match-to-target* problem. The frames look identical until you try to
run them on a single-author corpus and three of four metrics become
undefined.


## 2026-05-22 (late evening): Severity-only classification can't calibrate proposer trust — verifier output needs a typed `failure_type` axis

Smoke-tested `/lit-scout-iterate` on a Bayesian-dating bibliography
query: 175 claims across 35 rows × 5 verifiable fields; iter-0
returned 1 FAIL (row 16 authors — CrossRef family/given encoding
swap on "Lanos & Philippe"), iter-1 converged PASS by substituting
the verified value. Convergence rate 1/175 = 0.57 % — much lower
than the prior-art smoke test (3/18 = 17 %) on the same day. Two
clean data points: well-indexed academic corpora (CrossRef + S2
coverage) produce few confabulations; LLM-tooling prior-art (recent
repos, mixed registries, blog posts) produces many.

The architectural finding that matters more: the single FAIL was
classified `severity: high`, but it was *mechanically* an
`encoding_artefact` (CrossRef returned `family="Philippe"` for an
author widely known as Lanos), not a `confabulation` (proposer
inventing from memory). Both deserve high severity for the iterate
loop's prioritisation, but they call for very different calibration
responses over time — "the source API is noisy" is *not* a signal
to distrust the proposer; "the proposer invented this" *is*.

Generalises: any verification system that emits a single
"wrongness" axis can't separate proposer-failure from
source-failure, which undermines the closed loop's ability to
calibrate trust. The fix is a typed second axis. We landed
`failure_type ∈ {confabulation, encoding_artefact, metadata_drift,
stale_count}` in `prior-art-scout-verifier`; the lit-scout and
data-profile verifiers need the same backport for symmetry, and
the driver gains a per-iteration `failure_type` distribution table
as the calibration log that the rubric needs to evolve. Spec
in `agents/prior-art-scout-verifier.md` "Severity rubric and
failure_type axis" section; commit `c4e8139` for the
prior-art-scout retrofit that introduced it.

Bonus from the same smoke test: iterate-mode corrections do **not**
propagate to BibTeX. `lit-search.py bibtex` re-queries CrossRef and
recovers the raw (uncorrected) value, so the user-facing .bib is
still wrong on rows the loop corrected. Two fix paths (driver-side
post-processing or a `lit-search.py bibtex --corrections` flag);
deferred until rubric calibration is further along. Captured as
a follow-up item in workstream H.

## 2026-05-22: CC live-store JSONL shape — `cwd` is typically NOT on line 1

Sampling 50 unarchived main-thread sessions on amd-tower, only 5 of 50
(10%) carry the `cwd` field on line 1 of the JSONL. The other 45 carry
it on lines 2-10, behind one or more leading metadata records of type
`summary` (`{"leafUuid","summary","type"}`), `permission-mode`, or
`progress` that lack `cwd`. **Implication**: any toolkit that needs to
extract session-level metadata from a live JSONL by parsing the first
line will mass-misroute. The toolkit's `_extract_cwd_from_jsonl` had
this bug; pre-fix dry-run would have routed 78 of 96 amd-tower sessions
to a single `shawn/` bucket. Fix scans up to 20 records. Generalises:
CC's live JSONLs are append-streamed, with session-state metadata
flowing in alongside content; first-line assumptions are fragile.

Anchor: cc-session-toolkit commit `1dd4d69` (the audit-criticals fix
that added the multi-line scan to `_extract_cwd_from_jsonl`).

## 2026-05-22: Gemini 3 Flash Preview vs Gemini 3.5 Flash empirical comparison

3-session head-to-head on the toolkit's production prompt
(`prompt-gemini-v2.md`), small/medium/large session sizes
(~7K/228K/397K input tokens respectively, distilled):

- **JSON structural defects**: 3.5 Flash 0 of 3; 3 Flash Preview 1 of 3
  (a stray `three_ps.`-prefixed key under `three_ps` that would have
  degraded `provenance_summary` to empty via the M3 `.get() or default`
  guard).
- **Named-entity preservation**: 3.5 Flash picked up specific commit
  hashes (`a2e40fd`), git tags (`osf-lodgement-2026-05-20`), people's
  names (Adela Sobotková), 95% CI bounds — where 3 Flash Preview
  generalised or omitted these.
- **Numeric specificity**: 3.5 Flash more often reproduced explicit
  test counts, percent changes, and stat values exactly; 3 Flash
  Preview summarised.
- **Wall-clock**: 3.5 Flash ~20% faster on smaller sessions
  (~4.3s → 2.4s small; 8.7s → 5.9s medium; 13.5s → 12.8s large —
  the gap closes on big inputs).
- **Cost**: 3.5 Flash 3× the Flex price (empirically: $0.75/$4.50 vs
  $0.25/$1.50 per M input/output tokens — confirmed by direct
  `usage_metadata` token counts × API list price).

Production migration accepted on the price-quality trade-off (RDA-IG
provenance fidelity). Toolkit commit `cdc7c65`.

## 2026-05-22: Toolkit's `rebuild_catalogue` scans one level deep

`cc-session catalogue --rebuild --archive-root <root>` produces
`CATALOG.json` with only one-level project scanning. Nested
sub-category sessions (e.g. `LLM-History-Paper/theseus-ship/<session>/`,
`map-reader-llm/vlm-burial-mound-detection/<session>/`) don't appear in
the catalogue's session list. `_legacy/` content similarly absent.
Post-Phase-C state on rpi-shares: **411 catalogued sessions vs ~595
actually present** in `session.meta.json` files on the filesystem.

**Implication**: consumers that use `CATALOG.json` as the source of
truth need to know about this depth limit. `scripts/resolve_session_id.py`
papers over it by falling back to filesystem `rglob` after a catalogue
miss. Worth a toolkit-side fix to recurse (deferred — separate
toolkit issue, not blocking).

Anchors: `~/personal-assistant/scripts/resolve_session_id.py` (the
fallback impl); `~/Code/cc-session-toolkit/src/cc_session_toolkit/catalogue.py`
`rebuild_catalogue` for the source-side fix.

## 2026-05-22 (night): Secrets hygiene in env-sourcing — two leak surfaces

Two operational failures observed while provisioning a new Zotero API key:

1. **bash treats `VAR-NAME=value` as a command, not an assignment.** When
   `.env` contained `ZOTERO_API_KEY_PAPER-B=<value>` (hyphen in name),
   `set -a && . ~/personal-assistant/.env && set +a` parsed the line as
   an attempt to run a command named `ZOTERO_API_KEY_PAPER-B=<value>`,
   then printed `command not found` *including the offending line in the
   error message*. The key value ended up in stdout and from there into
   the session transcript.

2. **pyzotero embeds API keys as URL path segments in `GET /keys/<key>`
   and dumps the full URL into exception strings on 403.** Observed
   immediately after the revoke-and-reissue of the leaked Paper-B key:
   `UserNotAuthorisedError` traceback included the URL with the (now
   dead) key value embedded.

Operational rules that follow:

- Env-var names: all-uppercase + underscores. Never hyphens. Convention
  for multi-target services: `<SERVICE>_API_KEY_<TARGET>` (e.g.
  `ZOTERO_API_KEY_PERSONAL`, `ZOTERO_API_KEY_PAPER_B`).
- pyzotero traceback strings are NOT safe to forward into shared logs,
  paste into tickets, or copy from a session transcript without
  redacting the `?key=` or `/keys/<key>` URL fragments.
- Treat any key value that has appeared in stdout or a traceback as
  compromised even if "no one was watching" — log capture or scrollback
  may have preserved it.

Anchors: incident timestamps in this session's transcript; bash leak
visible after the `Permission to use Bash with command grep -i "zotero"
.env has been denied` event; pyzotero leak visible in the 403 retry
after key revoke. Mitigation pattern landed: read keys from disk via
Python `Path.read_text()` parsing rather than bash sourcing, when the
variable name might contain forbidden characters.

## 2026-05-22 (night): Closed-loop corrections must thread through to the deliverable, not via derivatives

Worked example from `/lit-scout-iterate` 2026-05-22:

Row 16 = Lanos & Philippe (2018) ChronoModel paper, DOI
`10.29220/csam.2018.25.2.131`. CrossRef returns
`authors[0]={family: "Philippe", given: "Lanos"}` — family/given
swapped from the canonical attribution. Same DOI flowed through three
output paths:

| Path | Author rendering | Source |
|---|---|---|
| Verifier's `claims.jsonl` (`value` field) | `Lanos, Philippe; Philippe, Anne` | iterate-mode correction at iter-1 |
| Verifier's `report.md` Findings table | `Lanos & Philippe (2018)` | iterate-mode correction at iter-1 |
| `lit-search.py bibtex` output `.bib` file | `author={Philippe, Lanos and Anne, Philippe}` | raw CrossRef, never corrected |
| `scripts/lit-scout-zotero-import.py` Zotero item | `lastName='Lanos', firstName='Philippe'` | claims.jsonl + CrossRef merge |

Same DOI, same closed loop, four outputs, two correct and one wrong
because it re-queried the source instead of consuming the correction.

The principle: **derivative artefacts re-query the source by default**.
If the closed-loop's corrections live only in the markdown / JSONL,
they only reach the user via paths that read those files. The
`.bib` file produced by a fresh CrossRef API call inherits the raw
encoding and silently undermines the verifier's work. Fix patterns:
(a) thread corrections through explicitly (Zotero-import path, here:
authors built from `claims.jsonl`, rest from CrossRef); (b) overlay
the corrections at emission time (`lit-search.py bibtex --corrections`
flag, deferred); (c) avoid the derivative path entirely (treat Zotero
as primary, .bib as backup — the design decision made this session).

Generalises beyond lit-scout: any closed-loop pair whose corrections
live in a structured contract file needs an audit of every consumer
to ensure they read the contract, not the upstream source.

Anchors: `commands/lit-scout-iterate.md` "### Zotero staging import"
section; `scripts/lit-scout-zotero-import.py:build_zotero_item` where
the author-from-claims override happens; the row 16 entry in
`/tmp/lit-scout-iterate-20260522-190212/iter-1/claims.jsonl` vs
`/tmp/lit-scout-iterate-bibtex-20260522-194400.bib`.

## 2026-05-22 (night): DOI dedup catches 2.5× more than text-based dedup on academic corpora

Direct measurement, single corpus (n=35 Bayesian-archaeology papers,
typical methodological-foundation literature):

- Lit-scout proposer's `[IN ZOTERO]` flag — uses
  `scripts/zotero.py:search_items`, a LIKE-based title + creator-name
  fuzzy text search on the local sqlite: **caught 2 of 5 duplicates**
  (Williams 2012 `2VNLIW93`, Lee & Ramsey 2012 `X2LIEQTE`).
- Staging-import script's `find_existing_by_doi` —
  `SELECT … WHERE LOWER(idv.value) = LOWER(?)` against the DOI field
  across all 16 local libraries: **caught all 5 duplicates** (added
  Crema & Bevan 2021 `7RJBCSPN`, Shennan et al. 2013 `XBJKDIUS`,
  Timpson et al. 2014 `Z8PCHCSH`).

Two of the misses were group-library items (SDAM-AU, TRAP) that the
proposer's text search did find for some rows but not these — likely
fuzzy-text precision issues at the boundary of multi-author titles
where the surface forms diverge between CrossRef metadata and Shawn's
typed Zotero entries.

The principle: for academic-paper corpora where DOI is reliably
present, **DOI is the right dedup primary key**. Text search is a
fallback for entries without DOIs (e.g. older books, grey literature),
not a substitute. Single measurement — generalise carefully; would be
worth re-measuring on a corpus where titles are short / less
distinctive.

Follow-up captured in continuity workstream H: add a `find_by_doi()`
fast-path to `scripts/zotero.py:search_items` so the lit-scout
proposer's dedup matches the staging-import script's coverage.

Anchors: `scripts/zotero.py:search_items` (current text-based impl);
`scripts/lit-scout-zotero-import.py:find_existing_by_doi` (the DOI
SQL query); the dry-run output in this session's transcript showing
the 5-vs-2 split with named DOIs.

## 2026-05-23: `/audit` on workstream-H code (post-ship) found 3 Mediums + 4 Lows the e2e validation missed

Empirical baseline for the "ship working code, then audit before
committing follow-ups" workflow. The lit-scout Zotero staging-import
(`scripts/lit-scout-zotero-import.py`) shipped 2026-05-22 with full
end-to-end validation: 30 items created in Zotero, manifest dedup
correct, iterate-mode correction round-tripped to the row-16 author
field. By the standard "does it work?" gate, the script was done.

Today's session added three small follow-ups (env-var rename, manifest
dedup helper, `find_by_doi` + proposer wiring), then ran `/audit` on
the diffs before commit. The audit pass spawned three parallel
subagents (one per touched `.py` file) per `commands/audit.md`.
Findings on workstream-H code (excluding the `sync-to-zotero.py`
Lows which predate the workstream): **3 Mediums + 4 Lows in
`lit-scout-zotero-import.py`** that the smoke test couldn't have
surfaced. They were patterns, not bugs visible on a single run:

- Title/authors precedence used `X or fallback` so a verifier-corrected
  empty string would silently fall back to CrossRef.
- Dead-code line (`url = …` overwritten by the next line) hiding a
  buried `import urllib.parse` inside the function body.
- `previous_manifest["imported_at"]` direct subscript (KeyError mid-write
  on a hand-edited manifest → orphan items with no manifest record).
- `read_text()` without `encoding="utf-8"` on `.env` + JSONL.
- `json.loads(prior_manifest)` no try/except — corrupt manifest aborts.
- `run_ts` drift on re-runs of workspaces without an embedded timestamp.

Most consequential finding came from auditing the new code I'd just
written: `find_by_doi`'s `LOWER(doi) = LOWER(?)` SQL would have silently
missed Zotero items stored with `https://doi.org/…` or `doi:…` prefixes
— partially undermining the 5/5 catch advantage the function was being
added for. Fixed with chained SQL `REPLACE` on both sides + a
`_normalise_doi()` helper.

**Principle:** "passes end-to-end on one workspace" and "audit-clean
under adversarial line-by-line read" are different gates with
different failure surfaces. The first catches behaviour on the happy
path; the second catches edge-case patterns that may never fire in a
single smoke test. Workstream-H code that ships under deadline
pressure should get an `/audit` pass before the *next* commit batch,
not deferred to the next session — context is loaded, fixes are
cheap, follow-ups bundle naturally with the new work.

Anchors: today's commits `ae3c141`, `4f50ce9` (audit-driven fixes
folded in); `/audit` subagent reports captured in chat transcript;
session log entry 2026-05-23 in `planning/continuity.md`.

## 2026-05-23: DOI dedup must normalise URL/scheme prefixes on both sides — bare-DOI match alone undercaught

Calibration measurement extending the 2026-05-22 "DOI dedup catches
2.5× more" entry above. Initial `find_by_doi` in `scripts/zotero.py`
used `LOWER(idv.value) = LOWER(?)` — exact match after lowercasing.
On the Zotero corpus, that would have silently missed any item the
user pasted as `https://doi.org/10.x/y` (browser-bookmarklet form)
or `doi:10.x/y` (some citation-manager exports), and matched only
bare-DOI entries. The 5/5 catch claim was tested on a corpus that
happened to have bare DOIs everywhere — empirically right but
not robust.

Fixed by normalising both sides:

- Python side: `_normalise_doi()` strips whitespace, lowercases, and
  strips the five common URL/scheme prefixes (`https://doi.org/`,
  `http://doi.org/`, `https://dx.doi.org/`, `http://dx.doi.org/`,
  `doi:`) before passing the bare DOI as the SQL parameter.
- SQL side: chained `REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(idv.value),
  …))))) = ?` to strip the same five prefixes from the stored value
  before comparison. Verified across bare, URL-wrapped, lowercased,
  and unknown forms.

Principle: when a function's correctness depends on string equality
across user-curated data, the input space is wider than the test
corpus shows. Normalise canonical forms on both sides; don't assume
the corpus is the input space.

Anchors: `scripts/zotero.py:_normalise_doi` + `find_by_doi`
(commit `4f50ce9`); /audit subagent finding at the same line range;
session-log 2026-05-23 in `planning/continuity.md`.

## 2026-05-22 (night): Anti-confabulation discipline failure — misread a Python dict literal

Recorded as a concrete instance of the failure mode the global
anti-confabulation rule was written to prevent.

Context: probing the new Zotero key's permissions. pyzotero's
`key_info()` returned a dict like:

```python
{'access': {'user': {...}, 'groups': {
    'all': {'library': True, 'write': True},
    '525489': {'library': True, 'write': False},
    ...
    '5861859': {'library': True, 'write': True},  # ← Paper-B
    ...
}}}
```

I asserted with confidence that Paper-B (`5861859`) had `write: False`,
which would have meant the new key's scope was inverted from intent.
Shawn pushed back: "if it's the old key, it will fail." Single-sentence
challenge that flipped my diagnostic — re-read character-by-character,
confirmed `write: True` on Paper-B, retracted.

Failure mode: speed-reading a long dict-repr output, taking the wrong
boolean value to be the one I expected, and asserting it with the same
confidence I'd have if I'd verified it. The global rule
(`~/.claude/CLAUDE.md` anti-confabulation section) says: "Before citing
a specific number, filename, path, identifier, commit hash, config
value, or quoted text in a claim to Shawn, re-read the source file."
That includes character-by-character re-reading of structured output
already in the conversation, not just file paths.

The recovery worked because: (a) Shawn challenged via consequence-
reasoning, not memory ("if it were X, then Y would have happened —
Y didn't happen, therefore not X"); (b) I admitted the misread
rather than re-justifying. Good failure to file because the recovery
pattern is concrete and reusable.

Anchors: this session's transcript; the exact pyzotero response is
preserved in the bash output around the key-info probe; the apology
turn followed by a character-by-character re-read confirms the
correction.

## 2026-05-24: Iterate-loop smoke tests on real briefs produce clean PASS-in-1 results; the row-removal path is hard to exercise without a manufactured failure

Two consecutive closed-loop iterate-driver smoke tests — `/lit-scout-iterate`
on "Bayesian methods for archaeological dating and chronological modelling"
(2026-05-22) and `/prior-art-scout-iterate` on "Open-source LLM provenance
toolkits (RDA-aligned)" (2026-05-23) — both terminated PASS in 1 iteration
(lit-scout converged at iter-1 after one CrossRef family/given correction;
prior-art was clean on iter-0). In both cases the `url_resolves` /
`doi_resolves` row-removal path was **not exercised**: zero fabricated URLs
or DOIs.

Empirical inference: when given a real specific-domain brief (rather than
a speculative or over-broad one), the proposer agents query live source
APIs at scout-time rather than guessing from memory. The fabrication
failure mode the verifiers were built to catch doesn't fire on clean
briefs from research-relevant domains. The verifier still does productive
work on these runs — diligent re-querying caught one author-attribution
error in lit-scout and surfaced one Cloudflare-blocked URL as `unverifiable`
in prior-art (with the verifier going one step further and confirming the
paper via OpenAlex DOI fallback rather than just marking unverifiable).

Implication for the rubric-calibration question (synthetic-FAIL test
vs accumulate-real-errors): the row-removal path appears genuinely rare
on real briefs, not just unlucky in two trials. Calibration data from
synthetic FAILs would optimise for an imagined failure distribution
that may not match real usage. Decision 2026-05-24: defer synthetic
testing indefinitely; let real errors accumulate over ~6 months; revisit
the verifier evals then.

Anchors: `data/experiments/prior-art-scout-iterate-smoke-2026-05-23/`
(full smoke trajectory + README); continuity 2026-05-22 / 2026-05-23 /
2026-05-24 session log entries; `data/scratchpad.md` 2026-05-24 entry
captures the bias to resist (manufacturing FAILs to validate
architecture).


## 2026-05-24: Production-vs-experiment config drift only surfaces when validation calls the production code path

The v3 session-summary bake-off (initial RAC-TRAC + 3-session mini round)
ran cleanly using its own runner script which set
`response_mime_type=application/json` and `max_output_tokens=8192`
explicitly in the Gemini call config. When the production code path
(`archive.py:_call_gemini_once` via `generate_auto_metadata`) was wired
up using the same v3 prompts on the same transcripts, **both calls
failed with JSON parse errors** — production was missing the
`response_mime_type` setting and was capped at the old v2-era
`max_output_tokens=1024` which truncated v3's richer output mid-JSON.

The bake-off success had masked these production-side defects entirely.
The validation step (`validate-production-path.py`) caught them only
because it called the actual production functions rather than
re-implementing the call in the experimental runner. Two ~5-minute fixes
to production after that, and the same transcripts succeeded.

Empirical implication: when shipping LLM call sites, the experimental
prototype and the production caller diverge on configuration in ways
the prototype's success doesn't reveal. A validation step that exercises
the **actual production function** with **real archive data** is the
load-bearing check — not the bake-off itself. The pattern: design in
experiment, ship via production path, validate the production path
end-to-end before declaring ready.

Anchors: 2026-05-24 commits `902b2eb` (toolkit fix adding
`response_mime_type` + raising cap) + `5e4266a` (PA continuity);
`data/experiments/session-summary-v3-bakeoff-2026-05-24/validate-production-path.py`;
audit follow-ups doc same dir.

## 2026-05-24: LLM-first audience design inverts archive optimisations human-first would mandate

The v3 session-summary schema rebuild flipped on a single Shawn-prompted
strategic question: "are session archives memory primitives, or
open-science / RDA-aligned transparency artefacts?". The original v2
design implicitly assumed human-first reading (terse fixed-word ceilings,
narrative prose). When we made explicit that the primary reader is
another LLM (future-Claude consulting the archive on demand, or
external researchers reading via LLM tooling), the design implications
inverted:

- **Density > brevity.** Tokens are cheap (Gemini Flex output costs
  ~$0.022 per 5K tokens); reconstructability is expensive. Capture
  more, not less. A human asks for a synopsis on demand; they cannot
  expand from a summary back to detail you did not write down.
- **Structure > prose.** Arrays of typed records (phases, decisions,
  key_exchanges) are easier for downstream LLMs to navigate than
  monolithic paragraphs. The schema additions reflect this directly.
- **Length scales with input.** Fixed 40-80-word ceilings were a
  human-page-fit constraint; for LLM readers, target ≈ √(input_tokens)
  with density-driven ±30% adjustment respects information content
  rather than reading comfort.
- **"Empty arrays beat invented arrays."** An honest empty `phases[]`
  on a single-thread session is strictly better than a confabulated
  populated one for downstream querying — the field's absence carries
  retrieval-useful information.

Cost-side check: v3 produces ~6× more summary text than v2 on the same
RAC-TRAC session at ~1.7× the cost — i.e., **3.4× cheaper per word of
summary produced**. Even though absolute spend per session rose, the
information density per dollar rose substantially. The audience
question wasn't just a framing exercise; it directly justified the
cost expansion.

Anchors: `data/experiments/session-summary-v3-bakeoff-2026-05-24/comparison-notes.md`
(numbers); `wiki/working-notes.md` 2026-05-23 calibration entry (the
chars-per-token undercount that broke v2's 850K budget); commit
`902b2eb` (toolkit wire-up with the v3 prompt that encodes this
framing explicitly).

## 2026-05-24: Run-1 anchors were corpus-contaminated; "regression against prior run" must be retired as a verification target when the prior run was extraction-noisy

The v2 Phase 1 pipeline failed 8 of 13 regression anchors when measured
against `corpus-style-analyser` run-1 values (the academic style guide
published 2026-05-22). The initial framing was "aggressive ref-stripping
explains the deviation; deviations are intentional per plan §2.5." Half
right. After Shawn pushed back on the interpretation and four parallel
diagnostic agents ran, the actual decomposition was:

- Run-1's body text was contaminated by author affiliations
  ("Center for Humanities Computing"), journal mastheads ("ScienceDirect",
  "Eftimoski", "Macquarie", "Australia"), running headers
  ("Sobotkova and Ross: The Tundzha Regional Archaeology Project"
  appearing ~10× per paper), web-PDF page-header bands
  ("5/22/25, 3:13 PM    Traces in a Lost Landscape:" 26 % of
  5INAFTVT's announcement-colon hits), and reference-fragment titles
  ("CIELab color space" inflating US-orthography counts).
- Run-1's sentence segmentation was inflated by column-interleaved
  Frankenstein sentences from `pdftotext -layout` on two-column PDFs;
  the published mean sentence length of 23.9 was high. The true
  body-only value on a clean PyMuPDF + pdfplumber extraction is
  **21.45**.
- Run-1 had internal numerical inconsistency: "892 semicolons across
  the corpus (5.57/1k)" implies a 160 870-word denominator, but the
  same run reports 139 105 total words. One of those two numbers was
  derived against a different sentence/word universe.

After all of that surfaced, the verdict had to be that run-1 cannot be
the regression target — the new (clean-corpus) values are the new
ground truth, and the legacy anchors get retired with their derivation
artefacts documented.

**Generalises:** any "regression against prior published numbers" check
silently assumes the prior numbers were on a noise-free input. For PDF
corpora processed through layout-sensitive extractors, that assumption
fails. Two pre-conditions worth checking before treating prior numbers
as regression anchors: (a) was the prior extraction's input verified to
exclude non-body content (mastheads, affiliations, running headers,
page-header artefacts)? (b) does the prior report's published derived
metrics (X / Y per 1k) reconcile against its own stated totals? Failing
either, treat the prior values as a *starting estimate* and document
the deviation, not as a target.

Anchors: `notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md`
§4 (three-way trajectory: run-1 → v1-dirty → v2-clean); §10 Stream A
section; commit `834a5c3` (clean-corpus pipeline);
`style-corpus/phase1-results-clean.json`.

## 2026-05-24: PyMuPDF section detector aggressively over-promotes title-case lines to `## H2`; needs a constraint filter to be usable for downstream metrics

PyMuPDF + pdfplumber (via the canonical extractor at
`~/Code/llm-reproducibility/extraction-system/scripts/pdf_processing/`)
uses a heuristic that promotes any short title-case or all-caps line
into a Markdown level-2 heading. On academic PDFs with rich masthead
typography or chapter running titles, this produces hundreds of
fragmentary `## H2` lines per paper:

- ENPYIZQF: 562 H2s, 515 of which are short fragments (journal masthead
  "ScienceDirect", surnames "Eftimoski / Sobotkova / Ross", affiliations
  "School / University / Macquarie / Australia / Department")
- 592YDKFM: 556 H2s, 429 fragments
- 9B2FJ6SL: `## JD` × 8 (a journal running header), `## Validating ML
  / predictions of burial mounds` × 7

These wreck downstream metrics that use `## ` as a section boundary
(paragraph-aware splitters, section-mapped tables of contents). They
also pollute body-text token counts if not stripped before the
body/refs split runs.

Fix shape (now in `extract_corpus.py:drop_fragment_headings`): drop
H1-H6 lines whose text is a 1-2 word fragment. Keep numbered section
headings (`1.`, `3.2`, `A.1 Methods`), whitelisted single-word section
names (`Abstract`, `References`, `Methods` …), and 2-word all-caps
labels (`AUTHOR AFFILIATIONS`). Drop everything else with ≤ 2 words.
Plus a `strip_running_headers` pass for any line ≥ 15 chars appearing
≥ 4 times verbatim. On ENPYIZQF: 36 running-header lines stripped + 960
fragment H2s dropped → 562 H2s reduced to a usable count.

**Generalises:** any PDF-to-Markdown pipeline that promotes layout cues
to structural markup will over-fire on cover pages, mastheads, and
running headers. The corpus-curation discipline this enforces is
*structural reads come from typography but typography is noisy; require
domain constraints to recover trustworthy structure*.

Anchors: `scripts/style-analyser/extract_corpus.py` (post-extraction
cleanup passes); `notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md`
§2.2 (the five cleanup passes); commit `834a5c3`.

## 2026-05-24: A silent zip-pair bug can survive a year of "working" output if the surrounding heuristic happens to fail-safe

`phase1_pipeline.py`'s `strip_references` author-year-density fallback
contained:

```python
for prev, cur in zip(ay_matches[-2::-1], ay_matches[::-1][1:]):
    if cur.start() - prev.end() < 1500:
        run_start = prev.start()
```

The two reversed slices produce **the same items in the same order**:
`ay_matches[-2::-1]` and `ay_matches[::-1][1:]` are both
`[m_{n-2}, m_{n-3}, …, m_0]`. So at each iteration `prev == cur` and
the gap test `cur.start - prev.end` evaluates to negative-match-length —
always < 1500, always extends `run_start` back, walks the entire list to
`ay_matches[0].start()`. The function ALWAYS truncates at the first
author-year-shaped string in the document, regardless of true tail-run
density.

**Why this wasn't caught earlier:**
1. The 3 000-character span guard on the following line partially masks
   the damage — papers without a long author-year-shaped tail span
   silently fall through to "no strip" and look correct.
2. The regex requires the rare `Surname, F.M. … (YYYY)` body pattern;
   typical in-body citations are `(Smith 2020)`, which don't match. So
   on most papers the buggy fallback path never even fires.
3. CI2Q7VXD was the only paper in the corpus where the path *did* fire,
   and its outcome (truncation at char 79 129 of 107 561) coincidentally
   happened to land at a reasonable boundary because the first
   author-year-shaped match in the document was already in the
   reference list.

The bug was caught by an `/audit` sub-agent that read the loop expression
literally and pattern-matched on `zip(seq[::-1], seq[::-1][1:])` as a
known anti-pattern. Fix: `for prev, cur in
reversed(list(zip(ay_matches[:-1], ay_matches[1:])))`. Post-fix legacy
run on CI2Q7VXD: body word count rises from 8 421 to 8 569 (recovered
148 words of body prose that the buggy truncation had eaten).

**Generalises:** when a heuristic has multiple guard conditions
(tail-position + span-size + match-density), each guard masks bugs in
the others. The combined system can produce reasonable-looking output
even when one component is silently broken. Code review or
human-readable line-by-line audit catches these where unit tests pass
(every test exercises the function on a fixed input where the buggy
loop returns the same answer the correct loop would).

Anchors: `scripts/style-analyser/phase1_pipeline.py:158` (post-fix);
`notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md` §10
(Stream A fix list); commit `834a5c3`.

## 2026-05-28: rclone+R2 has two distinct "looks like auth, isn't" traps

Wiring the Cloudflare R2 offsite backup (Phase 0e) surfaced two failure
modes that both present as permission/capability errors but are neither:

1. **Bucket-scoped tokens reject the bucket preflight.** rclone runs a
   HEAD/CreateBucket check before uploads; an R2 API token scoped to a
   single bucket can't do bucket-level operations, so the preflight
   403s and *every* `PutObject` fails — even on a genuinely Object
   Read & Write token. Dashboard said the token was R&W; the write
   still 403'd. Fix: `--s3-no-check-bucket` skips the preflight. I
   initially (and confidently) misdiagnosed this as a read-only token.
2. **rclone < 1.64 intermittently 501s on R2 PutObject.** The distro
   build (`v1.60.1`) returned `501 NotImplemented` on a large fraction
   of uploads; with retries it landed only ~964 of 4,654 files before
   exhausting the budget. Not a flag problem — `--s3-disable-checksum`
   didn't help. Upgrading to `v1.74.2` fixed it cleanly (0 errors).

**Generalises:** when an S3-compatible backend returns 403/501 on
writes, separate (a) credential scope, (b) the client's pre-upload
bucket ops, and (c) client-version compatibility before concluding
"bad credentials". Verify the token permission at the provider's
ground truth (dashboard) rather than inferring it from one rclone
error. Anchors: `scripts/push-archives-to-r2.sh`;
`planning/continuity.md` 2026-05-28 entry.

## 2026-05-28: append-only sync silently strands in-place rewrites

The v1.2→v1.3 bulk metadata rewrite (643 sessions) never reached the
canonical rpi-shares store: `daily-sync.sh` pushed cc-archives with
`rsync -a --ignore-existing`, which skips every path already present
in the destination. The flag is correct for the common case (new
sessions are append-only) but structurally cannot propagate an
*in-place* rewrite of an existing file. The source-of-truth sat two
upgrade-runs stale and **nothing flagged it** — directory sizes
matched (3.4 GB each), because the metadata delta is tiny against the
transcript bulk, so a `du`-based "are we in sync" check reads clean
while the metadata is silently divergent.

**Generalises:** append-only sync + in-place mutation = silent
divergence. Size/byte-count "in sync" heuristics miss it; you need a
content- or mtime-aware check on the mutable files specifically. Fix
shipped: scoped `rsync -rt --update` passes in both directions
(local→canonical and canonical→local), restricted to the
in-place-mutable files (`session.meta.json`, `CATALOG.json`).
Anchors: `scripts/daily-sync.sh` cc-archives sync block;
`planning/continuity.md` 2026-05-28 entry.

## 2026-05-28: response_schema enforcement eliminated the stochastic-JSON failure class

The 1-in-25 subagent-summary JSON parse failures (Gemini under
`response_mime_type=application/json` alone, which instructs JSON
output but does not validate structure) dropped to **0 failures
across 2,018 subagent calls** on the 2026-05-26 archive-wide upgrade
once `response_schema` was added to the subagent Gemini call. Gemini's
structured-output mode validates against the schema before emitting,
closing the failure at source rather than mitigating after the fact.

**Generalises:** for LLM JSON output, schema-validated structured-output
mode is a categorically stronger guarantee than a mime-type hint plus a
robust parser. The mime-type hint reduces but does not eliminate
malformed output; the schema eliminates the class (for the
single-field subagent shape, at least — the richer parent schema was
also wired but is harder to prove exhaustively). Anchors:
`cc-session-toolkit` `archive.py:SUBAGENT_NARRATIVE_SCHEMA`, commit
`8e44f1a`; `planning/continuity.md` 2026-05-25 + 2026-05-28 entries.

## 2026-05-29: A misplaced file regenerates until you fix the scaffolding template, not the instances

`working-notes.md` was found misplaced *inside* `docs/notes/reflections/` in
5 of 7 repos (inscriptions, LLM-History-Paper, llm-reproducibility,
map-reader-llm, paper-b) rather than beside `reflections/`. The instinct is to
read that as five independent slip-ups; it isn't. The single cause is a shared
generator — `cc-session-toolkit` ships a `working-notes.md` template at
`src/cc_session_toolkit/data/reflections/`, so every newly-scaffolded project
inherits the misplacement.

**Generalises:** when the same defect appears across many instances, find the
shared generator (template, scaffold, codegen, snippet) before fixing
instances one by one — otherwise the fix doesn't stick and the defect
regenerates on the next scaffold. Anchors:
`cc-session-toolkit/src/cc_session_toolkit/data/reflections/working-notes.md`;
`wiki/planning/wiki-index-draft.md` § "Relocating misplaced working-notes.md files".

## 2026-05-29: Prefer-new-fallback-legacy lets a multi-repo migration run without a flag day

The PA wiki migration had to move artefacts whose locations are resolved by
*global* tools (obs-writer, `/observe`, `/reflect`, the session-start and
continuity protocols) serving 7 repos, of which only 2 are migrated. Instead
of a synchronised cutover, each tool was made to **prefer the new path**
(`wiki/…`) and **fall back to the legacy path** (`docs/notes/…`, `planning/…`).
Migrated repos pick up the new layout; unmigrated repos keep working unchanged;
each repo migrates on its own schedule.

**Generalises:** for a migration across shared tooling, prefer-new /
fallback-legacy beats a flag day. The session-start + continuity protocols
already had this shape (`wiki/continuity.md` → `planning/continuity.md`
fallback), which is exactly why moving PA's continuity broke nothing. Anchors:
`skills/reflect/SKILL.md` locate section; `agents/obs-writer.md` §1;
`global-claude-md/session-start-protocol.md`.

## 2026-05-29: The 24-tag wiki vocabulary, measured against the corpus

Validated the hand-curated 24-tag wiki vocabulary empirically rather than by
intuition (`scripts/analyse-wiki-vocabulary.py` over the ~29k-record memory
corpus + the 33 `notes/_inbox.md` candidates). Measurements: the corpus
auto-tag vocabulary is 28,282 tags, **68.2 % singletons**, only ~1,049 used
11+ times — radically long-tailed, which is the empirical justification for
keeping a separate small hand-curated wiki set. Per-wiki-tag corpus support
spans `coding-practices` 13.0 % down to `three-Ps`/`claude-md`/`scratchpad`
≈0.0 %. Two recurring themes have **no tag home**: agent-orchestration
(explicit `agent-orchestration` tag 52×, `proposer-verifier` 67×, cluster sum
913 usages / 327 tags; ~10 inbox candidates already naming
`notes/agent-orchestration.md`) and infrastructure/ops (`infrastructure`
124×, `deployment` 73×, cluster sum 1023 / 417; ~5 inbox candidates). Two
genuine redundancies fell out of the four-grouping split: `memory-systems`≡
`memory-system`, `three-Ps`⊂`provenance`. The corpus *head* (`data-pipeline`
1410, `reproducibility` 1128, `validation` 1008, `preregistration` 368) is
project-execution substance that correctly has **no** wiki tag — empirical
confirmation that the candidate-pool layer ≠ the surfacing layer.

**Generalises:** validate a controlled vocabulary / taxonomy against the
corpus it indexes before building tooling that depends on it — counts reveal
both dead tags and blind spots that intuition misses. Note the measurement
caveat: keyword-support % is a *conservative floor* because corpus auto-tags
are finer-grained than the coarse wiki tags, so read the numbers as relative
signal, not absolute coverage. Anchors:
`wiki/planning/wiki-vocabulary-validation-2026-05-29.md`;
`scripts/analyse-wiki-vocabulary.py` (`WIKI_TAG_EXPANSIONS` map).

## 2026-05-30: A design's quantitative premise can silently expire — re-measure before building on it

The Vector 2 design (2026-05-16) was built on the measured fact that only **8**
memories were `verified=true` corpus-wide, so its Stage 1 selector leaned on a
"promoted-recent fallback" to avoid an empty digest. Two weeks later, the first
dry-run against the live corpus measured **289 verified-true in the last 7 days
alone** — the v2 write-path hook had been populating `verified` far faster than
the design assumed. The fallback the design treated as load-bearing is now
near-vestigial. The design doc itself flagged the trip-wire ("re-measure if the
gap to current is >2 weeks") and it was exactly right.

**Generalises:** a design grounded in a corpus measurement carries an implicit
expiry. Before implementing against a months-old quantitative premise, re-run
the measurement — the cheapest possible step, and it can invert which code path
matters. Anchors: `wiki/planning/vector-2-design.md` §2, §6a item 3;
`scripts/digest-preview.py` (live before/after harness); session 2026-05-30.

## 2026-05-30: A "byte cap" on templated output is not unconditional — the fixed scaffolding is an irreducible floor

`digest.py`'s docstring promised the rendered digest is "guaranteed
`<= byte_budget`". The `/audit` (execution-verifying subagent) disproved it by
construction: `build_digest([], byte_budget=50)` returns 522 B, because the
fixed scaffolding (title, what-changed line, anti-confabulation reminder, depth
footer) is load-bearing and never trimmed. The cap only governs the *variable*
part (the entries). Latent at the 1,500 B default (scaffolding ≈ 1/3 of it),
but the *contract* was false. Fixed by stating the floor honestly rather than
over-claiming, plus sub-floor / tight-budget / multibyte cap tests.

**Generalises:** when a generator templates fixed framing around variable
content, any "hard cap" applies to the variable content above a fixed floor, not
to the whole output. State the floor; don't claim an unconditional bound a
fixed preamble makes impossible. Anchors: `scripts/digest.py`
(`DigestResult` / `build_digest` docstrings, `_assemble`); `tests/test_digest.py`
(`test_sub_floor_budget_returns_minimal_scaffolding`); session 2026-05-30.

## 2026-05-30: Audit subagents that *execute* catch contract bugs inspection misses

Running `/audit` on the new digest code with subagents instructed to
*adversarially execute* (construct inputs, run the code, observe) rather than
read found two real bugs that line-by-line reading would likely have rated
"looks fine": the scaffolding-floor cap violation (proven by running
`build_digest` at tiny budgets) and a greedy `break` that emptied the digest
when the highest-ranked entry was oversized (proven by a big-top-entry +
small-tail corpus). Both were size-vs-rank non-monotonicities that read as
correct.

**Generalises:** for invariants about sizes, ordering, or boundaries, an audit
that runs adversarial inputs beats one that reasons about the code — execution
surfaces the non-monotonic edge cases intuition smooths over. Worth telling
audit agents explicitly to execute, not just inspect. Anchors: session
2026-05-30 `/audit` run; `tests/test_digest.py`
(`test_oversized_top_entry_does_not_starve_digest`).

## 2026-05-30: Digesting one channel doesn't shrink the payload proportionally

Vector 2 PASS 2 cut the session-start *recall dump* 91 % (17.5 KB → 1.49 KB),
but the *total* session-start payload dropped only ~33 % (48,083 B → 32,078 B
measured live on amd-tower, inscriptions cwd) because the ~30 KB scratchpad —
out of scope ("Vector 2b") — was untouched. The headline component reduction
overstates the felt change.

**Generalises:** when you reduce one component of a composite payload, report
the aggregate, not the component. A 91 % cut on one channel can be a 33 % cut
overall; the global "compute aggregate implications" rule applies to byte
budgets, not just cost/time. State both numbers so the real lever (here: the
scratchpad, now Vector 2b) is visible. Anchors: `scripts/digest-preview.py`
(honest-aggregate note); session 2026-05-30 PASS 2 live smoke.

## 2026-05-30: A line-based threshold misses byte-based bloat

The hook's `SCRATCHPAD_WARN_LINES = 150` guard never fired even though
`data/scratchpad.md` had reached 29,268 B — because the bloat was bytes packed
into 99 long lines, not line count. The file injected ~29 KB into every session
with no warning. The guard measured the wrong dimension.

**Generalises:** a size guard should measure the dimension that actually
constrains the system. The cost here is *bytes injected into context*, so the
threshold should be byte-based; a line count is a proxy that breaks the moment
entries are long. Folded into the Vector 2b scope (flip the threshold to bytes).
Anchors: `hooks/session-start-retrieval.py` (`SCRATCHPAD_WARN_LINES`,
`load_scratchpad`); session 2026-05-30 scratchpad distillation
(29,268 → 15,484 B).
