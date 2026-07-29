# Cross-model verification: using a non-Anthropic model as second reader

**Status:** design sketch, pre-implementation
**Created:** 2026-07-27 (evening, PA-hub session)
**Origin:** Brian's recommendation — drive OpenAI's GPT-5.6 Sol from a Claude
session, in addition to Claude's own spawned subagents
**First application:** map-reader-llm accuracy verification (drafting phase, W31+)
**Related:** `wiki/user-observations.md` 2026-07-27 Candidate 1 (two-stage
verification caught the verifier itself); Paper B adversarial-review apparatus

---

## 1. Why a *different vendor's* model, not more Claude agents

The value of adversarial verification comes entirely from the verifier having
**different failure modes** from the proposer. Claude subagents spawned from a
Claude session share training data, priors, and confabulation tendencies — *N*
Claude verifiers approximate one verifier with sampling variance, not *N*
independent checks.

This is not speculation: it is the **self-preference / similarity bias**
literature reviewed during Paper B — models systematically prefer their own
outputs, and outputs stylistically similar to their own, when acting as judges.
(Citations to be pinned from the research pass; see §7.)

Two axes of independence, and where we already are on each:

| Axis | Status | Mechanism |
|---|---|---|
| **Context** independence | **Built** (Paper B / Cosmos) | Fresh-context adversarial re-check; caught three pointer errors in the first stage's own ledger |
| **Model** independence | **Not built** — this plan | Second reader from a different vendor/lineage |
| **Human** adjudication | Exists, unstructured | Shawn resolves disagreements |

Model independence is the next axis out. Shawn's assessment: ChatGPT is
behaviourally quite distinct from Claude/Fable, which is precisely what makes it
a good second reader.

---

## 2. The integration question: how does a Claude session call another model?

### Path A — non-interactive CLI (PREFERRED, if available)

If the vendor CLI supports one-shot invocation, no cleverness is required:

```bash
sol -p "$(cat claims/claim-042.md)" > verdicts/verdict-042.md   # flags TBC
```

Properties: real exit codes, clean stdout, file-in/file-out, trivially
scriptable, parallelisable, and **reproducible** — the invocation and its output
are both artefacts that can be committed and deposited.

### Path B — `tmux` pane driving (FALLBACK, interactive-only CLIs)

Brian's described method. Two panes; the Claude session drives the other pane
via Bash:

```bash
tmux send-keys -t 0.1 'verify this claim: ...' Enter   # type into pane 1
tmux capture-pane -t 0.1 -p -S -200                    # scrape last 200 lines
```

The terminal becomes the integration layer — works with *any* interactive CLI,
no API or MCP integration needed. Genuinely useful when a tool only runs
interactively (e.g. requires an interactive login session).

**Known weaknesses** — these are why it is the fallback, not the default:

- `capture-pane` is a **screen scrape**: you get whatever is on screen at that
  moment, not a return value.
- **No completion signal** — you poll for the prompt to reappear, or sleep and
  hope. Fragile under variable latency.
- **Quoting and escaping** mangle multi-line prompts. Mitigations: write the
  prompt to a file and send a short command that reads it, or use
  `tmux load-buffer` + `paste-buffer`.
- **Poor audit artefact.** A scraped pane is a bad provenance record for a
  paper's verification trail.

### Path C — API + thin script

If Sol is API-accessible, a small script (or an MCP server exposing it as a
tool) is cleaner than either of the above and gives proper error handling,
retries, and structured output. Likely the real answer for batch work.

**Decision gate:** `sol --help` (or equivalent) settles A vs B in seconds;
API availability settles C. Resolve before building anything.

---

## 3. Architecture: what should actually be built

The critical insight is that **the job splits into two very different halves**,
and they want different tools:

### 3a. The bulk pass (~700 items) → a SCRIPT, not an agent

Mechanical, uniform, high-volume. Feeding this through LLM orchestration adds
cost, latency, and non-determinism for no benefit. A plain script that iterates
claims, calls the model, and writes per-claim verdict files is:

- deterministic and re-runnable,
- cheap (no orchestration tokens),
- auditable — every prompt and every response is a file on disk,
- resumable — skip claims whose verdict file already exists.

### 3b. The disagreements (small *N*) → the judgement layer

Where Claude's position and Sol's verdict **disagree** is where actual thinking
is needed. That is a much smaller set, and it is the right place to spend
Claude subagents, a workflow, or Shawn's own attention.

**Escalation ladder:** Claude proposes → Sol verifies → agreements pass →
disagreements go to a Claude adjudication pass → residual disagreements go to
Shawn.

