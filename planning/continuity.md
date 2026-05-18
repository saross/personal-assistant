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
- [ ] **First firing of Gemini Flex auto-metadata path** (new 2026-05-18,
  workstream F1+F2). PA venv reinstalled with editable
  cc-session-toolkit; next SessionEnd / PreCompact runs the new path
  automatically. Spot-checks:
  - **No log noise:** `tail -50 ~/personal-assistant/data/logs/auto-metadata.log`
    — look for "Calling Gemini Flex for ...", "Success for ...".
    Tracebacks or "FAIL"/"ERROR" lines mean the wire-up has a bug.
  - **Real outputs:** pick the most recent archive
    (`ls -td ~/cc-archives/personal-assistant/*/ | head -3`),
    read `session.meta.json`. Verify `auto_generated` carries a
    descriptive title, non-empty purpose, lowercase-hyphenated tags;
    `three_ps` has all three summaries populated (not empty strings).
  - **Sidecar:** the SessionStart sidecar at
    `~/personal-assistant/data/code-state/<session_id>.json` should
    have been written; `code_state.commit_at_start` in the
    `session.meta.json` should be the SHA at session start.
  - **`extractor_model_id` field:** new sessions should carry
    `gemini-3-flash-preview` (not `claude-haiku-4-5-20251001`).
  - **Model ID GA-rename watch:** if Google renames `gemini-3-flash-preview`
    → `gemini-3-flash` at GA, the call will start failing with
    "model not found". Bump the constant in
    `cc_session_toolkit/config.py:EXTRACTOR_MODEL_ID`.

## Pending tasks (cross-session)

These survive across sessions. Mark `[x]` with date when done.

- [ ] **Backup cleanup**: remove one of the two pre-v2 backups (in
  `data/archive/pre-v2/` or `~/cc-archives/pre-v2/` on rpi-server)
  after ≥1 week of stable v2 operation. Default removal target:
  pa-data copy (keeps git lean; the 96 MB `claude_memories.dump` is
  the bulk).
- [ ] **Phase 0 — focused session**: archive layout consolidation.
  Sub-items:
  - [ ] Backfill amd-tower's 91 unarchived live transcripts
  - [ ] Reconcile two archive layouts (old `~/cc-archives/` vs new
    `<project>/archive/cc-sessions/`) when consolidating
  - [ ] Set up `~/cc-archives-consolidated/` on rpi-server NVMe
  - [ ] Add rsync step to `daily-sync.sh`
  - [ ] Build `scripts/resolve_session_id.py` (cross-machine resolver)
  - [ ] Decide on indexing pattern: rpi-side cron vs working-machine
    SSHFS-mounted index
- [ ] **Phase 0e — R2 wiring** (once Phase 0b stable): rclone push
  from rpi-server to R2 daily; working-machine push to R2 when
  rpi-server unreachable (travel mode); rpi-server reconciles on next
  sight. R2 credentials are configured on all three machines already
  (see `~/personal-assistant/.env` on amd-tower + zbook, and
  `~/.config/rclone/rclone.conf` on rpi-server).
- [x] 2026-05-17 **Vector 2 — open design doc** (`planning/vector-2-design.md`) — done; implementation parked under workstream D
- [ ] **Phase 4 — typed links** — **superseded by workstream D**; the typed-links problem is now solved by wiki-page cross-references + working-notes references + frontmatter tags
- [ ] **Phase 5 — migration sweep** — **demoted**; still useful as backfill for `verified` field but no longer gating anything
- [ ] **Phase 6 — extractor bake-off** — **deprioritised** (prior-art-scout: write strategy ~3–8 retrieval-accuracy points vs ~20 for retrieval; wrong lever)

**Small open follow-ups (new 2026-05-18):**

