# Research-code review & FAIR4RS uplift — assessment

**Status:** assessment complete; **work deferred** (Shawn, 2026-07-03) —
single-threading Paper B; pick up post-Paper-B or as dedicated out-of-hours
time. Backlog row added 2026-07-03 (`tasks/backlog.md`).
**Created:** 2026-07-03, from a session prompted by the Fable-on-Max
availability window (Shawn hoped to use it for a general code uplift; the
work proved more entailed than a drive-by).
**Owner:** Shawn.

## The task

Review and improve the research code in `~/Code/inscriptions`,
`~/Code/map-reader-llm`, and other active repos: find and fix bugs, improve
efficiency/elegance, and implement best-practice FAIR for Research Software
(FAIR4RS — Findable, Accessible, Interoperable, Reusable) tooling.
Constraint: **both lead repos have completed analyses entering write-up; the
code must keep reproducing the existing outputs.** This is a recurring task
class, so the deliverable includes durable, reusable tooling — not just two
uplifted repos.

## Stock-take (verified 2026-07-03)

**No FAIR4RS skill or agent exists yet.** Shawn half-remembered starting one;
the sweep (grep for `fair4rs` across `~/Code`, `~/.claude`,
`~/personal-assistant`) found no skill, but three near-misses that between
them contain all the parts:

| Asset | What it is | What to lift |
|---|---|---|
| `~/Code/trap-extraction/` (Nov–Dec 2025) | Manual FAIR4RS uplift of a completed project: `STANDARDS-COMPLIANCE.md`, `DATA-DICTIONARY.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CITATION.cff` | The **output template** — esp. `STANDARDS-COMPLIANCE.md` structure (FAIR data + FAIR4RS software sections, pragmatic-compliance framing, limitations register) |
| `~/Code/map-reader-llm/` | Already had a FAIR4RS pass (`docs/planning/future-work.md` marks "FAIR4RS Compliance" `[x]`) | Second exemplar; proves the pass was done by hand twice without being codified |
| `wiki/planning/paper-review-skill-spec.md` (draft 2026-07-01, **untracked** as of 2026-07-03 — owned by the Paper B §2 session, left uncommitted here) | Fresh-context review panel for *prose* | The **architecture**: fresh-context subagent panel, evidence-anchored findings (no anchor → not a finding), deterministic severity aggregation |
| `~/Code/2026-mq-llm-dh-judgement-paper-b/scripts/workflows/adversarial-review-s3.mjs` | Working Workflow prototype (multi-lens sceptic panel) | The executable skeleton |
| `~/Code/llm-reproducibility/.claude/skills/reproduction-assessor/` + `research-assessor/` | Reproduction-assessment skills | Fresh-context independence framing; "if it's not in the artefact, it doesn't count" |
| PA agents `lit-scout`/`lit-scout-verifier`, `data-profile-proposer`/`-verifier` | House proposer–verifier pairs | The pattern the new skills should follow |

Note the sibling-but-distinct plan:
`~/Code/theseus-ship/planning/agentic-tooling-build-plan.md` (2026-07-01) is
producer/verifier loops for the software-longevity *study* (tool discovery /
documentation / evidence-of-life) — different target, same architectural
family. Don't merge them; do share the skeleton.

### Repo readiness (better than feared)

- **inscriptions:** `uv.lock` + `pyproject.toml`, `CITATION.cff`,
  `codemeta.json`, `LICENSE`, `PROVISIONING.md`, per-run frozen code dirs
  (`runs/<date>-<hypothesis>/code/`) with run-local tests. Run-centric layout
  is good for reproducibility, but review means reviewing many run-local code
  variants.