### 3c. Skill vs agent vs workflow — recommendation

| Form | Use it for | Verdict |
|---|---|---|
| **Script** | The 700-item bulk pass | **Build first.** Dumbest thing that works. |
| **Skill** | The *protocol* — how to frame a claim, verdict schema, what counts as disagreement, escalation rules, provenance fields to record | **Build second.** This is the reusable asset across papers. |
| **Workflow** | Fan-out over disagreements; multi-lens adjudication | **Later, if the disagreement set is large enough to warrant it.** |
| **Subagent type** | A driver agent marshalling claims and collating verdicts | **Probably unnecessary** if the script exists. |

A subagent cannot *be* Sol — subagents are Claude. Any non-Claude model enters
through a Bash call, at whatever layer makes the call.

---

## 4. Design requirements (non-negotiable for paper use)

1. **Paired, not unpaired.** Every claim goes to both readers; verdicts are
   compared per-claim. Do not compare aggregate accuracy rates across
   independent samples — a paired design controls for between-claim difficulty
   variance and is strictly more powerful at the same *N*.
2. **Blind where possible.** Sol should not be told which position is Claude's,
   nor be shown Claude's confidence, or similarity bias re-enters through the
   framing.
3. **Full provenance per verdict**: model identifier and version, exact prompt
   (or its hash), timestamp, temperature/reasoning settings, raw response.
   Committed to git, per the standing "all API-run outputs must be committed"
   rule.
4. **Structured verdict schema** — not free prose. Minimum: `agree` /
   `disagree` / `uncertain`, plus a stated reason and, where applicable, the
   corrected value. Machine-comparable.
5. **Disagreement rate is itself a result.** Log it. It is a reportable
   methodological metric, not just an internal QA number — and it is directly
   relevant to the llm-reproducibility project.

---

## 5. Cost gate

A ~700-item batch against a paid model is **API spend and requires the standing
review gate before any run**: model, batch vs real-time, exact call count,
estimated total cost. A pilot on ~20 claims should precede the full run — enough
to measure the disagreement rate, sanity-check the prompt, and extrapolate cost
honestly.

Note the aggregate framing: 700 calls at even a few cents each is modest, but
700 × a long reasoning response is not necessarily so. Compute the total before
committing, not the per-unit.

---

## 6. Methodological upside

Cross-model verification is potentially **reportable as a method** in the
map-reader paper, not merely an internal QA step — and it is squarely on the
llm-reproducibility project's territory. Worth deciding early whether to
instrument it for reporting, because retrofitting provenance after the fact is
expensive and partial.

---

## 6a. Research findings, 2026-07-27 (background agent pass)

Full report in the session transcript; the load-bearing points, with the agent's own
verification status preserved. **Two OpenAI marketing pages returned HTTP 403 to the
agent's fetcher (`openai.com/index/previewing-gpt-5-6-sol/` and the GA post) — anything
sourced only to those is unconfirmed and must be checked in a browser before being
quoted anywhere citable.**

**The access question is settled, and the answer is "none of the above".** An official
OpenAI CLI exists (Codex CLI, `codex exec`) and *does* support non-interactive one-shot
invocation with schema-constrained output — so Path A is technically available and Path
B (tmux) is unnecessary. **But the CLI is an agentic harness** (sandbox, tool loop, repo
indexing), which injects exactly the nondeterminism a verification instrument must not
have. Worse, there is published third-party evidence that Sol *measures differently
depending on the harness it runs inside* — so an agent-CLI comparison partly measures
the harness, not the model.

**Recommended path is C: the raw Batch API.** Model ID `gpt-5.6-sol`; Batch is 50% off
standard rates; estimated **~US$10–45 total for 700 calls** depending on prompt size and
reasoning effort. Cost is not a design constraint here — reasoning-effort choice
dominates it.

> **Pricing verified at source (2026-07-29, map-reader GATE 0).** Official page
> `https://developers.openai.com/api/docs/pricing` (PI-supplied): `gpt-5.6-sol`
> standard **$5.00 / $0.50 / $6.25 / $30.00 per M tokens** (input / cached read /
> cache write / output); **Batch is 50% off all four token types**, and the Batch
> table itself prices cached input — batch + cache-read discounts stack. Stacked:
> **$2.50 / $0.25 / $3.125 / $15.00 per M**. Long-context columns ($10/$1/$12.50/$45)
> don't trigger at verification call sizes. Empirical per-call model (map-reader
> `reports/verification/phase0-scope.md` § 4.3): ~$0.02 medium effort, ~$0.05 high,
> **~$0.10 absolute worst case** (fat source context + long reasoning). Re-verify at
> each API review gate before spend.

