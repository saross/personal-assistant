# Personal-Assistant — Continuity (Living Doc)

**Purpose:** cross-session state, pending work, things to verify, and a
session-by-session log. Updated at the end of each session, in place
(no new file per session). Points at the durable planning docs;
doesn't duplicate them.

**How to update at session end:**

1. **Mark done items** in place — replace `[ ]` with `[x]` plus
   the date (e.g. `[x] 2026-05-17 verified`); do **not** delete.
2. **Add new items** to the relevant section as `[ ]` with a brief
   note. Promote anything urgent to the "Things to verify next
   session" list.
3. **Append a new "Session log" entry** at the bottom (most recent
   first). One paragraph max, plus a short bullet list of artefacts
   touched (commits, planning docs, scripts).
4. **Carry forward open questions** in the "Open decisions /
   questions" section. Resolved decisions move down to the session
   log entry where they were made.

---

## Active workstreams

### A. Memory System v2 — *forward pipeline shipped 2026-05-16; Phases 4–6 superseded by rethink (workstream D) 2026-05-17*

The structural confabulation fix is live on amd-tower + zbook +
rpi-server. New memories now go through anchor verification and
confidence binding before they land in JSONL. See
`planning/memory-system-v2-design.md` for full design,
`planning/memory-system-v2-implementation-plan.md` for sequencing.

| Phase | Status |
|---|---|
| Phase 0 — operationalise tier-3 archive | **pending, priority promoted 2026-05-17** (unlocks open-science transcript search; see workstream D) |
| Phase 1 — schema + `/forget` + `/update` | **done 2026-05-16** (commits `03b86ad`, `d666470`) |
| Phase 2 — anchor verification + confidence binding | **done 2026-05-16** (commit `50e663b`) |
| Phase 3 — autonomous-save + correction markers | **done 2026-05-16** (commit `7078d39`) |
| Phase 4 — typed links + cross-session supersession (L3) | **superseded by workstream D 2026-05-17** — typed links reshaped as wiki-page links + working-notes references |
| Phase 5 — migration sweep + bulk-flag pass | **superseded by workstream D 2026-05-17** — migration sweep still valuable as backfill for `verified` field, but not gating anything |
| Phase 6 — extractor bake-off | **deprioritised 2026-05-17** — prior-art survey found write strategy contributes ~3–8 retrieval-accuracy points vs ~20 for retrieval; wrong lever |

### B. Session-start payload reduction (Vector 2 / injection issue) — *design landed 2026-05-17; implementation parked pending memory-system rethink (workstream D)*

Distinct from the v2 corpus work. The session-start hook injects
~43 KB of recall memories plus harness-injected auto-memory plus
skills listings plus tool schemas plus two CLAUDE.md files. Even
with the v2 confabulation fix shipped, an unverified high-volume
context injection can still drive subtle confabulation by priming
the model with stale or low-confidence specifics presented as
authoritative.

**Why this matters now:** Phase 2's anchor verification cleans the
write path; Vector 2 cleans the read/surfacing path. The two are
complementary — without Vector 2, even verified memories surfaced
authoritatively can drive primacy-effect errors.

**Status:**

- [x] 2026-05-15 Vector 2 explicitly acknowledged in design doc and
  impl plan; deferred to its own design pass
- [x] 2026-05-15 Vector 2 captured in
  `planning/memory-system-v2-future-extensions.md` section C with
  observed numbers + open questions for the eventual design
- [x] 2026-05-17 `planning/vector-2-design.md` landed. Hybrid digest +
  lazy depth, two-stage rollout (pre-/post-Phase-5), strict byte cap,
  six open questions captured.
- [ ] **Implementation parked** — Vector 2's hybrid direction is
  preserved but reshaped under the memory-system rethink (workstream D).
  Cross-project surfacing now via `notes/<topic>.md` wiki rather than
  pure semantic search.

**Open questions for the eventual design** (carried forward from
future-extensions.md):

- Lazy vs eager loading at session start
- Channel budget (suggest ≤4 KB for the retrieval hook)
- Anti-confabulation framing in the dump itself (de-weight or omit
  unverified entries now that the v2 `verified` field exists)
- Differential surfacing — only memories whose anchors still resolve

### C. PA infrastructure background (continuous)

Shawn runs PA infrastructure sessions as a *secondary* concurrent
context while his primary foreground is elsewhere (research, teaching,
or business work). **Do not lecture Shawn about focus-slot
allocation when this session is PA-infrastructure** — it is
deliberately background. Focus-slot accountability lives in
`tasks/FOCUS.md`; check it before mentioning slot pressure.

### D. Memory-system rethink + wiki formalisation — *design converged 2026-05-17, implementation pending*

Following a top-to-bottom review of the memory system (prompted by
Shawn's observation that the recall dump is large and ungrounded, the
3-tier escalation isn't firing, tier-3 connections are broken, and CC
rarely interacts with the system), the design converged on a
**four-artefact picture** with the memory corpus reframed as a
**candidate pool**, not the surfacing layer.

**The four-artefact picture:**

1. **`<project>/wiki/continuity.md`** — within-project cross-session state
2. **`<project>/wiki/working-notes.md` + `reflections/` + `user-observations.md`** — chronological/structured/meta observation layer
3. **`~/personal-assistant/notes/<topic>.md`** — cross-project curated topical knowledge (Karpathy-style wiki, flat directory + YAML frontmatter tags + `notes/index.md`)
4. **`data/scratchpad.md`** — protocol guardrails / principles (existing)

Plus: memory corpus as candidate pool (auto-extracted, noisy, feeds wiki
via cluster-and-carry at `/weekly-review`); transcript archive as
underlying record (Phase 0 unlocks topic-search).

**Two ritual moments knit the artefacts together:**

- **`/handoff`** (per session-close, in a project) — five steps: update
  continuity → capture observations → flag wiki candidates → user
  observations → commit. Protocol: `global-claude-md/handoff-protocol.md`.
- **`/weekly-review`** (existing, to be extended) — cluster-and-carry
  from candidate pools into curated wiki pages.

**Status:**

- [x] 2026-05-17 Prior-art survey complete (`prior-art-scout`) — field
  has converged on tiered architectures + session-end handoff docs +
  curation review; recall-trigger problem is unsolved field-wide;
  Karpathy wiki pattern validates the topic-notes idea. Some arXiv IDs
  in the report (2603.*) flagged as suspect — pre-date today.
- [x] 2026-05-17 Provenance audit complete (`general-purpose`) —
  Three Ps vocabulary already in `session.meta.json` schema (quiet
  win); summary fields are empty strings (quiet embarrassment); three
  specific gaps identified (see pending tasks).
- [x] 2026-05-17 `global-claude-md/continuity-protocol.md` landed
- [x] 2026-05-17 `global-claude-md/handoff-protocol.md` landed
- [x] 2026-05-17 `planning/vector-2-design.md` landed (now reshaped under workstream D, see workstream B)
- [x] 2026-05-17 Craft entry on session-wind-down trigger
  (`notes/working-practices.md`)
- [ ] **Implement `/handoff` as actual skill** — currently just a
  protocol doc; needs the skill file in `commands/` directory
- [ ] **Pilot wiki migration on personal-assistant** — move `planning/`
  + `docs/` under `wiki/`; add `wiki/index.md`; cleanest project to
  pilot because it has the most planning artefacts
- [ ] **Sketch `notes/index.md` + initial wiki-tag vocabulary** — based
  on topics that actually appear in your projects (cluster the corpus
  first); ~30 min design exercise
- [ ] **Extend `/weekly-review` with cluster-and-carry curation step**
  — pull week's new memories, cluster by topic, surface candidates,
  draft wiki-page diffs for review
- [ ] **Close 3 provenance audit gaps** — see pending tasks

### F. Auto-metadata production switch — Gemini Flex + tuned prompt (new 2026-05-18; wire-up landed 2026-05-18, backfill gated on review)

The 2026-05-18 bake-off established **Gemini 3 Flash Preview (Flex
tier) + a tuned full-transcript prompt** as the right production
choice on every dimension that matters:

| Dimension | Outcome |
|---|---|
| Quality (vs Haiku, 42 cells) | base prompt: 1/42 G; v1 tuned: 12/42 G; v2 tuned + title rule: 17–18/42 G — Gemini wins meaningfully |
| Reliability | Gemini 10/10 sessions; Haiku 7/10 (3 long-bin context overruns at 200K) |
| Cost (per session, 7 in-window) | Gemini Flex ~$0.014; Haiku Batch ~$0.029 — Gemini ~½ |
| Architectural complexity | single one-shot call vs Haiku-with-chunking + cross-chunk stitching |
| Long sessions | Gemini handles 264K-token sessions natively; no chunking |

**Production prompt (shipping):** bundled as package data at
`cc_session_toolkit/prompts/auto_metadata.md` (copy of bake-off-winner
`prompt-gemini-v2.md`, 477 lines / ~25.6 KB / ~6,400 tokens). Override
the bundled prompt with env var `CC_AUTO_METADATA_PROMPT_PATH`.

**Status:**

- [x] 2026-05-18 Bake-off across 5 rounds; verdict landed
- [x] 2026-05-18 `prompt-gemini-v2.md` finalised
- [x] 2026-05-18 **F1: Gemini Flex wired into
  `archive.py:generate_auto_metadata()`.** Full-transcript path via the
  new `cc_session_toolkit.transcript_text` module (ported from PA's
  `scripts/extract-transcript-text.py`); `thinking_budget=0`,
  `service_tier="flex"`, 503-retry with (30s, 60s, 120s) backoff.
  Sampled-message machinery (`_is_meta_message`, `_META_*`,
  `_ensure_anthropic_api_key`) all removed. `re` import dropped.
  Optional dep flipped from `anthropic>=0.40` to `google-genai>=2.3`.
- [x] 2026-05-18 **F2: `EXTRACTOR_MODEL_ID` switched** from
  `claude-haiku-4-5-20251001` to `gemini-3-flash-preview` (still
  Preview — see GA-rename watch below).
- [x] 2026-05-18 **PA venv reinstalled with `pip install -e ~/Code/cc-session-toolkit`**
  so the hook picks up the new path on next SessionEnd.
- [x] 2026-05-18 **`scripts/backfill-session-metadata.py` updated** —
  uses `_ensure_gemini_api_key`; cost line shows ~$0.027/session;
  `update_metadata` now writes Three Ps natively (was preserving empty
  defaults from prior Haiku schema).
- [ ] **F3: Backfill 307 historic sessions** — **BLOCKED on Shawn's
  approval after live-output review.** Est. ~$8.30 (Gemini Flex
  one-shot, ~$0.027/session). Requires explicit gate approval per the
  API Call Review Gate in `~/.claude/CLAUDE.md`.
- [ ] **F4: QA pass on ~20 sampled backfill outputs** — gates declaring
  workstream F done. Compare against bake-off rubrics
  (`review-rubric-populated-final.md`).
- [ ] **Re-verify Gemini model ID at GA** — currently "Preview"; expect
  rename (`gemini-3-flash`?). Set a calendar nudge for next major
  release.

**What Shawn does after a few SessionEnds fire:**

1. Wait for ~2–3 real SessionEnds to fire after `pip install -e` took
   effect. Each end-of-session triggers
   `cc_session_toolkit.cli archive --auto-metadata` via the
   PreCompact / SessionEnd hooks; the new Gemini Flex path runs
   automatically.
2. Spot-check the outputs by reading the new `session.meta.json`
   files. Each one is under `~/cc-archives/<project>/<dated-session>/session.meta.json`.
   Look at:
   - `auto_generated.title` — names of files, people, projects
     preserved? Five-to-ten-word descriptive title?
   - `auto_generated.purpose` — captures the *why*, not just *what*?
   - `auto_generated.tags` — lowercase-hyphenated, 2–5 items, on-topic?
   - `three_ps.{prompt_summary, process_summary, provenance_summary}` —
     populated (not empty strings)? Grounded in actual session events?
     User-voice paraphrase rather than CC's? Sequenced process
     narrative? Rejected alternatives preserved?
3. Cross-reference against the bake-off rubrics at
   `data/experiments/bake-off-metadata-2026-05-18/review-rubric-populated-final.md`
   so you have a calibrated sense of the v2 prompt's known quality
   profile.
4. Also check `data/logs/auto-metadata.log` for any Gemini API errors
   (503 preemptions, JSON parse failures). The hook-side handler
   collapses failures to `None` rather than aborting the archive, so
   they won't show up as user-visible breakage.
5. When satisfied: explicitly approve the F3 backfill. Phrase that
   triggers the gate: e.g. *"approved: run F3 backfill"*. CC will
   then run `python scripts/backfill-session-metadata.py --archive-root <root>`
   on the ~307 sessions and report back per the API Call Review Gate
   protocol.
6. If outputs look wrong (hallucinated names, empty Three Ps,
   continued-conversation failure mode): **do not approve F3**. The
   bundled prompt is overridable via `CC_AUTO_METADATA_PROMPT_PATH`;
   iterate on the prompt and re-fire before scaling.

Bake-off artefacts (all in `data/experiments/bake-off-metadata-2026-05-18/`):
- `sample-manifest.json` (10 sessions, 4/3/3 stratified by length, all <190K tokens)
- `prompt.md` (base / round-1+2)
- `prompt-gemini.md` (round-3 tuned)
- `prompt-gemini-v2.md` (round-4+5; production-candidate, *original* — the shipping copy lives in the toolkit package data)
- `LAUNCH-PLAN.md`
- Four populated rubrics (`review-rubric-populated*.md`)
- Archived response sets (`responses-round-1/`, `responses-gemini-baseline/`, `responses-gemini-tuned-v1/`, `responses-gemini-v2-round-4/`, `responses/`)

Bake-off spend: ~$1.45 across 5 Gemini rounds + 2 Haiku batches (29% of $5 cap).

### E. Open-science / RDA IG (Documenting GenAI Interactions in Research)

Shawn co-chairs an RDA Interest Group with Brian Ballsun-Stanton.
Target IG submission August 2026; first formal meeting RDA P26; WG
launch target RDA P28 (2027). Framework: Three Ps (Prompt, Process,
Provenance), extending FAIR / RO-Crate. Candidate Tier 2 output
"Research Grimoires Framework" maps directly onto the `notes/<topic>.md`
wiki pattern (workstream D).

The PA system is plausibly a proof-of-concept implementation of the
IG framework. Reference docs:
`~/personal-assistant/docs/open-science/RDA_IG_Statement_of_Work.docx`
and `RDA_IG_Summary_and_Description.docx`. Provenance audit
(workstream D) was first concrete alignment action.

### G. Style-guide construction (multi-genre, academic kick-off) — *agent built + run-1 complete + prior-art surveyed 2026-05-22; reconciliation + fork-vs-build pending*

`corpus-style-analyser` agent (global, at
`~/.claude/agents/corpus-style-analyser.md`) empirically derives a
writing style guide from a Zotero-cataloged corpus with strict
anti-confabulation discipline: every claim carries a count, ≥2 verbatim
quotations with paper key + sentence locator, and an explicit status
field (`attested` / `attested-rarely` / `absent-when-searched` /
`aspirational`). Designed for re-use across genres (academic /
Substack / business / teaching) and across LLM model versions.

