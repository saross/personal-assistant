---
name: phase-gate
description: "Experimental phase boundary checkpoint. Use before committing API spend, compute, or time to a new experimental phase — especially when scaling from pilot to production, applying a configuration selected on a subset to a larger dataset, or transitioning between optimisation and evaluation phases. Surfaces under-powered assumptions from prior phases and determines whether cheap validation is needed before proceeding. Trigger phrases: 'ready to run', 'start Phase X', 'scale up', 'production run', 'let's proceed with'. Also trigger PROACTIVELY when recognising a phase boundary, even if the user does not invoke it explicitly."
---

# Phase Gate: Experimental Assumption Checkpoint

Structured protocol for catching under-powered assumptions before they become
expensive mistakes. Complements `/review-implementation` (which checks whether
the *approach* is optimal) by checking whether the *decisions feeding the
approach* are validated at the power level required for the next phase.

## When to Use

- Before committing API spend or compute to a new experimental phase
- When scaling from a pilot or subset to full-corpus evaluation
- When applying a configuration selected on one dataset to a different or
  larger dataset
- When transitioning from parameter optimisation to production runs
- When the user says "let's run this", "ready to proceed", or similar
- **Proactively**: When you (CC) recognise a phase boundary, even if the
  user does not explicitly invoke this skill

## Why This Exists

Human-AI experimental workflows have a specific failure mode: a decision made
on a small sample (wide confidence intervals, overlapping alternatives) gets
carried forward as settled fact into a larger and more expensive phase. The
decision *feels* validated because it was data-driven — but the data didn't
have the statistical power to distinguish between alternatives.

This is distinct from:

- **Not knowing an alternative exists** (caught by `/review-implementation`)
- **Choosing the wrong method** (caught by domain review)
- **Implementation bugs** (caught by testing and audits)

The failure mode here is: **the right question was asked, the right method was
used, but the sample was too small to give a definitive answer — and nobody
noticed before scaling up.**

## Protocol

Work through each step in order. Present findings as a table at the end.

### Step 1: Enumerate Assumptions

List every prior result or decision that the upcoming phase depends on.
Be exhaustive — include decisions that seem obvious.

For each assumption, record:

- **What was decided** (e.g., "adversarial verifier is the best strategy")
- **What evidence supports it** (e.g., "F1=0.796 on 60-tile pilot")
- **What alternatives were considered** (e.g., "brief, checklist, adversarial")

### Step 2: Power Check

For each assumption from Step 1:

- **Sample size**: How many observations supported the decision?
- **Confidence intervals**: Were the CIs narrow enough to exclude alternatives?
- **Overlap**: Did the best option's CI overlap with the runner-up?

Flag assumptions where:

- CIs overlap between the chosen option and alternatives
- Sample size was < 100 (for proportion-based metrics like F1)
- The decision was made on a convenience sample or subset

Mark each assumption as:

- **Validated** — CIs do not overlap, adequate power
- **Under-powered** — CIs overlap or sample too small
- **Untested** — no direct comparison was made

### Step 3: Cheapest Validation

For each under-powered or untested assumption:

- What is the **minimum cost** to validate at full power? (Time, money, API calls)
- What is the **cost of proceeding without validation**? (Total spend in the
  upcoming phase that depends on this assumption)
- What is the **cost ratio**? (validation cost / phase cost)

A validation that costs 1% of the phase budget and takes 10 minutes is almost
always worth running.

### Step 4: Consequence Check

For each assumption: **if validation shows we chose wrong, what changes?**

- **"Nothing changes"** — The assumption is not load-bearing for this phase.
  Skip validation even if under-powered. (Example: we chose blue plots over
  red plots — the analysis is the same either way.)
- **"We'd need to re-run some experiments"** — Partial rework. Validate if
  cheap. (Example: we'd need to re-run 3 of 20 configs with a different
  parameter.)
- **"We'd need to re-run the entire phase"** — Full rework. Validation is
  mandatory regardless of cost. (Example: all 20 experiments used the
  wrong verifier strategy.)

### Step 5: Decision

Present the summary table and recommend:

- **Proceed** — All assumptions validated or non-load-bearing
- **Validate first** — List the specific validations to run, with cost and time
- **Reconsider** — A fundamental assumption is untested and load-bearing;
  the phase design may need revision

## Output Format

```text
## Phase Gate: [Phase Name]

| # | Assumption | Source | Status | Validation cost | If wrong... |
|---|------------|--------|--------|-----------------|-------------|
| 1 | ... | ... | Validated | — | — |
| 2 | ... | ... | Under-powered | $X, N min | Re-run phase |
| 3 | ... | ... | Untested | $Y, N min | Partial rework |

**Recommendation**: [Proceed / Validate first / Reconsider]

**Validations to run before proceeding:**
1. [Specific validation, cost, time]
2. [...]
```

## Standards

- UK/Australian English throughout
- Be specific and quantitative — state sample sizes, CI widths, costs
- Present the table even if all assumptions are validated (confirms the check
  was thorough)
- Do not skip steps — even "obvious" assumptions should be listed
- Flag when statistical power cannot be assessed (e.g., qualitative decisions)
  and note the basis for the decision instead
