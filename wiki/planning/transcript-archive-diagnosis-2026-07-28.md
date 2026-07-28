# Transcript archive — diagnosis of the error shape

**Date:** 2026-07-28
**Trigger:** the map-reader preregistration-vs-results audit. The audit is finding
confabulations in the reasoning recorded in intermediate documentation, and per Paper B's
own finding the **external grounding exists only in the session transcripts** — so the
transcript archive is the audit's evidence base, not supporting infrastructure.
**Scope of this document:** characterise the errors. **It does not fix the pipeline** —
that is the Thursday "fix a class" work (`session-archiving-upgrade-plan-2026-07-21.md`,
items B7/B8).
**Supersedes:** an earlier single-session characterisation that was wrong on three
counts; corrections are recorded in §3 so the error is legible rather than silently
overwritten.

---

## 1. Containment (done first, before any analysis)

Raw transcript stores snapshotted on both machines, read-only source, new destination:

| Machine | JSONL files | Size | Verified |
|---|---:|---:|---|
| amd-tower | 2,005 / 2,005 | 1.7 G | file count matched |
| zbook | 2,267 / 2,267 | 5.1 G | file count matched |

Destination on each machine: `~/backups/claude-raw-transcripts-2026-07-28/`.

Rationale: the raw store survived only because Shawn had held off purging old transcripts
and had not shortened the retention period. That is luck, not a safeguard.

---

## 2. Method (so every number below is re-verifiable)

- **Raw session identity** = basename of a top-level `*.jsonl` under
  `~/.claude/projects/<cwd-key>/`, excluding `subagents/` (those are agent transcripts,
  not sessions).
- **Archive session identity** = `session.session_id` read from `session.meta.json`
  inside each `<archive-root>/**/YYYY-MM-DDTHH-MM_<slug>/` entry.
- **Session dates** in §6 come from the first `timestamp` field *inside* the JSONL, not
  from mtime. Month tallies in §3 marked "(mtime)" are approximate; archive month tallies
  come from the date encoded in the directory name and are authoritative.
- Archive set built by recursive walk of `~/cc-archives` across **all** projects — not
  per-project — because sessions are demonstrably misfiled across project boundaries (§5).

---

## 3. Corrections to the earlier characterisation

### 3.1 The repo was never renamed — but the ARCHIVE PROJECT NAME was

