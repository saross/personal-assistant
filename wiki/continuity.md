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
| Phase 0 — operationalise tier-3 archive | **transcript-content search BUILT 2026-06-21** (the capability this phase was to unlock): `session_chunks` PG index + `search-sessions.py` / `/search-sessions` / `search_sessions` MCP tool + safe `.gz` fallback + auto-index hook. See the 2026-06-21 session-log entry. Archive consolidation itself was already done (workstream D). |
| Phase 1 — schema + `/forget` + `/update` | **done 2026-05-16** (commits `03b86ad`, `d666470`) |
| Phase 2 — anchor verification + confidence binding | **done 2026-05-16** (commit `50e663b`) |
| Phase 3 — autonomous-save + correction markers | **done 2026-05-16** (commit `7078d39`) |
| Phase 4 — typed links + cross-session supersession (L3) | **superseded by workstream D 2026-05-17** — typed links reshaped as wiki-page links + working-notes references |
| Phase 5 — migration sweep + bulk-flag pass | **superseded by workstream D 2026-05-17** — migration sweep still valuable as backfill for `verified` field, but not gating anything |
| Phase 6 — extractor bake-off | **deprioritised 2026-05-17** — prior-art survey found write strategy contributes ~3–8 retrieval-accuracy points vs ~20 for retrieval; wrong lever |

