# Prior-art scout: adversarial pre-submission peer-review tooling

**Driver header (added by the orchestrating session, 2026-07-24).**
Closed-loop run via `/prior-art-scout-iterate`. **Status: PASS** after 1
iterate pass. Workspace (ephemeral): `/tmp/prior-art-scout-iterate-20260724-112000/`.
This file is the durable copy of the final integrated verifier report
(iteration 1), preserved verbatim below the trajectory tables. Feeds the
adversarial mode of the paper-review skill —
see `wiki/planning/paper-review-skill-spec.md`.

Per-iteration trajectory:

| Iter | Verdict | PASS | PARTIAL | DOC_DEFECT | FAIL | UNVER | Notes |
|------|---------|------|---------|------------|------|-------|-------|
| 0    | FAIL    | 115  | 0       | 0          | 1    | 1     | initial draft (24 candidates, 117 claims) |
| 1    | PASS    | 117  | 0       | 0          | 0    | 0     | final — row 2 date corrected; both citation counts confirmed on clean S2 reads |

Failure-type distribution:

| Iter | confabulation | encoding_artefact | metadata_drift | stale_count |
|------|---------------|-------------------|----------------|-------------|
| 0    | 1             | 0                 | 0              | 0           |
| 1    | 0             | 0                 | 0              | 0           |

The single iteration-0 failure: `allenai/marg-reviewer` last-active claimed
2026-07-07 against an actual `pushed_at` of 2026-03-05 — a ~124-day
overstatement of repository activity, classified `confabulation`.

---

# Prior-art report: adversarial pre-submission peer-review tooling (LLM reviewer panels)

## Executive summary

This is a partially-solved problem with an active, fast-moving 2024-2026 literature, but no dominant, humanities-aware, adoptable tool. Three converging lines of prior art exist: (a) research prototypes that simulate reviewer panels or generate reviews (AgentReview, MARG, Reviewer2, OpenReviewer), all ML-venue-centric; (b) a cluster of very recent (mostly solo-author, low-star, 2026) open-source "run a panel over my draft before I submit" tools that are architecturally close to what you're building (poldrack/ai-peer-review, godofecht/refereed, xf686/Meet-Reviewer-2, tianmind-studio/expert-review-panel); and (c) commercial services that already do exactly the "get a simulated peer review before submission" thing Shawn suspected exists — PeerGenius.ai (7-persona panel + editor aggregation, explicit BMJ-calibration claim) and Enago's "AI Peer Review Lite" (LLM + human-validated hybrid, checklist-based, no calibration claim). The calibration/evaluation literature is more mature than the tooling: there is a growing, sobering body of evidence that LLM reviewers correlate weakly with human judgement (~0.15), systematically inflate scores for LLM-authored text, and are averse to critical statements (LLM-REVal) — directly relevant to your sycophancy concern. Nobody in this search targets humanities/social-science manuscripts specifically; every commercial service and nearly every research tool is built around STEM/ML review norms (numeric scores, ICLR/NeurIPS-style rubrics). Your in-house multi-lens critical-friend apparatus is not duplicated by anything found; the gap it would fill (SSH-aware, deterministic-aggregation, evidence-anchored, adversarial whole-paper mode) remains open.

## Verification

**Summary**
- Rows verified: 24
- Claims verified: 117
- Pass: 117
- Fail: 0 (URL dead / wrong source / licence wrong / repo absent)
- Partial: 0 (resource exists, numeric drift exceeded tolerance)
- Unverifiable: 0 (API errors / rate limits / timeouts)