**⚠ This section was itself wrong in its first draft and is corrected here.** The first
draft asserted a cwd-forking mechanism ("sessions launched from a subdirectory fork the
archive"). **That is not what happened**, and the correction matters because it changes
the consolidation decision.

**What is true:**

- Repo: `~/Code/map-reader-llm`; `origin = git@github.com:saross/map-reader-llm.git`.
  Never renamed. ✔ (Shawn's read was correct.)
- **Sessions were launched from the repo root**, as Shawn believed. Traced from raw
  transcripts, the 149 location-C sessions record `cwd`:
  **139 = `/home/shawn/Code/map-reader-llm`** (the root), 3 =
  `map-reader-llm/inputs/examples/neutral`, 7 = no cwd recorded. Back to 2025-12-22.
  ✔ (Shawn's habit was as he remembered.)
- **`vlm-burial-mound-detection` never appears as a launch directory anywhere in the
  corpus.** It is not a cwd artefact.

**Actual mechanism: the archiver's `project.name` changed.** Every entry in locations B
and C records `project.name = "vlm-burial-mound-detection"`; every entry in A records
`project.name = "map-reader-llm"`. Same repo, same cwd, two archive-layer project names
across time. So **the original session's "project rename" diagnosis was right** — the
rename was of the *archive project name*, not the repository, which is exactly why no
repo-level evidence of it exists.

**Corrected policy implication.** Launch discipline was never the problem here. The rule
that matters is:

> **The archive's project name is an identity. Changing it forks the archive silently and
> irreversibly, and nothing reconciles the two names afterwards.** Renames need an
> explicit migration step, not just a new value.

Launch discipline is a *separate, minor* issue — see §3.4.

### 3.4 Launch discipline: essentially clean

Measured across 923 sessions with a recorded `cwd` (30 distinct values):

| Category | Sessions |
|---|--:|
| Launched from a clean git repo root | 781 |
| Path no longer exists (deleted dirs / unmounted synology drive) | 113 |
| Launched from `~` or `~/Code` (non-repo parents) | 28 |
| **Genuine nested launch inside a repo** | **1** (`ANU-HUMN8031-2026/canvas-materials`) + 3 (`map-reader-llm/inputs/examples/neutral`) |

Shawn's belief that he always started at the repo root is **substantially correct**. The
113 "path missing" entries are not a discipline failure — they are directories since
deleted or an external drive not currently mounted.

### 3.2 April was never missing

**27 archived April sessions exist** for map-reader, in the nested location. The earlier
count returned 0 because it searched two of the four locations. Its per-month figures
match locations A + B exactly — a complete count of an incomplete search.

### 3.3 Nothing rotated away; raw is a superset of the archive

**Archive session IDs with no raw counterpart: 0** (of 727). Every archived session still
has its raw JSONL on one of the two machines. The earlier claim that the archive held
Dec–Feb sessions "raw JSONL has since rotated away" is false — those 136 sessions are on
**zbook**. Any single-machine count under-reports badly.

Raw sessions by month, map-reader (mtime, approximate):

| | Dec | Jan | Feb | Mar | Apr | May | Jun |
|---|--:|--:|--:|--:|--:|--:|--:|
| zbook | 10 | 66 | 60 | 11 | 6 | 2 | — |
| amd-tower | — | — | — | 14 | 17 | 8 | 19 |

**Consequence: everything is reconstructible from raw.** No recovery problem exists; this
is entirely a filing-and-visibility problem.

---

## 4. Error shape 1 — fragmentation across four locations

Map-reader session archives live in four places:

| # | Location | Entries | Distinct IDs |
|---|---|--:|--:|
| A | `cc-archives/map-reader-llm/` | 73 | 73 |
| B | `cc-archives/vlm-burial-mound-detection/` (top level) | 25 | 24 |
| C | `cc-archives/map-reader-llm/vlm-burial-mound-detection/` (nested) | 149 | 127 |
| D | `cc-archives/ANU-HUMN8031-2026/2026-04-28T02-55_incorporate-extends-pattern-and-map-reader/` | 1 | 1 |

Overlaps: **A∩C = 28**, **B∩C = 0**, **A∩B = 0**. Union of A/B/C = **196 distinct
sessions**.

**99 sessions exist only in C** — invisible to any catalogue or search that does not
descend into nested project directories. This is the same population already logged as
plan item **B6** ("257 metas live in nested locations the catalogue/sampling misses:
`map-reader-llm/vlm-burial-mound-detection` (149) …"), now confirmed and quantified at
the session level.

---

## 5. Error shape 2 — cross-project misfiling

One map-reader session is archived under the **ANU teaching project**
(`ANU-HUMN8031-2026/2026-04-28T02-55_incorporate-extends-pattern-and-map-reader`). It has
a complete entry (`session.jsonl.gz`, `session.meta.json`, `subagents/`) — it is filed,
just filed in the wrong project.

Operational consequence: **project-scoped search is unsound.** Any retrieval that filters
by project before searching can miss sessions belonging to that project. This is why the
archive ID set in §2 was built corpus-wide.

---

## 6. Error shape 3 — double archiving with divergent titles

Within location C alone: **22 session IDs appear twice, covering 44 directories.** The
duplicates share the session ID and timestamp prefix but carry *different
auto-generated slugs* — the archiver ran more than once over the same session and
re-titled it each time. Examples:

| Session | Directory 1 | Directory 2 |
|---|---|---|
| `a6efc880…` | `2026-04-18T00-17_resolve-git-sync-issues-and-clear-stale` | `2026-04-18T00-17_resolved-git-push-pull-conflicts-across` |
| `6ec37611…` | `2026-05-06T14-41_audit-and-patch-documentation-before-paper` | `2026-05-06T14-41_draft-documentation-audit-plan-and-reconcile` |
| `fd093096…` | `2026-05-04T04-54_complete-phase3a-verifier-completeness` | `2026-05-04T04-54_phase-3a-verifier-recovery-and-tier` |
| `1e573189…` | `2026-03-28T05-45_complete-multi-buffer-evaluation-and` | `2026-03-28T05-45_1e573189` |

Corpus-wide: **77 of 727 session IDs are archived more than once** (804 entries for 727
sessions).

Consequence for the audit: **entry counts overstate coverage**, and a search may return
two divergently-titled copies of one session, of which the metadata may differ.

---

## 7. Error shape 4 — the genuine gap

> **CORRECTION (2026-07-28, later session — backfill run).** The 224 figure and the
> table below **overcount, by 147**. Two filters were missing; the corrected count of
> sessions actually warranting a backfill is **77**. Details in §7a. The table below is
> left unedited as the original record; read §7a before using any number in it.

**224 raw sessions have no archive entry anywhere** (of 951 distinct raw sessions across
both machines). By cwd-key:

| Count | Project key |
|--:|---|
| 55 | `-media-shawn-…-synology-Adela-TRAP-WD-2020-04` (external drive) |
| 27 | `-home-shawn-Code-fieldmark-docs-staging` |
| 24 | `-home-shawn-personal-assistant` |
| 23 | `-home-shawn-Code-llm-reproducibility` |
| **19** | **`-home-shawn-Code-map-reader-llm`** |
| 16 | `-home-shawn` (home directory as cwd) |
| 14 | `-home-shawn-Code-trap-extraction` |
| 13 | `-home-shawn-Code-2026-mq-llm-dh-judgement-paper-b` |
| 8 | `-home-shawn-Code-LLM-History-Paper` |
| 6 | `-home-shawn-Code-ANU-HUMN8031-2026` |
| 5 | `-home-shawn-Code-vivienne` |
| 4 | `-home-shawn-Code` (code parent as cwd) |
| 3 | `-home-shawn-gemma-project` |
| 2 | `-home-shawn-Code-inscriptions` |
| 1 each | Groundsite-EFN-Planning, ANU-…-canvas-materials, FAIMS3, teaching-HUMN8031-2026-S1, client-materials |

### The 19 un-archived map-reader sessions (audit-relevant)

Dates from JSONL content, not mtime:

| Session date | ID | Machine |
|---|---|---|
| 2026-02-04T23:50 | `17559ba7…` | zbook |
| 2026-02-05T07:15 | `8a15785c…` | zbook |
| 2026-02-06T06:25 | `eef9732a…` | zbook |
| 2026-02-07T06:57 | `914fc177…` | zbook |
| 2026-02-07T07:33 | `43aa025a…` | zbook |
| 2026-02-11T11:54 | `c25acef1…` | zbook |
| 2026-02-12T07:26 | `bdc64cbe…` | zbook |
| 2026-02-12T07:26 | `c41eea22…` | zbook |
| 2026-02-13T23:05 | `214a2b5c…` | zbook |
| 2026-02-14T05:11 | `cb043866…` | zbook |
| 2026-02-15T11:57 | `d34910a0…` | zbook |
| 2026-02-15T14:15 | `0cc38455…` | zbook |
| 2026-03-08T11:34 | `363e3b73…` | zbook |
| 2026-03-09T23:14 | `a87a5a23…` | zbook |
| 2026-03-17T06:16 | `a577a9d7…` | zbook |
| 2026-04-20T02:06 | `57c157e2…` | amd-tower |
| 2026-05-28T12:02 | `5e3de346…` | amd-tower |
| 2026-07-02T04:17 | `07ad22f7…` | zbook |
| 2026-07-27T02:32 | `64b33adf…` | amd-tower |

**Twelve form a contiguous 4–15 February cluster.** Sixteen of the nineteen exist only on
zbook — so an amd-tower-only re-archive would recover three of them and silently miss the
rest. The 2026-07-27 entry is yesterday's and may simply not have been archived yet.

---

## 7b. The gap, corrected: 224 → 77 (backfill session, 2026-07-28)

Re-derived from the same snapshot with the same method, immediately before spending on
the backfill. Every subtraction below is reproducible from
`~/backups/claude-raw-transcripts-2026-07-28/` and `~/cc-archives/`.

| Step | N | Why |
|---|--:|---|
| Gap entries at re-derivation | 223 | 951 raw − 728 archived |
| − subagent transcripts | −75 | `agentId` + `isSidechain: true` + a *parent* `sessionId` |
| − below the substance floor | −71 | distilled transcript < 1,000 tokens |
| **Backfillable sessions** | **77** | 4,705,367 distilled tokens |

**224 → 223.** Not a discrepancy: the session that produced this document archived
itself at its own `/handoff` (`archived_at 2026-07-28T17:22:34`, filed as
`personal-assistant/2026-07-27T03-04_consolidate-map-reader-archives-run-5-arm`).

**The 75 subagent transcripts.** §2's method excludes the `subagents/` *directory*, but
agent transcripts also sit at the **top level** as `agent-*.jsonl`, and those were
counted as sessions. They are not sessions: each carries an `agentId`, `isSidechain:
true`, and a `sessionId` pointing at its parent — they are archived *inside* the parent
entry, so they can never have an archive entry of their own. This wholly accounts for
two rows of the §7 table: the external drive (**55**, i.e. every one of them) and
`trap-extraction` (**14**, likewise every one). Neither row represents a missing session,
and the external-drive layout question those 55 appeared to raise does not exist.

**The 71 below the floor.** Verified by inspection, not assumed. A recurring extract of
*exactly* 64 tokens across unrelated projects looked like extractor failure; it is not.
Those transcripts contain a `mode` record, a `file-history-snapshot`, an injected
`attachment` (often ~55 KB, which is why raw byte size misleads), and a single
`<command-name>/clear</command-name>` or `/exit` — the only "user text" is the
local-command caveat boilerplate. The remainder are one- or two-turn exchanges
("can you pull this repo?"). The distiller is correct and the floor is doing its job.

**Disposition of the 71: skipped, deliberately** (Shawn, 2026-07-28). They stay
un-archived. This is recorded here so a future source↔destination reconciliation check
(§9.5) does not re-flag them as a gap: **archive ⊊ raw is the intended steady state**,
and the floor is the reason. A reconciliation check should compare against
*substantive* raw sessions, not all raw sessions, or it will report 71 false positives
forever.

**Turn count is not a substance proxy.** `bulk-archive.py` filtered triviality on
`--min-turns 5`, which discarded **56 of the 77** — including a 205,848-token
`llm-reproducibility` session with **two** turns, and 15 others above 50,000 tokens. One
long analytical exchange is a single turn, so the turn test drops exactly the sessions
whose metadata is most worth having. Replaced with `--min-content-tokens`, measured on
the distilled text.

**Corrected breakdown of the 77** (`project.name` as filed):

| n | Project | | n | Project |
|--:|---|---|--:|---|
| 19 | fieldmark-docs-staging | | 2 | gemma-project → `_legacy/` |
| 12 | personal-assistant | | 2 | Code → `_legacy/` |
| 10 | llm-reproducibility | | 2 | LLM-History-Paper |
| 8 | map-reader-llm | | 1 | inscriptions |
| 8 | 2026-mq-llm-dh-judgement-paper-b | | 1 | client-materials |
| 6 | shawn → `_legacy/` | | 1 | Groundsite-EFN-Planning |
| 3 | ANU-HUMN8031-2026 | | 1 | FAIMS3 |
| | | | 1 | vivienne |

**theseus-ship contributes zero.** Its 60 entries and LLM-History-Paper's 12 already sit
in a single `LLM-History-Paper/` directory; the split is the `project.name` *field*, not
the location — an archive-side question this backfill does not touch, consistent with
Shawn's ruling that the fragmentation is user confusion over repo boundaries, not a
rename. LLM-History-Paper's 8 gap sessions reduce to **2** above the floor.

**Machine skew — the operational trap.** **55 of the 77 exist only on zbook.** Discovery
run against amd-tower's live `~/.claude` would have archived 22 of 77, including 1 of
map-reader's 8, and reported success. `bulk-archive.py` hardcoded `~/.claude/projects`
with no override; it now takes `--source-root` and detects the merged-snapshot layout.
**Raw-first is not a preference here, it is a correctness requirement.**

**Audit relevance (map-reader).** 19 gap sessions → 8 substantive. Seven fall in the
contiguous 4–15 Feb cluster (~373K distilled tokens); the eighth is 2026-07-27. Every
map-reader gap session from March onward is below the floor.

### 7d. theseus-ship resolved: succession, not rename (2026-07-28, later session)

The `LLM-History-Paper/theseus-ship` fragmentation was earlier deferred as "user confusion
over repo boundaries". Checked against the repos themselves, it is neither confusion nor a
rename — it is a **succession of three separate repositories**, and the archive nesting was
an archiving artefact reflecting no filesystem or git relationship.

| Repo | Remote | Sessions | Date range |
|---|---|--:|---|
| `theseus-ship` | `saross/theseus-ship` | 60 | 2025-12-05 → 2026-02-03 |
| `LLM-History-Paper` | `Denubis/LLM-History-Paper` | 14 | 2026-03-06 → 2026-04-23 |
| `2026-mq-llm-dh-judgement-paper-b` | own | 30 | 2026-04-25 → 2026-07-27 |

Evidence: both repos exist on disk with **different GitHub owners** (LLM-History-Paper is
Brian's), both are live (last commits 2026-07-01 and 2026-07-28), neither contains the
other as a subdirectory, and every session records its own repo root as `cwd` — never a
nested path. **The date ranges are contiguous and non-overlapping**, which is the signature
of sequential repos, not of a rename or a fork.

**Resolution (Shawn): promote, do not collapse.** `LLM-History-Paper/theseus-ship/` →
top-level `theseus-ship/`. All 60 entries already carried `project.name: theseus-ship`
unanimously, so this was a directory move with **zero metadata edits** — the identity was
already correct, only the placement was wrong. Collapsing the two would have destroyed a
real distinction, including which collaborator's repository the work happened in.

Effect: `CATALOG.json` 739 → **799** entries, uncatalogued 95 → **47**. All 60 verified
present, catalogued, and with transcripts intact after the move.

**The remaining 47 are all under `_legacy/` and should stay there.** That nesting is
deliberate — it is the established location for sessions launched outside a project tree —
so the fix is B6 (make the catalogue builder recurse), not more moves. Distinguish the two
cases: `theseus-ship` was a real project *accidentally* nested; `_legacy/Code` and friends
are *intentionally* nested and merely invisible to a depth-2 indexer.

### 7c. Backfill outcome (same session)

**Archived: 77 of 77, zero failures**, 146 subagents alongside. Ten entries were
relocated to `_legacy/{shawn,Code,gemma-project}/` to match existing precedent rather
than opening new top-level directories.

**Enriched with Terra: 80 of 83** (the 77 plus 6 pre-existing unenriched archives that
also clear the floor, minus 3 blocked). **Actual cost $8.45** against an $8.58 estimate;
the chars/4 × 1.11 calibration held to 1.5%.

**Three sessions were refused by OpenAI's content filter** (`invalid_prompt`, "Request
blocked") and remain unenriched: `6dacb961`, `f6b6552b`, `176e00cb`, all under
`_legacy/shawn/`. Their content is entirely benign — locating an Ollama Modelfile for
`gpt-oss:20b`, editing it in place, and inventorying ten locally installed models for
archaeology and digital-humanities research. The likeliest trigger is the local-model /
Modelfile subject matter. **This is a standing cost of a third-party extractor over a
corpus about LLM experimentation**, which is a substantial share of this one: budget for
a small refusal rate (here 3.6%) and a fallback provider, and note that the failure is
deterministic, so retrying is pointless. The adapter now surfaces the API's own
`code` rather than a bare `HTTP 400`, which is what made this diagnosable at all.

**Validator gate: 6 errors → 1**, and the survivor is a true positive that needs no
regeneration. Of the six `tag-project` errors, four were cross-reference tags on sessions
that *also* carried their own project tag (a time-tracking session naming the projects
whose hours it logged; a standup naming the paper it protected time for), and one was the
Fieldmark/FAIMS3 synonym. Both were validator gaps, now fixed: severity turns on whether
the session's own project tag is present, per the check's own stated harm, and
`fieldmark-docs-staging ↔ faims3` is aliased like `map-reader-llm ↔
vlm-burial-mound-detection`. The remaining error, `922bf6ff`, is **not a metadata
defect** — the metadata correctly describes a personal-assistant standup; the session was
merely *launched* from `~/Code/ANU-HUMN8031-2026` and is archived there. That is error
shape 2, and relocating it is a deliberate migration decision, not a validator fix.

**Catalogue rebuild is depth-2 only — B6, now measured exactly.** After
`verify --fix-catalogue`, `CATALOG.json` holds 739 entries: precisely the number of
`session.meta.json` files at depth 2. All 267 nested metas (246 at depth 3, 21 at depth
4) are invisible to it, leaving **95 on-disk sessions uncatalogued**, chiefly
`LLM-History-Paper/theseus-ship` (59) and the `_legacy/` subtree. Consequence for this
backfill: the 10 entries relocated into `_legacy/` are archived but uncatalogued until
B6 is fixed. Following precedent was still right — retrieval is raw-first and the
catalogue is a derived index — but the trade is real and should not be rediscovered.

**Postgres re-index deliberately NOT run.** `verify` recommends
`sync-sessions-to-postgres.py --full-resync`, but the B7 indexer defect
(`scripts/index-session-content.py:105`) is still unfixed, so a re-index now would bake
the role mislabelling back into `session_chunks`. Re-index after B7, not before.

---

## 7a. Error shape 5 — role mislabelling is an INDEXER defect (B7, characterised)

Measured in the parallel map-reader session, 2026-07-28; mechanism **re-verified at
source in this session**.

**Magnitude:**

- **40.0% of indexed `user` chunks are not Shawn's words** (95% CI 37.1–42.9%; n = 1,000
  sampled without replacement from the full 12,748-row population, each resolved back to
  its source record).
- **87.5% of `user` chunks over 2,000 characters are machine-generated** (n = 400). A
  long, articulate "user" turn is roughly **seven times more likely to be machine text
  than Shawn's**.
- Composition of the false-`user` population: `isMeta` **41.2%**, compact summaries
  **25.0%**, subagent task-notification reports **20.0%**.
- The `assistant` role is clean (399/400). **The defect is one-directional.**

**Mechanism — confirmed at source, not inferred.** `scripts/index-session-content.py:105`:

```python
role = (record.get("message") or {}).get("role") or record.get("type")
```

`type: "user"` is the JSONL **transport envelope** for every non-assistant record. When a
record carries no `message.role` — meta records, compact summaries, task notifications —
the `or record.get("type")` fallback silently promotes the envelope to a speaker
attribution. `assistant` records always carry `message.role`, which is why the error runs
one way only.

**Where the defect is NOT:** the raw JSONL is correct. `type: "user"` is accurate *as a
transport envelope*; the indexer over-reads it as authorship. So this is neither an
archive-time nor a raw-data problem — **the archives and raw transcripts are sound, and
the index built over them is not.**

**Candidate fix (not implemented — Thursday):** drop the `or record.get("type")`
fallback. Records without `message.role` are not conversational turns; either skip them
or classify them explicitly (`meta`, `summary`, `task-notification`) rather than
defaulting them to `user`. The three named categories account for 86.2% of the false
population, so explicit classification is tractable.

**Downstream blast radius — everything that consumed role attribution is suspect:**

1. **Memory extraction.** If extraction attributed statements by role, some memories may
   record Claude's words as Shawn's. Given the 87.5% figure for long turns — and that
   long articulate turns are exactly what extraction favours — this is the highest-risk
   consumer, not the lowest.
2. **`/search-sessions`** — role-filtered searches return misattributed hits.
3. **The 40-entry Three Ps audit** scored an *attribution* dimension against data that may
   itself have been misattributed.

**Immediate operational rule for the map-reader audit: do not filter or attribute by
role.** Search content corpus-wide and read the surrounding record to establish
authorship. This is a further argument for §9's raw-first retrieval, which does not
depend on the index at all.

---

## 8. Not yet characterised
- **Whether the same four-location fragmentation affects other projects.** The
  `_legacy/` (48 entries) and nested-location patterns suggest yes, but only map-reader
  has been examined at session level.
- **Metadata divergence between duplicate entries** (§6) — where a session is archived
  twice, the two `session.meta.json` files may disagree. Not compared.

---

## 9. Implications

1. **This is a visibility problem, not a loss problem.** Raw ⊇ archive (§3.3), and both
   raw stores are now snapshotted. Nothing needs recovering; things need finding.
2. **Any count derived from the catalogue under-reports**, because the catalogue misses
   nested locations. The earlier "April = 0 archived" figure is the worked example. Treat
   all prior coverage statistics as suspect until recomputed corpus-wide.
3. **Project-scoped search is unsound** (§5) — searches must run corpus-wide, then filter.
4. **For the audit specifically:** grounding is more available than feared. The blocker is
   unified retrieval across four archive locations plus both machines' raw stores — not
   recovery, and not a pipeline fix.
5. **For Thursday's class-fix:** the target is now specified rather than symptomatic. A
   source↔destination reconciliation check (the same fix shape already identified for the
   memory JSONL) would have caught the gap sessions and all 77 double-archives at the
   moment they occurred. **Two design constraints, learned from §7b:** it must compare
   *substantive* sessions only (top-level `agent-*.jsonl` are not sessions, and sessions
   below the distilled-token floor are skipped by design), and it must read the **union
   of both machines' raw stores** — a single-machine check would have reported the archive
   complete while 55 of 77 sessions were missing.
6. **The catalogue must never be the dedup key.** On 2026-07-28 `CATALOG.json` held 539
   entries against 728 session ids on disk. `bulk-archive.py` deduplicated discovery
   against the catalogue, so a backfill run would have **re-archived 189 already-archived
   sessions** — manufacturing precisely the double-archiving-with-divergent-titles defect
   of §6. Discovery now walks `session.meta.json` on disk; the catalogue is a derived
   index, regenerated by `verify --fix-catalogue`.
