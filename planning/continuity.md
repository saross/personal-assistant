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

**Workstream D — memory-system rethink + wiki formalisation (new 2026-05-17):**

- [ ] **Implement `/handoff` as actual skill** in `commands/` (protocol exists at `global-claude-md/handoff-protocol.md`)
- [ ] **Draft `global-claude-md/session-start-protocol.md`** — short companion to handoff-protocol.md; covers reading continuity.md first, spot-checking things-to-verify, de-weighting the auto-loaded recall dump, eventual auto-loading of wiki/notes index files
- [ ] **Pilot wiki migration on personal-assistant** — move `planning/` and `docs/` under `wiki/`; add `wiki/index.md`
- [ ] **Sketch `notes/index.md` + initial wiki-tag vocabulary** — cluster the corpus to surface real topics first
- [ ] **Extend `/weekly-review` with cluster-and-carry curation step** — produce candidate wiki-page diffs
- [ ] **Phase 0 archive consolidation — priority promoted** (open-science topic-search depends on this)

**Provenance audit gaps to close opportunistically (from workstream D audit, 2026-05-17):**

- [ ] **Gap 1: add `source_message_uuid` to extracted memories** in `hooks/extraction-hook.py` `format_memories()`. UUIDs already parsed but discarded. Enables tier-3 verifier fallback. Highest-value-low-cost fix.
- [ ] **Gap 2: capture `code_state.{commit_at_start, commit_at_end, dirty_at_end}` on session records** in `cc_session_toolkit/archive.py` `create_session_metadata()`. One `git rev-parse HEAD` call.
- [ ] **Gap 3: add `license` and `extractor_model_id` to memory + session records.** RO-Crate-required for sharing; extractor model ID currently hard-coded constant only.
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