| Phase | Status |
|---|---|
| Agent definition | done 2026-05-22 |
| Run-1 (academic) | done 2026-05-22 — `notes/style-guides/academic/style-guide-academic-2026-05-22.md` (51 KB; 18 papers, 139,105 words) |
| Prior-art-scout + verifier pair | done 2026-05-22 — `notes/prior-art-runs/llm-style-alignment-2026-05-22.md` (18 candidates; 3 hard failures corrected; verifier-pair smoke-test passed) |
| Reconciliation of aspirational section vs prior conscious style guides | **pending** (queued as inbox follow-up 2026-05-22) |
| Fork-vs-build decision on `github.com/Hiro-Inagawa/write-like-me` | **pending** — only verified open-source analogue; MIT, Python, last pushed 2026-05-10, multi-voice profile support |
| Methodology incorporations for v2 agent revision (Author Writing Sheet aggregation, Biber MDA vocabulary, Panickssery reverse-prompt, "Catch Me If You Can" evaluation suite) | **pending** |
| Substack / business / teaching genre runs | not started |

**Key prior-art findings (post-verification):**

1. **The `attested / absent-when-searched / aspirational` schema is
   genuinely novel** — does not appear in any of 18 verified candidates
   spanning academic papers (2024–2026), open-source tools, or
   commercial products. The `absent-when-searched` status in
   particular (treating a deliberate non-finding as data) has no
   prior-art equivalent.
2. **One real fork candidate exists**: `Hiro-Inagawa/write-like-me`
   builds voice profiles from corpus measurements with multi-voice
   support. The proposer's draft listed a wrong URL (a topic
   aggregator page); the verifier surfaced the actual repository.
   Reading its README + source decides whether to fork it (add
   provenance/attestation/Zotero anchors on top), compose with it
   (use as a feature-extraction component), or continue
   independently.
3. **Three methodology lifts worth incorporating** (no library
   dependencies needed):
   - Author Writing Sheet (Kumar et al. 2025, arXiv 2502.13028) —
     claim-evidence aggregation across documents.
   - Biber Multidimensional Analysis (Yang & Carpuat 2025,
     arXiv 2505.00679) — principled, citable vocabulary for
     section labels in an academic style guide.
   - Panickssery reverse-prompt pattern (blog) — adds a few-shot
     exemplar block at near-zero cost.
4. **Evaluation suite available**: "Catch Me If You Can" four-metric
   ensemble (Wang et al. 2025, arXiv 2509.14543) — best available
   way to measure whether the style guide actually moves LLM
   output toward Shawn's voice. Relevant for the longitudinal
   cross-model-version comparison built into the agent's design.

### H. Agent-orchestration upskilling — closed-loop proposer-verifier pairs