- [x] 2026-05-18 **SessionStart-hook sidecar for `commit_at_start`** — `hooks/session-start-code-state.py` writes `data/code-state/<session_id>.json`; `cc_session_toolkit/archive.py:capture_code_state()` now takes `session_id` + `sidecar_dir` kwargs and reads the sidecar best-effort. Hook wired into `settings.json` SessionStart array. Tests: 6 new in `test_subagent_archive.py`; full toolkit 220 passing.
- [x] 2026-05-18 **Hook hardening (`~/.claude/settings.json:91,112`)** — replaced `export $(grep -v '^#' ... | xargs)` with `set -a && . ~/personal-assistant/.env && set +a` on both PreCompact + SessionEnd archive commands. The Python `.env`-fallback pattern (`_ensure_anthropic_api_key` → `_ensure_gemini_api_key` post-F1) is retained inside `cc_session_toolkit.archive` as belt-and-braces.
- [ ] **`pg_trgm` extension missing on `claude_memories` DB** — `idx_memories_content_trgm` (`scripts/schema.sql:79`) has been silently failing to create. Non-critical (full-text search uses a different index). Either run `sudo -u postgres psql -d claude_memories -c "CREATE EXTENSION pg_trgm;"` or drop the index from schema.sql.
- [x] 2026-05-18 **`scripts/bake-off-metadata.py` tidy-up**: (a) `--yes` flag added (bypasses interactive `input()` for non-interactive runs); (b) `haiku_apply` path now navigates to `<root>/haiku/` to match where `haiku_submit` persists `batch-state.json`; print hint in submit updated to print `out_dir.parent` so the copy-paste is correct.

**Workstream F — auto-metadata production switch (new 2026-05-18):**

- [x] 2026-05-18 **F1: Gemini Flex wired into `cc_session_toolkit.archive.generate_auto_metadata`** — full replacement. New module `cc_session_toolkit/transcript_text.py` (ported from PA `scripts/extract-transcript-text.py`); new package data `cc_session_toolkit/prompts/auto_metadata.md` (shipping copy of `prompt-gemini-v2.md`); new helpers `_load_auto_metadata_prompt`, `_build_auto_metadata_user_message`, `_parse_metadata_response_json`, `_call_gemini_once`, `_call_gemini_with_retry`, `_ensure_gemini_api_key`. Old sampled-message machinery (`_is_meta_message`, `_META_*` sets, sampled-message loop, `_ensure_anthropic_api_key`, `re` import) all removed. `pyproject.toml` `api` extra flipped `anthropic>=0.40` → `google-genai>=2.3`; `prompts/*.md` added to package data. Test suite reshaped: dropped 32 obsolete sampling/meta-filter tests, added 17 Gemini-shape tests (helpers, integration with mocked `google.genai` client, 503 retry recovery, exhausted-retry → None, unparseable JSON → None). Toolkit 205 passing. PA suite 690 still passing — no callers broken.
- [x] 2026-05-18 **F2: `EXTRACTOR_MODEL_ID` switched** from `claude-haiku-4-5-20251001` to `gemini-3-flash-preview` in `cc_session_toolkit/config.py`. New constants `AUTO_METADATA_MAX_OUTPUT_TOKENS=1024`, `AUTO_METADATA_FLEX_RETRY_WAITS_SECONDS=(30, 60, 120)`, `GEMINI_FLEX_INPUT_PRICE_PER_MTOK=0.25`, `GEMINI_FLEX_OUTPUT_PRICE_PER_MTOK=1.50`.
- [x] 2026-05-18 **PA venv reinstalled** with `pip install -e ~/Code/cc-session-toolkit` so hook firings on amd-tower use the new path. zbook + rpi-server pip installs still pinned to the old non-editable wheel — re-run editable install on those machines or push a new tagged release before relying on the new path there.
- [x] 2026-05-18 **`scripts/backfill-session-metadata.py` updated** for the Gemini path: `_ensure_gemini_api_key`, cost line ~$0.027/session, `update_metadata` writes Three Ps natively (was preserving empty defaults).
- [ ] **F3: Backfill 307 historic sessions** — BLOCKED on Shawn's gate approval after live-output review. Est. ~$8.30.
- [ ] **F4: QA pass on ~20 sampled backfill outputs** — depends on F3.
- [ ] **GA-rename watch**: model id `gemini-3-flash-preview` is still "Preview"; bump constant when GA renames to `gemini-3-flash` (or similar).

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
- **Session archive: full mirror everywhere.** rpi-server NVMe holds
  canonical `~/cc-archives-consolidated/<project>/<session>/`;
  working machines hold full local mirrors. R2 is offsite + travel
  bridge. Decided 2026-05-16.
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
  decision: keep the toolkit reproducible standalone.

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
| Current FOCUS slots | `tasks/FOCUS.md` | Knowing whether to mention slot pressure (don't if PA work is deliberate background) |

---

## Recent session logs

*Most recent at top. One paragraph + bullets per entry.*

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