**Do NOT upgrade the ChatGPT subscription for this.** A consumer subscription does not
grant API access (separate billing; Tier 1 needs US$5 paid), and subscription-metered
access is throttled per-window — 700 calls through it would take tens of hours of
wall-clock throttling. The subscription remains useful for interactive spot-checks of
disputed items.

**Three findings that change the design, not just the plumbing:**

1. **Sol's own system card flags the exact failure mode a verifier must not have** —
   "instances where the model claimed completed work without verification". Mitigation
   is structural, not prompt-polish: the verdict schema must **require a verbatim
   evidence span quoted from the supplied source**, so a bare assertion cannot validate.
2. **Similarity bias is graded, not binary** (Goel et al. 2025, arXiv:2502.04313 — CAPA;
   "LLM-as-a-judge scores favor models similar to the judge"). Cross-vendor *reduces*
   the bias; it does not eliminate it. Consequences: do not claim independence as
   binary; prefer verification tasks with checkable ground truth over preference
   scoring; and consider a **third family (e.g. Gemini) for disputed items**, since
   two-way disagreement yields no tiebreaker.
3. **No dated model snapshot IDs are published** for Sol. The run cannot be pinned to a
   version string. The *only* reproducibility anchor is a per-call log of the returned
   model string, request ID, full request/response JSON, and run date — which raises
   §4's provenance requirement from good practice to load-bearing.

**Citations for the methods section** (all verified by the agent against the primary
record): Panickssery, Bowman & Feng 2024 (NeurIPS 37, arXiv:2404.13076) — foundational,
self-recognition correlates with self-preference; Goel et al. 2025 (arXiv:2502.04313,
preprint) — the graded-similarity result above; Xu et al. 2024 (ACL 2024, pp.
15474–15492, DOI 10.18653/v1/2024.acl-long.826) — self-refinement *amplifies* self-bias,
external feedback reduces it; Wataoka, Takahashi & Ri 2024 (arXiv:2410.21819, NeurIPS
Safe GenAI workshop) — perplexity/familiarity mechanism. Background: Zheng et al. 2023
(NeurIPS 36, arXiv:2306.05685), origin of "self-enhancement bias".

**Left on the table:** `gpt-5.6-terra` is half Sol's price and would run the job for
~US$5–10. A cheaper verifier is a weaker one, and the saving is trivial at this volume —
but a 30-item Sol-vs-Terra agreement pilot would settle it empirically rather than by
assumption.

---

## 7. Open questions — resolve before building

- [x] **Official CLI + non-interactive mode?** Yes (Codex CLI, `codex exec`) — but
      rejected as the driver; agentic harness adds nondeterminism. Resolved 2026-07-27.
- [x] **API + model identifier?** Yes — `gpt-5.6-sol` (alias `gpt-5.6`). Resolved.
- [x] **Subscription tier / rate limits?** Don't upgrade the subscription; open a
      separate API account. Tier 1 limits are ample for 700 calls. Resolved.
- [x] **Context window?** Not a constraint at this scale. Resolved.
- [x] **Structured output?** Supported (JSON Schema). Resolved.
- [x] **Self-preference/similarity-bias citations?** Pinned in §6a. Resolved.
- [ ] **Verify the two 403'd OpenAI pages in a browser** before quoting anything from
      them in citable text.
- [ ] Confirm Sol's supported `reasoning.effort` values and default **empirically** —
      not documented. Record whatever is used.
- [ ] Confirm whether `seed` / `system_fingerprint` determinism applies to Sol —
      NOT FOUND by the research pass. Assume non-deterministic until shown otherwise.
- [ ] Chase the unconfirmed third-party claim that Sol shows *higher* hallucination
      rate alongside its accuracy uplift. If it holds, it cuts against using Sol as a
      factuality authority and the design needs rethinking.
- [ ] **What exactly are the map-reader accuracy problems, and which are verifiable by
      a second reader without access to the underlying imagery?** **This scopes
      everything above** and remains unanswered — the true blocker.

## 8. Build order (revised post-research)

1. **Scope the claims** (blocked on the last open question above).
2. **Pilot ~30 items**: two reasoning-effort levels, and optionally Sol vs Terra, to
   measure disagreement rate and fix cost per item empirically.
3. **API review gate** with real numbers from the pilot.
4. **Batch run** the full set; per-call provenance log committed to git.
5. **Skill** encoding the protocol (claim framing, verdict schema with mandatory
   verbatim evidence span, escalation ladder, provenance fields).
6. **Third-family tiebreak** on disputed items, if the disagreement set warrants it.
