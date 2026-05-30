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

### B. Session-start payload reduction (Vector 2 / injection issue) — *design landed 2026-05-17; PASS 1 (engine + proof, hook untouched) shipped 2026-05-30; PASS 2 (live cutover) shipped + enabled on amd-tower 2026-05-30 — 2-week §8 observation window running; Vector 2b (scratchpad byte budget) shipped DARK 2026-05-30 — enable after §8 review*

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
- [x] 2026-05-30 **PASS 1 — Stage 1 engine + before/after proof, live
  hook untouched.** Greenfield (no prior scaffolding). Delivered:
  `scripts/digest.py` (pure selector: what-changed counter + verified-true
  ranking + promoted-recent fallback + hard byte cap + log primitive; no
  I/O, no hook import), `tests/test_digest.py` (28 tests pass),
  `scripts/digest-preview.py` (dry-run harness — reproduces the live recall
  dump via the hook's own `retrieve_*`/`format_context`, then prints
  before/after), plus best-effort `fetch-memories.log` instrumentation in
  `scripts/fetch-memories.py:main()` (design §7c tier-2 utilisation; the
  on-demand script, NOT the session-start hook) and a `digest.log`
  primitive. **`/audit` run on all four files (4 parallel subagents,
  execution-verified):** found 1 real Critical + 3 Medium + Lows, all
  fixed in-session — (Critical) the byte-cap docstring over-claimed an
  unconditional guarantee but ~550 B of scaffolding is irreducible
  (`build_digest([], byte_budget=50)` → 522 B); reworded to state the
  scaffolding-floor contract + added sub-floor/tight-budget/multibyte cap
  tests; (Medium) greedy `break` abandoned the whole tail when the
  top-ranked entry was oversized → empty digest, switched to `continue`
  (better packing — live digest went 3→4 entries shown); (Medium)
  `count_changes` double-counted a created-and-revised-in-window record as
  both new and updated, fixed to count updated/forgotten only for
  pre-window-created records; (Medium) the preview harness printed the
  uncapped 27-category list, diverging from the digest text — now calls
  `digest._format_categories`; (Lows) `render_entry` non-string-summary
  guard, `fetch-memories.log` `tag:` colon format. Test count 28→35 for
  digest; **full suite 734 passed, 0 regressions.**
  **Re-measured baseline (reproducible via `scripts/digest-preview.py`):**
  recall dump 16,222 B (PA hub) / 17,480 B (inscriptions) → digest 1,370 B
  → **~91–92 % cut on the recall dump** (≤1,500 B hard cap, proven by test
  + live). The design's 2026-05-16 table (recall 16,554 B, total 43,958 B)
  still holds within noise; scratchpad has grown to ~29 KB.
  **Key finding — design premise obsolete:** the design assumed only 8
  `verified=true` corpus-wide so the fallback would carry Stage 1; reality
  is **284 verified-true in the last 7 days alone** (dry-run output
  2026-05-30) — two weeks of v2-hook firings populated `verified` far
  faster than anticipated. Fallback never fired; it is already
  near-vestigial. Also fixed a starvation bug the dry-run exposed: the
  what-changed line itemised all 27 categories (~900 B), crowding verified
  entries to 2-of-284; capped to top-6 + "+N more" (`MAX_CATEGORY_BREAKDOWN`
  in `digest.py`), now 3 shown.
