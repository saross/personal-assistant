# Style-guide efficacy experiment — pre-registration & design

**Workstream G (style-guide construction) · roadmap item #1 · 2026-05-31**

Registers the design and decision rule *before* generation. Direction,
significance test and band-migration rules are fixed here in advance; the one
quantity calibrated from the pilot is the *magnitude* threshold for "material"
(it depends on the corpus leave-one-out (LOO) distance scale, which the pilot
measures).

## 1. Question and hypothesis

Does the empirical academic style guide
(`notes/style-guides/academic/style-guide-academic-2026-05-30-2.md`, §§1–11 +
Appendix F exemplars) measurably pull large-language-model (LLM) output *toward
Shawn's corpus*, beyond what a plain or a generically academic prompt achieves?

- **H1 (decision-relevant):** text generated under the full guide (C2) is
  closer to the corpus centroid than text generated under a generic
  academic-register instruction (C1). I.e. the guide adds *author-specific*
  value, not merely "academic register helps".
- **H0:** C2 ≈ C1. (If C2 ≈ C1 < C0, the guide is no better than a one-line
  "write like a journal article" instruction.)

## 2. Outcome measures

All scoring is by `scripts/style-analyser/phase5_evaluator.py`
(`evaluate_text`), CPU-only, no API, identical feature extraction to the corpus
(it imports `process_paper` from `phase1_pipeline.py`).

- **Primary — Mahalanobis distance-to-corpus** (continuous; 12-feature,
  length-normalised, Ledoit-Wolf-shrunk). Lower = more on-voice. Reported with
  the empirical **envelope band**: `within` (≤ corpus LOO max, currently
  4.42), `borderline` (≤ 1.5× LOO max), `outside`.
- **Secondary — 8-metric gate pass-count `/8`.** *Caveated:* the gate is
  aspirational-by-construction (the corpus's own median is 5/8) and is the
  most directly "teachable" measure (see §6). Reported, not relied upon.
- **Diagnostic — per-feature standardised |z| vs corpus.** Shows which
  features the guide moves toward the corpus and which it still misses; feeds
  guide revision and the future `/write-like-me` packaging.

## 3. Design — three conditions, paired on topic, two strata

Holding topic, task, length (~400 words) and format (continuous prose, no
lists/headings) constant, vary **only** the style guidance:

| Cond | Guidance | Role |
|---|---|---|
| **C0** | format/length scaffold + topic only | true baseline |
| **C1** | + "formal scholarly register suitable for a peer-reviewed journal" | **Shawn-specificity control** |
| **C2** | + guide §§1–11 + Appendix F exemplars | treatment |

**Why C1 is the crux.** Without it, a C2 < C0 win only shows "academic
instruction helps". C1 isolates author-specific value: the guide earns its
keep only if **C2 < C1**.

**Pairing.** Unit = topic. Each topic is generated under all three conditions;
we compare *within-topic* (controls between-topic variance). Per (topic ×
condition) we take the **median distance over replicates** (robust to an
outlier generation), then pair across topics.

**Two topic strata (6 each):**

- **On-domain (A1–A6)** — the corpus's own themes (digital/landscape
  archaeology, field data capture, FAIR data, OSS sustainability), phrased as
  *new* synthetic writing tasks, never "reproduce paper X".
- **Off-domain (B1–B6)** — academic topics *outside* archaeology
  (pre-registration in psychology, herd immunity, clinical ML interpretability,
  reproducibility in computational social science, OSS licensing economics,
  RCTs in education). These test whether the guide transfers **voice
  independently of content**, and control for distance dropping via
  discipline-vocabulary overlap rather than style. The off-domain result is the
  cleaner style-transfer evidence.

The exact prompts are archived in
`data/experiments/style-efficacy-2026-05-31/prompts.json`; the injected guide
block in `prompt-c2-context.md`.

## 4. Generation mechanism

- **In-CC fresh-context Claude subagents (Opus 4.8), one per (condition ×
  topic × replicate).** No external API call → **no API review gate**
  (confirmed with Shawn 2026-05-31). Fresh context per generation guarantees
  C0/C1 subagents never see the guide (clean isolation).
- **Deviation from strict Panickssery few-shot.** Appendix F is designed as
  conversation-history `(user, assistant)` turns. A single subagent prompt
  cannot carry turn structure, so the exemplars are embedded as a labelled
  block inside the C2 prompt. This matches how a real `/write-like-me` command
  would inject the guide into one Claude Code prompt — ecologically valid, but
  recorded as a deviation. The 2×2 ablation (below) will later isolate the
  exemplars' marginal contribution.
- **Replicates** capture generation stochasticity (temperature is not pinned in
  the subagent path; replication is the control for sampling noise).