Meta-workstream tracking the agent-design discipline that emerged
from the 2026-05-20→22 upskilling thread (see craft notebook entries
2026-04-18 and 2026-05-22). The pattern is: every proposer agent that
makes verifiable claims gets a verifier; the contract between them is
a machine-readable structured file (`claims.jsonl` / `corrections.jsonl`),
not free-form markdown; a thin driver loops proposer → verifier →
re-invoke proposer with corrections until PASS or termination
condition. Cost/capacity discipline (workstream item #4) is deferred
until first non-CC API spend.

| Pair | Status | Closed loop? |
|---|---|---|
| `lit-scout` + `lit-scout-verifier` | single-round shipped 2026-04-19; closed-loop wired 2026-05-22 — both sides emit machine-readable blocks via HTML-comment markers (sub-agent Write of report files is blocked, so the driver extracts inline); `/lit-scout-iterate` driver added | **yes** — closed; smoke-test pending |
| `data-profile-proposer` + `data-profile-verifier` | renamed + closed-loop wired 2026-05-22 (was `data-profile-scout`); `corrections.jsonl` emission added; iterate-mode on proposer; `/data-profile-iterate` driver; **smoke-tested on LIRE v3.0 2026-05-22** — PARTIAL verdict on iter-0 (81/83 PASS, 2 PARTIAL, 0 FAIL), loop terminated per policy without entering iterate mode; `documentation_defect` status added to the contract from the smoke-test calibration (commit `2e89bd1`) | **yes** — closed; plumbing confirmed; iterate-mode behaviour still unexercised |
| `prior-art-scout` + `prior-art-scout-verifier` | pair built + smoke-tested on style-guide query 2026-05-22 (verifier ran via general-purpose fallback as the agent was created mid-session) | **no** — contract is markdown; retrofit deferred until ≥1 closed-loop pair has real-run experience |

**Live next-steps across the closed-loop pairs:**

- [x] 2026-05-22 **Smoke-test `/data-profile-iterate` on a real
  dataset — partial outcome.** Ran on LIRE v3.0 (182,853 rows × 64
  cols) with config at `~/Code/inscriptions/runs/2026-05-22-data-profile-smoke/config.json`;
  workspace at `…/iterate-20260522-162723/`. Iter-0 returned PARTIAL
  (81 PASS, 2 PARTIAL, 0 FAIL, 0 unverifiable) and the loop
  terminated per driver policy without entering iterate mode.
  Plumbing confirmed end-to-end: proposer emits deterministic
  `claim_id`s; verifier emits the `corrections.jsonl` contract;
  driver reads `verdict.md` and routes correctly. Verifier flagged
  both group-count claims (`count-province-group-count`,
  `count-urban-area-group-count`) as `source_method`-string
  misdescriptions — strictly beyond the 0.5 % exact-count tolerance
  (1.54 % relative) but the verifier classified them as PARTIAL low
  rather than FAIL because the values were internally consistent
  with the report's tables. This judgement call exposed a real
  spec gap which we closed in-session by adding a
  `documentation_defect` status (see next bullet).
- [ ] **Synthetic-FAIL test to exercise iterate mode.** The
  bigger gap exposed by 2026-05-22's smoke test: the closed loop's
  actual *raison d'être* — iterate mode handling FAIL with
  `fix_hint` re-derivation — has not been tested on real data. The
  LIRE corpus produced 0 FAIL claims (it is in fact clean), so the
  proposer was never re-invoked with `previous_corrections_path`.
  Options for a follow-up test: (a) deliberately inject a buggy
  proposer prompt that under-counts on purpose, (b) use a known-
  noisy dataset where genuine FAIL is likely, (c) write a unit-
  level test that hands the proposer a synthetic `corrections.jsonl`
  with FAIL rows and confirms iterate mode rewires correctly. Do
  this *before* generalising the closed-loop pattern to any other
  pair (`lit-scout` retrofit, `prior-art-scout` lift).
- [x] 2026-05-22 **Added `documentation_defect` status to the
  verifier/proposer contract.** Carved out of the PARTIAL band for
  source_method-string defects where the numeric value reproduces
  the report's tables but the `source_method` string describes a
  different procedure. Non-iterating (rolls up to PARTIAL aggregate
  verdict); proposer's iterate-mode partition handles it via string
  substitution on `source_method` with no value re-derivation.
  Companion tightening on the proposer side requires
  `source_method` strings to state `dropna` (and other
  result-affecting default kwargs) explicitly at write time.
  Commit `2e89bd1`. Spec edits in
  `agents/data-profile-verifier.md` (3 hunks) and
  `agents/data-profile-proposer.md` (2 hunks).
- [ ] **Smoke-test `/lit-scout-iterate` on a real query.** Pick a
  bibliography target where iteration value is high — e.g., a
  topic with mixed-quality citations on Google Scholar, or one
  where the prior `/lit-scout` runs surfaced material
  confabulations. Capture: terminal verdict, iteration count,
  which fields most often required correction (authors / year /
  title / citation_count / doi_resolves), how many rows the
  iterate-mode `doi_resolves` removal path eliminated.
- [ ] **Calibrate the severity rubric across both pairs.** Current
  bands are rule-of-thumb (data-profile: high ≥10 % drift /
  decision-changing; medium ≥5× tolerance; low at the boundary.
  lit-scout: high = wrong first author / DOI fabricated / wrong
  paper at DOI; medium = >25 % citation drift / material title
  difference; low = borderline drift). Tighten against real
  iteration outcomes. **Note 2026-05-22:** the data-profile smoke
  test exercised only `severity: low` (and only via the new
  `documentation_defect` path) — high/medium calibration is still
  entirely on paper. Tied to the synthetic-FAIL test above.
- [ ] **Decide whether to quantify "how partial" precisely.** Both
  pairs currently use rule-of-thumb PARTIAL bands. A finer metric
  (continuous "how-partial" score) could let the driver
  auto-iterate on PARTIAL above a threshold. Defer until ≥3 real
  runs surface a pattern.
- [ ] **Lift to `prior-art-scout`** (the last remaining unconverted
  pair). Same shape as lit-scout retrofit. Lower priority because
  the existing pair already catches material confabulations via
  markdown contract; the closed-loop gain is auto-iteration on
  FAIL rather than detection per se.

**Reference docs for the closed-loop pairs:**

- `/data-profile-iterate` driver: `~/personal-assistant/commands/data-profile-iterate.md`
- data-profile proposer: `~/personal-assistant/agents/data-profile-proposer.md`
- data-profile verifier: `~/personal-assistant/agents/data-profile-verifier.md`
- `/lit-scout-iterate` driver: `~/personal-assistant/commands/lit-scout-iterate.md`
- lit-scout proposer: `~/personal-assistant/agents/lit-scout.md`
- lit-scout verifier: `~/personal-assistant/agents/lit-scout-verifier.md`
- Architecture rationale + 2×2 orchestration grid: craft notebook
  entries 2026-04-18 ("Agent definitions are specifications…",
  "Orchestration patterns are a 2×2…", "Subagents are context
  management…")
- Inline-block transport rationale (lit-scout specific): sub-agent
  Write of `.md` files is blocked per 2026-04-19 v4.x evaluation;
  closed-loop transport uses fenced `jsonl` blocks with HTML-comment
  markers extracted by the driver.

---

## Things to verify on next session (priority queue)

Read these *before* starting new work. Most should take <5 min each.

- [x] 2026-05-17 **First-firing of v2 extraction hook.** Phase 1–3 landed
  2026-05-16; the next `SessionEnd` / `PreCompact` is the first live
  test of `anchor_verify` + confidence binding in the hook chain.
  Check `~/personal-assistant/logs/extraction.log` for traceback
  noise. Query:
  ```sql
  SELECT COUNT(*) FILTER (WHERE verified IS NOT NULL) AS verified_set,
         COUNT(*) FILTER (WHERE anchors != '[]'::jsonb) AS with_anchors,
         COUNT(*) FILTER (WHERE created_at > '2026-05-16T07:00:00+00:00') AS post_v2
  FROM memories;
  ```
  `verified_set` should equal `post_v2`. `with_anchors / post_v2`
  is the rate at which Haiku is actually producing anchors per the
  updated prompt — a low rate is a signal to revisit the prompt.
- [x] 2026-05-17 **`/recall verified:true`** spot-check: a handful of post-v2
  memories should show `verified: true` (or `pending`); `verified:
  false` would mean Haiku invented an anchor that didn't resolve.
- [x] 2026-05-17 **zbook + rpi-server hook health.** Both have v2 code; only
  amd-tower has Postgres so verification only writes to the DB on
  amd-tower. Check that hook firings on zbook didn't choke.
- [x] 2026-05-18 **First firing of v3 extraction hook**. 13 post-v3 memories
  (`created_at > 2026-05-18T00:00`), all 13 with both
  `source_message_uuid` *and* `extractor_model_id` populated; every
  one used `claude-haiku-4-5-20251001` as expected. No
  schema/sync/anchor tracebacks in `logs/extraction.log`. Only blemish
  was a single transient `529 overloaded_error` at 13:38:59
  (Anthropic-side capacity, request_id `req_011Cb9LZzm1ph8knL9g9iP2s`)
  caught cleanly by the existing handler; next firing at 14:11
  succeeded. Schema v3 + Gaps 1+3 pipeline is healthy.
- [x] 2026-05-19 **First firing of Gemini Flex auto-metadata path**
  (workstream F1+F2). Verified on the pa-data session
  `9e6d3a24-dd08-42cf-91b0-3d7a01dbaac4` (Sat→Sun rollover, 76,972
  content tokens, single one-shot call, ~5s wall). Output at
  `~/cc-archives/pa-data/2026-05-17T12-44_wire-gemini-flex-auto-metadata-and/session.meta.json`
  passes every quality gate: descriptive title with named entities,
  purpose captures the why, 5 lowercase-hyphenated tags, all three
  Three Ps populated and grounded, `extractor_model_id` =
  `gemini-3-flash-preview`. Sidecar absent on this firing (expected —
  hook landed mid-session, so no sidecar existed at start). Today's
  session will be the first with full `commit_at_start` provenance.
  Zero log noise; the only entries in `auto-metadata.log` are this
  real firing plus test-fixture errors from `pytest`.
- [ ] **First firing of v3 hook with C2 sentinel + C3 cursor lock**
  (new 2026-05-20, audit follow-ups). After the C2/C3 commits land
  in PA + pa-data, next SessionEnd / PreCompact / Stop will exercise:
  - **Cursor flock** at `data/memories/extraction-cursor.json.lock`
    — file is created the first time `cursor_file_lock()` runs;
    `ls -la data/memories/` should show it after a couple firings.
  - **Transient-error sentinel** — on a 529 / 503 / network-timeout
    from Anthropic, look for the new log line "Skipping cursor
    advance due to transient API error (session ...)". If that
    fires, the next hook run should re-process the same window. If
    you don't see a transient error in normal operation, that's
    fine — the path is exercised by tests.
  - **PA venv re-install** is NOT required for the hook changes
    (extraction-hook.py is invoked directly, not via the toolkit).
    But the toolkit changes from 2026-05-19+20 (transcript_text,
    archive.py null guards, etc.) DO require a venv that picks them
    up — already editable-installed on amd-tower, still pinned on
    zbook + rpi-server (defer until you next use those machines).
  - **Model ID GA-rename watch** (carry-over): if Google renames
    `gemini-3-flash-preview` → `gemini-3-flash` at GA, the call will
    start failing with "model not found". Bump
    `cc_session_toolkit/config.py:EXTRACTOR_MODEL_ID`.
- [x] 2026-05-21 **rpi-server NVMe destination path + free space.**
  Resolved. Destination is `~/mnt/rpi-shares/cc-archives-consolidated/`
  (= `rpi-server:/opt/encrypted/workspace/shares/cc-archives-consolidated/`),
  mounted on working machines via the pre-existing `mount-rpi-shares`
  SSHFS alias (`~/.bash_aliases:9`). Encrypted SSD share, 393 GB total
  capacity, **300 GB available** at mount time (df reading; ~322 GB
  matched Shawn's check — small precision difference, no concern).
  Generous headroom for the ~1.45 GB initial consolidation. Folder
  structure laid out at the destination: share-root README + an
  inner `cc-archives-consolidated/README.md` documenting the layout
  contract, write-side rules, sizing, and cross-references; reserved
  subdirs `_indexes/` (for the future session_id resolver/manifests)
  and `manual-exports/` (for the 182 pre-Dec-2025 `.txt` exports).
  SSHFS-vs-NFS decision resolved in favour of SSHFS — already wired
  via existing alias, no server-side config required, performance
  fine for archival writes. Persistence handled by re-running
  `mount-rpi-shares` per session (per the existing convention; no
  fstab entry or systemd unit needed).

## Pending tasks (cross-session)

These survive across sessions. Mark `[x]` with date when done.

- [ ] **Backup cleanup**: remove one of the two pre-v2 backups (in
  `data/archive/pre-v2/` or `~/cc-archives/pre-v2/` on rpi-server)
  after ≥1 week of stable v2 operation. Default removal target:
  pa-data copy (keeps git lean; the 96 MB `claude_memories.dump` is
  the bulk).
- [ ] **Pre-consolidation inventory (amd-tower)** — **done
  2026-05-20**: see `planning/archive-inventory-2026-05-20.md` for
  the full picture. Headline numbers (amd-tower only; zbook +
  rpi-server out of scope):
  - **307 unique main-thread session IDs** total across all
    locations (the earlier 32-session figure was the
    archived-and-needing-F3 subset, not the full population).
  - **~1.97 GB** across 1,360 transcript files (433 main + 927
    subagent). Real on-disk dedup-aware estimate for the
    consolidated destination: **~1.45 GB** (excluding the
    LLM-History-Paper LFS contents that need pulling from
    git-lfs storage first).
  - **Zero genuine content conflicts.** 170 main-thread SIDs
    appear in >1 location, all explained by live-uncompressed
    vs archive-gzip (or LFS-pointer vs worktree-real-bytes for
    map-reader-llm).
  - **32 archived sessions need F3 backfill** (matches existing
    F3 estimate of $1.26 mean / $2.79 p90).
  - **61 live-only sessions** never archived (~177 MB
    uncompressed). Sweep these into archive before consolidation
    so they get auto-metadata at write time.
  - **182 manual `.txt` exports** (Oct–Nov 2025) under three
    `archive/cc-interactions/` dirs (~10.7 MB). Out of scope for
    F3; need their own `manual-exports/` subdir in the
    consolidated archive.
- [ ] **Phase 0 — focused session**: archive layout consolidation.
  Sub-items (revised 2026-05-20 — rpi-server is now mount-only, NOT
  install-target; see architectural-decision below).

  **Progress as of 2026-05-22** (consolidation arc complete):

  - [x] 2026-05-22 **Step 1** — LFS pull on map-reader-llm +
    LLM-History-Paper; 535 MB / 184 LFS objects resolved; SHA-verified.
  - [x] 2026-05-21 **Step 3** — Mount rpi-server SSD share via existing
    `mount-rpi-shares` alias.
  - [x] 2026-05-22 **Step 4a** — amd-tower → rpi-shares rsync; 1.4 GB
    consolidated; 4/4 SHA spot-checks match.
  - [x] 2026-05-22 **Step 4b** — zbook → rpi-shares rsync; +1.7 GB
    (Pass 1: zbook's `~/cc-archives/`, 2,073 files / 1.89 GB;
    Pass 2: per-project cc-sessions, 0 new files; Pass 3: per-project
    `cc-interactions/` → `manual-exports/`, 185 files / 10.8 MB).
    Sapphire inventoried, found clean (worktree stubs only).
  - [x] 2026-05-22 **Step 5** — Manual exports parked under
    `manual-exports/<project>/` (183 .txt files / ~15 MB across
    blue-mountains, fieldmark-docs-staging, llm-reproducibility).
  - [x] 2026-05-22 **Step 4.5 (added) — Layout cleanup** —
    sub-categories nested under parent projects (`theseus-ship/` under
    `LLM-History-Paper/`; `vlm-burial-mound-detection/` under
    `map-reader-llm/`); non-session artefacts quarantined to
    `_legacy-archive/`; cwd-derived buckets quarantined to `_misc-cwd/`;
    3 new READMEs published on the mount; b80b94c6 SHA-divergence
    triaged (not divergence — `/export`-vs-auto-archive content-equiv
    pattern instance).

  **Consolidation arc complete** — total 3.1 GB at the destination,
  594 `session.jsonl*` files across 16 project_ids, 297 GB mount
  headroom. Still pending in Phase 0:

  - [ ] **Step 2** — Gemini Flex sweep of unarchived live JSONLs
    (was scoped to amd-tower's 61 per the 2026-05-20 inventory; the
    2026-05-22 cross-machine verifier surfaced a much larger pool:
    1,024 + 2,043 + 17 = 3,084 live JSONLs across amd-tower + zbook +
    sapphire). **API gate to be re-presented with the revised scope
    + cost envelope.**
  - [ ] **Steps 6-10** — `git lfs untrack`, `git rm --cached
    archive/cc-sessions/` + gitignore in every project repo,
    daily-sync.sh rsync step, `scripts/resolve_session_id.py`,
    indexing pattern.
  - [ ] **Content-equivalence dedup pass** (new follow-up 2026-05-22) —
    `/export`-era duplicates inside `~/cc-archives/` ancestry now living
    in the consolidated store. SHA dedup misses these; tractable via
    file-extension-and-co-presence-within-session-dir as a marker.
    Lower priority; cautious approach to avoid losing content that
    only exists in the `/export` framing.

  Original step definitions below (Steps 1, 3, 4, 5 retained for
  historical context — execution details captured above):

  **Step 1 — Resolve Git LFS contents.** Two projects currently store
  transcripts via Git LFS, which means the per-project archive layer
  holds pointer stubs rather than real bytes. The toolkit's backfill
  cannot read pointer stubs; consolidation cannot rsync them safely.
  Per-project commands:

  ```bash
  # map-reader-llm (final-stages code, near paper-writing transition)
  cd ~/Code/map-reader-llm && git lfs pull
  # Verify: the per-project archive's bytes should now match the
  # worktree archive's bytes (per the 2026-05-20 inventory finding
  # that the worktree holds canonical content). Spot-check 3-5
  # session IDs by comparing SHA-256 between
  # archive/cc-sessions/<...>/session.jsonl.gz
  # and
  # .claude/worktrees/agent-a59a9dae0bff3f27b/archive/cc-sessions/<...>/session.jsonl.gz

  # LLM-History-Paper (49 pointer stubs in archive/cc-sessions/)
  cd ~/Code/LLM-History-Paper && git lfs pull
  # Verify: stub files now have real gzip magic bytes (00 1f 8b ...)
  # rather than the LFS pointer-text format ("version https://git-lfs...").
  ```

  This step is **read-only on the remotes** — `git lfs pull` only
  fetches LFS object bytes to the local cache and smudges them into
  the working tree. No history changes, no risk to other clones.

  **Step 2 — Sweep the 61 unarchived live sessions.** Per the
  2026-05-20 inventory, amd-tower has 61 main-thread sessions
  present in `~/.claude/projects/*.jsonl` with no corresponding
  archive entry. Each must go through the archive hook so it
  receives the current `session.meta.json` contract + Gemini Flex
  auto-metadata at write time (avoids inflating the F3 scope from
  32 → 93 and saves ~60 × $0.04 = ~$2.40 vs. backfilling later).

  ```bash
  # Approach: iterate the live JSONLs, identify the unarchived
  # subset (per inventory), and invoke the toolkit's archive CLI
  # for each. The exact loop depends on whether the inventory
  # produced a list of session_ids — check
  # planning/archive-inventory-2026-05-20.md for the explicit
  # paths or session_ids of the 61 live-onlys.
  ```

  **Step 3 — Mount rpi-server SSD share.** Resolved 2026-05-21.
  Run the existing alias:

  ```bash
  mount-rpi-shares
  # = sshfs -o compression=no,ServerAliveInterval=15,reconnect \
  #         shawn@rpi-server:/opt/encrypted/workspace/shares \
  #         ~/mnt/rpi-shares
  # Confirm:
  df -h ~/mnt/rpi-shares
  # Expect: shawn@rpi-server:/opt/encrypted/workspace/shares 393G ... 300G ... /home/shawn/mnt/rpi-shares
  ```

  Per-session re-mount via the alias (no fstab entry, no systemd
  unit — keep it simple, matches the existing `mount-rpi-vantec` /
  `mount-rpi-qnap` convention). Note the silent-empty-dir failure
  mode: if the SSHFS mount is not active, `~/mnt/rpi-shares/`
  appears as a regular empty local directory, which would route
  writes to amd-tower's disk rather than rpi-server. Always
  `df -h` to confirm the mount before writing in any script.

  **Step 4 — rsync sources to mounted destination.** One location
  at a time, verify per pass. Target structure:
  `~/mnt/rpi-shares/cc-archives-consolidated/<project>/<session>/`.
  Source order (most-canonical first):

  ```bash
  # 1. The current per-project archive (post-LFS-pull)
  rsync -av ~/Code/<project>/archive/cc-sessions/ \
        ~/mnt/rpi-shares/cc-archives-consolidated/

  # 2. The legacy global archive (~/cc-archives/) — only sessions
  #    not already present in the per-project layer
  rsync -av --ignore-existing ~/cc-archives/ \
        ~/mnt/rpi-shares/cc-archives-consolidated/

  # 3. The pa-data submodule's archive (data/archive/cc-sessions/)
  rsync -av --ignore-existing \
        ~/personal-assistant/data/archive/cc-sessions/ \
        ~/mnt/rpi-shares/cc-archives-consolidated/

  # 4. The map-reader-llm worktree archive (canonical for that project)
  #    — only needed if the LFS-pull in Step 1 didn't fully restore the
  #    per-project layer to match the worktree.
  ```

  After each rsync, spot-check: `du -sh` the destination, count
  `session.jsonl(.gz)` files vs. expected, sample 2-3 SHA-256s.

  **Step 5 — Park the 182 manual `.txt` exports.** Create
  `~/mnt/rpi-shares/cc-archives-consolidated/manual-exports/<project>/`
  and rsync the three `archive/cc-interactions/` dirs into it. Add a
  README explaining: pre-December-2025 manual exports, different
  format, not F3-eligible, retained as research-provenance artefacts.

  **Step 6 — De-track Git LFS for `archive/cc-sessions/` in the two
  affected project repos.** Non-destructive: stops new files from
  going to LFS; existing history-resident pointers are left alone.
  Per-project:

  ```bash
  cd ~/Code/map-reader-llm  # then LLM-History-Paper
  git lfs untrack "archive/cc-sessions/**"
  # .gitattributes now has the pattern removed; commit the change:
  git add .gitattributes
  git commit -m "chore(lfs): stop tracking archive/cc-sessions via LFS"
  ```

  **Step 7 — Remove `archive/cc-sessions/` from each project repo
  + gitignore the path.** This is the architectural fix that makes
  the LFS de-tracking permanent: transcripts no longer live in
  project repos at all, only on the rpi-server mount.

  ```bash
  cd ~/Code/<project>
  # Verify the consolidated copy on the mount is byte-identical
  # to the project copy before removing the project copy.
  diff -qr archive/cc-sessions/ \
       ~/mnt/rpi-shares/cc-archives-consolidated/<project>/
  # If clean, remove from the index (does NOT delete from disk yet):
  git rm -r --cached archive/cc-sessions/
  echo "archive/cc-sessions/" >> .gitignore
  git add .gitignore
  git commit -m "chore: move archive/cc-sessions to consolidated mount"
  # Now safe to delete the on-disk copy:
  rm -rf archive/cc-sessions/
  ```

  Apply to all projects with an `archive/cc-sessions/`, not only
  the LFS ones — this is the new architecture for every project.

  **Step 8 — Add rsync step to `daily-sync.sh`** (working-machine
  side only — pushes new local archive writes to the mounted
  rpi-server NVMe). Local hook should keep writing to
  `~/cc-archives/<project>/<session>/` (the legacy global path) as
  its scratch destination; `daily-sync.sh` moves the day's new
  archives to the mounted consolidated location, then prunes the
  local scratch.

  **Step 9 — Build `scripts/resolve_session_id.py`** (cross-machine
  resolver — runs on the working machine, queries the mounted
  consolidated archive's index).

  **Step 10 — Decide on indexing pattern: working-machine-driven
  only.** rpi-server has no toolkit, no cron, no Python env, so
  indexing must happen on the working machine writing to the
  mounted destination. (Was previously "rpi-side cron vs
  working-machine SSHFS-mounted index" — revised.)

  **Deferred to post-journal-submission**: `git lfs migrate export
  --include="archive/cc-sessions/**" --everything` in the two
  affected repos, to fully purge LFS pointer stubs from git history.
  This is a force-push history rewrite — only worth doing for GitHub
  LFS storage-quota cleanup or to keep clones lean. Orphaned pointers
  in old commits aren't actively harmful; defer this until both
  papers are submitted.
- [ ] **Phase 0e — R2 wiring** (once Phase 0b stable): rclone push
  from the working machine to R2 daily (rather than rpi→R2 — revised
  2026-05-20, since rpi-server has no toolkit and cannot run rclone
  on a schedule). Working machine pushes to R2 from the mounted
  rpi-server NVMe contents; R2 acts as offsite + travel bridge.
  Working-machine credentials in `~/personal-assistant/.env` on
  amd-tower + zbook (`R2_*` keys).
- [x] 2026-05-17 **Vector 2 — open design doc** (`planning/vector-2-design.md`) — done; implementation parked under workstream D
- [ ] **Phase 4 — typed links** — **superseded by workstream D**; the typed-links problem is now solved by wiki-page cross-references + working-notes references + frontmatter tags
- [ ] **Phase 5 — migration sweep** — **demoted**; still useful as backfill for `verified` field but no longer gating anything
- [ ] **Phase 6 — extractor bake-off** — **deprioritised** (prior-art-scout: write strategy ~3–8 retrieval-accuracy points vs ~20 for retrieval; wrong lever)

**Small open follow-ups (new 2026-05-18):**

- [x] 2026-05-18 **SessionStart-hook sidecar for `commit_at_start`** — `hooks/session-start-code-state.py` writes `data/code-state/<session_id>.json`; `cc_session_toolkit/archive.py:capture_code_state()` now takes `session_id` + `sidecar_dir` kwargs and reads the sidecar best-effort. Hook wired into `settings.json` SessionStart array. Tests: 6 new in `test_subagent_archive.py`; full toolkit 220 passing.
- [x] 2026-05-18 **Hook hardening (`~/.claude/settings.json:91,112`)** — replaced `export $(grep -v '^#' ... | xargs)` with `set -a && . ~/personal-assistant/.env && set +a` on both PreCompact + SessionEnd archive commands. The Python `.env`-fallback pattern (`_ensure_anthropic_api_key` → `_ensure_gemini_api_key` post-F1) is retained inside `cc_session_toolkit.archive` as belt-and-braces.
- [ ] **`pg_trgm` extension missing on `claude_memories` DB** — `idx_memories_content_trgm` (`scripts/schema.sql:79`) has been silently failing to create. Non-critical (full-text search uses a different index). Either run `sudo -u postgres psql -d claude_memories -c "CREATE EXTENSION pg_trgm;"` or drop the index from schema.sql.
- [x] 2026-05-18 **`scripts/bake-off-metadata.py` tidy-up**: (a) `--yes` flag added (bypasses interactive `input()` for non-interactive runs); (b) `haiku_apply` path now navigates to `<root>/haiku/` to match where `haiku_submit` persists `batch-state.json`; print hint in submit updated to print `out_dir.parent` so the copy-paste is correct.

**Audit follow-ups (from 2026-05-19 code audit across 21 files / ~10,800 lines):**

The audit ran 6 parallel subagents over all source code touched in the
prior week (PA hooks, scripts, shell; cc-session-toolkit production +
tests). Findings categorised C/M/Low. Most landed across 2026-05-19
and 2026-05-20 in three batches (priorities 1-6 by Shawn directly;
then C2+C3+C4 via agent; then M7-M15 + Lows via parallel agent; then
M6 directly).

Done:

- [x] 2026-05-19 **M1 + M2**: `transcript_text.py` pathological edges
  (single-fragment-over-budget, head+tail overlap) — tail-truncation
  fallback with non-negative clamp; 6 new tests in
  `test_transcript_text.py`. Toolkit 220 → 226.
- [x] 2026-05-19 **C1**: `archive.py:_call_gemini_once` now raises
  `RuntimeError` when `response.text is None` (safety filter / MAX_TOKENS
  / no candidates); outer handler degrades gracefully. Previously
  uncaught `AttributeError` was crashing the archive.
- [x] 2026-05-19 **M3**: `result.get(key, default)` → `result.get(key) or default`
  on title/purpose/tags/three_ps in both `archive.py` and
  `scripts/backfill-session-metadata.py`. Handles Gemini's occasional
  `"tags": null` output.
- [x] 2026-05-19 **M4**: backfill cost-estimate refined — `--cost-sample-size N`
  (default 20) samples real distillations to compute mean/p90/max per-
  session cost. Drove the F3 cost re-estimate from $8.30 to $1.26-$2.79
  on amd-tower's actual 32 sessions.
- [x] 2026-05-19 **M5**: stale "Haiku" references replaced with
  Gemini Flex (or `EXTRACTOR_MODEL_ID` interpolation) in
  `archive.py`, `cli.py`, `tests/test_hook.py`. Historical-context
  references in module docstrings explaining the 2026-05-18 switch
  left intentional.
- [x] 2026-05-19 **M6 (cost-analysis correction)**: prepended note
  to `data/experiments/transcript-cap-analysis-2026-05-19/findings.md`
  explaining that `analyse_caps.py` did not strip framing scaffolds;
  absolute cost figures inflated ~10-15% (deltas unaffected). Refined
  F3 estimate noted as ~$4.75 not $5.52 (subsequently superseded by
  the per-machine $1.26-$2.79 from the M4 sampler).
- [x] 2026-05-20 **C2**: `extraction-hook.py` distinguishes transient
  Anthropic errors (5xx, 429, network timeout) from permanent ones.
  Transient → return `None` sentinel → cursor does NOT advance →
  retry on next firing. Permanent → existing behaviour (log, return
  `[]`, cursor advances). 8 new tests in `tests/test_extraction_hook.py`.
- [x] 2026-05-20 **C3**: `extraction-hook.py` cursor file now wrapped
  in `fcntl.flock` via `cursor_file_lock()` context manager covering
  load → process → save. Sidecar lock file at
  `data/memories/extraction-cursor.json.lock`, gitignored. 1 new
  threaded test confirms serialisation.
- [x] 2026-05-20 **C4**: `scripts/sync-symlinks.sh` Step 7 pip exit
  code now captured and propagated. Script exits non-zero on pip
  failure (was silently exiting 0 — defeated the entire purpose of
  the 2026-05-15 self-heal step).
- [x] 2026-05-20 **M7**: `anchor_verify.verify_memory` returns `None`
  when zero anchors are well-formed (previously collapsed to "true").
  Production hot path was protected by extraction-hook's anchor
  filter; module-contract fix matters for drift-sweep / re-verification
  callers.
- [x] 2026-05-20 **M9**: `scripts/extract-transcript-text.py` is now
  a thin wrapper around `cc_session_toolkit.transcript_text`. Bake-off
  + resample scripts that imported the PA script now exercise the
  same distillation as production. Drift eliminated.
- [x] 2026-05-20 **M10**: `scripts/resample-bake-off-manifest.py`
  glob results now sorted; hardcoded "2026-05-17" replaced with
  runtime UTC ISO. Sampling reproducible across machines.
- [x] 2026-05-20 **M11**: `setup.sh` verify block now exits 1 when
  `ERRORS > 0` (was silently exiting 0 — verify was theatre).
- [x] 2026-05-20 **M13**: `test_sha_matches_file_bytes` no longer
  tautological (literal hex on known bytes vs same-helper round-trip).
- [x] 2026-05-20 **M14**: 503-retry tests now assert `call_count`.
  Loop-break-after-one-attempt regressions would be caught.
- [x] 2026-05-20 **M15**: empty-session test now uses
  `pytest.importorskip("google.genai")` so it tests the real code
  path instead of passing from the ImportError branch.
- [x] 2026-05-20 **M6**: `extraction-hook.py` slash-command skip flag
  no longer auto-cleared by intervening non-command user entries.
  Real-world MCP-injected tool_result-as-user entries no longer
  un-skip the assistant turn — fixes sporadic `/remember` double-
  extraction.
- [x] 2026-05-20 **Lows batch**: ~12 small fixes including
  `archive.py` exception widening + sidecar `isinstance(dict)` guard;
  `session-start-code-state.py` atomic sidecar write + `_timestamps.now_iso`;
  `_command_markers.py` `/sync-board` marker drift (was "GitHub
  Issues Sync", now "GitHub Projects Board Sync"); `sync-to-postgres.py`
  logger handler stacking + `_update_embeddings` exit semantics;
  `bake-off-metadata.py` content-block guard + system-prompt token
  inclusion in cost estimate; `project_id.py` deferred `Path.home()`
  + wider recursion error catch; `analyse_caps.py` tolerant decoding.

Deferred (with reason):

- [ ] **M12**: `schema.sql:75` `idx_memories_active` partial index
  serves no purpose (predicate `is_active = TRUE` matches ~all rows).
  Fix would drop or flip the predicate. Deferred to schema v4 with
  migration plan — schema changes have higher blast radius (live PG
  is at v3; this needs a v4 bump + `ALTER INDEX` migration). Audit
  note added in-file at `schema.sql:74-79`.
- [ ] **Memory-id non-idempotency** (`extraction-hook.py:679-681`):
  ids use wall-clock timestamp, so re-running on the same content
  produces different ids. Workaround exists in `scripts/dedup-memories.py`.
  Better fix: use `source_message_uuid + i` for true idempotency.
  Defer — not a bug, just a recurring tax.
- [ ] **Pricing-constant deduplication**: Gemini Flex prices live in
  `cc_session_toolkit/config.py`, `analyse_caps.py`, and
  `bake-off-metadata.py`. A shared `pa_pricing.py` module would make
  Google price changes a one-line edit. Cross-file refactor; defer.
- [ ] **`MEMORIES_FILE.read_text()` in-memory load**
  (`scripts/sync-to-postgres.py:798`): loads entire JSONL (~10MB) into
  memory. Fine at current scale; could become a problem at 100k+
  records. Defer.
- [ ] **`pg_trgm` extension missing** (carry-over from 2026-05-18):
  `idx_memories_content_trgm` (`scripts/schema.sql:79`) silently fails
  to create. Either run `sudo -u postgres psql -d claude_memories -c "CREATE EXTENSION pg_trgm;"`
  or drop the index from schema.sql.
- [ ] **Three Ps `*_summary` fields backfill** for pre-2026-05-18
  sessions (carry-over from 2026-05-17). F3 backfill will populate
  these natively going forward; the older sessions remain empty until
  backfilled. RDA IG POC framing slight embarrassment until closed.

**Workstream F — auto-metadata production switch (new 2026-05-18):**

- [x] 2026-05-18 **F1: Gemini Flex wired into `cc_session_toolkit.archive.generate_auto_metadata`** — full replacement. New module `cc_session_toolkit/transcript_text.py` (ported from PA `scripts/extract-transcript-text.py`); new package data `cc_session_toolkit/prompts/auto_metadata.md` (shipping copy of `prompt-gemini-v2.md`); new helpers `_load_auto_metadata_prompt`, `_build_auto_metadata_user_message`, `_parse_metadata_response_json`, `_call_gemini_once`, `_call_gemini_with_retry`, `_ensure_gemini_api_key`. Old sampled-message machinery (`_is_meta_message`, `_META_*` sets, sampled-message loop, `_ensure_anthropic_api_key`, `re` import) all removed. `pyproject.toml` `api` extra flipped `anthropic>=0.40` → `google-genai>=2.3`; `prompts/*.md` added to package data. Test suite reshaped: dropped 32 obsolete sampling/meta-filter tests, added 17 Gemini-shape tests (helpers, integration with mocked `google.genai` client, 503 retry recovery, exhausted-retry → None, unparseable JSON → None). Toolkit 205 passing. PA suite 690 still passing — no callers broken.
- [x] 2026-05-18 **F2: `EXTRACTOR_MODEL_ID` switched** from `claude-haiku-4-5-20251001` to `gemini-3-flash-preview` in `cc_session_toolkit/config.py`. New constants `AUTO_METADATA_MAX_OUTPUT_TOKENS=1024`, `AUTO_METADATA_FLEX_RETRY_WAITS_SECONDS=(30, 60, 120)`, `GEMINI_FLEX_INPUT_PRICE_PER_MTOK=0.25`, `GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK=1.50`.
- [x] 2026-05-18 **PA venv reinstalled** with `pip install -e ~/Code/cc-session-toolkit` so hook firings on amd-tower use the new path. zbook + rpi-server pip installs still pinned to the old non-editable wheel — re-run editable install on those machines or push a new tagged release before relying on the new path there.
- [x] 2026-05-18 **`scripts/backfill-session-metadata.py` updated** for the Gemini path: `_ensure_gemini_api_key`, cost line ~$0.027/session, `update_metadata` writes Three Ps natively (was preserving empty defaults).
- [ ] **F3: Backfill historic sessions** — BLOCKED on Shawn's gate
  approval after live-output review. **Refined estimate (2026-05-20):**
  ~$1.26 mean / ~$2.79 p90 worst-case envelope on amd-tower's 32 sessions
  needing backfill (the 307 figure in earlier notes was actually the
  full unique-main-thread-session count across all locations, not just
  the needing-F3 subset — confirmed by the 2026-05-20 inventory; see
  `planning/archive-inventory-2026-05-20.md`). The needing-F3 set is
  the 32 sessions under `~/cc-archives/<project>/` whose meta files
  have `auto_generated.purpose == "Auto-metadata unavailable"`.
  Per-session mean ~$0.039, p90 ~$0.087. Cost-estimate uses a
  20-session sample distilled through the production extractor — no
  flat-rate approximation. Run with `python3 scripts/backfill-session-metadata.py --dry-run`
  to see fresh numbers. Two-stage option recommended: do amd-tower
  first (~$1-3, low risk; tests the pipeline against a real
  population), then propagate to zbook **once zbook's own inventory
  pass is complete** (rpi-server is NOT a target — no toolkit
  installed; rpi-server is destination-only, mount-based).
  **Note**: the inventory also surfaced 61 *live-only* sessions on
  amd-tower that have never been archived. Sweeping those into the
  archive before F3 fires will let them pick up Gemini Flex
  auto-metadata at write time and avoid needing backfill at all.
- [ ] **F4: QA pass on ~20 sampled backfill outputs** — depends on F3.
- [ ] **GA-rename watch**: model id `gemini-3-flash-preview` is still
  "Preview"; bump constant when GA renames to `gemini-3-flash` (or
  similar).
- [ ] **Manual Gemini list-price re-verification** before F3 commits.
  Constants in `cc_session_toolkit/config.py:60-61` were verified
  2026-05-17; Google has historically adjusted preview-tier prices on
  short notice. 30-second check against
  https://ai.google.dev/gemini-api/docs/pricing#flex.

**Workstream D — memory-system rethink + wiki formalisation (new 2026-05-17):**

- [x] 2026-05-18 **Implement `/handoff` as actual skill** in `commands/handoff.md` — thin invoker that points at `handoff-protocol.md`
- [x] 2026-05-18 **Draft `global-claude-md/session-start-protocol.md`** — symmetric bookend to `/handoff`; silent fires at session-start; covers continuity.md read, things-to-verify spot-check, recall-dump de-weighting, future auto-loading of wiki/notes indexes
- [ ] **Pilot wiki migration on personal-assistant** — move `planning/`, `docs/`, `continuity.md`, etc. under `wiki/`; add `wiki/index.md` (sketch landed at `planning/wiki-index-draft.md` 2026-05-18); split `notes/_tags.md` content into `wiki/index.md` at migration time
- [x] 2026-05-18 **Sketch `notes/index.md` + initial wiki-tag vocabulary** — 24-tag set across four groupings (craft scaffolding 8, failure modes 5, domains 6, cross-cutting 5); pre-staged in `notes/_tags.md` ready to lift to `wiki/index.md` at pilot migration
- [ ] **Extend `/weekly-review` with cluster-and-carry curation step** — produce candidate wiki-page diffs
- [ ] **Phase 0 archive consolidation — priority promoted** (open-science topic-search depends on this)
- [ ] **Lit-scout file moves at pilot-migration time** — destinations decided 2026-05-18: `v3-bayesian-dating` → inscriptions; `v4` (maps) → map-reader-llm; `v4.1` (SPA Latin inscriptions) → inscriptions; `v4.2` (ABM Mediterranean economies) → inscriptions; `v4.3` (magnetometer) → `archive/lit-searches/magnetometer-2026-04-19/`; all `*-evaluation-*` / `*-verifier-*` → `wiki/docs/lit-scout-evaluations/`; `paper-b-working-notes.md` + `lit-scout-case-study.md` → Paper B project wiki; `general/2026-03-15-persona-affordance-design-paper-seed.md` → map-reader-llm

**Provenance audit gaps (from workstream D audit, 2026-05-17) — all three closed 2026-05-18:**

- [x] 2026-05-18 **Gap 1: `source_message_uuid` on extracted memories** — `hooks/extraction-hook.py` `format_memories()` now plumbs the batch-tail UUID through. Schema v2 → v3; partial index added. Live PG migration applied.
- [x] 2026-05-18 **Gap 2: `code_state.{commit_at_start, commit_at_end, dirty_at_end}` on session records** — `cc_session_toolkit/archive.py` now captures `commit_at_end` + `dirty_at_end` via `capture_code_state()`. `commit_at_start` closed 2026-05-18 via `hooks/session-start-code-state.py` sidecar + `capture_code_state(session_id=...)` lookup; `CODE_STATE_SIDECAR_DIR` config constant in `cc_session_toolkit.config`.
- [x] 2026-05-18 **Gap 3: `licence` + `extractor_model_id` on memory + session records** — UK spelling (`licence`) used across PA + cc-session-toolkit. Memory schema v3 absorbs both columns; live PG migration applied. cc-session-toolkit's `create_session_metadata()` accepts `licence` and `extractor_model_id` kwargs. PA `extraction-hook.py` defaults `licence=None` (user opts in at sharing time) and `extractor_model_id=HAIKU_MODEL`.
- [ ] **Bonus: populate the empty `prompt_summary` / `process_summary` / `provenance_summary` fields** in session.meta.json (schema present, generation missing). Quiet embarrassment for the RDA IG POC framing.

## Open decisions / questions

Resolved decisions move to the session-log entry where they were made.

*None blocking. All Phase 1–3 questions resolved 2026-05-15; Phase 0
architecture resolved 2026-05-16; memory-system rethink resolved
2026-05-17. Next session has concrete implementation choices (which
audit gap first, wiki-migration timing) but no design-level decisions
pending.*

## Architectural decisions worth not re-litigating

Distilled from the design + planning docs so the next session doesn't
reopen settled questions:

- **JSONL is canonical**, Postgres is a derived/rebuildable query
  layer. Drop the DB and rebuild from JSONL via
  `scripts/rebuild-postgres.py`.
- **Custom memory system is canonical**; Anthropic's harness-injected
  auto-memory and `MEMORY.md` are *legacy* — never write to them.
  Routed via the write-side rule in `global-claude-md/shared.md`.
- **Session archive: full mirror everywhere.** rpi-server SSD share
  holds canonical `~/mnt/rpi-shares/cc-archives-consolidated/<project>/<session>/`
  (path resolved 2026-05-21; see decision below); working machines
  hold full local mirrors. R2 is offsite + travel bridge. Decided
  2026-05-16.
- **rpi-server is mount-only, not install-target** for the cc
  archive (2026-05-20, revising Phase 0 plan). rpi-server has no
  cc-session-toolkit install, no Python venv, no cron-driven
  archive automation, and is not in scope for F3 backfill. It is
  purely a storage destination — working machines mount its NVMe
  (SSHFS / NFS — pattern TBD), and all archive writes, indexing,
  and rclone-to-R2 pushes happen on the working machine writing to
  the mounted destination. This supersedes earlier sub-tasks that
  envisioned rpi-side cron or installing the toolkit there. The
  existing pre-v2 backups at `~/cc-archives/pre-v2/` on rpi-server
  are legacy bootstrap artefacts and do NOT imply ongoing toolkit
  installation there.
- **Consolidation is comprehensive across all working machines**, not
  amd-tower-only (2026-05-22, scope expansion). The 2026-05-20 inventory
  was explicitly amd-tower-scoped (zbook + rpi-server out of scope);
  Phase 0 Step 4 as originally written rsynced only amd-tower sources.
  Mid-Phase-0 on 2026-05-22, Shawn confirmed that the *earlier* intent
  was always comprehensive consolidation across all working machines
  (amd-tower + zbook + sapphire) — the scope-narrowing in the inventory
  artefact hadn't carried that decision forward into continuity.md.
  The 2026-05-22 cross-machine verifier + Step 4b zbook rsync close
  this gap. sapphire is mount-only / rsync-only — its only CC content
  was worktree stubs, byte-redundant with the consolidated store, so
  no separate rsync from sapphire was needed. Going forward, any new
  working machine added to Shawn's setup must also feed this single
  source-of-truth.
- **`/export`-vs-auto-archive content-equivalence dedup pattern**
  (2026-05-22, surfaced + deferred). During an estimated ~30-day overlap
  window (Nov-Dec 2025 era), Shawn was using the built-in `/export`
  slash-command to manually export transcripts into `~/cc-archives/`
  AT THE SAME TIME as auto-archive (via the toolkit hook) was capturing
  live JSONLs into the same `~/cc-archives/` layout. The same session
  may therefore exist twice: as `/export` output (likely `.md` or
  `.txt`, different framing) and as `session.jsonl(.gz)`. SHA-based
  dedup misses these because the framing differs. Existence proof: the
  b80b94c6 triage on 2026-05-22 — 3 of 4 SHAs agreed on the auto-archive
  version; one lone zbook outlier in `~/cc-archives/` was the `/export`
  variant. Cleanup approach (deferred to post-Phase-0): file-extension-
  and-co-presence-within-session-dir as a marker. **Caution**: `/export`
  versions may carry framing or notes the auto-archive lacks — don't
  blindly discard.
- **Cwd-derived buckets live under `_misc-cwd/`, not at top level**
  (2026-05-22). The consolidated store surfaced 11 sessions from zbook
  where the toolkit's `project_id` had collapsed to the working
  directory name because CC was launched outside any project repo
  (8 from `~/Code/`, 3 from `~/`). Quarantined under `_misc-cwd/` rather
  than left at top level as if they were project_ids — preserves the
  data but signals it's an anti-pattern not a project.
- **Future system/network troubleshooting under `personal-assistant/`**
  (2026-05-22, working-practice decision). When CC needs to be launched
  to investigate system / network / infrastructure issues outside any
  specific project, the correct project repo is `personal-assistant/`
  (which is broadly scoped for cross-project infrastructure work) —
  NOT a bare home dir or a generic `~/Code/` invocation. Avoids
  producing more `_misc-cwd/` entries and keeps project_ids semantically
  informative.
- **`HUMN8031-2026-S1` and `ANU-HUMN8031-2026` are distinct repos, not
  duplicates** (2026-05-22 clarification). Both appear as top-level
  project_ids in the consolidated archive; both relate to the same ANU
  course but back two different repos — `HUMN8031-2026-S1` is Shawn's
  private course-development workspace; `ANU-HUMN8031-2026` is the
  shared student-facing materials repo. Naming-similar but semantically
  distinct; do not merge.
- **Consolidation destination: `~/mnt/rpi-shares/cc-archives-consolidated/`**
  (2026-05-21). The canonical cc transcript store lives on the
  rpi-server encrypted SSD share at
  `/opt/encrypted/workspace/shares/cc-archives-consolidated/`, mounted
  on working machines via the existing `mount-rpi-shares` SSHFS alias.
  393 GB total / ~300 GB free at consolidation time — ample headroom
  vs. the ~1.45 GB initial corpus. Distinct from the bulk-storage
  tiers on the same rpi-server: `rpi-vantec` (15 TB, mount-rpi-vantec)
  and `rpi-qnap` (26 TB, mount-rpi-qnap) are mounted via sibling
  aliases and reserved for bulk archival data, not the hot working
  archive. The destination's layout is published on the mount itself:
  share-root `README.md` documents the share as a whole; inner
  `cc-archives-consolidated/README.md` documents the cc-archives
  contract (write-side rules, subdir contracts, sizing, cross-refs).
  Reserved subdirs at consolidation time: `_indexes/` (cross-project
  session_id index, manifests — populated in Phase 0 Step 9-10);
  `manual-exports/` (the 182 pre-Dec-2025 `.txt` exports, per the
  2026-05-20 inventory).
- **Project repos do not carry `archive/cc-sessions/`** (2026-05-20,
  Phase 0 architectural conclusion). The consolidated rpi-server
  NVMe mount is the only location for transcripts. Project repos
  add `archive/cc-sessions/` to their `.gitignore` and `git rm
  --cached` any existing entries. This (a) prevents future drift
  between per-project archive copies and the consolidated store,
  (b) keeps project-repo working copies small and clones fast, and
  (c) eliminates the LFS-tracking problem permanently for projects
  that previously used Git LFS for transcripts (map-reader-llm,
  LLM-History-Paper). `git lfs untrack "archive/cc-sessions/**"`
  stops new files from going to LFS; the orphaned pointers in old
  commits are harmless and a full `git lfs migrate export` history
  rewrite is deferred until post-journal-submission (low blast-
  radius cleanup, not blocking).
- **Inscriptions** is *revitalisation* not abandonment. Drift sweep
  must distinguish revitalisation drift (preserve memory, mark
  `verified: stale`) from true staleness (`verified: false`).
- **Self-driving tenet**: the system must be ~99% self-driving. Rules
  out review-gated steps in the steady state. Manual review allowed
  at bootstrap and exceptional moments only.
- **Memory corpus is a candidate pool, not the surfacing layer** (2026-05-17).
  Auto-extraction kept (not killed) but reframed. Curated `notes/<topic>.md`
  wiki pages are the canonical knowledge layer; corpus feeds candidates
  via cluster-and-carry at `/weekly-review`. See workstream D.
- **Four-artefact picture** (2026-05-17): continuity.md (state) +
  working-notes/reflections/user-observations (raw chronological obs)
  + notes/<topic>.md (curated cross-project knowledge) + scratchpad
  (principles). Each has one job; no redundancy. Surface load
  ≤6–8 KB total at session-start across all always-on layers.
- **Recall-trigger problem treated as unsolvable** in the
  human-memory-cascade shape (2026-05-17). Replaced by always-on
  metadata catalogue (index files) + deterministic lifecycle hooks +
  topic-anchored knowledge (`notes/`). "Build the recall instinct"
  removed as an engineering goal.
- **Cross-project wiki structure** (2026-05-17): flat directory under
  `~/personal-assistant/notes/` + YAML frontmatter tags + `notes/index.md`.
  Wiki-tag vocabulary deliberately separate from (noisier) memory-tag
  vocabulary; curated short list, 20–30 tags total.
- **Project wiki structure** (2026-05-17): `<project>/wiki/` containing
  `planning/` + `docs/` + `continuity.md` + `working-notes.md` +
  `reflections/` + `user-observations.md`. Source code/data/tests stay
  outside `wiki/`. `wiki/index.md` is the navigation layer.
- **`/handoff` vs `/recap`** (2026-05-17): distinct skills, distinct
  cadence/audience. `/recap` is daily, multi-project, abstract, serves
  Shawn. `/handoff` is per session-close in a project, working-state,
  serves cross-session continuity. Do not merge.
- **Wind-down trigger** (2026-05-17): "stop when the work stops, not
  when capacity stops." Context % is a backstop, not the trigger.
  See `notes/working-practices.md` entry 2026-05-17.
- **Auto-extraction stays, but feeds curation** (2026-05-17). Field
  consensus (prior-art-scout) + retrieval-vs-write evidence: write
  strategy is ~3–8 retrieval-accuracy points; retrieval method is ~20.
  Fixing Haiku truncation (Phase 6) is the wrong lever. Deferred.
- **Three Ps vocabulary already in `session.meta.json` schema**
  (2026-05-17 audit finding). Pre-commitment to the RDA IG framework
  was built into `cc_session_toolkit` design. Summary-string
  generation needs to actually run to make the system a credible POC.
- **Auto-metadata provider: Gemini Flex over Haiku Batch** (2026-05-18).
  Bake-off scored Gemini-tuned-v2 17–7 vs Haiku across 42 cells, with
  18 ties. Gemini's 1M-token context sidesteps the chunking complexity
  that would otherwise plague the ~30% of sessions exceeding Haiku's
  200K window. Single-provider, single-shot call, ~half Haiku's cost.
  Production prompt: `data/experiments/bake-off-metadata-2026-05-18/prompt-gemini-v2.md`.
- **Full transcript over sampled-messages for auto-metadata** (2026-05-18).
  The previous `archive.py:_generate_auto_metadata()` prompt fed Haiku
  only first-and-last user messages. The new prompt sends the entire
  distilled transcript. Required for grounded Three Ps summaries (a
  sampled-input prompt can't characterise `process_summary` faithfully).
- **`thinking_budget=0` for structured-JSON generation on Gemini 3 Flash**
  (2026-05-18). Gemini 3 Flash Preview is a reasoning model; without
  `thinking_config={"thinking_budget": 0}`, thinking tokens consume the
  output budget before any visible JSON is emitted (first bake-off run
  produced 0/10 parseable responses with `max_output_tokens=1024`).
  Disabling thinking also gives apples-to-apples comparison with Haiku
  (which has no thinking mode).
- **System-prompt + delimited-transcript structure** (2026-05-18 prompt
  redesign). Putting instructions in the user message alongside the
  transcript caused Haiku to *continue the conversation* on 5/10
  sessions (treating `[assistant]` markers as chat turns). Fix:
  instructions to `system=` / `system_instruction=`; transcript wrapped
  in `<transcript>` tags with neutral `--- Role ---` dividers; output
  reminder *after* the closing tag. Eliminated the failure mode.
- **`/handoff` ritual: per session-close, in-project** (2026-05-18, first
  formal use). Five steps per `global-claude-md/handoff-protocol.md`.
  At step 4, *draft* candidate user-observations rather than ask
  blank-page question. At step 5, default is commit-and-push everything
  batched by logical area.
- **Production prompt ships as toolkit package data** (2026-05-18,
  workstream F wire-up). `cc_session_toolkit/prompts/auto_metadata.md`
  is the shipping copy of `prompt-gemini-v2.md`; load via
  `importlib.resources`. Env var `CC_AUTO_METADATA_PROMPT_PATH` overrides
  for prompt iteration without re-installing the package. The PA
  `data/experiments/.../prompt-gemini-v2.md` copy stays as the
  historical bake-off artefact. Reasoning: the toolkit is meant to be
  self-contained and reproducible across machines; coupling its
  production prompt to a PA submodule path would break that.
- **Transcript extractor lives in the toolkit, not PA scripts**
  (2026-05-18, workstream F wire-up). The script-form
  `scripts/extract-transcript-text.py` in PA stays for ad-hoc CLI
  smoke-testing, but the canonical module is now
  `cc_session_toolkit.transcript_text`. Production callers
  (`archive.generate_auto_metadata`, backfill script) import the
  module; only humans use the CLI. Symmetric with the prompt-shipping
  decision: keep the toolkit reproducible standalone. **2026-05-20
  follow-up**: the PA script is now a *thin wrapper* re-exporting
  the toolkit's symbols — drift is impossible going forward (M9).
- **850K-token session-level transcript cap with middle-truncation**
  (2026-05-19, design landed). Per-block caps on `tool_result` /
  `tool_use_input` removed entirely; replaced with a single
  session-total budget at 85% of Gemini 3 Flash Preview's 1M-token
  context. Cap fires on ~1 in 242 historic sessions (one
  llm-reproducibility outlier at 974K tokens uncapped). When it
  fires, middle-truncation preserves session head (user framing) +
  tail (commits / handoff) and drops repetitive middle (paper-after-
  paper extractions, file-after-file refactors). Empirical basis:
  `data/experiments/transcript-cap-analysis-2026-05-19/findings.md`.
  Pathological edges (single fragment > budget, head+tail overlap)
  fall back to a tail-truncation marker with non-negative clamp,
  added 2026-05-19 after audit.
- **Cost estimation grounded in per-session sampling, not flat per-
  session averages** (2026-05-20, M4 audit fix). Flat $0.027/session
  estimates under-state cost when long-tail sessions approach the
  cap. New `--cost-sample-size N` (default 20) in
  `scripts/backfill-session-metadata.py` distils a real sample
  through the production extractor and reports mean / p90 / max
  per-session cost + a worst-case envelope. Drove the F3 cost
  re-estimate from $8.30 to $1.26-$2.79 on amd-tower's actual
  population.
- **Anthropic API failure semantics: transient vs permanent**
  (2026-05-20, C2 audit fix). `hooks/extraction-hook.py`
  `extract_memories` now returns `None` (sentinel) on transient
  errors (5xx, 429, network timeout) — cursor does NOT advance,
  next firing retries. Permanent errors (4xx, programming bugs)
  preserve the prior behaviour: log, return `[]`, cursor advances.
  Reasoning: indefinite re-processing on permanent input errors
  blocks all downstream extraction; transient errors deserve a
  retry not a silent skip.
- **Cursor file flocked across concurrent hook firings**
  (2026-05-20, C3 audit fix). `~/.claude/settings.json` wires the
  extraction hook on `Stop` + `PreCompact` + `SessionEnd` — all
  three can fire close together on session-close. `cursor_file_lock()`
  context manager wraps load → process → save in an `fcntl.flock`
  exclusive lock on a sidecar lockfile. Holds the lock through the
  Anthropic call (~5s) — serialises hook firings, which is
  acceptable at this rate. Alternative (optimistic-concurrency
  merge) more complex and not warranted.
- **Reasoning-trace capture from Claude Code is upstream-blocked**
  (2026-05-19, CoT capture investigation). Thinking text is empty in
  CC session JSONLs as of v2.1.72 (Feb/Mar 2026 rollout of
  Anthropic's `tengu_quiet_hollow` server flag +
  `redact-thinking-2026-02-12` beta header that CC now sends). Three
  related issues closed as won't-fix; one open feature request
  (`anthropics/claude-code#39343` — `ThinkingBlock` hook event) is
  the right upstream fix. Workaround `showThinkingSummaries: true`
  no longer functions on Opus 4.7. Treat thinking-block metadata
  (count, signature) as the captured signal; community capture
  tools (`agentsight`, `claude-code-proxy`) exist but none is
  research-grade. Full investigation at
  `docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md`.
  Directly relevant to workstream E (RDA IG) — candidate IG output
  or JOSS tools paper.

## Reference docs

| Topic | Path | Read when… |
|---|---|---|
| v2 design + 8 resolved decisions | `planning/memory-system-v2-design.md` | New session continuing v2 work; want to know why a choice was made |
| Empirical basis for v2 | `planning/memory-corpus-audit-2026-05-14.md` | Need to cite specific audit findings, e.g. 53% unverifiable |
| v2 implementation plan + phases | `planning/memory-system-v2-implementation-plan.md` | Sequencing decisions; per-phase file lists; risks register |
| Deferred-work register | `planning/memory-system-v2-future-extensions.md` | Something feels like it should already exist but doesn't |
| Vector 2 design (parked) | `planning/vector-2-design.md` | Considering implementation of session-start payload reduction |
| Continuity-doc protocol | `global-claude-md/continuity-protocol.md` | Updating continuity.md; deciding what belongs in it |
| `/handoff` protocol | `global-claude-md/handoff-protocol.md` | End-of-session ritual; deciding which observations to capture |
| RDA IG context (Three Ps framework) | `docs/open-science/RDA_IG_Statement_of_Work.docx`, `RDA_IG_Summary_and_Description.docx` | Aligning system with research-data standards; provenance audit |
| Cap-analysis findings (850K decision basis) | `data/experiments/transcript-cap-analysis-2026-05-19/findings.md` | Why the cap is 850K; what middle-truncate sacrifices on outliers; the framing-strip correction note |
| CoT capture investigation (RDA IG-relevant) | `docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md` | Why thinking blocks are empty in CC JSONLs; survey of community capture tools; recommendations across short / medium / long horizons |
| Current FOCUS slots | `tasks/FOCUS.md` | Knowing whether to mention slot pressure (don't if PA work is deliberate background) |

---

## Recent session logs

*Most recent at top. One paragraph + bullets per entry.*

### 2026-05-22 (Fri, evening) — Data-profile closed-loop smoke test + documentation_defect calibration

Smoke-tested the `/data-profile-iterate` driver (workstream H, the
reference implementation of the closed-loop proposer-verifier pattern)
end-to-end on the LIRE v3.0 inscription corpus. Goal was to surface
real iteration outcomes that could calibrate the severity rubric and
PARTIAL-tolerance band. Iter-0 returned PARTIAL (81/83 PASS, 2 PARTIAL
on `count-province-group-count` and `count-urban-area-group-count`, 0
FAIL, 0 unverifiable). Loop terminated per policy without entering
iterate mode.

The two PARTIAL rows were the actual calibration finding. By the
spec's exact-count rule (PASS=±0, PARTIAL=≤0.5 % relative drift,
FAIL=beyond 0.5 %), a 1-of-65 group-count divergence is 1.54 %
relative — strictly beyond PARTIAL, so should be FAIL by the letter.
The verifier instead called them PARTIAL low on the grounds that the
proposer's numeric value (66) was internally consistent with the
report's tables (which display `<null>` as a group), and only the
`source_method` string (`df.groupby(['province']).ngroups` — which
defaults `dropna=True` and would yield 65) was wrong. Defensible
judgement; not authorised by the spec. We closed the gap by adding
a fifth corrections.jsonl status — `documentation_defect` — that
explicitly captures "value is right, description is wrong" cases,
keeps numeric tolerance bands clean, and gives the proposer's
iterate mode a cheap string-substitution path. Aggregate
verdict rolls `documentation_defect` into PARTIAL (non-iterating).

The bigger gap the smoke test exposed: **iterate mode itself was
never exercised**. The plumbing (proposer emits stable IDs, verifier
emits the JSONL contract, driver routes on verdict) is confirmed,
but the proposer was never re-invoked with `previous_corrections_path`
because LIRE produced 0 FAIL claims. The closed loop's real
behaviour — reading `fix_hint`, re-deriving values, no-progress
termination — still needs a synthetic-FAIL follow-up test before
the pattern can be generalised to `lit-scout` (workstream H next
step).

- Commits: `2e89bd1` (`feat(agents): add documentation_defect status
  to proposer/verifier contract` — 2 files, 6 insertions, 2 deletions)
- Spec edits: `agents/data-profile-verifier.md` (status enum
  extended; new bullet definition; aggregate-verdict rules updated);
  `agents/data-profile-proposer.md` (iterate-mode partition handles
  `documentation_defect` via string substitution; new "source_method
  ambiguity" failure-mode bullet requires explicit `dropna` and
  other result-affecting kwargs at write time)
- Smoke-test artefacts (under `~/Code/inscriptions/runs/2026-05-22-data-profile-smoke/`):
  `config.json` (the invocation); `iterate-20260522-162723/iter-0/`
  containing `summary.md`, `profile-province.md`,
  `profile-urban-area.md`, `artefacts.md`, `claims.jsonl` (83
  claims), `corrections.jsonl` (81 pass / 2 partial), `verdict.md`,
  `decisions.md`, `tables/` (12 CSVs), `code/profile.py`
- Agent runs: one `data-profile-proposer` (first-run mode, ~1.5 s
  Python wall-clock, 8 tool uses, 58K tokens); one
  `data-profile-verifier` (full-data re-derivation, 21 tool uses,
  57K tokens)
- Continuity updates (this file): workstream H table row updated
  with smoke-test result + `documentation_defect` note; live
  next-steps reorganised — smoke-test bullet marked done with
  partial outcome flag; new bullet added for synthetic-FAIL
  iterate-mode test; severity-rubric calibration bullet annotated
  to note only `low` was exercised

### 2026-05-22 (Fri) — Task-system arc 2026-05-18 → 2026-05-22 + new corpus-style-analyser agent

Multi-day conversational session covering the full Mon→Fri standup +
recap cycles (2026-05-18 → 2026-05-22), one major focus-slot rotation,
the first `/sync-board` execution, and a new reusable agent
definition. Distinct from the parallel PA-infrastructure session below
(Phase 0 LFS pull + consolidation).

**(1) Daily standups + recaps recovered cleanly across the week.**
Standup + recap pair for each of 2026-05-18 (Mon), 2026-05-19 (Tue),
2026-05-20 (Wed), 2026-05-21 (Thu), and 2026-05-22 (Fri standup;
recap to follow at EOD). All five standup files landed in
`~/personal-assistant/standups/`; recaps appended to each, then to
`reports/work-log.md` + `memories/memories.jsonl` (`progress`
category, daily-recap tag). Time logged daily into
`reports/time-log.csv` with no missing days.

**(2) Major slot rotation 2026-05-21.** Inscriptions prereg lodgement
(the long-running Slot 1 task since 2026-05-14) closed Wed
2026-05-20 at 18:15 (OSF tag `osf-lodgement-2026-05-20`). HUMN8031
Week 11 class delivered + course wrapped same week. Both slots
rotated 2026-05-21: Slot 1 → "RAC-TRAC talk materials for Adela's
Friday delivery" (1-week task; talk Fri 2026-05-22 22:20 Sydney =
14:20 Aarhus); Slot 2 → "EFN BolgiaTen arc". Paper B moved to
Paused; Map-reader stayed Paused. Slot 3 initially set to EFN
website review (queued); re-rotated 2026-05-22 to **EFN outreach
campaign planning (#83)** after UNSW outreach decision-day closed
silent. Website review pushed to "After Slot 3 closes".

**(3) BolgiaTen Slot 2 scope expanded 2026-05-21.** Originally framed
as "proposal support", expanded same-day after the GroundSite
Discussion meeting: BolgiaTen want the **dev plan in next week**,
shape is **backlog creation** (per-feature delta now-Fieldmark →
desired-MVP at TRL5, then prioritise). Updated in FOCUS.md
end-of-session 2026-05-22. Next BolgiaTen meeting Mon 2026-05-25
(time TBD).

**(4) `/sync-board` Phase 1 executed via background agent
2026-05-21.** 8 ops (4 moves + 3 creates + 1 waiting-for-add).
Project board now shows Slot 1 (#102) + Slot 2 (#103) in Focus,
#104 website review in Backlog, #105 UNSW in Waiting for, #73
Paper-B moved to Paused, #79/#80 moved Inbox→Backlog. Phases 2–4
(recently-done audit, full backlog audit, archive-repo cleanup)
deferred to a future dedicated session.

**(5) New reusable agent: `corpus-style-analyser`.** Saved at
`~/.claude/agents/corpus-style-analyser.md` (global subagent
definition). Empirically derives a writing style guide from a
Zotero-cataloged corpus with strict anti-confabulation discipline:
every claim carries count + ≥2 verbatim quotes + paper key +
explicit status (`attested` / `attested-rarely` /
`absent-when-searched` / `aspirational`). Parameterised for re-use
across newer Claude versions or different genres (substack,
business, teaching). Aspirational section deliberately generated
*independent* of corpus, to be reconciled in a follow-up
human-in-the-loop session against the user's prior conscious style
guides. **Run-1 (academic, 2015-present, Shawn-publications minus
Style-exclude tag) completed 2026-05-22** — 18 papers, 139,105
words analysed, 51KB output at
`~/personal-assistant/notes/style-guides/academic/style-guide-academic-2026-05-22.md`.
Top empirical findings: first-person plural default (16/18
papers), throat-clearing systematically absent, UK orthography 76%
on core probe. Reconciliation captured to inbox for follow-up
session.

**(6) Waiting-for + inbox hygiene.** UNSW outreach closed (silent
past decision-point); Odette PM offer added + updated (call
expected Fri afternoon). Penny welfare-check resolved during Thu
morning meetings. Jiayuan Li moderated-mark closed. Two
long-deferred EFN inbox items (`fieldnote.au/privacy` corrections,
Indigenous Data Sovereignty plan) promoted from inbox to backlog
2026-05-18.

- Files modified (task system): `tasks/FOCUS.md` (multiple updates
  across the week — final state has new slot definitions),
  `tasks/inbox.md` (numerous adds + ticks),
  `tasks/waiting-for.md` (UNSW closed, Odette added/updated),
  `tasks/backlog.md` (#79, #80 row promotions; #83 active-arc
  annotation; new ANU Week 11 reusable-asset row).
- Files added (session artefacts): `standups/2026-05-18.md` →
  `standups/2026-05-22.md` (five new), `reports/work-log.md`
  (entries for 18, 19, 20, 21 appended), `reports/time-log.csv`
  (multiple entries each day).
- Files added (new agent + first output):
  `~/.claude/agents/corpus-style-analyser.md` (global, not in PA
  git), `notes/style-guides/academic/style-guide-academic-2026-05-22.md`.
- Memories: progress memories for each recap (2026-05-18 →
  2026-05-21), plus a `decision` memory for the new agent and its
  run-1 output.
- No commits yet — all changes landed live in the working tree
  through the conversation; handoff is committing now.

### 2026-05-22 (Fri) — Phase 0 LFS pull + comprehensive consolidation + layout cleanup

Long PA-infrastructure background session executing most of Phase 0 in
one arc. Started with the two background-agent passes Shawn authorised
(LFS pull + 61-live-onlys sweep) but the latter never fired — early in
the session Shawn paused to confirm consolidation was actually done
before any new API spend. That pivoted the sequence: rsync the existing
corpus to rpi-shares first, verify across all working machines, then
revisit the Gemini Flex sweep with full picture.

**(1) Step 1 — LFS pull on map-reader-llm + LLM-History-Paper.**
Dispatched as background agent. 535 MB / 184 LFS objects resolved in
~28 s combined. Per-project archive contents now byte-identical to
canonical worktree (5 SHA-256 spot-checks match on map-reader-llm;
5 file-type confirms — `gzip compressed data`, magic bytes `1f 8b` — on
LLM-History-Paper). Read-only on remotes; no history changes.

**(2) map-reader-llm fetch + commit + push.** map-reader-llm was 35
commits behind origin/main with pre-existing dirty state. Stashed the
modified `logs/phase3a-recovery-overnight/launch-summary.md`,
fast-forwarded (no rebase needed), unstashed, added `.claude/worktrees/`
to `.gitignore` with a rationale comment, and pushed two focused
commits: `0efda174 chore(gitignore): ignore .claude/worktrees/` and
`b740da63 docs(logs): record phase3a-recovery campaign-halt postmortem`.
Working tree clean post-push.

**(3) Step 4a — amd-tower rsync to rpi-shares.** Dispatched as
background agent. 4 rsync passes (3 per-project + 1 legacy global;
worktree skipped as byte-redundant per 2026-05-21 SHA verification);
plus Step 5 (3 `archive/cc-interactions/` → `manual-exports/<project>/`).
1.4 GB consolidated. 4/4 SHA spot-checks match. Surfaced layout
anomalies the inventory hadn't flagged: pre-toolkit hand-rolled archive
scaffolding (CATALOG.json files, query templates, `queries/`,
`examples/`) inside source `archive/cc-sessions/` trees rsynced into
the dest root, plus sub-category dirs (`theseus-ship/`,
`vlm-burial-mound-detection/`) as siblings of project_ids. Pass 1 also
clobbered the dest README I wrote 2026-05-21 (no `--ignore-existing` on
Pass 1).

**(4) Cross-machine verifier.** Shawn flagged that consolidation needed
to be comprehensive across amd-tower + zbook + sapphire, not just
amd-tower — and that continuity.md hadn't captured this earlier
intent. Dispatched read-only verifier agent SSH'ing to zbook + sapphire
+ amd-tower, inventorying all CC transcript locations, comparing
SHA-256 against the rpi-shares destination. Findings: amd-tower clean
(0 gaps), zbook has 363 actionable real-content files / 1.83 GB not in
dest (mostly in zbook's `~/cc-archives/` legacy global which doesn't
exist on amd-tower), sapphire effectively clean (only worktree stubs).
Plus 62 zbook + 86 sapphire "conflicts" all in the worktree-stub
byte-redundancy pattern (ignorable). One size-match SHA-diff at
`b80b94c6/session.jsonl.gz` flagged for triage.

**(5) Step 4b — zbook rsync.** Dispatched background agent. 3 passes,
all `--ignore-existing` so amd-tower content stays authoritative.
Pass 1 (zbook `~/cc-archives/`): 2,073 files / 1.89 GB. Pass 2
(per-project `archive/cc-sessions/`): 0 new files (all redundant).
Pass 3 (per-project `archive/cc-interactions/` → `manual-exports/`):
185 files / 10.8 MB. 4/4 SHA spot-checks match. Surfaced 12 new
top-level dirs + 1 file at root (CATALOG.json) — most legitimate
zbook-only project archives (FAIMS3, vivienne, absence-judgement,
TRAP-WD-2020-04, trap-extraction); a few needed disposition (Code,
shawn, lowercase `llm-history-paper`, HUMN8031-2026-S1).

**(6) Layout cleanup.** Direct Bash + Write ops on the SSHFS mount
(metadata-only renames, instant). Three groups:

- **Sub-categories under their parent projects**: `theseus-ship/`
  (50 sessions, pre-toolkit era) → `LLM-History-Paper/theseus-ship/`;
  `vlm-burial-mound-detection/` (100 sessions, pre-toolkit era) →
  `map-reader-llm/vlm-burial-mound-detection/` (map-reader-llm/ already
  at top level from zbook's legacy archive).
- **Non-session artefacts quarantined to `_legacy-archive/`**: 2 dirs
  (`queries/`, `examples/`) + 5 root-level files (`archive-defaults.yaml`,
  `catalog.json`, `CATALOG.json`, `CATALOG.md`, `metadata-todo.md`).
  Likely to be discarded after triage; consolidated here for inspection.
- **Cwd-derived buckets to `_misc-cwd/`**: `Code/` (8 sessions launched
  from `~/Code/` directly) and `shawn/` (3 sessions launched from `~/`).
  System/network troubleshooting work; new working-practice decision
  recorded (see architectural decisions below).

Plus: deleted 5 empty subdirs (4 in `manual-exports/` + lowercase
`llm-history-paper/`); wrote 3 new READMEs (consolidated root,
`_legacy-archive/`, `_misc-cwd/`) replacing the source-clobbered one.

**(7) b80b94c6 triage.** Verifier had flagged this as possible real
divergence; triage proved otherwise. SHAs across 4 known copies: 3 of
4 agree on `d0938f2d...` (the auto-archive JSONL output across dest +
2 zbook per-project paths); only zbook's `~/cc-archives/theseus-ship/`
holds the lone outlier `c4cc2504...`. Exactly the
`/export`-vs-auto-archive content-equivalent-but-byte-different pattern
Shawn outlined mid-session. Resolved as instance of deferred dedup
work, not a real divergence.

**Phase 0 consolidation final state**: 3.1 GB total at
`~/mnt/rpi-shares/cc-archives-consolidated/`, 594 `session.jsonl*`
files across 16 project_ids + 4 reserved namespaces (`_indexes/`,
`_legacy-archive/`, `_misc-cwd/`, `manual-exports/`) + 183 manual `.txt`
exports. 297 GB headroom remaining on the rpi-shares mount.

**Step 2 scope re-framing**: the multi-machine verifier revealed
1,024 + 2,043 + 17 = 3,084 live JSONLs across all three machines (the
"61 unarchived" from the 2026-05-20 inventory was specifically the
amd-tower-archived-and-needing-F3 subset). Materially expands the
eventual Gemini Flex sweep envelope. To be re-presented to the API
gate after this continuity commit lands.

- Background agents dispatched: 4 (Step 1 LFS pull; Step 4a amd-tower
  rsync; cross-machine verifier; Step 4b zbook rsync)
- New rpi-shares files (on the mount): `cc-archives-consolidated/README.md`
  (rewritten post-cleanup), `cc-archives-consolidated/_legacy-archive/README.md`,
  `cc-archives-consolidated/_misc-cwd/README.md`,
  `cc-archives-consolidated/manual-exports/README.md`
- New commits in map-reader-llm: `0efda174` (gitignore), `b740da63`
  (logs/launch-summary postmortem)
- Architectural decisions added below: 5 new ones (comprehensive
  consolidation scope; `/export`-vs-auto-archive dedup pattern;
  `_misc-cwd/` for cwd-derived buckets; future system-troubleshooting
  under `personal-assistant/`; HUMN8031-2026-S1 ≠ ANU-HUMN8031-2026)
- Commits pending — to be made after this continuity update lands

### 2026-05-21 (Thu) — Phase 0 destination resolved; rpi-shares layout published

Short PA-infrastructure background segment closing the rpi-server
destination question that gated Phase 0 consolidation. Discovered the
pre-existing `mount-rpi-shares` SSHFS alias (`~/.bash_aliases:9`) —
destination is `shawn@rpi-server:/opt/encrypted/workspace/shares`
mounted at `~/mnt/rpi-shares/`, 393 GB capacity / 300 GB available
(df reading; ~322 GB by Shawn's earlier check — same order of
magnitude, no concern), encrypted SSD share, previously empty
(newly available storage). Laid out the directory structure at
`~/mnt/rpi-shares/cc-archives-consolidated/` with reserved subdirs
`_indexes/` and `manual-exports/`, plus two READMEs (share-root +
inner) documenting the share's role + the cc-archives layout
contract, write-side rules, sizing, and cross-references back to
this file and the 2026-05-20 inventory.

Phase 0 plan updated in place: Step 3 ("Mount rpi-server NVMe") is
now a one-line `mount-rpi-shares` invocation with the silent-empty-dir
guardrail noted; Steps 4, 5, 7 rsync targets re-pointed from the
placeholder `~/cc-archives-mounted/cc-archives-consolidated/` to the
real `~/mnt/rpi-shares/cc-archives-consolidated/`. The
"Things to verify" item for rpi-server NVMe path + free space is
closed. New architectural decision recorded: destination location
+ tier distinction (SSD share for hot working archive;
vantec/qnap for bulk). One small correction folded into the
architectural-decisions section: the "full mirror everywhere"
canonical path was previously written as `~/cc-archives-consolidated/`
(no mount prefix); now reads `~/mnt/rpi-shares/cc-archives-consolidated/`.

- New files on the rpi-shares mount: `README.md`,
  `cc-archives-consolidated/README.md`, plus the reserved
  empty subdirs `_indexes/` and `manual-exports/`
- Modified PA planning docs: `planning/continuity.md` (this entry +
  verify-queue close + Phase 0 Step 3 rewrite + path replace_all +
  architectural-decisions edits), `planning/archive-inventory-2026-05-20.md`
  (Step 1 of "Recommended consolidation sequence"),
  `planning/memory-system-v2-implementation-plan.md` (Section 3.2 0b
  destination path + mount-alias correction)
- No code changes
- Commits pending — to be made at session close

### 2026-05-20 (Wed) — Audit remediation: C2 + C3 + C4 + M7-M15 + Lows + M6

Long session with substantial parallel agent dispatch. After yesterday's
audit + priorities 1-6, dispatched two background agents to clear the
remaining audit findings. Both landed cleanly with no rebase conflicts.

**(1) C2/C3/C4 agent** — `extraction-hook.py` + `sync-symlinks.sh`.
Transient Anthropic errors (5xx, 429, network timeout) now return a
`None` sentinel from `extract_memories`; `main()` distinguishes
sentinel from empty-list and skips cursor advance on transient errors.
Cursor file wrapped in `fcntl.flock` via `cursor_file_lock()` context
manager so concurrent `Stop` / `PreCompact` / `SessionEnd` firings
serialise rather than race. `sync-symlinks.sh` Step 7 pip exit code
now captured and propagated (was `&& ... || ...`, silently swallowed).
9 new tests in `tests/test_extraction_hook.py`. PA suite 690 → 699
passing.

**(2) Cleanup agent** — M7 (anchor_verify zero-anchors → None), M9
(extract-transcript-text.py → thin wrapper around toolkit module),
M10 (resample reproducibility — sorted glob + runtime timestamp),
M11 (setup.sh ERRORS check), M12 (note-only — schema change deferred
to v4), M13/M14/M15 (toolkit test tightening), plus ~12 Lows across
`archive.py`, `session-start-code-state.py`, `_command_markers.py`
(sync-board marker drift), `sync-to-postgres.py`, `bake-off-metadata.py`,
`project_id.py`, `analyse_caps.py`. 12 commits in PA, 2 in toolkit,
1 in pa-data. Toolkit 226/226 passing throughout.

**(3) M6 direct** — `extraction-hook.py` slash-command skip flag
auto-clear bug. Pre-fix: any non-command user entry cleared the skip
flag, so MCP-injected tool_result-as-user between `/remember` and its
assistant response un-skipped the response (sporadic double-extraction).
Post-fix: flag persists until the next assistant turn consumes it.
Removed `test_skip_flag_resets_on_normal_user_message` (pinned buggy
behaviour) and added `test_command_skip_flag_persists_across_user_entries`
with realistic MCP scenario + pre/post baselines.

Total commits this session so far: 14 (PA), 2 (toolkit), 1 (pa-data).

- New PA tests: `tests/test_extraction_hook.py` net +9 tests (10 added,
  1 removed); now 60 tests total
- New toolkit tests: `tests/test_transcript_text.py` already +6 from
  yesterday; this session added M13/M14/M15 assertions to existing
  tests
- Architectural decisions added below: 6 new ones (850K cap +
  middle-truncate; sampled cost estimation; transient-vs-permanent
  Anthropic semantics; cursor flock; CoT capture upstream-blocked;
  extract-transcript-text as thin wrapper)

**(4) Pre-consolidation inventory + LFS plan.** Shawn asked whether to
consolidate transcripts on rpi-server NVMe before F3 backfill; agreed
it was the right sequencing. Dispatched a read-only inventory agent
across all amd-tower archive locations (cast a wide net per Shawn's
prompt: included `.claude/projects/` live store,
`archive/cc-interactions/` pre-Dec-2025 manual exports, and the
search ranged broadly under `~/`). Findings: **307 unique main-thread
session IDs across 1,360 files / ~1.97 GB raw / ~1.45 GB consolidated**,
of which only **32 need F3** — the "307 historic sessions" figure in
prior continuity entries was the total unique-session count, not the
F3-needing subset. 61 live-only sessions never archived (need pre-F3
sweep). 182 manual `.txt` exports surfaced (Shawn's hunch confirmed).
Zero genuine content conflicts (170 size-mismatches all benign: live
vs gzip of same content). One genuinely unexpected discovery:
map-reader-llm has a worktree-archive at
`.claude/worktrees/agent-a59a9dae0bff3f27b/` that holds **canonical
content**; the per-project `archive/cc-sessions/` there is full of
Git LFS pointer stubs. LLM-History-Paper similarly has 49 LFS-pointer
files. Inventory artefact at `planning/archive-inventory-2026-05-20.md`.

Shawn requested LFS extraction NOW (not at journal submission) for
both projects; agreed. Expanded Phase 0 task list to 10 numbered
steps with concrete commands covering `git lfs pull` → 61-live
sweep → mount rpi NVMe → rsync per-source → park `.txt` exports →
`git lfs untrack` → `git rm --cached` + gitignore
`archive/cc-sessions/` in every project. New architectural decision
recorded: project repos do not carry `archive/cc-sessions/` going
forward; consolidated mount is the only location for transcripts.
`git lfs migrate export` full history rewrite deferred indefinitely
to post-journal-submission (low blast-radius cleanup, not blocking).

- Inventory + Phase-0-revision commit: `63b798d`
- LFS sequence expansion commit: `8c2e115`
- Auto-sync that landed mid-session: `8c0ba53`
- New PA file: `planning/archive-inventory-2026-05-20.md`
- Architectural decision added: "Project repos do not carry
  `archive/cc-sessions/`" (per-project gitignore + permanent LFS
  resolution as a side benefit)

**(5) Handoff ritual** (this segment). Standard `/handoff` five-step
close: continuity extended (this entry), 3 working-notes drafted +
accepted, 3 wiki-candidate inbox entries added, 4 user-observations
drafted + all accepted by Shawn. Final commits below.

### 2026-05-19 (Tue) — Audit + 850K cap design + CoT investigation + priorities 1-6

Substantial session running as deliberate PA-infrastructure background.
Four movements:

**(1) Cap analysis + 850K design.** After discovering per-block caps
in `transcript_text.py` (TOOL_RESULT_MAX_CHARS=4000, TOOL_USE_INPUT_MAX_CHARS=1500)
were clipping substantive content from summarisation, ran empirical
analysis over 242 archived sessions (`analyse_caps.py`). Three regimes
costed: current caps (A), uncapped tool blocks (B), B + thinking blocks
(C). Found B and C nearly indistinguishable because 229/242 sessions
have empty thinking text (Anthropic redaction; see CoT investigation
below). Found B delta over A is negligible (~$3 backfill, ~$1.50/mo
ongoing) but worst-case session under B lands at 974K tokens — 97.5%
of Gemini's 1M context. Decided on uncapping + 850K-token emergency
cap with middle-truncation (preserves head + tail, drops repetitive
middle). Worst-case session under middle-truncate would lose ~6 user
turns out of 69 vs ~13 lost under tail-truncate. Implementation +
tests landed same day.

**(2) Code audit.** Dispatched 6 parallel subagents over 21 source
files / ~10,800 lines (toolkit core, toolkit tests, PA hooks, PA memory-
system v2 scripts, PA bake-off/experiments, PA shell). Consolidated
report identified 4 Critical, 15 Medium, ~20 Low findings. Most
significant: archive.py uncaught AttributeError when Gemini's
`response.text` is None (safety-filter case); extraction-hook silent
cursor advance on Anthropic API failure; cursor file not flocked
across concurrent firings; sync-symlinks pip exit code swallowed.

**(3) Priorities 1-6.** Shawn approved direct fix of M1+M2 (transcript_text
pathological edges), C1 (response.text None guard), M3 (`.get() or
default` for null Gemini fields), M5 (stale Haiku sweep), M4 (refined
backfill cost estimator with `--cost-sample-size`), M6 correction
note. All landed across the toolkit + PA. Toolkit 220 → 226.

**(4) CoT capture investigation.** Dispatched claude-code-guide (CC
docs + settings audit) + prior-art-scout (community-tool survey).
Confirmed thinking text is empty in CC JSONLs by Anthropic design as
of v2.1.72 (`tengu_quiet_hollow` flag + `redact-thinking-2026-02-12`
beta header). Three relevant issues closed as won't-fix; one open
feature request (`#39343`) is the right upstream fix. Surveyed
community tools: `agentsight` (eBPF), `claude-code-proxy` (Go MITM),
`llm-interceptor` (Python mitmproxy) — none built for research-grade
FAIR capture. Wrote report at
`docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md`
with three-horizon recommendations including candidate JOSS tools
paper + RDA IG Tier-2 output framing.

**(5) Commit-and-push.** 3 commits to toolkit, 2 to pa-data, 3 to PA
(including `.gitignore` for stray `archive/cc-sessions/` and submodule
pointer bump). All pushed.

- New PA file: `docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md`
- New pa-data: `experiments/transcript-cap-analysis-2026-05-19/` (script + findings.md + per-session.csv + summary.txt)
- New toolkit file: `tests/test_transcript_text.py` (15 + 6 pathological tests)
- Modified toolkit: `transcript_text.py` (uncap + 850K + middle-truncate + pathological edges),
  `archive.py` (None guard, .get() or default, Haiku → Gemini Flex),
  `cli.py` (Haiku → Gemini Flex), `tests/test_hook.py` (M5 docstring),
  `scripts/backfill-session-metadata.py` (.get() or default, --cost-sample-size sampler)
- Architectural decisions added: 5 new (850K cap rationale + middle-
  truncate over tail-truncate; sampled cost estimation; full-transcript
  rather than capped; reasoning-trace upstream blocked; analyse_caps
  framing-strip caveat)
- Agent dispatches: claude-code-guide (CC docs check), prior-art-scout
  (community capture tools), 6 parallel general-purpose (code audit)

### 2026-05-18 (Mon, follow-up session) — Small follow-ups + v3 spot-check + workstream F1+F2 wire-up

PA-infrastructure session run as deliberate background. Three movements,
all completed in one window:

**(1) Three small open follow-ups closed.** `hooks/session-start-code-state.py`
(new SessionStart hook) writes `data/code-state/<session_id>.json`
sidecar with `commit_at_start`; `cc_session_toolkit.archive.capture_code_state`
extended with `session_id` + `sidecar_dir` kwargs and a
`_load_code_state_sidecar` helper. New `CODE_STATE_SIDECAR_DIR` config
constant with env-var override. Hook wired into both `settings.json`
(live) and `settings-template.json` (tracked). Toolkit tests 214 → 220
passing; 6 new in `test_subagent_archive.py`. Hook hardening: both
PreCompact + SessionEnd archive commands swapped
`export $(grep -v '^#' ... | xargs)` → `set -a && . ... && set +a` —
robust to quoted/spaced values. Bake-off script tidy: `--yes` flag
added; `haiku_apply` path fixed (was reading from wrong dir); print
hint updated to `out_dir.parent`.

**(2) v3 hook spot-check — healthy.** 13 post-v3 memories
(`created_at > 2026-05-18T00:00`), all 13 with both
`source_message_uuid` *and* `extractor_model_id` populated; every one
recorded `claude-haiku-4-5-20251001`. Zero schema/sync/anchor
tracebacks. Single transient Anthropic 529 Overloaded at 13:38:59
(request id `req_011Cb9LZzm1ph8knL9g9iP2s`) caught cleanly; next firing
at 14:11 succeeded. v3 schema (Gaps 1+3 columns) is writing correctly
end-to-end through hook → JSONL → Postgres.

**(3) Workstream F1+F2: Gemini Flex wired into production.** Full swap
of `cc_session_toolkit.archive.generate_auto_metadata` from Anthropic
Haiku Batch (sampled-message) to Google Gemini 3 Flash Preview (Flex
tier, full distilled transcript). Design choices surfaced as
`AskUserQuestion` upfront — Shawn accepted all four defaults: prompt
bundles into toolkit as package data; transcript extractor copies into
toolkit as a module; Anthropic path drops entirely (no fallback);
backfill held until live SessionEnds reviewed. New module
`cc_session_toolkit/transcript_text.py` (ported from
`scripts/extract-transcript-text.py`). New package data
`cc_session_toolkit/prompts/auto_metadata.md` (shipping copy of
`prompt-gemini-v2.md`; override via `CC_AUTO_METADATA_PROMPT_PATH`).
New helpers `_load_auto_metadata_prompt`,
`_build_auto_metadata_user_message` (system_instruction +
`<transcript>` tags + post-transcript reminder),
`_parse_metadata_response_json`, `_call_gemini_once`
(`thinking_budget=0`, `service_tier="flex"`), `_call_gemini_with_retry`
(503 backoff (30, 60, 120)), `_ensure_gemini_api_key`. Sampling /
meta-filter machinery removed entirely (`_is_meta_message`, `_META_*`,
`_ensure_anthropic_api_key`, `re` import). `EXTRACTOR_MODEL_ID` switched
`claude-haiku-4-5-20251001` → `gemini-3-flash-preview`. `pyproject.toml`
`api` extra flipped `anthropic>=0.40` → `google-genai>=2.3`. PA venv
reinstalled with editable cc-session-toolkit so the hook picks up the
new path on next SessionEnd. Tests reshaped: toolkit 220 → 205 (32
obsolete sampling/meta-filter tests dropped; 17 new Gemini-shape tests
added — helpers, integration with mocked `google.genai` client, 503
retry recovery, exhausted-retry → None, non-503 → None, unparseable
JSON → None). PA suite 690 unchanged. F3 (~$8.30 backfill of 307
sessions) and F4 (QA on ~20 samples) parked behind explicit gate
approval after Shawn reviews live SessionEnd outputs.

- PA new: `hooks/session-start-code-state.py`
- PA modified: `settings.json` + `settings-template.json` (set-a hardening, SessionStart sidecar wiring), `scripts/bake-off-metadata.py` (--yes flag, haiku-apply path fix), `planning/continuity.md` (substantial — workstream F status, things-to-verify, three new architectural decisions, this session-log entry), `wiki/working-notes.md` (new entries from this session), `wiki/user-observations.md` (new candidates), `notes/_inbox.md` (new wiki candidates)
- Toolkit new: `src/cc_session_toolkit/transcript_text.py`, `src/cc_session_toolkit/prompts/auto_metadata.md`
- Toolkit modified: `src/cc_session_toolkit/archive.py` (capture_code_state sidecar lookup + full Gemini Flex swap), `src/cc_session_toolkit/config.py` (CODE_STATE_SIDECAR_DIR + EXTRACTOR_MODEL_ID flip + Gemini constants), `pyproject.toml` (anthropic → google-genai + prompts package-data), `tests/test_subagent_archive.py` (+6 sidecar tests), `tests/test_hook.py` (sampling tests → Gemini tests, net -15), `scripts/backfill-session-metadata.py` (Gemini API key + cost line + three_ps native write)
- Tests: toolkit 205 passing; PA 690 passing (with 2 deselected)
- Commits pending — to be made at this `/handoff` step 5

### 2026-05-18 (Mon) — Provenance audit closure + wiki sketch + auto-metadata bake-off

Long session run as deliberate background while primary foreground was
elsewhere. Three discrete movements:

**(1) Three quick steps in parallel.** Dispatched agents for `/handoff`
skill implementation, `session-start-protocol.md` draft, and provenance
Gap 1 (`source_message_uuid` plumbing). All three returned green; schema
bumped v2 → v3 with live PG migration applied. Tests 680 → 690.

**(2) Wiki design exercise.** Decided structural ambiguity (Option A2:
`personal-assistant/wiki/` plays both roles, with cross-project
sub-collections like `notes/`, `grimoire/`, future `templates/`,
`bibliographies/` sitting alongside PA-project artefacts). Drafted
`notes/index.md` (notes-specific) + `notes/_tags.md` (24-tag vocab
across four groupings) + `planning/wiki-index-draft.md` (sketch of the
eventual top-level `wiki/index.md`). Frontmatter shape settled
(title + tags + created + updated + status). Lit-scout file destinations
decided for the pilot migration (table in workstream D pending tasks).

**(3) Provenance audit Gaps 2 + 3.** Dispatched agent for both gaps
across two repos (PA + cc-session-toolkit). `code_state.{commit_at_end,
dirty_at_end}` now captured at archive time; `commit_at_start` is an
honest gap requiring a SessionStart-hook sidecar (queued). `licence` +
`extractor_model_id` plumbed through; UK spelling unified after agent
defaulted to American; live PG migration applied for both new columns.

**(4) Auto-metadata bake-off.** What started as a cost question
("should we backfill the 32 empty March cohort with Haiku?") became a
top-to-bottom redesign. Found the 2026-03 cohort regression had already
been fixed 2026-04-10 (commit `aeebe158` — brittle `export $(... |
xargs)` shell idiom in hook settings; Python `.env` fallback masks it
now). But also found 49 other sessions on a different fallback path
("No description provided"), and discovered the existing prompt sees
only sampled messages — not the full transcript. Pivoted to a
full-transcript redesign + provider bake-off (Haiku Batch vs Gemini
Flash Flex). Ran 5 iterations: base prompt → tuned-v1 (added Specifics
Requirement section + comparisons table) → tuned-v2 (added Structural
Requirements: sequencing, rejected alternatives, contrastive numbers,
user voice, conceptual characterisation, session-shape labelling) →
v2.1 (added title named-entity rule). Verdict landed: **Gemini Flex +
`prompt-gemini-v2.md` wins on every dimension** (quality 17–7 Haiku
in cells; reliability 10/10 vs 7/10; cost ½ Haiku; single one-shot
call vs chunking complexity).

**(5) Started this session-close ritual.** First formal use of
`/handoff` since the skill was implemented earlier in the same session
— mildly recursive.

- New PA files: `commands/handoff.md`, `global-claude-md/session-start-protocol.md`, `planning/wiki-index-draft.md`, `scripts/extract-transcript-text.py`, `scripts/bake-off-metadata.py`, `scripts/resample-bake-off-manifest.py`
- Modified PA files (Gaps 1+3): `hooks/extraction-hook.py`, `scripts/schema.sql`, `scripts/_schema_version.py`, `scripts/sync-to-postgres.py`, 5 test files
- New PA wiki seeds (this `/handoff`): `wiki/working-notes.md`, `wiki/user-observations.md`
- New cc-session-toolkit files (Gaps 2+3): `src/cc_session_toolkit/archive.py`, `src/cc_session_toolkit/config.py`, `tests/test_subagent_archive.py`
- Data submodule: `notes/index.md`, `notes/_tags.md`, `experiments/bake-off-metadata-2026-05-18/` (prompts, manifest, launch plan, 4 populated rubrics, 5 response sets)
- Network-resources correction (data submodule, from concurrent work on the pg_trgm thread)
- Tests: 680 → 690 PA passing; cc-session-toolkit 202 → 214
- Live PG migration applied: 3 new columns (`source_message_uuid`, `licence`, `extractor_model_id`) + 2 partial indexes
- Bake-off spend: ~$1.45 (29% of $5 cap)
- Architectural decisions added below: 3 new ones (Gemini for auto-metadata; named-entity preservation in titles; full-transcript over sampled)
- Commits pending — to be made at this `/handoff` step 5

### 2026-05-17 (Sun) — Memory-system top-to-bottom rethink + Vector 2 design + wiki formalisation

Long session that began with verifying yesterday's v2 hook firings
(found that the doc's expectation `verified_set == post_v2` was wrong —
correct invariant is `verified_set == with_anchors`; verification is
intentionally gated on Haiku producing anchors, line 876–877 of
extraction-hook.py; 9/18 anchor production rate in the post-deployment
cluster, borderline per the doc's own threshold but not actionable
until larger sample). Then drafted Vector 2 design
(`planning/vector-2-design.md`) — hybrid digest + lazy depth, ≤1.5 KB
target, two-stage rollout, six open questions captured.

Mid-session, Shawn raised broader concerns: dump too large /
insufficiently grounded / causing confabulation; escalation through
3-tier memory not happening; tier-3 connections broken; CC rarely
interacts with the system. This triggered a top-to-bottom rethink.
Honest finding: continuity.md (an accident from 2026-05-16) was
delivering more cross-session value than the entire 17 KB recall dump;
auto-extraction loop is the load-bearing problem, not the surfacing
layer. Dispatched `prior-art-scout` for state-of-practice survey
(strong validation: field has converged on tiered architectures +
session-end handoff docs + curation review; recall-trigger problem
unsolved field-wide; Karpathy wiki pattern validates topic-notes idea;
some arXiv IDs in report flagged as suspect — 2603.* IDs pre-date
today). Survey also surfaced retrieval-vs-write asymmetry (~20 vs ~3–8
accuracy points), demoting Phase 6.

Converged on **four-artefact picture** + **two ritual moments**:
continuity.md (state), working-notes/reflections/user-observations
(raw obs), notes/<topic>.md (curated cross-project knowledge),
scratchpad (principles) — knit together by `/handoff` (per
session-close) and `/weekly-review` (curation via cluster-and-carry
from candidate pools). Memory corpus reframed as candidate pool, not
surfacing layer.

Open-science / RDA IG angle then integrated: Shawn co-chairs the
"Documenting Generative AI Interactions in Research" IG (with Brian
Ballsun-Stanton). Three Ps framework (Prompt, Process, Provenance)
already pre-committed in `session.meta.json` schema (quiet win).
Dispatched provenance audit (`general-purpose`) — three specific gaps
identified for opportunistic closure (source_message_uuid, git commit
hashes, license + extractor_model_id); empty `*_summary` fields are
the quiet embarrassment to fix. Phase 0 archive consolidation
promoted in priority because it unlocks topic-search across
transcripts (an open-science feature).

Two protocol docs landed (`continuity-protocol.md`, `handoff-protocol.md`)
and one craft entry (session-wind-down trigger). Wound down at ~20%
context use because the work converged — applied the new "should vs
must" trigger. During the handoff itself, Shawn flagged two protocol
refinements which were folded into `handoff-protocol.md` before
commit: (a) at step 4 (user observations), I should *draft candidate
observations* rather than just ask the open question — candidates jog
memory and prompt better observations; (b) at step 5 (commit), default
is commit-and-push everything before handoff closes, batched by
logical area for legibility.

- Planning docs created: `planning/vector-2-design.md`
- Protocol docs created: `global-claude-md/continuity-protocol.md`,
  `global-claude-md/handoff-protocol.md`
- Craft notebook: `notes/working-practices.md` (2026-05-17 entry)
- Agent runs: `prior-art-scout` (memory systems state of practice);
  `general-purpose` (provenance audit)
- Reference docs (Shawn-provided): `docs/open-science/RDA_IG_*.docx`
- This file (substantial update): three verifications marked done;
  workstreams A/B updated to reflect supersession; new workstreams D
  (rethink) and E (RDA IG); 9 architectural decisions added;
  reference table extended
- No code changes this session; all design + protocol docs
- Commits pending — to be made after `/handoff` review

### 2026-05-16 (Sat) — Phases 1–3 of memory v2 shipped

Long session pushing the forward pipeline of the v2 confabulation fix.
Pre-v2 backups taken to two locations (`data/archive/pre-v2/` and
`~/cc-archives/pre-v2/` on rpi-server). Schema migrated v1→v2 (seven
new fields plus `feedback` category; pre-existing `subagent_count`
bug fixed in passing). `sync-to-postgres.py` updated for the new
column list and Json-wrapped JSONB values. New slash commands
`/forget` and `/update` implement memory-correction L1.
`scripts/anchor_verify.py` is the new mechanical verifier module;
`project_id.py` extended with `repo_set` auto-discovery. The
extraction hook now runs every extracted memory through
`verify_memory` and replaces Haiku's self-rated confidence with the
binding rubric. `EXTRACTION_PROMPT` updated to request anchors and
handle self-correction (L2). `COMMAND_MARKERS` extended for
autonomous-save / forget / update announce lines (L1 autonomous
path, Phase 3). Test suite 648 → 680 passing.

Phase 0 was deferred during the session when toolkit-layout discovery
showed two archive locations active (`~/cc-archives/` historical and
`<project>/archive/cc-sessions/` current) — reconciliation deserves a
focused session. Architecture decision made: **full mirror everywhere**
with R2 as offsite + travel bridge. R2 credentials configured on all
three machines using per-machine API tokens (rpi-server's hyphenated
remote name `r2-pa-cc-archives` keeps creds in `rclone.conf` directly;
amd-tower + zbook use env-var pathway with remote `r2archives`).

- Commits: `2b71151`, `17dc5bc` (backups); `03b86ad`, `d666470`
  (Phase 1); `50e663b` (Phase 2); `7078d39` (Phase 3); plus earlier
  `c5d3c36` (impl-plan v2 with Phase 0 added)
- Planning docs created/updated: `memory-system-v2-design.md` (resolved
  decisions added), `memory-system-v2-implementation-plan.md` (Phase 0
  added, completed-block updated, R2 foundation marked done),
  `memory-system-v2-future-extensions.md` (new register),
  `memory-corpus-audit-2026-05-14.md` (audit), this file
- Code: `scripts/schema.sql`, `scripts/_schema_version.py`,
  `scripts/sync-to-postgres.py`, `scripts/anchor_verify.py` (new),
  `scripts/project_id.py`, `scripts/_command_markers.py`,
  `hooks/extraction-hook.py`, `commands/remember.md`,
  `commands/forget.md` (new), `commands/update.md` (new),
  `global-claude-md/memory-system-reference.md`
- Tests: `tests/test_anchor_verify.py` (new, 32 tests);
  schema_version bumps in `test_sync_script`, `test_apply_decay`,
  `test_rebuild_postgres`, `test_sync_sessions`,
  `test_command_markers`

### 2026-05-15 (Fri) — v2 design resolved + R2 infrastructure

Resolved all 8 open questions from the 2026-05-14 design draft;
folded decisions into the design doc. Added Phase 0 to the
implementation plan. R2 setup on amd-tower and zbook with per-machine
API tokens. Self-healing venv infrastructure shipped (requirements.txt
+ sync-symlinks Step 7 + setup.sh updates) — fixes amd-tower's silent
SessionEnd archive failure (cc_session_toolkit was missing from venv).

- Commits: `85c832a` (write-anchor rule), `0177189` (audit + design),
  `10c36b2` (impl + future-extensions), `7d097af` (self-healing
  venv), plus rpi-server bootstrap commits

### 2026-05-14 (Thu) — Investigation + design draft

Cross-machine sync between amd-tower and zbook (the original purpose
of the day). Then triggered into the v2 design work after Shawn raised
the verifier's recurring confabulation hits. Corpus audit run as
background agent; produced the empirical basis. Design doc drafted
with 8 open questions; implementation plan drafted with 6 phases.
Three-tier model investigation began; established that tier-3 archive
is operationally broken (then corrected: 92% cross-machine
resolution).

- Commits: `1f01781` (teaching-contexts CLAUDE.md), plus the merge
  + sync commits and the audit/design docs