- [x] 2026-05-30 **PASS 2 — live cutover shipped + enabled on amd-tower
  (commit `68427cd`).** Shipped dark (flag default OFF → byte-identical
  legacy path; the existing 83 retrieval-hook tests stayed green untouched),
  then enabled on amd-tower via the go/no-go. Delivered: machine-local flag
  in `hooks/session-start-retrieval.py` (`digest_mode_enabled()` precedence:
  env `PA_DIGEST_STAGE1` truthy/falsy override → sentinel `~/.pa-digest-stage1`
  → OFF; **deliberately NOT in the synced `data/` submodule** so amd-tower
  enablement does not leak to zbook + rpi-server, which keep the legacy hook);
  a digest branch in `main()` that skips the four `retrieve_*` passes and
  emits `digest.build_digest(...)`; a per-firing `digest.log` write via
  `build_session_digest()` (best-effort, never raises — proven by a test
  that points the log at an unwritable path and asserts the session is still
  served). Relocated the tier-2 protocol to
  `global-claude-md/tier-2-retrieval.md` (design §7e); digest footer points
  at it (byte-neutral — still 4 verified entries at 1,488 B live). Tests:
  +19 (flag precedence/parsing + digest-mode `main()` output + best-effort-log
  contract) with an autouse fixture pinning the flag OFF so the suite is
  independent of operator machine state once the sentinel exists; **full
  suite 753 passed, 0 regressions** (was 734). **Enabled 2026-05-30**:
  sentinel `~/.pa-digest-stage1` created on amd-tower (this host;
  `digest_mode_enabled()` verified True via the sentinel path with env
  unset). Live smoke (inscriptions cwd): flag OFF → `# Memory Context`
  48,083 B; flag ON → `# Session-start digest`, digest 1,488 B (≤1,500 cap,
  log line `bytes=1488 shown=4 verified_available=305 fallback=False`), total
  payload 32,078 B. **Honest aggregate:** recall dump −91%, but TOTAL
  session-start payload only −33% (48→32 KB) because the ~30 KB scratchpad
  is untouched (out-of-scope "Vector 2b"). Rollback: `rm ~/.pa-digest-stage1`
  or `PA_DIGEST_STAGE1=0`.
  - [ ] **§8 observation-window review (due ~2026-06-13, 2 weeks out).**
    After the window, evaluate the four §8 measurements — (1) digest bytes
    median ≤1,500 B / p95 ≤2 KB from `data/logs/digest.log`; (2) /recall +
    fetch-memories invocation rates from `logs/fetch-memories.log` vs the
    pre-ship baseline (hypothesis: lazy-depth *increases* them; if not, depth
    isn't being fetched and the digest is starving rather than disciplining);
    (3) verifier confabulation-flag rate pre- vs post-ship; (4) Shawn's
    subjective too-thin/too-thick signal. Then decide go/no-go on the
    zbook + rpi-server rollout (and the Stage 2 fallback removal once
    verified-coverage is broad). If any of (1)–(4) flunks, `rm` the sentinel
    to roll back amd-tower and revise the design.
- [ ] **Finding (3) — digest density tuning, deferred (return to later
  per Shawn 2026-05-30).** At 1,500 B with ~8-tags-per-entry memories, only
  ~3 verified entries surface. Two levers, both judgment calls about digest
  information density (left at design defaults rather than decided
  unilaterally): (a) raise the byte budget toward the 2 KB p95 ceiling
  (`DEFAULT_BYTE_BUDGET` in `digest.py`, design §7b); (b) cap tags-per-entry,
  e.g. first 4 (design §7d). Decide alongside PASS 2 or after the
  observation window gives real density data.
- [x] 2026-05-30 **Review how to verify MORE memories — FEASIBILITY
  SCOPED (no code shipped; recommendation below).** Question: can we
  backfill `verified` across the ~29 K corpus to unblock Vector 2 Stage 2?
  **Answer: re-resolution backfill is local/free/~2 min and needs NO API
  gate — but it is nearly worthless for Stage 2, because the corpus carries
  almost no anchors to re-resolve.** `scripts/anchor_verify.py` resolves
  `file` (FS + `git cat-file`/`git log`) and `commit` (`git rev-parse`)
  anchors purely locally; `zotero` and `url` are stubbed → `pending`; no
  network/LLM in the path. **Verified at source 2026-05-30
  (`data/memories/memories.jsonl`, live/growing):** total **29,701**
  records; `verified` = true **629** / false **373** / pending **4** /
  absent **28,695**; records with non-empty `anchors` = **1,034 (3.5 %)**;
  legacy top-level `zotero_key` = 41. Anchoring is a *forward write-path*
  feature live only since 2026-05-16, so a full re-resolution pass would
  lift verified-true from ~629 to **~653 (2.2 % of corpus)** — `anchor_verify`
  returns `None` (not `true`) for the 96.5 % with no anchors, so net new is
  ~two dozen. **Design consequence (the real finding):** the promoted-recent
  fallback that Stage 2 was meant to *delete* is NOT a stopgap — it is the
  permanent handler for the 96.5 % that will never carry anchors. Reframe
  Stage 2 "verified-first" → "anchored-and-verified-first among records that
  *have* anchors, recent-promoted otherwise." Verified coverage grows
  forward (as the anchored write-path runs), not via backfill.
  - [ ] **Optional, ungated:** run the local re-resolution pass as a
    standing `scripts/drift-sweep.py` (design §8.2) — free, ~2 min,
    correctly stamps the 1,034 anchored records + re-checks them over time.
    Worth having as a quarterly job; needs no approval. Not urgent.
  - [ ] **API-gated, deferred:** the ONLY path to broad back-corpus
    coverage is a *retroactive anchor-generation* pass (design §4 step 5 /
    Phase 6) — re-reading transcripts with an extractor model to mint
    anchors records never had. ~thousands of calls; needs Shawn's API
    review gate (model + count + cost) as a separate costed decision. Do
    NOT fold into "backfill". Refs: `scripts/anchor_verify.py`,
    `scripts/project_id.py` (`repo_set`), `wiki/planning/memory-system-v2-design.md`
    §4, `wiki/planning/vector-2-design.md` §6b (Stage 2).
  - [x] 2026-05-30 **Design-doc reframe applied (commit `6bbb418`).**
    `wiki/planning/vector-2-design.md` §6b rewritten from "verified-first,
    delete the fallback" → "anchored-and-verified-first among anchored
    records, recent-promoted otherwise"; promoted-recent fallback now stated
    as permanent. Coherence edits also in §6a item 3, §9 step 5, §10 R2/R5,
    and a forward-pointer on the §1 sequencing premise. Counts re-verified
    at source this session (`data/memories/memories.jsonl`, 2026-05-30):
    **29,807** records, **1,076 (3.6 %)** anchored, **659** `verified=true`
    — the corpus grew ~106 records since the feasibility snapshot but the
    ~3.6 % structural finding holds. Open item (2) closed.
- [x] 2026-05-30 **Scratchpad distilled — clean baseline for Vector 2b
  (submodule `d840239`, superproject bump `f98bf2a`).** With the recall dump
  now digested to ~1.5 KB, the ~29 KB scratchpad became the dominant
  session-start payload term. First-ever distillation of `data/scratchpad.md`
  (header was `Last distilled: —`): **29,268 B → 15,484 B (47 % cut, zero
  principle loss)**. The `## Patterns` section had bloated to ~40 entries,
  ~half duplicates — removed 28 (project-specific ones already held verbatim
  in `data/scratchpads/{map-reader-llm,voice-assistant}.md` which load only
  on cwd match; exact dups of canonical Constraints/Preferences/What-Doesn't
  above). Moved "critical-friend on statistics" to Preferences; dropped two
  map-reader config-audit war-stories (per "record the principle, not the
  mistake"; principle held at the "audit new config against the original"
  Constraint) — Shawn approved as-is. Verified via diff: only 2 added lines
  (header + moved entry), so no kept principle altered. NB the hook's
  `SCRATCHPAD_WARN_LINES = 150` is LINE-based and never fired (99 lines) even
  at 29 KB — the bloat was bytes-in-long-lines; fix the warn to be byte-based
  as part of Vector 2b.
- [x] 2026-05-30 **Vector 2b — scratchpad load-path byte budget: DESIGN +
  IMPLEMENTATION shipped DARK (commits `db4da15` design, `da5790f` code,
  `422905f` doc-update).** Design doc `wiki/planning/vector-2b-design.md`
  (the "design FIRST" deliverable, like vector-2-design.md was). **Crux
  finding:** a curated principle log is NOT a recall dump (no `verified`,
  no decay, deliberately global, already distilled zero-loss), so Vector
  2's rank-and-drop selector is the wrong shape. Mechanism is narrower:
  (1) a byte-warn that actually fires — `SCRATCHPAD_WARN_LINES`
  (line-based, never fired at 29 KB / 99 lines) → `SCRATCHPAD_WARN_BYTES`;
  (2) a section-aware regrowth guard-rail — `digest.cap_markdown_to_budget`
  keeps whole `## ` sections under a hard UTF-8 cap, never splits a
  principle, visible trim marker. **Shared primitive per §7f**: lifted the
  byte-cap discipline out of `build_digest`'s `fits()` closure into a
  reusable markdown capper in `scripts/digest.py` (not re-invented).
  **Shawn chose Fork A (guard-rail)**: budgets sit ABOVE current sizes
  (global 18 KB > 15,484 B; per-project 8 KB > map-reader 5,134 B) → nothing
  trims today; the cap is regrowth insurance. **Flag-gated on its own
  sentinel** `~/.pa-scratchpad-budget` + env `PA_SCRATCHPAD_BUDGET`
  (mirrors `digest_mode_enabled()`), machine-local, NOT in synced `data/`.
  Default OFF → output byte-identical → the live Vector 2 §8 window
  (review 2026-06-13) is unconfounded. Warn recalibrated 12 KB → 17 KB
  after live smoke showed a sub-floor warn nags every session post-distill.
  Tests +28; **full suite 781 passed** (was 753), 0 regressions. Live
  smoke (PA-hub): flag OFF and flag ON both emit byte-identical 17,150 B
  (15,483 B scratchpad < 18 KB budget). **Sentinel NOT created — dark.**
  - [ ] **Enable Vector 2b on amd-tower AFTER the Vector 2 §8 review
    (2026-06-13)** — `touch ~/.pa-scratchpad-budget` (or accept the §8
    confound explicitly). At today's 15.5 KB nothing trims; the live win
    is the byte-warn firing on future regrowth. Revisit **Fork B**
    (active-cut, tighter budget with an explicit section-drop order) only
    if the scratchpad is still the bottleneck after Vector 2b's own
    observation window. Reference: `wiki/planning/vector-2b-design.md` §7.

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
- [x] 2026-05-18 **Implement `/handoff` as actual skill** — shipped
  (`commands/handoff.md`, available as the `/handoff` skill); verified
  present 2026-05-28.
- [x] 2026-05-28 **Pilot wiki migration on personal-assistant** — PA-project
  layer fully migrated under `wiki/`: continuity.md, working-notes.md,
  user-observations.md, index.md, planning/, docs/open-science/, reflections/.
  `/reflect` made layout-aware (prefers `wiki/reflections/`, falls back to the
  legacy `docs/notes/reflections/`). Old repo-root `planning/` + `docs/`
  removed. Cross-project `notes/` + `grimoire/` stay private in `data/` by
  design (shared via `published/`). Commits 21a7e60, 6481838, fd8ec38 + this
  session's reflections move. Remaining sub-task below.
  - [x] 2026-05-30 **Relocate misplaced `working-notes.md` files — DONE
    (done by a background agent earlier 2026-05-30; box flipped + independently
    re-verified at source 2026-05-30).** All 5 research repos (inscriptions,
    LLM-History-Paper, llm-reproducibility, map-reader-llm, paper-b) had
    `working-notes.md` relocated OUT of `docs/notes/reflections/` to the
    legacy-correct sibling `docs/notes/working-notes.md` (not `wiki/` — these
    repos aren't on the wiki layout yet; matches the survey's
    "or `docs/notes/working-notes.md` if not on the wiki layout"). Root cause
    fixed in cc-session-toolkit: template moved out of `data/reflections/` to
    `data/working-notes.md`, `init.py` updated, 301/301 tests. Commits landed
    + pushed in 6 repos (see session-log 2026-05-30). **Re-verification this
    session:** `find` confirms ZERO `*/reflections/working-notes.md` remain;
    `git ls-files` shows each of the 5 repos tracking `docs/notes/working-notes.md`
    with a clean working tree; toolkit template tracked at the new path, old
    path gone. Nothing left to do.
- [x] 2026-05-18 **Sketch `notes/index.md` + initial wiki-tag vocabulary**
  — `notes/index.md` + `notes/_tags.md` (24-tag vocabulary) landed;
  verified 2026-05-28.
  - [x] 2026-05-29 **Empirical cluster-the-corpus validation of the
    vocabulary (item #1)** — done. `scripts/analyse-wiki-vocabulary.py`
    (reproducible) + report at
    `wiki/planning/wiki-vocabulary-validation-2026-05-29.md`. Measured
    per-wiki-tag corpus support across 29,248 records + clustered the 33
    `notes/_inbox.md` candidates. Findings: two well-attested themes have
    no tag home — **agent-orchestration** (corpus cluster 913 usages /
    327 tags; ~10 inbox candidates) and **infrastructure/ops** (1023 /
    417; ~5 candidates); two genuine redundancies (`memory-systems` ≡
    `memory-system`; `three-Ps` ⊂ `provenance`). Recommended delta (ADD 2,
    MERGE 2; net 24 tags) is **pending `/weekly-review` ratification** —
    `_tags.md` reserves vocabulary edits for curation time, so this pass
    analysed and recommended only. `_tags.md` History carries the pointer.
    Grounds item #2 below.
- [x] 2026-05-29 **Extend `/weekly-review` with cluster-and-carry
  curation step (item #2)** — done. New **step 5 "Cluster-and-Carry Wiki
  Curation"** in `commands/weekly-review.md` (5a ratify pending vocab
  delta → 5b gather from `notes/_inbox.md` + week's memories +
  `wiki/working-notes.md`, reusing `scripts/analyse-wiki-vocabulary.py
  --window-days 7` → 5c cluster by vocabulary with a ripeness rule →
  5d draft page diffs → 5e review/accept and carry, removing carried rows
  from the notes inbox). Draft-only and human-ratified throughout. Steps
  6/7/8 renumbered; scorecard gains a "Wiki pages curated" row; the
  step-8 "learnings" follow-up now cross-refs step 5. 5a closes the
  chicken-and-egg with item #1: the first run ratifies the
  2026-05-29 vocabulary-validation delta before clustering. **Not yet
  exercised on a real week** — first live run is its own validation.
- [x] 2026-05-29 **Lift tag vocabulary to `wiki/index.md` + privacy
  decision (item #4)** — done, per Shawn's call. The tag vocabulary
  (innocuous) lifted from the private `notes/_tags.md` to the public
  `wiki/index.md` "Tag vocabulary" section, now its **canonical home**
  (full glosses + usage notes + History). `notes/_tags.md` reduced to a
  redirect stub (`status: archive`); `notes/index.md` pointer and
  `/weekly-review` step 5a both re-pointed at `wiki/index.md`. `_inbox.md`
  and all `notes/`/`grimoire/` *content* stay private by design. The
  pending vocabulary delta (item #1) now ratifies into `wiki/index.md`.
- [x] 2026-05-29 **Add grimoire→`published/` review to `/retro`** — done,
  per Shawn's call that the publishing-review ritual belongs in `/retro`
  (monthly), not `/weekly-review`. New **step 5c "Grimoire Publishing
  Review"** in `commands/retro.md`, sibling to 5b scratchpad distillation:
  surface matured private grimoire prompts not yet published, assess against
  the `published/README.md` bar, present per-entry publish/defer/decline,
  and on approval create the Pattern-B polished public copy in
  `published/prompts/` (original stays private). Draft-only, human-ratified.
  First run has a real backlog: 17 grimoire entries, 0 published.
- [x] 2026-05-18 **Close 3 provenance audit gaps** — all three closed
  (`source_message_uuid`, `code_state.*`, `licence` + `extractor_model_id`);
  see the "Provenance audit gaps … all three closed 2026-05-18" block lower
  in this doc. Verified 2026-05-28.

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
- [x] 2026-05-24 **F3: Backfill 33 historic sessions** — **DONE**.
  Ran on 2026-05-24 after Shawn's explicit approval (post-v3 wire-up,
  same session). Dry-run estimate ~$5.61 mean / ~$9.53 p90 against
  the 33 sessions whose `auto_generated.purpose ==
  "Auto-metadata unavailable"`. Backfill produced v1.3 schema records
  (parent Three Ps + phases/decisions/key_exchanges plus
  subagent_summaries for sessions with subagents) — **33/33 succeeded,
  0 failures**. Density discipline observed empirically: most
  sessions emit 3-5 phases, 2-4 decisions, 2-5 key_exchanges; 5
  short single-thread sessions correctly emit 0 phases. Notable
  recovery: the b089991e map-reader 1.83M-token session that
  previously hit Gemini's 1M ceiling under the chars/4 heuristic
  archived cleanly with 24/25 subagent summaries. The 33 figure
  reflects sessions found across the full `~/cc-archives/` tree at
  backfill time (was 32 in the 2026-05-20 inventory; one additional
  session surfaced since).
- [ ] **F4: QA pass on ~20 sampled backfill outputs** — partial
  coverage 2026-05-24: 2 production-path validation sessions + 3
  mini bake-off sessions + 1 initial bake-off session (b93ed93b
  RAC-TRAC) inspected and found good. Remaining: Shawn's own
  ad-hoc inspection of the 33 newly-backfilled sessions against
  the bake-off rubrics (`review-rubric-populated-final.md`).
- [x] **F5 (2026-05-25): 1-in-25 subagent summary failure on b089991e —
  RESOLVED.** Diagnosis: log line `auto-metadata.log:835` (12:37:43
  on 2026-05-24) showed subagent `ab92875bababd2549` failed with
  "Expecting ',' delimiter: line 3 col 1 char 1144" — Gemini's
  stochastic JSON-format glitch even under `response_mime_type=
  application/json` (which instructs JSON mode but does NOT enforce
  a schema). Confirmed reproducible-as-stochastic: re-ran the v3
  subagent prompt on the same transcript (~$0.05), got a clean
  1,199-char narrative. Fix landed: (a) `_call_gemini_once` /
  `_call_gemini_with_retry` gain optional `response_schema=`
  parameter; subagent path passes the new
  `SUBAGENT_NARRATIVE_SCHEMA` constant so Gemini's structured-output
  mode validates JSON before emitting — closes the failure class at
  source for the subagent path. (b) Parse-failure log lines bumped
  from `raw[:200]`/`raw[:300]` to `raw[:8192]` with `raw_len=`
  prefix on both parent and subagent paths, so future parse
  failures are fully diagnosable post-hoc. 4 new tests; 268 total
  passing. Parent-path `response_schema` deferred as separate
  decision (v3 parent's optional arrays need a richer schema spec).
  Smoke-tested end-to-end: schema-enforced output is compact (no
  pretty-print whitespace) and parses cleanly.
- [x] 2026-05-22 **Migrate extractor from Gemini 3 Flash Preview to
  Gemini 3.5 Flash** — 3× price accepted for zero JSON defects + better
  named-entity preservation (toolkit commit `cdc7c65`).
- [x] 2026-05-23 **Close char/4 heuristic calibration gap** — toolkit
  commit `917ac13`. `cc_session_toolkit.transcript_text` gains
  `extract_transcript_text_for_gemini` (two-pass: heuristic first cut,
  then real-tokeniser verify; re-truncate at observed chars/token × 0.92
  margin if first pass over-budget). `archive.generate_auto_metadata`
  wires `client.models.count_tokens` as the calibration callback (free
  per Google's docs). Smoke-tested on b089991e: 1.17M Gemini tokens
  (over 1M ceiling) → 730K (under 850K budget); 318K headroom under
  ceiling. 8 new tests; 257 total passing. PA venv reinstalled via
  `pip install -e ~/Code/cc-session-toolkit`. Closes the
  1-in-111-output (0.9 %) graceful-degrade failure mode surfaced by
  the 2026-05-23 F3 quality-assessment agent.
- [ ] **Re-verify Gemini model ID at GA** — `gemini-3.5-flash` is the
  current shipping ID and behaves as GA on the API (no -preview suffix
  required; ID accepted by both `generate_content` and `count_tokens`).
  Watch is now for any future rename of the 3.5 family.

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

### G. Style-guide construction (multi-genre, academic kick-off) — *v2 Phases 1–5 all done 2026-05-30 (Phase 1 legacy+clean+Stream A; Phase 2 Biber; Phase 3 Kumar+bimodality+verifier; Phase 4 Panickssery; Phase 5 Mahalanobis evaluator + 8-metric gate); v2.3 agent ready. **Workstream G core complete.** Remaining: multi-genre runs (Substack/business/teaching — agent re-invocations, not phase dev) + one deferred future refinement (8-metric gate tolerance review, see table)*

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
| Desk evaluation of `Hiro-Inagawa/write-like-me` | done 2026-05-22 — `notes/prior-art-runs/write-like-me-evaluation-2026-05-22.md` |
| End-to-end comparator pass (write-like-me vs run-1 on same 18-paper corpus) | done 2026-05-22 — `notes/style-guides/academic/write-like-me-comparator-2026-05-22/comparison-report.md` |
| Fork-vs-build decision on `Hiro-Inagawa/write-like-me` | **DECIDED 2026-05-22: compose with minimised scope** (re-implement the additive measurements under run-1 evidence discipline; do not vendor `stylometry.py`; do not adopt universal baseline em-dash zero-tolerance) |
| Prior-art rescan (under-searched corners — HF Spaces, GitLab, gh api) | done 2026-05-22 — `notes/prior-art-runs/llm-style-alignment-rescan-2026-05-22.md` |
| `ngpepin/stylometric-transfer` (most-complete tool found across both passes, PolyForm Noncommercial 1.0.0) | **DECIDED 2026-05-22: inspiration only** (read for fingerprint schema + deviation-report shape; lift no code; licence becomes a problem the moment commercial use surfaces) |
| v2 agent implementation plan | **DECIDED 2026-05-22** — `planning/style-guide-agent-v2-implementation-plan.md`; all 10 design questions resolved with recommended defaults; total envelope 12–18 h focused work + ~$0.50 API spend per generation run (Phase 4 only) |
| Step-Back Profiling Gist preamble (Tang et al. 2024) | deferred 2026-05-22 — memory captured (`decision` category), inbox follow-up added; revisit when downstream LLM consumer needs a compact context-card |
| Phase 1 v2.0 — measurement-layer extensions on legacy `pdftotext -layout` corpus | **done 2026-05-23** — `notes/style-guides/academic/v2-phase1-audit-2026-05-23.md` (six new metrics per-paper-and-aggregate, three previously-TBD gate targets filled in, regression-anchor framework, `attested-concentrated` fifth status added to schema); commits `834a5c3` (core pipeline `phase1_pipeline.py`) |
| Phase 1 v2.1 — clean-corpus rebuild (PyMuPDF + pdfplumber via `~/Code/llm-reproducibility/extraction-system/scripts/pdf_processing/`) | **done 2026-05-24** — `notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md`; commits `834a5c3` (`extract_corpus.py` wrapper); corpus archive at `data/style-corpus/extracted/<key>/{body.md,references.md,full.md,metadata.json,qa.json}` (18 papers); 16/18 PASS all QA-agent checks (2 cosmetic abstract-not-promoted flags); `data/style-corpus/phase1-results-clean.json` is the new ground-truth measurement file |
| Run-1 anchors retired as regression target | **done 2026-05-24** — empirically verified contaminated by author affiliations, journal mastheads, page headers, and reference fragments that survived legacy extraction. Clean-corpus values (mean SL 21.45, em-dash 0.572/1k, semicolon 6.538/1k, announcement colons 1.605/1k, hedge 0.721/100w, concession 0.1327) are the new baseline. See clean audit §4 for the three-way trajectory (run-1 → v1-dirty → v2-clean) |
| Stream A code hygiene (post-`/audit` fixes) | **done 2026-05-24** — 5 critical + 10 medium audit findings fixed: `strip_references` zip bug (recovers 148 legacy-mode body words for CI2Q7VXD), Unicode-aware tokeniser (`Sobotková`, `Çatalhöyük`, `Müller` now single tokens), `--keys` whitespace parsing, `_REF_BRACKETED_RE` window 400→1500 chars, manifest-key access guards both files, announcement-colon paragraph-crossing constraint, hedge-phrase boundary safety, multi-token concession phrases, spaCy `disable_pipes`→`select_pipes` deprecation, `_END_OF_BODY_MARKERS_RE` heading-prefix requirement, `_REF_PARAGRAPH_RE` `[A-Z][A-Z]→[A-Z][A-Z][a-z]` tightening, chapter-slice end-not-found fail-open; included in commit `834a5c3` |
| v2.1 agent file patch | **done 2026-05-24** — `~/.claude/agents/corpus-style-analyser-v2.md` (outside repo, user-global): Appendix E gate values refreshed to post-Stream-A clean-corpus targets; Phase 2 instructions point at clean-corpus pipeline; pinned-deps section adds `pymupdf 1.27.2.3`, `pdfplumber 0.11.9`, `python-slugify 8.0.4`, `pyyaml 6.0.3`; cross-version-diff section documents v1 → v2.0 → v2.1 trajectory |
| Phase 2 — Biber MDA section relayout (Stream B) | **done 2026-05-24** — agent file v2.1 → v2.2 (`~/.claude/agents/corpus-style-analyser-v2.md`, outside repo); audit doc `notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md` §11 documents the edits. Output §§1–6 follow Biber 1988 D1–D6; §§7–10 hybrid (register conventions, lexical/orthographic, voice-tic cross-reference, editor anti-patterns); §11 aspirational. Phase 3 dimensions-list reorganised to match. D2 narrative gets `absent-when-searched` with explicit search-list (past-tense, third-person past, communication verbs, perfect aspect) if signal is corpus-absent as predicted. §6 D6 em-dash density now MANDATORY year-binned (pre-2023 vs 2023–present) per audit §8.1. Appendix C must carry a v1/v2.0 → v2.2 redirect table when `compare_against` resolves to a pre-Biber prior guide. v2.0's `§8 Structural metrics` container dissolved — MATTR/hapax → D1, passive/nominalisation → D5, sentence-length/dep-depth/semicolons/em-dashes/paragraph-stats → D6, POS bigrams → Appendix C only. No code changes; agent file only. Validation deferred to first v2.2 generation run |
| Phase 3 — Kumar aggregation rule formalisation + bimodality + guide verifier | **done 2026-05-30** — `scripts/style-analyser/phase3_promotion.py` (deterministic CV>1.5 OR bimodality-gap>=0.25 → attested-concentrated; emits verbatim `papers_present` + `papers_absent` for the confabulation guard); `scripts/style-analyser/phase3_guide_verifier.py` (deterministic regression gate over every numeric claim in the guide). Bimodality detector uses inner-gap rule (≥3 papers each side) and caught a NEW finding at §5.3 mean_dep_depth (5-vs-13 cluster split at gap 0.269) that the CV-only algorithm missed. Verifier caught a §6.3 confabulation in the v2.2 guide ("8/18 papers, plus two more" when 6/18 was truth); end-to-end test = v2.3 in-session regeneration → 35 PASS / 0 FAIL (vs v2.2: 29 PASS / 5 FAIL / 3 WARN). Output: `notes/style-guides/academic/style-guide-academic-2026-05-30-2.md`. Commits parent `c4b47d5` (scripts), `78f425a` (agent v2.3 confabulation guard + Phase 3 status), `a719128` (submodule bump); submodule `ff0322a` (artefacts + v2.3 guide) |
| Phase 4 — Panickssery exemplar block | **done 2026-05-30** — `scripts/style-analyser/phase4_exemplar_scorer.py` (18-category sentence-level feature scorer, year-binned em-dash rule applied); 5 exemplars chosen (NQGD7QXT 2022 first, UI6SLPNY 2022 first, 9B2FJ6SL 2024 last, 5INAFTVT 2019 last, DE7YYNED 2018 middle) covering role balance (≥2 first + ≥2 last + ≥1 middle) and date spread 2018–2024; total 191 / 600 words. Inversions in-session by Opus 4.7 per plan §5.3 — no SDK calls. Appendix F appended to `style-guide-academic-2026-05-30.md`. Commits parent `169e944` (scorer + agent flip), `2a3a678` (submodule bump); submodule `d3eb1f4` |
| Phase 5 — Mahalanobis evaluator | **done 2026-05-30** — `scripts/style-analyser/phase5_evaluator.py` (the downstream generation-time gate, separate from guide generation per plan §6.5). `--text`/`--passage` → markdown/JSON verdict with (a) Mahalanobis distance to the corpus centroid in a 12-feature, length-normalised, Ledoit-Wolf-shrunk space (the 3 phase3-bimodal metrics — em_dash_per_1k, mean_dep_depth, pace_count — excluded from the centroid per plan §6.3 option (a), reported in an advisory block with cluster split; exclusion set read live from phase3), empirical leave-one-paper-out envelope + χ² cross-check; and (b) pass/fail vs the 8-metric Appendix E gate. Input measured by importing `process_paper` from `phase1_pipeline.py` (identical features, no drift). Self-contained CPU; adds `scikit-learn`+`scipy` to the venv. `--validate` → `data/style-corpus/phase5-validation-report.md` (off-register fixtures 14.2/21.7 vs corpus LOO max 4.67; held-out real paper 3.15 within range). Commits parent `80b2694` (script + agent v2.3 footer flip to all ✅), `fc1eb32` (submodule bump); submodule `fe78db1` (validation report) |
| Phase 5 future refinement — 8-metric gate tolerance review | **done 2026-05-30** — the `--validate` gate-calibration block found **0/18 corpus papers pass all 8 checks (median 4/8)**: the inherited Appendix E tolerances on **em-dash (1/18 pass), semicolon (3/18), announcement-colon (3/18) and hedge (5/18)** are tighter than the corpus's own between-paper variance, so a real corpus paper routinely fails them. The em-dash two-sided band (0.572 ±0.20) is especially ill-fitting for a bimodal metric where 12/18 papers sit at exactly 0. **Reframe (Shawn, 2026-05-30): this is aspirational by construction, not a defect to fix.** Conjoining 8 tight bands around the corpus central tendency defines a consistency no single paper achieves — text passing all 8 would be *more uniformly on-voice* than any actual paper. The gate is thus the quantitative aspirational layer, alongside the prose aspirational guides at `~/Code/prompts/System-setup/` and the empirical guide's §11. So the "review" is **mostly about labelling the gate aspirational, NOT loosening tolerances.** The one genuine wrinkle: the em-dash band is the mean of a bimodal split (12/18 at 0, six at 0.50–2.06/1k), so it rejects both halves of the corpus AND rejects zero-em-dash text that §6.3 calls correct for 2026+ prose — that check points the wrong way, but `--modern-em-dash` (≤0.20 ceiling) already sidesteps it. Optional follow-ups if ever revisited: make `--modern-em-dash` the new-prose default; note the gate's aspirational status in Appendix E. The report already frames a FAIL as a *deviation flag*, not proof of off-voice text. Reference: `data/style-corpus/phase5-validation-report.md` gate-calibration section; working-notes 2026-05-30 aspirational-gate entry; plan §2.4 / guide Appendix E. **Cleared 2026-05-30:** both optional follow-ups done — (1) flipped `phase5_evaluator.py` so the modern ≤0.20/1k em-dash ceiling is the DEFAULT gate behaviour (new inverse flag `--corpus-em-dash` reaches the legacy two-sided 0.572 ±0.20 band; argparse + docstring updated); (2) added a "Status: aspirational by construction" subsection to the guide's Appendix E (`style-guide-academic-2026-05-30-2.md`) and to the agent file's Appendix E + Phase 5 status (`agents/corpus-style-analyser-v2.md`). NO tolerance values changed. Validation re-run: em-dash check loosened 1/18→12/18, median 4/8→5/8, papers-passing-all-8 still 0/18, sanity verdict PASS. Commits below |
| Reconciliation of aspirational section vs prior conscious style guides | **done 2026-05-30** — reconciled in-session (Workstream G). Per Shawn's direction a **clean start**: the prior guides (`~/Code/prompts/System-setup/`, `e17a2f5`) were read to drive the reconciliation but are treated as superseded and are NOT cited in the guide; confirmed §11 items instead carry `Live cross-ref` pointers into the empirical §§1–10. Added §§11.9–11.13 (standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation, voice calibration). The apparent paragraph-length conflict (prior target 100–180 words vs §6.5 median 17) is a **§6.5 segmentation artefact** (headings, front-matter and line fragments counted as paragraphs; median falls below mean sentence length) — recorded as a reconciliation note, no item; a background agent has diagnosed it (non-prose blocks are 41% of "paragraphs" but only 4.4% of words; corrected median ≈27, mean ≈42; the "two-register cluster" is contamination-driven, r = −0.78) and proposed a suggest-only `phase1_pipeline.py` fix, pending decision. Guide §11 + agent template both updated. Submodule `16be506`; parent commits below |
| Substack / business / teaching genre runs | **deferred indefinitely (2026-05-30, Shawn)** — start only on an immediate need with an assembled Zotero corpus; each run needs a corpus + Phase 4 API approval. The v2.3 agent is ready to drive them |

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
| `lit-scout` + `lit-scout-verifier` | single-round shipped 2026-04-19; closed-loop wired 2026-05-22 — both sides emit machine-readable blocks via HTML-comment markers (sub-agent Write of report files is blocked, so the driver extracts inline); `/lit-scout-iterate` driver added; **smoke-tested on Bayesian-archaeology query 2026-05-22 — PASS in 2 iterations**; **Zotero staging-import wired 2026-05-22** (driver now auto-imports the corrected Findings table into a dated subcollection under `My Library → staging` after termination, closing the BibTeX-correction-propagation gap) | **yes** — closed; smoke-tested; Zotero-integrated |
| `data-profile-proposer` + `data-profile-verifier` | renamed + closed-loop wired 2026-05-22 (was `data-profile-scout`); `corrections.jsonl` emission added; iterate-mode on proposer; `/data-profile-iterate` driver; **smoke-tested on LIRE v3.0 2026-05-22** — PARTIAL verdict on iter-0 (81/83 PASS, 2 PARTIAL, 0 FAIL), loop terminated per policy without entering iterate mode; `documentation_defect` status added to the contract from the smoke-test calibration (commit `2e89bd1`) | **yes** — closed; plumbing confirmed; iterate-mode behaviour still unexercised |
| `prior-art-scout` + `prior-art-scout-verifier` | pair built + smoke-tested on style-guide query 2026-05-22; closed-loop wired same day after lit-scout smoke-test confirmed the pattern — proposer emits claims block (per source-type catalogue); verifier emits corrections block with `severity` × `failure_type` two-axis classification and `documentation_defect` status; `/prior-art-scout-iterate` driver added; **smoke-tested on RDA-aligned provenance toolkits 2026-05-23** — PASS in 1 iteration (63 PASS / 1 UNVERIFIABLE / 0 FAIL); workspace archived at `data/experiments/prior-art-scout-iterate-smoke-2026-05-23/` | **yes** — closed; smoke-tested; row-removal path still unexercised |

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
- [~] 2026-05-24 **Synthetic-FAIL test to exercise iterate mode —
  DEFERRED indefinitely per the 2026-05-24 conversation.** Two
  consecutive iterate-loop runs have now terminated PASS in 1
  iteration without exercising the row-removal path
  (2026-05-22 lit-scout on Bayesian archaeology, FAIL=0 after
  iter-1 converged; 2026-05-23 prior-art-scout on RDA-aligned
  provenance toolkits, FAIL=0 throughout). Rather than
  manufacturing synthetic FAILs to validate iterate-mode plumbing
  — which would optimise for imagined errors rather than learning
  from real ones — use the iterate loops self-consciously in real
  work and let calibration data accumulate from genuine failures.
  After ~6 months of real usage, revisit the verifier evals:
  if no real errors have surfaced, consider a QA → QI shift
  (improvement signals over confabulation catches); if real
  errors have surfaced, calibrate against them; if the rubrics
  are right and these queries simply didn't trigger failure,
  accept that too. Scratchpad entry 2026-05-24 captures the bias
  to resist. **Trigger for un-deferring:** accumulated real-run
  trajectory data sufficient to make rubric revision empirical
  rather than speculative (~6 mo + a handful of genuine FAILs
  across the three pairs).
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
- [x] 2026-05-22 **Smoke-test `/lit-scout-iterate` on a real
  query — PASS in 2 iterations.** Ran on "Bayesian methods for
  archaeological dating and chronological modelling"; workspace at
  `/tmp/lit-scout-iterate-20260522-190212/`. 35 rows × 5 categories
  = 175 claims; iter-0 returned FAIL with 1 claim (row 16 authors,
  CrossRef family/given swap, `severity: high`), iter-1 converged
  PASS. FAIL set shrank monotonically. Only `authors` field
  required correction (1/175 = 0.57 %); `doi_resolves` removal
  path NOT exercised (0 unresolvable DOIs in this domain — clean
  corpus). Surfaced two follow-up items: typed `failure_type`
  axis (now in the spec) and BibTeX correction-propagation gap
  (deferred).
- [~] 2026-05-24 **Calibrate the severity rubric across all
  three pairs — DEFERRED, tied to real-error accumulation.**
  Current bands are rule-of-thumb (data-profile: high ≥10 % drift
  / decision-changing; medium ≥5× tolerance; low at the boundary.
  lit-scout: high = wrong first author / DOI fabricated / wrong
  paper at DOI; medium = >25 % citation drift / material title
  difference; low = borderline drift). Three smoke tests so far
  have exercised only `severity: low` (data-profile LIRE via
  `documentation_defect`) and `severity: high` once (lit-scout
  row 16 CrossRef family/given swap, `failure_type:
  encoding_artefact`). Medium and the high band on data-profile
  and prior-art are still entirely on paper. Tied to the deferred
  synthetic-FAIL item above — same calibration arc, same
  six-month re-evaluation gate.
- [ ] **Decide whether to quantify "how partial" precisely.** Both
  pairs currently use rule-of-thumb PARTIAL bands. A finer metric
  (continuous "how-partial" score) could let the driver
  auto-iterate on PARTIAL above a threshold. Defer until ≥3 real
  runs surface a pattern.
- [x] 2026-05-22 **Lift to `prior-art-scout`** (the last
  remaining unconverted pair). Proposer gains Iterate mode +
  per-source-type Machine-readable claims block (catalogue covers
  GitHub / GitLab / PyPI / npm / HF / paper / generic URL).
  Verifier gains Tolerance bands, severity + `failure_type`
  rubric (incorporating the lit-scout smoke-test calibration
  finding from the same day), `documentation_defect` status
  (mirroring data-profile), and the Machine-readable corrections
  block. `/prior-art-scout-iterate` driver mirrors
  `/lit-scout-iterate`. Smoke-test pending.
- [x] 2026-05-23 **Smoke-test `/prior-art-scout-iterate` —
  PASS in 1 iteration.** Ran on "Open-source LLM provenance
  toolkits (RDA-aligned)"; workspace originally at
  `/tmp/prior-art-scout-iterate-20260523-222940/`, archived at
  `data/experiments/prior-art-scout-iterate-smoke-2026-05-23/`.
  12 candidates × 5–6 claims/row = 64 claims; iter-0 returned
  63 PASS / 1 UNVERIFIABLE (row 5 SSRN URL behind Cloudflare
  anti-bot; paper itself confirmed via OpenAlex DOI lookup) /
  0 FAIL / 0 PARTIAL / 0 documentation_defect. Loop terminated
  per driver case G.1. Closed-loop plumbing confirmed end-to-end;
  `failure_type` field wire-correct on all 64 verifier rows
  (null on PASS, as designed). **`url_resolves` / `doi_resolves`
  row-removal path NOT exercised** (no FAILs — the
  RDA-provenance domain produced clean discovery; the proposer
  queried live APIs at scout-time rather than guessing from
  memory). Two substantive RDA-adoption findings surfaced as
  inbox follow-ups 2026-05-24: Flowcept + PROV-AGENT (ORNL,
  MIT, IEEE e-Science 2025) and the rocrate Python library
  (Apache-2.0). Calibration decision: see deferred synthetic-FAIL
  item above. (Original suggested query was "a domain prone to
  invented repos / DOIs"; we chose RDA-provenance instead so the
  run would produce reusable substantive findings alongside the
  smoke-test value — that trade-off cost us row-removal-path
  exercise but bought us two real adoption candidates.)

  *(Note on the original "speculative-domain" smoke-test
  suggestion — that we should pick a query "prone to invented
  repos / DOIs" so the row-removal path was exercised: superseded
  by the 2026-05-24 calibration deferral. If a domain prone to
  confabulation is wanted for future exercise of the
  `url_resolves` / `doi_resolves` row-removal path, surface it
  organically through real research questions rather than
  manufactured ones.)
- [x] 2026-05-24 **Backport `failure_type` axis to
  `lit-scout-verifier` and `data-profile-verifier`.** Spec edits
  landed in both files: severity paragraph promoted to dual-axis
  "Severity + failure_type" rubric; JSONL schema gains
  `failure_type` row / field; example claims updated to show the
  canonical 2026-05-22 calibration cases (CrossRef family/given
  swap → `encoding_artefact` in lit-scout; DOI 404 →
  `confabulation` in lit-scout; pandas default-kwarg mismatch →
  `encoding_artefact` with `documentation_defect` status in
  data-profile); emission rule added warning against defaulting
  to `confabulation` for source-encoding issues. Drivers and
  proposers gracefully ignore the new field (verified by grep on
  both `/lit-scout-iterate` and `/data-profile-iterate`
  driver specs + both proposer agents). Wire-correctness
  confirmed on the `/prior-art-scout-iterate` smoke
  (2026-05-23): all 64 verifier rows carried the field with null
  on PASS.
- [x] 2026-05-22 **BibTeX correction-propagation gap closed by
  Zotero staging-import path** (lit-scout-specific). The
  iterate-mode correction now reaches the user's Zotero library
  directly via `scripts/lit-scout-zotero-import.py` (author field
  populated from the corrected `claims.jsonl`, journal-article
  fields from a fresh CrossRef fetch). The standalone `.bib`
  file is now a backup deliverable rather than the primary
  destination, and remains uncorrected on iterate-mode rows
  pending the deferred `lit-search.py bibtex --corrections`
  flag. Real-world validation: row 16 Lanos/Philippe arrived in
  Zotero with `lastName='Lanos'` (correct) where the .bib
  version still has `author={Philippe, Lanos and Anne, Philippe}`
  (wrong) — concrete demonstration of the gap and its closure.
- [x] 2026-05-22 **Zotero staging-import for `/lit-scout-iterate`
  shipped.** New script `scripts/lit-scout-zotero-import.py`
  (~430 lines, dry-run default, `--limit N` for smoke-testing,
  manifest-based idempotency). Driver spec
  `commands/lit-scout-iterate.md` now invokes it on every
  terminal verdict except LEGACY_PROPOSER; imports go to a
  dated subcollection `YYYY-MM-DD-<query-slug>` under
  `My Library → staging` (key `IX8XR97K`). Dedups against all
  16 local Zotero libraries by DOI via sqlite. Tags every
  imported item with `lit-scout-staging`, `lit-scout-run:TS`,
  `lit-scout-fit:<level>`, `lit-scout-cluster:<slug>`, plus
  `lit-scout-unverified:<field>` for any FAIL / PARTIAL /
  UNVERIFIABLE claim. Validated end-to-end on the smoke-test
  workspace: 30 items created in subcollection `3C7UZ5AC`, 5
  group-library duplicates correctly skipped, manifest at
  `/tmp/lit-scout-iterate-20260522-190212/zotero-import-manifest.json`.
  Required env vars (`ZOTERO_LIBRARY_ID`,
  `ZOTERO_API_KEY_PERSONAL`, `ZOTERO_STAGING_COLLECTION`) live
  in `~/personal-assistant/.env`. Operational note: pyzotero
  embeds the API key as a URL path segment in `GET /keys/<key>`
  and dumps it into traceback strings on 403 — exception output
  is not safe to forward into shared logs.
- [x] 2026-05-23 **Fix manifest `items_skipped` dedup on re-runs.** Cosmetic
  bug in `scripts/lit-scout-zotero-import.py` (~line 460):
  on re-invocation, the merge logic appends the new run's
  skipped-DOI list to the prior run's without deduping by DOI,
  so a workspace re-imported twice ends up with each
  group-library duplicate counted twice in
  `items_skipped`. Zotero state remains correct (the actual
  Zotero items aren't re-created); only the manifest count
  inflates. Fix: dedupe by `doi` (case-insensitive) when
  merging `prior_skipped + plan_skip`. Same pattern applies
  to `prior_failed + failed_live`.
- [x] 2026-05-23 **Promote proposer Zotero dedup to DOI-based.** The
  lit-scout proposer's `[IN ZOTERO]` flag in the Findings table
  is title/creator-based (via `scripts/zotero.py:search_items`).
  Smoke test 2026-05-22 surfaced the gap: proposer flagged 2 of
  5 actual duplicates; the staging-import script's DOI-based
  sqlite query caught all 5. Fix: add a `find_by_doi(doi)`
  function to `scripts/zotero.py` and have the proposer call it
  first, falling back to text search only when DOI is absent.
  Reduces wasted CrossRef fetches and clarifies the table for
  the user before staging-import even runs.
- [x] 2026-05-23 **Update `global-claude-md/zotero-reference.md`** to
  document the new env vars introduced 2026-05-22:
  `ZOTERO_API_KEY_PERSONAL` (personal write + all-groups read)
  and `ZOTERO_STAGING_COLLECTION` (the top-level staging
  collection key under My Library). Convention: when a workflow
  needs writes to a specific library, use a target-suffixed
  variable name like `ZOTERO_API_KEY_<TARGET>` rather than
  the bare `ZOTERO_API_KEY` (which `sync-to-zotero.py` still
  reads and which is now a separate Paper-B-scoped key under
  `ZOTERO_API_KEY_PAPER_B`). Also document the bash-hyphen
  trap (`ZOTERO_API_KEY_PAPER-B=...` parses as a command and
  leaks the value in the error message — happened once
  2026-05-22; key was revoked and reissued).

**Reference docs for the closed-loop pairs:**

- `/data-profile-iterate` driver: `~/personal-assistant/commands/data-profile-iterate.md`
- data-profile proposer: `~/personal-assistant/agents/data-profile-proposer.md`
- data-profile verifier: `~/personal-assistant/agents/data-profile-verifier.md`
- `/lit-scout-iterate` driver: `~/personal-assistant/commands/lit-scout-iterate.md`
- lit-scout proposer: `~/personal-assistant/agents/lit-scout.md`
- lit-scout verifier: `~/personal-assistant/agents/lit-scout-verifier.md`
- lit-scout Zotero staging-import: `~/personal-assistant/scripts/lit-scout-zotero-import.py`
  (run after `/lit-scout-iterate` terminates; auto-invoked by the driver
  on any terminal verdict except `LEGACY_PROPOSER`)
- `/prior-art-scout-iterate` driver: `~/personal-assistant/commands/prior-art-scout-iterate.md`
- prior-art-scout proposer: `~/personal-assistant/agents/prior-art-scout.md`
- prior-art-scout verifier: `~/personal-assistant/agents/prior-art-scout-verifier.md`
- Architecture rationale + 2×2 orchestration grid: craft notebook
  entries 2026-04-18 ("Agent definitions are specifications…",
  "Orchestration patterns are a 2×2…", "Subagents are context
  management…")
- Inline-block transport rationale (lit-scout + prior-art-scout):
  sub-agent Write of `.md` files is blocked per 2026-04-19 v4.x
  evaluation; closed-loop transport uses fenced `jsonl` blocks
  with HTML-comment markers extracted by the driver. Data-profile
  uses direct file Write since its agents have unrestricted Write
  to the configured `output_dir`.
- Severity × failure_type rubric (2026-05-22 calibration finding):
  every FAIL claim carries both `severity` (high/medium/low —
  drives prioritisation) and `failure_type` (confabulation /
  encoding_artefact / metadata_drift / stale_count — drives
  calibration of how much to trust the proposer). Originated in
  the lit-scout smoke test; landed in `prior-art-scout-verifier`
  same day; backport to lit-scout + data-profile pending.

---

## Things to verify on next session (priority queue)

Read these *before* starting new work. Most should take <5 min each.

- [x] 2026-05-30 **Vector 2 PASS 2 shipped + enabled on amd-tower — DONE
  (commit `68427cd`).** Pre-flight proof re-run this session held (PA hub
  17,068 B → 1,489 B / 91.3 %; inscriptions 17,493 B → 1,485 B / 91.5 %;
  both ≤ budget, fallback off; corpus now 29,491 memories / 305 verified-in-7d).
  The live cutover is wired behind a machine-local flag and ENABLED on
  amd-tower (sentinel `~/.pa-digest-stage1`). See workstream B for the full
  PASS-2 record + the §8 observation-window review sub-task (due ~2026-06-13).
  **Next-session verify:** glance at `data/logs/digest.log` — every
  session-start on amd-tower now appends a `bytes=… shown=… fallback=…` line;
  confirm bytes stay ≤1,500 (if one ever reports `budget` exceeded that is
  finding (3) density-tuning biting) and that the cadence looks like one line
  per real session-start. zbook + rpi-server still emit the legacy dump
  (sentinel absent there) — expected.
- [x] 2026-05-30 **Review + push the workstream-D #3 repos — DONE.** All 6
  relocation/fix commits are now on `origin/main`: pushed at session close
  on 2026-05-30 (re-verified each was 1-ahead/0-behind with the relocation
  commit as HEAD before pushing) — inscriptions `89cad01`, LLM-History-Paper
  `73f9876`, llm-reproducibility `dc40d8e`, 2026-mq-…-paper-b `99cab2b`,
  cc-session-toolkit `9129e8a` (`init.py` scaffold fix, 301/301 tests pass);
  map-reader-llm `3a17575` had already gone up earlier on a concurrent gs/h11
  push. The moves are history-preserving `git mv`s. Nothing outstanding.
- [ ] 2026-05-17 **First-firing of v2 extraction hook.** Phase 1–3 landed
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

### Post-Phase-0 + Step-2 cleanup register (added 2026-05-22)

Now that the canonical store at `~/mnt/rpi-shares/cc-archives-consolidated/`
(3.4 GB / 702 sessions + 183 manual exports) is fully populated AND mirrored
locally to `~/cc-archives/` on amd-tower + zbook, several pre-consolidation
copies are redundant and can be cleaned up with appropriate safety checks.
Five categories:

- [x] 2026-05-22 **A — worktree dir + /tmp test artifacts** (~6.4 GB
  freed on amd-tower). Removed
  `~/Code/map-reader-llm/.claude/worktrees/agent-a59a9dae0bff3f27b/`
  (already gitignored as of commit `0efda174`; SHA spot-checks
  confirmed byte-identical to rpi-shares' map-reader-llm content
  before deletion). Plus /tmp Step 2 logs, dry-run logs, comparison
  test artefacts.

- [x] 2026-05-22 **B — Phase 0 Steps 6 + 7 (per-project
  `archive/cc-sessions/` removal)** — DONE. Per-project verification
  script (`/tmp/verify-project-archive.py`, since cleaned up)
  confirmed 100% of source session_ids present in rpi-shares before
  any destructive op. amd-tower: 202 sessions across 3 projects;
  zbook: 251 across 4. All verified clean. Per-project sequence
  executed (git lfs untrack for LFS-tracked repos → git rm --cached
  → gitignore → commit → push → rm -rf). Commits:
  - map-reader-llm: `2f83ec58` (amd-tower) + zbook pulled + removed
  - LLM-History-Paper: `226def9` (amd-tower) + zbook pulled + removed
  - llm-reproducibility: `1b191cd` (amd-tower) + zbook pulled + removed
  - theseus-ship: `7359144` (zbook-only)
  Total freed: ~1.25 GB on amd-tower + ~1.24 GB on zbook. Pre-existing
  audit caveats remain unaddressed: `rebuild_catalogue`'s one-level
  scan limit, and the deferred `git lfs migrate export` history
  rewrite (post-journal-submission per the 2026-05-20 decision).

- [ ] **B (originally pending)** — *superseded by completed entry above*

  **Per-project safety procedure** (run for each project before
  destructive ops):

  ```bash
  # 1. List session_ids actually present in the source
  PROJECT_ARCHIVE=~/Code/<project>/archive/cc-sessions
  cd "$PROJECT_ARCHIVE"
  # Extract from session.meta.json files where possible
  find . -name "session.meta.json" -exec \
    python3 -c "import json,sys; m=json.load(open(sys.argv[1])); print(m.get('session',{}).get('id',''))" \
    {} \; > /tmp/src-sids.txt
  # Plus from dir-name UUIDs where meta.json missing
  # ...

  # 2. Build rpi-shares' known-session_ids set from CATALOG.json
  python3 -c "
  import json
  data = json.load(open('/home/shawn/mnt/rpi-shares/cc-archives-consolidated/CATALOG.json'))
  for s in data.get('sessions', []):
      print(s.get('id',''))
  " > /tmp/dest-sids.txt

  # 3. Set difference: source sids NOT in destination = "missing"
  comm -23 <(sort -u /tmp/src-sids.txt) <(sort -u /tmp/dest-sids.txt) > /tmp/missing.txt
  echo "missing in dest: $(wc -l < /tmp/missing.txt)"
  # 4. STOP if any missing. Otherwise proceed to git operations:

  cd ~/Code/<project>
  git lfs untrack "archive/cc-sessions/**"   # Steps 6 — LFS-tracked repos only
  git rm -r --cached archive/cc-sessions/    # Step 7 — un-track from git
  echo "archive/cc-sessions/" >> .gitignore
  git add .gitignore .gitattributes
  git commit -m "chore: stop tracking archive/cc-sessions/ (post-Phase-0)"
  git push
  rm -rf archive/cc-sessions/                # local removal
  # On zbook: git pull, then rm -rf archive/cc-sessions/
  ```

  **Caveat 1**: `rebuild_catalogue` scans one level deep — nested
  sub-category sessions (e.g. `LLM-History-Paper/theseus-ship/`,
  `map-reader-llm/vlm-burial-mound-detection/`) may not show in
  CATALOG.json. For those projects, also check that source-side
  sub-category subdir contents are reflected on rpi-shares' nested
  paths before destructive ops.

  **Caveat 2**: Git LFS untrack stops new files going to LFS but
  leaves history-resident pointer stubs in old commits. The full
  `git lfs migrate export --include="archive/cc-sessions/**"
  --everything` history rewrite is **deferred to post-journal-
  submission** (force-push history rewrite; not blocking).

- [ ] **C — pre-v2 backup cleanup** (~96 MB pa-data copy +
  ~96 MB rpi-server copy). Cooldown gate: ≥1 week of stable v2
  operation. v2 shipped 2026-05-16; today is 2026-05-22 (6 days).
  **Wait until 2026-05-23 or 2026-05-24** before removing. Safety
  check: confirm zero v2-related errors in `logs/extraction.log`
  for the cooldown window. Default removal target per earlier
  decision: pa-data copy first (keeps the git submodule lean —
  the 96 MB `claude_memories.dump` is the bulk).

- [ ] **D — source-side `archive/cc-interactions/`** (~11 MB across
  3 project repos) — **KEEP for now**. These are pre-Dec-2025
  manual `/export` `.txt` outputs in `~/Code/{blue-mountains,
  fieldmark-docs-staging,llm-reproducibility}/archive/cc-interactions/`.
  They're now mirrored to rpi-shares' `manual-exports/<project>/`
  AND to working-machine local `~/cc-archives/manual-exports/`,
  but the source-repo copies are tracked git content + represent
  the original research-provenance location. Small, immutable,
  historical. Not a high-value cleanup target; revisit only if
  source repo bloat becomes an issue.

- [ ] **E — Do NOT cleanup (reference list)**:
  - `~/.claude/projects/*.jsonl` — CC's live runtime store; CC
    manages 30-day retention; production hook reads/writes here.
  - `~/cc-archives/` — the new full local mirror; ~3.4 GB on each
    working machine; offline + travel resilience.
  - rpi-shares canonical store at `~/mnt/rpi-shares/cc-archives-consolidated/`.
  - `data/experiments/bake-off-metadata-2026-05-18/` and any future
    experiment artefacts — research provenance.
  - Git LFS objects in history for map-reader-llm + LLM-History-Paper
    — deferred to post-journal-submission per the 2026-05-20
    architectural decision.

### Older / non-cleanup pending tasks

- [ ] **Backup cleanup**: remove one of the two pre-v2 backups (in
  `data/archive/pre-v2/` or `~/cc-archives/pre-v2/` on rpi-server)
  after ≥1 week of stable v2 operation. Default removal target:
  pa-data copy (keeps git lean; the 96 MB `claude_memories.dump` is
  the bulk). *(Duplicates item C above — kept here for historical
  cross-reference; resolve via item C.)*
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

  - [x] 2026-05-22 **Step 2** — Gemini 3.5 Flash sweep of unarchived
    live JSONLs across amd-tower (76 sessions) + zbook (33 sessions)
    = **109 main-thread sessions archived**, 0 errors, 116
    trivial-skipped, ~$7-10 total spend against the $25 cap. Sapphire's
    13 sessions were scp'd to amd-tower's live store pre-Step-2 and
    folded into the amd-tower batch. Critical cwd-extraction bug in
    `_extract_cwd_from_jsonl` discovered + fixed before launching
    (see toolkit commit `1dd4d69`); without that fix ~90% of sessions
    would have mis-routed to `shawn/`.
  - [x] 2026-05-22 **Layout cleanup v2** — `_legacy/` umbrella
    consolidates the earlier `_legacy-archive/` + `_misc-cwd/` + the
    dormant sapphire-era projects + grouped TRAP work. Top-level now
    16 active project_ids + 3 reserved namespaces + 2 root files.
  - [x] 2026-05-22 **Mirror rpi-shares → working-machine local stores**
    — amd-tower + zbook each hold a full 3.4 GB / 885-file copy at
    `~/cc-archives/`. One-shot via `rsync -av --delete`; ongoing
    automation is Phase 0 Step 8 (still pending).
  - [x] 2026-05-22 **Sapphire cleanup** — `~/.claude/` removed
    (including `.credentials.json`). CC CLI was already absent.
    Sapphire is now CC-free per the operational decision that it's
    a compute server, not a CC client.

  **Phase 0 consolidation + Step 2 sweep arc complete** — 3.4 GB
  canonical at rpi-shares, 702 session files + 183 manual `.txt`
  exports, 297 GB mount headroom, full mirrors on amd-tower + zbook.
  Still pending in Phase 0:

  - [x] 2026-05-22 **Steps 6 + 7** — `git lfs untrack` (LFS repos)
    + `git rm --cached archive/cc-sessions/` + gitignore + commit/push
    + `rm -rf` on every affected project across amd-tower + zbook.
    See cleanup register entry B above for per-project commit hashes.
  - [x] 2026-05-22 **Step 8** — `daily-sync.sh` cc-archives section
    added (commit `800f01a`). Pushes ~/cc-archives/ → rpi-shares
    canonical via `rsync -a --ignore-existing` on every SessionStart
    via the existing daily-sync-trigger.sh hook chain. Mount-presence
    check via `df` grep ("rpi-server" in source) handles the
    silent-empty-dir failure mode.
  - [x] 2026-05-22 **Step 9** — `scripts/resolve_session_id.py`
    landed (commit `800f01a`). Two-stage resolution: fast-path
    CATALOG.json lookup, exhaustive filesystem rglob fallback for
    nested sub-categories + `_legacy/` content. Smoke-tested against
    4 location classes — all resolve correctly.
  - [x] 2026-05-20 **Step 10 — indexing pattern decided**:
    working-machine-driven only. No rpi-server-side automation
    (no toolkit, no cron, no Python env). Captured in the
    "Architectural decisions worth not re-litigating" section.
  - [ ] **Content-equivalence dedup pass** (new follow-up 2026-05-22) —
    `/export`-era duplicates inside `~/cc-archives/` ancestry now living
    in the consolidated store. SHA dedup misses these; tractable via
    file-extension-and-co-presence-within-session-dir as a marker.
    Lower priority; cautious approach to avoid losing content that
    only exists in the `/export` framing.

  **Phase 0 — DONE**. All 10 steps + Step 4.5 layout cleanups (v1 + v2)
  completed 2026-05-22. Sole outstanding follow-up: content-equivalence
  dedup pass for `/export`-era duplicates (deferred, low-priority).

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
- [x] 2026-05-28 **Phase 0e — R2 wiring — DONE.** `scripts/push-archives-to-r2.sh`
  (`rclone copy`, additive/never-deletes, `--s3-no-check-bucket` +
  `--s3-disable-checksum`, `RCLONE_BIN` override, rclone-version guard)
  wired into `daily-sync.sh` after the cc-archives convergence passes,
  gated to a single push owner (`AMD-tower-ubuntu`) by hostname. Reads
  the canonical mount, pushes to `r2archives:pa-cc-archives`. Initial
  3.342 GiB / 4,654-object push completed + verified (`rclone check
  --size-only --one-way` → 0 differences). Required upgrading rclone
  1.60.1 → 1.74.2 on amd-tower (the distro version intermittently 501'd
  on R2 PutObject). Credentials `RCLONE_CONFIG_R2ARCHIVES_*` in
  `~/personal-assistant/.env`; rclone remote `[r2archives]` in
  `~/.config/rclone/rclone.conf`. zbook + rpi-server need no rclone
  upgrade (single-owner gate). **Goal (a) — comprehensive recording →
  network-share source-of-truth → offsite backup — closed end-to-end.**
- [x] 2026-05-17 **Vector 2 — open design doc** (`planning/vector-2-design.md`) — done; implementation parked under workstream D
- [ ] **Phase 4 — typed links** — **superseded by workstream D**; the typed-links problem is now solved by wiki-page cross-references + working-notes references + frontmatter tags
- [ ] **Phase 5 — migration sweep** — **demoted**; still useful as backfill for `verified` field but no longer gating anything
- [ ] **Phase 6 — extractor bake-off** — **deprioritised** (prior-art-scout: write strategy ~3–8 retrieval-accuracy points vs ~20 for retrieval; wrong lever)

**Small open follow-ups (new 2026-05-18):**

- [x] 2026-05-18 **SessionStart-hook sidecar for `commit_at_start`** — `hooks/session-start-code-state.py` writes `data/code-state/<session_id>.json`; `cc_session_toolkit/archive.py:capture_code_state()` now takes `session_id` + `sidecar_dir` kwargs and reads the sidecar best-effort. Hook wired into `settings.json` SessionStart array. Tests: 6 new in `test_subagent_archive.py`; full toolkit 220 passing.
- [x] 2026-05-18 **Hook hardening (`~/.claude/settings.json:91,112`)** — replaced `export $(grep -v '^#' ... | xargs)` with `set -a && . ~/personal-assistant/.env && set +a` on both PreCompact + SessionEnd archive commands. The Python `.env`-fallback pattern (`_ensure_anthropic_api_key` → `_ensure_gemini_api_key` post-F1) is retained inside `cc_session_toolkit.archive` as belt-and-braces.
- [x] 2026-05-23 **`pg_trgm` extension missing on `claude_memories` DB** — re-verified live: extension is loaded (`pg_trgm` in `pg_extension`) and `idx_memories_content_trgm` exists on `memories` (`schema.sql:83-84`; L79 in earlier notes was off-by-four). No action needed; the continuity entry was stale. Date of original landing unknown — both already present at pickup. See also duplicate entry below (audit-deferred list) closed same date.
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
- [x] 2026-05-23 **`pg_trgm` extension missing** (carry-over from
  2026-05-18) — re-verified live on `claude_memories`: extension
  loaded, `idx_memories_content_trgm` present at `schema.sql:83-84`.
  Stale entry; closed without action. Duplicate of the entry in
  "Small open follow-ups (new 2026-05-18)" above, also closed
  2026-05-23.
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
- [x] 2026-05-28 **Pilot wiki migration on personal-assistant** — PA-project layer (continuity, working-notes, user-observations, planning/, docs/, reflections/) migrated under `wiki/`; `wiki/index.md` added; `/reflect` made layout-aware. `notes/_tags.md` lift into `wiki/index.md` deferred — cross-project layer stays private in `data/` by design. Sketch + steps: `wiki/planning/wiki-index-draft.md`
- [x] 2026-05-18 **Sketch `notes/index.md` + initial wiki-tag vocabulary** — 24-tag set across four groupings (craft scaffolding 8, failure modes 5, domains 6, cross-cutting 5); pre-staged in `notes/_tags.md` ready to lift to `wiki/index.md` at pilot migration
- [x] 2026-05-29 **Extend `/weekly-review` with cluster-and-carry curation step** — done; new step 5 in `commands/weekly-review.md`. Vocabulary validated first (item #1, `wiki/planning/wiki-vocabulary-validation-2026-05-29.md` + `scripts/analyse-wiki-vocabulary.py`). See the top-of-doc workstream-D block for detail. Not yet exercised on a real week.
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
- **Auto-metadata extractor: Gemini 3.5 Flash (GA)**, not 3 Flash Preview
  (2026-05-22, model migration). Decision basis: 3-session head-to-head
  on amd-tower's actual unarchived live JSONLs (small/medium/large).
  3.5 Flash showed zero JSON structural defects vs 1-of-3 for 3 Flash
  Preview (a stray `three_ps.`-prefixed key under `three_ps` that would
  degrade `provenance_summary` via the M3 `.get() or default` guard);
  materially better named-entity preservation (commit hashes, git tags,
  people's names, CI bounds); ~20% faster wall-clock. 3× Flex price
  ($0.75/$4.50 vs $0.25/$1.50 per M input/output tokens, verified
  empirically) accepted for the price-quality trade-off — Three Ps
  fidelity matters for the RDA-IG framing, and 3 Flash Preview was
  going to need migration eventually anyway. Production `EXTRACTOR_MODEL_ID`
  flipped + pricing constants updated in cli.py 2026-05-22 (commit
  `cdc7c65`).
- **`_legacy/` umbrella for no-new-sessions content** (2026-05-22,
  layout cleanup v2). Subsumes the earlier `_legacy-archive/` (pre-toolkit
  scaffolding) + `_misc-cwd/` (cwd-derived sessions: Code, shawn) +
  dormant sapphire-era project_ids (sciphi-project, gemma-project,
  llm_models) + the grouped TRAP archaeological work
  (`_legacy/trap/TRAP-WD-2020-04/` + `_legacy/trap/trap-extraction/`).
  Single top-level namespace for everything that won't grow; active
  project_ids stay at the consolidated root.
- **Step 2 (Gemini Flex sweep of unarchived live JSONLs) ran per-machine,
  not batched at amd-tower** (2026-05-22 operational decision). Each
  working machine (amd-tower, zbook) ran `cc-session archive --all
  --gzip --auto-metadata --archive-root ~/mnt/rpi-shares/...` against
  its own live store. Chosen over the alternative "scp zbook's live
  JSONLs to amd-tower, run once" because per-machine preserves
  `code_state.commit_at_end` + `dirty_at_end` accuracy — the project
  repos that produced each session live on their own machines. The
  sapphire content was an exception (live JSONLs scp'd to amd-tower
  pre-Step-2, since sapphire has no toolkit + no project repos worth
  preserving code_state against).
- **Working machines hold full local mirrors of rpi-shares at `~/cc-archives/`**
  (2026-05-22, operationally realised — was an architectural decision
  on 2026-05-16, "full mirror everywhere"). Periodic `rsync -av --delete
  ~/mnt/rpi-shares/cc-archives-consolidated/ ~/cc-archives/` brings each
  machine into exact sync with the canonical store. Provides offline
  archive access + write-side scratch + travel resilience. Daily
  automation of this mirror is Phase 0 Step 8 (still pending).
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

### 2026-05-30 (Sat, latest G) — Workstream G §11 reconciliation: aspirational section reconciled against the live empirical assessment; five items added; paragraph-length gap diagnosed as a §6.5 artefact

Completed the §11 aspirational-section reconciliation (continuity row 589) — the last open Workstream-G item beyond the deferred multi-genre runs. Per Shawn's direction this was a **clean start**: the prior conscious style guides at `~/Code/prompts/System-setup/` were read to drive the reconciliation but are treated as superseded and are NOT cited in the guide; confirmed items instead carry `Live cross-ref` pointers into the empirical §§1–10. Four decisions resolved: (1) relabel confirmed items with live cross-refs (§§11.3/11.4/11.6/11.7); (2) add four editorial rules — standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation; (3) add a voice-calibration item (prefer first person for crispness, third person where it avoids convolution; baseline first-person-plural per §1.1); (4) the prior-guide 100–180-word paragraph target seemed to conflict with §6.5's median of 17 words, but a background investigation confirmed that is a **segmentation artefact** — `split_paragraphs()` counts headings, surviving front-matter and line-break fragments as paragraphs (non-prose = 41% of blocks but only 4.4% of words), so the median sits below the mean sentence length (21.45 words), impossible for real prose. Corrected median ≈27, mean ≈42; the apparent two-register cluster is contamination-driven (r = −0.78) and was never a formal bimodality.

- Guide §11 (submodule `16be506`): intro marked reconciled; live cross-refs on §§11.3/11.4/11.6/11.7; new §§11.9–11.13 (standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation, voice calibration).
- Agent template (`agents/corpus-style-analyser-v2.md`): Phase 4 + §11 skeleton now reconcile against the live empirical assessment, not the superseded prior guides; academic register marked reconciled 2026-05-30.
- §6.5 artefact: background agent quantified contamination across all 18 papers and proposed a suggest-only `phase1_pipeline.py` fix (an `_is_prose_block()` filter). **Not applied — decision pending:** the fix shifts the Phase 5 12-feature centroid (paragraph mean is a feature), so it would need a phase1→3→5 re-run; the 8-metric gate is unaffected.
- Multi-genre runs (row 590): deferred indefinitely per Shawn pending an immediate need + assembled corpus.
- Also this session: recovered and dispositioned three Phase-5 user-observation candidates (1 and 2 accepted, 3 discarded — commit `a57bcb4`).

### 2026-05-30 (Sat, G) — Workstream G Phase 5 refinement: 8-metric gate labelled aspirational-by-construction + modern-em-dash made the default

Cleared the deferred "Phase 5 future refinement — 8-metric gate tolerance review" row. This was **documentation plus one small default flip — NOT a re-calibration; no tolerance VALUES were changed.** Per Shawn's 2026-05-30 reframe, the gate is *aspirational by construction*: `--validate` found 0/18 corpus papers pass all 8 checks (median 4/8) because conjoining 8 tight bands around the corpus central tendency defines a consistency no single real paper achieves — so a FAIL is a deviation flag, not proof of off-voice text. **Two things done:** (1) flipped `phase5_evaluator.py` so the modern ≤0.20/1k em-dash ceiling is now the DEFAULT gate behaviour for new prose, with a new inverse flag `--corpus-em-dash` reaching the legacy two-sided 0.572 ±0.20 band (the legacy band is bimodal — 12/18 papers at exactly 0 — and rejects both halves of the corpus plus the zero-em-dash prose §6.3 calls correct for 2026+); the boolean threaded through `build_gate`/`evaluate_text` was renamed `corpus_em_dash` (default False), argparse help + module docstring updated. (2) Added a "Status: aspirational by construction" subsection to the top of Appendix E in both the v2.3 guide (`style-guide-academic-2026-05-30-2.md`) and the agent file (`agents/corpus-style-analyser-v2.md`), citing the 0/18 finding and per-check pass-rates, and updated the agent's Phase 5 status + documented invocation to the new default. **Validation re-run confirmed the flip only loosens em-dash for modern prose:** that check's corpus pass-rate rose 1/18 → 12/18, median checks-passed 4/8 → 5/8, papers-passing-all-8 unchanged at 0/18, sanity verdict still PASS (exit 0). `phase5_evaluator.py` lint-clean (no line >100 chars). Near-duplicate older guide `style-guide-academic-2026-05-30.md` (no `-2`) left untouched per the brief.

Artefacts touched this session:
- Edited: `scripts/style-analyser/phase5_evaluator.py` (em-dash default flip + `--corpus-em-dash` inverse flag); `notes/style-guides/academic/style-guide-academic-2026-05-30-2.md` (Appendix E aspirational subsection + † footnote update); `agents/corpus-style-analyser-v2.md` (Appendix E aspirational note + Phase 5 status + invocation comment); `wiki/continuity.md` (refinement row done + this entry)
- Data submodule: `style-corpus/phase5-validation-report.md` regenerated (em-dash calibration 1/18 → 12/18, median 4/8 → 5/8)
- Coordinated with a concurrent foreground session editing a different region of `continuity.md` (row 574 + guide §11): explicit pathspecs only, fetched + checked 0-behind before committing
- Left uncommitted (NOT mine): `wiki/reflections/session-log.md`, `wiki/reflections/session-reflection.md`; `data` submodule `memories/memories.jsonl` + `memories/tag-vocabulary.txt`

### 2026-05-30 (Sat, latest PA) — Vector 2b (scratchpad byte budget) shipped dark + self-review + feasibility scope + relocation verify

Background workstream-B PA session (concurrent with the workstream-G Phase 5 session above — shared working tree; coordinated via explicit pathspecs + repeated 0-behind checks, no collisions). **Vector 2b** — bounded the scratchpad's session-start footprint, the dominant payload after PASS 2 digested the recall dump. Design doc written first (`wiki/planning/vector-2b-design.md`) per the parent design's §1a out-of-scope rule. **Crux:** a curated principle log is not a recall dump (no `verified`, no decay, deliberately global, already distilled zero-loss), so Vector 2's rank-and-drop selector is the wrong shape; the mechanism is narrower — a byte-warn that actually fires (the line-based one never did at 29 KB / 99 lines) + a section-aware regrowth guard-rail (`digest.cap_markdown_to_budget`, whole `## ` sections, never split, visible trim marker), lifted out of `build_digest`'s `fits()` closure to honour §7f "share the primitive". **Shawn chose Fork A (guard-rail):** budgets above current sizes → nothing trims today. Flag-gated on its own sentinel `~/.pa-scratchpad-budget` (mirrors `digest_mode_enabled()`), default OFF → byte-identical output → the live Vector 2 §8 window (review 2026-06-13) is unconfounded. Warn recalibrated 12 KB → 17 KB after live smoke showed a sub-floor warn nags every session post-distillation. **Then three follow-ups:** (a) **self-review** via adversarial agent — found one dormant contract bug (`cap_markdown_to_budget` over-promised "within budget" while the sub-floor case can exceed, the same scaffolding-floor caveat `build_digest` documents); fixed both docstrings + added 2 floor tests. (b) **feasibility scope** of "verify MORE memories" (agent + re-verified at source) — the substantive finding: only **1,034/29,701 records (3.5 %)** carry a re-resolvable anchor, `anchor_verify` returns `None` for the rest, so backfill lifts verified-true 629 → ~653 (~24 net); re-resolution is local/free/no-gate but near-worthless for Stage 2, and **the promoted-recent fallback Stage 2 meant to delete is the PERMANENT handler for the 96.5 % anchorless, not a stopgap** — broad coverage would need an API-gated retroactive anchor-generation pass (deferred). (c) **working-notes.md relocation** turned out already done by an earlier 2026-05-30 background agent (continuity box was stale) — re-verified at source (zero `*/reflections/working-notes.md` remain; all 5 repos track `docs/notes/working-notes.md` clean; toolkit template root-cause fixed) and flipped the box rather than manufacture commits. Scheduled the 2026-06-13 amd-tower enablement as a Google Calendar reminder (a remote `/schedule` routine can't touch a machine-local sentinel — surfaced the mismatch).

Artefacts touched this session:
- New: `wiki/planning/vector-2b-design.md` (design + §11 impl record)
- Edited: `scripts/digest.py` (`cap_markdown_to_budget` + `_split_markdown_sections` + `SCRATCHPAD_TRIM_MARKER`; floor-contract docstrings); `hooks/session-start-retrieval.py` (byte-warn constants, `scratchpad_budget_enabled()`, flag-gated cap in both loaders); `tests/test_digest.py` + `tests/test_retrieval_hook.py` (+30 tests total); `wiki/continuity.md` (workstream B: Vector 2b done, feasibility scope recorded, relocation box flipped, this entry)
- Tests: full suite **783 passed** (was 753 at session start), 0 regressions
- Parent commits (newest first): `82838f5` relocation box-flip; `1fcfa5a` feasibility scope; `bc54177` floor-contract fix; `bdde344` Vector 2b done; `422905f` design doc-update; `da5790f` Vector 2b code; `db4da15` design doc
- External: Google Calendar event 2026-06-13 09:00 AEST (amd-tower enablement reminder)
- Left uncommitted (NOT mine — concurrent G/Phase-5 session): `wiki/reflections/session-log.md`, `wiki/reflections/session-reflection.md`; `data` submodule memories.jsonl / tag-vocabulary.txt
- Sentinel `~/.pa-scratchpad-budget` deliberately NOT created — Vector 2b is dark; enable after the §8 review

### 2026-05-30 (Sat, latest) — Workstream G Phase 5 done: Mahalanobis evaluator + 8-metric gate; Workstream G core complete

Built `scripts/style-analyser/phase5_evaluator.py` (the Phase 5 downstream generation-time gate, undertaken in a fresh session per the prior entry's decision). Deterministic CPU-only tool: `--text`/`--passage` → markdown/JSON verdict with (a) Mahalanobis distance to the corpus centroid in a 12-feature, length-normalised, Ledoit-Wolf-shrunk space, and (b) pass/fail vs the 8-metric Appendix E gate. **Key design moves:** input measured by importing `process_paper` from `phase1_pipeline.py` (identical features, zero drift — no re-implementation); the three phase3-bimodal metrics (`em_dash_per_1k`, `mean_dep_depth`, `pace_count`) excluded from the single centroid per plan §6.3 option (a) and reported in an advisory block with their cluster split, the exclusion set read live from `phase3-promotion-clean.json` so it self-syncs; empirical leave-one-paper-out distance distribution is the primary envelope (χ² percentile a caveated secondary). Validated via `--validate`: off-register fixtures score 14.2 / 21.7 vs corpus LOO max 4.67, held-out real paper 3.15 (within range). **Methodological finding** surfaced by an added gate-calibration block: 0/18 corpus papers pass all 8 gate checks (median 4/8) — the Appendix E tolerances on em-dash, semicolon, announcement-colon and hedge are tighter than between-paper variance. **Shawn's reframe:** this is aspirational by construction (conjoined tight bands define a consistency no single paper hits), not a mis-calibration — it parallels his existing aspirational guides; the em-dash band is the one genuine artefact (bimodal mean, already sidestepped by `--modern-em-dash`). Logged the finding to working-notes (commit `6e166e1`) and reframed the continuity refinement row accordingly. Added `scikit-learn` + `scipy` to `~/Code/write-like-me/.venv` (no dependency manifest there to record them — pre-existing reproducibility gap, documented in the agent file). Agent file `corpus-style-analyser-v2` flipped: pipeline section now lists 5 scripts, canonical invocation gains the Phase 5 step, Phase 2–5 status footer all ✅, Workstream G core marked complete.

Artefacts touched this session:
- New script: `scripts/style-analyser/phase5_evaluator.py` (~720 lines; lint-clean, no line >100 chars)
- Edited: `agents/corpus-style-analyser-v2.md` (5-script pipeline, Phase 5 invocation, footer flip to all ✅); `wiki/continuity.md` (workstream G header + Phase 5 row done + reframed refinement row + this log entry); `wiki/working-notes.md` (aspirational-gate observation, via obs-writer)
- Data submodule: `style-corpus/phase5-validation-report.md` (LOO + sanity fixtures + gate calibration)
- Parent commits (newest first): `dbc1f04` docs(continuity) Phase 5 done + refinement; `fc1eb32` chore(data) submodule bump; `80b2694` feat(style-analyser) Phase 5 evaluator + agent flip; plus `6e166e1` working-notes observation (via obs-writer)
- Submodule commits: `fe78db1` Phase 5 validation report
- Remaining workstream-G work: multi-genre runs (Substack/business/teaching — agent re-invocations, need a corpus + Phase 4 API approval each) + the optional tolerance-labelling refinement
- Left uncommitted (NOT mine — pre-existing): `wiki/reflections/session-log.md`, `wiki/reflections/session-reflection.md`; `data` submodule memories.jsonl / tag-vocabulary.txt

### 2026-05-30 (Sat) — Workstream G Phases 2 + 3 + 4 done: Biber relayout, Phase 3 promotion + bimodality + guide verifier, Phase 4 Panickssery exemplars; v2.3 guide passes verifier 35/35

Long session spanning resumption of the workstream-G corpus-style-analyser work from a 2026-05-24 checkpoint through completion of three numbered phases. Resumed with the Stream B (Biber MDA relayout) edit landing on the v2.1 agent file → v2.2; then dispatched the v2.2 subagent to generate `style-guide-academic-2026-05-30.md` (1241 lines, 18 papers / 127,720 words, single-digit-dollar Opus subagent run). Reconciled a parallel-session reorg (planning/ → wiki/, continuity.md moved, agents/ dir now tracked, ~/.claude/agents/ files symlinked from repo) before committing — all my edits had been swept into auto-syncs during the gap, so the inventory was clean; only the agent file had a stale `planning/` → `wiki/planning/` path to patch. Migrated corpus-style-analyser × 2 from standalone `~/.claude/agents/` files into the tracked `agents/` dir with symlinks back, conforming to the existing pattern (7 other agents already followed it). **Phase 4 — Panickssery exemplar block** then landed: built `phase4_exemplar_scorer.py` (18-category sentence-level feature detector with year-binned em-dash rule), selected 5 exemplars (role-balanced ≥2 first + ≥2 last + ≥1 middle, date-spread 2018–2024, no PDF-extraction artefacts), ran 5 inversions in-session (no SDK call needed since I am Opus 4.7), appended Appendix F (191/600 words budget). **Phase 3 — Kumar formalisation + bimodality detector + guide verifier** was the headline thread: built `phase3_promotion.py` (deterministic verdict; emits verbatim `papers_present`/`papers_absent`) and `phase3_guide_verifier.py` (regression gate over every numeric claim). Verifier-first audit on v2.2 surfaced 1 confabulation (§6.3 "8/18 papers, plus two more" when 6/18 was truth — Opus subagent invented "plus two papers with single-digit counts" to inflate visible support), 2 status-judgement disagreements (§6.4, §6.5 attested-concentrated despite CV < 1.5), and 1 false-positive cluster of verifier-side issues (§3.4 mapping bug, §6.3 regex over-fire, §6.4 sub-cluster handling — all fixed). After tighten-up: 5 real FAILs + 3 WARNs. Added a bimodality detector (inner-gap rule, ≥3 papers each side, threshold 0.25) which both validated §6.3 em-dash bimodality AND caught a NEW §5.3 mean_dep_depth finding (5.76–5.87 cohort of 5 vs 6.13–6.75 cohort of 13; CV 0.046 tiny but gap fraction 0.269) the v2.2 algorithm missed. Then regenerated v2.3 in-session as `style-guide-academic-2026-05-30-2.md` (preserves v2.2 baseline for diff) applying: §6.3 confabulation fix, §6.4/§6.5 downgrades to algorithm verdict, §5.3 upgrade to attested-concentrated. **End-to-end test:** v2.2 verifier = 29 PASS / 5 FAIL / 3 WARN; v2.3 verifier = **35 PASS / 0 FAIL / 0 WARN**. The confabulation guard works.

Phase 5 (Mahalanobis evaluator, 3–5 h, self-contained) is the only remaining workstream-G item. Decided to undertake in a fresh session for context-cost reasons (this conversation accumulated many branches; Phase 5 is independent of in-session memory and consumes the now-committed phase1+phase3 artefacts).

Artefacts touched this session:
- New scripts: `scripts/style-analyser/phase3_promotion.py`, `phase3_guide_verifier.py`, `phase4_exemplar_scorer.py`
- Edited: `agents/corpus-style-analyser-v2.md` (v2.1 → v2.3 — Biber relayout, confabulation guard, Phase 3 status, pipeline section updated for 4 scripts)
- Data submodule: `notes/style-guides/academic/style-guide-academic-2026-05-30.md` (v2.2, subagent-generated), `style-guide-academic-2026-05-30-2.md` (v2.3, in-session regeneration), `style-corpus/phase3-promotion-clean.json`, `style-corpus/phase3-guide-verifier-report.md`, `style-corpus/phase3-guide-verifier-report-v23.md`, `style-corpus/phase4-exemplar-candidates.json`; audit doc §11 (Stream B Biber relayout) committed during 2026-05-24/25 auto-sync
- Repo restructure consequence: corpus-style-analyser × 2 agents migrated from standalone `~/.claude/agents/` files into tracked `agents/` dir with symlinks back to `~/.claude/agents/`, matching the existing pattern used by all 7 other tracked agents
- Parent commits this session (newest first): `a719128` chore(data): bump for Phase 3; `78f425a` feat(agents): v2.3 confabulation guard; `c4b47d5` feat(style-analyser): Phase 3 scripts; `2a3a678` chore(data): Phase 4 bump; `169e944` feat(style-analyser): Phase 4 scorer; `61d6814` chore(data): v2.2 bump; `09989bb` feat(agents): track corpus-style-analyser agents
- Submodule commits this session: `ff0322a` v2.3 + Phase 3 artefacts; `d3eb1f4` Phase 4 Appendix F; `82815a7` v2.2 Biber-relayout guide

### 2026-05-30 (Sat, later) — Vector 2 PASS 2 (live cutover, enabled on amd-tower) + scratchpad distillation

Background workstream-C PA session, continuing from the PASS 1 entry below.
Three threads. **Thread 1 — Vector 2 PASS 2 (workstream B).** Wired
`digest.py` into the live `hooks/session-start-retrieval.py` behind a
machine-local flag (`digest_mode_enabled()`: env `PA_DIGEST_STAGE1` → sentinel
`~/.pa-digest-stage1` → OFF), deliberately NOT in the synced `data/` submodule
so amd-tower can't leak to zbook/rpi-server. Shipped dark (default-OFF proven
byte-identical; the 83 existing retrieval-hook tests stayed green untouched),
then enabled on amd-tower via the go/no-go — sentinel created, verified
`digest_mode_enabled()` True; live smoke (inscriptions cwd): flag ON →
`# Session-start digest` 1,488 B (≤1,500 cap) vs flag OFF → `# Memory Context`
48,083 B. +19 tests; full suite 753 green, 0 regressions (commit `68427cd`).
Relocated the tier-2 protocol to `global-claude-md/tier-2-retrieval.md`
(design §7e); digest footer points at it. The 2-week §8 observation window is
running; review booked as a Google Calendar event for Sat 2026-06-13 (the
§8 logs are gitignored/local-only so a remote `/schedule` agent couldn't read
them — calendar fits the local review). **Thread 2 — scratchpad distillation
(the Vector 2b "content" half).** With the recall dump now digested to ~1.5 KB,
the ~29 KB scratchpad became the dominant session-start term. First-ever
distillation of `data/scratchpad.md` (header was `Last distilled: —`):
29,268 → 15,484 B (47 % cut, zero principle loss) — removed 28 duplicate/
misfiled `## Patterns` entries (project-specific ones already held verbatim in
`data/scratchpads/{map-reader-llm,voice-assistant}.md`; exact dups of canonical
Constraints/Preferences entries above). Verified via diff (only 2 added lines:
header + moved entry). Submodule `d840239`, superproject bump `f98bf2a`.
**Thread 3 — Vector 2b teed up** as the next focused design pass (byte budget
on `load_scratchpad()` + flip the line-based `SCRATCHPAD_WARN_LINES` to bytes;
needs a short design doc first per §1a). Concurrent style-guide session
interleaved pushes throughout; explicit pathspecs kept the two sessions' work
cleanly separated — nothing lost on either side.

- Commits on `origin/main`: `68427cd` (hook digest branch + machine-local flag
  + tier-2 doc + 19 tests), `09d2e74` (continuity PASS 2), `f98bf2a` (data
  submodule bump), `e7b2c40` (continuity scratchpad + Vector 2b). Data
  submodule: `d840239` (scratchpad distillation, pushed to pa-data).
- Live change: `~/.pa-digest-stage1` created on amd-tower — digest mode ON for
  all future session-starts here; rollback `rm ~/.pa-digest-stage1` or
  `PA_DIGEST_STAGE1=0`.
- New file: `global-claude-md/tier-2-retrieval.md`. Touched:
  `hooks/session-start-retrieval.py`, `scripts/digest.py` (footer → doc
  pointer), `tests/test_retrieval_hook.py` (+19 tests).
- Calendar: Google Calendar event Sat 2026-06-13 09:00 AEST — §8 review +
  go/no-go on zbook/rpi-server rollout.

### 2026-05-30 (Sat) — Vector 2 PASS 1 (digest engine + proof, hook untouched) + git-cadence correction

Background workstream-C PA session; two threads. **Thread 1 — Vector 2 PASS 1
(workstream B).** Built the Stage 1 session-start digest as an engine + proof
with the live hook deliberately untouched (Shawn picked the low-blast-radius
option over a full live cutover). `scripts/digest.py` is a pure, I/O-free
selector (what-changed counter, verified-true ranking, promoted-recent
fallback, hard byte cap); `scripts/digest-preview.py` reproduces the live
recall dump via the hook's own functions and prints before/after;
`tests/test_digest.py` has 35 tests. Re-measured baseline (reproducible via the
harness, 2026-05-16 design table still holds within noise): recall dump
16,222 B (PA hub) / 17,480 B (inscriptions) → digest ~1,484 B, ~91 % cut, cap
intact. Key finding — the design premise is obsolete: it assumed 8 verified-true
corpus-wide, but there are now 289 verified-true in the last 7 days, so the
fallback is near-vestigial. `/audit` (4 parallel execution-verifying subagents)
found 1 real Critical (byte-cap docstring over-claimed an *unconditional*
guarantee; ~550 B of scaffolding is irreducible) + 3 Medium (greedy `break`
emptied the digest on an oversized top entry; `count_changes` new+updated
double-count; preview category-line divergence) + Lows — all fixed in-session;
full suite 734 passed. Also instrumented `fetch-memories.py` (best-effort
`fetch-memories.log`, tier-2 utilisation, design §7c) and a `digest.log`
primitive. PASS 2 (live cutover) is queued in workstream B + the verify-queue;
finding (3) digest-density tuning and the "verify MORE memories" feasibility
pass are both logged in workstream B. **Thread 2 — git-cadence correction.**
Shawn flagged that I'd grown reticent about committing and especially pushing
over ~2 weeks. Traced it at source: not his preference (scratchpad 2026-04-23
line 44 — "Default is direct-push to main") but the harness per-session default
("commit or push only when the user asks / branch off main first") winning over
his recorded norm. Fix: a standing-authorisation block in the Git section of
`global-claude-md/shared.md` (composed into `~/.claude/CLAUDE.md`) makes liberal
commit + push-after-every-commit + direct-push-to-main the default for
sole-authored repos, with collaborative repos (FAIMS3) gating in their own
project CLAUDE.md. Captured as a `feedback` memory + a FAIMS3 inbox follow-up.

- PA commits (all pushed to `origin/main`): `be4bcf8` (digest.py + tests +
  harness), `809a89f` (fetch-memories instrumentation), `1c9ffd5` (continuity
  workstream B + audit + verify-queue), `4673735` (shared.md git-cadence default)
- pa-data commit (pushed): `925d070` (FAIMS3 inbox capture); memory
  `2026-05-30-51525074863e` (feedback, 3 anchors) written to memories.jsonl
  (daily-sync commits it)
- Files: `scripts/digest.py`, `scripts/digest-preview.py`,
  `tests/test_digest.py` (new); `scripts/fetch-memories.py`,
  `global-claude-md/shared.md` (edited)
- Design ref: `wiki/planning/vector-2-design.md` §6a (selector), §8 (rollout),
  §7b/§7d (density-tuning levers, deferred as finding 3)

### 2026-05-29 (Fri) — Workstream D items #1–#4: vocabulary validation, /weekly-review cluster-and-carry, working-notes relocation, vocab lift + /retro grimoire review

Background workstream-C session continuing goal (b). Cleared four of the
five remaining workstream-D items. **#1** — wrote a reusable analysis script
(`scripts/analyse-wiki-vocabulary.py`) and validated the 24-tag wiki
vocabulary empirically against the ~29k-record memory corpus + the 33
`notes/_inbox.md` candidates; the report finds two well-attested themes with
no tag home (`agent-orchestration`: corpus cluster 913 usages/327 tags, ~10
inbox candidates; `infrastructure`/ops: 1023/417, ~5) and two genuine
redundancies (`memory-systems`≡`memory-system`; `three-Ps`⊂`provenance`),
net delta ADD 2/MERGE 2 → still 24, deferred to `/weekly-review` ratification
per the curation rule. **#2** — extended `/weekly-review` with a new step 5
"Cluster-and-Carry Wiki Curation" (5a ratify pending vocab delta → 5b gather
→ 5c cluster → 5d draft diffs → 5e carry), draft-only and human-ratified;
5a closes the chicken-and-egg with #1. **#3** — dispatched a background
agent that relocated misplaced `working-notes.md` in 5 repos (→
`docs/notes/working-notes.md`, history preserved via `git mv`) and fixed the
cc-session-toolkit scaffold root cause (template moved out of
`data/reflections/`, `init.py` updated, 301/301 tests pass); relocation
commits landed in 6 repos and were **all pushed to `origin/main`** (5 at
session close on 2026-05-30 after a re-verify; map-reader-llm's earlier, on
a concurrent gs/h11 push). **#4** —
lifted the tag vocabulary from the private `notes/_tags.md` to its canonical
public home (`wiki/index.md` "Tag vocabulary"); `_tags.md` is now a redirect
stub; `_inbox.md` + notes/grimoire content stay private; and added a step 5c
"Grimoire Publishing Review" to `/retro` (Shawn's call: monthly cadence, not
weekly). #5 (Vector 2) deferred to its own session. PA #1/#2/#4 work
committed and pushed; #3 repos left for Shawn.

Artefacts touched:
- New: `scripts/analyse-wiki-vocabulary.py`, `wiki/planning/wiki-vocabulary-validation-2026-05-29.md`
- Edited: `commands/weekly-review.md` (step 5), `commands/retro.md` (step 5c), `wiki/index.md` (vocabulary lifted in), `wiki/continuity.md`
- Data submodule: `notes/_tags.md` (→ stub), `notes/index.md` (pointer)
- PA commits: `60ef989` (#1+#2), `cc1a93b` (#4a lift), `3a13b15` (#4b retro); submodule `d0e4311`, `769f448`
- #3 relocation commits (in `~/Code/*`), **all pushed to `origin/main`**: inscriptions `89cad01`, LLM-History-Paper `73f9876`, llm-reproducibility `dc40d8e`, 2026-mq-…-paper-b `99cab2b`, cc-session-toolkit `9129e8a` (pushed 2026-05-30); map-reader-llm `3a17575` (pushed earlier on a concurrent gs/h11 push; repo HEAD now `c8f92781`)

### 2026-05-28 (Thu, evening) — Research-notes/reflections split + PA wiki migration (workstream D pilot complete)

Background workstream-C session picking up goal (b) (the wiki/memory
architecture) after goal (a) closed earlier today. Started by fixing a
reconciliation snag Shawn flagged: `working-notes.md` (research notes) and
`reflections/` (meta-research) had no clear ownership. Split them —
obs-writer + `/observe` own `working-notes.md`; `/reflect` owns the
reflections set (session-reflection, abductive-reasoning, session-log) and
now excludes `working-notes.md`. A cross-repo survey surfaced a
half-finished migration: 5 of 7 repos keep `working-notes.md` *misplaced*
inside `docs/notes/reflections/`, root cause a cc-session-toolkit
scaffolding template that ships the file in the wrong place — logged as a
future per-project relocation task. Then ran the PA wiki-migration pilot to
completion: `continuity.md`, `planning/`, `docs/open-science/`, and
`reflections/` all moved under `wiki/`; `wiki/index.md` front door created;
the cross-project `notes/` + `grimoire/` layer confirmed to **stay private**
in `data/` by design (sharing is positive-action promotion to `published/`,
Pattern A/B per the existing `published/README.md` — not an open decision).
All three lifecycle tools made layout-aware (prefer `wiki/…`, fall back to
legacy paths) so the 5 unmigrated repos keep working. Old repo-root
`planning/` + `docs/` removed entirely.

- Commits (all pushed to `origin/main`): `1479244` notes/reflections split;
  `21a7e60` continuity→wiki + index; `6481838` privacy model resolved;
  `fd8ec38` planning/+docs/ moved; `b69ef5c` reflections moved + /reflect
  layout-aware.
- Skills/agents: `agents/obs-writer.md`, `commands/observe.md`,
  `skills/reflect/SKILL.md` (layout-aware locate + research/meta split).
- Wiki: `wiki/index.md` (new), `wiki/continuity.md` (this file, moved from
  `planning/`), `wiki/planning/` (44 files), `wiki/docs/open-science/`,
  `wiki/reflections/` (3 files).
- Refs updated: README structure diagram + design-docs section, cot-capture
  relative links, 4 script doc-comments, 2 zotero-script comments,
  `session-start-protocol.md`.
- Plan doc: `wiki/planning/wiki-index-draft.md` (privacy resolution +
  relocation steps + per-file `_inbox`/`_tags` privacy review).
- Deferred (tracked in workstream D + wiki-index-draft): working-notes
  relocation in the 5 legacy repos + toolkit-template fix;
  `notes/_inbox.md`/`_tags.md` privacy review; `/weekly-review`
  cluster-and-carry step.

### 2026-05-28 (Thu, midday) — v1.3 archive upgrade results + cost-tracking backport + preflight skip + cap calibration

Follow-on session reviewing the 2026-05-26 archive-wide v1.3 upgrade
run and closing two remaining loose ends in the backfill script.

**Archive-wide upgrade run (launched 2026-05-26 15:24 local, ran
~6h 45m).** 626 / 637 parent successes (98.3%). 11 failures, all
content-empty: 4 theseus-ship stubs (200–650 bytes compressed), 6
``*empty-abandoned-session*`` map-reader archives, 1 with no JSONL
at all. **0 JSON parse failures across 2,018 subagent calls** —
today's ``SUBAGENT_NARRATIVE_SCHEMA`` enforcement (commit `8e44f1a`)
fully closed the failure class it was designed to close. Real
spend ~$163 actual vs ~$216 dry-run estimate (under by ~$53).
Per-subagent cost came in at ~$0.04, not the flat $0.05 budgeted —
worth carrying into future estimates. Schema enforcement also
appears to improve content quality on edge cases (e.g., the
2026-04-28 EOD recap session that previously emitted 0 phases now
correctly emits 2 phases for its multi-thread Tue/Wed content;
phases-threshold prompt fix from 2026-05-25 Workstream B working
as designed).

**Cap calibration (`MAX_SUBAGENT_SUMMARIES` 20 → 70).** 17 of 637
sessions exceeded the original 20-cap, heaviest at 68 subagents.
591 subagents total were truncated by the cap, costing those
sessions ~25-65% of their structural narrative coverage. 70 covers
the empirical worst-case distribution; per-session blast radius
still bounded (~$3 worst-case at cap, vs ~$1 at 20). Toolkit commit
`f80094b`.

**Cost-tracking backport (Item #2).** Backports Agent D's
instrumented-wrapper pattern from ``validate-production-path.py``
(pa-data commit `bbe2a7b`) into the production backfill script.
Monkey-patches ``cc_session_toolkit.archive._call_gemini_once`` at
runtime, captures input/output tokens + Flex-tier cost + wall time
+ phase (parent/subagent) into ``_CALL_RECORDS``. Writes JSON cost
log to ``data/logs/backfill-cost-log-<UTC>.json`` on exit (including
SIGINT — written from the ``finally`` block); brief per-phase
summary prints to stdout. Toolkit commit `172a1a7`.

**Preflight skip + permanent marker (Items #1, #3 — combined design).**
New ``EMPTY_TRANSCRIPT_TOKEN_THRESHOLD = 50`` and helper
``mark_session_permanently_skipped(meta_path, reason)`` that writes
``auto_metadata_skip_permanent: true`` + reason atomically. Both
finders (``find_sessions_needing_backfill``,
``find_sessions_needing_v13_upgrade``) honour the marker.
``main()`` now runs a preflight before ``generate_auto_metadata``:
distils the transcript, counts tokens, if below threshold marks the
session + skips. Counts surface as a new ``skipped_empty`` tally in
the final summary. Item #1 done as a one-off: the 11 known-empty
sessions from the 2026-05-26 run are manually marked. Toolkit
commit `5660265`. +12 tests (289 → 301 passing).

**Reupgrade in flight (Item #1 — the actual rerun).** 17 capped
sessions had their ``schema_version`` flipped 1.3 → 1.2 so the
finder picks them up. Combined queue: 17 capped + 11 known-empty
re-tries = 28 sessions. Started 2026-05-28 01:08 UTC. Dry-run
estimate ~$36 mean / ~$38 worst-case envelope. At time of writing
**COMPLETE.** 17 succeeded, 11 failed (the empty stubs, as predicted),
0 cap truncation — all 17 formerly-capped sessions now at full
subagent fan-out (68/68, 59/59, 58/58, … 21/21). Real spend
**$23.73** (under the ~$36 estimate) across 608 calls: parent 17
calls $5.44, subagent 591 calls $18.29 — captured by the new
cost-audit log at
``data/logs/backfill-cost-log-20260528T020248Z.json``. The 11 empty
sessions re-failed in this run as expected (python loaded its code
before the preflight landed); they now carry permanent-skip markers
so future runs auto-skip them. Net archive state: 643 sessions on
v1.3 (626 from the 2026-05-26 run + 17 here), 11 permanently-skipped
empty stubs, 0 remaining on v1.2.

**Tests:** 289 → 301 (+12 across permanent-marker helper, finder
marker-honouring, instrumented-wrapper cost recording on
full/missing/partial usage_metadata, schema forwarding, raise-
after-record on response.text=None, ``_summarise_cost_records``
phase aggregation + lower-bound flagging).

**Merged + pushed.** All today's work landed on ``main`` via merge
commit ``63aaa95`` (toolkit), squashing the three feature commits:
- `5660265` feat(backfill): preflight skip on empty transcripts + permanent-skip marker
- `f80094b` fix(config): bump MAX_SUBAGENT_SUMMARIES 20 → 70
- `172a1a7` feat(backfill): per-call cost-audit log (backport from validator)

**R2 / Phase 0e diagnosis (2026-05-28).** Investigated the offsite-
backup blocker. Credentials present + correct on amd-tower + zbook
(``RCLONE_CONFIG_R2ARCHIVES_ACCESS_KEY_ID`` + ``_SECRET_ACCESS_KEY``);
``rclone.conf`` remote ``[r2archives]`` fully configured (type=s3,
provider=Cloudflare, env_auth=true, endpoint
``059b3362f2a505d81c10b3d7b1800f86.r2.cloudflarestorage.com``).
Bucket is ``pa-cc-archives`` (three Object-Read&Write tokens, one per
machine). Initial write 403 was the **rclone+R2 bucket-preflight
gotcha** — scoped tokens reject HEAD/CreateBucket; ``--s3-no-check-
bucket`` fixes it. **Phase 0e then COMPLETED same session:**
``scripts/push-archives-to-r2.sh`` built (``rclone copy``, additive /
never-deletes, ``--s3-no-check-bucket`` + ``--s3-disable-checksum``,
``RCLONE_BIN`` override, rclone-version guard), wired into
``daily-sync.sh`` after the convergence passes and gated to a single
push owner (``AMD-tower-ubuntu``). The ``501 NotImplemented`` turned
out to be **rclone-version**, not flag-related: the distro rclone
``v1.60.1`` 501s intermittently on R2 PutObject (a first push landed
only ~964/4654 before exhausting retries). Upgrading to ``v1.74.2``
(official installer, sudo) fixed it cleanly — the resumed push
completed with **0 errors**; ``rclone check --size-only --one-way`` =
**0 differences, 4,654/4,654 matching, 3.342 GiB**. Single-owner gate
means zbook + rpi-server need no rclone upgrade. (Pre-existing
``_legacy/`` dir in the bucket left untouched.) Storage ~$0.05/mo,
zero egress. **Goal (a) closed end-to-end.**

**Cross-machine sync reconciliation (2026-05-28).** Confirming "are we
in sync across amd-tower / zbook / rpi-server" surfaced a real gap on
two axes. (1) **Archives:** the v1.3 upgrade wrote to local
``~/cc-archives`` (``DEFAULT_ARCHIVE_ROOT``), but the canonical
rpi-shares store + zbook's mirror were stranded at v1.2 — root cause
``daily-sync.sh``'s ``rsync -a --ignore-existing`` is append-only and
cannot propagate in-place meta rewrites. Fixed by (a) a one-time
scoped ``rsync -rt --update`` of metas amd-tower→canonical (675 files)
and canonical→zbook (1307 files; zbook also lacked the v2-backups), and
(b) **a permanent design fix** — ``daily-sync.sh`` cc-archives sync is
now a 3-pass convergence: append-only UP (unchanged) + metadata UP
``--update`` + metadata DOWN ``--update``, scoped to
``session.meta.json`` + ``CATALOG.json``, newest-mtime-wins (commit
``f6929d6``). Future re-summarisation runs now self-heal across
machines via daily-sync; no manual cross-machine push needed. (2)
**Git:** zbook was behind on all three repos (toolkit ~6 days stale at
``cdc7c65``); rpi-server's PA had benign ``M data`` stale-submodule-
pointer drift (0 local commits). Both pulled clean to PA ``f6929d6``,
pa-data ``ec4dd42``, toolkit ``63aaa95`` (zbook; rpi-server has no
toolkit repo by design). **All three machines now fully convergent on
git + archives.**

**Out of scope (deferred / non-issues):**
- The 11 known-empty sessions could be **deleted** from the archive
  entirely rather than marked — they have no salvageable content.
  Left in place for now because preserving them is the safer default
  (a future archaeologist of the archive can confirm "these were
  empty all along" via the meta).
- Per-subagent flat cost constant (``PER_SUBAGENT_COST_USD = 0.05``)
  is now known to over-estimate by ~20% (measured ~$0.04 actual on
  the 2026-05-28 run). Updating to 0.04 would improve dry-run
  accuracy but the 20% buffer is also a reasonable safety margin
  against future model-price changes. Leave at 0.05.



### 2026-05-25 (Mon, afternoon) — Session-summary v3 tooling finalisation: F5 closed, 15 audit follow-ups landed, --upgrade-to-v13 flag, parent-path schema

PA-infrastructure session that closed out the v3 session-summary
tooling end-to-end. Built on yesterday's wire-up (commit `5e4266a`)
by resolving the residual follow-up backlog. Five workstreams
delivered + smoke-tested + pushed to ``main`` on both
``cc-session-toolkit`` and ``pa-data``.

**F5 resolved (commit `8e44f1a`, pushed earlier).** The 1-in-25
subagent-summary failure on b089991e (subagent `ab92875bababd2549`,
log line ``data/logs/auto-metadata.log:835`` at 12:37:43 on
2026-05-24, "Expecting ',' delimiter line 3 col 1 char 1144") was
diagnosed as stochastic JSON-format glitch under
``response_mime_type=application/json`` (which instructs JSON output
but does NOT enforce a schema). Reproduced once (~$0.05) — same
input, clean output — confirming non-determinism at the model layer.
Fix: ``_call_gemini_once`` / ``_call_gemini_with_retry`` gain
optional ``response_schema=`` parameter; new
``SUBAGENT_NARRATIVE_SCHEMA`` constant (single-field
``{"narrative": str}``) passed by ``generate_subagent_summaries`` on
every call. Parse-failure log lines on both parent and subagent
paths widened ``raw[:200]`` / ``raw[:300]`` → ``raw[:8192]`` with
``raw_len=`` prefix so future failures are fully diagnosable.

**Audit follow-ups (15 items, 4 background agents in parallel).**
The deferred follow-up list at
``data/experiments/session-summary-v3-bakeoff-2026-05-24/audit-followups-2026-05-24.md``
was cleared in a single afternoon via 4 parallel agents working in
independent worktrees:

- **A — archive.py + scripts (5 items):** ``MAX_SUBAGENT_SUMMARIES``
  cost-control cap on subagent fan-out (default 20, in
  ``config.py``); subagent-aware ``_estimate_total_cost`` reporting
  parent + subagent costs separately; silent-all-failures print path
  (``0 / N succeeded`` message when ``subagent_summaries`` is empty);
  redundant ``except (TypeError, ValueError, Exception)`` cleanup;
  atomic session.meta.json overwrite via ``.json.tmp`` + ``os.replace``
  in backfill. Commits ``e85fe9b`` + ``f7c52dc``.
- **B — prompts (5 items):** ``user_quote`` "verbatim or near-verbatim"
  loophole closed (ellipsis-only trimming permitted); anti-satisficing
  rule 9 softened to "no equal-grain duplication" (pointer-style
  ``see phases[i]`` cross-references now licensed); surviving 60-word
  / 25-word floors dropped (gradient philosophy now consistent
  parent-wide); phases-emission threshold tension resolved
  (qualitative test dominates; size threshold becomes heuristic
  only); slash-command skill-markdown injection guidance added.
  Commit ``c0247e1``.
- **C — tests (4 items):** new ``TestGenerateSubagentSummaries``
  class (5 sub-cases: empty / missing-transcript / Gemini-fail /
  non-string-narrative / multi-subagent accumulation); v3 schema
  parser test gains nested ``three_ps`` content assertions;
  non-object-root parser test parametrised over list / string /
  number / boolean; ``test_subagent_archive.py`` module docstring
  bumped to "v1.3 schema". Commit ``75c7ee3``. +8 tests.
- **D — experiments scripts (2 items, in pa-data):**
  ``validate-production-path.py`` gains module-level cost-trail
  accumulator + instrumented wrapper around ``_call_gemini_once``;
  per-target ``_cost_audit`` blocks persisted into v3 overlays plus
  an aggregate ``validate-production-path-cost-log.json`` next to
  the script. ``run-bakeoff.py`` no longer silently records $0 when
  ``usage_metadata`` is missing — WARN + null cost + final-summary
  lower-bound annotation. Commit ``bbe2a7b`` on pa-data.

**``--upgrade-to-v13`` backfill flag (commit `d030a45`).** Extends
``scripts/backfill-session-metadata.py`` with a second finder
(``find_sessions_needing_v13_upgrade``) that partitions the archive
into disjoint populations: empty-marker sessions → default backfill
(unchanged); pre-v1.3 populated sessions → upgrade path; already-v1.3
sessions → skipped. Before each upgrade, the original
``session.meta.json`` is preserved side-by-side at
``session.meta.v2-backup.json`` via idempotent ``backup_pre_v13_meta``
(never overwrites a prior backup). 8 new unit tests covering finder
partition + backup idempotency. Smoke-tested on the live archive:
637 candidate sessions across 12 project trees; dry-run cost
estimate (sample-of-20 distillation) reports mean ~$0.11/session
parent, plus 2,269 subagent calls across 303 sessions × $0.05 =
~$113.45 subagent cost, total ~$216 mean / ~$347 worst-case
envelope.

**Parent-path ``PARENT_METADATA_SCHEMA`` (commit `e30ad98`).**
Complement to today's subagent-side fix at `8e44f1a`. The v3 parent
schema encodes the prompt's documented field structure: top-level
``title`` / ``purpose`` / ``tags`` / ``three_ps`` / ``phases`` /
``decisions`` / ``key_exchanges`` all required (lenient on content —
no ``minItems`` so empty arrays satisfy — strict on presence so
downstream can iterate without isinstance guards). Nested
required-field sets per the prompt's per-section field contracts:
``three_ps`` requires all three Three Ps sub-fields; ``phases[]``
items require ``title``, ``summary``, ``approx_start``;
``decisions[]`` items require ``question``, ``options_considered``
(array of strings, not nested objects per L587 of the prompt),
``chosen``, ``rationale``; ``key_exchanges[]`` items require
``context``, ``user_quote``, ``assistant_response_paraphrase``.
``chosen`` deliberately a plain string (not enum over
``options_considered``) — the prompt explicitly licenses synthesis
("both A and B"). 5 new schema tests. Smoke-tested end-to-end (1
Gemini Flex call, ~$0.10) against the 2026-04-28 EOD recap session:
clean output, all 7 required top-level fields + all three Three Ps
sub-fields present, content quality preserved (2 phases, 2
decisions, 2 key_exchanges; phases-threshold prompt fix from
Workstream B now correctly identifies the multi-thread Tue/Wed
content where yesterday's pre-fix run had emitted 0 phases).

**Tests:** 264 → 289 (+25 across all workstreams: 4 F5 + 8 audit-C
+ 8 upgrade-to-v13 + 5 parent-schema).

**Pushed:**
- ``cc-session-toolkit`` origin/main = ``c615f13`` (12 commits this
  session: F5, prompts, archive+scripts audit, tests audit,
  upgrade-to-v13 feature, parent-schema feature, + 5 merge commits)
- ``pa-data`` origin/main includes the audit-experiments merge
  ``b43c158`` (via the auto-sync process)

**Out of scope (deliberately deferred to future sessions):**
- The 637-session v1.3 upgrade run itself (~$216 mean spend; flag
  is shipped; running is a separate decision). 2026-05-26 update:
  approved and launched in a background process — see the F-block
  for status.
- Smoke-testing the new ``MAX_SUBAGENT_SUMMARIES`` cap path
  (intentionally never triggered in normal operation; only fires
  when a session has >20 subagents).
- Parent-path ``response_schema`` interaction with the v3 prompt's
  ``approx_start`` field — Gemini will reject if the model omits it
  on a phase item; existing exception handler collapses to None
  graceful-degradation (auto-metadata becomes "Auto-metadata
  unavailable" and the session can be re-backfilled). No production
  failures observed yet; monitor on the upgrade run.

- Toolkit commit `c615f13` (merge of feat/parent-response-schema)
- Toolkit feature: `e30ad98` (parent schema), `d030a45` (upgrade
  flag), `f7c52dc` + `e85fe9b` (archive audit-followups),
  `c0247e1` (prompts), `75c7ee3` (tests), `8e44f1a` (F5 fix)
- Data submodule commit (pa-data): `b43c158`
  (audit-experiments merge); also the v3 wire-up's bake-off
  experiments dir lives at
  ``data/experiments/session-summary-v3-bakeoff-2026-05-24/`` as
  before.



### 2026-05-24 (Sun, evening) — Workstream G Phase 1: legacy run → user-mandated clean rebuild → QA agent → Stream A code hygiene

Heavy ~12 h workstream-G session arc spanning v2 Phase 1 of the
corpus-style-analyser plan. Started with the deterministic measurement
extensions per plan §2 (six new metrics, three TBD gate targets,
regression-anchor framework, `attested-concentrated` fifth status), all
landed cleanly against the legacy `pdftotext -layout` corpus.
Regression vs run-1 anchors showed 5 of 13 passing — most failures
explainable by intentional aggressive ref-stripping per plan §2.1, but
the framing was over-confident. Shawn's "I'm having a little trouble
interpreting your regressions" was a polite "I don't believe you fully";
the redraft re-decomposed into solid / hypothesised-but-unverified / not
known, and listed four diagnostic checks. Shawn asked for all four in
parallel and pushed back further with *"I think it goes deeper than
[bibliography]"*.

Four parallel diagnostic agents (boundary-check, `Center` grep, passive
spaCy validation, announcement-colon precision) confirmed the deeper
read. Three of four found new failure modes the audit hadn't covered:
PyMuPDF / pdfplumber over-promoting title-case lines to `## H2` (562
H2s on ENPYIZQF, 556 on 592YDKFM; mastheads + author surnames + place
names treated as section headings); page-header bands (`5/22/25, 3:13
PM   Traces in a Lost Landscape:`) surviving as 26 % of 5INAFTVT's
announcement-colon hits; spaCy parse hallucinations on
column-interleaved sentences (one sample literally tagged a full-stop
as `nsubjpass`); CI2Q7VXD's 338-word body-prose loss to the
author-year-density fallback hitting the right column of a two-column
PDF and lopping off the body left column. The "affiliations in page
headers" hypothesis for the `centre/center` US-spelling deficit was
mechanistically wrong but directionally right (the 7 discarded US
tokens were all in reference-list publisher names + cited titles, not
body prose; v2 was correctly removing non-body content).

Shawn's call: "let's first spend some effort" on real PDF extraction.
Built `scripts/style-analyser/extract_corpus.py` reusing PyMuPDF +
pdfplumber from `~/Code/llm-reproducibility/extraction-system/scripts/
pdf_processing/` (imported in place — no vendoring per the scoping
decision). First clean extraction had 13/18 needs-review; iterated four
times — adding paragraph-prefix detector for `References Akata,` style,
bracketed-numbered detector for `[1] McNutt …` style, chapter-slicing
for SP2R6FF9 (chapter 8 of an edited volume), and a tighter tail-
position guard — until 5/18 needs-review. Spawned a QA agent over the
clean extractions; it found 5 material issues that drove five
post-extraction passes (running-header strip, fragment-H2 drop,
author-affiliation tail strip, end-marker + author-year density
fallback, per-key body/refs split override for JFA-style bare-year
refs). Final: 16/18 PASS, 2/18 cosmetic flags.

Re-ran Phase 1 on the clean corpus. Mean SL dropped from 23.93 to
**21.45** because PyMuPDF preserves paragraph boundaries that
pdftotext dissolved (more, shorter, real sentences). Paragraph stats
went from obvious garbage (mean 162 words) to plausible (median 17,
mean 30). Announcement colons dropped 31 % (1.884 → 1.605/1k) because
page-header artefacts gone. Body word count dropped 5 % vs v1-dirty
and 10 % vs run-1 — the lost tokens were mastheads, affiliations, and
reference fragments, not body prose. **Run-1 anchors retired as a
regression target.**

Two `feedback` memories saved (whilst/amongst deliberate avoidance;
em-dash post-2023 reduction). Both now load on session-start and
should shape the eventual v2 style guide (whilst published as
`absent-when-searched` with deliberate-authorial-preference editor's
note; em-dash density should be date-binned, not aggregated).

`/audit` over the two new scripts found 5 critical + 10 medium issues.
Stream A patched all of them, including a silent zip-pair logic bug
in `strip_references` author-year-density fallback (`zip(ay_matches[-2::-1],
ay_matches[::-1][1:])` paired each match with itself; pre-fix in legacy
mode, CI2Q7VXD recovered 148 body words after the fix). The Unicode
tokeniser switch (`[^\W\d_]` instead of `[A-Za-z]`) added 1,867 corpus
words — `Sobotková`, `Çatalhöyük`, `Müller` no longer mis-tokenised.
The v2.1 agent file's Appendix E gate values were patched to the
post-Stream-A clean-corpus targets.

- PA commits: `834a5c3` `feat(style-analyser): add v2 Phase 1 pipeline + clean-corpus extractor` (1,474 lines: `extract_corpus.py` + `phase1_pipeline.py` with all Stream A fixes); `ad32534` `feat(style-analyser): add Phase 1 validation scripts` (375 lines: `validate_passive_detection.py` + `validate_announce_colon.py`)
- Data submodule artefacts (auto-synced during session): `notes/style-guides/academic/v2-phase1-audit-2026-05-23.md` (legacy audit); `notes/style-guides/academic/v2-phase1-audit-clean-2026-05-24.md` (clean-corpus + Stream A audit, 11 sections); `style-corpus/extracted/<key>/` for 18 papers; `style-corpus/corpus-manifest.json`; `style-corpus/phase1-results-clean.json` (the new ground-truth measurement file); `memories/memories.jsonl` (+2 feedback entries on whilst/amongst + em-dash); `memories/tag-vocabulary.txt` (+2 tags `lexical-preference`, `llm-prose-tics`)
- Outside-repo artefact: `~/.claude/agents/corpus-style-analyser-v2.md` patched (Appendix E refreshed, Phase 2 instructions pointed at clean corpus, deps list expanded, cross-version-diff section now documents v1 → v2.0 → v2.1 trajectory)
- Out of scope (deferred per Shawn): Phase 2 Biber relayout; Phase 3 Kumar CV re-derivation on clean corpus; Phase 4 Panickssery exemplars (API-gated); Phase 5 Mahalanobis evaluator; reconciliation with prior conscious style guides (already tracked in workstream G as separate human-in-the-loop session)
- Verification: clean extraction 18/18 OK + 2 cosmetic flags; Phase 1 clean re-run n_words 127,720 / n_sentences 5,832 / mean SL 21.45; legacy mode CI2Q7VXD body recovers 148 words after zip-bug fix

### 2026-05-23 (Sat, afternoon) — Tokeniser-aware session budget + workstream-F char/4 calibration fix

Background PA-infra session sandwiched between this morning's workstream
H Zotero closeout and ongoing workstreams G + H sessions elsewhere.
Goal: pick up two "quick" items from the post-Phase-0 cleanup register
— `pg_trgm` extension closure and Gemini list-price re-verification —
then a "mid" item. Both quick items closed in single touches (`pg_trgm`
re-verified live: extension + index already present, continuity entries
at L1047 + L1159 stale, marked `[x] 2026-05-23` with off-by-four
line-number correction; Gemini 3.5 Flash pricing confirmed by Shawn at
3× the 3-Flash-Preview rate). The mid item — pre-v2 backup cleanup C —
got pre-empted when the F3 quality-assessment agent surfaced a
1-in-111-output failure mode that turned out to have a fixable root
cause: the `SESSION_TOKEN_BUDGET = 850_000` cap in
`cc_session_toolkit.transcript_text` is enforced via a
`SESSION_CHAR_BUDGET = SESSION_TOKEN_BUDGET * 4` (chars/4 heuristic),
but real Gemini tokenisation on code-heavy / tool-output-heavy content
averages ~2.79 chars/token, eating the 15 % safety margin between the
budget and Gemini's 1 M hard ceiling. Empirically on session b089991e:
3,273,001 chars distilled, toolkit-reported 818,250 tokens, Gemini's
real `count_tokens` reported 1,174,153 — a 1.43× undercount that
produced the observed 400 INVALID_ARGUMENT.

Fix shape: tokeniser-as-authority with self-calibrating fallback.
Method 1 (`client.models.count_tokens`) preferred over Method 2
(`LocalTokenizer`) — same authoritative tokeniser, no sentencepiece +
protobuf chain, no offline vocab-drift risk, latency irrelevant against
the ~5 s `generate_content` call. New helper
`extract_transcript_text_for_gemini` does a two-pass dance: heuristic
first cut, then real-tokeniser verify, re-truncate with observed
chars-per-token × 0.92 if over budget. `_apply_session_budget`
refactored to accept both `budget_tokens` and `char_budget` so the
second pass can apply the calibrated char ceiling without re-reading
the transcript. None-default resolution preserves existing
monkey-patching test-pattern. 8 new tests cover under/over-budget paths,
empty-session short-circuit, exception graceful degrade, non-int
return, custom budget narrowing, observed-ratio calibration formula.
Toolkit suite 249 → 257 passing.

Production wiring in `archive.generate_auto_metadata`: Gemini client
constructed up-front, `_count_tokens` closure passed to the helper, log
header now reports Gemini's authoritative count (not the heuristic) for
every session. `int()` coercion + try/except in both helper and
archive.py make the path resilient to count_tokens network blips or
non-int returns — failure modes fall back to the first-pass text, no
worse than the pre-tokeniser-aware code.

Smoke-test on b089991e: 1,174,153 → 729,971 tokens (under 850 K budget,
+318 K headroom under 1 M ceiling). Middle-truncation marker correctly
present in second-pass output. Opportunistic sweep: docstrings +
comments in toolkit (`pyproject.toml`, `transcript_text.py`,
`archive.py`, `backfill-session-metadata.py`, `tests/...`) and PA
(`scripts/bake-off-metadata.py`, `skills/audit-config/SKILL.md`,
`data/notes/grimoire/pre-launch-experiment-audit.md`) updated from
"Gemini 3 Flash Preview" to "Gemini 3.5 Flash" where they describe the
current production model. Historical / provenance content
(experiment artefacts, prior session-log entries) preserved unchanged.

- Toolkit commit (cc-session-toolkit): `917ac13`
  `feat(transcript): tokeniser-aware session budget` (5 files, +439 / -41)
- Data submodule commit (pa-data): `a0363c3`
  `docs(grimoire): update model name to gemini-3.5-flash`
- PA commit: this entry + closure ticks
- Toolkit files: `src/cc_session_toolkit/transcript_text.py` (new
  helper, `_load_fragments` extraction, parameterised
  `_apply_session_budget`, `TOKENISER_SECOND_PASS_MARGIN` constant),
  `src/cc_session_toolkit/archive.py` (client-up-front, `_count_tokens`
  closure, int-coerced log header, graceful degrade),
  `tests/test_transcript_text.py` (`TestExtractTranscriptTextForGemini`
  class, 8 tests), `pyproject.toml` + `scripts/backfill-session-metadata.py`
  (model-name comment sweep).
- PA files: `planning/continuity.md` (this entry + F3 cost revision +
  workstream-F calibration-fix tick + GA-rename watch note + pg_trgm
  closures earlier in session), `scripts/bake-off-metadata.py`
  (`GEMINI_MODEL = "gemini-3.5-flash"` + price comment with re-verify
  caveat), `skills/audit-config/SKILL.md` (model example update).
- Verification: full toolkit test suite 257 passing (249 baseline + 8
  new). PA venv reinstalled with editable toolkit. Live smoke-test
  against `~/cc-archives/map-reader-llm/vlm-burial-mound-detection/
  2026-04-16T05-56_b089991e/session.jsonl.gz` confirms calibrated
  truncation behaves as designed.
- Out of scope: backport `failure_type` axis to `lit-scout-verifier` +
  `data-profile-verifier` (workstream H, running elsewhere); style-guide
  v2 phase 1 (workstream G, running elsewhere); pre-v2 backup cleanup C
  (deferred — gate opened today but pre-empted by calibration work).

### 2026-05-24 (Sun, afternoon) — Session-summary v3 wire-up: schema 1.2 → 1.3 with phases, decisions, key_exchanges, subagent summaries

PA-infrastructure session that delivered the v3 session-summary schema
all the way from co-design to production-deployed + backfilled. Builds
on yesterday's tokeniser-aware session budget (workstream F, commit
`917ac13`) by re-framing the session archive's purpose: not a memory-
feed primitive, but an open-science / RDA-IG transparency artefact for
methodology audit and practice-sharing. Memory operational layer
(continuity + scratchpad + memories.jsonl + recall hook) is already
doing the daily-driver retrieval work; session archives' job is now to
make a thoughtful external reader (Brian, a P26 audience member, a
paper-replication reader, or future-Claude looking up a named past
session) able to reconstruct methodology from the JSON alone.

**Schema delta (1.2 → 1.3, additive / backwards-compatible).**
``auto_generated`` gains optional ``phases[]``, ``decisions[]``,
``key_exchanges[]`` arrays. Top-level ``subagent_summaries[]`` added
for lightweight per-subagent narratives. Length scales with input
transcript size via a √(input_tokens) curve with density-driven
±30% adjustment instead of v2's fixed 40-80-word ceilings. LLM-first
audience framing in the v3 parent prompt: tokens are cheap,
reconstructability is expensive — capture more, not less.

**Co-design + empirical-validation arc.** Three rounds before
production wire-up: (1) initial bake-off on the b93ed93b RAC-TRAC
session (6 h / 273 tool calls / 4 subagents) confirmed v3 produces
~6× more summary text at ~1.7× the cost of v2, with cost-per-word
3.4× cheaper — and surfaced an unexpected win where v3 captured a
slide-split decision (B1a/B1b, B3a/B3b, B13a/B13b) that v2 had
entirely missed. (2) Mini bake-off across short / medium-single-
thread / no-subagent sessions confirmed v3 behaves correctly at the
floor (67-word output for a 7-turn micro-session, no padding) and on
simple shapes (phases stays empty when warranted), and surfaced TWO
critical bugs: a 1-in-3 trailing-brace JSON parse failure under v3
prompts, and an 80-word floor breached on all three sessions.
(3) Production-path validation on two specific sessions via the
post-wire-up archive.py code path surfaced two MORE defects masked
by the bake-off runner's richer config: production was missing
``response_mime_type=application/json`` and capped at
``max_output_tokens=1024`` (too tight for v3 output).

**Wire-up.** ``cc_session_toolkit/prompts/auto_metadata.md`` replaced
with v3 parent prompt (38 KB, was 26 KB v2); new
``auto_metadata_subagent.md`` (7 KB) for lightweight per-subagent
narratives. New function ``generate_subagent_summaries`` (~163 lines)
in ``archive.py`` iterates a session's subagents, distils each via the
tokeniser-calibrated extractor, calls Gemini Flex, parses with the
robust JSON parser. ``archive_session`` calls it after subagent
archival when auto-metadata is on; result threads into
``create_session_metadata`` as new ``subagent_summaries`` parameter.
``generate_auto_metadata`` normalises the new v3 fields to ``[]``
when absent. ``_parse_metadata_response_json`` refactored to use
``json.JSONDecoder().raw_decode()`` plus leading-prose skip; tolerates
trailing brace artefacts. ``response_mime_type=application/json``
added to ``_call_gemini_once`` to eliminate the failure class at
source. ``AUTO_METADATA_MAX_OUTPUT_TOKENS`` raised 1024 → 8192.
``backfill-session-metadata.py`` extended to write the v3 fields +
subagent_summaries + bump schema_version (from
``SCHEMA_VERSION`` constant, not a hardcoded literal).

**Audit + fixes.** ``/audit`` across 4 parallel subagents over all
new + modified code surfaced ~25 findings. Production-correctness
criticals fixed inline before commit: duration_seconds None-trap in
subagent header formatting, ``decisions[].chosen`` synthesis-vs-strict-
match schema contradiction, subagent prompt 60-word floor (contradicted
the parent's no-floor philosophy adopted yesterday), ``.env`` parser
quote-strip in experiment scripts, auto_generated fallback dict
missing v3 fields, dead-code constant removed, ``SCHEMA_VERSION``
imported in backfill not hardcoded, stale ``$0.027/session`` cost
figures updated to ``$0.10/session``. ~12 deferred follow-ups tracked
at ``data/experiments/session-summary-v3-bakeoff-2026-05-24/audit-followups-2026-05-24.md``
(cost-control hardening, prompt refinements, test-coverage gaps;
all non-blocking).

**Production validation + backfill.** Production-path validator
re-summarised the b93ed93b RAC-TRAC session + a 30-turn personal-
assistant recap session via the post-wire-up code path; both
produced clean v3 output (RAC-TRAC: 4 phases, 3 decisions, 2
key_exchanges, 4/4 subagent summaries 112-169 words each; recap: 0
phases, 2 decisions, 2 key_exchanges, 0 subagent_summaries — single-
thread session correctly skipped phases). Both promoted from v2 to
v3 canonical with v2 backed up to ``session.meta.v2-backup.json``
side-by-side for comparison. Backfill run on 33 historical sessions
that had never had auto-metadata (``purpose == "Auto-metadata
unavailable"``); **33/33 succeeded, 0 failures**. Most sessions
emit 3-5 phases + 2-4 decisions + 2-5 key_exchanges; the handful of
single-thread sessions correctly emit 0 phases. Notable: session
b089991e (map-reader 1.83M-output-token session that previously hit
Gemini's 1M input ceiling under v2's chars/4 heuristic) **archived
cleanly + generated 24/25 subagent summaries** — tokeniser-calibrated
truncation shipped yesterday did its job in production. Dry-run
estimate was ~$5.61 mean / ~$9.53 p90; real spend not surfaced by
the script but within budget.

**Tests:** 264 passing (257 baseline + 7 new). New tests cover the
robust JSON parser (trailing-brace tolerance, leading-prose skip, v3
schema shape, non-object root rejection), schema-version 1.3 bump,
and ``subagent_summaries`` field plumbing through
``create_session_metadata``.

- Toolkit commit (cc-session-toolkit): ``902b2eb``
  ``feat(archive): v1.3 schema — phases, decisions, key_exchanges, subagent summaries``
  (7 files, +1264 / -303)
- Data submodule commit (pa-data): ``90e87d1``
  ``experiments: v3 session-summary bake-off (2026-05-24)``
  (20 new files; v3 prompts, runners, outputs, comparison notes,
  audit-follow-ups doc)
- PA commit: this entry + the submodule pointer move
- PA-side experiments dir: in the data submodule at
  ``data/experiments/session-summary-v3-bakeoff-2026-05-24/``.
- Out of scope (deliberately deferred):
  - Cost-control cap on subagent fan-out
  - Prompt refinement: "verbatim or near-verbatim" loophole on
    user_quote, anti-satisficing rule 9 vs worked-example tension,
    surviving 60-word floor on phases[].summary + 25-word floor on
    purpose, slash-command skill-injection guidance, phases emission
    threshold tension
  - Test-coverage gaps: ``generate_subagent_summaries`` has no unit
    tests (covered indirectly by the production-path validator);
    ``test_parse_response_handles_v3_schema_shape`` doesn't assert
    nested three_ps content; non-object-root test only covers list
    case
  - F3 follow-up: ``--upgrade-to-v13`` flag for backfill so existing
    v2-schema sessions can be re-summarised on v3 schema. Deferred
    pending user inspection of the 33 fresh-backfilled sessions and
    the 2 promoted production-path validation sessions.



Closed out two remaining workstream-H items and recorded the calibration
decision for the closed-loop pairs going forward. Backported the
`severity × failure_type` two-axis rubric (originating in
`prior-art-scout-verifier` 2026-05-22) to both `lit-scout-verifier`
and `data-profile-verifier`: severity paragraphs promoted to dual-axis
sections, JSONL schema gains `failure_type` field, example claims
updated to show the canonical 2026-05-22 calibration cases (CrossRef
family/given swap → `encoding_artefact`; DOI 404 → `confabulation`;
pandas default-kwarg mismatch → `encoding_artefact` with
`documentation_defect` status). Drivers and proposers gracefully
ignore the new field (verified by grep before launching). Then smoke-
tested `/prior-art-scout-iterate` on "Open-source LLM provenance
toolkits (RDA-aligned)" — the last unconverted pair's first real run:
12 candidates, 64 claims, PASS in 1 iteration (63 PASS / 1
UNVERIFIABLE — SSRN URL behind Cloudflare anti-bot, paper itself
confirmed via OpenAlex DOI lookup / 0 FAIL / 0 PARTIAL / 0
documentation_defect). Closed-loop plumbing confirmed end-to-end;
`failure_type` field wire-correct on all 64 verifier rows.
**`url_resolves` / `doi_resolves` row-removal path NOT exercised**
(the RDA-provenance domain produced clean discovery; the proposer
queried live APIs at scout-time rather than guessing from memory —
same pattern as the 2026-05-22 lit-scout smoke on Bayesian
archaeology).

**Calibration decision (2026-05-24):** two consecutive iterate-loop
runs have now terminated PASS in 1 iteration without exercising the
row-removal path. Rather than spinning up synthetic-FAIL tests to
validate iterate-mode plumbing — which would optimise for imagined
errors over real ones — the new discipline is to use the iterate
loops self-consciously in real work and accumulate calibration data
from genuine failures. After ~6 months of real usage, revisit the
verifier evals: if no real errors, consider QA → QI shift; if real
errors, calibrate against them; if rubrics are right and these
queries just didn't trigger failure, accept that. Synthetic-FAIL
test, severity-rubric calibration, and the original "speculative-
domain" smoke-test suggestion all marked `[~]` deferred with a
six-month-and-a-handful-of-real-FAILs un-defer trigger. Scratchpad
entry 2026-05-24 captures the bias to resist.

Two substantive RDA-adoption findings surfaced from the prior-art
smoke (independent of test value): **Flowcept + PROV-AGENT** (ORNL,
MIT, IEEE e-Science 2025; arXiv 2508.02866) as the closest published
peer to the Three Ps framework with a directly-reusable PROV-O
extension; and the **rocrate Python library** (Apache-2.0, v0.15.0)
as the mature RO-Crate serialisation layer with native ORCID / DOI
/ DataCite support. Both captured as 2026-05-24 inbox follow-ups
with cross-references to the experiment archive. **Three further
P-V-pair scoping items** added to the inbox over the session as
ideas surfaced: (a) `file-organiser` pair (expanded from the
initial archive-only framing to cover broader crufty-repo cleanup
across all infra + research repos), (b) FAIR4RS uplift pair (repo
+ code documentation + research-software metadata for legibility
/ reusability), and (c) `corpus-style-analyser` verifier (slop
detection grounded in published literature + style-match
confirmation against the target voice — companion to the
workstream-G v2 build). All three deferred to dedicated scoping
sessions; all three architectured to mirror the three existing
iterate loops.

- `agents/lit-scout-verifier.md`: 4 edits — severity section
  expanded to dual-axis, schema row added, example claims updated,
  emission rule added.
- `agents/data-profile-verifier.md`: 2 edits — severity section
  retitled and expanded to "Severity + failure_type axes", JSONL
  schema gains `failure_type` field.
- `data/experiments/prior-art-scout-iterate-smoke-2026-05-23/` —
  new experiment archive (4 files: draft.md, claims.jsonl,
  report.md, corrections.jsonl) plus README documenting
  trajectory, findings, calibration decision, and substantive
  follow-ups.
- `tasks/inbox.md`: **5 new items** — two RDA-adoption follow-ups
  (Flowcept+PROV-AGENT; rocrate Python library) and three P-V
  pair scoping items (file-organiser; FAIR4RS uplift; corpus-style-
  analyser verifier).
- `data/scratchpad.md`: 1 new entry (use iterate loops self-
  consciously; calibrate from real errors, not synthetic ones).
- `wiki/user-observations.md`: candidates 22, 23, 24 from
  2026-05-22 late-evening session accepted.
- Workspace originally at
  `/tmp/prior-art-scout-iterate-20260523-222940/` (archived in
  full to `data/experiments/`); will be cleared with normal /tmp
  reaping.
- Commits: `pa-data` `1530389` (smoke-test archive + scratchpad +
  initial RDA + archive inbox items), `ef54026` (expand archive
  item → file-organiser + add FAIR4RS), `75b3afd` (add corpus-
  style-analyser verifier scoping); `personal-assistant`
  `08b725b` (verifier failure_type backport), `1516b63`
  (continuity + wiki + submodule bump), `0830bcc` and `998d9dd`
  (subsequent submodule bumps for the second + third inbox-item
  rounds).

### 2026-05-23 (Sat) — Zotero collection writer: workstream-H follow-ups + /audit closure

Close-out session for the lit-scout Zotero staging-import workstream H.
Landed the three follow-ups carried over from 2026-05-22 (sync-to-zotero
env-var rename to `ZOTERO_API_KEY_PAPER_B`, manifest `items_skipped`
dedup-on-merge, DOI-first proposer dedup via new `find_by_doi` in
`scripts/zotero.py` with `agents/lit-scout.md` Phase 5 wired to use it).
Then ran `/audit` on the session diffs per Shawn's request — surfaced
3 Mediums and 4 Lows on workstream-H code, all addressed in-session.
Most consequential finding: `find_by_doi`'s SQL did `LOWER(doi) = LOWER(?)`
exact match, which would have silently missed Zotero items stored with
`https://doi.org/…` or `doi:…` prefixes — partially undermining the 5/5
catch advantage the function was added for. Fix: chained SQL `REPLACE`
on both sides plus a Python `_normalise_doi()` helper covering the five
common URL/scheme prefixes (`https://`, `http://`, `https://dx.`,
`http://dx.`, `doi:`). Closed with a reference-doc update covering the
full target-suffixed env-var convention, all three env vars in a single
table, and the bash hyphen-trap warning that cost a key revocation
2026-05-22. **Zotero collection writer is now closed.**

- Commits (5):
  - `e2d12ac` fix(scripts): rename sync-to-zotero key to PAPER_B
  - `4f50ce9` feat(zotero): DOI-first dedup in lit-scout proposer
  - `ae3c141` fix(zotero-import): manifest dedup + audit fixes
  - `af3209a` docs(wiki): accept user-observation candidates 28-31
  - `190daf5` docs: close workstream-H Zotero writer TODOs
- Workstream H ticks: items at continuity.md L471 (`items_skipped`
  dedup), L482 (DOI-based proposer dedup), L492 (zotero-reference.md
  update) all `[x] 2026-05-23`. Session-log summary block updated to
  reflect (c)/(d)/(e)/(f) closure.
- Scripts touched: `scripts/zotero.py` (+109 lines, `find_by_doi` +
  `_normalise_doi`), `scripts/lit-scout-zotero-import.py` (+128/-36,
  `merge_manifest_entries_by_doi` + 7 audit fixes), `scripts/sync-to-zotero.py`
  (env-var rename, 14 lines).
- Docs touched: `global-claude-md/zotero-reference.md` (+99 lines —
  new API Credentials section, target-suffixed convention,
  bash-hyphen-trap, Lit-scout Staging Import section);
  `agents/lit-scout.md` (Phase 5 + Zotero dedup tool section updated
  for DOI-first); `wiki/user-observations.md` (candidates 28-31 accepted).
- Verification: all fixes smoke-tested against live Zotero DB before
  commit. `find_by_doi('10.1017/RDC.2020.59')`, URL-form variant,
  lowercased variant all return same key `BP7KAMA3`; whitespace +
  empty + unknown all return `[]`. `merge_manifest_entries_by_doi`
  self-merge idempotency + whitespace-strip dedup confirmed.
- Out of scope: 4 Lows in `scripts/sync-to-zotero.py` predate
  workstream H (only the env-var rename touched that file this
  workstream) — captured as deferrable follow-ups; not blocking.

### 2026-05-22 (Fri night → Sat early) — /lit-scout-iterate smoke test + Zotero staging-import shipped

Follow-on session immediately after the three-closed-loop-pairs work
below. Goal: smoke-test the new `/lit-scout-iterate` on a real query,
then act on the surfaced finding (BibTeX correction-propagation gap)
rather than deferring it. The "act now" choice produced the
Zotero staging-import pipeline — a meaningfully new capability that
makes the closed-loop's iterate-mode corrections reach the user's
library directly, not via a fragile BibTeX intermediate.

**(1) Smoke test.** Query: "Bayesian methods for archaeological
dating and chronological modelling". Workspace
`/tmp/lit-scout-iterate-20260522-190212/`. 35 rows × 5 categories =
175 claims. Iter-0 returned 1 FAIL (row 16, Lanos & Philippe 2018,
CrossRef family/given swap, severity high); iter-1 converged PASS.
The proposer's Guard A self-check explicitly *noticed* the swap and
flagged it for the verifier — but didn't correct its own table.
That's the exact division of labour the closed-loop pattern is meant
to enable: proposer is allowed to be imperfect; verifier catches.
Post-run note at `/tmp/lit-scout-iterate-20260522-190212/post-run-note.md`
captured five calibration findings, including the failure_type
recommendation (now landed in `prior-art-scout-verifier`) and the
BibTeX correction-propagation gap (closed in this session, see below).

**(2) Zotero staging-import — design.** Four decisions locked via
`AskUserQuestion`: (a) trigger policy = auto-import on any non-LEGACY
terminal verdict; (b) subcollection naming = `YYYY-MM-DD-<query-slug>`
(timestamp-first for chronological sort, slug truncated to ~50 chars);
(c) dedup on hit = skip + record (no duplicate-stub clutter); (d) tag
scheme = `lit-scout-staging` + `lit-scout-run:TS` + `lit-scout-fit:<level>`
+ `lit-scout-cluster:<slug>`, plus `lit-scout-unverified:<field>` for
FAIL / PARTIAL / UNVERIFIABLE rows (per a fifth question).

**(3) Zotero key provisioning + bash-hyphen incident.** Shawn
provisioned a new personal-library write key
(`ZOTERO_API_KEY_PERSONAL`) and a top-level `staging` collection
(`IX8XR97K`). One operational hazard surfaced and was resolved:
naming the env var `ZOTERO_API_KEY_PAPER-B` (hyphen instead of
underscore) caused `set -a && . .env && set +a` to interpret the line
as a command, dumping the key value verbatim into bash's
"command not found" error string. Key revoked and reissued under
`ZOTERO_API_KEY_PAPER_B` (underscore). pyzotero compounded the risk
by embedding API keys as URL path segments in `GET /keys/<key>` and
dumping the full URL into traceback strings on 403 — exception output
is not safe to forward into shared logs. Naming convention settled:
`ZOTERO_API_KEY_<TARGET>` with `<TARGET>` being the library write
scope (so `_PERSONAL`, `_PAPER_B`); the unqualified `ZOTERO_API_KEY`
is reserved for backward compat with the existing
`scripts/sync-to-zotero.py` consumer (currently broken pending an
aliasing decision — captured as a follow-up).

**(4) Implementation.** New script
`scripts/lit-scout-zotero-import.py` (~430 lines). Reads the final
iteration's `claims.jsonl` for corrected values; fetches fresh
CrossRef metadata for journal-article fields (publicationTitle,
volume, issue, pages, ISSN, abstract); overrides the author field
from the corrected `claims.jsonl` so iterate-mode corrections
propagate end-to-end. Dedup query runs against all 16 local Zotero
libraries by DOI via sqlite immutable-mode read (`scripts/zotero.py`
pattern). Idempotent via a workspace-side
`zotero-import-manifest.json`. Dry-run by default; `--live` to write;
`--limit N` for smoke-testing.

**(5) End-to-end validation.** Two-stage live run against the
smoke-test workspace. Stage 1: `--live --limit 1` created Bronk
Ramsey (2009) `Bayesian Analysis of Radiocarbon Dates` in new
subcollection `3C7UZ5AC` under staging — round-trip-fetch confirmed
all fields landed correctly (compound surname "Bronk Ramsey"
preserved as `lastName`, journal metadata from CrossRef, all four
design-tag categories present). Stage 2: `--live` without limit
created the remaining 29; manifest dedup correctly skipped the
already-imported one. Final state: 30 items in subcollection, 5
group-library duplicates correctly skipped (SDAM-AU + TRAP libraries
that the proposer's text-based `[IN ZOTERO]` flag missed 3 of).
**Row 16 Lanos/Philippe verified clean in Zotero**: first author
`lastName='Lanos'` — concrete demonstration that the iterate-mode
correction propagated all the way through, where the parallel `.bib`
file (still uncorrected from CrossRef raw) shows
`author={Philippe, Lanos and Anne, Philippe}`.

**(6) Driver wiring.** `commands/lit-scout-iterate.md` updated with
new "### Zotero staging import" subsection between Final reporting
and BibTeX generation; failure-modes table gains two rows;
Final-reporting markdown template now references the manifest.
Zotero is now the primary deliverable; BibTeX is backup.

**(7) Follow-ups recorded in workstream H** (continuity.md edits
this session): (a) BibTeX correction-propagation gap closed
[x] 2026-05-22 (Zotero-import path replaces it); (b) Zotero
staging-import shipped [x] 2026-05-22; (c) manifest `items_skipped`
dedup-on-merge bug [x] 2026-05-23; (d) promote proposer Zotero dedup
to DOI-based [x] 2026-05-23; (e) update
`global-claude-md/zotero-reference.md` with the new env-var convention
and bash-hyphen-trap warning [x] 2026-05-23. Plus
(f) `sync-to-zotero.py` rename to `ZOTERO_API_KEY_PAPER_B` [x]
2026-05-23 (the bare `ZOTERO_API_KEY` consumer is now retired).
A post-fix `/audit` pass against the workstream-H code surfaced 3
Mediums and 4 Lows in `scripts/lit-scout-zotero-import.py` plus DOI
URL-normalisation in `scripts/zotero.py`; all addressed in the same
session. Zotero collection writer is now closed.

- Files added (scripts): `scripts/lit-scout-zotero-import.py`
  (~430 lines; dry-run default; `--limit` smoke-test mode;
  manifest-idempotent).
- Files modified (commands): `commands/lit-scout-iterate.md`
  (Zotero staging import section + failure-modes table rows +
  manifest pointer in Final reporting).
- Files modified (planning): `planning/continuity.md` (workstream H
  pair-status row updated; BibTeX gap closed; Zotero shipped
  bullet; three new actionable follow-ups; reference docs section
  gains pointer to the import script; this session log entry).
- `.env` (untracked) gained `ZOTERO_API_KEY_PERSONAL` +
  `ZOTERO_STAGING_COLLECTION`; reorganised under symmetric naming
  `ZOTERO_API_KEY_PAPER_B` / `ZOTERO_API_KEY_PERSONAL`.
- Zotero state: subcollection `staging → 2026-05-22-bayesian-methods-for-archaeological-dating-and-chr` (`3C7UZ5AC`) created with 30 items + 4-tag-category scheme.
- Workspace artefacts at `/tmp/lit-scout-iterate-20260522-190212/`:
  `iter-0/` + `iter-1/` (claims, draft, corrections, report markdowns);
  `post-run-note.md` (smoke-test calibration findings);
  `zotero-import-manifest.json` (durable import audit trail).
- Commits this session (main repo): `43ab371`
  (`feat(scripts,commands): auto-import /lit-scout-iterate results to Zotero staging`),
  `b1ea23a` (`docs(planning): continuity update for lit-scout Zotero staging-import`).
- Data submodule untouched (passive logging changes deferred to a
  separate /handoff cycle).

### 2026-05-22 (Fri, late evening) — Agent-orchestration upskilling: three closed-loop pairs landed

Long meta / agent-design session running parallel to the Phase 0 and
style-guide work. The arc: discuss next steps in the upskilling
roadmap, then close all three remaining proposer-verifier loops in
one session (data-profile, lit-scout, prior-art-scout), incorporating
two calibration findings from real smoke tests (one mine, one a
concurrent session's). Workstream H ("Agent-orchestration upskilling
— closed-loop proposer-verifier pairs") now covers the discipline
as an explicit meta-workstream.

**(1) Roadmap recall + #1 build.** Recalled the 2026-04-18 craft
notebook entries on agent orchestration, identified four next
steps (verifier for prior-art, close data-profile loop, retrofit
lit-scout, cost discipline). User chose to defer #4 (cost
discipline) until non-CC API spend begins — captured as a
`commitment` memory. Built `prior-art-scout-verifier` (~250 lines,
source-type dispatch for GitHub / PyPI / npm / HF / DOI / generic
URL); updated `prior-art-scout` to emit the
`⚠ VERIFICATION PENDING` marker (explicit pair contract).
Commit `36721a7`.

**(2) Smoke-tested the new pair on a real query.** Prior-art for
"corpus-grounded LLM author-voice style guides" — proposer
returned 18 candidates; verifier (run via general-purpose
fallback because the new agent only registers at next session
start) caught 3 hard failures in 17 % of rows, including a URL
that pointed at a topic-aggregator page rather than the real
repo (`github.com/Hiro-Inagawa/write-like-me`, MIT). The
correction materially changed the build-vs-adopt verdict from
"build from scratch" to "read the README first, fork-vs-build
is now a live decision". Report saved at
`notes/prior-art-runs/llm-style-alignment-2026-05-22.md`. Commit
`fe625ee` in data submodule.

**(3) Closed the data-profile loop.** Renamed
`data-profile-scout` → `data-profile-proposer` for naming
symmetry. Added `corrections.jsonl` emission (machine-readable
per-claim audit with stable claim_id, status, severity,
fix_hint). Added iterate-mode (preserve PASS, re-derive FAIL via
fix_hint, regenerate affected markdown). Built
`/data-profile-iterate` driver — cap N=5, FAIL-only iteration,
PARTIAL flag-without-iterate, no-progress termination. Commit
`fab2e0e`. Continuity workstream H added in `dfe13c0`.

**(4) Closed the lit-scout loop.** Same retrofit pattern as
data-profile but with one architectural quirk: sub-agents are
blocked from Write on `.md` files (2026-04-19 v4.x evaluation),
so the closed-loop transport uses **inline fenced jsonl blocks
with HTML-comment markers** that the driver extracts via
`awk | sed`. Proposer emits 5 claims per DOI-bearing row
(authors / year / title / citation_count / doi_resolves);
verifier emits per-field corrections with severity + tolerance
bands. `/lit-scout-iterate` driver added. Commit `a1d9ede`.

**(5) Real smoke test of `/lit-scout-iterate`.** User ran on
"Bayesian methods for archaeological dating and chronological
modelling": 35 rows × 5 categories = 175 claims; iter-0 returned
1 FAIL (row 16 authors, CrossRef family/given swap, severity:
high); iter-1 converged PASS. The FAIL was a textbook
encoding artefact, not a confabulation — but the single-axis
severity rubric couldn't distinguish those. **User
recommendation**: split the severity field into severity ×
`failure_type` axes where `failure_type ∈ {confabulation,
encoding_artefact, metadata_drift, stale_count}`. Two bonus
findings: doi_resolves removal path NOT exercised (clean corpus
— follow-up test should target a confabulation-prone domain);
and the iterate-mode correction does NOT propagate to BibTeX
(`lit-search.py bibtex` re-queries CrossRef and gets the raw
swap back).

**(6) Retrofitted prior-art-scout (last unconverted pair) with
calibrations folded in from the start.** Incorporated:
(a) `failure_type` axis (from #5 above) as a typed second axis on
every FAIL / `documentation_defect` claim; (b)
`documentation_defect` status (from the concurrent data-profile
smoke-test session 2026-05-22 evening — landed there as commit
`2e89bd1` — non-iterating status for source_method-string defects
where the numeric value reproduces). Per-source-type claim
catalogue (GitHub: url_resolves/name/stars/last_active/language/
license; PyPI: url_resolves/name/latest_version/last_upload/
license; etc.). `/prior-art-scout-iterate` driver mirrors
`/lit-scout-iterate` with one new feature: the final report
includes a per-iteration `failure_type` distribution table for
calibration over time. Commit `c4e8139`.

**(7) Workstream H updated throughout** as each pair landed. By
session-close all three pairs are marked **closed-loop wired**;
remaining items in workstream H are smoke-test
`/prior-art-scout-iterate`, synthetic-FAIL test for
data-profile iterate-mode, backport `failure_type` to lit-scout
and data-profile verifiers for symmetry, and the deferred BibTeX
correction-propagation gap.

- Files added (agents): `agents/prior-art-scout-verifier.md` (`36721a7`);
  `agents/data-profile-proposer.md` (renamed from
  `data-profile-scout.md`, `fab2e0e`).
- Files modified (agents): `agents/prior-art-scout.md` (verification
  marker + iterate-mode + claims block);
  `agents/data-profile-verifier.md` (corrections.jsonl + tolerance
  bands + severity rubric — user added `documentation_defect`
  status in `2e89bd1` from concurrent session);
  `agents/lit-scout.md` (iterate-mode + per-row claims block);
  `agents/lit-scout-verifier.md` (per-field tolerance bands +
  severity + corrections block);
  `agents/prior-art-scout-verifier.md` (tolerance bands +
  severity × failure_type + documentation_defect + corrections
  block).
- Files added (commands): `commands/data-profile-iterate.md`,
  `commands/lit-scout-iterate.md`,
  `commands/prior-art-scout-iterate.md` (symlinked into
  `~/.claude/commands/`).
- Files modified (planning): `planning/continuity.md` —
  workstream G addition (style-guide construction, line ~262);
  workstream H addition (closed-loop pairs, line ~314); session
  log entry above.
- Files added (notes): `notes/prior-art-runs/llm-style-alignment-2026-05-22.md`
  (in data submodule).
- Memories: one manual `/remember` (deferred cost discipline) +
  auto-extracted memories from session activity.
- Commits this session (main repo): `36721a7`, `fab2e0e`,
  `dfe13c0`, `a1d9ede`, `c4e8139`. Data submodule: `fe625ee`.

### 2026-05-22 (Fri, afternoon→evening) — Step 2 sweep + toolkit audit-cycle + Gemini 3.5 Flash migration + Phase C-D-E

Long PA-infrastructure session continuing the morning's Phase 0 work.
Six discrete arcs landed in sequence:

**(1) Toolkit audit cycle — three commits.** First-fix
(`a3e7197 feat(cli): global-mode dispatch for archive + catalogue
subcommands`) introduced `_cmd_archive_global` + `_extract_cwd_from_jsonl`
+ dispatched `cmd_archive` and `cmd_catalogue` on `--archive-root`,
plus a regression fix for `auto_metadata` flow-through in per-project
mode. Audit ran via the `/audit` skill across cli.py + test_hook.py —
found a CRITICAL `_extract_cwd_from_jsonl` line-1-only bug (90% of
real live JSONLs have `cwd` on lines 2-10, behind leading
`type: summary`/`permission-mode`/`progress` records), plus mediums:
no agent-*.jsonl exclusion, no trivial-session filter in batch mode,
no tilde expansion on `--archive-root`. Audit-criticals fix
(`1dd4d69 fix(cli): audit follow-ups — cwd scan, trivial filter,
agent-* exclusion`) closed the critical + four mediums. Audit-lows
fix (`32742ca fix(cli): close remaining audit follow-ups`) added
explicit-selector error for global-mode no-flag invocation,
typo-protection on cmd_catalogue's archive-root, the
update_catalogue-per-project call-count test, --force + --session-id
tests in global mode, tilde-expansion regression test, fixed
inaccurate comments. Test count 220 → 249 (+29). Without the
critical fix, the Step 2 sweep would have mass-routed ~340 of the
~375-then-projected sessions to a single `shawn/` bucket and
silently degraded provenance_summary.

**(2) Gemini 3 Flash Preview → 3.5 Flash migration**
(`cdc7c65 feat(model): migrate auto-metadata extractor to Gemini
3.5 Flash (GA)`). After cwd-bug fix changed the actionable scope
from 375 → 107 sessions, ran a head-to-head 3-session comparison
($0.64 spend) against the toolkit's production prompt. Findings:
3.5 Flash had zero JSON structural defects (3 Flash Preview had 1
of 3 — a stray `three_ps.`-prefixed key under `three_ps` that would
degrade provenance_summary via the M3 `.get() or default` guard);
materially better named-entity preservation (commit hashes, tags,
people's names, CI bounds); ~20% faster wall-clock; 3× Flex price
(confirmed empirically: $0.75/$4.50 vs $0.25/$1.50 per M input/output
tokens). Shawn expanded the API gate from $10 to $25 to accept the
price-quality trade-off; production migration committed in lockstep
(same call shape, `thinking_budget=0` honoured, same 1M context).

**(3) Step 2 sweep — per-machine for code_state fidelity.** amd-tower
phase ran first: 76 sessions, ~6 min wall-clock, 23 trivial-skipped,
0 errors. Spot-checks confirmed exemplary outputs — named-entity-rich
titles ("Complete HUMN8031 teaching wrap-up, inscriptions
preregistration lodgement, and academic style guide construction";
"Resolve PostgreSQL trigram extension and index migration error";
"Smoke test data-profile iteration loop on LIRE v3.0 parquet"),
clean three_ps schema (zero defects across all 76), `extractor_model_id:
gemini-3.5-flash` recorded, code_state populated. zbook phase ran
second: 33 sessions, ~4.5 min, 93 trivial-skipped, 0 errors, 5
projects touched (theseus-ship, vlm-burial-mound-detection, Code,
shawn, personal-assistant). Total Step 2: **109 main-thread sessions
archived to rpi-shares**.

**(4) Phase C — layout cleanup v2** (consolidation under `_legacy/`).
Subsumed `_legacy-archive/` + `_misc-cwd/` + all dormant project
subdirs + the TRAP-WD-2020-04 + trap-extraction grouping into a
single `_legacy/` umbrella with READMEs documenting the structure.
Top-level dropped from 31 entries (post-Step-2 sprawl) to 21
(16 active project_ids + 3 reserved namespaces + 2 root files).
Sub-categories nested under their parent projects:
`LLM-History-Paper/theseus-ship/` (60 sessions),
`map-reader-llm/vlm-burial-mound-detection/` (149 sessions).
Global CATALOG.json rebuilt — 411 sessions across 16 active project
roots (note: rebuild_catalogue scans one level deep; nested
sub-category sessions not in the rollup — separate toolkit fix
deferred).

**(5) Phase D — mirror rpi-shares back to working machines.**
amd-tower + zbook each got a full `rsync -av --delete` mirror from
rpi-shares to `~/cc-archives/`. Both machines now hold 702
`session.jsonl(.gz)` + 183 `.txt` (manual exports) = 885 files /
3.4 GB matching rpi-shares exactly. **Methodology gotcha**: the
pre-flight dry-run check ran in the wrong direction (local → rpi-shares
instead of rpi-shares → local), which showed misleading "deletion"
lines that I incorrectly interpreted as safe. The actual mirror
(rpi-shares → local with --delete) DID delete some local-only content
that wasn't in rpi-shares — but verification confirmed those session_ids
ARE in the rebuilt catalogue (re-archived by Step 2 at new
canonical paths), so no actual data loss. Saved to memory as
`2026-05-22-mirror-dryrun-direction` so the gotcha doesn't recur.

**(6) Phase E — sapphire cleanup.** `rm -rf ~/.claude` on sapphire
(13 live JSONLs from Aug 2025 already imported to amd-tower and
processed by Step 2; `.credentials.json` + settings + projects/
all removed). CC CLI was already not installed there. sapphire is
now CC-free, matching the operational decision to use it only for
compute offload.

**Pre-Phase-D dry-run cost-summary** (estimated from auto-metadata
log token counts; not exhaustively reconciled): ~$6-9 for the 109
Step 2 calls plus ~$0.64 for the bake-off test = ~$7-10 total against
the $25 cap. Well under approval.

- Toolkit commits today: `a3e7197`, `1dd4d69`, `32742ca`, `cdc7c65`
  (cli.py global-mode + audit follow-ups + Gemini 3.5 Flash migration)
- rpi-shares destination size: 3.4 GB / 702 session files + 183 `.txt`
- Local mirrors: amd-tower + zbook each hold full 3.4 GB copy
- New memories: `2026-05-22-e020f8b3cb4b` (proper-fix preference),
  `2026-05-22-mirror-dryrun-direction` (rsync direction gotcha)
- Background agents dispatched: 2 (cli.py audit + test_hook.py audit)
- Architectural decisions added below: 4 new (Gemini 3.5 Flash;
  _legacy/ umbrella; Step 2 per-machine for code_state; local mirrors)

**(7) Phase 0 closeout sweep** (continuation, post-commit `6d87d01`).
Four further sub-arcs landed before session close:

- **Cleanup register A** (commit pending) — removed
  `~/Code/map-reader-llm/.claude/worktrees/agent-a59a9dae0bff3f27b/`
  (~6.4 GB, larger than the cc-sessions/ portion alone) and the
  ~700 KB of /tmp test/log artefacts from today's runs. SHA spot-checks
  before the destructive op confirmed worktree content was
  byte-identical to rpi-shares' map-reader-llm subtree.

- **Phase 0 Steps 6 + 7 destructive ops** (per-project
  `archive/cc-sessions/` removal). Per-project safety verification
  script confirmed 100% of source session_ids present in rpi-shares
  before any destructive op (`/tmp/verify-project-archive.py`, since
  cleaned). amd-tower: 202 sessions across 3 projects;
  zbook: 251 across 4. Sequence per project: `git lfs untrack` (LFS
  repos) → `git rm --cached` → gitignore → commit → push → `rm -rf`.
  Five commits: `2f83ec58` map-reader-llm, `226def9` LLM-History-Paper,
  `1b191cd` llm-reproducibility (amd-tower); `7359144` theseus-ship
  (zbook-only); zbook pulled-then-removed for the three amd-tower ones.
  Total freed: ~1.25 GB amd-tower + ~1.24 GB zbook.

- **Step 8 — daily-sync.sh cc-archives section** (commit `800f01a`).
  Added a section between the parent-repo push and the symlink-sync
  step that does `rsync -a --ignore-existing $HOME/cc-archives/ →
  ~/mnt/rpi-shares/cc-archives-consolidated/` on every SessionStart
  via the existing daily-sync-trigger.sh hook chain. Mount-presence
  check via `df` grep ("rpi-server" in source) handles the
  silent-empty-dir failure mode.

- **Step 9 — `scripts/resolve_session_id.py`** (commit `800f01a`).
  Two-stage resolution: fast CATALOG.json lookup, then exhaustive
  filesystem rglob fallback for nested sub-categories +
  `_legacy/` content. Smoke-tested against four location classes —
  catalogued, LLM-History-Paper/theseus-ship/ nested,
  map-reader-llm/vlm-burial-mound-detection/ nested, _legacy/Code/ —
  all resolve correctly.

- **Step 10 — indexing pattern** was decided 2026-05-20
  (working-machine-driven only); no new work needed.

- **Phase 0 closeout commit `1f0c6c1`** — continuity register updated
  with the per-step completion markers; "Phase 0 — DONE" recorded.
  Sole outstanding follow-up is the deferred content-equivalence
  dedup pass for `/export`-era duplicates.

**Day's commit total across all repos**: 18 commits across 6 repos.
**API spend today**: ~$8.5-11.5 against the $25 cap.
**Disk freed across both working machines**: ~9.5 GB (worktree +
per-project archives).

### 2026-05-22 (Fri, late evening) — Style-guide workstream G: comparator pass + rescan + v2 implementation plan DECIDED

Resumed the morning's style-guide work after the run-1 + prior-art-scout
pair landed earlier in the day. Shawn directed the session along three
tracks: (a) freeze run-1 and the prior conscious guides as comparators
before doing any reconciliation; (b) evaluate then test
`Hiro-Inagawa/write-like-me` rather than just deciding off the desk
eval; (c) build a complete v2 implementation plan from the lifts that
survive the comparison. All three closed in one session.

**(1) Desk eval of write-like-me via background `general-purpose` agent.**
Read-only WebFetch/GitHub-API pass; report at
`notes/prior-art-runs/write-like-me-evaluation-2026-05-22.md` (committed
`891facc` earlier in the day). Verdict: compose, do not fork — the
`scripts/stylometry.py` module is a clean importable Python feature
extractor (~50 features, JSON output, stdlib-only, no LLM calls); the
user-facing templates carry no per-claim counts or locator placeholders,
so attestation discipline would need to be layered on top.

**(2) End-to-end comparator pass.** Cloned `~/Code/write-like-me/` (6
commits, last `3878d9d` 2026-05-10); set up a venv with textstat 0.7.13
+ spaCy 3.8.14 + en_core_web_sm 3.8.0; symlinked the 18 included papers
from `/tmp/style-corpus-extract/` into a clean comparator directory; ran
`stylometry.py --register academic --output … --report …`. Three real
failure modes surfaced that the desk eval missed: (i) academic
reference-list contamination — "sobotkova" (56) and "ross" (52) leaked
into top-20 sentence-initial words, "doi/https/org" into top content
words; (ii) silent textstat compatibility break — `textstat.word_count`
removed in 0.7.13, `compute_readability`'s bare `except Exception:` swallows
the AttributeError and drops the entire readability dict with no warning;
(iii) universal-baseline em-dash zero-tolerance ban that conflicts with
Shawn's attested 0.46/1k em-dash usage concentrated in 7 of 18 papers
(TRAP chapters at 2.12/1k). Comparator report
(`notes/style-guides/academic/write-like-me-comparator-2026-05-22/comparison-report.md`)
refined the desk-eval verdict to "compose with minimised scope" —
re-implement the additive measurements under run-1's evidence discipline
rather than vendoring.

**(3) Prior-art rescan via `prior-art-scout` background agent.** Shawn
explicitly requested re-scanning the 7 GitHub queries that failed in run
1. Report at `notes/prior-art-runs/llm-style-alignment-rescan-2026-05-22.md`.
Surface coverage: HF Spaces (7 queries, only relevant Spaces at 0–1 likes
inaccessible unauthenticated), GitLab (effectively null — 9 stylometry
repos all 0–1 stars, irrelevant), GitHub via `gh api` + topic pages. Null
hypothesis partially falsified — `ngpepin/stylometric-transfer` (10 stars,
Python, pushed 2026-02-27) is the most technically complete tool found
across both passes (versioned JSON fingerprints with raw distribution
histograms, per-component validators, structured deviation reports, CLI +
HTTP API + dashboard + regression suites). But licensed PolyForm
Noncommercial 1.0.0. Shawn endorsed "inspiration only" given commercial
Fieldmark/FAIMS context.

**(4) v2 implementation plan via `Plan` background agent.** Shawn agreed
to incorporate four lifts (Biber MDA dimension labels for §§1–6;
reduced Catch-Me-If-You-Can 2-metric CC-only evaluation suite — paper's
4-metric ensemble is multi-author-benchmark-shaped, only style-matcher
applies; Kumar et al. Author Writing Sheet aggregation as deterministic
merge rules with new `attested-concentrated` 5th status for bimodal
patterns; Panickssery reverse-prompt 5-exemplar block at Opus 4.7,
~$0.50/run) plus the write-like-me measurement extensions
(MATTR/hapax/passive ratio/nominalisation/dependency depth/POS
bigrams/paragraph stats + 8-metric verification gate + reference-list
stripping pre-pass). Step-Back Profiling Gist preamble deferred to
memory + inbox. Plan saved to `planning/style-guide-agent-v2-implementation-plan.md`.
Walked through all 10 design questions in three AskUserQuestion batches;
recommended default taken on every item. Plan front-matter promoted from
DRAFT to DECIDED.

**(5) Workspace state.** Phase 1 (4–6 h, deterministic, no API spend) is
the next executable unit when v2 work resumes. Total envelope 12–18 h
focused work + ~$0.50 API spend per generation run (Phase 4 only).

- Commits this session (5 logical chunks):
  - data submodule: `d3fa75d` (comparator pass artefacts),
    `8ec1f3c` (prior-art rescan), `33f7efa` (Step-Back memory + tag
    vocab + inbox row)
  - PA repo: `244668b` (v2 plan), `dbaab9a` (submodule pointer bump)
  - All pushed to `origin/main` on both repos
- New artefacts:
  - `notes/style-guides/academic/write-like-me-comparator-2026-05-22/` —
    3 files: `academic-profile.json`, `academic-profile-report.md`,
    `comparison-report.md`
  - `notes/prior-art-runs/llm-style-alignment-rescan-2026-05-22.md`
  - `planning/style-guide-agent-v2-implementation-plan.md`
- New memory: `decision` memory `2026-05-22-bad057fbe9e9` (Step-Back
  deferred), 4 new tags appended to `memories/tag-vocabulary.txt`
- Inbox additions: Step-Back follow-up row; existing reconciliation row
  updated with concrete prior-guide paths
- Local-only clone: `~/Code/write-like-me/` with `.venv` and
  en_core_web_sm — not committed; can be deleted between sessions or
  kept for Phase 1 cross-reference

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