- **map-reader-llm:** full apparatus — `pyproject.toml`, `uv.lock`,
  `requirements-lock.txt`, `pytest.ini` + real `tests/` suite, `ruff.toml`,
  `CITATION.cff`, `codemeta.json`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`,
  dual licences.
- **Liability, both repos (as of 2026-07-03):** untracked output dirs in the
  working trees —
  `inscriptions/runs/2026-06-18-h9-letter-mass-h3a/data/processed/` and
  `map-reader-llm/outputs/55maps-text-min-n10-uplift/proposer-all/`. Resolve
  (commit or archive) before any freeze tag.

## Recommended approach: freeze first, improve behind a harness

The constraint ("must reproduce existing outputs") and the goal ("fix bugs")
are in tension — a real bug fix *changes outputs*. Resolve it by making
reproducibility a **tested property** before touching anything.

### Layer 0 — freeze & verify (per repo; small; on the write-up critical path)

1. Resolve untracked outputs, then **tag the exact state** that produced the
   paper's numbers (e.g. `analysis-freeze-2026-07`). Zenodo Digital Object
   Identifier (DOI) at submission time.
2. Build a **golden-output regression harness**. Key design point for large
   language model (LLM) research code: split the pipeline into *stochastic
   generation* (LLM calls — frozen artefacts, never re-run for repro) and
   *deterministic analysis* (stats, joins, figures from stored
   intermediates — cheap, re-runnable, diffable against committed outputs).
   The harness only needs to cover the deterministic half.

The green tick licenses everything downstream.

### Layer 1 — review & fix (behind the harness)

- Multi-lens adversarial panel (correctness, statistics, data handling,
  efficiency) with fresh-context verifiers — Paper B's own architecture
  pointed at code.
- **Rule:** output-preserving refactors are free (harness-gated);
  output-changing fixes are *findings* — logged, decided explicitly; if one
  changes a paper's numbers, that is a write-up event, not a silent commit.
- Weighting: correctness and reproducibility high; "elegance" refactoring of
  completed analyses is the lowest-value item — defer beautification.

### Layer 2 — FAIR4RS uplift (additive, low-risk, any time)

Releases, Zenodo DOIs, README repro sections, data-availability statements,
CHANGELOG, registry entries. Both lead repos are mostly there; an audit finds
the gaps.

## The durable artefact: two skills, not one monolith

Home: `personal-assistant` (house pattern — skill + helper script +
independent verifier; publish via `published/` when polished).

1. **`fair4rs-audit`** — a deterministic helper script does the checkable
   parts (CITATION.cff parses; codemeta.json is valid; lockfile exists;
   LICENSE is SPDX-identifiable; tags/DOI present; README has
   install/run/repro sections); LLM judgement only for the qualitative
   residue. Output: gap table + prioritised plan, modelled on
   trap-extraction's `STANDARDS-COMPLIANCE.md`.
2. **`research-code-review`** — codifies freeze → harness → panel → verify,
   lifting evidence anchors + deterministic aggregation from the paper-review
   spec and the `adversarial-review-s3.mjs` skeleton.

**Build order (build-one, codify, apply):** do inscriptions *manually* first;
codify what generalised into the skills; run the skills on map-reader as
their first real test; iterate. Do not build the skills in the abstract.
Passes the 3-use heuristic: inscriptions, map-reader, llm-reproducibility,
LLM-History-Paper, trap-extraction (re-audit) are all queued behind it.

## Sequencing & accountability

- Focus slots at assessment time: Paper B §3 edit; Cosmos grant. This work is
  neither — deferred accordingly.
- **Layer 0 is genuinely on the write-up critical path** (repro package for
  JAMT submission and map-reader write-up) and small; it can run as an early,
  bounded step when the write-ups resume.
- Layers 1–2 + skill build: dedicated time, post-Paper-B or out-of-hours.
  Related backlog rows to coordinate with: "Revive the 'Theseus' ship'
  paper" (shares the producer–verifier skeleton) and "Re-implement tool
  discovery/documentation/evidence workflows in modern scaffolding".

## Resumption checklist

- [ ] Re-read this doc + the paper-review spec
      (`wiki/planning/paper-review-skill-spec.md` — confirm it got committed;
      it was untracked on 2026-07-03).
- [ ] Resolve the two untracked output dirs (paths above; re-verify with
      `git status` — they may have moved on).
- [ ] Layer 0 on inscriptions: freeze tag + deterministic-half regression
      harness. Decide harness home (`tests/repro/`?) and runner (`pytest`
      golden-file comparison is the obvious default).
- [ ] Manual review pass on inscriptions (multi-lens; findings
      evidence-anchored; output-preserving vs output-changing split).
- [ ] Codify → `fair4rs-audit` + `research-code-review` skills; first real
      run on map-reader.
- [ ] Decide scope of "other active repos" (llm-reproducibility,
      LLM-History-Paper, blue-mountains, fieldmark-docs-staging, …) — audit
      order by write-up proximity.

## Open questions

- Harness form for inscriptions' per-run layout: one harness per run dir, or
  a top-level runner that sweeps `runs/*/`?
- Verifier model family: same as producer vs deliberately different (same
  question as the theseus-ship plan; answer once, share).
- Zenodo integration: manual deposit vs GitHub–Zenodo webhook per repo.
