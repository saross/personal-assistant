# Session-transcript archiving and retrieval — upgrade plan

**Date:** 2026-07-21. **Workstream:** session-archiving (SA).
**Sources:** tiered-architecture decision (session 2026-07-20/21, this
plan's parent session); Three Ps audit
(`data/reports/threeps-audit-2026-07-21.md`, data commit `f99270b`);
review of Brian Ballsun-Stanton's
`Denubis/claude-code-research-transcript-hook` (v0.7.3, 2026-07-13).

**Decisions already made (context, not open questions):**

- **Tiered architecture.** One conceptual system, two layers: the
  existing cc-session-toolkit floor (capture, auto-metadata, memory
  extraction, `/search-sessions`, multi-machine convergence) runs
  everywhere; research repos (~70% of work) additionally get Brian's
  `transcript-archive` plugin as the curated, citable, in-repo
  research-record layer. Analogy ratified by Shawn: /reflect
  (research-only, separate tooling) vs /handoff (universal).
- **Floor archives never promote to research-tier (collaborator-
  visible) storage without a sensitivity screen.** Audit evidence:
  ~18% of sampled floor entries carry sensitive personal content.
- **Sensitive-data control is procedural, not technical** (Shawn,
  2026-07-21, correcting the audit's defect-1 framing): the root
  error was processing identifiable student data in the personal
  Anthropic account at all, not the Gemini extraction leg
  specifically. Standing rule: no identifiable student data (or
  equivalent third-party sensitive material) processed in this
  account; future ARDC work runs on the ARDC enterprise account;
  Claude actively checks at intake and flags slips (established
  pattern — this has caught slips before).

## A. Research-tier adoption (Brian's tooling)

- [ ] **A1. Pilot install on llm-reproducibility.** Install the
  `transcript-archive` plugin (marketplace or `uv tool`), configure
  in-repo `./ai_transcripts/`, run `/transcript` on 2–3 sessions,
  assess the Three Ps curation workflow and outputs (CATALOG.json,
  SUMMARY.md, HTML). Success test: an evidence-grade session record a
  methods section could cite. (~1–2 h, out-of-hours)
- [ ] **A2. Thinking-block due diligence.** Before any shared-repo
  install, verify how Brian's tool handles thinking blocks in
  archived transcripts (our toolkit has explicit thinking-block
  ethics handling; his equivalent unverified). (~0.5 h; blocks A3)
- [ ] **A3. Research-repo designation + rollout.** Enumerate the
  research repos that get the tier (llm-reproducibility, inscriptions,
  map-reader-llm, Paper B, LLM-History-Paper, …); per-repo decision
  on collaborator visibility of in-repo transcripts; install; DVC
  where volume warrants (his 0.7.3 is DVC-aware). (~2 h after A1)
- [ ] **A4. /handoff wiring.** In research-tier repos, /handoff
  prompts the `/transcript` Three Ps curation pass at session close,
  mirroring the /reflect precedent. (~1 h)
- [ ] **A5. Upstream PR: auto-draft pre-fill for needs_review.** Our
  extractor already produces bake-off-validated Three Ps
  (prompt/process/provenance, field-for-field compatible). PR Brian's
  tool to accept a pre-filled draft so `/transcript` curation starts
  from the machine draft (human confirms + adds off-transcript
  context) instead of blank. Directly cuts the research-tier's main
  workflow tax. (~3–4 h incl. his test conventions; goodwill high —
  see the accepted register-note interchange precedent)
- [ ] **A6. Sensitivity screen rule, written down.** Encode the
  never-promote-without-screen rule in the toolkit docs and the
  research-tier install checklist (A3), so it is a stated invariant,
  not configuration folklore.

## B. Floor upgrades (cc-session-toolkit)

- [ ] **B1. Auto-stitch port.** Adopt Brian's customTitle-clustering
  approach to stitch continuation sessions into one archive cluster.
  Fragmented continuations currently hurt memory extraction,
  `/search-sessions`, and the catalogue. Read his Phase 2–6 design
  (`docs/design-plans/2026-05-16-auto-stitch-customtitle-clustering.md`)
  before building. (~4–6 h; the largest single floor item)
- [ ] **B2. needs-review/status loop.** `status` verb listing
  unarchived + needs-review sessions with exact follow-up commands
  (his 0.6.0 pattern); hook-archived entries flagged for later
  curation instead of fire-and-forget. (~2–3 h)
- [ ] **B3. Archive-time identifier verification.** Verify named
  commit hashes and paths at archive time (the audit's method,
  automated): flags inherited stale-doc errors at the moment of
  capture. Audit evidence: the only failed hash in 126 was inherited
  from a stale continuity doc read in-session. (~2 h)
- [ ] **B4. decisions-array consumer.** The structured decisions
  records are write-only. Options: a `/recall`-adjacent query
  surface, or feed decisions into the memory pipeline as first-class
  records. Decide, then build the small version. (~2–4 h)
- [ ] **B5. code_state cross-repo bug.** `commit_at_start` sometimes
  captured from the parent repo when the session's project is the
  data submodule (2 instances in the 40-entry audit). File and fix in
  cc-session-toolkit. (~1 h)
- [ ] **B6. Archive-location reconciliation.** 257 metas live in
  nested locations the catalogue/sampling misses:
  `map-reader-llm/vlm-burial-mound-detection` (149 — project also
  archives top-level; drift from sub-project graduation),
  `LLM-History-Paper/theseus-ship` (60), `_legacy/` (45). Decide
  canonical layout, migrate, confirm `/search-sessions` indexes the
  lot. (~1–2 h)

## C. Extractor quality fixes (auto_metadata prompt + pipeline)

Audit baseline (40 entries): zero extractor confabulation (125/126
hashes, ~530 paths); weaknesses are tags 1.50, framing ~1.5,
arrays 1.63.

- [ ] **C1. Tag validator.** Post-generation check: each tag
  groundable in summary text; deny-list enforced in code; 2–5 cap;
  no project-name echoes or path-mangled tags. One regeneration
  retry on failure. Highest-value fix — tags are the retrieval keys
  and ~1 in 2–3 entries carries a defective tag. (~2 h)
- [ ] **C2. Framing rule: enforce or delete.** "The user
  requested…" openers survive in most entries despite the ban.
  Either add negative examples + a validator regex, or drop the
  rule. A rule that pretends is worse than none. (~0.5–1 h)
- [ ] **C3. Quote discipline.** Enforce the ~50-word key_exchanges
  cap (length check); add a rule for AskUserQuestion transactions
  (render as question + chosen answer, not pseudo-quote). (~1 h)
- [ ] **C4. Count-recomputation rule.** Counts must be recomputed
  from the final state / the emitted list, not quoted from
  mid-session prose (audit: "three commits" listing six; "five"
  where git shows seven). Prompt rule + spot validator. (~0.5 h)
- [ ] **C5. Minor sweeps.** UK/AU spelling in outputs (US spellings
  in ~4 of 40); language-glitch watch (stray CJK, one "resultados");
  chosen-option-must-be-listed check for decisions; self-referential
  provenance check (entry citing its own session id as antecedent).
  (~1 h)
- [ ] **C6. extractor_model_id backfill.** Stamp the ~367
  unattributed metas "extractor unrecorded (pre-2026-05-17 audit)".
  Audit finding: these are not an older generation (8 of 10 sampled
  carry full v3-style arrays) — bookkeeping only. (~0.5 h)
- [ ] **C7. Marathon-session coverage spot-check.** Verify the v3
  phases array copes with very long multi-thread sessions (audit
  found thread-level coverage on a 4,833-minute NONE-era session;
  v3 unproven at that scale). (~1 h)

## D. Data governance

- [ ] **D1. Procedural sensitive-data rule, encoded.** Add the
  standing rule (header decision 3) to the global CLAUDE.md teaching
  section or the memory system: no identifiable student /
  third-party sensitive data processed in the personal account;
  ARDC work on ARDC enterprise account; Claude checks at intake.
  (~0.5 h, wording Shawn approves)
- [ ] **D2. Retention decision for existing teaching-session
  archives.** Archived HUMN8031 sessions (transcripts + metas with
  identifiable student data) already sit in `~/cc-archives/` and
  mirrors. Decide: retain (private, legitimate record), redact
  metas, or purge the cohort. Shawn's call; needs listing first
  (cheap grep). (~1 h to enumerate + decide)

## E. Reflection-layer repairs (added 2026-07-22)

The /reflect output review (2026-07-22) found the reflection corpus
high-quality but under-anchored for its intended research use. Shawn
ruled transcript-pairing mandatory. Correction on the record: the
review's initial "19 abductive entries vs ~100 paper-b sessions, zero
skips" was a counting error (subheads swept into entry counts) —
paper-b has 20 true session-log entries and near-total reflection
coverage; the skip-discipline gap applies prospectively, not to
paper-b's record.

- [x] **E1. /reflect schema 2** (2026-07-22, commit `aeb2897`):
  mandatory session-id anchor + instance field on abductive entries,
  standardised core + named optional sections (incl. the falsifier
  "What would change this belief"), mandatory skip assessments (the
  denominator), retro-annotation convention, and a prompt-rotation
  guard for session reflections ("surprised" had collapsed to ~100%
  selection; "uncertain or unresolved" used once in ~90 entries).
- [x] **E2. Retro-match existing abductive entries to archived
  transcripts** (2026-07-22, three agents; commits inscriptions
  `5dd52ad`, paper-b `ba50e16`, llm-repro `676d0e2`, PA `3507c0b`).
  **63 records annotated: 49 transcript-confirmed (78%), 8
  meta-matched, 6 unmatched** — inscriptions 33/33 confirmed;
  paper-b 10/7/2; llm-repro 4/1/2 (file held 5 entries + 2 skips,
  not the 6+4 previously stated); PA 2/0/2 (entry + dated revision
  subsections anchored separately). Every meta-matched and unmatched
  record traces to ONE cause: travel/machine-swap coverage gaps —
  eight paper-b archives (2026-06-25→07-14) and two llm-repro
  archives are meta-only locally (transcripts recorded by sha256 in
  the meta but absent, plausibly on R2 or never converged from
  zbook), and six records' authoring sessions ran on another machine
  and were never archived here. Also surfaced: inscriptions Entry 14
  referenced by three entries but never written (reconstructable —
  its session is now identified); one duplicate archive dir sharing
  a session id (→ B6); one in-file date contradicting git history
  (PA confidence note, 04-19 vs commit 04-18).
- [x] **E3a. Convergence repair (2026-07-22).** Root cause found:
  daily-sync's cc-archives passes push transcripts up append-only
  and sync metadata both ways, but **no pass pulls transcripts
  down** — local mirrors are transcript-partial by design, and the
  meta-only shells were zbook-archived sessions whose transcripts
  only canonical (and zbook) held. Repair run with all machines up:
  zbook → local → canonical append-only passes plus the missing
  pull leg; all 25 paper-b + current llm-repro transcripts now
  present locally and **sha256-verified against their metas (25/25,
  0 mismatches)**; two never-archived sessions recovered from
  zbook's raw store and archived `--stats-only` (no API calls;
  placeholder metadata pending needs-review):
  `2026-07-14T12-23_19779003` (paper-b) and
  `2026-07-13T23-54_6590f824` (llm-repro); zbook,
  local, and canonical fully converged. (Correction, same day: the
  older `agent-*` meta-only cohort was NOT lost — zbook's archive
  store held those transcripts and the zbook→local pass recovered
  them; the completeness gate now reads 0 across the corpus.)
- [x] **B7. Transcript-pull posture: DECIDED + IMPLEMENTED
  (2026-07-22).** Full mirrors on all working machines (zbook LUKS
  full-disk encryption confirmed by Shawn). daily-sync gains pass 4
  (append-only transcript pull canonical → local) and a
  **completeness gate**: metas recording a `jsonl_sha256` with no
  local transcript and no `transcript_lost` write-off marker are
  counted to `~/.cache/cc-archives-gate`; daily-sync-trigger
  surfaces a warning at EVERY session start while non-zero. Store
  roles documented in `network-resources.md` (mirrors / canonical /
  R2-backup / project-local side-output), including the R2
  break-glass pull and the pre-travel gate-must-read-0 ritual.
  Verified in production same day: all four passes green, gate 0,
  R2 push complete. Rejected alternative (canonical-fallback in
  consumers) recorded in the 2026-07-22 session.
- [x] **E3b. Anchor close-out (2026-07-22).** Post-repair rematch:
  **29 of 30 anchor records transcript-confirmed, 0 meta-matched,
  1 unmatched** (paper-b 2026-07-02 daytime — its session fell in a
  genuine archive gap; not in any store incl. R2, which mirrors
  canonical; accepted as lost unless a third machine surfaces).
  The rematch also found and repaired a third failure mode: three
  archives were **mid-session snapshots** (sha-verified strict
  prefixes of the full sessions) truncating exactly the episode
  material; re-archived complete from zbook's raw store
  (--stats-only), truncated metas kept as in-dir backups.
  Commits: paper-b `a6e0537`, llm-repro `f2ce612`, PA `fc14a4e`.
  Remaining sub-items: (c) optional Entry 14 reconstruction
  (inscriptions); (d) pre-research audit of contemporaneous
  session ids.
- [ ] **B8. Snapshot-supersede handling** (new, from E3b): archives
  created mid-session (pre-compact or early Stop) can fossilise a
  truncated transcript that later looks complete. Toolkit should
  re-archive (or flag needs_review) when the raw session grew after
  the archive was cut — detectable by comparing archive
  `jsonl_bytes` against the raw file before rotation. Fold the B6
  dedupe residue in here too: one byte-identical duplicate archive
  pair (llm-repro 6590f824), the 13 KB `50ed4d22` stub, the
  inscriptions duplicate dir pair, and the project-local
  `archive/cc-sessions/` duplicates policy. (~2 h)

## Sequencing suggestion

A1 → A2 → (A3–A6 rollout) as the visible win; C1–C4 as one batched
prompt/pipeline pass; B1 as the biggest floor improvement; B5/C6 as
quick hygiene; D1/D2 early because governance. All out-of-hours per
the standing research-first rule; A1 pairs naturally with the next
llm-reproducibility working session.
