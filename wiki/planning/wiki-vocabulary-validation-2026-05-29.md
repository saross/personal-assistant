---
title: "Wiki tag-vocabulary validation against the memory corpus"
tags: [memory-system, index, audit-pattern]
created: 2026-05-29
updated: 2026-05-29
status: active
---

# Wiki tag-vocabulary validation (2026-05-29)

**Workstream D, item #1** (memory-system rethink + wiki formalisation):
empirically validate / refine the 24-tag wiki vocabulary
(`notes/_tags.md`, drafted 2026-05-18) against what actually recurs in
the memory corpus and the `notes/_inbox.md` candidate backlog. This is
the prerequisite that grounds item #2 (extending `/weekly-review` with a
cluster-and-carry curation step).

**Status of the recommendations below:** *analysis only.* Per
`notes/_tags.md` ("New tags happen at `/weekly-review` curation time,
not in arbitrary sessions"), the add / drop / merge proposals here are
**pending ratification at the next `/weekly-review`**. Nothing in the
vocabulary has been changed by this pass.

## Method

- **Inputs:** `data/memories/memories.jsonl` (29,248 records,
  2025-11-20 → 2026-05-29); `notes/_inbox.md` (33 wiki-page candidates);
  the 24 wiki tags in `notes/_tags.md`; frontmatter tags on the 6
  currently-tagged wiki/notes pages.
- **Script:** `scripts/analyse-wiki-vocabulary.py` (reproducible;
  re-runnable for `/weekly-review`). It reports all-time and
  90-day-recency `research_tags` frequencies, per-wiki-tag corpus
  support via a documented keyword-expansion map (`WIKI_TAG_EXPANSIONS`),
  and top co-occurring pairs. Gap-cluster sums below come from a direct
  substring sweep over the same corpus.
- **Anchor:** all counts are re-derivable by running the script against
  the corpus file at the commit recorded alongside this doc.

### Caveat that governs every number

The corpus auto-tag vocabulary and the wiki vocabulary **measure
different things.** The corpus head is dominated by *project-execution
substance* — `data-pipeline` (1410), `documentation` (1136),
`reproducibility` (1128), `validation` (1008), `batch-processing` (513),
`preregistration` (368) — which belongs in **per-project continuity**,
not the cross-project craft wiki. The wiki vocabulary correctly has no
tag for `data-pipeline`; that is the "candidate pool ≠ surfacing layer"
design working as intended. Consequence: the per-wiki-tag support
percentages below are a **conservative floor** for the craft/meta
themes, because a craft memory is often auto-tagged with fine-grained
execution tags that the expansion map cannot see. Read the support
numbers as *relative* signal between wiki tags, not as absolute coverage.

## Headline findings

1. **Two well-attested cross-project themes have no wiki-tag home:**
   **agent-orchestration** (corpus cluster 913 usages / 327 tags; ~10
   inbox candidates) and **infrastructure / ops** (1023 usages / 417
   tags; ~5 inbox candidates). These are the strongest add candidates.
2. **Two tag pairs are genuine redundancies** created by the
   four-grouping structure: `memory-system` ≡ `memory-systems`, and
   `three-Ps` ⊂ `provenance`. Merging each frees budget for the two
   adds, leaving the count at 24.
3. **Five artefact-kind tags are near-unused** (`claude-md`,
   `scratchpad`, `hooks`, `index`, `skills`) but are *forward-looking
   scaffold* by design — keep, with a cut-review trigger at the next
   `/retro` if still unused.
4. **Two real tagged pages already drift** from the vocabulary — the
   vocabulary is not yet being applied consistently even on the handful
   of pages that carry frontmatter tags.

## Per-tag verdict

Support = memories whose `research_tags` match the tag's expansion map
(all-time; % of 29,248-record corpus). Verdict columns:
**keep** / **thin** (forward-looking scaffold, low support, watch) /
**merge** / **add**.

| Wiki tag | Support | % | Verdict |
|---|---:|---:|---|
| coding-practices | 3813 | 13.0% | keep — top theme |
| llm-craft | 2797 | 9.6% | keep |
| research-methodology | 2435 | 8.3% | keep |
| teaching | 1695 | 5.8% | keep (rubric/assessment/pedagogy/course — real) |
| bidirectional-verification | 1588 | 5.4% | keep |
| open-science | 1407 | 4.8% | keep |
| prompts | 1305 | 4.5% | keep |
| agents | 1293 | 4.4% | keep — but scope it to artefact *design* (see add) |
| audit-pattern | 714 | 2.4% | keep — **broaden gloss** to absorb quality-gates/pre-launch |
| provenance | 508 | 1.7% | keep — gloss already names Three Ps |
| memory-system | 417 | 1.4% | keep — **absorbs `memory-systems`** |
| working-practices | 395 | 1.4% | keep |
| anti-confabulation | 376 | 1.3% | keep |
| human-ai-collaboration | 279 | 1.0% | keep |
| skills | 235 | 0.8% | thin (scaffold) |
| memory-systems | 204 | 0.7% | **merge → memory-system** |
| hooks | 94 | 0.3% | thin (scaffold) |
| session-shape | 83 | 0.3% | keep — real cross-cutting theme; auto-tags rarely use the literal string |
| anti-satisficing | 54 | 0.2% | thin — keep (named pattern, distinct from anti-confabulation) |
| index | 34 | 0.1% | keep — used on real index pages |
| paper-seed | 13 | 0.0% | keep — but align usage (real page uses `paper-idea`) |
| scratchpad | 9 | 0.0% | thin (scaffold) |
| claude-md | 8 | 0.0% | thin (scaffold) |
| three-Ps | 7 | 0.0% | **merge → provenance** |

## Gaps — recurring themes with no wiki-tag home

### 1. agent-orchestration  *(recommend ADD)*

The single largest, most-repeated cluster in *both* evidence sources.

- **Corpus:** explicit `agent-orchestration` tag used **52×**, plus
  `proposer-verifier` (67), `orchestration` (29), `verifier-design` (32),
  `verifier-calibration` (38), `multi-agent-coordination` (20),
  `multi-agent` (8). Cluster sum **913 usages across 327 distinct tags.**
- **Inbox:** ~10 candidates explicitly name `notes/agent-orchestration.md`
  as the target page, e.g. *"P-V loops as an emerging architectural
  pattern"* (2026-05-24), *"dual-axis severity × failure_type rubric"*
  (2026-05-24), *"closed-loop-pairs-as-spec-extractors"* (2026-05-22),
  *"long-sapphire-job-orchestration"* (2026-05-26), *"multi-agent
  proposer → schema-check → verifier pipeline"* (2026-05-25).
- **Why `agents` doesn't cover it:** `agents` is an *artefact-kind* tag —
  "subagent design, briefing, evaluation." Orchestration is about
  *coordinating* agents (closed-loop proposer-verifier contracts, iterate
  drivers, fan-out, file-ownership splitting). Distinct axis.
- **Recommendation:** add `agent-orchestration` to the craft-scaffolding
  grouping; keep `agents` for single-agent design. This is the
  one add that workstream H (the closed-loop pairs meta-workstream) has
  been waiting on — the inbox has flagged the page since 2026-05-22.

### 2. infrastructure / ops  *(recommend ADD)*

- **Corpus:** `infrastructure` (124), `deployment` (73),
  `archive-consolidation` (25), `backup-strategy` (18),
  `production-deployment` (15), `devops` (7), `rpi-server` (10),
  `ollama-deployment` (7), `mcp-server` (5), `compute-infrastructure` (8).
  Cluster sum **1023 usages across 417 distinct tags.**
- **Inbox:** ~5 candidates — *"mount-not-install"* (2026-05-20),
  *"multi-machine archive consolidation"* (2026-05-22),
  *"cc-archives-pipeline"* (2026-05-28), *"tmpfs inode exhaustion /
  sapphire-craft"* (2026-05-25), *"GitHub Projects v2 setup"* (2026-05-25).
- **Why `coding-practices` doesn't cover it:** it is the over-broad
  catch-all (13%); ops/infra (servers, mounts, archives, deployment
  topology, compute hosts) is a distinct concern from software
  engineering craft. Splitting it sharpens both.
- **Recommendation:** add `infrastructure` to the domain/topic grouping.

### 3. quality-gates / pre-launch discipline  *(recommend BROADEN `audit-pattern`, not add)*

- **Corpus:** `quality-gates`+`quality-gate` (22), `decision-gate` (19),
  `phase-gate`/`stage-gate`/`approval-gate`/`api-gate`/`budget-gate`/
  `pre-launch-*` (~30 more). Cluster ~197 across 113 tags.
- **Inbox:** the *"run `/audit` before a production sweep"* (2026-05-22),
  *"`/audit` post-ship"* (2026-05-23), *"production-vs-experiment config
  drift"* (2026-05-24), *"audit follow-ups as deliberate non-shipping
  artefact"* (2026-05-24) thread.
- **Recommendation:** do **not** add a tag — this overlaps `audit-pattern`
  heavily. Broaden `audit-pattern`'s gloss to: "adversarial review,
  claims inventories, bidirectional checks, **pre-launch / quality
  gates**." A `notes/quality-gates.md` page tagged
  `audit-pattern + coding-practices` covers the page-level need.

### 4. tool / OSS-evaluation and credential hygiene  *(recommend PAGES, not tags)*

- **Tool-eval corpus signal** is modest after removing `cross-*` noise:
  `tool-selection` (22), `tool-evaluation` (6), `open-source` (5).
  Inbox: compose-vs-fork, licence-awareness, registrar-version-DOI,
  multi-author-benchmark-scrutiny (~4 candidates).
- **Secrets corpus signal:** `credential-management` (14),
  `api-key-management` (9), `secrets-management` (7) — ~76 across 33 tags.
  Inbox: secrets-hygiene, zotero-integration (~2 candidates).
- **Recommendation:** these are real *page* candidates
  (`notes/tool-evaluation.md`, `notes/secrets-hygiene.md`,
  `notes/zotero-integration.md`) but do not warrant their own vocabulary
  tags. Tag them with existing `coding-practices` + `audit-pattern` /
  `working-practices`. Revisit at `/retro` if a fourth or fifth page
  accumulates under either theme.

## Redundancies to merge

| Drop | Keep | Rationale |
|---|---|---|
| `memory-systems` (0.7%) | `memory-system` (1.4%) | Same concept, split only by the craft-scaffolding vs cross-cutting groupings. Corpus uses one string (`memory-system`, 117). |
| `three-Ps` (0.0%) | `provenance` (1.7%) | `provenance`'s own gloss is "RDA IG Three Ps (Prompt, Process, Provenance)" — co-extensive. *Lower-confidence merge:* `three-ps` is used on one real page (the open-science CoT-capture page); that page would re-tag to `provenance`. Keep `provenance`'s gloss naming Three Ps explicitly. |

## Net budget effect

ADD 2 (`agent-orchestration`, `infrastructure`) − MERGE 2 (`memory-systems`,
`three-Ps`) = **24 tags, unchanged.** Comfortably within the stated 20–30
budget, with the redundancy removed and the two largest gaps closed.

## Real-page drift (apply at curation, mechanical)

Only 6 wiki/notes pages currently carry frontmatter tags; 2 of them
drift from the vocabulary:

1. `notes/general/2026-03-15-persona-affordance-design-paper-seed.md` —
   tags `[persona-affordance-design, human-ai-collaboration,
   research-methodology, paper-idea]`. `persona-affordance-design` is a
   one-off content tag (not vocabulary); `paper-idea` should be
   `paper-seed` (the vocabulary spelling, which the filename already
   uses).
2. `wiki/docs/open-science/cot-capture-claude-code-investigation-2026-05-19.md`
   — tags `[open-science, rda-ig, three-ps, reasoning-traces,
   claude-code, agent-observability, fair, ro-crate]`. Only `open-science`
   and `three-ps` are vocabulary tags; the other six are corpus-style
   fine tags. Recommend re-tagging to vocabulary terms, e.g.
   `[open-science, provenance, agents]` (provenance absorbing
   `three-ps`/`fair`/`ro-crate`; `agents` for `agent-observability`).

These are mechanical fixes for `/weekly-review` curation, after the
add/merge decisions are ratified.

## Recommended actions for the next `/weekly-review`

1. Ratify ADD `agent-orchestration`, `infrastructure`; MERGE
   `memory-systems` → `memory-system`, `three-Ps` → `provenance`.
2. Broaden `audit-pattern` gloss to include pre-launch / quality gates.
3. Record the four changes in `notes/_tags.md` "History" with this doc as
   the evidence anchor; update the grouping counts.
4. Apply the two real-page re-tags above.
5. Cluster the 33 inbox candidates into the (now-updated) vocabulary as
   the first live exercise of the item-#2 cluster-and-carry step — the
   biggest pre-formed cluster (`agent-orchestration`, ~10 candidates) is
   ready to become `notes/agent-orchestration.md`.