- **Archival.** Every prompt (`prompts.json`), every passage
  (`passages/{topic}__{cond}__rep{n}.md`) and every score (`scores.json`) is
  saved, so the *analysis* is fully reproducible even though regeneration is
  not bit-identical.

## 5. Sample size and aggregate

- **Pilot:** 4 topics (A1, A2 on-domain; B1, B3 off-domain) × 3 conditions ×
  2 replicates = **24 generations**. Confirms the pipeline end-to-end and
  reveals effect direction + LOO-SD scale.
- **Full (on green light):** 12 topics × 3 conditions × 3 replicates =
  **108 generations**.
- **Cost.** Generation is in-CC (session tokens only, no $); scoring + analysis
  are CPU-only/free.

## 6. Central validity threat — teaching-to-the-test

The guide *names target numbers* for many of the 12 distance features
(mean sentence length 21.45, semicolons 6.54/1k, hedges 0.72/100w, passive
0.31, nominalisation 38.6/1k …) in its section prose. A capable model can
partly "hit the test", so a C2 win is partly tautological — **most acutely on
the 8-metric gate**, which is literally "did you hit these bands". Mitigations,
in order of weight:

1. **The C1 control** reframes the question from "does telling the model the
   numbers make it hit them?" (trivially yes) to "does the author-specific
   guide beat a generic academic instruction?".
2. **Distance is primary, gate is caveated.** The covariance-aware holistic
   distance is harder to game perfectly than 8 independent bands.
3. **The off-domain stratum** separates style from content.
4. **Independent evaluator (deferred follow-up):** the "Catch Me If You Can"
   four-metric ensemble (Wang et al. 2025, arXiv 2509.14543) uses features
   *not* derived from this corpus pipeline — a genuinely held-out judge. It is
   its own build; out of scope for v1, flagged if v1 shows promise.

## 7. Analysis plan (`efficacy_analyse.py`)

- Paired differences per topic on median distance, for C1→C2 (headline),
  C0→C2, C0→C1.
- **Exact sign-flip permutation test** (one-sided in the H1 direction +
  two-sided); enumerated over 2^n sign assignments. *The pilot (n=4) has min
  one-sided p = 1/16 = 0.0625 and cannot reach significance — read direction,
  win-rate and LOO-SD magnitude, not the p-value.*
- **Wilcoxon signed-rank** as a rank-based cross-check (guarded for small n).
- **Effect size** = median paired Δ / corpus LOO standard deviation.
- **Envelope-band migration** table; **gate pass-count** shift (caveated);
  **on-/off-domain stratum** breakdown (descriptive; n=6 each is not powered
  for a formal interaction test); **per-feature |z|** profile.

## 8. Pre-registered decision rule

- **Guide adds Shawn-specific value** ⇢ C2 distance materially & (at full n)
  significantly **below C1**, directionally consistent in the off-domain
  stratum. "Material" = ≥ 1 corpus-LOO-SD reduction in median distance **or** a
  topic-level envelope-band migration (e.g. outside→borderline,
  borderline→within). *The exact LOO-SD magnitude threshold is fixed after the
  pilot reveals the SD scale.*
- **Guide ≈ generic register** ⇢ C2 ≈ C1 < C0 → the elaborate guide's marginal
  value over a one-line instruction is small; reconsider before packaging.
- **Guide doesn't work** ⇢ C2 ≈ C0.

Outcome gates roadmap item #2 (package a `/write-like-me` workflow): build only
on a positive (or at least off-domain-positive) result.

## 9. Deferred to the to-do list

- **2×2 ablation** (guide-only, exemplars-only, in addition to plain and
  full) — decides whether the Appendix F exemplar-injection plumbing is worth
  building into `/write-like-me`. Run after the 3-condition result lands.
- **Independent evaluator** (Catch-Me-If-You-Can ensemble) — see §6.4.

## 10. Artefacts

| Artefact | Path |
|---|---|
| This pre-registration | `wiki/planning/style-guide-efficacy-experiment-design.md` |
| Prompt manifest | `data/experiments/style-efficacy-2026-05-31/prompts.json` |
| Injected C2 guide block | `data/experiments/style-efficacy-2026-05-31/prompt-c2-context.md` |
| Generated passages | `data/experiments/style-efficacy-2026-05-31/passages/` |
| Generation log | `data/experiments/style-efficacy-2026-05-31/generation-log.jsonl` |
| Scores | `data/experiments/style-efficacy-2026-05-31/scores.json` |
| Analysis | `data/experiments/style-efficacy-2026-05-31/analysis.{md,json}` |
| Prompt builder | `scripts/style-analyser/efficacy_build_prompts.py` |
| Scorer | `scripts/style-analyser/efficacy_score.py` |
| Analyser | `scripts/style-analyser/efficacy_analyse.py` |
