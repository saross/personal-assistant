---
title: "Session archiving and retrieval — how the system works"
tags: [session-archiving, infrastructure, research-record]
created: 2026-07-23
updated: 2026-07-23
status: active
---

# Session archiving and retrieval — how the system works

State-oriented reference for the session-transcript system as it
stands after the 2026-07-18→22 overhaul. The change history and open
work items live in
`wiki/planning/session-archiving-upgrade-plan-2026-07-21.md`; this
page describes what IS.

## Two-layer architecture

- **Floor (every repo):** cc-session-toolkit
  (`~/Code/cc-session-toolkit`) archives every session via
  SessionEnd/PreCompact hooks into `~/cc-archives/<project>/`, with
  auto-generated Three Ps metadata (Prompt/Process/Provenance, RDA
  framework; Gemini 3.5 Flash extractor, model attribution stamped in
  each `session.meta.json`). The floor serves continuity: memory
  extraction, `/search-sessions`, recall.
- **Research tier (per-repo opt-in, ~70% of work):** Brian
  Ballsun-Stanton's `transcript-archive` plugin
  (`Denubis/claude-code-research-transcript-hook`) adds curated,
  citable, in-repo evidence archives (`./ai_transcripts/`,
  human-elicited Three Ps, needs-review workflow, DVC at scale).
  Adoption plan and pilot status: plan items A1–A6. The two layers
  coexist; the floor never turns off.
- **Boundary rule:** floor archives are ~18% sensitivity-bearing
  (2026-07-21 audit) and are **never bulk-promoted** to
  collaborator-visible research-tier storage without a sensitivity
  screen.

## Stores and sync (B7 decision, 2026-07-22)

Four stores, fixed roles — operational table in
`data/global-claude-md/network-resources.md` §"Session-archive
stores". Summary: **local full mirrors** on amd-tower and zbook (the
only offline-capable copies; all tooling reads locally,
single-path); **canonical union** on rpi-server (home LAN, via the
rpi-shares SSHFS mount); **R2 offsite backup** (additive-only,
break-glass pull documented, NOT an operational read path);
**project-local** `archive/cc-sessions/` side-outputs (not
converged).

`daily-sync.sh` runs four cc-archives passes: (1) append-only
transcript push local→canonical; (2)/(3) metadata `--update` both
ways; (4) append-only transcript pull canonical→local. Pass 4 exists
because passes 1–3 alone leave mirrors transcript-partial (the
"meta-only shell" failure — see below).

**Completeness gate:** after pass 4, every `session.meta.json`
recording a `jsonl_sha256` must have a sibling transcript locally
(or an explicit `transcript_lost` write-off). The count is written
to `~/.cache/cc-archives-gate` and `daily-sync-trigger.sh` announces
a non-zero count at **every session start**. A silent gate means the
local mirror is complete. Pre-travel ritual: daily-sync on zbook at
home; gate must read 0.

## Reflection layer (research corpus)

`/reflect` (schema 2, 2026-07-22) maintains per-project
`wiki/reflections/` documents. `abductive-reasoning.md` files are a
cross-project research corpus (~65 episodes, Feb 2026→): every entry
carries a **contemporaneous session id** and instance field, skip
assessments are mandatory (the denominator), and all pre-schema-2
entries were retro-matched to archived transcripts (29 of 30
transcript-confirmed; sole loss: paper-b 2026-07-02 daytime
session). An episode is auditable: its anchor names the archive dir
whose sha-verified transcript contains it.

## Known failure modes (and their status)

1. **Meta-only shells** — sessions archived on another machine
   appeared locally as metadata without transcripts. Root cause: no
   transcript-pull pass. FIXED (pass 4 + gate, 2026-07-22).
2. **Mid-session snapshot archives** — an archive cut pre-compact or
   mid-session fossilises a truncated transcript that looks
   complete; three found (sha-verified strict prefixes), re-archived
   complete. OPEN: automatic supersede detection is plan item B8.
3. **Archive-location drift** — nested project stores
   (`map-reader-llm/vlm-burial-mound-detection`, `_legacy/`,
   duplicate dirs, a stub). OPEN: plan item B6.
4. **Inherited stale-doc errors** — extractor metadata faithfully
   propagates wrong identifiers read in-session (1 of 126 hashes in
   the audit). Mitigation planned: archive-time identifier
   verification (B3).
5. **Metadata quality drifts** — tags weakest (spurious ~1 in 2–3
   entries), framing boilerplate, over-length quotes, stale
   mid-session counts. Quality baseline + fixes: audit report
   `data/reports/threeps-audit-2026-07-21.md`, plan items C1–C7.

## Governance

Sensitive-data control is **procedural**, not routing: no
identifiable student or third-party sensitive data processed in the
personal Anthropic account at all; ARDC work on the ARDC enterprise
account; Claude checks at intake (encoded in the plan, D1). A
retention decision on legacy teaching-session archives is pending
(D2).

## Pointers

- Change plan / open items:
  `wiki/planning/session-archiving-upgrade-plan-2026-07-21.md`
- Metadata quality audit: `data/reports/threeps-audit-2026-07-21.md`
- Store roles + emergency pull:
  `data/global-claude-md/network-resources.md`
- Extractor prompt:
  `~/Code/cc-session-toolkit/src/cc_session_toolkit/prompts/auto_metadata.md`
- Research-tier tool: `Denubis/claude-code-research-transcript-hook`
  (v0.7.3 at adoption decision)