### B. Session-start payload reduction (Vector 2 / injection issue) — *design landed 2026-05-17; PASS 1 (engine + proof, hook untouched) shipped 2026-05-30; PASS 2 (live cutover) shipped + enabled on amd-tower 2026-05-30 — 2-week §8 observation window running; Vector 2b (scratchpad byte budget) shipped DARK 2026-05-30 — enable after §8 review; Vector 2c (focus-aware + project-scoped digest) shipped DARK 2026-05-30 — enable after §8 review*

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
- [x] 2026-05-30 **Vector 2c — focus-aware + project-scoped digest selection:
  DESIGN + IMPLEMENTATION shipped DARK.** Operationalises the relevance
  dimension of the 2026-05-30 Stage 2 reframe (vector-2-design §6b). Two
  changes to the digest's verified-entry selection, behind ONE machine-local
  flag (`PA_DIGEST_FOCUS` / `~/.pa-digest-focus`, default OFF, byte-identical
  → §8 window unconfounded): (1) **focus-aware ranking** — the active FOCUS.md
  slot projects become the primary ranking key (Option 3: ranking + a thin
  one-line legibility label, NOT a redundant focus block — `# Task Status`
  already prints the slots); (2) **hard project scope** — in a project repo
  the verified/fallback pools are filtered to that project (`matches_project`,
  mirroring `is_same_project`); the PA hub is exempt (already nulls
  `current_project`). **Coarse by design** (Shawn's choice): the focus key is
  the last path segment of each slot's `- **Project:**` line
  (`research/inscriptions` → `inscriptions`), substring-matched against the
  memory's encoded `project` + tags — bridges to differently-named repos
  (`efn` matches `…-Groundsite-EFN-Planning`). Empirically validated at source
  (2026-05-30, `data/memories/memories.jsonl`): of 377 verified-true in-window
  records, `{inscriptions, efn}` matches 127 (34 %). Rank key has two regimes:
  focus-on → `(focus_score, recency)` (drops the degenerate whole-corpus
  overlap term that biases toward verbose projects); flag-off →
  `(overlap_score, recency)`, byte-for-byte the pre-2c key. Tests +37 (digest
  + retrieval-hook); **full suite 818 passed**, 0 regressions. Live smoke
  (PA-hub): OFF byte-identical to today's digest; ON renders the focus label +
  focus-ranked entries. Design: `wiki/planning/vector-2c-design.md`. **Sentinel
  NOT created — dark.** Known limitation (documented, deferred): focus slots
  with little recent verified activity (EFN this week) don't surface — a
  per-slot round-robin is the future lever, not v1.
  - [ ] **Enable Vector 2c on amd-tower AFTER the §8 review (2026-06-13)** —
    `touch ~/.pa-digest-focus` (or accept the §8 confound). Same gate timing
    as Vector 2b.
  - ⚠️ **Provenance note (concurrent-session race):** the 2c code physically
    landed in commit **`cfa9152`** — a *workstream-G* commit
    (`fix(style-analyser): scope prose-paragraph filter…`), NOT a 2c-labelled
    one. A concurrent style-guide session ran a bare `git commit` that swept my
    `git add`-staged 2c index (5 files: `scripts/digest.py`,
    `hooks/session-start-retrieval.py`, both test files,
    `wiki/planning/vector-2c-design.md`) into theirs. No data loss; already
    pushed, so not rewritten. Anyone auditing 2c history: look at `cfa9152`,
    not a 2c-named commit. This is the exact hazard the convention added in
    `87205b0` (one commit earlier) warns about — bare `git commit` over a
    shared index. Mitigation going forward: stage AND commit in one tight
    step, never leave files staged across turns in this repo.
- [ ] **Write-path / corpus-health thread (NEW, 2026-05-31).** Read path
  (Vector 2/2b/2c) is now well-disciplined; focus shifts to corpus health
  while the §8 review is pending. **Full plan + 19-item backlog + the
  2026-05-31 read-only corpus profile live in
  `wiki/planning/memory-write-path-plan.md`** (key finding: the <4 % verified
  rate is NOT 96 % wrong — 86.5 % of the corpus predates the 2026-05-16
  anchoring epoch and is unanchorable by construction; there is no cheap clean
  "wrong memory" signal, so the strategy is structural, not a purge).
  **Item 11 (write-time anchor quality gate) shipped 2026-05-31 (`b6f85c1`)** —
  `anchor_verify.wellformed_anchor()` drops anchors malformed for their type
  (chiefly commit refs written as slugs, ~3 %); forward fix, the ~22 already in
  the corpus await a cleanup pass. +17 tests, full suite 835.
  **Item 12 (verified=false triage) shipped 2026-05-31 (`5edbdd4`,
  `scripts/triage_anchors.py`, read-only).** Of 402 false-anchored records:
  13 clean-after-strip, 8 cross-repo, 381 unresolvable — **but unresolvable is
  overwhelmingly a verifier artefact** (446 relative + 75 tilde + 15 absolute
  file anchors `verify_file` can't resolve; only 7 commit refs resolve nowhere).
  Genuinely-suspect set is tiny → `verified=false` is NOT a trustworthy prune
  signal yet. Surfaced **item 20 (`verify_file` path/history hardening, no-API)**
  — expand `~`, accept absolute paths, check the memory's commit not just HEAD —
  which now **precedes any pruning**. Next no-API: item 20, then item 13 design
  (retention), item 9 (§8 apparatus). API-gated: items 5/6/14/15. Full backlog
  + sequence in `wiki/planning/memory-write-path-plan.md`.

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

### E. Open-science / RDA IG (Documenting GenAI Interactions in Research) — *application EDIT-COMPLETE 2026-09-03; submission expected 4 Sep 2026; then RDA's 10–12 week cycle*

Shawn co-chairs an RDA Interest Group (eight co-chairs; Brian
Ballsun-Stanton and Shawn proposing). Framework: Three Ps (Prompt,
Process, Provenance), extending FAIR / RO-Crate. **All working material is
in `data/notes/rda-ig/` — start at `index.md` ("State as at 2026-09-03"),
then `change-log.md`.** The docx files under `docs/open-science/` are the
July originals and are superseded. Anchoring: month 1 = November 2026
(expected endorsement), VP28 (March 2027) = month 5, P29 (September
2027) = month 11, Working Group launch P30 (2028); 25 participants.
Resume checklist for when RDA responds: the 2026-09-03 session log entry.

The PA system is plausibly a proof-of-concept implementation of the IG
framework (cc-session-toolkit is cited in the Statement of Work as
exemplar tooling). Provenance audit (workstream D) was the first concrete
alignment action.

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
| Reconciliation of aspirational section vs prior conscious style guides | **done 2026-05-30** — reconciled in-session (Workstream G). Per Shawn's direction a **clean start**: the prior guides (`~/Code/prompts/System-setup/`, `e17a2f5`) were read to drive the reconciliation but are treated as superseded and are NOT cited in the guide; confirmed §11 items instead carry `Live cross-ref` pointers into the empirical §§1–10. Added §§11.9–11.13 (standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation, voice calibration). The apparent paragraph-length conflict (prior target 100–180 words vs §6.5 median 17) is a **§6.5 segmentation artefact** (headings, front-matter and line fragments counted as paragraphs; median falls below mean sentence length) — recorded as a reconciliation note, no item; a background agent has diagnosed it (non-prose blocks are 41% of "paragraphs" but only 4.4% of words; corrected median ≈27, mean ≈42; the "two-register cluster" is contamination-driven, r = −0.78) and proposed a `phase1_pipeline.py` fix — **applied 2026-05-30** (scoped to the paragraph-stats path only; phase1→3→5 re-run): corrected median 27, mean 41, n 2 968 prose paragraphs, with only paragraph stats changed (gate + all word-level metrics byte-identical). phase3: median now `attested`, mean `attested-concentrated` (a genuine short-vs-long register split the contaminated median had mislocated); phase5 re-validated PASS (paragraph mean now excluded from the centroid as bimodal; LOO max 4.67→4.42). Guide §6.5 + Appendix A/C + the §11 note all updated. Submodule `0f85a3c`; parent commits below |
| Substack / business / teaching genre runs | **deferred indefinitely (2026-05-30, Shawn)** — start only on an immediate need with an assembled Zotero corpus; each run needs a corpus + Phase 4 API approval. The v2.3 agent is ready to drive them |

**Big-picture status & roadmap (2026-05-31 review).** Separate the
*means* from the *end*. The style **assessor** (academic register) is
**complete** — phases 1–5 built and validated: measurement
(`phase1_pipeline.py`), the empirical guide v2.3, deterministic
promotion + verifier (`phase3_*`), exemplars (`phase4_*`), and the
runtime `phase5_evaluator.py` (Mahalanobis distance-to-corpus + the
8-metric gate). The **end** — a capacity to write in Shawn's voice — is
**under-built, and its efficacy is unproven**: nothing has yet tested
whether the guide actually moves LLM output toward the corpus. Open
items, ranked:

1. **Efficacy experiment — DONE 2026-05-31. Verdict (citation-corrected): the
   guide WORKS — it moves output toward the corpus on intrinsic voice, and
   BOTH the distance and a blind judge now agree.** Pre-reg + harness + pilot at
   `wiki/planning/style-guide-efficacy-experiment-design.md` and
   `data/experiments/style-efficacy-2026-05-31/` (authoritative synthesis:
   `efficacy-synthesis.md`). 3-condition paired design (C0 plain / C1
   generic-academic / C2 full guide + Appendix F), Opus 4.8 in-CC
   fresh-context subagents (no API), 4 pilot topics (2 on- + 2 off-domain) ×
   2 reps; length-matched scoring (319 ~400-word corpus excerpts — fixed a
   hapax/Heaps'-law length artefact that had dominated whole-paper scoring).
   **The decisive correction (Shawn):** citation format is venue-determined,
   NOT voice — it had leaked in three ways (guide §3 prescribed it, Appendix F
   demonstrated it, the judge prompt *rewarded* it). Removed surgically (guide
   §3/§9.4 → exclusion notes; injection citation-strip + no-citation directive;
   judge prompt + reference de-citationed) and both tests re-run. **Corrected
   result: C0 plain → C2 guide = +0.44 LOO-SD, 4/4 on the distance (was a null
   +0.007 when citation-confounded), and the blind judge prefers the guide 6/8
   (was 7/8 — citations had been part of the cue).** Removing citations also
   *improved* the prose: citation clauses had inflated C2 sentence length
   (|z| 1.66→0.995) and passive (0.91→0.21). Generic-academic stays *harmful*
   (−0.92 LOO-SD vs plain, 0/4). So the distance is a usable diagnostic for
   citation-free generation (it still omits discourse features — not a sole
   gate). **Then three diagnostic-driven guide adjustments (Shawn-approved):**
   (i) corpus reference rebuilt citation-free + §6.2 semicolon target corrected
   6.54→≈3.4/1k (the 6.54 was ~half citation-list); (ii) concession dialled
   back (§6.7/§9.2 — C2 had conceded ~2× corpus); (iii) first-plural moderated
   (§1.1 — C2 had over-produced "we"). After adjustment: **C0→C2 = +0.66
   LOO-SD, 4/4** (up from +0.44); first-plural now exact (5.03 vs 5.05),
   concession near-corpus (0.19 vs 0.14); judge stable 6/8. **Guide is in shape
   to proceed to /write-like-me.** Tried + rejected: a C3 "operative preamble"
   revision (overshot; dropped). **Final validation RESOLVED 2026-06-03: Shawn
   read the four C2-vs-C0 pairs blind and picked the guide 4/4** (both
   high-confidence calls among them) — the author, the only non-proxy judge,
   confirms the guide works (`human-validation.md`). Remaining caveat is only
   pilot scale (4 topics).
2. **Package a generation workflow — JUSTIFIED by (1).** **Workflow CODIFIED
   2026-06-03: neutral-draft → voice-align** (full spec
   `wiki/planning/write-like-me-workflow.md`). Five stages: (1) outline jointly
   → (2) CC drafts in plain/neutral voice (content first) → (3) Shawn
   content-edits author-hat (audits naked prose; naturally drifts toward his
   voice) → (4) `/write-like-me` voice-aligns *conservatively* (citation-
   stripped guide + Appendix F; preserve what Shawn already got right; meaning-
   preserving + show-changes; **no citations**, §3; phase5 + per-feature deltas
   as the diagnostic/iterate signal) → (5) Shawn editor-hat final pass (catches
   meaning-drift). Architecture: `/write-like-me` is the stage-4 **skill**
   driving a fresh-context generation **agent** for isolation. **Gate:** the
   experiment validated the *fused* path; the neutral→voice-align path is
   untested — **try the workflow manually first, validate stage 4 (blind-pair
   vs fused + meaning-drift check), then build the skill.** Do NOT bolt on the
   rejected C3 preamble.
3. **Multi-genre assessors** (Substack / business / teaching) — deferred
   indefinitely; each needs a Zotero corpus + Phase 4 API approval.
4. **(minor) phase1 manifest reproducibility gap** —
   `data/style-corpus/corpus-manifest.json` is the extraction *output*
   format, not the flat list `phase1_pipeline.py` expects, and the
   agent's canonical invocation points at a non-persistent
   `/tmp/style-corpus-extract/manifest.json`. The 2026-05-31 re-run
   reconstructed a manifest from the committed json's 18 keys. Fix:
   commit a phase1-format manifest, or derive keys from
   `corpus-manifest.json["results"]` / the extracted dirs.
5. **(minor) venv dependency manifest** — `~/Code/write-like-me/.venv`
   has scikit-learn / scipy / spaCy added with no pinned manifest; a
   fresh machine cannot reproduce it.
6. **(minor) longitudinal cross-version tracking** — the agent is
   designed to be re-run across Claude versions (Appendix D diff), but
   there is only one data point; re-run on a future version to track
   drift.
7. **2×2 ablation (queued 2026-05-31, Shawn)** — does the Appendix F
   exemplar block contribute, or does the guide §§1–11 do the work alone?
   Adds guide-only and exemplars-only conditions to the plain/full pair.
   Decides whether the exemplar-injection plumbing is worth building into
   `/write-like-me`. Re-uses the efficacy harness
   (`scripts/style-analyser/efficacy_*.py`); score by the **judge test**, not
   the distance.
8. **(minor) judge-based / discourse-aware efficacy gate** — the efficacy
   experiment showed the phase5 Mahalanobis distance is insensitive to the
   markers that signal authorship (citations, first-plural stance, concession
   moves). A reusable acceptance gate for generated voice needs either a
   blinded judge harness (`efficacy_build_judge_tasks.py` +
   `efficacy_score_judges.py` are a first cut) or distance features for
   citation density + discourse moves. Relevant to (2) and to the deferred
   Catch-Me-If-You-Can ensemble.

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

### I. Adversarial reviewer (`/review-paper`) — AR — *apparatus BUILT + audited 2026-07-24 (2nd session); calibration + hardening next*

Pre-submission "Reviewer 2" apparatus for papers (Paper B first; shareable
with Brian). Authoritative docs: `wiki/planning/paper-review-skill-spec.md`
(design + resolved decisions + 2026-07-24 amendments) and
`wiki/planning/prior-art-adversarial-reviewer-2026-07-24.md` (verified
prior-art report, PASS).

| Piece | Status |
|---|---|
| Prior-art scout loop | **PASS 2026-07-24** — build-informed-by verdict; 6 design imports in spec as candidates for ruling |
| AB+ substrate (source-fidelity lens) | **complete 2026-07-24** — 75/79 cited keys (94.9%); remainder = explicit rulings (3 unavailable, 1 film) |
| Model-provenance convention | **live** — pin at dispatch, stamp at render, transcripts are truth; enforced via /audit-config + /phase-gate |
| Paper-repo pipeline | PRs #20, #21 merged; **#22 open** (default-bib-join glob) |
| The apparatus itself | **BUILT 2026-07-24 (2nd session)** — `skills/review-paper/SKILL.md` + `scripts/review-paper-prepass.py` + `scripts/workflows/review-paper.mjs` (both stances, both scopes, DA hard rules, meta-reviewer, unanimous-check); 3-agent /audit (3 Critical/9 Medium) all fixed + fixture-verified; build record in the spec |
| SSH-hedging stress test | **next, REQUIRED before first adversarial use** — procedure in SKILL.md §"Calibration gate"; record result in the spec |
| Critical-friend hardening runs | next — Paper B §3–§8 section runs to harden the rubric (build plan step 1 tail); AB+ self-heal chaining (step 4) still open |

---

## Things to verify on next session (priority queue)

Read these *before* starting new work. Most should take <5 min each.

### ⚠ From the 2026-08-22 session, closed 2026-09-03 — three items it could not safely close

1. [x] 2026-09-03 **DONE** — fixed on amd-tower in submodule commit `eb04150`
   (`fix(focus): mark the closed ARDC slot as a record heading`) by a concurrent
   session and pushed. Original text follows.

   **`FOCUS.md` still announces a closed item as Slot 1, on every machine but
   this one.** `## Slot 1: ✅ CLOSED — ARDC application SUBMITTED 2026-08-13`
   never received the `(record)` prefix that marks a retired section, so the
   parser returns **two Slot 1s** and every session banner has listed a closed
   application as current work since 13 August — now three weeks. The one-line
   fix was made on 2026-08-22 but **was never committed**, and upstream
   (`data` @ `ca3689d`) still carries the unfixed heading. Apply on a machine
   whose `data` submodule is current:

   ```bash
   sed -i 's|^## Slot 1: ✅ CLOSED — ARDC|## (record) Slot 1: ✅ CLOSED — ARDC|' \
     ~/personal-assistant/data/tasks/FOCUS.md
   ```

2. [x] 2026-09-03 **DONE** — cleared on zbook the same morning: **78** records (not
   68) committed as `0519e6a` before any merge, backed up outside the repo at
   `~/pa-rescue-2026-09-03/` (`memories-added-78.jsonl`, `full-working-tree.diff`),
   then merged (`b323978`) and pushed. Post-merge: 40,931 records, none
   unparseable, all ids unique, all 78 present. The SSH-vs-HTTPS theory was
   **disproved**: the fetch succeeded once the records were committed. Residual:
   six duplicate lines in `tag-vocabulary.txt`, three pre-existing. Original
   text follows.

   ⚠⚠ **THIS HAS NOW BITTEN — 2026-09-03, Shawn's `git submodule update` on
   zbook failed and the RDA folder is absent there.** The refusal is almost
   certainly protective: `git submodule update` will not overwrite uncommitted
   changes, and zbook holds 68 uncommitted memory records. **Do not force it,
   and do not stash** — this repo has lost memory records to stash before.
   Commit `memories/memories.jsonl` on zbook first, then update. A second,
   independent cause may also apply: `.gitmodules` declares the submodule over
   **SSH** (`git@github.com:saross/pa-data.git`) while amd-tower's checkout
   actually uses **HTTPS** with `gh auth git-credential`, so a machine without
   a registered SSH key will fail to fetch it at all. Diagnose which before
   acting. Original text follows.

   **Do not update the `data` submodule on zbook without rescuing its
   uncommitted work first.** The checkout sits at `e268e29`, **254 commits
   behind** what the parent records, because this session pulled repeatedly with
   `submodule.recurse=false` to avoid sweeping a concurrent session's files. It
   holds **68 uncommitted memory records** plus edits to `tag-vocabulary.txt`,
   two `logs/*.json`, and the `FOCUS.md` fix above. This repo has lost memory
   records to stash operations before (`5defc3e`, "recover 3 stash-only memory
   records"), which is why the session declined to touch it. Commit
   `memories/memories.jsonl` first, then update.

3. **The Slack dashboard has been publishing twelve-day-old figures on zbook**,
   for the same reason: it renders from the submodule working tree, so a stale
   checkout yields a stale canvas. **The provenance footer caught this** — it
   reads `data/tasks/ @ e268e29+dirty` — which is exactly what that footer was
   built for, and is the first live evidence the design works. Two follow-ups
   worth considering: have the publisher **refuse to publish, or mark the canvas
   degraded, when the submodule is behind the pointer its parent records**,
   since a stale dashboard that looks authoritative is the failure being
   designed against; and note that other machines are unaffected only if their
   submodules are current.


- [ ] 2026-07-27 **Zotero shared-group write-back — RULED, awaiting keys
  (work package, ready to execute on amd-tower).** Shawn's ruling
  (2026-07-27): Claude notes ALWAYS allowed in FAIMS-Project (he owns the
  group); SDAM-AU writes limited to the `SPA` collection (key `PZN5ATJK`,
  top-level; reads fine group-wide). **Blocked on Shawn minting two keys**
  at zotero.org/settings/keys (per-group permissions, Read/Write on just
  that group): `ZOTERO_API_KEY_FAIMS_PROJECT` (group 2542876) and
  `ZOTERO_API_KEY_SDAM_AU` (group 2366083), then adding both to
  `~/personal-assistant/.env` on amd-tower. Caveat ruled visible: Zotero
  keys cannot be collection-scoped, so SPA-only is enforced in the sync
  script (item ∈ `PZN5ATJK` check), not by the key. Implementation steps
  once keys exist: (1) extend `scripts/sync-to-zotero.py` to route
  per-item across libraries (locate item via all-groups read; select the
  target-suffixed key; enforce the SPA gate for SDAM-AU) — /audit the
  change; (2) replay the 4 parked notes from
  `data/memories/quarantine-zotero-skipped.jsonl` (cursor 32654 is past
  them — replay reads the quarantine file, not the cursor); (3) the
  SDAM-AU note targets attachment `FGM4PVSX` — re-point to parent
  `RWKBBVTZ` (the Hanson book), which is currently in collections
  `F2385QXW`/`ZAS3ZRV4`, NOT in SPA: it only becomes writable if Shawn
  adds the book to SPA, else it stays parked by the ruling. **Machine
  note:** `ZOTERO_GROUP_ID=5861859` was added to zbook's `.env` only
  (2026-07-24); add it to amd-tower's `.env` alongside the new keys
  (`.env` is per-machine, not in git).

- [x] 2026-07-24 **AR: paper-repo PR #22 — MERGED** (decision review,
  2026-07-24 evening; merge commit `d23fbfc`, worktree + branch cleaned up).
- [x] 2026-07-24 **AR: 3 advisory verifier flags — RULED (amend per
  verifier)** (decision review, 2026-07-24 evening). Entries amended with
  Author-ruling notes (paper-b `e6d497d`); olofsson positioning watch-item
  ruled acceptable, kept; stale Zotero notes deleted + re-pushed from the
  amended entries (3 clean creates). Verifier sections retained unedited.
- [x] 2026-07-15/24 **Zotero write-back — RESOLVED (decision review,
  2026-07-24 evening), and the 2026-07-15 diagnosis was WRONG.** Probing all
  15 accessible libraries showed the 5 pending notes target THREE libraries:
  3 → `MPZHXY3P` (FAIMS-Project group 2542876, blogPost), 1 → `FGM4PVSX`
  (SDAM-AU group 2366083 — an ATTACHMENT key, parent `RWKBBVTZ`), 1 →
  `ENPYIZQF` (personal library). No held key writes to the first two, and
  shared-group writes need a visibility ruling anyway. **Ruled: personal
  now; park shared.** Implemented: `build_zotero_client()` is env-driven
  (`ZOTERO_SYNC_LIBRARY_TYPE`, default `user` + `ZOTERO_API_KEY_PERSONAL`;
  `group` + `ZOTERO_API_KEY_PAPER_B` available); parent-not-found (409)
  parks as `skipped_not_found` instead of failing so the cursor advances.
  Live run verified: `created: 1` (note `WUKQ9S5G` on the Kazanlak article,
  read back OK), `skipped_not_found: 4`, `failed: 0`, cursor 32654. The 4
  parked records are recoverable in
  `data/memories/quarantine-zotero-skipped.jsonl` (reason
  `zotero_item_missing`) if shared-group notes are ever ruled in; the
  SDAM-AU one also needs its attachment key re-pointed to parent
  `RWKBBVTZ`.
- [x] 2026-07-15 **amd-tower post-swap spot-checks — ALL PASS** (verified 15:12
  AEST, first amd-tower session post-handoff): (1) sync-cron green — cursor at
  EOF (`sync-cursors.json` postgres_sync_line 30827 == JSONL length), last clean
  run 15:10:02 AEST; the 11:30–11:50 poison-record errors in `sync-cron.log`
  (record `2026-06-15-46328e405d0c`, null session_id) were the tail of the
  repair-replay window and stopped before handoff. **Latent defect noted:** that
  JSONL line still carries `session_id: null` (PG holds `''` via rebuild
  coercion) — any future cursor rewind/replay through the incremental insert
  path will jam on it again; belongs with the splice-below-cursor candidate
  fixes in the 2026-07-15 inbox row. (2) Row count tracking zbook — amd-tower
  30,827 (PG == JSONL), zbook 30,825 over SSH (192.168.1.80; hostname didn't
  resolve): amd-tower 2 ahead from today's local extractions, correct drift
  direction. (3) rpi-shares mounted rw via SSHFS. (4) daily-sync ran at
  SessionStart 14:21 — cc-archives sync [3/3] complete, R2 push complete
  (real push 14:09, 14:21 nothing-to-transfer), symlinks refreshed. Benign
  `deadline_at 'TBD'` warning in sync-cron.log is a task row, not memories.

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

- [ ] 2026-09-03 **Shawn committed to clearing all pending observation sections
  by end of week.** Recorded so the next `/handoff` and `/recap` do not
  re-surface them before then. **Scale worth knowing before planning the
  sitting: 14 pending sections in `wiki/user-observations.md` alone**, plus 4
  across `cv-and-applications` (2), `fieldmark-docs-staging` (1), and
  `map-reader-llm` (1) — 18 in total, oldest dated 2026-05-18. The protocol's
  hold-over rule has worked as designed (nothing was silently discarded) but the
  queue has never been drained, which is a different failure from the one the
  rule prevents. Worth deciding at the sitting whether the older sections are
  still worth reviewing or should be closed unread with a note.

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
| RDA IG context (Three Ps framework) | `data/notes/rda-ig/` (start at `index.md`; `statement-of-work.md`, `summary-and-description.md`, `change-log.md`); the July docx originals under `docs/open-science/` are superseded | Aligning system with research-data standards; provenance audit |
| Cap-analysis findings (850K decision basis) | `data/experiments/transcript-cap-analysis-2026-05-19/findings.md` | Why the cap is 850K; what middle-truncate sacrifices on outliers; the framing-strip correction note |
| CoT capture investigation (RDA IG-relevant) | `docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md` | Why thinking blocks are empty in CC JSONLs; survey of community capture tools; recommendations across short / medium / long horizons |
| Current FOCUS slots | `tasks/FOCUS.md` | Knowing whether to mention slot pressure (don't if PA work is deliberate background) |

---

## Recent session logs

### 2026-09-03 (Wed, latest RDA) — SESSION CLOSE: THE APPLICATION IS EDIT-COMPLETE AND IN SHAWN'S HANDS; A CHANGE LOG THAT "WAS UP TO DATE" NEEDED SIX CORRECTIONS; A SECOND OWNERSHIP-OF-ACTION ERROR GOT AN INBOX ROW

The RDA Interest Group application is edit-complete and everything left is
Shawn's: paste the Markdown into the two Google Docs, paste the HTML into the
RDA web form, paste the membership sheet into Drive, send the group email
(drafted: To Brian, 24 BCC, empty body), and submit, expected 4 September,
which keeps month 1 at November 2026. **Not submitted at close.** The day
opened by clearing the zbook blocker (78 uncommitted memory records committed
before any merge; see priority-queue item 2) and then produced this lane's
second ownership-of-action error in two days: a paste into the live Summary
Doc that was Shawn's step after his review. He named the error class and asked
for an inbox row, not a fix now. The roster gained a Title column (Sol's list
cross-checked against the verified worksheet; member-supplied titles preferred;
one title each), a Chair-or-Member Commitment column ordered chairs first, and
the Karlsruhe, SDSC, and TBC corrections. Asked whether the change log was
fully up to date, a re-check of every claim against the files found six wrong
(24 cited DOIs, not eleven; two SPEC DOIs, not four; no full reader's pass was
folded in; member-supplied titles unmentioned; emails drafted, not sent; two
addresses under confirmation), which became a scratchpad rule: re-derive every
count in a shared document from the artefact. Shawn sent the six confirmation
emails; Klump and Meyers replied within the day and their rows are applied. A
re-spaced deliverable timeline answering the Month 6 collision is written up
as a proposal only, with explicit plenary anchoring and P29 outputs at Shawn's
request.

**Artefacts touched** (data submodule unless noted)

- `notes/rda-ig/statement-of-work.md` + annotated copy: Title column and
  Chair/Member Commitment column, chairs-first order, Klump's division,
  Meyers's SDSC address (`5554bb8` → `03e32e9`, `d011e1f`). The annotated body
  strips to the clean file byte-for-byte.
- `notes/rda-ig/summary-and-description.md` + annotated copy: four local
  corruptions repaired against the live Doc (`b8a3728`); draft H1 dropped by
  Shawn (`10dee6f`).
- `notes/rda-ig/change-log.md` (new; from the Doc's docx export via pandoc):
  the 3 September section, corrected twice (`8d57b84`, `03e32e9`, `ede4cd1`).
  Paste boundary: from its heading to the rule before the 17 August heading.
- `notes/rda-ig/form-html/` (new): one HTML file per web-form field, tag-set
  checked; `build.py --check` proves the HTML was built from the current
  Markdown (`03b95f3`, `a9c591f`).
- `notes/rda-ig/ig-membership-2026-09-03.csv` / `.tsv` (new): the full sheet in
  the Drive sheet's row order (`5b379f5`, `d011e1f`).
- `notes/rda-ig/participant-titles.md` (verified; Sol cross-check reconciled),
  `email-drafts-2026-09-03.md` (sent; two replies), `timeline-proposal-2026-09-03.md`
  (new, `cfd1f92`, `43cd337`), `index.md` (state block current).
- `tasks/inbox.md`: ownership-of-action design row (`8b3b018`) and the RDA
  titles-run observation candidates (`07c7d8c`). `tasks/waiting-for.md`: four
  pending replies; the RDA decision row. `tasks/FOCUS.md`: Slot 3 current-state
  block, slot stays open until submission.
- `data/scratchpad.md`: paste-into-Docs is Shawn's step; oversized MCP results
  live on disk; re-derive counts from the artefact (`bf8cf06`).
- `memories/`: 78 zbook records rescued (`0519e6a`), merged (`b323978`).
- Gmail Drafts (unsent): the group email, To Brian, 24 BCC, subject "RDA IG -
  Documenting Generative AI Interactions in Research", empty body for Shawn.
- Public repo: this file; `global-claude-md/claude.md` unchanged today.

**Decisions made**

- **Ownership of action.** "Paste into Google Docs" and "send" in a brief are
  Shawn's steps. Claude reads Docs through the Drive connector only; no UI
  writes as a work-around. Repo changes stay autonomous (recoverable, bounded).
  The design work (markup in continuity and handoff prompts; lanes per model;
  workstreams per parallel session; beacon by default, prompt only on model
  change; narrow public-facing exclusion class) is an inbox row until after
  submission.
- **Titles.** One per person; member-supplied wording wins unless there is
  evidence of a recent change; short-form affiliations. Sangtani TBC (not
  "determined"); Bharathy stays ARDC in an individual capacity; Lane Senior
  Lecturer.
- **Commitment column.** Chair or Member only in the Statement of Work; the
  availability statements stay in the membership sheet.
- **Timeline.** Proposal only. Shawn rules with "apply it", with or without the
  Supporting Output clause in the month 12 milestone.

**Resume when RDA responds, or if anything changes before submission**

1. Start at `data/notes/rda-ig/index.md` ("State as at 2026-09-03"), then the
   top of `change-log.md`. Once Shawn has pasted, the live Docs, the form, and
   the Markdown are the same text; `python3 form-html/build.py --check` proves
   Markdown↔HTML sync; the annotated copies strip to the clean files.
2. Any change to roster or text: edit the Markdown, mirror the annotated copy,
   rebuild the HTML, add a change-log line, and Shawn re-pastes. Never write to
   the Docs or the form.
3. Three replies pending (Drummond email and title; Seal and Wharton titles);
   Klump, Meyers, and Kumar replied on 3 September and are applied. Apply
   later ones to both Statement of Work copies, the sheet, and the HTML.
   Drummond's address is the only one still unconfirmed; a bounce is her answer.
4. RDA cycle after submission: community review about four weeks, TAB four to
   six, Council two; endorsement about November 2026 = month 1. If submission
   slips past mid-September, re-anchor the plenary ladder (the 5 August
   change-log entry shows the arithmetic). Community-review comments become
   amendments; the comment set closed 24 August.
5. Still open, none gating: GRS Round 2 consultation response; a co-chair's forthcoming
   institutional change, recorded only in the private notes
   (`actions-2026-08-24.md` §H1), to be reflected by amendment when it happens; the timeline proposal (an
   amendment if adopted after submission); Google Docs API access, which Shawn
   will set up and which would let Claude edit Docs under the same ownership
   rule.
6. Infra to remember: the auto-sync on both machines pushed a parent pointer
   before its data commit twice today (dangling pointer until the next data
   push); the 2026-08-24 inbox row on `daily-sync.sh` covers it. A Drive
   connector search that returns nothing is not evidence of absence (it missed
   the 17 August group send).

**Evening addendum (3 Sep, after the close-out above)**

- **Gnana's final-review requests, both applied.** The Tier 2 candidate output
  *Research Grimoires Framework* now defines a research grimoire in its first
  sentence (a curated, tested collection of prompts and GenAI workflows; the Three
  Ps record what happened, a grimoire captures what is worth repeating) and the
  scope clause reads "including multi-modal models". Shawn applied both to the
  Doc and the Markdown; mirrored into the annotated copy, the HTML, and change-log
  items 7 and 8 (`5109cfc`). Gnana approved the definition.
- **Kumar's reply.** Haresh Kumar, Researcher, University of Vaasa, Finland replaces
  the H.K. Sangtani placeholder row (same email); Europe 6, no affiliation left to
  confirm; participant sentence and change-log roster item recomputed. Three replies
  pending: Drummond, Seal, Wharton.
- **Change-log status section rewritten with names** (`d5d7f93`) after Shawn's trim
  and a Claude insertion had merged into "two have replied" with three entries.
  Shawn's ruling: record names properly; **a co-chair's forthcoming move stays out**
  of the circulated log because its publicness is unknown, and it was scrubbed from
  this public file too (history left alone, by his ruling). Scratchpad rule added
  (`0949c33`).
- **Sheet rows paste from the TSV**, not the CSV (Sheets splits on tabs; the title
  cells contain commas).
- **An accidental paste into a generated HTML file** (wrong window in focus) was
  repaired by rebuilding; `build.py --check` is the guard.
- Still Shawn's: re-paste the Statement of Work Doc (Kumar row, participant
  sentence), the change-log Doc (roster item 5, status items 1 and 5, new items 7
  and 8), the sheet row, the form HTML; send the group email; submit.
- **4 Sep, morning: Shawn confirms all pastes and the group email are done and
  he submits this afternoon.** On his word "submitted": `/done` Slot 3, set the
  waiting-for row's Since to the submission date, and note the RDA confirmation.

### 2026-09-02→03 (Tue 2 → Wed 3 Sep, latest RDA) — THE PROPOSAL FOLD-IN LANDED, AN EMAIL WENT OUT THAT SHOULD NOT HAVE, AND A VERIFIER CAUGHT FIVE FABRICATIONS IN ITS OWN AGENTS' NOTES

Two days on the RDA Interest Group proposal, ending with both documents
edit-complete but **not submitted** and **not yet pasted back**. The fold-in
itself went to plan once a structural surprise was cleared: Crawley's nine
suggested edits were still *pending* in the Google Doc, so the Drive text view
showed them as body text while the saved document did not contain them, and two
of the three planned edits were targeting passages that did not exist. Accepting
the nine first, then editing on top, resolved it. The three edits landed as
specified — the gap claim sharpened rather than softened, the checking paragraph
rewritten once to close four separate items, and the jurisdiction-to-description
register sweep — plus four repairs that acceptance itself created. The ICMJE
Methods requirement was re-verified against the current Recommendations before
being asked to carry evidential weight, and all eleven cited DOIs resolved.

**The session's own failure was an email.** "ONE EMAIL" appeared in the task
brief and was read as authorisation to send; the reply to Crawley went out and
cannot be recalled. Shawn's correction was immediate and became a standing rule
plus, at his request, a hard enforcement layer. Both are now in place.

The last stretch produced local Markdown copies of both documents, annotated
review copies, and a verified participant-titles worksheet for the Title column
the template requires. **Verification changed roughly a third of the title
results**, and the durable finding is about method rather than people: the lookup
agents' *Notes* column carried five false statements while their *titles* largely
held. An anti-confabulation instruction aimed at the answer field did not protect
the prose explaining it.

Session ends mid-handoff on a cross-machine blocker: zbook cannot pull the work,
see priority-queue item 2.

**Artefacts touched**

- Live Google Docs (both) edited in place — nine suggestions accepted, three
  edits, four repairs. Still **stale on four roster and arithmetic items** until
  Shawn pastes the Markdown back.
- `data/notes/rda-ig/` — five new files: two clean Markdown exports
  (`3dd6fb1`), two annotated review copies (`404f9eb`, `d222737`), and
  `participant-titles.md` (`404f9eb` → `8e5a680`).
- `global-claude-md/claude.md` (`08e8311`) — standing rule: Claude never sends
  outbound messages; drafting is the deliverable.
- `settings.json` (untracked, per-machine) and `settings-template.json`
  (`2f6709f`) — deny rules on the Gmail send, reply, and forward tools. The
  three tools left this session's tool list immediately.
- `data/scratchpad.md` — four entries: two on Google Docs mechanics, two on
  proposer/verifier behaviour.
- Email sent to Crawley, thread `1a031cbff4661b6e`, message `1a06102d6cac604d`.

**Decisions made**

- Markdown round-trip with paste-back into the existing Doc becomes the working
  method for these documents, because it preserves version history and gives a
  diffable local copy. The Drive connector cannot edit document bodies at all —
  its only write paths are create, rename/move, copy, share, and trash.
- The Google Docs API is the right long-term tool and is **not set up**: no
  client library, no credentials, no existing Google API code anywhere in the
  repo. Shawn will set it up, but not now.
- Section C roster and arithmetic fixes were applied to the **Markdown only**,
  deliberately, so a single paste closes the gap.

*Most recent at top. One paragraph + bullets per entry.*

### 2026-08-22 (Sat), recorded late on 2026-09-03 — SLACK DASHBOARD BUILT AND RUNNING; THE GITHUB BOARD DIAGNOSED AS A MANUAL-REFRESH CASUALTY

**Out of date order deliberately.** The work happened on 22 August; the session
stayed open and only closed on 3 September, by which point five later entries
sat above this one. Recording it late is better than not recording it: nothing
in this entry appears anywhere else in the continuity.

**The GitHub Projects board was diagnosed, not fixed.** `commands/sync-board.md`
renders `data/tasks/*.md` to the board one-way and declares its trigger
**"Manual only — no automatic sync."** By 22 August the board's Focus column
named *"Marketing / outreach strategy session"* and *"EFN — BolgiaTen arc"*
whilst `FOCUS.md` and every banner said EFN / Move / RDA, and it showed 1
waiting-for item against 46. **Two independent failures**: wrong because
refresh was manual, unvisited because Shawn works through `gh`, git, and Claude
rather than boards. Automating the sync fixes only the first, which is why it
was rejected.

**A Slack canvas replaced it**, refreshed from the same markdown on every
session start via `scripts/daily-sync-trigger.sh`, ahead of its once-per-day
gate. No new store: `data/tasks/` stays canonical and the canvas holds nothing
not re-derived each run. `hooks/session-start-accountability.py` gained
`build_banner()` and `all_task_files_missing()`;
`scripts/publish-dashboard.py` reuses its parsers so the two surfaces cannot
disagree. Full detail and the Slack API findings:
**`wiki/docs/slack-dashboard.md`**.

**Four API assumptions were falsified by building it**, none documented: Slack
splits a canvas into one section per markdown block; `canvases.sections.lookup`
requires a filter and cannot express plain paragraphs; it rejects more than
three `section_types` per call; and **type filtering is simply unreliable** — a
rendered provenance line matched no type at all whilst `contains_text` found it,
and `list` returned four times the sections present. Publishes were measured
growing 9 → 11 → 13 operations with four provenance lines stacked up. The fix
was to shrink the document to a single table, after which five consecutive
publishes each cost 2 operations with the section count constant.

**Verified still healthy on 2026-09-03**, twelve days and 279 commits later: one
table, three sections, no accumulation. Script, tests, doc, and trigger wiring
all survived.

- `scripts/publish-dashboard.py`, `tests/test_publish_dashboard.py` (27 tests),
  `wiki/docs/slack-dashboard.md`, `scripts/daily-sync-trigger.sh`
- Canvas `F0BRX9EPY0N`; **bot-owned**, because canvas ownership is per identity
  and the bot got `canvas_not_found` on the MCP-created one
- `SLACK_BOT_TOKEN` and `SLACK_DASHBOARD_CANVAS_ID` on both machines
- **Kill criterion falls due 2026-09-05**: if Shawn has not opened the canvas
  unprompted in the second week, delete it and stop solving this with surfaces
- `claude-obs 61–63`; four user-obs candidates pending from 2026-08-22 and four
  more from today, all in `wiki/user-observations.md`

⚠ **Three carry-forwards this session could not safely close** — see the
"Things to verify" queue.


### 2026-08-25 (Tue, latest SOL) — PHASE 2 INSTRUCTION REFACTOR: SHARED.MD SPLIT, PILOT REPO EXTRACTED, AND THE 8 KiB BUDGET TURNS OUT TO BE 11.3

Phase 2 of `wiki/planning/sol-in-codex-integration.md` executed on the
Claude side. `global-claude-md/shared.md` is split into
`global-agent-guidance/common.md` (portable, shared editing surface, the
source Sol's installer composes into `~/.codex/AGENTS.md`) and
`global-claude-md/claude.md` (Claude-owned overlay). The split is verbatim
apart from five de-Claude-ification wordings and the ownership section,
which was rewritten because its original phrasing was Claude-first and
would have read backwards in Sol's instructions — the reciprocal statement
now sits in `common.md`, Claude's concrete blocked paths in the overlay. A
line-level check confirms every other non-heading line of `shared.md`
survives verbatim across the two files.

**The budget finding is the substantive result.** Plan §6 targets at most
8 KiB for the whole global `~/.codex/AGENTS.md`. Measured, the portable
core alone is **11,264 bytes** — over target before a line of Sol's
overlay. The budget was set before anyone measured the portable core, so
this is a finding rather than a regression. I did not compress it: every
route to 8 KiB (compress, tier into on-demand files, or revise the budget)
changes what is always in context, and a rule that is not loaded is a rule
that is not applied. Recorded in the plan, and put to Sol as options A–D
with the content question reserved for Shawn.

- **Composer** (`scripts/compose-global-claude-md.sh`): now layers common +
  overlay + local, reports byte sizes per source (the cross-harness budget
  is bytes, not lines), and no longer dies of SIGPIPE in `--dry-run` —
  piping into `head` closed the pipe early, which under `set -o pipefail`
  failed the whole script with exit 141. That bug predated this change.
  Composed output verified idempotent: 212 lines, 17,628 bytes.
- **Pilot repo** (`map-reader-llm`): shared policy extracted to
  `docs/agent-guidance.md` (10,653 B, either agent may edit); `CLAUDE.md`
  11,981 → 2,438 B, keeping only session archiving and the `map-reader` /
  `/phase-gate` / `/reflect` mechanisms. First commit used a prose "read
  this first" pointer, which quietly demoted always-loaded rules — among
  them "archive, never delete" and the sapphire compute rule — to
  read-if-you-remember. Second commit wires `@docs/agent-guidance.md` as a
  Claude Code import (verified in `~/.claude-code-docs/docs/memory.md`), so
  adherence is unchanged from before the split.
- **Agent mail sent** (two): the composer contract plus the measured budget
  with options A–D, and the proposed `AGENTS.md` text for `map-reader-llm`
  — proposal route, since `AGENTS.md` is Sol-owned under `ownership.toml`.
  Receipt written for Sol's `trusted-surfacing-live` message.
- **Exit criteria:** pilot-repo criterion met; no Claude-specific rules in
  `common.md` and no Codex-specific rules in the overlay (grep-checked, the
  only hits being the deliberate reciprocal naming); Claude-side chain
  verified. The 24 KiB max-chain and fresh-Codex-session criteria need
  Sol's installer and stay open.
- **Not done, deliberately:** no content compression of `common.md`; the
  Codex composer is Sol's to build; beacon items RESERVED FOR FABLE
  untouched.
- 1,170 PA tests pass. Artefacts: PA `9786a71`; map-reader-llm `6e335b52c`,
  `2bf12c6da`.

### 2026-08-25 (Sat 22 → Tue 25 Aug, latest SOL) — SESSION CLOSE (/handoff): SOL INTEGRATION PHASE 1 CLOSED WITH EVIDENCE; AGENT MAIL DESIGNED, RATIFIED, BUILT, AND LIVE BIDIRECTIONALLY; PHASE 2 ROUTED TO OPUS

The Sol-in-Codex infrastructure workstream ran end to end: Fable reviewed
the plan and Sol's review (verifying every checkable claim), Shawn's
rulings were recorded as single current policy, Phase 1 (reciprocal
ownership guardrails) was implemented and closed with attempted-write
evidence on both enforcement layers (Claude tool-layer, Codex OS), and
the agent-mail mailbox went from Shawn's "random thought" to live
bidirectional infrastructure in one day — proposal, Sol's revisions,
consensus, Shawn's loosening sign-off, PR #108 merged, activation, seven
read receipts. The trust norm passed its first live test: a relayed
request to run an unreviewed /tmp script against Sol's harness config was
paused, audited (clean), and handed to Shawn to execute — his verdict:
"that was the right call".

**MODEL-LANE ROUTING (beacon — Shawn's instruction, 2026-08-25; Fable
credits exhausted until ~27 Aug):**

- **Next session (Opus): execute Phase 2** of
  `wiki/planning/sol-in-codex-integration.md` §10 — instruction refactor.
  Split `global-claude-md/shared.md` into portable
  `global-agent-guidance/common.md` plus a Claude overlay; update
  `scripts/compose-global-claude-md.sh`; coordinate the Codex composer
  and the 8/24 KiB budget with Sol (agent mail is live — use it);
  pilot-repo shared-policy extraction (map-reader-llm). Well-specified,
  criteria-driven, design decided — deliberately Opus-suitable.
- **RESERVED FOR FABLE** (queue, do not attempt in Opus sessions):
  (1) ownership/trust-boundary adjudications and cross-agent disputes;
  (2) changes to the trust norm, credential grants, or security posture;
  (3) the Phase 6 routing review and division-of-labour retro;
  (4) Phases 7–9 single-writer memory-service design review / pre-run
  review; (5) reviews of Sol proposals where a confidently-wrong verdict
  is expensive.

Carry-forward:

- [ ] **Sol's agent-mail close-out** (Sol-side, in flight): the
  `codex-claude-agent-mail` OS case, trusted/restricted profile surfacing
  attempts, results into
  `gpt-hub/integration-records/2026-08-25-agent-mail.md`, receipt for the
  eighth message, and committing `/tmp/sol-agent-mail-activate.py` into
  `gpt-hub/config/` for provenance.
- [ ] **`.env.bak` cold-storage decision** parked with Shawn (four
  timestamped credential backups beside PA/.env; read-fenced for both
  agents since 2026-08-24, but fencing ≠ shrinking the surface).
- [ ] **`~/worktrees/personal-assistant/sol-phase1-merge`** still on disk
  at 632dd8a — Sol's to remove.
- [ ] **Claude settings are machine-local** (settings.json gitignored):
  amd-tower now carries Edit-only ownership denies (incl.
  `~/agent-mail/codex/**`), `.env` variant read denies, and the agent-mail
  SessionStart hook. **zbook has none of these** — replicate when Claude
  next runs there.
- Scratchpad and `notes/_inbox.md` appends left uncommitted in the data
  submodule for daily-sync (deliberate; other sessions' pending content
  shares those files).
- Working-notes candidates from this session held over if ungated at
  close (see handoff message of 2026-08-25).

Artefacts: plan reviews/rulings `0b7c7d8` `f0197f6` `03cd9b0` `485ce7b`;
`/process-email` guard `7f20329`; Phase 1 close `c2b10f4` (exit-test merge
`779d6af`, PR #107 merge `632dd8a`); agent-mail proposal v2 `93dab64`,
Claude side `7371a84`, policy PR #108 merge `6857ef1`; gpt-hub
implementation `b010436`; Codex transcript-adapter backlog row (pa-data
`56471d0`). Governing docs: `wiki/planning/sol-in-codex-integration.md`,
`wiki/planning/agent-mail-proposal.md`,
`global-agent-guidance/ownership.toml` (active, schema 2, 9 rules,
18 cases).

### 2026-08-26→28 (Wed 26 → Fri 28 Aug, latest PA) — THE FIRST SALE, THE SLOT THAT WAS NAMED WRONG, AND A NOVELTY CLAIM I HAD BACKWARDS TWICE

Three-day session across two standups, a recap and a re-plan. **Slot 2's flat line broke and
the instrument measuring it turned out to be the problem.**

**1. ⭐⭐ FIRST SALE OF THE INVENTORY, AND THE BURN-DOWN MOVED 5 → 7 LISTED / 1 SOLD.**
GRR-RIPPERs at **$120, full posted price, no counter**, buyer paid $20 postage. ⭐ **The ask had
been corrected DOWN from my $170 — 42% too high, above the price of a new pair — and the
corrected figure sold to the first serious enquirer.** *Establish the new price first* now has
a transaction behind it. **The car went live on all channels including Carsales; the mitre saw
was identified, drafted and listed, completing BATCH A.** **Two offers arrived at 72–77% of
ask, which brackets the pricing: too high yields 50% offers or silence, too low yields instant
full-price takes.**

**2. ⭐⭐ SLOT 2 WAS RESCOPED, AND THE OLD NAME HAD BEEN HIDING THE MOST VALUABLE WORK IN THE
PROJECT.** Named *"everything that sells online is POSTED FOR SALE ONLINE"*, it could not see
4.0h spent on a **~$1.0M house decision**. ⇒ Now **"Move — HOUSE SOLD AND CONTENTS GONE, by
~1 Oct."** **Not a repeal of the name-per-task convention** — the move has a hard end date and
a definite completion state, so the project *is* the deliverable. ⚠ **Cost named in FOCUS.md:
a broader slot is easier to feel busy inside, so the burn-down stays as the sub-metric admin
cannot satisfy.**

**3. ⏰ THE HOUSE. Karen will not discuss price before her solicitor's review**, despite Shawn
conceding in writing that a material contract issue would adjust it; **the agent does not
understand it either.** ⇒ **RULING: if she will not talk by Mon 31 Aug, go to market with
Bart.** ⚠⚠ **That obligates $5,300 — and Monday is effectively the LAST START DATE at which a
26-day campaign completes before the 29–30 Sept departure.** A week's slip moves the outcome
from ~$1,019k net to ~$982k or ~$945k. ⏰ **Ask Bart whether the fee triggers on SIGNING or on
PUBLISHING.**

**4. ⭐⭐ MAP-READER: I HAD THE NOVELTY CLAIM BACKWARDS TWICE, AND SHAWN WAS ABOUT TO SOFTEN A
STRONG RESULT ON MY ANALYSIS.** I compared his **point-feature** F1 ~0.85 against **polygon and
line** numbers and called it unremarkable. **The only comparable point-feature figure in his
105-item corpus is 0.73** — which itself required *"abundant annotated data"* and a
human-in-the-loop. ⇒ **He is ~12 points above it, calibrating on 20 tiles in a couple of hours
with no weight updates.** **Held-out evaluation CONFIRMED**, so forking-paths is answered not
merely disclosed. ⚠ **The $100 is deployment cost; discovery was a $6k preregistered search —
which is the contribution, not the embarrassment.** Full note:
`wiki/planning/map-reader-priority-and-scoop-risk-2026-08-28.md`.

**5. ⭐ RDA §K STAGED, AND THE SIXTH DATE IS TUE 1 SEPT.** Crawley's reply folded in; **six asks
reduced to THREE EDITS, one check, one email.** **K1 raised to blocking** — the *"no shared
cross-domain standard"* claim is wrong as written and he predicts TAB will catch it; **the fix
is to SHARPEN, not soften.** ⚠ **The calendar block existed from Mon 24 and I called it
unevidenced twice while holding the calendar tool.** ⏰ **Tue 1 Sept IS the secretariat
premise's expiry date — the block sits on its last day, and there is no seventh date with a
reason.**

**Held over / open:**

- ⏰ **Both Friday triggers fired and produced nothing: the Red Truck quote never arrived and
  Mohan never replied.** ⇒ **Phone calls early next week.** ⭐ **Third instance of the same
  lesson — the accountant row already records that PHONE WORKED WHERE EMAIL DID NOT.**
- ⚠⚠ **The container is now TIME-BOXED: Portabox's quote lapses ~1 Sept, Red Truck's has not
  arrived, and Monday carries applications plus the house.** **A lapsed Portabox with no Red Truck
  leaves NO priced option — the PODS quotes died exactly that way.**
- ⏰ **Both applications due COB Mon 31.** **Sequenced by COMPRESSIBILITY, not speed**: AFCA is
  compressible (AI allowed, ground covered) so it goes LAST; Arcadia's no-AI reading is
  incompressible. **Reading Sat evening → draft Sun → revise Mon.** Three calendar blocks
  created.
- **US taxes: 2023–24 done and paid; 2025 input sent; the Oct extension CONFIRMED from Shawn's
  own IRS account to cover 2025.** ⚠ **Real deadline ~25 Sept, not 15 Oct — the statutory date
  falls a fortnight into Melbourne, mid-unpacking.**
- ⚠ **EFN's fine-grained website pass still unscheduled** — planned three times. **It is the
  only thing between Slot 1 and closing.**
- **Red Truck: 20' container, ~30 m³, $12/day, boxing at an hourly rate.** **Cheaper per m³
  ($250 vs $390), dearer in total.** ⭐ **Included loading may close the packers row — the most
  exposed dated item in the move.**

**Hours: 6.5h Wed 26 · 6.5h Thu 27 · 5.75h Fri 28. W35 to date 36.25h** (move 16.25 · efn 8.25
· map-reader 5.75 · rda 2.5 · pa 1.75 · career 1.0 · personal 0.75).

### 2026-08-23→26 (Sun 23 → Wed 26 Aug, latest PA) — W34 REVIEW RUN AT LAST; ALL THREE OPEN MOVE-PROVIDER QUESTIONS RESOLVED; AN EMAIL REGISTER BUILT FROM SENT MAIL; AND AGENT COMPRESSION FINALLY GOT A NUMBER

Four-day session across two standups, two recaps and the deferred weekly review.

**1. 📋 THE W34 REVIEW RAN** (`reports/weekly/2026-W34.md`) — deferred Fri→Sun and then
past Sunday. 46.75h, ~22 completions, **zero slot closures**, three collaborator
reports. **Amended same-day when Shawn caught two closures it had missed.**

**2. ⏰ RDA IS FULLY STAGED AND HAS A BLOCK.** Feedback enumerated from **31 emails plus
the Drive suggestions**; accept/reject calls on all nine of Crawley's items; a reader's
pass over the Statement of Work; **blocking work separated from improvements in §G**.
**Both emails sent Tue.** ⭐ **Everything is in `data/notes/rda-ig/` — `index.md` is the
pick-up point and assumes no prior context.** **Crawley accepted as an eighth
co-chair.** The GCPA-SIDCER claim resolved via Sol (deposited on Zenodo 16–22 Aug,
which is why it was unfindable on the 24th). ⏰ **Block: Sat 29 Aug 10:00–13:30.**
Day 21 fell Thu 27 under the **progress exception** — confrontational, not abandon.

**3. ⭐⭐ ALL THREE OPEN MOVE-PROVIDER QUESTIONS RESOLVED.** **Container:** Portabox
**Medium 19 m³ @ $289/mo** local (Blacktown depot), **swap rights to Large**,
deliverability confirmed **with the driveway measured during the call** (4 × 8 m),
fee-free unlimited access, **~$6,007 committed**. ⚠ **Its quote proved LINE-FOR-LINE
IDENTICAL to PODS**, voiding the 19 Aug decision that had compared Portabox's
*advertised* $219 against PODS' *quoted* $349. **Kerbside MOVED to Mon 28 Sept and is
the ONLY pickup** ⇒ the sale reverts to **19–20 Sept**, undoing a 12-day compression.
**Sixth departure date: drive 29–30 Sept BY VAN**; car handover Mon 28. **Red Truck
estimator visits Thu 27** to size the container — retiring the volume problem that
four successive checks kept enlarging.

**4. ⭐ EFN DELIVERED.** No page copy on Sunday → a built Astro site, curation closed,
agenda built, leadership meeting held Wed. ⚠ **Steve is AI-sceptical and attributes
delays to the LLM-intermediated approach** ⇒ the site is **evidence in a live argument
about the method**, not just a deliverable.

**5. ⭐ AN EMAIL REGISTER, DERIVED FROM SENT MAIL** —
`data/notes/style-guides/email/reference_register-email.md`. Two load-bearing rules:
**draft at the FLOOR** (adding warmth takes seconds; removing hedges takes minutes),
and a **three-way hedge test** — epistemic and cost-of-no hedges stay, status-lowering
ones go.

**6. ⭐⭐ AGENT COMPRESSION MEASURED: 16–24× on drafting** (8–12h → 0.5h), **confirmed
twice in one day in unrelated projects.** **Principle: compression is available where
the SPECIFICATION ALREADY EXISTS and the work is mechanical execution against it — not
where the specification is what you are producing.** ⇒ **Curation is not overhead; it
is what turns work into a compressible step.**

**Held over / open:**

- ⚠ **`scripts/daily-sync.sh:500` does `git add -A`**, sweeping prose files into
  generic auto-commits **against the script's own documented invariant**. Captured;
  Shawn wants it fixed as drive-bys after EFN.
- ⚠ **Slot 2 burn-down stuck: 5 of 30 listed, ZERO sold, since Sun 23.** The car —
  worth more than the other 29 rows combined — was carried four days.
- **Sol ↔ Claude agent-mail COMPLETE**, the same day Fable credit ran out; it
  immediately carried three research tasks. Credit exhaustion costs **1–2 working
  days a week**.
- ⚠ **Contract did not arrive** as promised Tue. **Packers still unbooked**; notice
  line **Thu 3 Sept**.
- **Paywalled retrieval diagnosed as EZproxy hostname rewriting** — the backlog row
  carries the rule and the routes.
- ⚠ **Verdict backlog untouched** — user-obs and working-notes candidates carried since
  2026-08-19; **wiki curation deferred a sixth time**, with a ~20-row llm-craft cluster
  now the ripest the notes inbox has held.

**Hours: 7.5h Mon 24 + 10.0h Tue 25 + 3.75h Wed 26 (partial).**

### 2026-08-20→23 (Thu 20 → Sun 23 Aug, latest PA) — SESSION CLOSE (/handoff): THE MOVE SPINE MOVED FIVE TIMES AND THE FIFTH ONE HAS A REASON; 41 MEMORY RECORDS WERE RECOVERED FROM A LOSS NOBODY HAD NOTICED; THREE FALSE ALARMS TURNED OUT TO BE THE SAME MISTAKE

Four-day session across two standups and two recaps. **Three things were repaired that nobody
knew were broken, and the week's biggest finding is a shape rather than an incident.**

**1. ⭐⭐ THE MEMORY SYSTEM HAD SILENTLY LOST 41 RECORDS AND ITS OWN GATE READ CLEAN.** Opened as
*"I think the postgres datastore is broken?"* — it was not; **it was the only surviving copy**.
38 records existed in PostgreSQL and nowhere else, 3 more in a July stash and nowhere at all.
**Cause: `daily-sync.sh` stashes uncommitted data-submodule changes before pulling, the
extraction hook appends continuously, and on 2026-08-19 a run was killed between stash and pop.**
It runs as a **SessionStart hook child with a 90s timeout**, so ⚠ **the existing `EXIT` trap could
never have saved it** — a killed shell runs no trap. **⇒ Recovery had to move to the START of the
next run**, which is what shipped: `scripts/check-memory-drift.py` (two loss paths, PG-only and
stash-only) wired read-only into daily-sync, plus append-only files now **committed rather than
stashed**. Parent `3ad6fa6`; recoveries `data` **108d044** and **43fcd15**.
⚠ **The rebuild the backlog prescribes would have destroyed all 38** — a rebuild treats JSONL as
complete by definition. That trap is now recorded.

**2. ⭐⭐ THREE "FINDINGS" THIS WEEK WERE THE SAME ERROR: A PARTIAL VIEW OF A SPLIT POPULATION,
MISTAKEN FOR THE WHOLE.** (a) A reported **12-week hole in the session archive did not exist** —
a `*.jsonl` glob missed every `*.jsonl.gz`, and map-reader is archived under **two slugs**
(`map-reader-llm` to 27 Jul, `vlm-burial-mound-detection` from 23 May). **I made the same error
first and was one command from reporting a SEVEN-month hole.** (b) The memory drift signal was
buried under **4,684 legitimately archived records**. (c) **Two different settlements** — family
court (~25 Sept, the gate) and property settlement (12–30 Oct) — were being treated as one, and
Shawn caught it. **⇒ Brief for Fable: `wiki/planning/cc-archives-health-and-hardening-2026-08-22.md`,
since acted on.** ⭐ **The generalisation is the valuable part: a signal emitted but not surfaced
is indistinguishable from no signal** — both gates were working and reporting to stderr nobody
reads.

**3. ⏰ THE MOVE SPINE MOVED FIVE TIMES, THREE OF THEM IN ONE DAY, AND THE FIFTH HAS ITS REASON ON
FILE.** ~15 Sept → 25–30 Sept → Mon 21 → Sat 19 → **Sun 27 Sept**. Reason (Shawn): the extra week
is nearly free because **the cancelled cosmetic works had already booked it**, and a Sunday start
makes the drive an easy multi-day run with Lishan on cheaper Sun–Wed lodging. **Whole spine
shifted a week; packing Mon 21 – Sun 27 Sept; new `notes/move/{timeline,packing-week-plan,contacts}.md`,
with `timeline.md` canonical for dates.** ⚠ **The weekend slack protects the DRIVE, not the
container load** — the container leaves Friday, so the Mon 28 unattended-collection request is the
only slack in that chain.

**4. ⭐ THE CONVEYANCER RESOLVED, AND THE CONTRACT CARRIES THE HEDGE THE FILE HAD WANTED SINCE
19 AUG.** Presence **not required** for completion; contract **prepared**, held on one NSW
document. **The title-clearance clause lets exchange happen before the title clears, so the
42-day completion clock runs IN PARALLEL with the court process — worth 18–28 days**, and it
answers *"can Brent exchange now and settle later?"*, which the file had carried unasked.
⏰ **Exchange is "free" until ~4 Sept.**

**5. ⭐ SLOT 2 BROKE ITS FLAT LINE: 2 → 5 OF 30, three listings in one day, $2,075 live.** Freud
dado $170, MICROJIG GRR-RIPPERs $120, Makita saw + WST03 $695. ⚠ **And my price estimates ran
high on 3 of 4** — drill press 25% over, dado 47%, GRR-RIPPERs 42% **and above new retail**; the
saw exact. **The saw is the only one anchored to NEW PRICE rather than to the item's qualities.**
**⇒ Rule now settled: establish the new price first — it is the ceiling.**

**6. Substack: the blocker was composition, not setup, and it broke.** Arc across **six posts**
(Paper B arc + an intro), quotes pulled, register work begun via lit scouts. **`~/Code/substack`
created — private, Brian invited, branch+PR gated.** ⚠ **Scoped, not drafted.** **Six is the
number that covers the move**; the binding deadline is **drafting all six by ~20 Sept**, not
publishing. **Sol-in-Codex plan drafted** and its allow-list corrected by Shawn's ruling
(collaborator presence is *not* a Sol gate; only `personal-assistant` is restricted).

**Held over / open:**

- **📋 THE W34 REVIEW HAS NOT RUN** — deferred Fri → Sun, and Sunday closed without it.
  **Inputs assembled at `reports/weekly/2026-W34-PREP.md` so it need not be rebuilt.**
- ⚠⚠ **RDA is on its FOURTH date (Mon 24 Aug) and `SYSTEM.md` sets `escalation_abandon_day = 21`.
  It rotated in 2026-08-07, so it hits Day 21 on Thu 27 Aug** — if Monday slips, the next standup
  is an abandon conversation by the system's own parameters.
- ⏰ **Mon 24:** RDA **first thing** → **council call** (kerbside 7 → 21 Sept **and** the container
  road-occupancy permit — **gates advertising the moving sale**) → **packers** (notice line
  Thu 3 Sept). **Mon/Tue/Wed are the ENTIRE EFN runway** to the ~26 Aug commitment.
- **⭐ AFCA re-sequenced BEFORE Arcadia** — undated rolling posting; Arcadia's 31 Aug is safe to
  defer, an invisible deadline is not. Proposed **Thu/Fri, 2–3h**.
- **Facebook groups requested; Gumtree cross-posts live.** ⏱ **Re-check insights ~5 days after
  the GROUP posts appear, not 5 days from now**; step-downs stay gated on **≥50 clicks**.
- ⚠ **STILL AWAITING A VERDICT, carried since 2026-08-19 across four sessions now: four user-obs
  candidates and two working-notes candidates** (auto-gamma clamp; comparables-checks-correct-in-
  both-directions). Per no-silent-discard, re-surfaced again.
- ⏰ **Playfair Display still needs `sudo cp ~/Downloads/playfair-display-static/* /usr/local/share/fonts/`**
  — needs Shawn's password; carried since 2026-08-19.

**Hours: 46.75h over the week** (move 16.00 · efn 10.00 · map-reader 7.50 · career 4.50 ·
substack 4.50 · llm-repro 1.75 · personal 1.25 · personal-assistant 1.25).

### 2026-08-22 (Sat) — Citation-deletion bug fixed; credentials reconciled across machines

Ran from a `fieldmark-docs-staging` session, so the fieldmark-side work
(Macquarie, BolgiaTen) is logged there; this entry covers the PA work.

**The lit-scout verifier no longer deletes citations it could not
check** (`cef6a5e`, Tier 1 item 1 of the 2026-08-21 politeness audit,
and the surviving half of D-X4). The deletion path was narrower than
the audit described: `agents/lit-scout.md` already preserved
unverifiable rows, but the verifier was **manufacturing** a
`doi_resolves` FAIL from an all-unverifiable row, and the proposer then
correctly removed a row it had been told was fabricated. A
`doi_resolves` FAIL now requires a status code actually seen and
re-checked with `curl`, since `lit-search.py metadata` renders 404 and
429 identically. **The `unverifiable` token was deliberately not
renamed** to the audit's `undetermined`:
`scripts/lit-scout-zotero-import.py:1190` and `:1247` membership-test
the literal tuple, so a rename would have stripped the Zotero review
tag from exactly the rows needing it. Its definition was fixed instead.

**OpenAI keys resolve from the hostname** (`fb99205`).
`scripts/_openai_key.py`; `bulk-archive.py` and `bake-off-metadata.py`
had read `OPENAI_API_KEY_PA_AMDT` unconditionally and so could not run
on zbook at all. 26 tests, suite at 1143. Verified live on both hosts.

**`.env` reconciled across zbook and amd-tower** at Shawn's request,
compared by salted value-hash so no secret entered the session. **A
straight copy would have been destructive** — three keys hold
deliberately different per-machine values. Both files now hold 26 keys.
Shawn confirmed the per-machine practice for paid services and asked
for a rigour audit later. Five machine-agnostic keys synced;
`ZOTERO_SUBSTACK_AI_COLLECTIONS` renamed to `..._GROUP_ID` on both
after its 7-digit value contradicted its name.

**A sweep found six `.env` files** under `~/Code` plus PA's, four of
them mode `664`, now all `600`. `~/Code/FAIMS3/tests/.env` is tracked
and unignored in the shared upstream repo — currently harmless (all
credential fields empty) but a hazard if ever populated locally.

- `wiki/docs/env-cross-machine-reference.md` — new; what differs by
  design, and why a copy is the wrong instinct
- `scripts/env-fingerprint.sh` — promoted out of the scratchpad; takes
  an optional path
- `global-claude-md/zotero-reference.md` — audited complete for PA's
  `.env` (17/17), and bounded: it describes five of at least seven
  Zotero keys, the rest being project-local
- **Correction made at handoff**: I had recorded that amd-tower cannot
  reach GitHub unattended. Wrong — the parent repo is HTTPS and fetches
  fine; only the `data` submodule's SSH remote fails. With
  `-c submodule.recurse=false` the resolver was landed there without
  Shawn. Doc corrected; `claude-obs 51`.
- **Observation gate: four user-obs candidates pending** in
  `wiki/user-observations.md` (2026-08-22 section). `claude-obs 51–53`
  written. Three wiki candidates in `notes/_inbox.md`.
- **Left uncommitted deliberately**: the `data` submodule carries a
  concurrent session's dirty files plus this session's inbox row and
  wiki candidates. Do not sweep.

### 2026-07-27 (Mon, latest AR) — WIND-DOWN (light): shared-group write ruling recorded; work moves to amd-tower

Light wind-down by design (full /handoff ran for AR on 2026-07-24, and
everything since was committed with continuity entries in real time —
nothing lives only in this session). Shawn ruled the shared-group
question the parked notes were waiting on: FAIMS-Project always
writable (owner); SDAM-AU limited to the `SPA` collection. The
executable work package — key minting (Shawn), multi-library routing in
`sync-to-zotero.py`, quarantine replay, attachment re-point — is fully
specified in the 2026-07-27 verify-queue entry above. AR next steps
unchanged (workstream-I table): SSH-hedging stress test before first
adversarial use, then §3–§8 hardening runs. Session close: zbook →
amd-tower; weekly-review + rituals resume there.

### 2026-07-24 (Fri, latest AR, decision review) — six outstanding decisions ruled; tranche-8 amendments live; write-back diagnosis corrected + repaired

Same session as the apparatus build, continued. Shawn reviewed the
outstanding-decisions queue one at a time; all six ruled and executed:
(1) hallucinated-objection taxonomy **confirmed as built**; (2)–(4) the
three tranche-8 advisory flags **amended per verifier** (paper-b
`e6d497d`; stale Zotero notes deleted + re-pushed; olofsson positioning
watch-item kept); (5) **PR #22 merged** (`d23fbfc`); (6) Zotero
write-back — the 2026-07-15 group-library diagnosis proved WRONG on
first live attempt (404 in the paper-b group too); read-only probes
across all accessible libraries located the 5 pending targets in THREE
libraries (FAIMS-Project / SDAM-AU / personal). Re-ruled: **personal
now; park shared**. Implemented env-driven library targeting (default
personal + `ZOTERO_API_KEY_PERSONAL`), 409-parent-not-found parks
instead of failing, focused audit of the change (F1–F5 fixed incl.
config-error exit code); live run `created: 1` / parked 4 / cursor
advanced — the May backlog is clear. Details + recovery paths in the
verify-queue entries above. Lesson for the error-mode ledger: the
2026-07-15 entry inferred "group library" from 404+403 without probing
the other groups — a diagnosis recorded as likely became a ruling
premise; the fix survived contact with the API for one item in five.

### 2026-07-24 (Fri, latest AR, 2nd session) — apparatus BUILT: /review-paper skill + portable workflow + mechanical pre-pass; 3-agent audit, all findings fixed

Second AR session of the day. **The apparatus itself is built** — the
Paper B prototype (`adversarial-review-s3.mjs`) generalised into three
components in this repo (commit `171fa07`): the `/review-paper` skill
(orchestration protocol: parameters → free mechanical pre-pass → API
gate → dispatch → verify-contested-findings with the hallucinated-
objection taxonomy → triaged three-tier report + provenance stamp →
apply-phase rules), `scripts/review-paper-prepass.py` (deterministic
pre-pass, 9 checks + settled-rulings register extraction; lives outside
the workflow because the Workflow sandbox has no filesystem), and
`scripts/workflows/review-paper.mjs` (fresh-context panel; both stances,
both scopes; Devil's-Advocate hard-rule fields schema-required in
adversarial mode; `[UNANIMOUS-CHECK]` devil's advocate on a clean panel;
meta-reviewer that critiques findings but never overrides the
deterministic verdict; model pinned at dispatch, default
`claude-opus-4-8`). Skill symlinked into `~/.claude/skills/` and
registered. **Three-agent /audit** (one per file, cross-file contracts in
scope) returned 3 Critical / 9 Medium / ~17 Low — headline: the settled-
rulings register was keyed relative but looked up absolute (silently dead
feature, confirmed by all three agents independently); aux-label check
collided across counter types; wrapped citations went unchecked; an
invalid `lensSet` would have produced CONFIRMED on zero review. All
fixed; every fix re-verified empirically against fixtures + real Paper B
sections — which caught one new bug the fix round itself introduced
(texcount `(errors:N)` trailer parsed as the word count). Spec updated
with build record + import rulings (`c2782e5`): DA hard rules, meta-
reviewer, SSH stress test ruled in via the build instruction; taxonomy
adopted as vocabulary (CC's call, flagged for confirmation); calibration
harness + refchecker unchanged.

- **Next session:** run the SSH-hedging stress test (REQUIRED before
  first adversarial use; procedure in SKILL.md §"Calibration gate");
  then critical-friend hardening runs over Paper B §3–§8. AB+ self-heal
  chaining (build plan step 4) still open.
- Carry-forward unchanged from the morning session: paper-b PR #22 open;
  3 advisory tranche-8 flags await Shawn's ruling; local Zotero SQLite
  lags the 113 API writes until the client syncs.
- PA commits: `171fa07` (apparatus), `c2782e5` (spec), + this continuity
  update.

### 2026-07-24 (Fri, latest AR) — SESSION CLOSE (/handoff): adversarial-reviewer kickoff — prior-art PASS, AB+ substrate complete (75/79), model-provenance convention shipped

Workstream-AR kickoff session, parallel to the day's PA-hub standup session.
Full arc: **prior-art scout loop** (`/prior-art-scout-iterate`) to PASS (24
candidates, 117 API-verified claims; PeerGenius.ai identified as the
commercial analogue; verdict build-informed-by; report committed `1efdcac`,
six design imports in the spec awaiting ruling). **AB+ audit chain**
(proposer → independent re-check → corrected v2) established coverage ground
truth and caught its own errors (`\citealp` regex; a Zotero sync race that
mimicked a join bug). **Model-provenance forensics**: 68/93 existing entries
Opus-4.8-made, 25 Fable-made; commit trailers + session metadata proven
stale across a mid-session model switch — per-message transcript fields are
the only reliable attribution. Convention (pin at dispatch / stamp at render
/ transcripts are truth) landed in the spec, `/audit-config`, and
`/phase-gate` (`53b3b57`). **Paper-repo build via gated PRs**: #20 (pin+stamp,
HTML-snapshot sources, tracked note-push re-authoring, provenance record,
hardened by a 3-agent `/audit` — 5 Critical/8 Medium found and fixed, incl.
POST-200-with-failed-map and a dry-run-only idempotency hole) and #21
(title-markup join fix + deterministic citation-context seed) merged; #22
open. **Tranche 8 generated and pushed**: pilot + 38-agent run
(`wf_deb1127b-09f`, `wf_6de9969c-341`; 3.12M subagent tokens; 583/583
messages on the pinned model), 117/117 quotes deterministically verified,
17/20 verifier-clean; Zotero batch live — 20 notes created + 93 provenance
back-fill stamps, zero failures. **AB+ cited-key coverage now 75/79
(94.9%)**; the 4 uncovered are explicit rulings. Also: cited-tags
reconciled to `assembly/` (3 flips, 2 adds), Böckeler duplicate trashed,
films excluded from AB+ by ruling. Next session: build the apparatus itself
(`/review-paper` skill + portable workflow).

- PA commits: `1efdcac` (prior-art report), `566d506` (spec: scout findings
  + AB+ status), `53b3b57` (provenance convention + gate checks), `ae887f8`
  (substrate complete), + reflections/continuity/observations commits at
  close.
- Paper-b: PR #20 (6 commits, merged `76f1484`), PR #21 (merged `2f74666`),
  PR #22 (open); seed `f93a231`; tranche 8 `85e1e88`; manifests `7600fec`.
- Working-notes candidates HELD OVER (no verdict yet, per no-silent-discard):
  (1) measured AB+ per-source cost on Opus 4.8 — pilot 158.8k, run avg
  ~164k subagent tokens/source; (2) attribution-reliability ordering
  (per-message transcript > commit trailer = session metadata > artefact).
- Session id: a5a760a8-01d0-499d-bad1-f702289ebae8.

### 2026-08-22 (Fri, latest SA) — HARDENING SESSION: false 12-week hole closed at the defect class; storage invariant normalised; reconciliation check shipped (caught 2 live leaks); gates moved to a channel that is read

Fable session responding to the health brief
(`wiki/planning/cc-archives-health-and-hardening-2026-08-22.md`); full
record + the brief's nine questions answered in
`wiki/planning/cc-archives-hardening-outcomes-2026-08-22.md`. Highlights:
storage invariant ruled + normalised to gz-only on local AND canonical
(157 compressed, 35 identical duals removed, 0 divergent; full 6,278-file
`gzip -t` sweep 0 corrupt); toolkit archives gz-by-default with round-trip
verification and an identity guard (`a5f4680`); daily-sync **self-mounts**
rpi-shares (the "dead path" was manual-mount-dependence: 25 successes /
30 skips, not 4); `check-archive-drift.py` = the source↔destination
class-fix, first run caught **2 leaked substantive sessions** (archived
same day, --stats-only); B7 indexer fix landed (re-index still
double-gated); Syncthing repaired AND its recurrence closed (eCryptfs
boot race → login-time bind-heal user unit) — and corrected on the
record: **Syncthing never replicated cc-archives** (personal docs only).
Shawn's rulings: map-reader-llm canonical (CLAUDE.md fork source fixed,
map-reader `703c28af`; alias map `data/config/project-identities.json`);
transparency spec AMENDED not restored (Amendment 1); gates surface via
session-start **stdout** relay (stderr provably never reached anyone).
Six inbox rows dispositioned; archive-integrity session agenda shrunk to
the placement/duplicate rulings that are genuinely Shawn's. Residuals in
the outcomes doc §Residuals — zbook normalisation is the load-bearing one
(new inbox row). Commits: PA `e6ccfef` batch, data `3a4aea6` batch.

**Close-out addendum (same day, later).** The residuals shrank to nearly
nothing before the session ended. (1) **SSH root cause found and wired
shut**: the session ran over SSH from zbook, so hooks saw a forwarded
agent without amd-tower's GitHub key (`IdentitiesOnly` + passphrase);
PA + pa-data remotes switched to HTTPS with per-repo `gh` credential
helper — full daily-sync verified over it, zero SSH involvement.
(2) **zbook executed remotely same day, its inbox row dispositioned**:
mirror normalised (all three stores now identical — 1,133 metas, ZERO
raw transcripts), self-mount verified live there, and two unplanned
rescues — **27 stash-only memory records recovered** from July stashes
via `check-memory-drift.py --recover` (never pop against a moved base),
and one leaked fieldmark session archived when the new drift gate fired
on its first zbook run. (3) **amd-tower 26.04 rebuild (weeks away)**:
full-disk LUKS will dissolve the eCryptfs boot race, so the
native-Syncthing alternative is DROPPED (Shawn); pre-wipe checklist
captured as an inbox row — the raw `~/.claude` transcripts are the one
wipe-time data risk. Lesson banked twice today: a `git pull` that
prints "Updating x..y" can still have ABORTED on dirty append files —
read the full output, not the tail, before diagnosing phantom actors.
Later commits: map-reader `703c28af`, toolkit `a5f4680`, data
`7bfe268`/`4897d7f`, PA `1d527d5`.

### 2026-07-22/23 (Wed/Thu, latest SA) — reflect schema 2; abductive corpus anchored 29/30; convergence repair; sync pass 4 + completeness gate; system wiki page

Continuation of the SA session. /reflect review → **schema 2**
(`aeb2897`): mandatory session-id anchors + instance field on
abductive entries, mandatory skip assessments, prompt-rotation guard
("surprised" had collapsed to ~100% selection). Retro-matching agents
anchored the full abductive corpus; a convergence repair (all
machines) then resolved every gap but one — **29/30 records
transcript-confirmed**, sole loss paper-b 2026-07-02 daytime. Root
cause of the gaps: daily-sync's cc-archives passes never pulled
transcripts down; **B7 decided + implemented** (`c2c75b4`): pass 4
append-only pull → full mirrors on both working machines (zbook LUKS
confirmed), plus a completeness gate surfaced at every session start
(`~/.cache/cc-archives-gate`). R2 clarified as disaster backup with a
break-glass pull, not the travel path (store-role table:
`data/global-claude-md/network-resources.md`, `c654ee1`). Third
failure mode found and repaired: three mid-session snapshot archives
(strict-prefix transcripts) re-archived complete → new plan item B8.
Two of my own claims corrected on the record: paper-b session count
(20, not ~100 — subhead-count error) and the `agent-*` cohort (never
lost; zbook held the transcripts). State-oriented system reference
written: **`wiki/docs/session-archiving-system.md`**.

- System page: `wiki/docs/session-archiving-system.md`
- Plan (B7/B8/E updated): `wiki/planning/session-archiving-upgrade-plan-2026-07-21.md`
- Sync: `scripts/daily-sync.sh` (pass 4 + gate), `scripts/daily-sync-trigger.sh` (per-session surfacing)
- Anchor commits: inscriptions `5dd52ad`, paper-b `ba50e16`+`a6e0537`, llm-repro `676d0e2`+`f2ce612`, PA `3507c0b`+`fc14a4e`
- **Open threads at session close (2026-07-23)** — all named in tray
  files; nothing lives only in this session: (1) **Brian's PRs #8–#10**
  → waiting-for row 2026-07-18 (follow-up PRs F4/F6/F7 contingent on
  his uptake — don't build unprompted). (2) **Write-like-me efficacy
  test** → addendum on the 2026-07-12 inbox row (build complete; test
  on next queued paper; 57 h baseline). (3) **SA plan open items**
  (A1–A6 research-tier pilot, B1–B6+B8 floor, C1–C7 extractor
  quality, D1–D2 governance, E3b(c)/(d)) → 2026-07-21 inbox row →
  plan doc. (4) Two recovered archives carry **placeholder metadata**
  pending ~$0.027/session Gemini approval (fold into the needs-review
  loop, plan B2). (5) **D2 teaching-archives retention** — Shawn's
  decision, ~1 h enumerate-and-decide.

### 2026-07-21 (Tue, latest SA) — session-archiving: tiered architecture DECIDED; 40-entry Three Ps audit (zero extractor confabulation); standalone upgrade plan

Multi-day session (started Fri 18, Brian-tooling review) resolved the
session-archiving question: **one conceptual system, two layers** —
cc-session-toolkit floor everywhere, Brian's `transcript-archive`
plugin as the per-repo research tier (~70% of repos), /reflect-vs-
/handoff as the ratified analogy. Five-agent Three Ps audit of 40
sampled `session.meta.json` entries: 125/126 hashes and ~530 paths
verified (the one failure inherited from a stale in-repo doc, not
invented); tags (1.50) and framing boilerplate the systemic
weaknesses; ~18% of floor entries sensitivity-bearing → never-promote-
without-screen rule ratified. Compliance finding reframed by Shawn as
procedural (no sensitive student data in personal account at all),
not technical routing. **All actionable items consolidated in
`planning/session-archiving-upgrade-plan-2026-07-21.md`** (18 items,
A research-tier adoption / B floor upgrades / C extractor quality /
D governance); inbox item created pointing at it.

- Plan: `wiki/planning/session-archiving-upgrade-plan-2026-07-21.md`
- Audit: `data/reports/threeps-audit-2026-07-21.md` (data `f99270b`,
  correction addendum same day)
- Inbox: 2026-07-21 capture "Session-transcript infra" → plan doc
- (Same session, earlier, style-guide workstream: academic-prose
  skill + output style shipped; denubis-plugins PRs #8–#10; Paper B
  register note + delta mining — logged in those repos' commits.)

### 2026-08-19/20 (Wed 19 Aug → Thu 20 Aug, latest PA) — SESSION CLOSE (/handoff): THE EFN ZERO BROKE AND THE DIAGNOSIS HELD; A "QUICK LOOK AT A DOWNLOADS FOLDER" BECAME THE BRANDING PACKAGE; THE HOUSE GREW A THIRD BRANCH

Long single-day session. **A structural claim was tested and passed, a routine consolidation
turned into a full brand audit, and the house decision acquired an option nobody had costed.**

**1. ⭐ EFN produced 3.75h after two consecutive zeros, and that is a confirmed prediction, not
a good day.** The 2026-08-19 handoff recorded the cause of the zeros as *structural rather than
avoidance* — **an open list of small externally-dated items acts as a concentration blocker, not
merely a competitor for hours** — and named Wed 19 as the direct test, since the list had been
cleared. **It produced.** ⇒ **Clearing dated small items is a PREREQUISITE for EFN blocks, not
housekeeping to fit around them.** Carry this into sequencing.

**2. The container question closed, and the answer came from measurement.** Shawn measured 22
large items into **`notes/move/volume-inventory.csv`**; known subtotal **9.79–10.36 m³ raw**
against a 25 m³ container, leaving **~80 large cartons** of headroom. **One container fits, with
real margin but not enough to stop culling.** PODS quoted **$349/mo + $1,956** to Melbourne;
**Portabox is $219/mo — $130/mo cheaper on rental alone**, so **Portabox Large is decided** and
the PODS quote became beat-guarantee leverage. ⏰ **That quote expires Wed 26 Aug.** ⚠ **The
Medium was declined on arithmetic:** it saves $60/mo and risks a second container at 5–7× that,
on a load whose largest unknown — the dismantled rack — cannot be measured until the final day.

**3. ⭐⭐ THE HOUSE DECISION HAS A THIRD BRANCH, and the file that concluded otherwise is now
banner-flagged.** The agent recommends **listing NOW, no repairs, shown with contents** — the
falling market outweighing both the repairs and the empty-house premium. **That deletes the $10k
works term and shortens the 10–12 week wait, which are the two inputs the *"0% of the agent's
range beats Brent"* finding rests on.** Shawn's works split: keep exterior clean + functional
plumbing, cancel re-grout + interior paint (~⅓ of cost). **⇒ Checkable consequence, taken from
the waiting-for rows rather than inferred: BOTH surviving items are already recorded as
date-independent, so the cosmetic chain WAS the entire reason the works needed an empty house
and a September window. Cancel it and the 28 Sept ready-date dissolves.** ⚠ **The deposits are
therefore not simply cancelled — the scope changed, so both quotes need re-quoting before any
non-refundable money moves.**

**4. ⚠ Brent's contract is six days late and the accountability is INVERTED.** It was ordered
*from our conveyancers*; Brent and his mother will not negotiate before seeing it. **So the
delay is ours, and the deposit-pressure play cannot be used honestly until it lands.** The
Sun Legal Norwest row also carried a *"call if nothing by ~Fri 15 Aug"* trigger that **fired and
went unactioned for four days**. Emailed 19 Aug; **call escalation set for the morning of 20 Aug,
before Shawn leaves at ~10:30**.

**5. ⭐ THE BRANDING PACKAGE — scoped as "check what's in ~/Downloads", delivered as a corrected,
documented, version-controlled brand system.** Eleven-plus commits in `fieldmark-docs-staging`
under `brand/`. **It expanded because every check found a real defect.** The findings, all
measured rather than asserted:

- **The green was wrong in every asset.** Specs say **`#669911`**; all artwork said `#559A00`
  (established from a flat fill of **421,665 fully-opaque pixels, no ICC profile**). **The
  layered `backgrounds.psd` holds `#669911` across 100.0% of 3.45M pixels and the live site's
  CSS uses `#691`** — so the designer worked to spec and only the *exports* drifted. Corrected
  throughout; **residual old-green after correction: zero pixels.**
- **The Fieldmark favicons were the mark stretched vertically ~1.38×** to force a square
  (content aspect 1.012 against a true 1.395). **Shipping distorted since 2023.** Now letterboxed.
- **⭐ EFN's canonical artwork is Steve's production site, adopted on Shawn's ruling that
  `www.fieldnote.au` breaks ties** (Steve maintains it; the original designer is his brother).
  **EFN's grey is `#444939`** — neither candidate — and it is **olive-toned, sitting with
  `#324C08`/`#141E03` rather than beside Fieldmark's neutral `#5C5A5A`. Deliberate, not drift.**
- **A horizontal EFN lock-up was reconstructed — and already existed in production.** Built
  independently by reusing the designer's own 29.11-unit gap, it came out at 4.05:1 against
  production's 4.67:1. **The method validated; the artefact was redundant.** ⚠ **Self-critique:
  the site's CSS was fetched for colour and font but its LOGO FILES were not — one obvious step
  further would have found it.**
- **Typography settled on production**: Playfair Display (SIL OFL) + Arial, **superseding the
  style guide's "Archive"**, whose licence is disputed across the aggregators that distribute it.
- **`#A4A4A4` resolved: it is the ™ glyph and nothing else** — 1,581 px in one 90×43 block.
- **The letterhead was rebuilt**: superseded Macquarie Park address → Surry Hills, stale
  *"© Penny Crook et al 2021"* → EFN, three Roboto variants → Arial/Playfair, `.dotm` → `.dotx`
  (**no VBA project at all**), and **the embedded signature removed entirely** at Shawn's
  instruction. A Google Docs master was added alongside; **the Doc is canonical, the `.dotx`
  mirrors it.**

**6. Google Drive reorganised** — 14 items suffixed **OLD**, a **`2026-branding-assets-CURRENT`**
folder created with a START-HERE README, and 32 asset files uploaded by Shawn. ⚠ **One upload
converted silently:** Drive's *convert-uploads* setting turned the `.dotx` into a Google Doc and
**flattened its date field to static text**; caught on verification and re-uploaded natively.
**FAIMS3 was deliberately left untouched** — separate project, not ours to supersede.

**7. RDA displaced to Fri 21 Aug, and the reasoning is consistent rather than convenient.**
Shawn: *"it's still August, and the people at RDA who would be reviewing it are almost certainly
on summer vacation"* — **the same population argument recorded on 2026-08-10** to justify
silence-is-consent. ⚠ **Logged as a SECOND slip against a stated one-day tolerance.** **Francis
P. Crawley left NINE suggestions at 05:16 on 19 Aug**; the relationship cost is covered by
Shawn's standing Thursday practice of thanking contributors, which is independent of submission.

**Held over / open:**

- **⏰ RESIDUE — Playfair Display is NOT installed system-wide, so OnlyOffice cannot see it.**
  Shawn uses OnlyOffice almost exclusively; **it is a snap, and its `$HOME` is redirected, so
  `~/.local/share/fonts` is invisible to it** (verified inside the sandbox — `fc-list` returns
  nothing). **12 static instances are staged at `~/Downloads/playfair-display-static/`** and need
  a `sudo cp` into `/usr/local/share/fonts/`, which the snap *can* see. **Needs Shawn's password
  — cannot be done for him.**
- **⚠ The Fieldmark `.ai` masters still carry `#559A00`** and need a designer to reissue. **SVG
  has no CMYK model, so print is the one place the downstream fix could not reach.**
- **The favicon distortion is fixed for Fieldmark but the square-variant question stands** —
  letterboxing is the honest interim; a purpose-drawn square mark is the real answer.
- **⚠ The Substack is on its THIRD date** (w/c 3 Aug → weekend 15–16 Aug → Fri 21 Aug with
  Brian). **Shawn's own diagnosis names a decaying asset, not a missed date: *"that keeps
  slipping and the preprint is cooling."*** Backlog row updated; **if it moves a fourth time it
  needs a different mechanism, not a fourth date.**
- **Working-notes candidates STILL HELD OVER from the 2026-08-19 handoff** (no verdict given
  across two sessions now): the **auto-gamma clamp**, and
  **comparables-checks-correct-in-both-directions**. Per no-silent-discard, re-surfaced again.
- **Deposits (~$5k) still unexecuted**, and now possibly unnecessary on *both* branches.
- **Garage census remains formally REOPENED.**

**Hours: 7.75h** — efn 3.75 · personal/move 2.00 · map-reader 1.75 · llm-repro 0.25. **Corrected
down from a 9.25h estimate on Shawn's own reckoning** (PA-system time folds into his standing
admin hour; the container discussion was already inside the move block).

**Artefacts touched:**

- Move: `notes/move/{volume-inventory.csv,container-call-plan.md,storage-container-options.md,off-market-vs-campaign.md,index.md}`
- Branding (in `fieldmark-docs-staging`): `brand/` — README, `colours.md`, `copy/`, `efn/`, `fieldmark/`, `efn/letterhead/`, `efn/logo/production-reference/`; `.gitattributes` LFS additions
- Tasks: `tasks/{inbox.md,backlog.md,FOCUS.md}`
- Reports: `reports/time-log.csv`; standup+recap `standups/2026-08-19.md`
- Google Drive: `Branding/` renames + `2026-branding-assets-CURRENT/`

### 2026-08-19 (Mon 17 Aug → Wed 19 Aug, latest PA) — SESSION CLOSE (/handoff): SLOT 2 BROKE ITS ZERO AND ACQUIRED A RATE; THE DENOMINATOR WAS WRONG; THE HOUSE DECISION HARDENED ON TIME

Three-day session, almost entirely move workstream. **Two listings posted, one reporting
error caught by Shawn, and a decision that had been open for two weeks closed on an argument
about time rather than price.**

**1. Slot 2 broke an eight-day zero and, on the second listing, produced a rate.** The
**Privia PX-850** went up 17 Aug at **$695** (comparables-checked; the check moved its floor
**up** $125 from a $400 guess). The **Carbatec DP4116F drill press** went up 18 Aug at
**$395 the pair** — the specs pass that produced the model number also turned up **a heavy
matched vice, oiled, in original packaging, never used**, and a comparables check moved the
ask **down** $100 from Claude's $495 suggestion. **0.75h end to end, the first item listed
*within* a batch, which is what makes it a measurement rather than a data point.** Extrapolated:
**~14–15h for the remainder, ~5.5 h/week against a 17.5 h/week floor.** **Slot 2 was never a
capacity problem — it was a start problem**, exactly as the first-unit-expensive pattern
predicted and as nine confrontational-band standups disguised.

**2. ⚠ The burn-down denominator was wrong, and Shawn caught it.** *"Are there really 50 things
that need posting, or are some of those for the moving sale?"* — the listing target is the
`sell-online` subset. **50 → 24** on correction, then **→ 21** as the instruments were
withdrawn, then **→ 23** as the keg fridge, fermenters and gym rows were added. The standing
rule now in `tasks/SYSTEM.md`: **recompute the denominator from the data at each report; never
carry it forward as a remembered number.** This is the third instance in two days of *a partial
count presented as a total* — the others being the unverified packing-week anchor and the
visual-sweep census.

**3. The house decision hardened, and time decided it.** Shawn got the agent's number
first-hand: **$1.05–1.09M if going to market today**, unchanged from the ≈3 Aug forecast, with
the caveat *"4–6 weeks might make a difference."* **But the campaign cannot transact for 10–12
weeks** — the separation went to family court late in the week of 11 Aug with a **~6-week
settlement estimate**, and no sale completes before it. Decayed to a realistic exchange,
**0% of the agent's range beats Brent at $1.03M** at any decay rate. **An agreed off-market
price is fixed today; a campaign price is set by a market twelve weeks away.** The off-market
route is a hedge; the campaign is an unhedged exposure.

**4. The move date moved and the spine was rebuilt.** **~15 Sept was over-optimistic — the slip
is external (court disclosure paperwork), not move work.** Now **25–30 Sept conservative,
20–21 Sept hoped**; packing stays anchored **14–20 Sept**; works run the week of the 21st with
nobody in the house (contractors have worked unattended before). **Kerbside 7 Sept does not
move**, so the moving sale can shift **one week at most** — two weeks would put kerbside after
departure, which is a hard stop.

**5. Two new batches, a keep/sell decision, and the storage question re-scoped.** **Batch G
(homebrew)** — a **10 L small-batch, all-ball-lock system** with a keg fridge as its anchor;
**Batch H (home gym)** — resolved by a rule that generalises: ***keep what you would rebuy
identically, sell what you would rebuy differently.*** ATX Power Rack 520 + Lat Option stay
($1,285 current replacement, matched pair, intermittent supply); bar, 120 kg plates, plate tree,
dumbbells, kettlebells and both benches go. Storage research (Sol) landed a shortlist —
**Portabox Large 25 m³ @ $219/mo provisional first, PODS Large as the competing quote** — plus
the **3,400 kg payload limits**. **Books turn out not to be the constraint** (20–25 banker's
boxes ≈ 300–500 kg), so **volume is the sole open constraint**, and **capacity is a step
function**: breaching volume *or* weight costs the same **~$5,256** second container.

**Held over / open:**

- **⏸ EFN (Slot 1) produced ZERO on both days**, and the cause is structural rather than
  avoidance: **sequencing it first was not enough.** Shawn's account — *"too stressed by the
  list of small but time-sensitive things, and then those took longer than expected and then
  the tax matter arose."* **An open list of small externally-dated items acts as a
  concentration blocker, not merely a competitor for hours.** That list is now largely cleared,
  so **Wed 19 tests the diagnosis directly** — if EFN produces nothing with a clear list, the
  diagnosis is wrong. ⚠ It gates the **Rainer follow-up, dated Wed 19**.
- **⏸ CLAUDE OWES A CONTAINER CALL PLAN at the Wed 19 standup** (inbox row). **Prerequisite
  not yet supplied: a rough inventory of the largest items** — Shawn offered it; volume is the
  only open constraint and without it the plan can only say *ask for 25 m³ and hope*.
  ⏰ Three-week notice line: **Mon 24 Aug**.
- **⚠ THE LISTING STEP-DOWN CALENDARS HAVE NO TRIGGER** — both live rows carry dated price
  reductions (Privia $695→$650 ~24 Aug; drill press $395→$360 after a quiet week) and nothing
  surfaces them. Inbox row created this handoff.
- **Deposits (~$5k) decided but unexecuted** — held to end of week pending Brent's draft
  contract, which was due Mon/Tue and has not arrived. **The two clocks are independent.**
- **Garage census formally REOPENED** — not done until every enclosed container is swept; the
  vice was found in an unchecked cabinet. Brewing gear (wardrobe + tubs) is the known gap.
- **Working-notes candidates HELD OVER** (no verdict given): the auto-gamma clamp, and
  comparables-checks-correct-in-both-directions. Re-surface at the next `/handoff` or `/recap`.

**Artefacts touched:**

- Move (new): `notes/move/{home-gym-decision,storage-container-options,listing-copy}.md`
- Move (updated): `notes/move/{index,selling-channels,photo-checklist,off-market-vs-campaign,fallback-bank}.md`, `selling-inventory.csv` (50 → 58 rows)
- Tasks: `tasks/{SYSTEM,inbox,waiting-for,backlog,FOCUS}.md`
- Reports: `reports/{time-log.csv,work-log.md}`; standups `2026-08-1{7,8}.md`
- Practices: `notes/working-practices.md` (lodgement entry)

### 2026-08-17 (Mon 10 Aug → Mon 17 Aug, latest PA) — SESSION CLOSE (/handoff): ARDC SUBMITTED; MOVE INSTRUMENT REPLACED; SELLING INVENTORY 1 → 50; HOUSE-SALE ARITHMETIC

Eight-day session spanning W33 and the start of W34. **Three things closed, one
instrument was replaced, and one decision was analysed to a conclusion.**

**1. ARDC application SUBMITTED (Thu 13 Aug, Day 11)** — a day ahead of the internal
target, four days before the hard close, email confirmation filed as the external witness.
**25.25h of tracked `career` time across eleven days.** The 2026-08-09 prediction — *"one
strong response plus two adaptations"* — was recorded as a hope and delivered almost
exactly: **3.75h for the Program Manager statement, then 1h, 1h, 1h.** Register §9, itself
a by-product of that overrun, is why. **The tail is open**: interview prep if he advances,
on his own 70–80% estimate, landing early–mid September inside the move window.

**2. The move-tracking instrument was replaced (ratified Tue 11 Aug).** The 3-day rolling
average is **retired**; a **task burn-down** is primary; the 17.5h weekly floor is demoted
to a reported-not-graded diagnostic. The argument came from the parameter's own stated
purpose — load-shifting, i.e. volume out of September — for which hours were a proxy
chosen when no inventory existed. **W33 move hours: 13.50h against W32's 1.50h.** Causation
not claimed (the CleanOut deadline and better weather pushed the same way), but the
instrument stopped producing a false negative every day and the work went up.

**3. The census ran and the selling inventory went 1 → 50 rows.** Two zones (garden shed,
garage). **One zone flipped the moving-sale decision**: the sub-$50 count went from three
items to ~26 after the shed alone, and that count *is* the go/no-go. Chemical CleanOut
**delivered Sun 16 Aug** — the single-occurrence event the whole week's sequencing was
built around.

**4. The house-sale decision was analysed to a conclusion** (`notes/move/off-market-vs-campaign.md`).
Brent (gardener, mother financing) offered $1.00M against a $1.03M floor. **The analysis
was wrong twice before it was right and both corrections are kept in the file** — the
avoided works are not pure saving, and "walking away loses money" reversed once a real
comparable existed. **Deposit decision: PAY** ($5k deposits, ~$10k works, break-even 68–81%
against Shawn's own 50-50 read).

**Held over / open:**

- **⏳ IN FLIGHT AT HANDOFF:** the **ALA application** (2h box, closes today, Shawn
  reporting time all at once — **not yet in the log**); **llm-repro's large automated run**
  and **map-reader's automated work**, both launched today and running unattended.
- **Slot 2 has produced 0 listings in 8 days** — the census is done, the listing step has
  not started. Three planned for this afternoon (drill press, Privia PX-850, mitre saw),
  **to be individually timed** so "all listings posted" acquires a rate.
- **Wiki curation deferred a fifth time**; `notes/_inbox.md` holds 186+ rows.
- **Anchor drift trend has no fresh point since 2026-06-06** (18.4%); active memory
  retrieval is 36 against 858 digest exposures.

**Artefacts touched:**

- Task system: `tasks/SYSTEM.md` (instrument change), `tasks/FOCUS.md` (Slot 1 closed and
  twice rotated), `tasks/{inbox,waiting-for,backlog}.md`
- Move: `notes/move/{selling-inventory.csv,box-inventory.csv,selling-channels.md,photo-checklist.md,fallback-bank.md,off-market-vs-campaign.md,index.md}`
- Reports: `reports/weekly/2026-W33.md`, `reports/work-log.md`, `reports/time-log.csv`
- Standups: `standups/2026-08-1{0,1,2,3,4,7}.md`
- Memories: personal-calendar architecture entry; RSpace partnership + Rob Day contacts

### 2026-08-10 (Mon, latest PA) — SESSION CLOSE (/handoff): SYNCTHING MESH REPAIRED + HEALTH GATE; W32 REVIEW; MOVE WORKSTREAM SCAFFOLDED

Long multi-strand session on amd-tower spanning infrastructure, the weekly
ritual, and the opening of a new move workstream. Three substantive threads.

**1. Syncthing — a three-month silent outage found and fixed.** The four-device
mesh had been dead since early May and nothing reported it. Two independent
failures: rpi-server's container exited cleanly 2026-05-06 with `restart: 'no'`
and never came back; amd-tower's came up 2026-07-14 on a **detached bind mount**,
booting a stale 2025 config and advertising the wrong device ID (`7OXIKQ7…`
instead of `TNOT4GW…`) while `docker ps` reported it healthy. Root cause of the
May outage later confirmed from container timestamps: a `docker.service` restart
killed all three containers; the two with restart policies came back, Syncthing
did not. Both repaired; rpi-server drained a 298-file backlog. **LAN addresses
then pinned** (`PATCH /rest/config/devices/<id>`) — the mesh had been relaying
through a public server even between machines on the same switch, because both
daemons run in Docker bridge networks and announce their container IP. All links
now `tcp-*` on `192.168.1.x`.

**2. `scripts/syncthing-health.sh` — the gate that would have caught it.** Checks
container state, bind liveness (host vs container `/config` inode), device
identity against `data/config/syncthing-expected.json`, folder errors, always-on
peer reachability, stalled transfers, **discovery/announce failures**, and
**peers absent beyond threshold**. Surfaced at every session start via
`daily-sync-trigger.sh`, mirroring the cc-archives gate. **Every check was
fault-injected and observed to fire** — the folder-health check was vacuous on
first write (it called a `syncthing cli` subcommand that does not exist in v1.29)
and was rebuilt on the REST endpoint. The last two checks were added *after* the
gate missed a live failure: zbook's container held a stale DNS server from
another network, so it could not announce and no peer could find it.

**3. W32 weekly review + the move workstream.** Review found the "16h deficit"
was `move_contents_daily_target`, not the work target — 1.5h against 17.5h,
exactly 16.0, while work hours were *exceeded* at 45.00h. Deficit written off,
parameter re-expressed as a weekly floor, promoted to a named deliverable.
`working-with-claude.md` carried from stub to seed (17 rows, seven themes) —
first wiki curation in four weeks. New `data/notes/move/` workstream scaffolded:
nine-bucket destination taxonomy, selling-channel framework, box inventory.

**Held over / open:**

- **Books climate decision UNRESOLVED** — three boxes packed, destination
  deliberately open. Three options live: container with mitigations, small
  climate-controlled unit for a valuable subset, or a colleague's office
  (waiting-for row, Shawn following up).
- **Today has no recap** — Shawn deferred it; time tracking also pending.
- `notes/_inbox.md` carries one row from a concurrent llm-reproducibility
  session, committed here rather than left stranded.

**Artefacts touched:**

- Scripts: `scripts/syncthing-health.sh` (new), `scripts/daily-sync-trigger.sh`
- Data config: `data/config/syncthing-expected.json` (new)
- Docs: `data/global-claude-md/network-resources.md` (Syncthing section, failure
  modes, compose-v2 provenance), `notes/working-with-claude.md` (stub → seed),
  `notes/working-practices.md` (two estimation entries), `data/scratchpad.md`
  (three self-corrections)
- Move: `data/notes/move/{index,selling-channels}.md`,
  `{selling,box}-inventory.csv` (all new)
- Reports: `reports/weekly/2026-W32.md`, three W32 collaborator reports,
  `standups/2026-08-10.md`
- Tasks: FOCUS Slots 1–3, `waiting-for.md` (3 new rows), `inbox.md`,
  `SYSTEM.md` (move parameter tuned, standing report added)
- Infra changed outside git: compose v2 installed on rpi-server (apt),
  Syncthing configs on all three nodes (`config.xml.bak-2026-08-08` for rollback)

### 2026-08-09 (Fri 7 Aug → Sun 9 Aug, latest PA-hub) — SESSION CLOSE: ARDC PACK BUILT — CV, COMBINED LETTER, SEEK PROFILE; THREE CRITERIA STATEMENTS DRAFTED

Three-day session on zbook (the CV work had been amd-tower-only; `moderncv`
and nine other TeX packages had to be installed here before anything would
build). **The application is assembled but not submitted.**

**The deliverable changed twice, both times discovered rather than planned.**
Seek's upload stage turned out to be a single *National Recruitment Campaign*,
so three differentiated cover letters became **one combined letter** — evidence
file §8's three-letter allocation is superseded as an architecture. Then a
re-read of the applicant instructions found a **third requirement**: a response
to the Key Selection Criteria as a separate document, max 2pp, per position.
The employer questions, which drove the whole week's sequencing, turned out to
be pro forma.

**My worst error was measuring the wrong thing.** I repeatedly told Shawn the
letter was "30% over" and needed ~250–300 words cut, from a word ceiling in the
file's own frontmatter — when that same frontmatter says the ceiling is
*rendered page count*. He asked to stop guessing; I built `render-letter.py`,
and it fitted 2 pages with ~152 words to spare. Two cutting passes were spent
on a constraint that was never binding. **Anything gated on a rendered artefact
must be measured by rendering it.**

**Verification that paid.** A fresh-context proofreader caught *San Diego
Supercomputing Center* (it is **Supercomputer**) — the second misspelt
institution after *Research Space* → *ResearchSpace*. A bounded criteria-coverage
audit against all three PDs found 28 criteria, nothing absent, and one thin:
people leadership on the **preferred** role, because the letter's
"influence rather than authority" framing had crowded out the fact that he had
line-managed. Under-claiming again. And compressing three named skill areas to
"data management" had re-attached the **70%** to the construct that carries
~50% in the ARDC's own published case study — §13's exact warning.

- **`saross/cv-and-applications`** — `src/CV-ARDC-main.{tex,pdf}` (19pp, 41
  publications verified printing, month+year dates, director roles split);
  `src/letters/ardc-national-campaign.{md,pdf}` (2pp, signed);
  `src/criteria/` (three 2pp KSC statements, DRAFT); `scripts/register-gate.py`,
  `render-letter.py`, `render-criteria.py`, `extract-for-seek.py`; repo
  `CLAUDE.md`. Head `8a54b80`.
- **Seek profile** complete: 15 roles, 3 qualifications. Job title caps at 100
  characters; the Company/Job-title autocompletes swallow the next click, so
  descriptions silently save empty unless verified visually.
- **Open:** revise the three statements (PM → ProjM → BA) in a Fable session —
  prompt at session scratchpad `fable-criteria-session-prompt.md`. Treat them as
  **three variations on one letter**; shared paragraphs verbatim are fine.
  Re-upload the CV (the copy on Seek predates the date fixes). Still waiting on
  the ARDC GenAI one-document-or-two question. `seek-month-overrides.txt` is
  superseded by the 2026-08-09 dates.

### 2026-08-06 (Wed 5 Aug → Thu 6 Aug, latest PA-hub) — SESSION CLOSE (/handoff): CV REBUILT AND VERIFIED END TO END; Seek format resolved; letters still unwritten

Two-day PA-hub session (amd-tower) that began as a standup and became a full
verification and reconstruction of the CV, plus the infrastructure to keep it
honest. **The CV is submission-ready; no cover letter is written.**

**What the verification found.** Nothing was fabricated — but the CV was wrong in
both directions, and the errors that mattered were *understatements*. Four places
undersold Shawn: the funding total (the summary printed the Lead-CI subtotal as
if it were the total, a **\$1.8M** understatement), the deployment and workflow
counts, and the generative-AI contribution. Against that, two real
overstatements: the ALTC "After Standards" grant at **A\$294,000 against a
funder-recorded A\$172,000 ex GST**, and the America for Bulgaria award, whose
**administering body names three investigators and Shawn is not among them** —
removed on his ruling (*"if the public record diverges, then it's safest to
remove it"*). **Total moved A\$4,399,690 → A\$4,208,062**; twenty-one grants
attested at funder level.

**The worst defect was invisible.** `biblatex-apa` source-maps both
`@incollection` and `@inproceedings` to `inbook`, so two `\printbibliography`
filters matched nothing. **The CV claimed 41 publications and printed 27** —
eleven chapters and three proceedings papers absent, under a heading reading
*Publications*, not *Selected*. A filter matching nothing leaves no gap, so
neither of us would have caught it by reading. Found by an agent instructed to
*count what appears against what the source asks for*; verified in the `.bbl`
before fixing. All 41 now print.

**Apparatus built — the durable output.** A private repo,
**`saross/cv-and-applications`** (`~/Code/cv-and-applications`), holding the
source, an empirically-derived **register note** for CV and application prose
(measured from 3,666 words of Shawn's own letters — he uses **zero em-dashes**
in letters against 2–3/1k in policy documents), a **claim audit** giving every
assertion a source and a status (VERIFIED / ATTESTED / PRIOR-DOC /
NEEDS-VERIFY), and an **interview capability inventory** from two agent audits of
his repositories. Evidence and provenance live in `data/notes/career/`.

**Zotero corrected as source of truth** — 72 field corrections across 25 items
plus name normalisation on 14 creator entries, over two agent passes, **180
independent assertions, zero failures**. Every write asserted its expected
current value first and carried a version number.

**Seek's format resolved at the end:** a **prose cover letter** (the cheaper
shape — the DCCEEW register applies), then **employer questions not visible until
the letter is uploaded**. Brian pre-cleared moving Friday to beer/dinner only,
taking Friday from ~4h to ~7h.

- Public repo: `wiki/` (continuity, working-notes, both observation registers),
  `notes/_inbox.md`.
- New repo: `saross/cv-and-applications` — `src/`,
  `docs/register-cv-and-applications.md`, `docs/interview-capability-inventory.md`.
- Data: `notes/career/` — `ardc-application-evidence-2026-08-05.md`,
  `cv-blocks-claim-audit-2026-08-05.md` (now §§1–20),
  `ai-upskilling-plan-2026-08-06.md`, `external-funding-2026-08-06.xlsx`;
  `tasks/backlog.md` (Zotero dedup; AI upskilling weekend); FOCUS Slot 1.
- **Open / carry-forward:** ⚠ **the Overleaf master is now badly stale** — every
  change of the last two days is local and in the new repo, and editing Overleaf
  next would silently discard a day's work. **Waiting on people:** Bree Kelly's
  conferral date (colleague asked); whether the ARDC's GenAI policy and staff
  guidelines were one document or two (can only let Shawn claim *more*).
  **Deferred by ruling:** do not regenerate the `.bib` from Zotero before the
  applications go in — a fresh export adds three items and changes name
  rendering; dedup first (backlog row). **Next:** three brief cover letters,
  Program Manager first so its employer questions reveal the scope early.

### 2026-08-05 (Tue 4 Aug → Wed 5 Aug, latest PA-hub) — SESSION CLOSE (/handoff): RDA IG PROPOSAL REMEDIATED AND CIRCULATED; ARDC still at zero

Two-day PA-hub session (amd-tower) that began as a one-hour RDA salience pass and
became a full verification and remediation cycle on both proposal documents.
**The proposal is now submission-ready and the comment window is live: comments
close Fri 14 Aug, submission Mon 17 Aug.**

**What the pass actually found.** The salience diagnosis held (purpose and
activities were buried in template detail), but almost everything else came from
checking. A pre-flight found the live Google Docs had drifted from the archive
copies in three substantive ways (Kiera named in the STM clause, an editorial
note removed, Christina Drummond's email changed). A consistency check found
eight issues; a **critical-friend review** (one Opus agent, fresh context, a
settled-rulings list so it would not re-argue the day's decisions) found five
high-severity findings on top. The largest: **the 12-month timeline was anchored
to a start date the document's own approval arithmetic excluded.** Working
forward from a mid-August submission and the stated 10–12 week cycle, endorsement
lands ~November 2026, so month 1 is November, P27 carries no formal session,
VP28 is month 5, P29 (month 11) is where the WG proposal is presented, and the WG
launches at **P30 (2028)**. The success criterion changed from *launching* a
Working Group within twelve months to *submitting an application*.

**Corrections of substance.** The proposal had read in places as though the
Interest Group would produce standards itself, contradicting its own Primary
Objective and its twice-stated anti-proliferation position; all three framing
statements now describe take-stock → identify-gap → extend the Three Ps →
hand to Working Groups. Two questions a TAB reviewer asks first are now answered
in new subsections (*Why an Interest Group rather than a Working Group*; *Beyond
the first twelve months*). **Exemplar tooling** became a real IG deliverable with
an owner, a supporting objective, and a stated reason for staying unfinished
(harnesses are still evolving). **All six July verification flags are discharged,
three of which held real errors**: the CHART statistics were misstated in three
ways and are now cited to Huo et al. (JAMA Netw Open 2025,
doi:10.1001/jamanetworkopen.2024.57879); "Huvila et al." was wrong on two counts
(edited collection, three editors); AID and GAIDeT were asserted but uncited.
Also corrected: CSC removed (no such member), the GRS consortium is four partners
convened with WCRIF (singular Conference), and "STM Association" is the correct
name.

**Other arcs.** BolgiaTen contract **signed and executed** — the one-week poke
trigger discharged without firing, ending the arc that ran from the 2026-06-02
ETL sign-off. **Odette fully unblocked** (script delivered, test server fixed
after Steve's upgrade, invites passed on); ball with her, monitored on Slack.
Kiera confirmed the STM attribution, and it turned out to be public anyway. Move
works captured with their dependency chain (move out → re-grout → clean → paint)
and a gated backlog row for the works schedule. **9.5h logged Tue** (rda 4.5,
personal 3.5, map-reader 1.25, efn 0.25); 22:00 stop breached with cause (22:45
station pickup, one-off).

- Public repo: `wiki/claude-observations.md` (obs 27–30), `wiki/user-observations.md`
  (2026-08-05 candidates, pending), `notes/_inbox.md` (2 wiki candidates).
- Data: `archive/rda-ig-application-2026-07/` — both documents remediated end to
  end, plus `critical-friend-review-2026-08-04.md`, `salience-pass-drafts-2026-08-04.md`,
  and `change-log-addition-2026-08-04.md`; recap + work-log + scratchpad
  (verification-cost pattern); tasks (BolgiaTen closed, Odette waiting-for, move
  trades, Kari ask).
- **Open / carry-forward (updated 2026-08-05 midday — the RDA document work is
  DONE):** all three documents are synced and archived
  (`RDA_IG_change-log_2026-08-05.md`, renamed from the July date). The AID
  expansion, the co-chair resolution, and the July strike-throughs are all
  applied; the comment cycle is running. **Closed since the handoff:** co-chair
  count (seven is fine — two IGs on the first page of listings have seven, so
  the template's 2–4 is guidance); the Kari Weaver permission ask (she is on
  vacation through 24 Aug, past both the comment close and submission, so the
  membership-connection sentence is dropped, and the AID citation stays).
  **Still open before submission:** member-table Title column, GRS Round 2
  decision, Commitment column from replies. **First substantive member comment
  in** (Gnana Bharathy): are the existing proof-of-concept tools going to seed
  the Working Group? The Exemplar Tooling deliverable already answers yes, but
  the question is itself evidence that the tooling reads as less mature than it
  is. Tooling links now in a `reference` memory; new inbox row to get them
  publishable. **Unresolved:** what Gnana means by "queries" — possibly a third
  artefact neither repo covers; **change-log addition not yet pasted** into
  `RDA_IG_change-log_2026-07-23`, and the July section's strike-throughs are
  specified only in this session's chat (reproduced in the resume prompt);
  **Kari Weaver permission ask** (inbox row carries sentence + wording);
  **ARDC had two consecutive days at zero** against ads closing ~17 Aug;
  map-reader **timeline step-back still unscheduled** (twice deferred);
  conveyancer email forgotten twice; co-chair count and member-table Title
  column still open before submission.

### 2026-08-03 (Thu 30 Jul → Mon 3 Aug, latest PA-hub) — SESSION CLOSE (/handoff): DRAIN COMPLETED in full; W31 review + Jun–Jul retro run; division proposal presented; ARDC ads live → Slot 1

Five-day PA-hub session (amd-tower) spanning the named drain day through Monday's
carried block. **The clear-all-reviews drain (Slot 1, promoted 27 Jul) finished on
every term of its original Done criterion**: tasks-inbox 24→7 (all survivors
deliberate), notes-inbox cluster-and-carried (verification-apparatus.md NEW from 6
rows; remaining 8 ripe clusters in a dated rotation queue, one per weekly pass),
user-obs verdicts ZERO across all repos (8 accepted / 3 dropped Mon; paper-b's
U21–27 + llm-repro + fieldmark were cleared Fri–Sun), the 2026-05-29 vocab report
resolved as a **phantom** (ratified+applied 1 Jun; only its `status: active` flag
was stale — fourth stale-row instance of the fortnight), memory-integrity triaged
into the class-fix row. Scratchpads distilled (global 96→47, map-reader 61→40; 11
promotions to permanent memories; PR-workflow prune caught a REAL gap → collaborator-
presence clause added to global CLAUDE.md `de22fd1` — paper-b + LLM-History-Paper
have no project CLAUDE.md). **Jun–Jul retro** (`reports/retros/2026-07.md`): July =
~39 closures incl. 3 external submissions in one week, 168h on target, 96% standup
consistency; one degrading trend (inbox 13→19→25) → **disposition-cadence
convention ratified** (weekly ~45-min pass bound into /weekly-review + recap
micro-triage ≤10 min; four-week trial). **Memory archive swept** (4,684 records →
2026-08 cold partition, invariance held, integrity PASS). **Published-artefacts
review executed same day** (retro 5c): 2 refreshes + 6 NEW publications (audit,
improve-prompt, both scout pairs; Pattern-B redactions; re-scan caught 4 residuals
the mapping missed; sub-READMEs corrected off the retired symlink policy)
`8915b8c`. Worktrees/branches: all three relics fully merged → removed (repo back
to single-checkout).

**The week's other arcs, all landed:** division proposal BUILT + PRESENTED Day 1
(Fri, 7h vs 1h estimate — reconstruction work concealed in "loose ends"; ball with
Adela; Mon nudge sent, ~$16k gap on ~$360k, one contention point, lawyers hold the
spreadsheet). Paper B FULLY DISCHARGED (wikis live, FAIR apparatus, continuity
staged for RSOS cold restart). Penny repaired (sent Sat, reciprocated Sun; ops
meeting H2 Aug captured). Codex-transcript integration designed + approved
(`data/notes/codex-transcript-integration-plan-2026-08-01.md`; ~/.codex chmod 700
— was world-readable holding the most sensitive transcript on the box). Subagent
model policy shipped both machines (opus default for agents; composed-CLAUDE.md
arrangement learned + memory-anchored). Cosmos write-like-me pilot measured from
git: 74% final-side light-edit-or-better (48% verbatim) vs Paper B's 4–12% —
suggestive, not the efficacy test. W31 review (`reports/weekly/2026-W31.md`):
16 closures; Next Week = map-reader outline + dated path, llm-repro preliminaries
→ LAUNCH, drain-to-zero + ARDC readiness; move-window regime restated (3–4h/day;
EFN web refresh mid-Sept; research side-by-side; Substack = career-stakes
workstream).

**Monday's rotations:** division-wait vacated Slot 1 (Paper B precedent) →
**ARDC application in (Day 1): ads LIVE, close ~17 Aug, submit THIS WEEK**; PD at
`data/notes/career/ardc-pd-program-manager.pdf`. Slot 2 map-reader Day 8: five
agents in flight, MCC performance finding likely paper-bound; **timeline
step-back with Shawn pending (reminder delegated: recap or next /track)**. Slot 3
llm-repro Day 8: **OSF amendment PUBLISHED + prereg amendment ACCEPTED via the
API workflow** (proven "much easier and more reliable"). Mon 4.75h.

- Public repo: published/ (6 new + 2 refreshed + READMEs), global-claude-md
  (subagent model policy Thu `00daa82`; collaborator clause `de22fd1`),
  wiki/user-observations.md verdicts `03571ec`, vocab-report status `7ebd0f5`,
  RDA .docx → private archive (pointer note), worktree/branch cleanup.
- Data: W31 `fb4b0a9` + retro `a240629` + drain sweep `c0323ec` + ARDC rotation
  `34304c7` + verification-apparatus carry `63e5e89` + SYSTEM.md conventions
  (disposition cadence; PA tracking boundary; excess-pa-admin label) + Codex plan
  + collaborator reports (Brian/Steve/Penny 2026-W31) + time/work logs.
- **Open / carry-forward:** map-reader **timeline step-back** (Claude reminds at
  recap/next-track); **two Gmail drafts residual** — eRA planning-meeting ask to
  Penny (SEND this week) + Odette-designation draft (DISCARD, superseded); **RDA
  salience pass TOMORROW first block** (before Wed 6 Aug reminder); tutorial
  regeneration + Odette script in flight (fieldmark session); disposition-pass
  FIRST RUN next Monday's weekly review; zbook `~/.codex` check at next sync;
  Adela mid-week judgement if silent; working-notes candidates from this handoff
  held over pending verdicts (Cosmos-survival measurement; archive-sweep record;
  Codex-store findings).

### 2026-07-30 (Wed→Thu 00:xx, prior PA-hub) — SESSION CLOSE (/handoff): 224-session backfill EXECUTED (real number 77), subagent gap found + closed, theseus-ship resolved; Wed rituals run

Long PA-hub session (amd-tower) spanning Tue evening → Thu small hours, resumed from the
2026-07-28 beacon below. Job was to run the metadata backfill on Terra. **It ran, but the
brief's central number was wrong and finding that out was most of the value.**

**Scope corrected before spending — 224 → 77.** Re-derived the gap set from the raw
snapshot rather than trusting the diagnosis table. Three subtractions, all reproducible:
223 gap entries today (224 at diagnosis; the delta is that session archiving *itself* at
its own handoff, `archived_at 2026-07-28T17:22:34`) − **75 top-level `agent-*.jsonl`
subagent transcripts** miscounted as sessions (`agentId` + `isSidechain: true` + a *parent*
`sessionId`) − **71 below a 1,000-token substance floor** (`/clear`, `/exit`, aborted
starts; verified by inspection after a suspicious *exact* 64-token extract recurred across
projects — it is the local-command caveat boilerplate). The 75 wholly account for two rows
of §7's table: the external drive (**55**, i.e. all of them) and `trap-extraction` (**14**,
likewise) — so **the external-drive layout question never existed**.

**Four archiver defects, each of which would have corrupted the run** (all fixed,
`scripts/bulk-archive.py`): discovery read a hardcoded `~/.claude/projects` while **55 of
the 77 exist only on zbook** — it would have archived 22 and reported success; dedup used
`CATALOG.json` (539 entries against 728 ids on disk) and would have **re-archived 189**
sessions, manufacturing the very double-archiving defect just repaired; `--min-turns 5`
discarded **56 of 77** substantive sessions including a **205,848-token session with two
turns**; and `shawn`/`Code`/`gemma-project` would have opened new top-level directories
beside their existing `_legacy/` homes.

**Executed:** 77 archived (0 failures, 146 subagents), **84 enriched with Terra**,
validator-gated, catalogue rebuilt **539 → 799**. **Actual cost US$8.49** against an $8.58
estimate — the chars/4 × 1.11 calibration held to 1.5%.

**Shawn's challenge changed the outcome twice.** (1) *"Don't we need to archive the
subagent transcripts?"* — he was right and I was wrong: **247 were genuinely unarchived**
(63 flat `agent-*.jsonl`, 184 nested), recoverable because every subagent record carries
its parent `sessionId`. Subagent coverage now **3,175 / 3,175**; 13 orphans whose parent
transcript does not exist anywhere are held at `_legacy/_orphan-subagents/<parent-id>/`
rather than dropped. (2) *"Shall we fall back to Gemini?"* — **OpenAI's content filter
refused 3 entirely benign transcripts** (`invalid_prompt`; Ollama Modelfiles for
`gpt-oss:20b`, a local-model inventory). Deterministic, so retrying is pointless.
`enrich --fallback-gemini` added; all three enriched for $0.04. **Zero archived sessions
now lack metadata.**

**theseus-ship resolved from evidence, not guesswork.** Not a rename and not user error: a
**succession of three separate repositories** — `saross/theseus-ship` (60 sessions,
2025-12-05→2026-02-03), **`Denubis/`**`LLM-History-Paper` (14, 2026-03-06→04-23), paper-b
(30, 2026-04-25→07-27). Different GitHub owners, both live, neither nested in the other,
**contiguous non-overlapping date ranges**. Promoted to top-level `theseus-ship/` with
**zero metadata edits** (all 60 already carried the right `project.name`); collapsing would
have erased which collaborator's repo the work happened in.

**Validator over-strictness fixed rather than metadata regenerated.** The gate returned 6
`tag-project` errors; all six checked against transcripts, **none was a metadata defect**.
Four were cross-references on sessions that also carried their own project tag; one was the
Fieldmark≡FAIMS3 synonym. Severity now turns on whether the session's own tag is present —
tied to the check's own stated harm. The survivor (`922bf6ff`) is a true positive whose
*metadata is correct*: a PA standup archived under `ANU-HUMN8031-2026` because it was
launched there. Placement, not content. **Deliberate deviation from the brief's "regenerate
any flagged records" instruction, stated as such.**

**B6 measured exactly:** `rebuild_catalogue` is **depth-2 only** — 799 catalogued equals
precisely the depth-2 meta count; 47 sessions remain invisible, all under deliberate
`_legacy/` nesting. **Postgres re-index deliberately NOT run**: B7
(`scripts/index-session-content.py:105`) plus a depth-2 + `_`-prefix exclusion at :132/:137
means re-indexing now would re-bake the role mislabelling and skip `_legacy/` entirely.

**Wednesday rituals** (data submodule): standup, recap, seven time entries (5.5h Wed;
one 0.25h meta-tracking entry logged then reversed on the 2026-07-06 convention), inbox
**29 → 24 → 25**, weekend infra session bundled to backlog, RDA captures + the Kiera-nudge
sequencing decision (first touch → 6 Aug send; 12 Aug demoted to backstop), Adela
disclosure **RESOLVED both sides**, and **Slot 2's target restated** as a staged charter
programme after a wall-clock rescope Shawn asked for.

- Public repo: `scripts/bulk-archive.py` (`--source-root` + merged-snapshot detection,
  disk-based dedup, `--min-content-tokens`, `_legacy` relocation, `subagents` mode,
  `enrich --provider terra` with `--fallback-gemini`, per-provider cost accounting);
  `scripts/validate-session-metadata.py` (severity by own-tag presence; Fieldmark/FAIMS3
  alias); `wiki/planning/transcript-archive-diagnosis-2026-07-28.md` (§7b corrected gap,
  §7c outcome, §7d theseus-ship). Commits `9012e7d`, `a843b3d`, `38af0ac`, `87a6d3e`.
- Data: standup/recap for 2026-07-29, time log, inbox/backlog/waiting-for, FOCUS Slot 2.
- **Open / carry-forward:** **47 uncatalogued under `_legacy/` — review together
  (Shawn's ask) before assuming B6 recursion is the whole fix**; **~201 double-archived
  entries** (1,006 metas vs 805 distinct ids, error shape 3, untouched); `922bf6ff`
  placement decision; the two `index-session-content.py` fixes gating re-index; Sonnet 5
  price constants stale **2026-08-31**; Zotero write-key test still untried; user-obs
  batches **2026-07-24 + 2026-07-27 still pending** (2026-07-28 accepted).

### 2026-07-28 (Tue, latest PA-hub) — SESSION CLOSE (/handoff): transcript archive diagnosed + consolidated; deterministic validator shipped; 5-arm metadata bake-off → TERRA CHOSEN, LLM verifier deferred

Full-day PA-hub session (amd-tower), resumed from the 2026-07-27 beacon. **The
transcript archive turned out to be the map-reader audit's evidence base, not
infrastructure** — the audit is finding confabulations in intermediate documentation,
and per Paper B the external grounding exists only in transcripts (Shawn's
reclassification; I had filed it as Thursday drain work).

**Forensics — three prior beliefs overturned, all re-runnable
(`wiki/planning/transcript-archive-diagnosis-2026-07-28.md`):** (1) **archive ⊆ raw
always** — 0 of 727 archived session IDs lack a raw counterpart, so nothing was ever
lost to rotation and retrieval should go **raw-first**; 224 raw sessions have no
archive entry anywhere (map-reader: 19, twelve a contiguous 4–15 Feb cluster, 16 of 19
zbook-only). (2) **No cwd-forking and no repo rename** — 139 of the 149 nested-location
sessions record `cwd = ~/Code/map-reader-llm` back to 2025-12-22; the fork came from the
archiver's `project.name` changing. Corpus-wide 781/923 sessions launched from a clean
repo root, exactly 1 genuine nested launch — **Shawn's "I always start at the root"
belief was correct and my first diagnosis was wrong**. (3) **CATALOG.json under-reports
by a third** (538 vs 804 entries on disk); the earlier "April = 0 archived" was a
complete count of an incomplete search. **B7 relocated**: role mislabelling is an
*indexer* defect (`scripts/index-session-content.py:105`, the `or record.get("type")`
fallback), not an archive one — archives and raw are sound; 40% of indexed `user` chunks
are not Shawn's words, 87.5% for chunks >2,000 chars. Memory extraction is the
highest-risk consumer.

**Containment + consolidation (reversible, verified):** both machines' raw stores
snapshotted (`~/backups/claude-raw-transcripts-2026-07-28/`, amd 2,005 + zbook 2,267
files, merged 951 distinct sessions); `~/cc-archives` snapshotted pre-change. map-reader
consolidated A+B+C → one `map-reader-llm/` location: 123 moved, 51 quarantined
(manifest at `~/backups/cc-archives-consolidation-quarantine-2026-07-28/`), **196 entries
= 196 distinct sessions, 0 lost**; DB `sessions.project` updated 151 rows → 196/0.
Dedupe rule was evidence-based (A won all 28 overlaps; 14 of C's copies had 0-byte
transcripts). **LLM-History-Paper / theseus-ship / paper-b left untouched** per Shawn —
that fragmentation is user confusion over repo boundaries, not a rename.

**Metadata bake-off, 5 arms × 10 sessions, blinded (labels flipped per session):**
Terra 38/60, Haiku 15, Luna 4, Gemini 3 — **Terra 27 of 30 on long sessions**, which is
where the corpus lives. Two silent failures found only by running: Gemini 3.6 rejects
`thinking_budget: 0` (use `thinking_level: "minimal"`), Sonnet 5 returns **empty output**
on long inputs because adaptive thinking now defaults on and `max_tokens` caps thinking
+ output together. Haiku 4.5 **rejected 5 of 10 sessions on its 200K window** —
disqualifying regardless of quality. Sonnet 5's tokenizer billed 2.71M tokens where
OpenAI billed 1.81M on identical text (+50%), making it 6× Luna's cost. Costs this run:
Haiku $0.91 · Luna $0.91 · Gemini $1.37 · Terra $2.28 · Sonnet 5 $5.48.

**DECISIONS: (1) TERRA for the backfill and production** (~$12 for 224 sessions);
Luna is mechanically clean but substantively thin (4/60) and **not worth migrating to
from Gemini**. (2) **LLM verifier DEFERRED** — the deterministic validator caught 3 of 3
code-checkable defect classes and Terra returned zero findings; revisit if retrieval
actually fails. (3) The archive project name is an identity — renaming it forks the
archive silently; renames need an explicit migration step.

- Public repo: `scripts/validate-session-metadata.py` (new — 6 checks, milliseconds,
  zero cost; `--fail-on` gates a pipeline); `scripts/bake-off-metadata.py` (+3 arms,
  2 thinking-config fixes, **corrected a 3× cost under-estimate** — Gemini constants were
  the Preview rate the file's own comment had flagged and nobody acted on);
  `wiki/planning/transcript-archive-diagnosis-2026-07-28.md`;
  `session-archiving-upgrade-plan-2026-07-21.md` (B7/B8 added + priority raised);
  `wiki/working-notes.md`; `wiki/claude-observations.md` (Obs 32–35);
  `wiki/user-observations.md` (4 candidates pending); `notes/_inbox.md` (3 flags).
- Data: bake-off artefacts (5 arms × 10, 2 blinded rubrics + key sidecars, 2 Claude
  scorecards, dated manifest with paths re-resolved by session id).
- **Open / carry-forward:** 2026-07-28 time log EMPTY (full day untracked);
  `CATALOG.json` stale (538 vs 804; map-reader 73 vs 196) — regenerate after backfill;
  `session_chunks` still 4,691 rows under the old project name (rebuilt at re-index);
  **Sonnet 5 price constants go stale 2026-08-31** when intro pricing ends;
  canonical-layout decision still unmade beyond map-reader (blocks a clean backfill);
  Zotero write-key test still untried; user-obs candidates 2026-07-24 + 07-27 + 07-28
  all pending review.

### 2026-07-27 (Mon, latest PA-hub) — SESSION CLOSE (/handoff): the three-submission week ran through this session; W30 review + pace ratified; RDA Drive mis-pair found and fixed; memory-integrity trilogy

Six-day arc as the PA-hub coordination layer (amd-tower; resumed 2026-07-21 from the
model-swap beacon below; Shawn on zbook Fri–Sun). **The week's headline ran through this
session's rituals: THREE SUBMISSIONS** — Cosmos (Tue 21, Day 16, claim-by-claim +
clean-context adversarial verification first), RDA IG proposal revived+circulated (Thu 23,
Day 4), Paper B to RSOS (Fri 24, **RSOS-261690**, via zbook; queue pre-cleared here Wed–Thu).
Canonical record: `reports/weekly/2026-W30.md` (written Mon 27, retrospectively — weekend
was rest by design). **W30-review decisions:** Slot 1 = clear-all-reviews drain (named day
Thu 30); pace RATIFIED into `tasks/SYSTEM.md` (`workday_target_hours=7 tracked` avg;
`evening_hard_stop=22:00`, emergency-only override; Claude's post-22:00 wind-down reminder
standing, scratchpad 2026-07-23); wildcard credibility-review probe Fri 31; Substack w/c
3 Aug; June+July retro Fri–Sun. **Slot 2 = map-reader** (rotated Wed 22 via an in-session
prioritisation conversation — the reframe that unlocked it: the two llm-repro directions
consume different resources, so the JAS run competes with nothing while the wildcard
competes with map-reader for drafting hours; Day 1 block finally ran Mon 27 ~12:40 after
two explicit trades; **Friday floor deliberately deferred to first-generation evidence** —
first full paper-generation with the academic-prose skill, revision-cost range 30–60h,
checkpoint at Mon's recap). **Slot 3 = llm-repro JAS** (rotated Fri via zbook; §9 verdicts
first). **Infrastructure findings this session, all repaired:** (1) circular skill
self-symlinks deleted — and the apparent regenerator was daily-sync's `stash -u` cycle
refreshing untracked-file timestamps (scratchpad rule; `scripts/daily-sync.sh:262`);
(2) memory-integrity trilogy — 29-record zbook below-cursor gap (16 Jul splice), 23-record
pre-commit loss recovered PG→JSONL (instance 3 of the class; map
`data/logs/pg-recovery-2026-07-23.json`), plus two more below-cursor repairs during syncs
Thu/Mon; both machines converged (id-diff 0/0, 100% embedded; ~32.9k records) — the
integrity inbox row is now the drain session's headline; (3) **RDA Drive mis-pair** found
Mon: the Drive "Summary_and_Description" doc held the final SoW and the "Statement_of_Work"
doc held the pre-trim SoW — the actual 410/848-word Summary+Description had never reached
Drive; local files had been deleted with Downloads, recovered byte-exact from trash,
archived privately (`data/archive/rda-ig-application-2026-07/` — member emails, hence not
public wiki), both Drive docs re-pasted by Shawn and marker-verified correct. RDA sequence:
group reminder ~Thu 6 Aug → comments close Fri 14 Aug → **submit Mon 17 Aug**; Kiera STM
confirmation in flight; word-cap provenance resolved (the 250–400/500–800 "limits" are
self-imposed, not RDA's — template V4 + page + web form all checked). **Live waits:** Adela
(Slovakia; calendar check Wed 29 15:00; hard deadline Mon 3 Aug), lawyer, RSOS (1–3 mo),
Cosmos (~mid/late Aug), ARDC postings (~3 Aug), Emmanuel (Fri 31). BolgiaTen invoice PAID
(confirmed Mon). **Carry-forward:** new Zotero write keys (Mon) may unblock the stalled
`sync-to-zotero` pipeline (403 since May; hypothesis = key/library mismatch,
`sync-to-zotero.py:320`) — test pending; 2026-07-24 AR user-obs batch still pending review.

- Public repo: this entry; `wiki/user-observations.md` (2026-07-27 pending candidates);
  `wiki/claude-observations.md` (Obs 29–31); `tasks/SYSTEM.md` via symlink (pace params).
- Data: `reports/weekly/2026-W30.md` + 3 collaborator reports; standups 07-21→27 with
  recaps + commitments; FOCUS.md (all three slots re-populated across the arc);
  waiting-for (Adela travel, invoice closed, Kiera, RSOS); inbox (19 held — drain Thu;
  eRA captures; RDA sequence; public-docx privacy item); backlog (map-reader follow-ups,
  wildcard probe, eRA deadlines); scratchpad (stash-cycle rule, wind-down rule ratified);
  `archive/rda-ig-application-2026-07/`; time-log Mon–Mon.
- Session continues for Shawn in a fresh context (map-reader block running; recap tonight).

### 2026-07-21 (Tue, latest PA-hub) — SESSION WIND-DOWN (model swap Opus→Fable): six-day accountability arc Wed 15 → Tue 21; Paper B SUBMITTED-READY + handed to Brian; W29 review + two-month runway plan; Cosmos at the goal line

Long multi-day session (amd-tower, PA-hub). **Ran the task-system daily through Paper B's
end-game and into the two-month runway.** Resume state below is the beacon — the durable
records are FOCUS.md (runway record at top + all three slots), `reports/weekly/2026-W29.md`,
and the standup files 07-15 → 07-21.

**Focus slots (as of Tue 21, 11:15):**
- **Slot 1 — Paper B: task CLOSED Fri 17** (15d in focus; "edit §3→end" done). Editing pass
  finished end-to-end (§4 frozen, §5 rebuilt, Conclusion, abstract, bibliography), handed to
  Brian as a **submission-ready RSOS-templated manuscript**. **Waiting on Brian's weekend
  readthrough + adversarial read.** Successor task = **RSOS submission, Fri 24 Jul, all-day
  booked** (Google Calendar event created; ~30 min minor LaTeX/bibtex fixes in the paper-b
  beacon; celebration beer). Slot in waiting state — no action unless Brian hands over early.
- **Slot 2 — Cosmos grant: AT THE GOAL LINE.** OSF prereg **LODGED 2026-07-20** (with embargo;
  osf.io/dqnhg) = serial gate cleared. Overnight session redrafted the 500-word application.
  **Tue 21 first action (IN PROGRESS at wind-down): verify the redraft (list every number/
  name/date/claim as verified-vs-record or from-memory — error_mode drumbeat this week) →
  SUBMIT today.** Brian read optional (he approved v0.3 on 09 Jul); submit by **Thu 23 latest**
  either way. Deadline Sun 26. **This closes the slot — sixth-move history, no Paper-B excuse
  left.**
- **Slot 3 — RDA WG proposal: promoted Mon 20**, named day Tue 21 scoped to **reconnaissance
  only** (locate docs, take stock, pull together what needs adding/changing); actual edits +
  WG-member emails slide to Wed to protect the reset. Target Oct 2026.

**Two-month runway (set at W29 review 07-20; full record atop FOCUS.md):** must be **out of the
house ~15 Sep**. Separation disclosure SUBMITTED 07-20 (Shawn's done, Adela's forwarded) →
gates Family Court → ~1mo settlement → title transfer → sale. **W30–31 = full-time research
push** (cheap-revision window); **from 3 Aug ~20h/wk = 10 EFN + 10 research**. **ARDC ads
expected week of 10 Aug** (CEO back 3 Aug), 3–4wk process, Shawn 70–80% success → start ~21 Sep.
**Mid-Sept targets:** map-reader SUBMITTED, llm-repro JAS research phase DONE (25–35 papers),
**inscriptions → stretch/fallback**. **Load-bearing dependency: the style-gap halving**
(write-like-me workstream, parallel session; `academic-prose` skill shipped 07-19) — the
40h/paper estimate assumes it; Paper B's measured base rate at the current gap is 57.25h.

**Pace mechanism (Shawn asked to be held to Paper-B-style treatment):** Sunday 07-19 stamina
crash (recovery, not slip); Mon 07-20 hit 9.25h over the proposed 8h ceiling. **Tue 21 =
deliberate RESET** (earlier meals/exercise/bed); today's ceiling = **quit ~16:30–17:00, breach
signal past 17:30 → log at recap**. **Standing 8h-number + hard-cap consequence deferred to the
W30 review BY DESIGN** (ratify on reset-week data, not one crashed Sunday). Do not let "defer to
W30" become "never" — W30 review must name the standing number.

**Live waiting-on (load-bearing):** lawyer's post-disclosure step (the sale/move chain);
**Adela disclosure return — ping Mon 27 Jul, HARD DEADLINE Mon 3 Aug**; Brian (Fri 24);
Emmanuel (reply-or-park ~24 Jul); ARDC (monitor postings from ~3 Aug).

**Open, un-scheduled:** **clear-all-reviews session** (13 inbox items + ~35 notes-inbox rows +
the **2026-05-29 vocab-validation report still unapplied** — its gate, Paper B, has cleared;
wants a slot this week; wiki cluster-and-carry deferred at W29 to here). **June+July → ONE
retro at month-end (~31 Jul)** — named, on time.

- Public repo: standups 07-16→07-21; `wiki/continuity.md` (this entry); FOCUS.md (runway record
  + Slots 1–3); this session's commits through wind-down.
- Data: `reports/weekly/2026-W29.md` + 3 collaborator reports; `reports/time-log.csv` (07-15→21,
  ~50 rows); `reports/work-log.md` (07-17, 07-20); `tasks/waiting-for.md` (Brian/Adela/lawyer/
  Emmanuel/Rory-parked); `tasks/backlog.md` (reflect-and-prioritise done, RDA promoted);
  `tasks/inbox.md` (Flinders + Odette captures; §5 row closed); memories (recap + hook
  extractions). All committed + pushed.
- Model swap: Opus 4.8 → Fable at this point. Next session resumes from this beacon — no need to
  re-read the session body.

### 2026-07-15 (Wed, latest PA-hub) — SESSION CLOSE (/handoff): standup + machine-swap sync (zbook → amd-tower daily driver); memory mirrors converged after three-layer repair; Zotero write-back diagnosed (broken on BOTH machines)

Morning: standup (11:20 — late start absorbed as load-bearing §5 review; Wed = paper-b
push, target draft DONE, floor ≥8 cleared paragraphs) + /track rows (efn 0.75, paper-b
1.5). Afternoon (delegated in full while Shawn edited §5): home-network reintegration
for the daily-driver swap. **(a) Repos:** zero unpushed anywhere; 4 zbook + 9 amd-tower
repos fast-forwarded; stranded work committed + pushed (colour-names — README/.gitignore/
data/docs/scripts, 23 files; map-reader `proposer-all/` artefacts; 3 sapphire inscriptions
run logs from 20–21 Jun). **`~/Code/vivienne` has NO remote — decision pending** (same
class as the talks row, which resolved as already-private-since-1-May → inbox-archive).
**(b) Memory system, three layers:** (1) amd-tower's sync jam (poison record, backlog
row 21) cleared by git pull — non-interactive auth worked around the passphrase-protected
GitHub key via the live GNOME-keyring agent (`SSH_AUTH_SOCK=/run/user/1000/keyring/ssh`);
(2) full derived-store rebuild on amd-tower (pre-dedup ghosts: 38,039 → 30,798 rows;
backup `/tmp/claude_memories-pre-rebuild-20260715.sql.gz` on amd-tower; embeddings via
sapphire; `apply-decay` then run on BOTH machines — zbook's weekly decay was also stale);
(3) two integrity defects found and repaired — **five records (session `7611d1aa`,
13–14 Jul) lost from canonical** (existed only in zbook PG; never committed — `git log -S`
empty; mechanism unconfirmed, and NOT prevented by the `merge=union` driver in place since
2026-04-30, data commit `020826f`) recovered by PG→JSONL serialisation (lines 30803–30807);
and **14 amd-tower travel-period records union-merged at the fork point (lines
28384–28397), below zbook's already-advanced line cursor** — invisible to incremental sync;
fixed by cursor rewind + replay (insert accounting clean: 11+3 inserted, 0 unexpected
drops). The splice-below-cursor behaviour is *systematic* whenever a cross-machine merge
lands older appends — candidate fixes in the 2026-07-15 inbox row. **Final state: PG id-diff
between machines = 0; 30,811 rows each; 100 % embedded; sessions table 713; cron green.**
**(c) Servers:** Vantec re-attached + unlocked by Shawn (`/mnt/vantec` 9.4 T used / 4.5 T
free); rpi-shares SSHFS-mounted on both clients (manual — autofs row still the durable
fix); cc-archives converged (3 passes) on both + **first R2 offsite push since 23 Jun**
(amd-tower, 14:09). **Zotero write-back — investigation (Shawn-requested):** his memory
("worked on amd-tower before I left") was **treated as a lead and was right about config**
— amd-tower's `.env` has all four current key names (count-only check; the 23 May rename
`e2d12ac` is NOT the issue), and the chain's "must be set" error was an artefact of my
env-scrubbed `setsid` invocation (the script has no dotenv loading; it relies on the
caller sourcing `.env`). The real defect is **identical on both machines** with env
loaded: GET 404 (target items `MPZHXY3P`, `FGM4PVSX` absent from `users/3097511`) + POST
403 "Write access denied" — 5 `source_insight` notes pending since 2026-05-19/20 (+56
skipped_legacy); the cursor correctly refuses to advance. **Root-cause hypothesis:
`build_zotero_client()` hard-codes library type `"user"` (sync-to-zotero.py:320) while
`ZOTERO_API_KEY_PAPER_B` + the referenced items likely belong to the paper-b GROUP
library.** Correction needs Shawn's Zotero-account knowledge — see the new
things-to-verify item. Held over per no-silent-discard: two working-notes candidates
(W-a id-diff integrity instrument; W-b rebuild economics) + four user-obs candidates
(pending section in `wiki/user-observations.md`) await verdicts. **Resolved same
session (verdicts given at handoff review): W-a + W-b ACCEPTED → written to
`wiki/working-notes.md`; user-obs 2 & 4 ACCEPTED, 1 & 3 discarded (heading updated).**

- Public repo: this entry + things-to-verify items; `wiki/user-observations.md`
  (2026-07-15 pending section); `wiki/claude-observations.md` (Obs 21–22).
- Data: `tasks/inbox.md` (talks row → archive; rpi-shares update; integrity-defects
  row added then amended re `020826f`); `tasks/inbox-archive.md`;
  `memories/memories.jsonl` (5 recovered records, lines 30803–30807);
  `notes/_inbox.md` (2 wiki-candidate lines); `standups/2026-07-15.md` (morning).
- Other repos: colour-names, map-reader-llm (zbook pushes); inscriptions (sapphire
  push `chore(runs)`); paper-b/llm-repro untouched (Shawn's sessions own them today).

### 2026-07-13 (Mon, latest PA-hub) — SESSION CLOSE (/handoff): five-day accountability arc Thu→Mon; W28 review; throughput estimation instrumented

Ran the task-system hub across the Paper B submission run-up: daily standups (Thu 09 15:07, Fri 10 14:43, Mon 13 13:32 — three consecutive afternoon standups, twice masking real untracked morning work), recaps (Thu; Fri's rolled into the review by agreement), /track cadence, and the **W28 weekly review (Sun 12)**. System outputs: **(1)** W28 review + three collaborator reports (canonical completions incl. ANU teaching 100% closed, GEOMAR champion-grade follow-up delivered on hard deadline, travel-insurance Slot-3 close — 20d in inbox → 1d in slot → done). **(2)** **Editing-time estimation switched to empirical throughput** — ~1.8–2.0 paragraphs/hour from three convergent measurements (time-log hours × LaTeX paragraph counts); `notes/llm-craft.md` +3 entries; scratchpad rule added: prompt for paragraphs-completed on paper-editing /track rows; cold-start a new paper from the previous paper's pace (~4–5 paragraphs to recalibrate). **(3)** Evidence-layer Obs dispatched to the paper-b register via obs-writer (paper-b `e2a017b`; the agent's verification corrected two seed anchors — write-side anchor rule validated in production). **(4)** Captures: **write-like-me prose quality (URGENT** — throat-clearing/filler/circumlocution, low fact density; plan = mine Paper B §§1–4 git history when §4 done, then a planning discussion with Claude), clear-all-reviews session, **RDA WG proposal** (backlog; promote when Paper B clears — third claimant alongside map-reader re-entry + llm-repro re-mobilisation), 5%-sampling methods-paper row. **(5)** Paper B state at close: §3+§4 DONE, paper reorganised (old §5→§4.5, §6–7→Discussion), **submission target Fri 17 Jul** (Brian push-hard for a Thu/Fri-AM half-day readthrough — ask sent; **8-paragraph tripwire today** or flip to Mon 20; Wed-all-day-push option open, decision at tonight's recap; IS-wheels in/out of the submission Discussion still undecided). **Retro overdue (June) — Shawn committed to /retro this week.**

- Gates RESOLVED same day (2026-07-13 review): working-notes **W1 accepted** (throughput-extraction → `wiki/working-notes.md` 2026-07-13 entry); W2 (slots-vs-calendar) discarded. User-obs: 1 accepted; 2 discarded with correction (late standup = morning personal matters + after-dinner work block — captured to scratchpad); 3 discarded. Prior pending user-obs batches (2026-06-20, 2026-06-21) still await verdicts — feed the captured clear-all-reviews session.
- Data repo commits `4c5eb91` → `dd01ec3` (standups 07-09/10/13 + recap + probes; W28 review + brian/steve/penny collaborator reports; time-log rows Thu–Sun; FOCUS/inbox/waiting-for/backlog dispositions; llm-craft +3; scratchpad rule)
- paper-b repo: `e2a017b` (obs-writer: "The evidence layer was the work")
- Calendar: GEOMAR response trigger (all-day Thu 16 Jul, free); Odette onboarding call (Tue 14 Jul 09:00–11:00)
- Corrections of record: return flight is **Tue 14 Jul 16:00–17:30** (not Mon 13); home-network-gated items actionable from Wed 15 Jul

### 2026-07-09 (Thu, latest career/cosmos) — SESSION CLOSE (second /handoff): four-day ritual arc Tue–Thu; context cleared

Addendum to the 2026-07-06 capstone below — the same session continued as the **persistent coordination layer** through Thu morning while dedicated sessions did the substantive work. Canonical records are the daily files (`standups/2026-07-06/07/08.md` with recaps inline; `reports/work-log.md`), not this entry. Headlines: **Tue** — Cosmos solo draft v0.1→v0.2 same day (Brian fallback invoked at standup), prereg-before-submission decided, Odette admin phase done, valuation form in, Sarah Bevan silence explained (paralegal transfer). **Wed** — ARDC call banked (**roles advertised ~fortnight, ≈22 Jul**; application backlog row created); ANU teaching **100% closed** (5 legacy rows discharged); GEOMAR = warm institutional prospect with internal champion (memory `2026-07-08-4904f1f919a4`); §4 tripwire fired at 18:00 → **slip declared to Brian same-day** (Fri COB best case → Mon central); calibration rule adopted (evidence count, not prose maturity; decomposed-from-combined = hidden evidence debt); backlog row: re-mobilise llm-reproducibility post-RSOS ("no direct rival" verified). **Thu (this close):** retroactive +0.5h efn (Steve check-in) → Wed totals corrected to 7.25h in standup + work-log addenda (the Wed progress memory still says 6.75h — superseded by the CSV, which is canonical for hours).

- Observations: claude-obs 16 (pre-decided rules were the load-bearing element of the crowded week) + 17 (self-critique: stray `cat` timeout + verified-state recovery); user-obs candidates ×3 (pending) — **prior pending batches: 2026-07-05 PA-infra and 2026-07-06 (partially reviewed) still await verdicts** where unreviewed.
- Live tripwires handed to today's standup (fresh session): §4 finish (evidence-heavy half remains), **GEOMAR invite HARD DEADLINE COB Thu** (champion-grade), GroundSight 16:30, paralegal escalation call (calendared), Brian poke re Cosmos window, Odette briefing call if scheduled. Thursday recap carries the Friday weekly-review reminder.
- Commits this arc: daily-file + task-row commits Tue–Thu in data (see `git log` there); this close's commits follow.

### 2026-07-06 (Mon, latest career/cosmos) — SESSION CAPSTONE (/handoff): Cosmos grant DECIDED (llm-reproducibility) + framed; ARDC PM brief for Wed 8 Jul; 1 May talk-session archaeology

Professional-tasks session spanning Sun 5 – Mon 6 Jul (Cosmos = FOCUS Slot 2; ARDC = new `career` workstream). Four outcomes. **(1) Cosmos project-choice DECIDED: llm-reproducibility, AI x Truth-seeking track.** Grant facts verified at source (deadline **Sun 26 Jul 2026**, US$1k–10k+, 90-day build, rolling review ~4 weeks, Airtable form); **186-grantee proximity scan** across all five Cosmos programmes via the community site's JSON API (`/api/search`) found *no* overlap — nearest neighbour Metalens is the evidence-synthesis layer, complementary to our verification layer; the paper-b-derived alternative (decompose → fresh-context review → human verification) was evaluated and **folded into the pitch as the human-verification surface**, not pitched separately (claim-verification is the portfolio's most crowded cluster). Framing + brainstorm-grade budget externalised to llm-reproducibility `wiki/planning/cosmos-grant-application-framing.md` (commit `ee2a099` there, incl. planning-README indexing fix); FOCUS Slot 2 reframed to **write-and-submit the 500-word application** (data `4e968f7`). Extraction/credibility lanes: frame + track record, *not* 90-day deliverable. **(2) ARDC programme-manager prep.** Context recovered from Gmail: meeting with Natasha Simons **booked Wed 8 Jul 10:00–11:00 AEST**; the NDRI Outcome 3 bid is **funded**, several PM roles recruiting through ARDC Limited. Two-page brief at `data/notes/career/ardc-pm-brief-2026-07-08.md` (data `16181c0` + `c9c292d`): PM-role shape in NCRIS terms (six activities), WP2 as likely home (Shawn was RAiD Product Manager + Manager NII Products — RDA/RVA/PIDs), WP1 contingency (sharper COI exposure — EFN/Fieldmark), positioning reframe ("programme-shaped work without the title": FAIMS, NII portfolio, RAiD, EFN), question list, and **§8 critique-to-programme-design** — the bid's "AI-ready" conflation disambiguated as AI-as-trainee / querent / curator (curator carries the metadata-circularity risk). **(3) Session archaeology.** Shawn's half-remembered prior conversation about the bid was recovered: **1 May 2026 session `b8758cc7`** (`~/cc-archives/personal-assistant/2026-05-01T06-38_prepare-ardc-ai-talk-proposal-and-establish/`) — claude.ai search had failed because it happened here. Recovered verbatim: the bid critique (train-on vs query-by; load-bearing Fig. 2 agent; 75/25 underspecification; CARE thinness), the talk spine, the sent 1 May proposal email (Gmail), and the NDRI PDF source (Natasha's 19 Sep 2025 email "Outcome 3 NDRI"). The `~/Code/talks` repo created that session is **on amd-tower, local-only, no remote** (I initially mis-declared it deleted — see claude-obs 14); remediation captured to inbox. **(4) Memory + tracking:** `/remember` Vivi-in-Denmark capacity fact (`2026-07-05-998146e281d4`: 1 Jul 2026 – 30 Jun 2027 provisional, ~4h/day freed); `/track` 2h logged for Sun (1.5 cosmos-grant + 0.5 personal-assistant).

- Public-repo commits: this handoff entry + observations (user-obs pending ×4, claude-obs 13–15); prior pointers `06680e2`, `b701985`, `3ceff15` (+ this session's closing pointer).
- Data commits: `4e968f7` (FOCUS Slot 2 + time-log + memory), `16181c0` + `c9c292d` (ARDC brief), plus the handoff sweep (inbox capture, `notes/_inbox.md` flags, memory-file appends).
- llm-reproducibility commit: `ee2a099` (framing doc + continuity + planning-README index).
- **Working-notes candidates: BOTH ACCEPTED (Shawn's verdict, post-handoff 2026-07-06)** and written to `wiki/working-notes.md` — (A) `community.cosmos-institute.org/api/search` undocumented JSON API (check for a data backend before browser automation); (B) session-archaeology workflow (PG title search → transcript zgrep → subagents → Gmail, ~15 min to full recovery) + the local-only-repo hazard.
- **User-obs verdicts (post-handoff 2026-07-06): 1, 2, 4 accepted; 3 discarded** — recorded in `wiki/user-observations.md`. **Still pending:** the 2026-07-05 PA-infra user-obs batch never got verdicts.
- **Loose ends handed to next session/standup:** ~~Monday's session time untracked~~ → **tracked post-handoff** (1h career ARDC prep Mon; 0.5h W27 weekly review Sun, catch-up); `tasks/waiting-for.md` ARDC row predates the funded-bid news + booked meeting — update at standup; Cosmos first move (open Airtable form, capture questions) is the Slot 2 task, clock running since Mon 6 Jul. Weekday-slip correction: 2026-07-05 was a **Sunday** — two "(Sat)" labels in FOCUS Slot 2 and this entry's span line fixed post-handoff.

### 2026-07-05 (Sun, latest PA-infra) — SESSION CAPSTONE (/handoff): docs-vs-wiki convention promoted; zbook PG mirror repaired; sync poison-records fixed; session_id forensics (44/84 reconstructed)

Session spanning Fri 4 – Sun 5 Jul (out-of-hours infra; Paper B stays primary). Four outcomes. **(1) docs-vs-wiki convention promoted to the cross-repo template** (decided 2026-07-03 in llm-reproducibility, commit `8845a45` there): `wiki/index.md` gained a Conventions subsection (product docs stay at repo-root `docs/` — GitHub Pages/JOSS; process record in `wiki/`; never nest process under `docs/`; never GitHub's Wiki feature; PA-style `wiki/docs/` exception), the README two-line disambiguation map, and a migration-precedent pointer (PA 2026-05-28 + llm-reproducibility). **(2) zbook PG memory mirror repaired** (executed the 2026-07-04 backlog row). Root cause was neither deliberate deprecation nor a broken cron: the 2026-05-02 audit deployed a schema-version gate in code while `schema.sql` was applied only on amd-tower — zbook's cron then failed every 5 minutes for two months (13,231 runs), invisibly, because recall falls back to JSONL. Repair: `schema.sql` applied (v3), pattern/gotcha decay flipped 180→NULL (the 2026-06-02 decision `ON CONFLICT DO NOTHING` cannot propagate — same trap awaits any config-row change), `rebuild-postgres.py --yes`, full repopulation (29,180 memories, 700 sessions, 100% embeddings via local Ollama, ~8 min, $0), four Slack forgets confirmed propagated, cron green. **(3) The rebuild surfaced two canonical-JSONL poison records that abort entire insert batches** — 43 manual records with `session_id: null` (a `.get` default only covers *absent* keys) and one `deadline_at: "TBD"`. Both now tolerated in `record_to_tuple`; the misleading "PostgreSQL unreachable" label on schema errors in `sync_memory_edit.py` split into unreachable-vs-query-failed; reference doc records the two-machine PG reality + the migration rollout rule. **amd-tower is almost certainly jammed on the same lines since ~15 Jun** — unreachable this weekend (away from home network); recovery is a `git pull` + one cron tick (new backlog row). **(4) Sunday loose ends:** `/remember`'s session_id spec now documents the derivation (session UUID is a path component of the scratchpad dir; verified against the transcript filename) and mandates omit-if-unknown — never null/`""`/invented (write path had produced 43 falsy + 41 confabulated slugs like `session-39`). Then forensic reconstruction of all 84 bad records: multi-pattern scan of 2,987 archived transcripts for the memory-ID capture echo, cross-checked against session time windows → **44 reconstructed with hard evidence, 40 stripped to field-absent** (25 origin-never-archived, 14 recall-only hits, 1 ambiguous — not guessed). Manual records now exactly 168 UUID + 40 absent; PG mirrored in the same pass. Also fixed the 2 pre-existing `test_lit_search.py` failures (tests still pinned the pre-`fbe743c` retry contract) + removed ~28s of real sleeping from the suite (1105 passed, suite 45s→15s).

- Public-repo commits: `b69c0a0` (wiki conventions), `0ade464` (sync poison-record tolerance + tests), `e6b56af` (sync_memory_edit error labelling + tests), `8413c33` (postgresql-reference update), `fe95602` (remember.md session_id spec), `476974c` (lit-search test rewrite).
- Data commits: `ed3f58d` (backlog: repair row → amd-tower follow-up row), `0cb74c4` (memories.jsonl session_id rewrite + audit map `logs/session-id-reconstruction-2026-07-05.json`); pointers `cb5b4cc`, `3c06996`.
- Machine-local (zbook, not repo): `claude_memories` DB now schema v3, fully populated, cron green.
- Other-workstream files untouched (incl. untracked `wiki/planning/paper-review-skill-spec.md`).
- Next session (Shawn's stated plan): Cosmos Institute grant (FOCUS Slot 2 — clock starts Mon 6 Jul, first step = project-choice decision) + prep for an informal ARDC job discussion (new topic, no doc yet).

### 2026-07-03 (Fri, latest code-uplift) — research-code uplift ASSESSED + DEFERRED; Slack Wayland fix (drive-by)

Short session, two outcomes. **(1) Research-code review & FAIR4RS uplift assessed, then deliberately deferred** — Shawn asked how to approach reviewing/improving the inscriptions + map-reader code (both entering write-up; outputs must keep reproducing) and uplifting FAIR4RS apparatus, prompted by the Fable-on-Max availability window. Stock-take: **no FAIR4RS skill exists** (the half-remembered start is the *manual* trap-extraction uplift + map-reader's earlier pass + the untracked paper-review-skill spec's architecture); both repos are better-appointed than feared but carry untracked output dirs. Recommended approach: **freeze first (tag + golden-output regression harness over the deterministic half), then review behind the harness** (output-preserving refactors free; output-changing fixes are logged findings), FAIR4RS uplift additive; durable artefact = two skills (`fair4rs-audit`, `research-code-review`) built by codifying a manual inscriptions pass, not in the abstract. Full assessment: `wiki/planning/research-code-uplift-assessment.md`; backlog row added. Deferred: Shawn is single-threading Paper B. **(2) Slack-won't-launch diagnosed + fixed on zbook** (deb 4.50.143 crashes under native Wayland — mutter kills it on a bad `xdg_toplevel.set_min_size`; user-local `.desktop` override forces `--ozone-platform=x11`), captured as memory `2026-07-03-9bacc8f5f296` + 3 dup/suspect auto-extracted rows flagged for `/forget` (decision pending).

- Artefacts: `wiki/planning/research-code-uplift-assessment.md` (new), this entry, `tasks/backlog.md` row (data submodule), memory `2026-07-03-9bacc8f5f296` (data `22f39a0`, pointer `69084db`), `~/.local/share/applications/slack.desktop` (machine-local, not repo).
- Other-workstream files left untouched (incl. untracked `wiki/planning/paper-review-skill-spec.md` — owned by the Paper B §2 session).

### 2026-06-21 (Sun, latest PA-infra) — SESSION CAPSTONE (/handoff): safe session-search system built end-to-end; claude-obs plumbing landed; LLM-use inventory + standard

Heavy out-of-hours infra session, four workstreams (research sprint stayed primary; FOCUS.md untouched except the inscriptions Slot-2 closure noted below). **Headline: the safe session-search system** — built in response to an ad-hoc transcript search that hard-locked Shawn's machine for hours (diagnosis: inscriptions `planning/archive-search-crash-diagnosis-2026-06-21.md`). Treated the diagnosis as input to *verify*, not a spec: its "build fresh SQLite FTS5" recommendation was superseded because the project already runs PostgreSQL + `pg_trgm` + `pgvector`, so the real fix is an integrated `session_chunks` index (per-turn prose, generated tsvector GIN + trigram). Shipped the full escalation ladder Shawn remembered wanting — memory → session metadata → **content search** → exact-turn retrieval → bounded `.gz` fallback. Two design pivots from the diagnosis, both recorded: PostgreSQL not SQLite; a **pure-Python scan engine not `rg`** (on this machine `rg`/`grep` are shell *functions* routing to the Claude Code binary, not standalone tools — the harness `rg` was itself the OOM-killed process in the crash). Phased: safe fallback landed first as its own commit (crash-risk → zero immediately), then the indexed ladder, then a 5-agent adversarial `/audit` + fixes. **470 main sessions across 18 projects → ~49.7k prose chunks indexed; auto-index now wired into the SessionEnd/PreCompact hook chain** (incremental, ~0.5s overhead). `/audit` found no Critical bugs in the indexed path (SQL param-ordering + mtime-float-equality both proven correct); fixed the real fallback-path bugs (context-line duplication, dash-pattern rejection, `degraded`-systemd silently dropping the cgroup ceiling, LIKE-wildcard leakage in identifier search, gappy-ordinal `--show` context). **Also this session:** the **claude-observations plumbing** the 2026-06-20 entry queued — `/handoff` §4 split into 4a user-obs (gated) + 4b claude-obs (default-keep), `/reflect` SKILL gained a claude-obs step (symmetric dedup guard, either ritual may run first), three active repos seeded (paper-b, map-reader, LLM-History-Paper; inscriptions already had one), and `notes/working-with-claude.md` created as the shared curation stub. The **LLM-use inventory** for the JAMT Methods disclosure: a reusable hub generator (`scripts/llm-use-inventory.py`) + a hub standard (`notes/llm-use-disclosure-standard.md`), with the inscriptions instance regenerated v1→v2 (governance-leads, per Shawn's review feedback). Plus inscriptions /track (1.75h, analysis-phase handover) and FOCUS Slot-2 closure (analysis phase done + handed to DK co-authors; next deliverable post-Europe = JAMT outline, 10k words).

- **Session-search artefacts** (PA `d0da92e`→`b62c765`): `scripts/{_scan_archives.py,search-archives-safe.sh,index-session-content.py,search-sessions.py}`, `scripts/schema.sql` (session_chunks section), `scripts/memory_mcp.py` (search_sessions tool), `commands/search-sessions.md`, `settings-template.json` + live `settings.json` (auto-index hook), `global-claude-md/infrastructure-reference.md` (escalation-ladder docs), `tests/test_memory_mcp.py`. Inscriptions `b68b1f6` (diagnosis marked RESOLVED with the two divergences).
- **claude-obs plumbing** (PA `3d942ee`→`ae36fb6`, data `0bd9730`): `global-claude-md/handoff-protocol.md` §4, `commands/handoff.md`, `skills/reflect/SKILL.md`, `wiki/claude-observations.md`, `wiki/planning/claude-observations-rollout.md`, `notes/working-with-claude.md`; seeds in paper-b/map-reader/LLM-History-Paper repos.
- **LLM-use inventory** (PA `818ab20`/`4f1b939`, data `cccb169`, inscriptions `6d08b71`/`0ca58ac`): `scripts/llm-use-inventory.py`, `notes/llm-use-disclosure-standard.md`, inscriptions `reports/llm-use-inventory.md`.
- **This handoff:** `wiki/claude-observations.md` (Obs 7–9), `wiki/user-observations.md` (2026-06-21 candidates, pending), `notes/_inbox.md` (3 flags incl. SQLite→PG correction), this entry, Phase-0 row updated. **Other-workstream files left untouched** (`wiki/reflections/*`, the inscriptions session's `docs/notes/reflections/*`, the data-submodule memories on auto-sync).
- **Memory written** (`/remember`, rides auto-sync): `2026-06-20-24e4034721c7` — Shawn runs /reflect before /handoff; the claude-obs guard is symmetric.

### 2026-06-20 (Sat, latest PA-collab) — claude-observations: PA stub built + design refined (observer-axis); plumbing build queued for next session

Heavy multi-day task-system + collaboration-design session (out-of-hours; research sprint stayed primary). **claude-observations register** designed + stubbed 2026-06-18 (`wiki/claude-observations.md`, committed `24757aa`) as the Claude-owned, default-keep counterpart to `user-observations.md`. **Refined 2026-06-20** with Shawn's sharper rule — *register = the observer*: Claude-observing-Shawn (+ self-critique, + how-we-work from my vantage) → claude-obs; Shawn-observing-Claude (+ Claude relaying Shawn's in-the-moment reaction) → user-obs. **Verified build state:** the PA stub exists but **no skill references claude-observations** — the `/handoff`+`/reflect` plumbing and per-repo files were never built (deferred; see `wiki/planning/claude-observations-rollout.md` + a `tasks/backlog.md` build-out row), which is why other repos' handoffs (e.g. inscriptions) still mis-file Claude-observing-Shawn items as user-obs. **Decision: implement the plumbing next session** (Shawn driving via drive-bys while pushing Inscriptions + Paper-B to completion). Other outcomes (separately captured in standups/FOCUS): inscriptions **analyses COMPLETE + audited** (Slot 2, ahead of 24 Jun); map-reader → *results-to-share* (carried into trip); **holiday mode activated** (Denmark leg 24–29 Jun); SpiderOak reframed as a 6–8TB backup-strategy decision; calendar events for Brian's review (1–3 Jul) + the SpiderOak decision (18–19 Jul).

- Artefacts: `wiki/claude-observations.md` (Obs 1–6 + observer-axis clarification), `wiki/planning/claude-observations-rollout.md`, `tasks/FOCUS.md` (Slot 2 complete, holiday mode, map-reader reframe), `tasks/backlog.md` (build-out + SpiderOak/Brian/scheduled-agents rows), standups 06-17→19, calendar (2 events).

### 2026-06-06 (Sat, latest PA) — SESSION CAPSTONE (/handoff): write-path plan largely closed out; item 16 is the forward bet

Long out-of-hours workstream-B session (PA is out-of-hours; research sprint stayed primary — FOCUS.md untouched). Detailed per-piece entries below; this is the orientation summary. **Shipped (no-API, all committed):** P8 fixed (`sync_memory_edit.py` + `is_active` in sync — caught a real 9-day-stale forget live); item 16 Stage 1 (per-memory surfacing instrumentation, now visible in the health report [G] + weekly-review); item 8 drift-sweep built ([H]); P10 fixed (extraction `max_tokens` 2000→8000 + salvage — was silently dropping 81 dense windows); Item C pre-v2 backup removed; P3 closed as superseded; lit-scout Zotero fix branch merged; item 6 (anchor coverage) scoped + both deterministic levers killed by cheap validation (Lever A 13% net + dilution; Lever B negligible demand); a 5-agent QA pass (0 Critical, 3 small fixes); and `recover_anchors.py` brought to crash-safety parity with `archive-memories.py`. **Forward state:** the write-path plan §6a is largely closed — what remains is gated: **item 16 Stage 2** (the earned-utility archival stay-of-execution) needs months of surfacing data to accrue; items 7/10 are §8-gated until **2026-06-13**; P7 (Haiku-vs-Gemini) + item 15 (dedup) are API-gated. **The strategic conclusion of the whole P9→item 16→item 6 thread: earned utility (item 16) is the principled surfacing lever, not anchor coverage** — anchoring is repriced/capped, so let item 16 mature. **Next dated item: the 2026-06-13 §8 review** (the two dark sentinels stay OFF, `~/.pa-digest-stage1` ON; digest window undisturbed all session).

### 2026-06-06 (Sat, latest PA) — anchor-machinery robustness follow-up DONE: `recover_anchors.py` brought to crash-safety parity with `archive-memories.py`

Closed the QA follow-up flagged in the prior entry. **No quiet period needed** — it's a code change to the script, not a run of it (the quiet window only applies to executing `--apply`, which was NOT run). Brought `recover_anchors.py` to parity with the more-defensive `archive-memories.py`:

- **`fsync` before the atomic rename** (`apply_plans`): added `out.flush(); os.fsync(out.fileno())` before `tmp.replace(corpus)` (+ `import os`), so a crash/power-loss between write and rename can't leave a truncated corpus. Mirrors `archive-memories.py:356–364`.
- **Schema-drift guard in `_update_postgres`**: added `assert_schema_version(conn)` before the UPDATE — but with a **soft warn-and-return** (not `archive-memories`' `sys.exit(2)`), since the corpus is already committed by that point, so the JSONL is correct and only PG is left unreconciled (fix = `rebuild-postgres.py`). This is also a small improvement over the sibling's exit(2)-after-commit (which the audit flagged as partial-success-as-failure).
- **Recovery doc**: a comment at the `_git_commit` call documenting that a commit failure leaves the corpus rewritten-but-uncommitted (a later run blocks on the dirty tree), with the two recovery commands (`git commit -- memories/memories.jsonl` to keep, or `git checkout --` to discard and re-run; the pass is idempotent).
- **Deliberately NOT done:** the lock/commit reordering (restructuring the lock ordering is riskier than documenting the recovery — left as the doc above). Also left `archive-memories`' own `exit(2)`-after-commit untouched (a separate minor item, not corpus-risk).
- **Verified:** compile clean; dry-run (no `--apply`) intact (mutates nothing); 17 `test_recover_anchors` pass; full suite 1091 (only the unrelated lit-search 429 fails). No new unit test added for the `fsync`/schema-guard paths — they are mechanical parity copies of `archive-memories`' patterns, whose equivalent PG path is likewise not unit-tested (matched the sibling's test posture). **`--apply` was NOT run; no corpus mutation.**

### 2026-06-06 (Sat, latest PA) — QA pass: 5 agents (1 doc-update + 4 /audit slices); 0 Critical; 3 small fixes applied; anchor-machinery robustness flagged as follow-up

End-of-session QA to complement the piecemeal /audit use during composition. Dispatched 5 background sonnet agents (1 doc-updater + 4 read-only `/audit`-methodology slices over the memory-system code), then adversarially triaged the findings myself.

- **Documentation updated** (`global-claude-md/`): the doc agent reconciled `infrastructure-reference.md` (hooks/scripts tables — P10 max_tokens+salvage, the new `sync_memory_edit.py`/`surfacing_log.py`/`surfacing_stats.py`/`drift-sweep.py`, the health-report [G]/[H]), `postgresql-reference.md` (P8 is_active sync + the lockstep-helper section + multi-machine), `tier-2-retrieval.md` (item-16 surfacing instrumentation), `memory-system-reference.md` (is_active P8 note). **I reviewed the diff against source** and corrected one over-assertion (the agent claimed "the 5-min cron is amd-tower-only" as fact; reworded to "PG-writing paths are no-ops where there's no PG"). No CLAUDE.md / shared.md changes needed.
- **Audit verdict: ZERO Critical across all 4 slices.** Today's new code (P8/P10/item-16/item-8/#1) verified sound — P10 salvage path + cursor contract, P8 24×24×24 column alignment + 6-col UPDATE, the surfacing format↔parse round-trip, the health-report key contracts, injection prevention, best-effort contracts. 99/99 anchor-verify tests confirmed the existing contract.
- **3 small fixes applied** (today's new files only; +3 tests, suite 1091): (1) `sync_memory_edit.py` — guard a content-less malformed record with a clear error (NOT the audit's suggested `.get("content","")`, which would have *blanked* the PG content — caught by adversarial review); (2) `surfacing_section` (health report) — added the `last_any_at` recency tiebreak so the top-5 is reproducible; (3) `drift-sweep.py` — guard `load_records` so a missing corpus exits 2 cleanly, not a traceback.
- **Pushed back on** the "guard `import surfacing_log`" finding — it's a *sibling* module imported unguarded exactly like `digest_selector`/`_schema_version`; guarding it would break the codebase convention (only external deps are guarded). Skipped the cosmetic findings (dead guards, docstring notes, generator-contract nicety).
- **FLAGGED FOLLOW-UP (green-light needed — corpus-mutation code, NOT touched):** the anchor-machinery audit found a real **robustness asymmetry** — `recover_anchors.py` lacks the `fsync`-before-`tmp.replace()` and the `assert_schema_version()` guard that `archive-memories.py` has, and both release the rewrite lock before `_git_commit` (a commit failure leaves the corpus dirty + blocks re-runs, with no documented recovery). All pre-existing, low-probability, in guarded `--apply` paths. Worth a deliberate parity pass (bring `recover_anchors` up to `archive-memories`' crash-safety + document the dirty-corpus recovery), but it touches hard-to-roll-back mutation code → a separate gated effort, not applied unprompted.
- **Provenance:** `global-claude-md/{infrastructure,postgresql,tier-2-retrieval,memory-system}-*.md` (doc commit); `scripts/{memory-health-report,sync_memory_edit,drift-sweep}.py` + their tests (fix commit); this entry. Data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — cleanup: today's two signals folded into the health report ([G]+[H]); anchor-type expansion (Lever B) sized + dropped

Two no-API cleanups to make today's instrumentation pay off and to close a speculative lever.

- **#1 — surfacing + drift-trend folded into `memory-health-report.py` (and `/weekly-review`).** The earned-utility surfacing log and the drift-sweep trend log were accruing *invisibly*; now they surface in the standing report: **[G] Memory surfacing** (reads `surfaced.log` via `surfacing_stats.aggregate_surfacing` — distinct surfaced, ever-actively-retrieved, active/digest exposures, top-5) and **[H] Anchor drift trend** (reads `drift-sweep.jsonl` — latest fail % + last-8 trend). Both always-on + fast (log reads, no git/PG). `/weekly-review` already runs the report, so they appear in the ritual automatically; also added an optional weekly `drift-sweep.py` run (to append a trend point) + the two new fields to the review template. New pure `surfacing_section()` + `drift_trend()`; **+6 tests, health-report file 19 pass, full suite 1088** (only the 2 unrelated lit-search 429 fails). Live-verified: [G] already shows 11 distinct / 3 active / 8 digest exposures (the surfacing instrumentation has been firing live this session), [H] shows 297/1616 = 18.4%. This resolves item 16's "aggregator home" open call (health-report section, not standalone).
- **#2 — Lever B (anchor-type expansion / item 19) SIZED → DROPPED.** Read-only count over the 4,402 unanchored post-v2 memories: URL 6 (0 %), DOI 17 (0 %), arXiv 2 (0 %), PR/issue 138 (3 %, but `#NNN` is noisy), Zotero-key-like 84 (1 %, and `zotero` is *already* supported), memory-id 2 (0 %). The few real candidates also split badly on verifiability — URL/DOI/PR need **network** (so they'd just be `verified=false`), the locally-verifiable ones are vanishing. **No hidden type-narrowness reservoir; Lever B not worth building.** Recorded in the anchor proposal (Lever B + §7 #3) + plan.
- **Net for item 6:** both deterministic remedies now closed out — Lever A repriced to 13 %+dilution (drop the blanket mutation), Lever B negligible. Confirms **item 16 (earned utility) is the path**, and #1 just made its signal visible. The binding-constraint diagnosis stands; the at-source remedies don't pay.
- **Provenance:** `scripts/memory-health-report.py` + `tests/test_memory_health_report.py` + `commands/weekly-review.md` (#1); `wiki/planning/anchor-coverage-proposal.md` + plan §6a (#2 + #1 notes); this entry. No live change to the digest/hook; data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — item 6 Lever A Step-0 dry-run: repriced DOWN (13% net, dilution confirmed) → pivot to item 16 as the primary surfacing lever

Executed the read-only, no-API Step-0 dry-run of Lever A (deterministic anchor inference) over the back-corpus. It earned its keep exactly like P3's spot-check — it repriced a compelling-looking lever before any build or corpus mutation. Nothing written.

- **Method (read-only):** reused `triage_anchors.recovery_status` (unique file-suffix match) + `anchor_verify.verify_commit` over `broad_repo_set()` (32 repos, 21,671 basenames). For each of 2,550 unanchored required-category memories, extracted file/commit tokens from `content` and resolved them.
- **Net result: 13% (337/2,550) resolve UNIQUELY** (290 file + 47 commit), 76 ambiguous, **2,137 absent**. The §2 "40% gross" collapsed because most path-like tokens resolve **nowhere** — files named as *future work to create* ("sketch `notes/index.md`"), renamed/moved, or cross-project.
- **Quality is MIXED — dilution risk confirmed.** Eyeballing the inferred anchors: some genuine ("wiki structure will split into `wiki/index.md`"), but a real fraction tangential/future-tense ("`_inbox.md` should *move* from `notes/_inbox.md`") where the file existing doesn't verify the claim. Naive token-selection also mis-picks (chose `CLAUDE.md` over the more-relevant `scripts/schema.sql`). Effective high-quality reach ~150–200.
- **Pivot (recommendation revised):** **drop the blanket back-corpus mutation** — a modest, dilution-prone 13% doesn't justify rewriting the corpus + weakening the verified signal. **Make item 16 (earned utility) the PRIMARY surfacing lever** instead — it surfaces what actually gets *used*, regardless of anchorability (strictly more general, already instrumented Stage 1). A forward high-precision anchor-suggestion slice stays available but optional. The binding-constraint *diagnosis* stands; the deterministic *remedy* is weaker than hoped.
- **Provenance:** `wiki/planning/anchor-coverage-proposal.md` (Step-0 result section + §6/§7 revised); plan §6a P9 (c) updated. No code, no API, nothing written to the corpus. Data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — item 6 (anchor coverage / P9 (c)) SCOPED: the binding constraint, and its biggest lever turns out to be NO-API

Scoping/design pass for item 6 (anchor coverage) — the binding constraint P9 named and the verify-checks confirmed is flat at ~27 % of post-v2 writes. `wiki/planning/anchor-coverage-proposal.md`. No code, no live change, no API. Diagnosed at source (PG + the extraction prompt).

- **Why it binds:** the digest surfaces only from the `verified=true` pool (1,214 = 21 % of post-v2). Coverage gates everything downstream.
- **Root finding — the prompt's escape hatch is used wholesale.** Anchors are "required" for 6 categories, but the prompt says "if you cannot find an anchor, *either lower confidence to low or reword*" — and since `bind_confidence` overrides confidence anyway, "mark low" is the easy out. Of 2,542 unanchored required-category memories, **2,505 are `low`, 35 high**. By category the requirement bites unevenly: required 37 % vs other 10 %, but `decision` (biggest, 1,640) is only 32 % while architecture/completion/provenance hit 49–56 %.
- **The 27 % is a BLEND, not one ceiling:** a genuine ceiling for abstract categories (self_reflection 2 %, pattern 6 %, prompt_effectiveness 3 % — correctly unanchorable, forcing anchors = confabulation) + **real headroom in concrete-but-escape-hatched memories** — unanchored decisions that *name files* (`lit-scout-zotero-import.py`, `CLAUDE.md`…) but took the hatch.
- **Headline lever is NO-API — deterministic anchor inference.** Of the 2,542 unanchored required-category memories, **1,041 (40 %) already contain a file-path or commit-hash token in their content.** Resolve those tokens (reusing `verify_file`/`unique_suffix_match` from items 20/21) and add anchors that resolve uniquely — **no LLM, no API**, and it works both forward AND retroactively over the back-corpus for $0, superseding most of the API-gated LLM retroactive pass the plan had feared. Main risk: verified-signal dilution (an inferred anchor means "a cited file exists", weaker than "claim verified") — mitigated by unique-resolution + required-category-only guards.
- **Strategic fork surfaced:** item 6 (concrete) and item 16 (earned utility, abstract-but-used) are **complementary halves** — don't over-invest anchoring into the abstract categories item 16 will cover better.
- **Recommendation:** build Lever A (deterministic inference) as its own guarded effort; **Step 0 is a read-only no-API dry-run** to get the net-resolved count (how many of the 1,041 actually resolve uniquely) before committing. Levers B (anchor-type expansion, item 19) secondary; C (prompt tightening) P3-tempered + API-gated, deferred; D (LLM retroactive) largely superseded. 4 open calls in §7.
- **Provenance:** `wiki/planning/anchor-coverage-proposal.md` (new); plan §6a P9 (c) + §5 item 6 updated. Data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — P3 (extraction selectivity) CLOSED as superseded & deprioritised (reviewed with Shawn)

Reviewed P3 with Shawn and closed it. P3 was refuted 2026-06-05 (all three levers failed: prompt weak 11.4 %; confidence-gate invalid — `confidence` is a verification echo not value; per-run cap marginal). The review added the decisive context: P3's *concern* is already handled from the other end. **Closed as superseded, no lever shipped.** Recorded in the proposal ("Decision (2026-06-06)"), plan §6a P3 + §5 item 14.

- **Why closed:** (1) the volume's *impact* is managed downstream — archival cadence (P2/item 13) keeps the hot corpus lean, the byte-budgeted digest (Vector 2) caps surfacing, the digest favours the anchored pool; (2) **P10's fix (today) made the volume honest** — the densest windows that were truncated to zero now extract fully, so a "reduce volume" lever would fight a bigger, legitimate number; (3) **item 16 (earned utility, Stage 1 shipped today) is the principled successor to the dead Lever 2** — value comes from what gets used, not from `confidence`.
- **Parked, not pursued:** cross-run/write-time **dedup (item 15)** — the only reframed lever with real leverage, but embedding-driven (API-gated) + unbuilt, a separate deliberate project. Firing-cadence change considered + rejected (fights P10's truncation lesson). No further at-source selectivity work planned; revisit only on a concrete problem, via item 15 or item 16.
- **Docs only, no code.** `extraction-selectivity-proposal.md` (status → CLOSED/SUPERSEDED + Decision section), plan §6a P3 + §5 item 14, this entry. Data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — P10 IMPLEMENTED: extraction no longer drops truncated windows (max_tokens 2000→8000 + salvage; +11 tests → suite 1083)

Implemented the P10 fix (a)+(b) in the live extraction hook, per Shawn's go. No-API code change; ship-and-observe (no spot-check run). Back-fill of the 81 already-lost windows deferred (agreed not-worth-it-now; revisit after P3).

- **`hooks/extraction-hook.py`** — three edits: **(a)** new `EXTRACTION_MAX_TOKENS = 8000` constant replacing the literal `max_tokens=2000` (the truncation cause); **(b)** new pure `_salvage_truncated_array(text)` (`json.JSONDecoder().raw_decode`s the complete leading objects, stops at the cut-off tail, returns only dicts) + a `getattr(response, "stop_reason", None) == "max_tokens"` branch *before* `json.loads` that salvages the prefix and advances the cursor. The genuine-malformation `return []` path is kept for the 4 true-garbage cases; the C2 transient-error `return None` path is untouched.
- **Why salvage, not retry:** re-reading the same oversized window truncates identically (sizing, not transient) → naive "preserve + retry" would wedge (the C2 failure mode). Salvage keeps the N complete objects, drops only the incomplete tail, and advances — wedge-free.
- **+11 offline tests** (`TestSalvageTruncatedArray` 9 shapes: complete / mid-string / mid-object / first-truncated / `[`-only / `[]` / non-array / whitespace / non-dict-filter; `TestTruncationRouting` 2: max_tokens→salvaged-not-dropped, end_turn→unaffected). extraction-hook file **73 pass**; **full suite 1083** (only the 2 unrelated lit-search 429 fails remain). Live hook import-smoke clean (`EXTRACTION_MAX_TOKENS=8000`, salvage works).
- **Forward-only:** new dense windows now extract fully (or salvage); the truncation rate is observable going forward via the verify-check query. The 81 lost windows (~1,200–2,000 memories) stay recoverable from archived transcripts if/when the back-fill is scoped (after P3).
- **Provenance:** `hooks/extraction-hook.py` + `tests/test_extraction_hook.py` (edited); plan §6a P10 marked IMPLEMENTED. Data submodule + `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — P10 fix PROPOSAL written ((a)+(b)); lit-scout fix branch merged to main

- **P10 proposal** (`wiki/planning/extraction-truncation-proposal.md`) — Shawn picked "(a)+(b)". **(a)** raise extraction `max_tokens` 2000 → 8000 (headroom, self-funding); **(b)** detect truncation via `response.stop_reason == "max_tokens"` then **salvage the complete-object prefix** (keep the N fully-formed memories, drop only the cut-off tail) and advance the cursor. **Corrected my own earlier (b):** "treat truncation as transient / preserve the window" is wrong — re-reading the same oversized window truncates identically (a sizing problem, not a transient one), so it would **wedge** (the exact C2 failure mode); salvage-prefix is wedge-free and lossless for the prefix. (b)'s salvage logic is offline-unit-testable (no-API); an optional ~$4–5 Haiku spot-check quantifies the truncation-rate drop (gated). **Diagnosed + proposed, NOT edited** — live hook gets the careful treatment; implementation awaits Shawn's go (4 open calls in §9). Plan §6a P10 updated to point at the proposal.
- **lit-scout fix branch merged.** `fix/litscout-zotero-arxiv-doi` (`184d193` — Zotero import handles arXiv DOIs, multi-slash DOIs, author lists; 3 files: `scripts/lit-scout-zotero-import.py` + the two agent docs) merged to main (`3cce512`, `--no-ff`). Verified conflict-free first (`merge-tree` exit 0; main never touched those files since base `cb79b0e`). Post-merge: 69 zotero/lit-scout tests pass, script compiles. **Separate from the lit-search 429-retry test failures** (those are from a different concurrent session's `fbe743c`, on `lit-search.py` — unrelated; confirmed pre-existing on clean HEAD; that session owns the fix).

### 2026-06-06 (Sat, latest PA) — Weekend infra follow-ups: Item C backup removed, drift-sweep built (item 8), 3 background agents' findings folded in; P10 (extraction truncation data-loss) FOUND

After P8, cleared the two small background jobs + the two verify-checks (three read-only sonnet agents, all no-API), then built the agreed deliverable and logged a real bug the checks surfaced.

- **Item C — pre-v2 backup REMOVED.** Agent verified GO: the pa-data copy `data/archive/pre-v2/` (3 files — `claude_memories.dump` 96 MB + `memories.jsonl` 21 MB + `tag-vocabulary.txt` 432 KB, ~117 MB; the continuity "~96 MB" was the dump alone) is **byte-identical** (SHA-256 on all three) to the surviving rpi-server copy at `~/cc-archives/pre-v2/` on independent NVMe; `extraction.log` shows zero v2/schema/db errors since 2026-05-16. Removed from the submodule (data `71f361d`, parent pointer `8aee48a`); archive-not-delete satisfied by the rpi copy. Verified at source before deleting (didn't act on the agent's word alone); used an explicit pathspec so the live-append `memories/` wasn't swept.
- **item 8 — drift-sweep BUILT.** `scripts/drift-sweep.py` (+`test_drift_sweep.py`, 9 tests). Reuses the memory-health report's `tier_c_audit` **verbatim** (one resolution code path) but sweeps the **full** anchored back-set (no 30-day window — Tier-C's window covers all anchored only until ~late July) + appends a trend line to `data/logs/drift-sweep.jsonl` + a `--alert-threshold` exit code (default 25 %). Read-only re corpus/PG. First live run: **1,616 anchored, 18.4 % fail (absent 201 / recoverable 96 / ambiguous 64)** — matches the agent's read, validating the wiring + seeding the first trend point for the 2026-06-13 review. Trend log gitignored (`logs/*.jsonl` added to data/.gitignore, also tidying the untracked `archive-runs.jsonl`).
- **Drift verdict (background agent): STABLE.** 18.4 % vs 18.2 % on 2026-06-04; 7 commit-refs-nowhere unchanged → **no retroactive drift**, new failures just track corpus growth. Low urgency, hence the trend log over any fix.
- **Verify-checks (background agent) — two findings:**
  - **Anchor-production rate ~27 % of post-v2 writes, FLAT over 3 weeks** (26.1 / 26.6 / 30.2 / 26.0 % by week). Item 6 (anchor coverage) is the binding constraint and is **not self-improving** — reinforces P9(c). (NB the "~5–6 % anchored" figure elsewhere is whole-corpus incl. pre-v2; ~27 % is the post-v2 forward rate.) C2/C3 healthy: cursor flock present, 30 transient-sentinel firings (all 529 overloads 2026-05-20/22, all recovered), no Gemini model-rename errors.
  - **The "verified_set should ≈ post_v2" check premise was outdated** — verification only runs when an anchor is present, so the real near-identity is `verified_set` (1,563) ≈ `with_anchors` (1,613); the 50-record residual (anchored but `verified` NULL) is **benign** — 42/51 are manual `/remember` captures (no hook verification by design), only 9 are extraction records. No action.
- **P10 FOUND + LOGGED (real data-loss bug, NOT fixed).** The 84 "Failed to parse extraction JSON" errors are **NOT** hopeless inputs — **every one** is an `Unterminated string … (char ~6,200–7,800)`, the signature of `max_tokens=2000` truncation (`extraction-hook.py:585`) on content-dense windows. The `JSONDecodeError` path returns `[]` (`:653–656`), which per the C2 audit note **advances the cursor** → the window's memories are **lost forever**. Cruel inverse of P3: the *richest* windows extract zero. Logged as plan §6a **P10** with fix options (bump `max_tokens` 2000→~8000; check `stop_reason=='max_tokens'` and treat truncation as transient; quarantine raw failed responses) — touches the LIVE hook + validation is API-gated, so **diagnosed + proposed, not edited blind.** Awaiting Shawn's go.
- **Provenance:** `scripts/drift-sweep.py` + `tests/test_drift_sweep.py` (new); plan §6a (P10 added, lower-list items 4+8 marked done) + this continuity entry; `data/.gitignore` (`logs/*.jsonl`). The Item C removal is data `71f361d` / parent `8aee48a`. `wiki/reflections/*` untouched.

### 2026-06-06 (Sat, latest PA) — P8 FIXED: `/forget` & `/update` now propagate to PostgreSQL in lockstep (caught + fixed a real 9-day-stale forget live; +15 tests → suite 1065)

Fixed plan P8 (the `/forget`+`/update` → PG propagation bug) in the main thread, per the plan's preferred option (a) plus the root-cause sync gap. No-API. Two parts:

- **(1) Root-cause: `is_active` was synced nowhere.** Added `is_active` to `sync-to-postgres.py` in three aligned places — `JSONL_FIELDS`, the INSERT column list, and `record_to_tuple` (`record.get("is_active", True)`), appended LAST so existing tuple indices (the v3 fields at 20/21/22) stay stable. This covers the forget-**before**-first-sync edge: a not-yet-synced forgotten row now INSERTs inactive instead of being resurrected `is_active=TRUE` by the column default. Verified 24/24/24 alignment (INSERT cols == tuple len == JSONL_FIELDS).
- **(2) The lockstep UPDATE: new `scripts/sync_memory_edit.py`.** Modelled on `recover_anchors._update_postgres`: given `--id`, reads the (already-edited) JSONL record and issues a surgical `UPDATE` of the six mutable columns (`is_active`/`content`/`confidence`/`verified`/`anchors`/`revisions`) so PG mirrors JSONL. Idempotent; one UPDATE reconciles both commands (a /forget changes is_active+revisions; an /update changes content + clears verified/anchors). Pure `find_record` + `extract_values` (defaults mirror the PG column defaults) + an injectable-`connect` `reconcile_pg` (tested without a live DB). Exit codes: 0 reconciled / 0 benign not-yet-in-PG / 1 PG-unreachable (WARN → run rebuild later) / 2 id-not-in-JSONL.
- **Wired into both commands** (`commands/forget.md` + `commands/update.md`) as a **mandatory** final step, replacing the false "PostgreSQL sync is automatic" claim with the exact `sync_memory_edit.py --id [id]` call + the why (INSERT-only sync can't propagate edits to existing rows).
- **Caught the P8 bug LIVE in the wild.** Of the two `is_active=false` JSONL records, `2026-06-05-52451aba7fd4` (hand-reconciled yesterday) was correctly inactive in PG — but `2026-05-28-183835fe9bfc` had been `/forget`'d on 2026-05-28 yet PG still had `is_active=TRUE` and it was **still in `active_memories`**, silently surfacing in recall for **9 days**. The new helper reconciled it (now 0 in `active_memories`) — a genuine recall-correctness fix, not just a smoke test. (This is a machine-local PG data change on amd-tower; not git-tracked.)
- **Multi-machine caveat is smaller than P8 first implied:** PostgreSQL runs **only on amd-tower** (per the 2026-05-17 check); other machines' recall reads the git-synced JSONL directly, so the JSONL edit alone suffices there — the helper is a no-op notice on a PG-less machine.
- **+15 tests** (`test_sync_memory_edit.py` 14 + 1 new in `test_sync_script.py`); **full suite 1065, 0 regressions.** This **delivers Tier-2 item 4 (activate the correction loop)** as a side effect.
- **Provenance:** `scripts/sync_memory_edit.py` + `tests/test_sync_memory_edit.py` (new); `scripts/sync-to-postgres.py` + `tests/test_sync_script.py` + `commands/forget.md` + `commands/update.md` (edited); plan §6a P8 marked fixed. Data submodule + `wiki/reflections/*` untouched (explicit-pathspec commit).

### 2026-06-06 (Sat, latest PA) — item 16 STAGE 1 SHIPPED: per-memory surfacing instrumentation live at all three paths (forward-only, no-API, +26 tests → suite 1050)

Shawn green-lit "build stage-1 instrumentation now" off the P9 (b) scoping. Built the forward-only earned-utility instrumentation per the proposal §6 Stage 1 — **instrumentation only, no consumption logic** (the stay-of-execution archival override is Stage 2, deferred until months of data accrue). No API, no change to what any path surfaces.

- **Two new modules.** `scripts/surfacing_log.py` — the per-ID logger: pure `format_surfacing_line` + `iter_surfacing_lines` (1-based rank, skips id-less entries) + best-effort `log_surfaced` (never raises) + an `--ids` CLI for `/recall`. Appends one tab-separated line per surfaced memory ID to `data/logs/surfaced.log` (`<ts>\tid=…\tpath=digest|fetch|recall\trank=…\tsession=-`; gitignored runtime log). `scripts/surfacing_stats.py` — the read-only aggregator: tolerant `parse_surfacing_line` + `aggregate_surfacing` (per-memory `active_retrievals` / `digest_exposures` / `last_active_at` / `last_any_at`; **weights active fetch/recall above passive digest** per proposal §3.2) + `summarise` + a human/`--json` CLI. `aggregate_surfacing` is importable so the memory-health report can fold in a surfacing section later (Stage 2 / cadence).
- **Wired at all three capture sites.** (1) **digest** — `surfacing_log.log_surfaced(result.entries, "digest")` added to `build_session_digest` (`session-start-retrieval.py`) as a pure additive best-effort side-write; **the digest text and `digest.log` are byte-untouched, so the §8 measurement is unaffected** (honours the standing gate). (2) **autonomous fetch** — `_log_invocation` (`fetch-memories.py`) now also logs `results` with `path=fetch` (active retrieval). (3) **`/recall`** — a sibling best-effort step in `recall.md` shells out to `surfacing_log.py --ids`; **the §8 count-logger `log-recall.py` was deliberately left untouched** (separation of concerns; no perturbation of the measurement instrumentation).
- **Two real bugs caught by the new tests + fixed.** (a) `_clean(None)` returned the string `"None"` (truthy), so a `None` session logged `session=None` not `-` — fixed to collapse `None`→`""` so the `or "-"` placeholder fires. (b) `log_surfaced`'s `log_path=DEFAULT_LOG_PATH` default bound at def-time, so the CLI's path was un-overridable (and the first failing test run wrote `a/b/c` to the **real** log) — changed to `log_path=None`, resolved inside at call time. **+26 tests** (`test_surfacing_log.py` 16, `test_surfacing_stats.py` 10, incl. a writer↔aggregator round-trip parity test); **full suite 1050, 0 regressions.**
- **Live-verified end-to-end.** Compile + a real hook-module load (critical — it runs every session start; imports cleanly). A genuine `fetch-memories.py --query "anchor verification" --limit 3` wrote 3 real `path=fetch` lines; `surfacing_stats.py` aggregated them (3 active, 0 digest, with the honest "earned *retrieval*, a proxy — not earned *use*" caveat printed). Truncated the test-pollution lines beforehand so the live log accrues clean (it now holds those 3 genuine fetch entries). The digest wire is unit-covered; the next real session-start with digest mode on will exercise it live.
- **Provenance:** `scripts/surfacing_log.py` + `scripts/surfacing_stats.py` + `tests/test_surfacing_log.py` + `tests/test_surfacing_stats.py` (new); `hooks/session-start-retrieval.py` + `scripts/fetch-memories.py` + `commands/recall.md` (edited, additive); plan §5 item 16 marked Stage-1 shipped. **`surfaced.log` is gitignored — not committed.** Data submodule + `wiki/reflections/*` untouched (explicit-pathspec commit). Still no dated obligation beyond the **2026-06-13 §8 review**; dark sentinels stay OFF, `~/.pa-digest-stage1` ON.

### 2026-06-05 (Fri, latest PA) — P9 (b) SCOPED: earned-utility value signal (item 16) — design pass, the logs record counts not IDs, and "never surfaced → archive" is the P3/P9 trap inverted

After-hours workstream-B increment (PA is out-of-hours; research sprint is primary — FOCUS.md checked first, untouched). Did the scoping/design pass for P9 (b) / item 16 (the earned-utility value signal), modelled on the item-13 and P3 proposals: **diagnose + design + push back where the evidence warrants, build nothing.** Proposal: `wiki/planning/earned-utility-value-signal-proposal.md`. No code, no live change, no API.

- **Central instrumentation finding (re-derived at source, NOT trusted from the carry-forward).** All three surfacing paths log **counts, not memory IDs**: the digest writes `len(result.entries)` to `digest.log` (`digest.py:685`, but `result.entries` — the surfaced dicts — is in hand at the hook's log site `session-start-retrieval.py:1222/1251`); `_log_invocation(args, results)` writes `len(results)` to `fetch-memories.log` (`fetch-memories.py:805/829`); `/recall` passes only `--results <N>` to `log-recall.py`. So the carry-forward's "build on the existing recall logging" is right about the **sites** but the logs **cannot today attribute surfacing to a specific memory** — item 16 is blocked on a per-ID capture that does not exist. Confirmed too: **no `surfaced_count`/`last_surfaced_at` field on records** (grep `memories.jsonl` = 0); `fetch-memories.log` is **6 lines total** (active paths have ~no history).
- **Three honest constraints (the substance).** (i) The signal is earned *retrieval* (was returned), a proxy — NOT earned *use* (informed the response); naming that ceiling is the same discipline that killed the P3 confidence premise. (ii) **Passive digest surfacing ≠ active retrieval** — the digest draws only from the **verified-true in-window pool** (`digest.py:577,604` → `rank_verified`), so its counts concentrate on the same few-hundred anchored-and-recent records and largely **re-derive the anchor signal**; active fetch/recall can return any memory and fire on intent, so any value score must weight active ≫ passive. (iii) **"Never surfaced → archive" is the P3/P9 trap inverted** — the digest structurally can't surface the unanchored 94 %, and the active logs are near-empty, so absence has **zero discriminating power** and would re-penalise exactly the unanchored-but-valuable population P9 protected.
- **Design: invert the polarity — presence *protects*, absence never *condemns*.** Earned (active) retrieval within K days buys a past-decay record a **stay-of-execution** from the item-13 / `monthly-archive.py` sweep — reversible, protective-only (cannot suppress the unanchored majority), reuses the audited sweep. Digest exposure is excluded from the spare test (it re-derives the anchor signal).
- **Architecture: append-only `surfaced.log` + offline aggregation, NOT a record field.** A `surfaced_count` on the record is rejected: P8 (INSERT-only sync) makes it invisible to the PG-reading digest/fetch paths until rebuild, and it would rewrite the hot corpus on every session start. The side-log + read-only aggregator mirrors `confab-flags.log` / `memory-health-report.py` and sidesteps P8 entirely.
- **Staged + open calls.** Stage 1 = instrument now (forward-only, no-API, no consumption — starts the accrual clock, like the confab-flags/recall-log instrumentation); Stage 2 = wire the stay-of-execution once months of data exist (don't pick K before the distribution is visible). Four open calls for Shawn (proposal §7): build Stage 1 now vs hold; new `surfaced.log` vs extend existing logs; add the `/recall` `--ids` pass-through; aggregator in `memory-health-report.py` vs standalone. **Nothing built.**
- **Provenance:** `wiki/planning/earned-utility-value-signal-proposal.md` (new); plan §5 item 16 + §6a P9 (b) updated to point at it. Data submodule + `wiki/reflections/*` untouched (explicit-pathspec commit). The only dated item remains the **2026-06-13 §8 review**; the two dark sentinels stay OFF, `~/.pa-digest-stage1` stays ON (digest window undisturbed).

### 2026-06-05 (Fri, latest PA) — P9 (a) shipped: recall displays now show honest `verified` state, not the misleading "Confidence: low"

After-hours incremental. Shawn chose option (a) (relabel/drop the misleading `confidence` display) and asked: relabel or drop? **Decided: neither relabel nor drop — replace it with the real underlying signal (`verified`), glossed** (a single relabel can't be honest across both eras, and dropping loses a real trust signal). Shipped to the two human/CC-facing recall surfaces:

- **`fetch-memories.py`:** added `verified` to both SELECT column lists; new pure helper `_verified_label()` maps `verified` → `verified (anchors resolved)` / `unverified (anchor did not resolve)` / `pending verification` / **`unanchored — no anchor to check (not a value signal)`**; the per-result line is now `Verification:` not `Confidence:`. Live-checked: recall output now reads honestly.
- **`recall.md`:** display token `(confidence)` → `(verified|pending|unanchored)` + a legend noting `unanchored` is a factual anchor-status, **NOT** a low-value flag.
- **+5 tests** (`_verified_label` + format_output reflects `verified` not `confidence`); **full suite 1024**.
- **Deliberately scoped:** the **stored** `confidence` field is untouched (schema drop is a bigger change, deferred). `memory_mcp.py` still returns raw `confidence` in its JSON envelope (structured API, not a display — renaming breaks the shape; left as a noted residual).
- **Still open (Shawn to decide whether to continue):** (b) a *true* value signal via earned utility (item 16); (c) anchor coverage (item 6, the binding constraint). Logged in plan P9.

### 2026-06-05 (Fri, latest PA) — P9 investigated: no consumer treats `confidence` as value (good); but the field is incoherent + mislabelled, and the digest favours the anchored 5%

Per Shawn's "P9 first, then see what we learn" + his open question (should a *value* metric be split from an *anchored*/verification one?). Read-only audit of every `confidence` consumer.

- **The worry is unfounded — no recall path treats `confidence=low` as low-value.** `digest.py` ranks by `verified` + tag-overlap + recency, *explicitly never* confidence (`:17–18`; fallback even prefers anchored, `:246–253`). `fetch-memories.py` queries `active_memories` (is_active+decay, no confidence clause), orders by recency / embedding similarity, `confidence` display-only. `/recall` filters `is_active=TRUE`+category/tag, display-only. The v2 designers already knew confidence ≠ value. **No acute bug.**
- **But the investigation surfaced three real residuals.** (a) **`confidence` is temporally incoherent:** of 18,023 active `high`, only 1,207 are `verified=true` → ~16,800 `high` are *pre-v2 Haiku self-ratings* (uninformative — 93 % high incl. confabulations); post-v2 `high` = verification echo. Same field, two meanings. (b) **Mislabelled in display:** `/recall`/`fetch-memories` print "Confidence: low" where a reader infers "low value" but it means "unanchored". (c) **The verification apparatus is anchor-gated:** the digest surfaces from the ~5 % `verified=true` pool (1,207, enough to fill the tiny digest) + anchored-preferred fallback — so it **deliberately favours the anchored 5 %**, and the unanchored 93 % rarely reach the digest (by design, via `verified`, not a confidence bug).
- **On Shawn's design question (separate value from anchored?):** the fields are *already* separate (`confidence`/`verified`/`anchors`); the mess is `confidence` became a redundant verification-echo shown as if it were value. Recommendation: **(1)** relabel/drop `confidence` in recall displays (cheap); **(2)** a *true* value signal can't come from LLM self-rating (v2 abandoned it for that reason) — the principled source is **earned utility (item 16: track what's actually surfaced/used)**, orthogonal to "anchored"; **(3)** the bigger lever is **anchor coverage** (~5–6 %) — the digest draws from a 5 % pool, so raising coverage beats any confidence reform.
- **No code changed** — investigation + design rec only; decision pending Shawn. Logged into plan P9. No-API.

### 2026-06-05 (Fri, latest PA) — P3 spot-check REFUTES the proposal: prompt lever weak + `confidence` is a verification artifact, not value. P3 needs rework; P9 logged

Built + ran the green-lit Haiku spot-check (`scripts/extraction-prompt-spotcheck.py`, **50 paired real windows, 100 calls, ~$1.17, 0 failures**; report `reports/extraction-spotcheck-20260605T075449Z.json`). It earned its cost by returning a clear **negative** result and surfacing a wrong premise — both caught *before any live change*.

- **Lever 1 (prompt) is empirically weak.** New-vs-old, paired on Haiku 4.5: per-run median **5→4**, total **201→178 = 11.4 %** reduction (target ~3×). The **zero-floor backfired** — empty-window rate went **14→11** (wrong way), 6 windows flipped old=0→new≥5. Per-window swings **−7..+9** ⇒ extraction **stochasticity dominates** a single-shot comparison.
- **Lever 2 (sideline `confidence=low`) is INVALID — the central premise was backwards.** The spot-check showed 0 `low` (Haiku's raw rating) while the corpus is 79 % low — because the hook **overrides** Haiku's confidence with `anchor_verify.bind_confidence(verified)` (`hooks/extraction-hook.py:1073`; `anchor_verify.py:493–494`: `verified∈{false,None}→low`). Only ~6 % of memories are anchored ⇒ **`low` ≈ "no verified anchor", NOT low value.** The low rate step-changed **0 % (Feb–Apr) → 51 % (May) → 81 % (June)**, tracking the v2 anchor rollout. Sidelining `low` would hide **63–79 %** of recent memories, most valuable-but-unanchored. (My earlier "Haiku self-flags the low-value tail" + the "low looks ephemeral" sample were confirmation bias; the "clean 19 %" used the stale all-time rate.)
- **Reframe:** session volume = **runs-per-session (median 10, max 152) × per-run (3–5)**. The prompt only touches the modest per-run; nothing here touches the runs-per-session multiplier — the real driver. High-leverage levers are elsewhere: fire extraction less often / batch more per run; cross-run dedup; or accept volume and rely on the archival cadence (P2, done) + byte-budgeted digest.
- **Outcome:** P3 as scoped is **refuted** — proposal status flipped to REFUTED with a top "Validation outcome" section (§§1–7 preserved as audit trail); plan §6a item 3 marked ❌. **Nothing shipped to the hook.** New item **P9**: `confidence` is *overloaded* (verification vs value) — any consumer (recall ranking, digest, P6 "verified breakdown") that reads `low` as low-value is really keying on anchor-presence and may suppress unanchored-but-valuable memories. Investigate next.
- **Spend:** $1.17 of the approved $5 (one batch). Harness committed (reusable for P7). Anti-confab note: this whole catch came from re-deriving `confidence` at source instead of trusting the proposal's premise.

### 2026-06-05 (Fri, latest PA) — Model-divergence resolved (Haiku, not Gemini); 2 memory corrections made effective; `/forget`+`/update`→PG bug found; P7+P8 logged

Shawn was "sure we switched memory extraction to Gemini 3.5 Flash"; the code + `extractor_model_id` stamps said Haiku 4.5. He asked for an agent transcript review. **Two parallel forensic agents converged:** the switch was **real but for a different pipeline** — the `cc-session-toolkit` *session auto-metadata* generator migrated to `gemini-3.5-flash` on 2026-05-22 (`~/Code/cc-session-toolkit/.../config.py:54`, verified directly), whose config constant is literally `EXTRACTOR_MODEL_ID`. The **memory-extraction hook** (`hooks/extraction-hook.py:51`) is, and has always been, **Haiku 4.5** — it never imports the toolkit. Name collision (`EXTRACTOR_MODEL_ID` vs the memory field `extractor_model_id`) crossed the wires. (Also: I was wrong to doubt "Gemini 3.5 Flash" as a model name — it's real and post-dates my Jan-2026 cutoff; the name was never the error, the pipeline attribution was.)

- **Confab caught *in* the corpus.** Two low-confidence memories auto-extracted this morning had baked in the wrong attribution. Corrected per Shawn's instruction: **`/update 2026-06-05-d2befeae59b8`** (decision — spot-check budget is for Haiku 4.5, not Gemini; prior content preserved in `revisions[]`, `verified`/`anchors` cleared) and **`/forget 2026-06-05-52451aba7fd4`** (prompt_effectiveness — false "production = Gemini" claim, `is_active=false`).
- **BUG found doing it — `/forget`+`/update` don't reach PG.** Setting `is_active=false`/new `content` in the JSONL does NOT propagate: `sync-to-postgres` is INSERT-only (`ON CONFLICT DO NOTHING`) and `is_active` isn't a synced field; `daily-sync` doesn't rebuild. So the PG-reading recall paths (digest + autonomous `fetch-memories`) ignore the edits until a manual `rebuild-postgres`. Verified live: `52451aba` was still `is_active=true` AND in `active_memories` after the JSONL forget. **Reconciled by hand** (surgical PG `UPDATE` — the `recover_anchors` pattern): now `52451aba` is 0 in `active_memories`, `d2befeae` shows corrected content. Logged as **plan P8** (fix: make the commands do the surgical PG update; multi-machine caveat noted). The commands' "PG sync is automatic" claim is false for existing rows.
- **New workstream item per Shawn: P7 — Haiku-vs-Gemini for memory *creation*.** Re-evaluate quality vs cost of the extraction *model* (Haiku 4.5 → Gemini?), mirroring the toolkit's auto-metadata switch. **Separate from P3** (which is the *prompt*): validate the prompt on the current model first (isolate prompt- from model-effect), then a bake-off. API-gated. Division Shawn is happy with for now: **session auto-metadata → Gemini; memory creation → Haiku.**
- **P3 spot-check: green-lit on Haiku 4.5**, $5 ceiling approved, prompt validated on the *current* model (Haiku) as agreed. Next: draft the new prompt, build the harness, present exact call-count/cost, fire on confirm. JSONL corrections ride the next daily-sync; this commit is docs (plan P7/P8 + this entry).

### 2026-06-05 (Fri, latest PA) — P3 numbers signed off: per-run reframe folded into the proposal (Levers 1 & 3 revised; still no live change)

Shawn asked for empirically-grounded guidance on the two numbers (prompt target, backstop cap). The data forced a **reframe that corrected my own earlier suggestion**: extraction runs **per ≤30-message window** off the cursor (not per session), and **per window Haiku is already restrained — median 3 memories/run (p90 6, max 12)**. The 33/session is `~10 runs × 3`; the multiplier is **runs-per-session (median 10, p90 44, max 152)**, not per-window greed. So a session-level "~10" in the prompt would be misapplied (extraction never sees the session), and my earlier "~30–40 backstop" was wrong — the per-session impact curve shows cap-30 touches **53 %** of sessions / cuts **59 %** of corpus (a primary cap, not a backstop).

- **Numbers, signed off:** **(1)** prompt = a per-window **zero-floor + value bar** ("most excerpts are worth `[]`; never invent to fill a quota"; relabel "per session" → "from this excerpt"; sharper `decision` def), goal = per-run median **3 → ~1** (≈3× fewer/session) — *not* a session count. **(3)** backstop = a **per-run cap ~10** (clean, lives where "2–8" already does, max observed/run is 12 so near-zero collateral), with an optional ~150 session catastrophe-guard; the per-session 30–40 is rejected.
- **Folded into the proposal** (`wiki/planning/extraction-selectivity-proposal.md` rev. 2026-06-05b): §1 gains the per-run/runs-per-session table; §2 root-cause #1 rewritten ("per session" misnomer + no zero-floor); Levers 1 & 3 rewritten; §4/§5/§6 updated; §6 #2 (numbers) marked RESOLVED.
- **The one number still under-determined by current data:** the post-prompt per-run rate — which is exactly what the API spot-check measures (re-run the new prompt on sample windows, read the new per-run distribution). Reinforces the lean toward paying for it.
- **Still no live change.** No hook edit, no view change, no API calls. **Still open (proposal §6):** API spot-check vs ship-and-observe (provisional: spot-check); all-three-together vs stage (provisional: together). Doc-only commit; data + `wiki/reflections/*` untouched.

### 2026-06-05 (Fri, latest PA) — P3 confidence-gate reworked to sideline-not-delete (proposal rev.; still no live change)

Shawn was inclined toward a write-time hard-drop of `confidence=low` but asked for the risks first. **Measured the false-positive risk and pushed back with evidence** (not a rubber-stamp): a write-time drop is a **one-way door** (unrecoverable, unlike archival), and the carve-outs meant to make it safe **barely fire** — only **8 %** of `low` memories carry a usable anchor, and the self-correction carve-out is **not implementable as written** (`superseded_by` populated **0** times; no self-correction marker field). Worse, the `low` bucket is **not clean junk**: of 4,238 `low` records, **62 % are permanent-category** (decision 1,099, gotcha 441, pattern 324, architecture 214…) and **2,400 carry `why`/`how_to_apply`** guidance fields. So "drop `low` minus carve-outs" ≈ "delete ~92 % of `low`, sight-unseen, on a noisy signal."

- **Resolution (Shawn agreed): sideline, not delete.** Write `low` as normal but **exclude `confidence='low'` from the `active_memories` view** (one-line predicate; kills recall/digest noise) + extend the archival criterion to cold-store `low` independently of category decay (reclaims JSONL/embedding). **Fully reversible** — the records stay in-corpus, then in cold store (`--include-archive`). ~100 % of the hot-path benefit of a delete, ~0 % of the irreversibility, and it reuses the P2 sweep machinery. A true delete, if ever wanted, is gated behind a 2–4 week log-only dry-run.
- **Proposal reworked** (`wiki/planning/extraction-selectivity-proposal.md` rev. 2026-06-05): Lever 2 rewritten; §1 overclaim corrected (the `low` bucket is *mixed*, not pure junk — the 12-sample looked junky but at scale it's 62 % permanent); §4/§5/§6 updated; the "P2 sweep auto-archives sidelined low" overstatement fixed (the current sweep keys on decay, so archiving `low` needs a small criterion addition). §6 records the still-open calls (target number, backstop cap, API spot-check vs observe, together vs stage) with Shawn's provisional leanings (spot-check; all-three-together).
- **Still no live change.** No hook edit, no view change, no API calls — proposal phase. **Next:** finalise the §6 calls → gated implementation (sideline + cap are no-API; prompt validation is API-gated). Doc-only commit; data + `wiki/reflections/*` untouched.

### 2026-06-04 (Thu, latest PA) — P3 INITIATED: extraction over-extracts ~4–7×; diagnosis + proposal written (no live change), awaiting sign-off

Out-of-hours workstream-B. P3 (item 14) touches the **live extraction hook** (writes memories across *all* sessions), so it gets the item-13 treatment — diagnose + propose, do NOT edit the hook autonomously. **Diagnostic (read-only, `source=extraction` over `data/memories/memories.jsonl`):** the hook produces a **median 33** memories/session (mean 56.9, p90 139, p95 197, **max 378**) against the extraction prompt's own stated **"2–8" target** (`hooks/extraction-hook.py:214–215`) — **86 % of sessions (339/393) over-target, 99 % of all memories from them.** It's a *volume* problem, not terse junk (content median 286 chars; 9 % < 200). `decision` is 27 % of recent 30 d output (~60/day — implausible for genuine durable choices); the sample bucket is full of micro-decisions/plans ("Use Quarto for slides", "Slot 1 rotation: Adela paper tomorrow"). **Key signal: Haiku already self-flags the low-value tail `confidence: low` (19 % corpus-wide; 8/12 sampled decisions), but that signal is discarded** (prompt calls confidence "advisory", nothing gates on it).

- **Deterministic levers simulated over the existing 22,347 extraction records (no API):** drop `confidence=low` → cuts 19 % (precise, sample-confirmed tail); cap top-12/session → cuts 81 % but 87 % of it is permanent-category (`decision`/`architecture`/`source_insight`) — a **blunt cap destroys durable signal from dense research days**, so it's rejected as the primary lever.
- **Proposal (`wiki/planning/extraction-selectivity-proposal.md`):** **(1)** strengthen the prompt (prescriptive ~10 cap + sharper value bar + sharper `decision` def) as the primary *at-source* lever — Haiku picks which survive, by meaning; **(2)** a no-API confidence-aware persistence gate (drop `low` minus an anchor/self-correction carve-out, protecting the v2 corrected-claim case); **(3)** a HIGH backstop cap (~30–40) for runaway sessions only.
- **API gate flagged (CLAUDE.md):** the *implementation* is no-API, but **validating the prompt change requires re-running Haiku** on a sample of transcripts → present model/batch/count/cost for approval, OR ship-and-observe forward via the P6 health report (no API, slower loop). The deterministic gate/cap need no API to validate.
- **Open calls for Shawn (proposal §6):** hard-drop vs downgrade-and-hide `low`; the target number (~10) + backstop cap (~30–40); pay for the API spot-check vs ship-and-observe; do both now vs stage (gate first, prompt later).
- **What was NOT done:** no edit to `hooks/extraction-hook.py`, no prompt change, no API calls. **Reproduce the diagnostic:** `venv/bin/python3` over the live JSONL — group `source=extraction` by `session_id` for the per-session distribution; by `category`/`confidence` for the mix; the policy simulation replays a confidence-gate + per-session-cap over the same records. Data submodule + `wiki/reflections/*` untouched. **Next:** Shawn's sign-off → gated implementation (deterministic gate is no-API; prompt validation is API-gated). Only dated item remains the 2026-06-13 §8 review.

### 2026-06-04 (Thu, latest PA) — P6 COMPLETE: cadence wired — `/memory-health` command + weekly-review integration

Closed the one open P6 decision. Shawn's pick: "command like this, but also add to the weekly-review ritual." Implemented both: (1) **`commands/memory-health.md`** — the `/memory-health` slash command (modelled on `/confab`; passes `--tier-c`/`--json` through, surfaces the exit-1 integrity verdict prominently), symlinked into `~/.claude/commands/` and **live in this session's skills list** (also auto-linked by `scripts/sync-symlinks.sh` on any future run). (2) **`/weekly-review` integration** (`commands/weekly-review.md`) — a step-2 "Memory-system health" run instruction (default fast report; Tier-C optional) + a new **"## Memory-System Health"** section in the internal-review template, placed after Git Activity, capturing corpus/integrity/anchors/confab-rate with week-over-week trend so bloat / dup-ids / a climbing confab rate surface in the ritual. A **periodic cron was deliberately NOT added** (Shawn chose command + weekly-review), and the **§8 digest window is left untouched** (no session-start one-liner during the measurement period — honours the standing gate until 2026-06-13). `test_command_markers` (26) + full suite **1019** still green; no Python changed, docs + command markdown only.

- **P6 is now complete** (engine + cadence). Remaining write-path queue: **P3 (item 14 extraction selectivity)** is the next substantive out-of-hours item; only dated item is the **2026-06-13 §8 review**.
- **Provenance:** `commands/memory-health.md` (new), `commands/weekly-review.md` (edited), plan §6a/§5-item-18 marked complete. Code engine shipped in the prior commit (`af3e833`). Data submodule + `wiki/reflections/*` untouched.

### 2026-06-04 (Thu, latest PA) — P6 INITIATED: memory-health report engine built (`scripts/memory-health-report.py`); cadence is the one open decision

Out-of-hours workstream-B, straight after P5 (which handed P6 its `audit_archive_parity()` building block). Built the **read-only** memory-health report engine — it mutates nothing (no locks, no PG writes, no cursor changes), so it is safe to run during concurrent extraction; it reads a point-in-time snapshot of the live JSONL, the cold partitions, `claude_memories.memories`, and `data/logs/*`. Six sections, each grounded in an existing source rather than a new metric: **[A]** corpus size & composition + dup-id tripwire, **[B]** growth (`created_at` 1d/7d/30d) & archival volume (`archive-runs.jsonl`), **[C]** anchor health (anchored %, verified breakdown, malformed via `wellformed_anchor`), **[D]** sync & archive integrity (live↔PG tail, the P5 archive-parity, dup-id + quarantine tripwires; PASS/FAIL with exit 1 on a real recall leak), **[E]** confab-flag rate (§8 measurement 3 — parses `confab-flags.log`, keeping the verifier rate Σflagged/Σchecked separate from the absolute-only manual catches), **[F]** **Tier C** write-time fresh-anchor-fail rate (opt-in `--tier-c`; `verify_memory` over `broad_repo_set`). `--json` for machine output. +14 tests, **full suite 1019**.

- **One real bug caught + fixed pre-commit:** the first Tier-C cut classified *every* file anchor on a failing record into the recoverable/absent split — but a record fails if *any* anchor fails, so resolving anchors were inflating "recoverable" (210/142/70, sum 422 > the 275 failing records). Refined to re-check each file anchor with `verify_file` and classify ONLY the genuinely-failing ones → **193 absent / 76 recoverable / 65 ambiguous** (sum 334). The headline fail rate is unchanged (it's record-level). A standing report must not carry a misleading metric — same lesson as P5's refuted framing.
- **Live snapshot (2026-06-04, point-in-time; reproduce with the script):** corpus **23,701** live / **0 dup-ids** / integrity **PASS**; archive parity **7,831 archived · 7,241 in-PG · 590 not-in-PG (benign) · 0 leaked**; live↔PG tail 3; anchored **6.4 %** (1,507; verified true 1,136 / false 321 / pending 50; 1 malformed anchor); growth 450/2,470/6,719 (1d/7d/30d); confab verifier 2/2 (n tiny, not yet meaningful) + 1 manual; **Tier-C 275/1,507 = 18.2 % fail** (absent 193 / recoverable 76 / ambiguous 65).
- **One open decision — cadence/delivery (Shawn's call).** The engine is identical across all delivery modes; only the wrapper differs: (1) manual on-demand, (2) a `/memory-health` slash command (like `/confab`/`/recall`), (3) a periodic cron (the P2 pattern) writing a timestamped report to `reports/`, (4) a one-line health summary folded into the session-start digest. Not wired pending Shawn's pick. Tier-C is ~1.5 min (per-anchor git resolution) so it stays opt-in / cron-only, not in any hot path.
- **Provenance:** code `scripts/memory-health-report.py` + `tests/test_memory_health_report.py` land this commit (public repo). All numbers produced by running the script this session. Data submodule + `wiki/reflections/*` left untouched (concurrent sessions). **Next out-of-hours:** wire the chosen cadence, then P3 (item 14 extraction selectivity); only dated item remains the 2026-06-13 §8 review.

### 2026-06-04 (Thu, latest PA) — P5 DIAGNOSED: dup-id hypothesis refuted; the "590" is a closed stranded-cursor artefact, zero impact; `--archive-parity` shipped

Out-of-hours workstream-B. Picked P5 first (read-only diagnostic, lowest-risk autonomous work, and it feeds P6). The plan's P5 framing — "PG behind the JSONL for *non-lag* reasons (dup-id / quarantine)" — is **wrong on both counts**, measured at source: (1) **no dup ids** — live JSONL (23,683) and the cold partition (7,831) each have **zero** duplicate ids and zero overlap (the 2026-04-14 `dedup-memories.py` + the item-13 sweep already cleared them); (2) **no quarantine** — `quarantine-postgres-drops.jsonl` was **never created**, the drop path has never fired. The **"590 archived ids never in PG" is real but inert**: a 40-record sample is **40/40 content-genuinely-absent from PG** (0 under another id) → **true never-synced records, not dup-collapse**; they cluster 540 in 2026-04 (from the dedup day on) + 50 in 2026-05, source extraction/manual, **0 reprocessing**. Root cause = the **pre-item-22 stranded-cursor leak** (the dedup shrank the JSONL → cursor stranded above EOF → incremental sync silently skipped appends until reset). The past-decay victims were swept to cold storage on 2026-06-02 before the post-sweep re-scan reconciled the *live* survivors (the documented 857).

- **Impact: zero.** The 590 are preserved verbatim in `data/memories/archive/memories-archive-2026-06.jsonl` (no data loss) and are past-decay AND archived → excluded from `active_memories` regardless; cold-readable via `fetch-memories.py --include-archive`.
- **Forward leak is closed:** item-22 shrink guard (2026-06-02) + the #55 advisory lock + quarantine-on-drop (never fired). `only_in_canonical` is 0–8 at any moment (normal unsynced tail; the 8 seen mid-session drained on the next 5-min cron tick).
- **Deliverable — `scripts/audit-postgres-sync.py --archive-parity`** (read-only): reconciles cold-store partitions vs PG, reports the benign archived-not-in-PG count, and **fails (exit 1) only on a recall leak** (an archived id still `is_active=TRUE`). Live run: `archived 7,831 / in-PG 7,241 / not-in-PG 590 (benign) / leaked 0`, exit 0. +6 tests (`tests/test_audit_postgres_sync.py`), **full suite 1005 pass**. This is the reproducible anchor for the finding and the building block P6/item 18 folds in (call `audit_archive_parity()` for the drift line).
- **Optional, NOT done (Shawn's call):** backfill the 590 into PG as `is_active=FALSE` — declined by default (zero value: past-decay + archived + already cold-readable; would add 590 inert rows).
- **Provenance:** all numbers re-derived at source this session (live JSONL, the partition, `claude_memories.memories`); reproduce with `venv/bin/python3 scripts/audit-postgres-sync.py --archive-parity`. Code lands this commit (public repo). Data submodule + `wiki/reflections/*` left untouched (concurrent sessions). **Next out-of-hours:** P3 (item 14 extraction selectivity) or P6 (item 18 health report); only dated item is the 2026-06-13 §8 review.

### 2026-06-04 (Thu, latest PA) — SESSION-CLOSE SUMMARY (/handoff): write-path plan advanced on five fronts

One long workstream-B session (2026-06-02 → 06-04) that moved the memory-system write-path plan substantially. Arc (each has its own detailed entry below): **item 9** — §8 apparatus verified (only measurement 1 is review-ready; (2)'s baseline is dead, (3) had no apparatus) + **/recall instrumented** to close the measurement-2 blind spot. **Confab-flag tracking** stood up — **Tier A** (the three verifier agents self-log to `data/logs/confab-flags.log`), **Tier B** (`/confab` manual capture), **Tier C** folded into item 18. **P4** — harness `MEMORY.md` neutralised (589→262 B/session) + the CLAUDE.md **SAFE redundancy set** (A1/B1/C1-SAFE) + D1/D2 correctness rewords applied; **E1 + C1-JUDGMENT deferred to Shawn** (logged below). **P2** — the recurring **archival cadence** (`scripts/monthly-archive.py`) built → twice adversarially reviewed → Shawn-watched first `--apply` (158 records, all gates green) → cron-readiness fix → **monthly cron installed + live on amd-tower**. Closed with a **session-end `/audit`** of all new code (6 MEDIUM fixes, no CRITICAL). Everything committed + pushed; corpus + recall provably intact throughout.

- **Next (out-of-hours):** P3 (item 14 extraction selectivity), P5 (dup-id diagnostic), P6 (item 18 health report — now houses Tier C + the cheap "live JSONL == active_memories after a sweep" drift check). **Shawn's manual calls:** E1 (tighten the project Concurrent-sessions section) + C1-JUDGMENT (collapse the network guardrails).
- **Only dated PA item: the 2026-06-13 §8 review** (9 days) — minutes on the day, nothing to build. Research (papers; Europe ~24 Jun) remains the real priority; PA is out-of-hours.

### 2026-06-04 (Thu, latest PA) — Session-end `/audit` of this session's new code (4 parallel agents): no CRITICAL, 6 MEDIUM fixed

Audited all of this session's new/un-audited code — `log-recall.py`, `log-confab-flag.py`, `monthly-archive.py` (+ their tests) and the verifier/command instrumentation Bash snippets — with four parallel anti-satisficing audit agents. **No CRITICAL bugs.** Six MEDIUM findings fixed (`f48f000`, suite 999): (1) TSV-corruption — only `detail` was whitespace-collapsed; now ALL log fields (`source`/`deliverable`/`kinds`/`selectors`) are, so no value can forge a column or split a record; (2) shell-injection — `confab.md` + the 3 verifier defs single-quoted the agent-substituted `--detail`/`--deliverable` (was double-quoted → a confabulated `$(…)`/backtick/quote could execute); (3) `log-confab-flag` clamps `confab <= flagged` + `main()` now takes argv (testable); (4) `log-recall` `results: int → object` (latent raise in the "pure" formatter); (5) `monthly-archive` exit-code-4 docstring (covers all 3 halt-before-push cases); (6) tests — de-vacuoused the coercion test, added field-sanitisation + `main()`-clamp coverage.

- **Deferred LOW (noted, not fixed — capture so they aren't lost):** `limit=10` hard-coded vs `fetch-memories.MAX_RESULTS`; the parity test asserts prefixes not true cross-module agreement; `_data_submodule_ahead()` conflates no-upstream with git-failure; latent partition-path normalisation (resolved-vs-unresolved — non-live under the current real-dir layout); the no-op `"nothing to archive"` string-match is coupled to `archive-memories.py`'s exact wording (worth a cross-ref comment); the direct `git -C data push` ignores its own returncode (re-verify catches it); `monthly-archive` returns rc 0 when a direct push is *rejected* (durable-but-unpushed — rc-based monitoring can't see it); privacy "names-only" is a calling-convention the loggers can't enforce; a few cheap untested branches (`sanity_verdict` at exact cap, `_archived_records_since`).
- **Provenance:** audit fixes `f48f000`; full suite 999 passed.

### 2026-06-04 (Thu, latest PA) — P2 first `--apply` executed (Shawn-watched): 158 records archived, all gates passed; cadence validated end-to-end

Ran the cadence wrapper's first live `--apply` with Shawn present (his only active CC sessions were inscriptions + map-reader — different repos; the shared corpus is guarded against their extraction-hook appends by the bulk-rewrite guard + JSONL flock). Dry-run previewed **158** records (up from 47 on 06-02 — a day's accretion + today's research-session memories); sanity OK (158 « the 10k / 25%-of-23,517 caps). Live run: flush → sanity → apply → **INVARIANCE OK** (all 158 independently verified strictly past-decay at the pinned `as_of`) → **PG-drift OK** (archived ids `is_active=FALSE`) → re-sync → push. **158 archived to `memories-archive-2026-06.jsonl`** (partition 7,673 → 7,831; live corpus 23,678 → 23,520). **Recall invariant held:** `active_memories` went 23,517 → 23,520 — *up* +3 (benign concurrent appends during the ~75 s run), never down; and the live JSONL now equals `active_memories` exactly (23,520 = 23,520), i.e. the hot file is reconciled to the recall set.

- **The push-verification gate worked as designed (real catch, not theory).** daily-sync left the archival commit **unpushed** (data submodule 1 ahead of upstream — exactly the HIGH-2 scenario the 2nd review predicted: daily-sync skips the data push on a clean tree). The wrapper **warned loudly + returned the warning** instead of falsely claiming success; resolved with a manual `git -C data push` (`c271927..4d44ef8`). Superproject pointer bumped to `4d44ef8` + synced.
- **CRON-READINESS FINDING (one small fix before cron-enabling):** the wrapper detects-and-warns the unpushed archival but does not *itself* push it — it relies on the next daily-sync. **Not a data-loss risk** (the commit is local + durable; next sync pushes), but for a fully self-contained unattended cron it should `git -C data push` when still ahead after the daily-sync step. ~4-line change to `monthly-archive.py` step 9. **✅ FIX APPLIED same session:** step 9 now `git -C data push`es directly when daily-sync leaves the archival commit ahead, then re-verifies (warns only if a direct push *also* fails to land — durable-but-unpushed, never silent). 22 tests + suite 996 still green. **P2 is now cron-ready** — add the monthly cron line from `wiki/planning/archival-cadence-2026-06-02.md`. **✅ CLOSURE 2026-06-04: cron INSTALLED + live** in the amd-tower user crontab (`0 4 1 * *`, `--apply`, self-pushing, `OLLAMA_BASE_URL` set for the embed step; line verified intact via `crontab -l | grep -c`). **P2 fully complete — do not re-install.**
- **Provenance:** archival `data 4d44ef8`; run log `data/logs/monthly-archive.log` (2026-06-04T04:19–04:21). No-API. Scratchpad pattern on the invariance-gate design captured (`data baaf995`).

### 2026-06-03 (Wed, latest G) — Workstream G: `/write-like-me` drafting workflow codified (neutral-draft → voice-align)

Roadmap #2 design decision (no code yet). Agreed with Shawn the drafting workflow: **separate content from voice.** (1) Outline jointly → (2) CC drafts in plain/neutral voice, content-first → (3) Shawn content-edits with his **author hat** (auditing naked prose is easier — on-voice prose masks flaws; the edit also naturally drifts the draft toward his voice, lightening stage 4) → (4) `/write-like-me` **voice-aligns conservatively** (citation-stripped guide + Appendix F; preserve what Shawn already got right; meaning-preserving + show-changes; **no citations**, §3; phase5 + per-feature deltas as the diagnostic) → (5) Shawn **editor-hat** final pass catches any meaning-drift. Two verification checkpoints, two hats (content on plain prose; voice + drift on the voiced version). Architecture: `/write-like-me` = the stage-4 **skill** driving a fresh-context generation **agent** for isolation.

- **Gate before building:** the efficacy experiment validated the *fused* path (content+voice in one shot); the neutral→voice-align path is **untested**. Try the workflow manually first, validate stage 4 (blind-pair vs a fused in-voice draft + a meaning-drift check), then build the skill.
- Spec: `wiki/planning/write-like-me-workflow.md`. Roadmap #2 updated with the codified workflow.

### 2026-06-03 (Wed, latest PA) — CLAUDE.md SAFE redundancy set + D1/D2 correctness rewords applied (P4 cont.)

Applied the SAFE-rated trims + the two correctness rewords from the CLAUDE.md audit proposal (`data/notes/claude-md-redundancy-audit-2026-06-02.md`), per Shawn's sign-off. Edits went to the **source** files (the global `~/.claude/CLAUDE.md` is auto-generated — never edited directly) and `scripts/compose-global-claude-md.sh` was re-run + verified:
- **A1** (`CLAUDE.md` project Context): dropped the duplicated "archaeologist and ancient historian" bio (it lives in the global *About me*); kept the project-specific redundancy/finite-window framing.
- **B1** (`global-claude-md/shared.md`): deleted the duplicate *File Reorganisation Safeguards* section; folded its one unique line ("create `archive/` if it doesn't exist") into *File Organisation*.
- **C1-SAFE** (`data/global-claude-md/local.md`): dropped the redundant "Read that file when…" pointer in *Network Resources* (the Reference-Docs table row already carries it). **The four safety guardrails were KEPT inline** (that was C1-JUDGMENT — deliberately not touched; "Never reboot rpi-server/sapphire" etc. stay in every session's face).
- **D1** (`shared.md`): reworded the FAIMS3 git example — it claimed collaborative repos "gate … in their own project-level `CLAUDE.md` (e.g. FAIMS3)", but FAIMS3 has no CLAUDE.md. Now "(e.g. the FAIMS3 monorepo is collaborative — branch + PR there)" — the *behaviour* (branch+PR in FAIMS3) is unchanged; only the false mechanism claim is gone.
- **D2** (`shared.md` + `global-claude-md/scratchpad-reference.md`): "Opus 4.7" → "Opus-class models" (running model is now 4.8; the anti-confab rule is unchanged, just unpegged from a version).
- **Verified:** composed `~/.claude/CLAUDE.md` 12,545 → 12,157 B; 0 "Opus 4.7", 0 "File Reorganisation Safeguards", 0 "Read that file when", guardrails intact.

#### ⏳ DEFERRED FOR SHAWN — E1: tighten the project CLAUDE.md "Concurrent sessions" section (manual, your call)

**What:** In `~/personal-assistant/CLAUDE.md`, the section headed **"Concurrent sessions — label your workstream"** (~1,900 bytes) is the single biggest *verbosity* trim available (~700–800 B). It currently repeats the "don't sweep another session's files / shared index" rationale ~four times and narrates a past incident at length (a style-guide commit once absorbed another session's Vector-2c work).

**Why it's left to you, not auto-cut:** that section encodes a **hard-won, costly lesson — an actual mis-commit that really happened**. The vividness is *why* a fresh session takes the warning seriously; mechanically halving it risks gutting the thing that makes it land. So this is a judgment edit only you should make.

**Suggested edit (when you get to it):** keep the four rules — (1) label your workstream in commit subjects + continuity headers, (2) `git add <path>` isn't enough, use `git commit -- <path>` because a concurrent session may have pre-staged, (3) genuinely-simultaneous infra work → worktree not branch, (4) this is repo-specific — plus the worktree command block. Drop the *repeated* rationale and shorten the Vector-2c anecdote to a parenthetical (e.g. "(this has bitten us)"). Target ~1,000 B. Full detail: audit proposal §E1. **Also still on the table (your call, NOT done): C1-JUDGMENT** — collapsing the four network guardrails to the table pointer (~670 B), deliberately left because it trades guardrail salience for payload.

**Provenance:** parent commit (this entry's batch); proposal `data/notes/claude-md-redundancy-audit-2026-06-02.md`.

### 2026-06-02 (Tue, latest PA, OVERNIGHT autonomous) — P4 (dead payload) + P2 (archival cadence) built; both gated for Shawn's review

Shawn authorised an autonomous overnight run on P4 + P2, going to bed. Scoped to **safe/reversible work only**; the one irreversible action (a live `archive-memories.py --apply`) was deliberately **left for a Shawn-watched window** per the item-13 protocol (overnight is not genuinely quiet — the sync cron + extraction hooks append continuously).

**P4 — neutralise dead fixed-payload weight (item 3):**
- **MEMORY.md neutralised** (the harness auto-memory index, injected every session): **589 → 262 B/session**, reversible. Backup at `~/.claude/projects/-home-shawn-personal-assistant/memory/MEMORY.md.pre-p4-2026-06-02.bak`; the 3 feedback detail files left in place; the concepts are also in the JSONL corpus. No settings toggle exists to disable the auto-memory at the harness level (checked), and the system-prompt `# Memory` block can't be removed by us — but the user CLAUDE.md override already neutralises its effect.
- **CLAUDE.md redundancy audit** → proposal at `data/notes/claude-md-redundancy-audit-2026-06-02.md` (committed `data 0da8376`, **NOT pushed** — rides next sync). Key finding: the global `~/.claude/CLAUDE.md` is **auto-generated** by `scripts/compose-global-claude-md.sh` from `global-claude-md/shared.md` + `data/global-claude-md/local.md`, so trims go to the **sources**. **~610 B SAFE** dedup (bio restated; archive-rule stated twice; a duplicated network pointer) + **~1,505 B JUDGMENT** trims; filesystem-verified two stale claims (FAIMS3 has no CLAUDE.md; an "Opus 4.7" peg). **Nothing applied** — even the SAFE batch awaits Shawn (behaviour-governing files).

**P2 — recurring archival cadence (completes item 13):**
- `scripts/monthly-archive.py` (parent `69e69f6`) + cadence/first-run/cron doc `wiki/planning/archival-cadence-2026-06-02.md`. Wraps the proven item-13 sweep as one **safe-by-default** command (dry-run unless `--apply`): preflight (pins to MAIN checkout) → flush → **sanity gate** (refuse absurd/oversized) → apply → **invariance gate** → **PG-drift gate** → verified push. Every post-apply halt leaves a local, revertable data-submodule commit.
- **The invariance gate is the redesigned safety heart:** it independently re-derives, for every record the apply actually archived (partition delta), whether it is strictly past-decay at a single **pinned `as_of`** — a different code path from the tool, **immune to the live-`NOW()` drift** that the first review proved would false-alarm a correct sweep on the original aggregate-count design.
- **Two adversarial agent reviews (audit trail):** pass 1 found a CRITICAL (ran-from-worktree path split-brain) + 3 HIGH (NOW()-drift invariance false-alarm, unpushed-archival, PG-drift false-OK) → all fixed (incl. the invariance redesign). Pass 2 confirmed **no CRITICAL/HIGH remain**, residuals all fail in the safe direction (halt-before-push); 5 low-cost refinements applied (main-tree path assertion, tightened `as_of`, always-log end marker, no-op vs false-halt, `Z`-timestamp parse). **22 unit tests; full suite 996.**
- **Validated end-to-end from the main tree (dry-run):** preflight passes, queries `active_memories` (23,021 active), would archive **47** records, sanity OK, zero changes. (47 ≈ the 46 found earlier + accretion — concrete proof the cadence is needed: past-decay records re-surface within hours of a sweep via multi-machine sync.)

**Left for Shawn (morning):** (1) review the CLAUDE.md proposal; apply the SAFE ~610 B in the source files if happy (then re-run `compose-global-claude-md.sh`). (2) Watch one `monthly-archive.py --apply` (the first live run), then add the documented monthly cron line. Nothing else outstanding. **Standing gates honoured:** §8 window + dark sentinels untouched; no API calls; explicit-pathspec commits; other sessions' files (corpus churn, `wiki/reflections/*`) left alone.

### 2026-06-02 (Tue, latest PA) — /confab manual confabulation capture shipped (Tier B)

Shawn opted in to the manual complement — the whole memory-infra push began when he noticed a run of confabulations, and `/confab` lets him log them as they're caught. Shipped (`aa62095`): extended `scripts/log-confab-flag.py` with a `--detail` note field (whitespace-collapsed + 200-char bound so free text can't corrupt the TSV — line is now 8 fields) and added `commands/confab.md`. `/confab [what was confabulated]` classifies the welded specific's kind (path / identifier / count / quote / citation / commit / date / other), composes a short claimed-vs-actual `detail`, and logs `source=user-correction checked=0 flagged=1 confab=1` to the shared `data/logs/confab-flags.log`. **`checked=0` is deliberate:** a manual catch has no denominator (you only ever log the catches), so manual rows are absolute-count-only and MUST be excluded from the verifier rate (Σflagged / Σchecked) — documented in both the helper docstring and the command. +3 tests; **full suite 974**. Built in worktree, FF-merged, pushed; other session's files untouched.

- **Tier B vs Tier A:** Tier A (verifier agents) catches citation/repo/dataset-number confab automatically; Tier B (`/confab`) catches the prose path/identifier/count welding Vector 2 most targets, manually. One log file, two source classes; item 18 reads both (rate from verifier rows, absolute count from manual rows). Default `source=user-correction`; `self-catch` reserved for genuine proactive catches.
- **Live:** `~/.claude/commands/confab.md` symlink created (mirrors capture.md / recall.md); `/confab` now appears in the skills list. Log file still uncreated — the first `/confab` or verifier run makes it.
- **Still deferred:** Tier C (write-time fresh-anchor-fail rate — fully automatic, broader, needs a noise-filter trace of the extraction hook). Provenance: parent `aa62095`.

### 2026-06-02 (Tue, latest PA) — Tier-A automated confab-flag tracking shipped (§8 measurement (3) apparatus, per Shawn's ask)

Item 9 surfaced that §8 measurement (3) — the confab-flag rate — had **no apparatus at all**. Per Shawn's same-session ask ("start tracking"), built **Tier A** (`353a45a`). `scripts/log-confab-flag.py` parses the per-claim `corrections.jsonl` that the three adversarial verifier agents already emit, tallying `checked` / `flagged` (`status=fail`) / `confab` (`failure_type=confabulation` — a first-class class shared verbatim across all three verifier contracts) / `kinds` to `data/logs/confab-flags.log` (best-effort, never raises; also accepts explicit counts). Wired all three verifier agent defs (`agents/{lit-scout,prior-art-scout,data-profile}-verifier.md` — the live source, symlinked into `~/.claude/agents` + `published/agents`) to self-log their tally as a final Bash side-effect: the single reliable point, fires on every invocation path. +10 tests; **full suite 971 pass**. Built in worktree `../pa-confab`, FF-merged, pushed; other session's `wiki/reflections/*` + `data` untouched.

- **Honest limits (recorded so the review doesn't over-read it):** (1) **forward-only** — no pre-ship data, so it does NOT rescue measurement (3) for 2026-06-13; standing capability. (2) **selection-biased** — counts only deliverables that pass a verifier (lit / prior-art / data-profile — mostly research), not Claude's overall rate. (3) **narrow kind** — catches citation/repo/dataset-number confabulation, NOT the prose path/identifier welding Vector 2 most targets (deferred Tier B manual-capture / Tier C write-time anchor-fail). (4) **instruction-based** — agents self-log; a forgotten step silently drops a line (best-effort by nature).
- **Folds into item 18** (memory-health standing report): confab rate = Σflagged/Σchecked + absolute flagged/fortnight + the confab subset.
- **Provenance.** Parent `353a45a`. `data/logs/confab-flags.log` does not exist yet — created on the first verifier run. Verified live: the three `~/.claude/agents/*-verifier.md` symlinks resolve to the instrumented files; helper importable on the canonical path.

### 2026-06-02 (Tue, latest PA) — Item 9 (P1): §8 apparatus verdict + /recall instrumented (measurement (2) gap closed)

Verified the four §8 measurements against both the code that *should* produce each and the data that *does* exist — read-only, sentinels untouched (`~/.pa-digest-stage1` present; the two dark sentinels absent → window unconfounded). **Verdict: only measurement (1) is review-ready.** (1) **Digest bytes — healthy.** The `digest.log` write lives only inside the `if digest_mode_enabled():` branch (`hooks/session-start-retrieval.py:1330→1341`, which returns before the legacy path) → every line is a genuine post-enablement firing, zero legacy confound. Ran the review's own computation over the 26 firings (2026-05-30→06-02): **median 1491 B, p95 1499 B, 0 over the 1500 budget, 0 fallback**. Schema changed mid-window (Vector 2c added `focus=`/`scoped=`; 11 pre-2c + 15 post-2c lines) → a key=value parser is mandatory, positional breaks. *Caveat for the review:* the 1500-byte budget is a HARD cap (max observed = exactly 1500), so median≤1500/p95≤2000 are satisfied by construction — (1) actually measures *how hard the cap binds* (median≈cap → trims almost every firing), not a pass/fail. (2) **Invocation rates — broken three ways:** (2a) **no pre-ship baseline, unrecoverable** — instrumentation shipped `809a89f` dated 2026-05-30, the same day as enablement; design §2 baseline captured *bytes only*, never rates; (2b) **/recall was not instrumented at all** — `recall.md` reads `memories.jsonl` directly and never calls `fetch-memories.py`/`_log_invocation`, yet `tier-2-retrieval.md:63` *claimed* it "runs the same retrieval"; this risks a false negative on design risk R1 ("depth is never fetched") since the human path is /recall, not the autonomous one; (2c) sparse (5 events/3.5 d). (3) **Verifier confab-flag rate — NO apparatus exists** (no verifier log, no flag tally anywhere). (4) **Subjective** — qualitative by design; no capture point.

- **Fix shipped (Shawn chose "instrument /recall now"):** `scripts/log-recall.py` (best-effort, never raises) appends a `source=recall`-tagged line to the same `fetch-memories.log`; autonomous lines stay source-less by convention (parser: absent ⇒ fetch). Wired `commands/recall.md` to log every invocation as a mandatory final step (selector *names* only — never the search text, mirroring fetch-memories' privacy choice). Corrected the false "runs the same retrieval" claim in `tier-2-retrieval.md` + documented the `source=` convention. +8 tests (format, best-effort-never-raises, format-parity); **full suite 961 pass, 0 regressions**. Built in worktree `../pa-item9`, FF-merged to main, pushed; other session's `wiki/reflections/*` + `data` left untouched.
- **Provenance.** Parent `4db5a9d`. All cited numbers (digest.log median/p95/n, the 5 fetch-memories lines, the 809a89f date, the recall.md direct-read) re-derived at source this session — not from the plan/continuity pointers. Sentinels + §8 window NOT perturbed; the /recall log is additive side-channel only (doesn't change digest output).
- **Still open after this:** (2a) baseline is gone — the review must drop the pre/post comparison for (2) and read it as *absolute post-ship counts + R1 binary* (now spanning both paths). (3) **automated confab-flag tracking is under design per Shawn's same-session ask** — see the proposal below / next entry; note it is forward-only (no pre-ship data) so it does NOT rescue (3) for 2026-06-13 either. P1/item 9's *verification* objective is met; the residual is review-expectation reframing + the optional (3) build.

### 2026-06-02 (Tue, latest PA) — Item 22 fixed + a session-end /audit of ALL session code (2 MEDIUM fixes); item-13 write-path thread closed; next steps prioritised

Closed out the post-execution hardening. **Item 22** (`sync-to-postgres.py` shrink guard, `b94d3b5`): `_sync_locked` now detects a below-cursor shrink and resets to 0 for a full re-scan, so future archival sweeps self-heal the line cursor (no more manual reset). Then ran a **session-end `/audit` over every file created/modified this session** (4 parallel subagents, 7 files). The audit confirmed the bulk sound — `schema.sql` clean, `archive-memories.py` no regressions, and the new tests proven non-vacuous by mutation testing — and caught **two real MEDIUM bugs, both fixed** (`2e709ec`): (1) `fetch-memories.py --include-archive` put `None` into the dedup set when an active result lacked an id, which would drop *every* id-less archived record as a false dup (latent — 0 id-less today — but `archive-memories.py` keeps id-less records); extracted a tested `_merge_archive()` that excludes `None`. (2) the item-22 first cut called `detect_jsonl_shrink`, which counts lines by file-handle iteration — diverging from the `splitlines()` count the cursor is saved with (on embedded Unicode separators surviving an `ensure_ascii=False` rewrite), risking a spurious shrink WARN every cycle; switched to the inline `cursor_line > total_lines` check (same count as the saved cursor + the slice, and drops a redundant file read). Full suite **953 pass**; live runs confirm clean no-op at EOF and working `--include-archive`.

- **The item-13 write-path thread is now complete end-to-end:** design → sign-off → tool (built + audited) → executed (7,673 archived, recall provably unchanged) → both follow-ups → item 22 (the bug execution surfaced) → audit of all the code it produced. Nothing outstanding *on item 13*.
- **Session commits (parent):** `9a5345a` (tool), `a5ac41b` (gotcha/pattern→permanent + `--include-archive`), `53421c7` (docs: executed), `b94d3b5` (item 22), `2e709ec` (audit fixes); design-phase `bfaf0ab`/`41c55e9`/`41ca87a`; data submodule archival `034f1cc`+`761caf5`.
- **NEXT STEPS (prioritised) — memory-system write-path, post item-13:**
  1. **P1 (dated): item 9 — verify the §8 measurement apparatus before 2026-06-13** (11 days out). The only dated item; the 2026-06-13 review gates enabling the Vector 2b/2c sentinels. Cheap, de-risks. No-API.
  2. **P2: recurring archival cadence (new — completes item 13).** The sweep was one-shot; without a periodic run the JSONL re-bloats (~260/day). Stand up a monthly `archive-memories.py --apply` after a `daily-sync.sh` flush (the item-22 fix makes the cursor self-heal). No-API.
  3. **P3: item 14 — extraction selectivity tuning** (fewer, higher-value memories at source — the upstream lever that prevents accretion before any cleanup). No-API.
  4. **P4: item 3 — neutralise dead fixed-payload weight** (harness auto-memory `MEMORY.md` + CLAUDE.md redundancy audit; loaded every session). No-API.
  5. **P5: write-side dup-id hygiene (new — surfaced this session).** The sweep exposed 590 archived ids never in PG + 857 unsynced live records — PG was materially behind the JSONL for *non-lag* reasons (dup-id / quarantine). Diagnose the dup-id source. No-API diagnostic first.
  6. **P6: item 18 — memory-health standing report** (counts / anchor-rate / age / growth / archival-volume); folds in P2's recall-invariance check + the P5 drift diagnostic. No-API.
  - **Lower:** items 4 (correction loop), 7 (actionable what-changed counter), 10 (identifier-welding), 8 (drift-sweep job), 17, 19.
  - **API-GATED (deferred, need cost approval):** item 6 (retroactive anchor-gen to verify the back-corpus — the big one), items 5/15 (semantic dedup).

### 2026-06-02 (Tue, latest PA) — Item 13 EXECUTED: 7,673 records archived (~25% of corpus), recall provably unchanged; both follow-ups done

Shawn opened a Shawn-watched quiet window (1.5h, no concurrent sessions) and authorised the gated `--apply` + both follow-ups. Ran the full retention sweep from the main working tree. **Flushed first via `daily-sync.sh`** (the corpus had dirty extraction appends on the protected files — exactly the dirty-corpus state the bulk guard blocks on). Then staged: `--apply --category progress` (**4,094**) → verify → push data → `--apply` rest (**3,579**) → verify → push data. **7,673 records (~25% of the 30,588-line corpus) archived** to `data/memories/archive/memories-archive-2026-06.jsonl` (data `034f1cc`, `761caf5`; live JSONL 30,588 → 22,915, 0 unparseable). gotcha/pattern untouched in the live file (PERMANENT_OVERRIDES). **Recall invariance PROVEN empirically:** `active_memories` total AND every per-category count were IDENTICAL before and after each apply (21,999) — archiving a quarter of the corpus changed recall by exactly zero, because the archived records were all already past-decay and excluded by the `active_memories` view. PG: 7,083 archived ids set `is_active=FALSE`; **0 resurrected, 0 visible in active_memories** (verified by sampling the partition ids against PG).

- **Two real issues surfaced and handled.** (1) The apply's **rowcount-drift warning fired** (progress: PG marked 3,832 of 4,094; rest: 3,251 of 3,579) — a *pre-existing* PG drift: 590 archived ids were never in PG (dup-id/quarantine), so nothing to mark; harmless, the records are archived out of the JSONL regardless. (2) **`sync-to-postgres.py` does NOT wire the `detect_jsonl_shrink` guard that exists in `_sync_cursor.py`** — after the shrink, `_sync_locked` saw `cursor (30588) >= total_lines (22915)`, logged "No new memories", and **stranded the cursor above EOF** (future appends would be silently skipped until regrowth). **Worked around** by resetting `postgres_sync_line` 30588→0 + full re-scan (`ON CONFLICT DO NOTHING`); cursor landed correctly at 22,915 and the re-scan also reconciled **857 previously-unsynced live records** into PG (`active_memories` 21,999→22,856 — a completeness *gain*, not archival damage). **Logged as plan item 22 — fix before the next sweep.**
- **Follow-ups done.** (2a/D3) `category_config` gotcha/pattern `decay_days 180→NULL` — live `UPDATE` + `schema.sql` seed (no schema_version bump: config-data, not shape/view/meta). Un-hid the past-180d guidance records (active gotcha 3050→3084, pattern 1460→1482 = full live counts). (2b/D6) `fetch-memories.py --include-archive` — `load_archive_memories()` + `search_archive()` glob the cold partitions and append deduped matches after the active results; off by default. End-to-end verified: an archived id returns 0 results normally, 1 with the flag. 4 new tests. **Full suite 946 pass.** Code parent `a5ac41b`.
- **Provenance.** Tool `9a5345a` (built/audited prior entry); follow-ups `a5ac41b`; data archival `034f1cc`+`761caf5` (pushed). Baseline/verification captured live at each step (not from memory). Standing caveat held — NOT pruned on `verified=false`. The 2026-06-13 §8 review still gates the 2b/2c sentinels; untouched. **Next no-API:** plan item 22 (sync-to-postgres shrink guard) before any future archival; item 9 (§8 apparatus) de-risks 2026-06-13.

### 2026-06-02 (Tue, latest PA) — Item 13 EXECUTION TOOL built + /audit-ed: `scripts/archive-memories.py` (dry-run validated; `--apply` still gated)

Shawn approved building the execution tool (worktree + dry-run agreed). Built `scripts/archive-memories.py` (`9a5345a`) on the `recover_anchors.py` guarded-mutation template, in an isolated worktree (`workstream-b-item13`, branched off `ec9764d`, merged ff to main, worktree removed — workstream-G's worktree untouched). Implements the 2026-06-01 signed-off policy: ephemeral categories archived past their `category_config` window to a monthly cold partition (`data/memories/archive/memories-archive-YYYY-MM.jsonl`); `gotcha`+`pattern` forced permanent via `PERMANENT_OVERRIDES`; `--category` for the staged rollout. Dry-run default; `--apply` gated by `_bulk_rewrite_guard` + `lock_jsonl_for_rewrite` (re-partitions inside the lock), `Rewrite-Class: bulk` trailer, verbatim passthrough, surgical PG `is_active=FALSE`. **30 unit tests; 55 pass with the sibling template suites.**

- **/audit (two parallel subagents) caught two real bugs, both fixed before merge:** (1) **boundary** — the planner used truncated `.days > decay_days`, which left ~171 already-decayed records behind; changed to fractional `(now−ref) > timedelta(days=dd)`, algebraically identical to the `active_memories` view / `apply-decay` interval predicate (`created_at < NOW()−dd`). (2) **cold-store duplication** — append-mode partition write would duplicate records on a crash-then-retry; added idempotent dedup-by-id (`_partition_ids`) + `fsync` on partition and `corpus.tmp` before the rename. Plus PG hardening: loud warning if PG is unreachable *after* the corpus mutation, a `rowcount != len(ids)` drift warning, an id-less-record warning, and a fixed dispatch so no PG branch is silently skipped. The guard/lock/commit/schema-version machinery audited at full parity with `recover_anchors.py`.
- **Dry-run (2026-06-02, `--category progress`):** **4,061** progress records past 30 d (3.09 MB) from the canonical JSONL (5,213 total). Surfaced a real **sync-lag observation: PG is ~272 progress records behind the JSONL** (PG 4,941 vs JSONL 5,213) — which is exactly why the gate flushes via `daily-sync.sh` first (daily-sync runs the JSONL→PG sync, closing the drift); the new rowcount-drift warning is the backstop if skipped.
- **Remaining (gated `--apply`, Shawn-watched, quiet window):** flush via `daily-sync.sh`, run `progress` alone first, verify recall + digest unchanged, then the rest. Small follow-ups: flip `category_config.decay_days` `gotcha`/`pattern` `180→NULL`; add `fetch-memories.py --include-archive` (D6). Standing caveat held — NOT pruning on `verified=false`. The 2026-06-13 §8 review still gates the 2b/2c sentinels; untouched.

### 2026-06-01 (Mon, latest PA) — Item 13 DESIGN proposal written (no mutation, no API): per-bucket retention/archival policy for sign-off

Wrote the item-13 design deliverable — `wiki/planning/memory-retention-policy-proposal.md` (`bfaf0ab`) — a **proposal for per-bucket sign-off, not an execution**. Re-derived all counts at source (`data/memories/memories.jsonl`, 30,277 records on 2026-06-01). **The reframe that reshapes the design: decay already exists, archival does not.** `category_config.decay_days` + the `active_memories` view already exclude past-decay records from recall *at read time*; `apply-decay.py` mirrors that as `is_active=FALSE` in PostgreSQL only. So past-decay records are **already invisible to recall** yet still sit in the live JSONL (extraction-append target, daily-sync input, git object, decay-blind recall fallback) as dead weight. Archival = physically evicting them from the hot file. This splits item 13 into **two separable levers**: **Lever A (behaviour-preserving)** — archive the **7,370 records (5.62 MB, ~24 %)** already past their *existing* decay window; recall is unchanged via PostgreSQL (the view already hides them), the only delta is the degraded JSONL fallback becomes *consistent* with the primary path. **Lever B (policy)** — per-bucket tier/window redesign, which *does* change recall and is where sign-off matters.

- **Pushback on the brief (the real judgement call):** the brief named `gotcha` (with `progress`) as an aggressive-decay candidate. **I recommend against** decaying `gotcha` *or* `pattern` aggressively — both are in the extraction hook's `GUIDANCE_CATEGORIES` (the steer-future-work set); a `gotcha` outlives a 30-day window. Empirically they aren't the bloat either (only 27 `gotcha` / 15 `pattern` past even 180 d). Recommend **permanent or 365 d**. `progress` IS the right aggressive target (3,902 past 30 d, no guidance role).
- **Corrected a stale brief pointer:** `scripts/bulk-archive.py` archives **Claude Code sessions** (→ `~/cc-archives/`), **not memories** — no memory-archival tool exists. The execution tool (`scripts/archive-memories.py`) must be **built** on the `scripts/recover_anchors.py` guarded-mutation template (dry-run default, `_bulk_rewrite_guard` + `lock_jsonl_for_rewrite`, verbatim passthrough, surgical PG `UPDATE is_active=FALSE`), NOT on `bulk-archive.py`. Per-record `decay_days` exists on only 15 records (unused override); canonical decay is `category_config`.
- **Cold store:** monthly partitions `data/memories/archive/memories-archive-YYYY-MM.jsonl` in the `data` submodule — git history (remote `saross/pa-data`) is the durable offsite copy, so **no R2 path** (R2 mirrors *session* archives, which aren't in git). Retrievable via a proposed `fetch-memories.py --include-archive` (default off).
- **Six decisions for sign-off** in §9 (D1 Lever A · D2 tier structure · D3 gotcha/pattern · D4 progress 30-vs-14 · D5 cold store · D6 retrievability). **Standing caveat held:** do NOT prune on `verified=false` (residual ~224 is genuinely-gone files, not wrong memories — items 20/21). Execution is gated: per-bucket sign-off + quiet (corpus-clean) window; no-API for design + mechanical archival.
- **Next:** capture Shawn's per-bucket sign-off → build `scripts/archive-memories.py` (gated) → staged sweep (`progress` alone first, verify recall+digest unchanged). The 2026-06-13 §8 review still gates the 2b/2c sentinels; this work doesn't perturb them.

### 2026-05-31 (Sun, latest PA) — Items 20 + 21 (a+b+act) DONE: `verify_file` hardening, file-gate tightening, prefix-recovery diagnostic, AND the corpus fix applied; `verified=false` 404 → 224 and now a trustworthy signal

Ran the next write-path item in an isolated worktree (`workstream-b-item20`) per the concurrent-session convention. **Anti-confab catch up front:** the plan/continuity described `verify_file` as lacking absolute-path support and being HEAD-only, but the code (unchanged since `50e663b`) *already* stat'd absolute paths and ran `git log --all` history — so the only genuine resolver gaps were **tilde expansion** and an **absolute→git fallback** (an absolute path missing on disk got no history check). Implemented both: `expanduser()` on a leading `~`, plus a new `_git_knows_path` (HEAD `cat-file` + `git log --all`) reached via a lexical `_relpath_in_repo` prefix mapper. Deliberately did **not** thread "the memory's own commit" through the signature — `git log --all` already covers "existed on any ref", a superset, for negligible plumbing. **Re-ran the item-12 triage:** tilde broad-false file anchors **75 → 7**, ~40 records moved unresolvable → cross-repo (`cross-repo` 8 → 50, `unresolvable` 383 → 343). **But the headline is a reframe:** `verified=false` is *still* not a clean prune signal. Characterising the 272 unique relative refs still false shows the residual is **write-side anchor junk, not verifier gaps** — 143 (53 %) prefix-mismatch (real file, anchor dropped its dir prefix: `continuity.md` vs `wiki/continuity.md`), 68 genuinely-absent (incl. batch IDs / hex fragments mis-typed as `file`), 48 prose-as-`file`-anchor, 13 directory. Genuine wrongness signal stays tiny: **7** commit refs resolve nowhere.

- **Shipped (merged to main + pushed):** `0dc5172` (code+tests: tilde + absolute→git fallback, new `_git_knows_path`/`_relpath_in_repo`, 3 new test classes), `e100d3a` (plan doc: item 20 done, item 21 added). ff-only merge; workstream-G worktree + other sessions' dirty files (`data`, `wiki/reflections/*`) untouched. 134 anchor/triage/extraction tests pass.
- **Surfaced item 21 (write-side anchor hygiene, no-API)** — the *actual* blocker on trusting `verified=false`: (a) tighten the item-11 `file` gate to reject prose / bare IDs / slash-command names; (b) collision-guarded prefix-recovery (accept a basename suffix-match only on a unique hit). **(a) is the safer first step; item 20 was necessary but not sufficient.**
- **Item 21a DONE (`c27d6a4`, `d0bee38`):** `wellformed_anchor` → `_looks_like_file_ref` rejects prose / slash-command names / bare object-ids mis-typed as `file`, keying on path structure (separator/extension) **not** on spaces — so Zotero PDFs (`~/…/Hanson - 2016 - …pdf`) and extensionless real files (`LICENSE`) still pass. Forward gate; also reclassified existing junk in the triage: `clean-after-strip` **13 → 48**, `unresolvable` **343 → 311**, relative broad-false file anchors **452 → 405**. 162 anchor/triage/extraction tests pass. Worktree `workstream-b-item21` off `origin/main` (G pushed a `data` bump + continuity mid-session).
- **Item 21b DONE (`7dbee3f`):** `anchor_verify.unique_suffix_match` (pure, collision-guarded — recovers a prefix-dropped ref **only on a unique path-suffix hit**) + a read-only `recovery_status` breakdown in `triage_anchors.py`. **Measured on the live corpus:** of **225** unique relative refs resolving nowhere, **118 (52 %) safely recoverable** (real file at a unique suffix — `preregistration-draft.md` → `planning/preregistration-draft.md`), 17 (8 %) ambiguous (basename collision), 90 (40 %) absent. Kept **read-only on purpose** — `unique_suffix_match` is *not* wired into live `verify_file` (fuzzy matching would erode the `verified` signal), and no ref is rewritten. 175 tests pass. Also corrected now-stale triage fileform labels.
- **Net verdict (items 20 + 21):** `verified=false` is now **legible**. The genuinely-suspect "wrong memory" set is **tiny** — ≈**9** commit-refs-resolving-nowhere + a slice of the 90 absent; the bulk is recoverable (118), already-strippable junk (48 clean-after-strip), or cross-repo (50). So **item 13 pruning still must not treat `verified=false` as "wrong"** — it should target the recoverable/strippable cleanup + category retention, not deletion-by-verification-status.
- **Item 21b-ACT DONE (Shawn approved the window; data `a792240`, parent `6cd6666`):** built `scripts/recover_anchors.py` (dry-run default; `--apply` guarded by `_bulk_rewrite_guard` + `lock_jsonl_for_rewrite`, verbatim-passthrough minimal diff, `revisions` audit entry, surgical PG `UPDATE`). Re-verifies each modified record via the **exact production path** (`verify_memory` over `repo_set()`, `bind_confidence`). **Flushed the corpus first via `daily-sync.sh`** (the real content of the "quiet window" — the guard blocks on uncommitted appends), then `--apply`: **218 records — 155 false→true, 41 → unanchored (None), 21 refs corrected (hard anchor keeps false), 1 → pending.** 218 PG rows updated in lockstep; corpus integrity verified (30,235 records, 0 unparseable). **Post-apply triage: `verified=false` anchored 404 → 224; `clean-after-strip` 48 → 0; prefix-recovery `recoverable` 118 → 0** — corpus cleaned of all mechanically-fixable `verified=false` noise. Residual (irreducible): **7** commit-refs-nowhere + 93 absent + 17 ambiguous + 10 absolute + 7 tilde — genuinely-gone files, not wrong memories.
- **Net (items 20 + 21 a/b/act):** `verified=false` is now a **small, trustworthy** signal. **Item 13 (retention) must still NOT prune on `verified=false`** — the residual is genuinely-gone files; item 13 targets category retention/archival.
- **Next (no-API):** item 13 design (retention policy, per-bucket sign-off + quiet window). API-gated (costed): items 5/6/14/15. The 2026-06-13 §8 review still gates the 2b + 2c sentinels. Plan: `wiki/planning/memory-write-path-plan.md`.

### 2026-05-31 (Sun, latest G) — Workstream G efficacy experiment: the guide WORKS (citation-corrected — distance 4/4 + judge 6/8 now agree)

Ran roadmap item #1 end-to-end in an isolated git worktree (`worktree-workstream-g-efficacy`; data submodule on branch `workstream-g-efficacy`) per Shawn's instruction, given the concurrent memory/scratchpad session sharing the tree. Designed *with* Shawn (3 structured decisions): in-CC fresh-context subagents (Opus 4.8, **no API gate**), 3-condition paired design (C0 plain / C1 generic-academic / C2 full guide + Appendix F), pilot-first. Pre-registration + harness committed before generating. **The experiment turned on two reversals.** (1) The whole-paper Phase 5 feature space mis-scores ~400-word passages — **hapax ratio is a length artefact** (Heaps' law; ~58% of the squared Mahalanobis distance), so I built a **length-matched reference** (319 ~400-word corpus excerpts) and re-scored. Corrected result: **guide ≈ plain (Δ≈0)**, the C3 "operative-preamble" revision *worse* (over-direction overshoot), and **generic-academic actively harmful** (−0.92 LOO-SD vs plain — "write like a journal" overshoots Shawn's crisp register). That looked like a null. (2) But a **blind, order-counterbalanced pairwise judge test** (16 judgments, real corpus excerpts as reference) **preferred the guide 13/16 (81%); original guide C2 = 7/8**, robust to a mild position bias, all high-confidence picks favouring it. **Resolution: the 12-feature distance is blind to the markers judges actually use** — author-date citations (not even a phase1 feature), first-person-plural stance, concession-then-rebuttal — and over-weights the guide's sentence-length overshoot. The guide looked like it worked only on the judge, with the distance blind. **(3) Citation correction (Shawn, same day) overturned that.** Citation format is venue-determined, NOT voice — and it had leaked three ways: the guide §3 prescribed it, the Appendix F exemplars demonstrated it, and the judge prompt *rewarded* it ("citation habits" was a listed criterion). Removed surgically (guide §3/§9.4 → exclusion notes; injection citation-strip + no-citation directive; judge prompt + reference de-citationed), C2 regenerated citation-free, C3 dropped, both tests re-run. **Corrected: C0 plain → C2 guide = +0.44 LOO-SD, 4/4 on the distance — the earlier "null" was itself a citation artefact (citation clauses had inflated C2 sentence length |z| 1.66→0.995 and passive 0.91→0.21) — and the blind judge still prefers the guide 6/8 (down from 7/8: citations had been part of the cue).** So **both** metrics now agree the guide moves output toward the corpus on *intrinsic* voice; the "distance is the wrong gate" framing was overturned once generation is citation-free. **(4) Three diagnostic-driven guide adjustments (Shawn-approved):** citation-free corpus reference + §6.2 semicolon target corrected (6.54→≈3.4/1k, the 6.54 was ~half citation-list); concession dialled back (§6.7/§9.2 — C2 had conceded ~2× corpus); first-plural moderated (§1.1 — C2 over-produced "we"). After adjustment **C0→C2 = +0.66 LOO-SD, 4/4** (from +0.44), first-plural now exact (5.03 vs 5.05), concession near-corpus (0.19 vs 0.14), judge stable 6/8 — guide ready for /write-like-me. `efficacy-synthesis.md` is the authoritative capstone.

- **Verdict + roadmap:** item #1 DONE; item #2 (`/write-like-me`) **justified** — build on the **citation-stripped original guide + Appendix F** (NOT the rejected C3 preamble); output carries **no citations** (venue-determined, §3). Guide §3/§9.4 now mark citation format excluded — the standing correction Shawn flagged. Queued #7 (2×2 ablation — does Appendix F contribute?) and #8 (judge-based/discourse-aware efficacy gate).
- **Artefacts:** pre-reg `wiki/planning/style-guide-efficacy-experiment-design.md`; harness `scripts/style-analyser/efficacy_{build_prompts,build_reference,score,analyse,build_judge_tasks,score_judges}.py`; data `data/experiments/style-efficacy-2026-05-31/` (prompts, 24 citation-corrected passages C0/C1/C2, scores, `efficacy-synthesis.md` [authoritative], plus original-run records `pilot-findings.md`/`retest-analysis.md`/`judge-analysis.md` marked superseded). Original citation-confounded run preserved at submodule `e51e998` / parent `ab471c5`.
- **Caveats:** pilot scale (4 topics; deterministic n=4 paired; judge 8 judgments, one/pair, mild B-position-bias — corrected 6/8 leans on it); Claude judged Claude-written text (blind, vs citation-stripped real excerpts). **Final validation RESOLVED 2026-06-03: Shawn read the four C2-vs-C0 pairs blind and picked the guide 4/4** (both high-confidence calls among them; `human-validation.md`). The author — the only non-proxy judge — confirms the guide works.
- **Not yet merged to main** (held for Shawn's review + concurrent-session coordination); memory capture deferred (concurrent session is editing `memories.jsonl`).

### 2026-05-31 (Sun, PA) — Vector 2 Stage 2 reframe + Vector 2c (dark) + git guardrails + write-path pivot (items 11 & 12)

A long memory-system session in two arcs. **Read-path arc:** reframed Vector 2 Stage 2 — the promoted-recent fallback is *permanent*, not a stopgap, because anchoring is forward-only and only ~3.6 % of the corpus carries anchors (`6bbb418`, `a4f6ba1`); then assessed the session-start injection's efficacy (read path strong, but the digest's verified entries were recency-random — 1-of-4 relevant in a hub session) and built **Vector 2c** — focus-aware + project-scoped digest selection, Option 3 (focus-ranking + a thin legibility label), shipped **DARK** behind `PA_DIGEST_FOCUS`, enable after the 2026-06-13 §8 review. The 2c code landed in workstream-G commit `cfa9152` via a concurrent-session bare-commit sweep (no loss; documented in `0d22dd7`), which prompted **git concurrency guardrails**: a scratchpad principle (`058cb0a`/`b2bdd41`) and a worktree escape-hatch in the CLAUDE.md convention (`88be212`). **Write-path arc:** pivoted to corpus health (read path well-disciplined; write path is an append-only firehose — 1 correction in 29.9 K records). A read-only corpus profile reframed the "<4 % verified" alarm: 86.5 % predates the 2026-05-16 anchoring epoch and is unanchorable by construction, so "cut the unverified" would be amnesia. Shipped **item 11** (write-time anchor quality gate, `b6f85c1`) and **item 12** (verified=false triage, `5edbdd4`), which found verified=false is overwhelmingly a *verifier artefact* (`verify_file` can't expand `~`/absolute paths, checks HEAD-only), not wrong memories — surfacing **item 20** (`verify_file` hardening) as the next no-API lever that must precede any pruning.

- **Read path:** `6bbb418` (Stage 2 reframe), `0d22dd7` (Vector 2c dark + `cfa9152` provenance). 2c code swept into `cfa9152`. Designs: `wiki/planning/vector-2-design.md` §6b, `wiki/planning/vector-2c-design.md`.
- **Git guardrails:** `058cb0a`/`b2bdd41` (scratchpad), `88be212` (worktree convention). Lesson: stage+commit atomically via `git commit -- <path>`; never leave files staged across turns in this shared-tree repo.
- **Write path:** `8cc8275` (plan + 2026-05-31 corpus profile + 19-item backlog), `b6f85c1`+`c7824aa` (item 11), `5edbdd4`+`9a07c88` (item 12 + item 20). Full suite 844 passing.
- **Next session (no-API):** item 20 (`verify_file` path/history hardening) → re-run item-12 triage → item 13 design (retention policy, needs per-bucket sign-off + quiet window). API-gated (costed): items 5/6/14/15. The 2026-06-13 §8 review now also gates enabling the 2b + 2c sentinels. Plan: `wiki/planning/memory-write-path-plan.md`.

### 2026-05-31 (Sun, G) — Workstream G big-picture review + handoff; next session = efficacy experiment

Stepped back from the details to map the whole "style assessor + write-in-Shawn's-voice" endeavour (captured in the new "Big-picture status & roadmap (2026-05-31 review)" block in the workstream-G section above). Conclusion: the **assessor (academic) is done**; the **end — writing in his voice — is under-built and its efficacy is unproven**, which makes the with-guide-vs-without efficacy experiment the highest-value, lowest-cost next move (it gates generation-workflow packaging and any multi-genre work). Handed off to a fresh session for that experiment rather than continuing — this session's context was large and implementation-laden (the §6.5 plumbing + the commit-sweep incident), and the experiment is a distinct, methodology-sensitive design task that wants a clean head. Earlier in this same 2026-05-30→31 session: tolerance refinement verified; three Phase-5 user-observation candidates dispositioned (`a57bcb4`); §11 reconciled against Shawn's conscious-writing intent as a clean start (superseded guides not cited, live cross-refs instead); the §6.5 paragraph-length segmentation artefact fixed end-to-end; the workstream-labelling convention added and then strengthened after a real commit-sweep.

- Roadmap + all six to-dos (3 major, 3 minor) captured in the workstream-G "Big-picture status & roadmap (2026-05-31 review)" block.
- **Next session's task:** efficacy experiment — generate with/without guide, score via `phase5_evaluator.py`, compare Mahalanobis distance + 8-metric gate pass-rate. Scoring CPU-only/no-API; generation-step model + cost needs the usual API gate if non-CC.
- Commit hygiene: a concurrent memory/scratchpad session shares the working tree — use `git commit -- <path>` (pathspec) per the strengthened convention in `CLAUDE.md` (`8e80ea8`); `wiki/continuity.md` is the one file both workstreams edit, so commits there will cross-sweep (benign, labelled).

### 2026-05-30 (Sat, G) — Workstream G §11 reconciliation: aspirational section reconciled against the live empirical assessment; five items added; paragraph-length gap diagnosed as a §6.5 artefact

Completed the §11 aspirational-section reconciliation (continuity row 589) — the last open Workstream-G item beyond the deferred multi-genre runs. Per Shawn's direction this was a **clean start**: the prior conscious style guides at `~/Code/prompts/System-setup/` were read to drive the reconciliation but are treated as superseded and are NOT cited in the guide; confirmed items instead carry `Live cross-ref` pointers into the empirical §§1–10. Four decisions resolved: (1) relabel confirmed items with live cross-refs (§§11.3/11.4/11.6/11.7); (2) add four editorial rules — standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation; (3) add a voice-calibration item (prefer first person for crispness, third person where it avoids convolution; baseline first-person-plural per §1.1); (4) the prior-guide 100–180-word paragraph target seemed to conflict with §6.5's median of 17 words, but a background investigation confirmed that is a **segmentation artefact** — `split_paragraphs()` counts headings, surviving front-matter and line-break fragments as paragraphs (non-prose = 41% of blocks but only 4.4% of words), so the median sits below the mean sentence length (21.45 words), impossible for real prose. Corrected median ≈27, mean ≈42; the apparent two-register cluster is contamination-driven (r = −0.78) and was never a formal bimodality.

- Guide §11 (submodule `16be506`): intro marked reconciled; live cross-refs on §§11.3/11.4/11.6/11.7; new §§11.9–11.13 (standalone-demonstrative ban, impersonal-opener minimiser, attribution-verb tiering, connective variation, voice calibration).
- Agent template (`agents/corpus-style-analyser-v2.md`): Phase 4 + §11 skeleton now reconcile against the live empirical assessment, not the superseded prior guides; academic register marked reconciled 2026-05-30.
- §6.5 artefact: background agent quantified contamination across all 18 papers and proposed an `_is_prose_block()` filter. **Applied 2026-05-30** (scoped to the paragraph-stats path only; sentence stats, the 8-metric gate, and all word-level metrics byte-identical — verified by full structural diff, 77 field diffs / 0 non-paragraph): phase1→3→5 re-run; corpus median 17→27, mean 30→41, n 4 213→2 968. phase3 now: paragraph median `attested` (unimodal), mean `attested-concentrated` (the genuine short-vs-long register split, re-located from the contaminated median). phase5: paragraph mean excluded from the centroid as bimodal (11 features), LOO max 4.67→4.42, sanity PASS. Guide §6.5, Appendix A/C, comparison + diff entries, and the §11 note regenerated (submodule `0f85a3c`).
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
