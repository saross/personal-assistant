# corpus-style-analyser v2 — implementation plan

**Date drafted:** 2026-05-22
**Drafted by:** Plan agent (subagent)
**Status:** DECIDED 2026-05-22 — ready for execution. All 10 design questions resolved (see §9).

## 0. Scope

**In scope (the five agreed lifts, in user's preferred order):**

1. Biber Multidimensional Analysis dimension labels as the §§1–6 organising scheme (Yang & Carpuat 2025).
2. Catch Me If You Can evaluation suite (Wang et al. 2025) as a post-generation evaluation gate.
3. Kumar et al. 2025 Author Writing Sheet cross-document aggregation rule, formalised for academic register.
4. Write-like-me measurement-layer extensions (MATTR, hapax, passive ratio, nominalisation rate, dependency depth, POS bigrams, paragraph stats) + 8-metric verification gate + reference-list pre-pass.
5. Panickssery reverse-prompt few-shot exemplar block appended to the guide.

**Out of scope:**

- Step-Back Profiling Gist preamble (Tang et al. 2024) — already captured in memory.
- Hassid 8-section relayout — superseded by Biber.
- Forking `write-like-me` wholesale (re-implement under run-1 evidence discipline; see comparator report §7.1).
- Vendoring `write-like-me/scripts/stylometry.py` (citation pollution + textstat bugs in the source per comparator §4).
- Reconciliation with prior conscious style guides (deliberately a separate human-in-the-loop session — see agent line 231–238).

**Carry-over from run-1 (must not regress):**

- Four-status schema: `attested` / `attested-rarely` / `absent-when-searched` / `derived-by-inference` / `aspirational` (agent lines 29–30, run-1 line 18–22).
- ≥2 verbatim quotes per attested claim with `[ZoteroKey#sentence-idx]` locator (agent lines 188–199, run-1 line 27).
- Per-paper attestation distributions preserved in Appendix C (run-1 lines 932–1107).
- UK/Australian English (agent line 21).
- Aspirational section corpus-independent, marked `aspirational — generated independent of corpus` (agent lines 125–135).
- Re-runnability across model versions with Appendix D diff (agent lines 254–267).

---

## 1. Pre-implementation design decisions (cheapest first)

| # | Question | Trade-offs | Default if no user input |
|---|----------|------------|-------------------------|
| D1 | Where does v2 live? Update `/home/shawn/.claude/agents/corpus-style-analyser.md` in place, or fork to `corpus-style-analyser-v2.md`? | Forking preserves bit-perfect ability to re-run run-1. In-place edit reduces directory cruft and matches the agent's own "re-run with newer Claude" idiom. | **Fork to `corpus-style-analyser-v2.md`** until v2 has been run against the 18-paper corpus and confirmed; then deprecate the v1 file. |
| D2 | Where does the analysis code live? Inline-in-agent Bash/Python heredocs (run-1's idiom), or a dedicated `~/personal-assistant/scripts/style-analyser/` directory? | Inline keeps the agent self-contained and re-creatable from prompt only. A scripts directory is testable and reusable across genres but adds a maintained dependency. | **Inline-in-agent for v2.** Promote to a scripts directory only if the inline blocks exceed ~400 lines or are duplicated across genres. |
| D3 | spaCy model version pinning? | `en_core_web_sm` 3.8.0 confirmed available in the write-like-me venv (comparator line 155). Pinning prevents Biber-feature drift across runs. | **Pin to `en_core_web_sm==3.8.0`**; document in the agent's Re-runnability notes. |
| D4 | Per-paper measurement granularity for the new write-like-me metrics? Aggregate corpus-wide only, or also per-paper (matching run-1 §1.1 ledger pattern)? | Per-paper costs extra rows in Appendix C but is the whole point of the evidence discipline. Aggregate-only is the write-like-me mode that loses the role-dependent pattern (comparator §3 line 63). | **Per-paper AND aggregate.** Every new metric gets an Appendix C ledger table the shape of §1.1. |
| D5 | API budget per v2 generation run? Phases 3 and 5 involve LLM calls (Kumar aggregation + Panickssery inversion). | Cost-visible per global CLAUDE.md API-gate. | **Approval required before run** per global CLAUDE.md; defaults proposed in §10. |

---

## 2. Phase 1 — Measurement-layer extensions

The cheapest, lowest-risk phase. Pure additive Python; no LLM calls; deterministic.

**2.1 Reference-list stripping pre-pass.** Insert *before* the existing extraction-quality step (current agent Phase 2, lines 74–86). The write-like-me run leaked surnames "sobotkova" (56 hits) and "ross" (52) plus "doi/https/org" content words into its output (comparator §4 lines 80). Run-1 already strips references via the SP2R6FF9 chapter-boundary technique (run-1 lines 912–919) but does so ad hoc per paper.

Formalise: after `pdftotext -layout`, detect the references-section header by regex (case-insensitive `^(References|Bibliography|Works\s+Cited|Literature\s+Cited)\b` at line start), truncate everything after the *last* such header. Fallback: if no header detected, look for a high density of `Author, A.B. (\d{4})` patterns and truncate at the start of the longest such run. Record in Appendix B which truncation method was used per paper.

**2.2 Lift these metrics from write-like-me, re-implemented:**

| Metric | Source function | Citation | Per-paper | Aggregate |
|--------|-----------------|----------|-----------|-----------|
| MATTR-window-100 | `compute_mattr` (stylometry.py:199–209) | Covington & McFall (2010) | yes | yes |
| Hapax ratio | `compute_hapax_ratio` (357–363) | (no citation needed) | yes | yes |
| Passive ratio (spaCy) | `compute_spacy_features` (388–442, `nsubjpass`/`auxpass`) | Biber (1988) feature family | yes | yes |
| Nominalisation rate (spaCy) | same, `nom_suffixes` lemma scan | Biber (1988) | yes | yes |
| Mean dependency depth (spaCy) | same, `_hop_depth` | (Lin 1998 family) | yes | yes |
| Top-20 POS bigrams (spaCy) | same | (descriptive only) | aggregate only | yes |
| Paragraph stats (mean/median/stdev) | `compute_paragraph_stats` (299–311) | (descriptive only) | yes | yes |

Do **not** copy code wholesale. Re-implement each function in the agent's inline Python block. Reasons (from comparator §4 lines 76–83): (a) write-like-me's textstat call swallows exceptions and silently returns `{}`; (b) its markdown stripper conflicts with the reference-list pre-pass; (c) MIT licence requires copyright attribution which is more administrative overhead than the ~30 lines per metric warrants.

**Do not lift the 50,000-character spaCy sampling cap** (stylometry.py line 396). At 139k words the corpus comfortably fits in memory if processed per-paper; sample only if any single paper exceeds spaCy's 1M-char limit (none do in run-1).

**2.3 Attestation-discipline per new field.** Each new metric must, per the cross-cutting requirement, carry the same shape as run-1's §2.1:

- Aggregate value with 2 decimal places.
- Per-paper distribution in Appendix C.
- Status: `attested` (corpus has the metric — true for all of these by construction).
- ≥2 verbatim sentence-level examples *when the metric has sentence-level granularity* (passive ratio, nominalisation rate, dependency depth). For corpus-aggregate metrics with no sentence anchor (MATTR, hapax, POS bigrams) the Editor's note explains what the number signifies and §2.1's data anchors it. Document this distinction explicitly in the agent's Phase-3 instructions.

**2.4 8-metric post-generation verification gate (write-like-me `references/07-verification.md` lines 36–49).** This is a *deferred* gate — it does not run during v2 of `corpus-style-analyser` itself. It runs against any *downstream LLM output* that claims to apply the guide. The agent should emit a new Appendix E ("Verification protocol") containing the eight target metrics with corpus-derived target values and tolerances:

| Check | Corpus target (from run-1) | Tolerance |
|-------|----------------------------|-----------|
| Em dashes | 0.46/1k | ±0.20/1k |
| Semicolons | 5.57/1k | ±1.0/1k |
| Announcement colons | TBD — needs verification (run-1 reports total colons via §2.4 sample only; per-1k figure not derived) | ±0.5/1k |
| Mean sentence length | 23.9 words | ±10 (per write-like-me) |
| Consecutive short (≤5 words) sentences | 0 attested-in-runs | 0 |
| Boosters per 100w | 0.067 (write-like-me; corpus zero on the targeted vocabulary per run-1 §1.3) | 0.0 |
| Hedge density per 100w | TBD — recompute from corpus (run-1 §1.2 gives raw counts, not per-100w) | ±0.1/100w |
| Concession rate (sentences with concession word) | TBD — recompute from corpus | ±0.05 |

Three of eight need recomputation (`announcement colons`, `hedge per 100w`, `concession rate`). Recompute as part of Phase 1 implementation; the gate itself is just a document.

**2.5 Regression tests against run-1 numbers.** v2 must reproduce the following run-1 values within tolerance:

| Statistic | Run-1 value | v2 must produce |
|-----------|-------------|-----------------|
| Total words (refs stripped) | 139,105 | within ±2% (more aggressive refs-stripping may legitimately reduce this) |
| Total sentences | 5,448 | within ±2% |
| Mean sentence length | 23.9 | within ±0.5 |
| First-plural per 1k | 4.83 | within ±0.05 |
| Em-dash per 1k | 0.46 | within ±0.05 |
| Semicolons per 1k | 5.57 | within ±0.10 |
| "while" / "whilst" | 232 / 0 | exact |
| "however" / "although" | 126 / 72 | exact |
| `pace` Latin abbr. | 9 in 6 papers | exact |
| UK:US orthography core | 177:55 | exact |

Run-1 Appendix C tables (§1.1, §2.3, §4.2, §4.3, §5.1) are the regression-test reference data. If v2 disagrees on any of these the disagreement must be explained in the Re-runnability notes before publishing the guide.

---

## 3. Phase 2 — Biber MDA section migration

**3.1 Mapping table.** The user instructed to use Biber's six canonical dimensions where they map, and to declare hybrid where they do not.

Biber's 1988 six dimensions (canonical):

- **D1** Involved vs Informational Production
- **D2** Narrative vs Non-narrative Concerns
- **D3** Explicit vs Situation-dependent Reference
- **D4** Overt Expression of Persuasion
- **D5** Abstract vs Non-abstract Information
- **D6** On-line Informational Elaboration

Note: Yang & Carpuat 2025 reference "Biber's MDA framework" but their paper (per the HTML fetch) does not enumerate which dimensions they use. The user's instruction to use Biber's six dimensions therefore relies on the canonical 1988 set, not on Yang & Carpuat's specific selection. This is fine — citing Biber 1988 directly is more defensible than citing a paper that under-specifies its own use of the framework.

**Mapping current → Biber:**

| Run-1 section (agent lines 157–164) | Maps to Biber dimension(s) | Notes |
|-------------------------------------|---------------------------|-------|
| §1 Voice & register | **D1** Involved vs Informational | First-plural pronouns (§1.1) and hedge inventory (§1.2) are textbook D1 features. Booster absence (§1.3) and throat-clearing absence (§1.4) also D1. |
| §2 Sentence-level craft | **D3** Explicit vs Situation-dependent + **D6** On-line Informational Elaboration | Subordination (§2.2), parentheticals (§2.5), and sentence length (§2.1) are D3+D6 territory. Em-dash and semicolon (§2.3, §2.4) are punctuation craft, partially D6. |
| §3 Paragraph & argument structure | **D4** Overt Expression of Persuasion (stance pivots §3.3, "However" §3.4) + hybrid (paragraph statistics are not Biber-canonical) | Connectives and stance pivots fit D4. Topic-position §3.1 doesn't fit any Biber dimension cleanly. |
| §4 Citation conventions | **Register-specific (academic)** — no Biber mapping | Citations are genre-specific; Biber's dimensions are register-agnostic. Keep as a hybrid section labelled `§7 Academic register conventions`. |
| §5 Lexical preferences | **D1** (orthography, UK/US, archaic UK is involvement+register) + register-specific (discipline vocabulary) | Hybrid. Orthography is partly D1; "tell" / "tumulus" / "concentration" is pure register. |
| §6 Voice tics | Cross-dimensional | Tics span D1–D6; keep as a `§8 Voice-tic summary` cross-referencing the dimension sections. |
| §7 Anti-patterns the editor removes | Cross-dimensional | Same. Keep as `§9 Editor anti-patterns`. |
| §8 Aspirational | n/a | Keeps its current name. |

**Proposed v2 section layout:**

```
## §1. D1 — Involved vs Informational Production
   (pronouns, hedges, boosters, throat-clearing, nominalisation)
## §2. D2 — Narrative vs Non-narrative Concerns
   (TBD — verify whether the academic corpus has narrative features to measure;
    if not, document as "low signal — corpus is predominantly non-narrative" and
    keep the section to preserve the canonical scheme)
## §3. D3 — Explicit vs Situation-dependent Reference
   (deictic expressions, parentheticals as scope qualifiers)
## §4. D4 — Overt Expression of Persuasion
   (modals, connectives, stance pivots, "However"/"Although" balance)
## §5. D5 — Abstract vs Non-abstract Information
   (passive ratio, nominalisation rate — moved from §1 if duplicated)
## §6. D6 — On-line Informational Elaboration
   (sentence length, subordination depth, dependency depth, semicolons)
## §7. Academic register conventions (citation, Latin abbreviations)
## §8. Lexical / orthographic preferences (UK vs US, archaic UK, hyphenation)
## §9. Voice-tic cross-reference
## §10. Editor anti-patterns (derived-by-inference)
## §11. Aspirational — generated independent of corpus
```

Risk: D2 may have near-zero signal in this corpus (no narrative tense alternation, no third-person past). Default if so: keep the §2 heading with the `absent-when-searched` status and an explicit note that narrative features are corpus-absent (which is itself data per the project's anti-confabulation discipline).

**3.2 Per-claim format unchanged.** The `### {N.N} {Claim title}` block (agent lines 189–199) continues unchanged; only the parent section labels move to Biber.

**3.3 Cross-reference Appendix C tables.** Run-1's ledger keys (§1.1, §2.3, etc.) must be re-numbered to track the new section structure, with a small redirect table at the top of Appendix C mapping old (v1) numbers to new (v2) numbers. Important for the diff appendix to work across versions.

---

## 4. Phase 3 — Kumar Author Writing Sheet aggregation

The current agent does cross-paper aggregation informally: a claim is `attested` if ≥3 papers exhibit it, `attested-rarely` if 1–2, `absent-when-searched` if deliberately searched and not found (agent lines 88–124). Kumar et al. 2025 provides a formal merge algorithm.

**4.1 Kumar's algorithm (per HTML fetch of arXiv 2502.13028v1):**

- For each story (read: paper) `t`, an LLM generates an intermediate sheet `A_t'` by comparing the author-written story against an *average baseline story* generated per-prompt by `LLM_avg`.
- This intermediate sheet is iteratively merged with the previously accumulated sheet `A_{t-1}` using an `LLM_combine`.
- Merge operations: (i) group equivalent Claims within each narrative category; (ii) select the best Evidence for grouped Claims; (iii) retain ungrouped Claims with their respective Evidence.
- Each category caps at 10 Claim-Evidence pairs.
- The process avoids reprocessing prior stories.

**4.2 Adaptation for academic register without LLM-mediated extraction.** Kumar uses LLMs for both the per-paper claim extraction and the merge. v1 of `corpus-style-analyser` does both deterministically (regex counts + manual rule selection by Claude during synthesis). The user's anti-confabulation discipline (agent lines 208–230) is incompatible with LLM-generated claims — the whole point is that "a memory of a pattern is not the pattern; a re-read of the source is" (agent line 33). So lift the **merge rule**, not the LLM-mediated extraction.

**Concrete merge rule for v2 (academic register):**

For each candidate pattern `P` (e.g. "sentence-initial 'Although'"), define:

- `n_papers(P)` = number of papers in which `P` is attested at a paper-specific threshold (e.g. ≥1 occurrence per 1k words, or ≥2 absolute occurrences for low-frequency features).
- `n_occ(P)` = total occurrences across the corpus.
- `coefficient_of_variation(P)` = stdev(per-paper rate) / mean(per-paper rate).

**Promotion rules:**

| Status | Condition |
|--------|-----------|
| `attested` | `n_papers(P) ≥ 3` AND `n_occ(P) ≥ 5` |
| `attested-rarely` | `1 ≤ n_papers(P) ≤ 2`, OR (`n_papers(P) ≥ 3` AND `n_occ(P) < 5`) |
| `attested-concentrated` | `n_papers(P) ≥ 3` AND `coefficient_of_variation(P) > 1.5` (the pattern is real but lives in a subset of papers — like em-dash usage, run-1 §2.3) |
| `absent-when-searched` | `n_occ(P) ≤ 2` AND `n_papers(P) ≤ 1`, AND the absence was deliberately searched (i.e. P is on the agent's search list) |
| `derived-by-inference` | absence + plausible editorial-removal explanation (agent line 31, anti-patterns) |

`attested-concentrated` is a new status — it formalises a pattern run-1 already exhibits informally for em-dashes (§2.3, where 7 of 18 papers carry 96% of em-dashes). This is the academic analogue of Kumar's "best evidence selection": when a pattern concentrates, the per-paper breakdown (Appendix C) is the diagnostic, not the corpus aggregate.

**Conflict resolution for "strong in 3, absent in 15":** treat as `attested-concentrated`. Document in the Editor's note both the where-it-appears papers and the where-it-does-not papers, so a downstream LLM applying the guide can choose to apply or not based on context (venue / co-author / genre). The user's question — "how are conflicts resolved when a pattern is strong in 3 papers and absent from the other 15?" — is answered: do **not** resolve to a single status; preserve the bimodality and let the editor decide.

**4.3 Where this slots in.** Add to the agent's Phase 3 instructions (agent lines 88–124) a new sub-step "3.0 — Status assignment rules" that codifies the promotion table above. Add to each claim's per-paper Appendix C entry: `n_papers`, `n_occ`, `coefficient_of_variation`.

**4.4 Per-paper distribution preservation.** This is a hard requirement (cross-cutting #3). The promotion rules above are computed from per-paper rates; Appendix C must continue to carry the full per-paper breakdown for every metric (matching run-1 §1.1 lines 932–953). Aggregate-only summaries are forbidden.

**4.5 No LLM calls in Phase 3.** Kumar's `LLM_avg` and `LLM_combine` are not used. The merge rule is deterministic. This preserves run-1's anti-confabulation discipline and keeps the phase free.

---

## 5. Phase 4 — Panickssery reverse-prompt exemplar block

The Panickssery recipe (Candidate 4 in the prior-art report, lines 90, 115): feed an existing passage to an LLM, ask "what prompt would have produced this?", assemble the (prompt, passage) pairs as a few-shot conversation-history block.

**5.1 Where it lives in the guide.** Append as **Appendix F — Few-shot exemplar block** after the existing appendices (after Appendix E verification protocol from Phase 1). It is explicitly *not* part of §§1–11; it is a downstream-consumable conversation-history fragment for LLMs that will write under the guide.

**5.2 Exemplar selection rule.** Three concrete criteria, applied in order:

1. **High-attestation passages.** A passage is "high-attestation" if it instantiates ≥3 distinct attested patterns from §§1–10 (e.g. sentence-initial "Although" + first-plural "we" + parenthetical aside + parenthetical citation, all in one sentence). Compute by scanning each candidate passage against the attested-feature regex bank.
2. **Per-paper diversity.** No two exemplars from the same paper.
3. **Length budget.** 1–3 sentences each; total exemplar block ≤ 600 words.

Choose **5 exemplars**: one from each of 5 distinct papers, prioritised by author role (≥2 first-author papers; ≥2 last-author/editor papers; ≥1 middle-author).

**5.3 The inversion prompt.** Sent per chosen exemplar:

```
You will be shown an academic passage. Without paraphrasing the passage, write a
3-5-sentence prompt (in the second person, addressed to a future writer) that
would have produced this passage when given to a writer faithful to the
attached style guide. Describe the task, audience, scope, and any constraints
the passage implies (e.g. "you are writing the methods paragraph of a journal
article…"). Do NOT mention the passage itself, the topic, or any proper nouns
from the passage. Do NOT include style-guide rules — the writer already has
those. UK / Australian English throughout.

Passage:
{passage}
```

**5.4 Model choice for inversion.** Use Claude Opus 4.7 (or current best opus-tier) for the inversion call. Five calls × roughly 500 input tokens + 200 output tokens = ~3,500 tokens total per run. At Opus 4.7 list pricing this is sub-dollar (TBD — pricing varies; needs verification at runtime, but this is one batch of five calls).

**5.5 API gate.** Per the cross-cutting requirement, this LLM-call phase must surface for user approval before running. Default: ask the user "OK to spend ~$0.50 (estimate) on 5 inversion calls to Opus 4.7 for the exemplar block?" before Phase 4 begins.

**5.6 Output format in Appendix F:**

```markdown
## Appendix F — Few-shot exemplar block

[Use this block as conversation history when prompting an LLM to write under
this style guide. Each turn shows a (prompt, exemplar passage) pair.]

### Exemplar 1 of 5 — `[ZoteroKey#sentence-idx]`

**Reverse-engineered prompt:**
{inversion output}

**Exemplar:**
> {verbatim passage}

**Attested patterns instantiated:** §1.1, §2.2, §2.5, §4.1
**Source:** Zotero {key}, {year}, role {first/middle/last}

### Exemplar 2 of 5 — …
```

Note: every exemplar carries a Zotero locator, preserving the run-1 evidence discipline even into this synthetic block. The "Attested patterns instantiated" cross-reference is what binds the exemplar back to the guide's evidence ledger.

---

## 6. Phase 5 — Catch Me If You Can evaluation suite

**6.1 What the open-source release contains** (verified at `https://github.com/jaaack-wang/llms-implicit-writing-styles-imitation`, MIT licence, 5 stars, last push 2026-01-16):

- Training/test data splits for four datasets (Enron, Blog, CCAT50, Reddit) — *not* applicable to Shawn's academic corpus.
- Scripts for training AA (authorship attribution) and AV (authorship verification) models.
- LLM writing generation + evaluation scripts.
- Stylometry feature creation tools.
- `LIWC2007_English100131.dic` dictionary file (third-party; commercial LIWC dictionary).
- `requirements.txt` against Python 3.12.9 conda env.

**No pre-trained classifier weights are included.** Users must train their own AA/AV models on their own data.

**6.2 Concrete answer to the CC-only question.** The four metrics decompose as:

| Metric | Local feasibility | What it costs |
|--------|------------------|---------------|
| **Style matching** (LIWC + WritePrint features + Mahalanobis distance) | Local on CPU. LIWC dictionary is commercially licensed (Pennebaker et al. — *not* MIT) but a free open alternative (Empath, or LIWC-2001 derivatives) exists. | Local compute only. |
| **Authorship attribution** (Longformer-base-4096 or ModernBERT-base, fine-tuned) | Local-on-GPU. **Problem: Shawn's corpus is 18 papers by one author — there is no other-author class to discriminate against.** | The AA metric is conceptually inapplicable to a single-author corpus. |
| **Authorship verification** (same encoders) | Same problem: AV asks "were these two texts by the same author?" — meaningful only if you have ≥2 authors to compare. Could be done by treating individual papers as the units to be matched, but that measures *intra-author paper similarity*, not generation-vs-author similarity in the way the paper intends. | Re-purposable as a *self-consistency* metric across generated vs held-out passages — but this is a re-purpose, not the paper's metric. |
| **AI detection** (GPTZero, off-the-shelf web service) | External API. GPTZero has free and paid tiers; paid tier ~$0.01–0.02 per scan. | External API spend; not in CC. |

**Honest read:** the Catch Me If You Can suite is designed for *multi-author benchmarks*. Three of its four metrics either don't apply to a single-author corpus or require external infrastructure (GPU for AA/AV; GPTZero for AI detection).

**6.3 Recommended adaptation for v2:**

Implement a **reduced two-metric evaluation suite** that runs in Claude Code without external infrastructure:

1. **Stylometric distance** (lift from CC's "style matcher" component). Compute the Mahalanobis distance between (a) the held-out 2–3 paragraphs from the corpus (per write-like-me verification §07 lines 14–22) and (b) generated text claiming to write under the guide. Distance is computed in the feature space of the metrics from Phase 1 (MATTR, passive ratio, function-word profile, hedge density, etc.). Pure CPU; no API.

2. **8-metric tolerance gate** (from write-like-me `references/07-verification.md`, already adopted in Phase 1.4 above). Pass/fail against the targets in §2.4 of this plan.

**Cost per evaluation run:** zero API spend in CC; one round of LLM-generation on the test prompt (the *thing being evaluated*, not the evaluator) which the user controls separately. The evaluator is deterministic.

**6.4 Optional: external AI-detection check.** If the user wants the full four-metric ensemble, plan an *optional* Appendix G containing GPTZero scores. Cost: ~$0.05 per 1,000-word generated passage (estimate from GPTZero pricing, TBD — needs verification at runtime). Surface for user approval before running. Default: skip.

**6.5 Where this slots in the lifecycle.** v2 of the agent itself does **not** run Phase 5 — the agent produces the guide, not the evaluation. Phase 5 lives in a **separate downstream tool** invoked when a downstream LLM has written text claiming to apply the guide. Document Phase 5 as a section of the agent's Appendix E ("Verification protocol") with concrete instructions for the human-in-the-loop to run.

This separation is important: the user can re-run v2 of the analyser without re-running the evaluation, and vice versa.

---

## 7. Cross-cutting concerns

**7.1 Attestation discipline per new field.** Codified in §2.3, §4.4 above. Hard rule: no aggregate-only summaries. Every new field gets per-paper distribution.

**7.2 UK/Australian English.** Already mandated (agent line 21). v2 must also extend the orthography probe (run-1 §5.1) to include words newly visible in the spaCy/POS-bigram surface (e.g. "behaviour" was probed at 2:1 UK; new probe candidates: "modelling/modeling", "fibre/fiber", "metre/meter" — already in §5.1; "honour/honor", "favour/favor", "ageing/aging").

**7.3 Regression tests.** Per §2.5 above. Run the v2 pipeline on the same 18-paper corpus and confirm the run-1 anchors before publishing.

**7.4 API gate compliance.** Per global CLAUDE.md, every Claude/external-API call must declare model + batch-vs-realtime + count + cost estimate before running. v2 calls:

- Phase 4 inversions: 5 calls × Opus 4.7 × ~700 tokens each = ~3,500 tokens. Realtime. **~$0.50 estimate** (TBD per current pricing).
- Phase 5 (optional) GPTZero: per-passage cost. **~$0.05/1k words estimate** (TBD).

No other v2 phase makes API calls.

**7.5 Per-paper distribution preservation.** Verified in §4.4 above.

---

## 8. Sequencing

```
Phase 1 (measurement extensions) ──┐
                                   ├──> Phase 2 (Biber relayout) ──┐
Phase 3 (Kumar aggregation) ───────┘                               │
                                                                   ├──> Output assembly
Phase 4 (Panickssery exemplars) ───────────────────────────────────┘
                                                                   │
Phase 5 (evaluation suite — separate downstream tool) ─────────────┘ (independent)
```

**Critical path:** Phase 1 → Phase 2 → Output. Phase 3 (aggregation rules) is logically pre-Phase-2 since it changes how status is computed, but it has no code dependency on Phase 1 — implement in parallel.

**Parallelisable:** Phases 1, 3, 5 can be developed independently. Phase 4 depends on Phase 1 (needs the metric set to score exemplar candidates) but is independent of Phases 2 and 3.

**Suggested execution order for the parent assistant:**

1. Phase 1 first (lowest risk, deterministic, unblocks regression tests).
2. Phase 3 second (deterministic rule formalisation; affects every status in §§1–10).
3. Phase 2 third (relayout — easy once Phases 1 and 3 are settled).
4. Phase 4 fourth (LLM calls — requires API approval).
5. Phase 5 separately (downstream evaluation tool — its own session).

---

## 9. Decisions resolved (2026-05-22)

All 10 design questions decided in this session; the recommended default was taken on every item.

1. **D1 — Fork or in-place?** Decided: **fork** to `~/.claude/agents/corpus-style-analyser-v2.md`. Deprecate v1 file after v2 is verified against the 18-paper corpus.
2. **D2 — Inline or scripts directory?** Decided: **inline** in the agent (Bash/Python heredocs, matching run-1's idiom). Promote to a scripts/ directory later only if blocks exceed ~400 lines or get duplicated across genres.
3. **D3 — spaCy model pin?** Decided: pin to **`en_core_web_sm==3.8.0`**. Document in agent re-runnability notes.
4. **D4 — Per-paper granularity for new metrics?** Decided: **per-paper AND aggregate**. Every new metric (MATTR, hapax, passive ratio, nominalisation rate, dependency depth, paragraph stats) gets an Appendix C ledger table matching the shape of run-1 §1.1.
5. **Phase 2 — D2 narrative dimension if near-zero signal?** Decided: **keep** the §2 heading with `absent-when-searched` status. Absence is data per anti-confabulation discipline; preserves canonical six-dimension scheme for future Substack/business/teaching genre runs.
6. **Phase 3 — new `attested-concentrated` status?** Decided: **add as fifth status**. Formalises run-1 §2.3's informal bimodal-em-dash treatment. Status vocabulary becomes: `attested` / `attested-rarely` / `attested-concentrated` / `absent-when-searched` / `derived-by-inference` / `aspirational`.
7. **Phase 4 — exemplar count?** Decided: **5 exemplars** (≥2 first-author + ≥2 last-author + ≥1 middle).
8. **Phase 4 — inversion model?** Decided: **Claude Opus 4.7** (`claude-opus-4-7`); ~$0.50 total spend per generation. Surface for API-gate approval before running.
9. **Phase 5 — GPTZero optional appendix?** Decided: **skip as standard**; opt-in per generation if a defensible AI-detection number is wanted.
10. **Phase 5 — Mahalanobis style matcher feature space?** Decided: **free alternative** built on the function-word + punctuation + hedge + sentence-shape feature set from Phase 1. Keeps v2 cleanly redistributable, matches the inspiration-only stance taken on `ngpepin/stylometric-transfer`.

**Also decided in this session (outside the 10-question list):**

- **`ngpepin/stylometric-transfer` (PolyForm Noncommercial 1.0.0):** inspiration only. Read for design patterns — fingerprint schema with raw distribution histograms, per-component validators, structured deviation reports, regression-suite shape — but lift no code. Reason: Shawn cannot guarantee personal-only use indefinitely, and the licence becomes a problem the moment commercial use surfaces.

---

## 10. Effort and cost estimate

**Per-phase effort (focused work hours):**

| Phase | Effort | Why |
|-------|-------:|-----|
| Phase 1 (measurement extensions + verification doc + regression) | 4–6 h | Most of the time is regression-testing against run-1 numbers; the metrics themselves are short. |
| Phase 2 (Biber relayout) | 2–3 h | Mechanical rewriting of section headers + Appendix C cross-reference. The D2 narrative-feature search may take an extra hour. |
| Phase 3 (aggregation rule formalisation) | 1–2 h | Pure documentation + algorithm sketch. Test against run-1's existing claims to confirm no status changes break. |
| Phase 4 (Panickssery exemplar block) | 2–3 h plus API spend | Implement exemplar selection scoring; 5 LLM calls; assemble. |
| Phase 5 (Mahalanobis evaluator + verification gate) | 3–4 h | Separate downstream tool. |

**Total v2 development envelope: 12–18 hours of focused work** plus one batch of ~$0.50 API spend at generation time (Phase 4 inversion).

**API spend per v2 run (Phase 4):** ~$0.50 estimate; surface for user approval before running.

**Optional Phase 5 GPTZero scans:** ~$0.05 per 1,000-word generated passage; opt-in per generation.

---

### Critical files for implementation

- `/home/shawn/.claude/agents/corpus-style-analyser.md` — current agent definition; v2 forks from here (lines 88–124 Phase 3, lines 137–207 Phase 5 output assembly, lines 208–230 anti-confabulation rules)
- `/home/shawn/personal-assistant/notes/style-guides/academic/style-guide-academic-2026-05-22.md` — empirical baseline for regression tests; Appendix C tables at lines 932–1107 are the per-claim anchors v2 must reproduce
- `/home/shawn/Code/write-like-me/scripts/stylometry.py` — informational only; the functions to re-implement under run-1 evidence discipline are at lines 199–209 (MATTR), 299–311 (paragraph stats), 314–326 (hedging), 357–363 (hapax), 388–442 (spaCy features). Do not vendor.
- `/home/shawn/Code/write-like-me/references/07-verification.md` — 8-metric verification framework lifted into v2 Appendix E
- `/home/shawn/personal-assistant/notes/style-guides/academic/write-like-me-comparator-2026-05-22/comparison-report.md` — authoritative adoption checklist (lines 119–130) and failure-mode documentation

### Sources

- [Variation across Speech and Writing — Biber 1988](https://www.cambridge.org/core/books/variation-across-speech-and-writing/A546CF5ED8F8E62F1432CB2F369CF356)
- [Catch Me If You Can — arXiv 2509.14543](https://arxiv.org/abs/2509.14543)
- [jaaack-wang/llms-implicit-writing-styles-imitation](https://github.com/jaaack-wang/llms-implicit-writing-styles-imitation)
- [Steering LLMs with Register Analysis — arXiv 2505.00679](https://arxiv.org/abs/2505.00679)
- [Whose Story Is It? — arXiv 2502.13028](https://arxiv.org/abs/2502.13028)