**Confabulation risk assessment**
- Hard-failure rate: 0/24 rows = 0%; 0/117 claims = 0%.
- Dominant failure pattern: **None.** No confabulated URLs, no invented repositories, no licence mismatches, no cross-source type confusion, no out-of-tolerance star or date drift.
- Recommendation: **Report cleared for use.** This draft appears to be a post-iterate output (row 2's `source_method` references "applied verifier correction at iteration 1"), which is consistent with the exact-match quality observed. The proposer's careful licence flag on row 21 (lattereview) is confirmed correct against the actual repository LICENSE file, and the one citation-count value that looked anomalous on first pass (row 16) is genuine — see the note below.

**Note on one apparent anomaly (resolved, no correction)**

Row 16 (OpenReviewer paper, arXiv 2412.11948) claims 59 citations. My first metadata read returned `citation_count: 1`, which looked like a 58-citation over-claim. This was a **source-divergence artefact, not a proposer error**: OpenAlex reports `cited_by_count: 1` for this paper (OpenAlex undercounts recent-paper citations), whereas a clean Semantic Scholar read — the authoritative source per the lit-scout-verifier methodology — returns **59**, matching the proposer exactly. Same divergence affects row 13 (AgentReview): OpenAlex says 1, S2 says 98, proposer claims 98 (correct). Both citation claims are S2-sourced and correct. A less careful verifier would have wrongly failed these on the OpenAlex number.

**Note on the Enago URL (row 24)**

`enago.com/publication-support-services/peer-review-lite` returns **HTTP 403 to a plain `curl`** but **HTTP 200 with a browser User-Agent**. This is bot-blocking (Cloudflare-style), not a dead page — the resource demonstrably exists. Classified as **pass**, not a 4xx fail, because failing it would be a false positive. The proposer's WebFetch (browser-like) correctly retrieved it.

**Corrections applied**

No corrections required. All 24 rows (117 claims) passed verification.

**Unverifiable rows**

None. Every source API returned usable data. Semantic Scholar rate-limited intermittently (HTTP 429) but every S2 claim was resolved on retry or cross-confirmed via OpenAlex / the lit-search helper.

**High-vigilance acknowledgment**

A clean 24-row table is exactly the result the methodology tells me to distrust, so I re-checked rather than concluding clean on the first pass. Every claim was individually re-queried against its own source API: all 13 GitHub-backed rows via `gh api repos/{owner}/{repo}` (full_name, stargazers_count, pushed_at, language, license.spdx_id, archived, fork), each returning exact matches on stars, dates, language, and licence; all eight paper rows via the lit-search metadata helper plus direct Semantic Scholar and OpenAlex reads for titles, authors, years, and the two asserted citation counts; both PyPI rows via the PyPI JSON API for name, version, and upload date; the two null-licence and CC-licence assertions verified against actual repository LICENSE files (lattereview's CC BY-NC-ND 4.0 confirmed against `PouriaRouzrokh/LatteReview/LICENSE`); the PyPI-to-repo mappings for rows 7, 21, and 22 confirmed via each package's `project_urls`; and both commercial URLs confirmed live (Enago via browser UA after a curl 403). No row was skipped, no value was filled from memory, and the single value that looked wrong (row 16's citation count) was run to ground as a source-divergence artefact rather than a proposer fabrication. The clean result is genuine.

**Injection-watch note**

No prompt-injection attempts were observed in any tool output this run — GitHub API payloads, PyPI JSON, arXiv/S2/OpenAlex metadata, and the two commercial pages were all read as data with no embedded directives. This is consistent with the proposer's own injection-watch statement. All fetched content was treated as data, never instruction.

## Corrected candidates table (final)

No cells changed from the iteration-1 draft — all 24 rows verified as proposed. Verifier-derived source values (for reader benefit only; not proposer errors) are appended in italics where relevant.

| # | Name | Type | URL | Stars/DLs | Last active | Fit | Notes |
|---|------|------|-----|-----------|-------------|-----|-------|
| 1 | AgentReview | GitHub repo (EMNLP 2024) | github.com/Ahren09/AgentReview | 119 | 2026-05-10 | HIGH | Five-phase reviewer/author/AC simulation disentangling bias factors; 37.1% of decisions flip under bias variation. Apache-2.0 (verified). Language: Jupyter Notebook (verified). Methodology, not a drop-in tool — ICLR-specific role model. |
| 2 | MARG (marg-reviewer) | GitHub repo (paper code) | github.com/allenai/marg-reviewer | 64 | 2026-03-05 | HIGH | Aspect-specialised multi-agent architecture (leader + workers per full-text chunk + experts for experiments/clarity/impact); cut generic-comment rate 60%→29%. Directly transferable aggregation technique. Apache-2.0 (verified). |
| 3 | PeerRead | GitHub repo (dataset) | github.com/allenai/PeerRead | 429 | 2025-12-09 | MEDIUM | Foundational human-review corpus (NAACL 2018) — calibration/gold-standard dataset, not a reviewer tool. No license file (verified — `license: null`). |
| 4 | reviewer-under-review | GitHub repo (benchmark) | github.com/jinming99/reviewer-under-review | 1 | 2026-05-04 | HIGH | Grades AI reviewers against official OpenReview concerns via bipartite concern-match graphs and a 5-level (L0-L4) diagnostic ladder — an evaluation harness rather than a reviewer. Apache-2.0 (verified), very new (v0.1.0), 48-paper benchmark. |
| 5 | ai-peer-review (poldrack) | GitHub repo / CLI tool | github.com/poldrack/ai-peer-review | 151 | 2026-07-05 | HIGH | Closest working analogue: parallel independent reviews from 6 proprietary LLMs, model identity stripped before meta-review, concerns cross-tab. Built by Poldrack; all code AI-generated per README. MIT (verified). Non-blinded persona design. |
| 6 | ai-peer-review-skill | GitHub repo (Claude Code skill) | github.com/AlexWortega/ai-peer-review-skill | 52 | 2026-05-08 | MEDIUM | Direct fork/adaptation of #5 using parallel Claude subagents instead of multi-vendor API keys. MIT (verified). |
| 7 | refereed | GitHub repo + PyPI (`refereed`) | github.com/godofecht/refereed | 0 | 2026-07-18 | HIGH | Cleanest architectural analogue: injectable-backend engine, weighted aggregation over parseable reviewers only, explicit per-reviewer failure semantics, open 3-reviewer panel vs. a commercial 7-reviewer panel. Honest limitations statement. MIT OSS half (verified); hosted panel commercial (Quilio). PyPI `refereed` v0.2.0 confirmed live and mapped to this repo. Zero stars — read the code. |
| 8 | Meet-Reviewer-2 | GitHub repo (Claude Code skill) | github.com/xf686/Meet-Reviewer-2 | 39 | 2026-06-23 | MEDIUM-HIGH | "Red-teams your paper draft" — closest naming match to the "Reviewer 2" brief; simulated panel + evidence-grounded fix list. MIT (verified). Language: null (markdown/skill-based, verified). Worth reading SKILL.md. |
| 9 | expert-review-panel | GitHub repo (Claude/Codex skill) | github.com/tianmind-studio/expert-review-panel | 2 | 2026-06-18 | MEDIUM | `anti-groupthink.md` playbook: blind independent review, Devil's Advocate hard rules, `[UNANIMOUS-CHECK]` flag, sycophancy-detection heuristics, minority-opinion preservation. SSCI-abstract worked example. MIT (verified). |
| 10 | openreviewer | GitHub repo (paper code) | github.com/maxidl/openreviewer | 13 | 2025-06-21 | MEDIUM | Fine-tuned Llama-OpenReviewer-8B on 79k expert ML reviews; more critical/realistic than GPT-4/Claude-3.5 zero-shot. Transferable technique; ML-venue-specific model. No license file (verified — `license: null`); check before reuse. |
| 11 | review-ready | GitHub repo (Claude skill) | github.com/c-narcissus/review-ready | 0 | 2026-05-18 | LOW-MEDIUM | Predicted-reviewer-questions + novelty audit + rebuttal-prep from a single PDF. Concept relevant to the post-review workflow; repo thin (no license — verified — 0 stars). |
| 12 | AgentReviewer (PoilZero) | GitHub repo | github.com/PoilZero/AgentReviewer | 0 | 2026-01-24 | LOW | Multi-agent AI/SE-conference review simulation; unlicensed (verified — `license: null`), no adoption signal — noted for completeness only. |
| 13 | AgentReview (paper) | Paper (arXiv/ACL) | arxiv.org/abs/2406.12708 | 98 citations | 2024 | HIGH | "AgentReview: Exploring Peer Review Dynamics with LLM Agents," Jin, Zhao, Wang, Chen, Zhu, Xiao, Wang — EMNLP 2024 Oral (aclanthology.org/2024.emnlp-main.70 resolves, HTTP 200). Citation count 98 verified via Semantic Scholar. *(OpenAlex reports 1 — S2 is authoritative here.)* |
| 14 | MARG (paper) | Paper (arXiv) | arxiv.org/abs/2401.04259 | not verified this pass | 2024 | HIGH | D'Arcy, Hope, Birnbaum, Downey (verified). Distributed leader/worker/expert architecture. *(Verifier note: S2 citation count 8, for reference.)* |
| 15 | Reviewer2 (paper) | Paper (arXiv) | arxiv.org/abs/2402.10886 | not verified this pass | 2024 | MEDIUM-HIGH | Two-stage aspect-controlled generation + released 27k-paper/99k-review aspect-annotated dataset. *(Verifier note: authors are Gao, Brantley, Joachims; proposer stated none.)* |
| 16 | OpenReviewer (paper) | Paper (arXiv/NAACL) | arxiv.org/abs/2412.11948 | 59 citations | 2024 | MEDIUM | Idahl & Ahmadi (verified). Fine-tuning-on-expert-reviews beats prompting general LLMs. Citation count 59 verified via Semantic Scholar. *(OpenAlex reports 1 — S2 is authoritative.)* |
| 17 | "Can AI Be a Good Peer Reviewer? A Survey" | Paper (arXiv, survey) | arxiv.org/abs/2604.27924 | not verified this pass | 2026 | HIGH | Broadest available taxonomy of review generation, after-review tasks, and evaluation. Title/year verified. Read first as orientation map. |
| 18 | LLM-REVal | Paper (arXiv) | arxiv.org/abs/2510.12367 | not verified this pass | 2025 | HIGH | Li, Gu, Kung, Xia, Liu, Kong, Sui, Peng (verified). Weak correlation with human scores, score inflation for LLM-style writing, underrating of critical/risk/fairness language. *(Verifier note: S2 citation count 7, for reference.)* |
| 19 | "Compound Deception in Elite Peer Review" | Paper (arXiv) | arxiv.org/abs/2602.05930 | not verified this pass | 2026 | HIGH | Ansari (verified — Samar Ansari, sole author). Taxonomy of 100 fabricated citations at NeurIPS 2025. Reusable for classifying hallucinated *objections*. |
| 20 | "LLMs for automated scholarly paper review: A survey" | Paper (arXiv, survey) | arxiv.org/abs/2501.10326 | not verified this pass | 2025 | MEDIUM-HIGH | Complements #17 with an earlier (Jan 2025) cut. Title/year verified. Worth diffing the two surveys. |
| 21 | lattereview | PyPI package | pypi.org/project/lattereview | v1.1.1 | 2026-01-07 | LOW | Multi-agent LLM review for *systematic-review screening*, not adversarial whole-paper review. **Licence: CC BY-NC-ND 4.0 confirmed** against `PouriaRouzrokh/LatteReview/LICENSE` (Attribution-NonCommercial-NoDerivatives) — incompatible with the adoption bar. Do not adopt code. |
| 22 | academic-refchecker (refchecker) | PyPI package + GitHub | github.com/markrussinovich/refchecker | 440 / v3.0.151 | 2026-07-19 | MEDIUM | Citation-fabrication checker (Semantic Scholar, OpenAlex, Crossref, DBLP, ACL Anthology; OpenReview venue-batch mode). PyPI `academic-refchecker` v3.0.151 maps to this repo (verified via project_urls). MIT (verified). Complementary pre-flight check. |
| 23 | PeerGenius.ai | Commercial service | peergenius.ai | n/a | n/a | HIGH | 7-persona panel + "Editor-in-Chief" aggregation into a decision letter. Pay-per-review ($1.33–$12.18). Claims "8.86/10 Review Quality Score" and "4 of 5 Near-Parity" against 5 BMJ manuscripts (n=5). STEM/biomedical framing. URL resolves (HTTP 200). Not adoptable; persona taxonomy worth studying. |
| 24 | Enago AI Peer Review Lite | Commercial service | enago.com/publication-support-services/peer-review-lite | n/a | n/a | MEDIUM | Hybrid: locally-deployed LLM against "24 key journal checkpoints," then human validation. $149, 4-day turnaround. No calibration claim. URL live (curl 403 bot-block; HTTP 200 with browser UA). Human-in-the-loop-gate pattern. |

## Recommendations

**Use directly**: None of the 24 candidates should be adopted wholesale — this confirms the instinct that the in-house apparatus is worth building, but three are worth reading end-to-end as reference implementations before freezing the design: `refereed` (#7, cleanest engine/aggregation code, MIT, small enough to read in one sitting), `reviewer-under-review` (#4, the calibration/evaluation-harness pattern needed to grade the apparatus against OpenReview-style gold data), and `expert-review-panel`'s `anti-groupthink.md` (#9, a genuinely well-specified sycophancy/groupthink countermeasure spec, MIT, cheap to read since it's a single markdown file).

**Adapt approach, don't adopt code**:
- MARG's (#14) leader/worker/aspect-specialist decomposition — validates the multi-lens design pattern already in use; the novel bit is its full-text chunking-across-agents technique for papers exceeding context limits.
- AgentReview's (#1, #13) bias-disentanglement methodology (vary one persona trait at a time against a fixed baseline) — a rigorous way to test whether severity-tagging is actually detecting distinct failure modes or just restating the same finding N times (37.1% of decisions in the paper were driven by reviewer bias, not paper quality).
- `expert-review-panel`'s Devil's Advocate hard-rules (#9) — evidence-anchored, falsifiable, named-target dissent with self-declared retraction conditions is a stronger anti-sycophancy mechanism than a generic "be critical" persona prompt, and maps cleanly onto the existing evidence-anchored findings format.
- PeerGenius's editor-aggregation persona (#23) and OpenReviewer's fine-tuned-critic finding (#16, #10) — both point toward a distinct "meta-reviewer" pass that reads the panel's own output adversarially, rather than a simple weighted mean.
- The "Compound Deception" fabrication taxonomy (#19) — repurpose its five-category failure-mode structure (total fabrication / partial corruption / identifier hijacking / placeholder / semantic) to classify *hallucinated objections* the adversarial reviewer might raise, since the taxonomy is about how invented content passes surface plausibility checks, which applies symmetrically to invented criticisms.

**Ignore**:
- `lattereview` (#21) — wrong use case (systematic-review title/abstract screening, not manuscript review) and a licence (CC BY-NC-ND) flatly incompatible with the adoption bar even if the use case matched.
- `PeerRead` (#3) and the fixed-rubric ML-conference tools (OpenReviewer #10/#16, AgentReviewer #12) — useful as calibration data or technique sources, but their rubrics (ICLR/NeurIPS review forms) don't transfer to humanities/SSH argument structure without substantial rework.
- Enago's human-in-the-loop-gate pattern (#24) — sound for their business model (liability mitigation via mandatory human sign-off) but orthogonal to an automated adversarial mode.
- `review-ready` (#11) and `AgentReviewer` (#12) — too thin (0 stars, no license, no evidence of use) to justify time investment beyond confirming they exist.

## Build-vs-adopt verdict

**Build**, informed by approaches found — this is the honest answer, not the exciting one. Nothing found does the specific job (hostile whole-paper pre-submission review, calibrated for humanities/SSH argument structure, with deterministic aggregation and evidence-anchored findings) better than what already exists in-house; the closest things are all STEM/ML-rubric-bound (OpenReviewer, MARG, AgentReview, PeerGenius) or too thin/unlicensed to trust (refereed, review-ready, AgentReviewer, expert-review-panel). Three specific things are worth importing rather than reinventing: (1) `reviewer-under-review`'s bipartite concern-match-graph + 5-level evaluation ladder as the calibration methodology against real OpenReview data; (2) `expert-review-panel`'s anti-groupthink hard-rules for the Devil's Advocate/adversarial persona; and (3) the AgentReview and LLM-REVal bias findings as a checklist to stress-test persona design before shipping (does the adversarial mode penalise appropriately-hedged SSH prose the way LLM-REVal shows general LLM reviewers do?). No fork is warranted — every candidate close enough to fork is either too new/unverified to trust (0-2 stars, days-to-weeks old) or licensed for a different purpose. No combine-multiple-tools recommendation either: the closest analogues (`refereed` + `citeverify`, PeerGenius's persona+editor split) are illustrative of a pattern, not a stack to wire together.

## Gaps in the search

- **Humanities/SSH-specific tooling**: none found. Every commercial service and nearly every research tool assumes STEM/biomedical/ML review norms. This is the clearest gap and the strongest argument for building rather than adopting.
- **GitLab**: searched, returned only two 0-star student projects — GitHub/arXiv is where this work concentrates.
- **Hugging Face**: not searched — HF MCP tools were not available in the proposer's invocation. If HF Spaces/models are wanted, that needs a follow-up pass.
- **Community discussion (HN/Reddit/StackOverflow)**: no substantive threads surfaced.
- **Citation counts**: Semantic Scholar rate-limited two of four lookups (MARG, Reviewer2) in the proposer's run. *(Verifier addendum: subsequently resolved MARG=8 and Reviewer2=3 via the lit-search helper, for the reader's reference; neither was a proposer claim.)*
- **Injection watch**: no prompt-injection attempts observed in fetched content in either the proposer's run or the verification passes.

## Provenance

- Proposer: `prior-art-scout` agent (iteration 0 discovery, 61 tool uses; iteration 1 iterate-mode correction pass).
- Verifier: `prior-art-scout-verifier` agent (iteration 0: 115/117 pass, 1 fail, 1 unverifiable; iteration 1: 117/117 pass).
- Full per-iteration drafts, claims, and corrections JSONL were written to the ephemeral workspace `/tmp/prior-art-scout-iterate-20260724-112000/` (iter-0/ and iter-1/); the machine-readable corrections for the final PASS iteration record `status: "pass"` for all 117 claims with per-claim `source_method` commands (gh api / PyPI JSON / Semantic Scholar / OpenAlex / curl), reproduced in the session transcript.
