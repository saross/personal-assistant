---
name: review-implementation
description: "Structured review protocol for catching suboptimal implementations and methodology choices. Use when completing a significant new integration, adopting a new tool or method, or at phase boundaries in a project. Surfaces both 'discovery failures' (capabilities not yet considered) and 'exploitation failures' (capabilities known but underutilised). Invoke with /review-implementation."
---

# Implementation and Methodology Review

Structured protocol for ensuring that a newly implemented approach — whether an API
integration, statistical method, data processing pipeline, experimental design, or any
significant technical decision — uses the full capability envelope rather than defaulting
to the first working solution.

## When to Use

- After implementing a significant new integration or methodology
- At phase boundaries when establishing infrastructure for a new stage of work
- When adopting a new tool, API, library, or analytical technique
- When the user explicitly invokes `/review-implementation`
- When you (CC) recognise mid-implementation that you've made a significant design
  choice that the user may not have the domain expertise to evaluate
- Proactively, when the aggregate implications of an approach haven't been stated

## Background: The Discovery/Exploitation Pattern

Human–AI collaboration has two distinct failure modes when adopting new approaches:

1. **Discovery failure**: Not knowing a capability or method exists. Addressed by
   capability scanning — broadening the search space before committing.

2. **Exploitation failure**: Knowing a capability exists but implementing it
   conservatively, without using the full available configuration space. This is
   harder to catch because the implementation works correctly — it's just suboptimal.

Both failure modes are especially likely in domains where the human collaborator is
not the primary expert (e.g., programming, statistics, API design, systems
architecture). The first methodologically sound approach is often accepted without
surveying the solution space for strictly better alternatives.

## Protocol

Work through each phase in order. For each phase, state your findings explicitly —
do not skip phases even if they seem unnecessary.

### Phase 1: Capability Scan (What Else Exists?)

Survey the full solution space for the domain in question. Ask:

- **APIs/services**: Are there alternative execution modes (batch, streaming, async),
  tiers, or features we haven't considered? Check the full API surface, not just the
  endpoints we're currently using.
- **Statistical methods**: Are there alternative tests or estimators that are strictly
  more powerful, more appropriate for our data structure, or better suited to our
  hypothesis? (E.g., paired vs unpaired tests when observations are naturally paired;
  Bayesian vs frequentist approaches; exact vs asymptotic methods for small samples.)
- **Programming patterns**: Are there alternative architectures (parallel vs serial,
  batch vs streaming, lazy vs eager) that better fit the workload characteristics?
- **General**: What would a domain expert consider the standard best-practice approach
  for this type of problem? Does our approach match it?

Report any alternatives found, with a brief assessment of whether they would be
materially better for our specific use case.

### Phase 2: Exploitation Review (Are We Using It Fully?)

Examine the current or proposed implementation against the full capability envelope:

- **Concurrency and parallelism**: Are we processing sequentially when parallel
  execution is available? What are the concurrency limits, and how much of the
  available capacity are we using?
- **Batch and bulk operations**: Are we making individual calls when batch endpoints
  exist? Are we using the maximum batch size?
- **Configuration space**: Have we accepted default parameters without checking
  whether alternatives would be better? (E.g., default significance levels, default
  chunk sizes, default timeout values, default model hyperparameters.)
- **Error handling and resilience**: Does the implementation handle partial failures
  gracefully, or does a single failure cascade into retrying the entire operation?
- **Cost optimisation**: Are there pricing tiers, reserved capacity options, or
  discount modes (e.g., batch pricing, spot instances) that reduce cost for our
  usage pattern?

For each dimension, state whether the current implementation is using the full
capacity or leaving gains on the table.

### Phase 3: Quantitative Audit (What Does It Actually Cost?)

Compute the total resource implications of the current approach and compare with
the best alternative from Phases 1–2:

- **Wall-clock time**: Total elapsed time from start to finish, including worst-case
  failure/retry scenarios. State the formula (N items × L latency × R expected
  retries).
- **Monetary cost**: Total spend, not per-unit cost. Include failure costs.
- **Human attention cost**: Does the approach require human monitoring or
  intervention? How often? What happens if the human is unavailable?
- **Failure cascade cost**: If one unit fails, what is the recovery cost? Does serial
  processing mean a failure at unit 60/70 requires restarting from unit 60, while
  parallel processing would have all other units already complete?

Present as a comparison table where possible:

| Dimension | Current approach | Alternative | Difference |
|-----------|-----------------|-------------|------------|
| Wall-clock time | ... | ... | ... |
| Monetary cost | ... | ... | ... |
| Failure resilience | ... | ... | ... |

### Phase 4: Recommendation

Based on the above, provide a clear recommendation:

- **No change needed**: The current approach is at or near the optimum for our use
  case. State why.
- **Low-effort improvement**: A configuration change or minor refactor would yield
  material gains. Describe the change and the expected improvement.
- **Significant redesign warranted**: A different approach would be substantially
  better, but requires meaningful implementation effort. Describe the approach,
  the expected gain, and the implementation cost. Let the user decide.

## Domain-Specific Checklists

### API/Service Integrations

- [ ] Checked for batch/bulk endpoints
- [ ] Checked concurrency limits and parallel submission options
- [ ] Checked for different pricing tiers (batch, spot, reserved)
- [ ] Computed total wall-clock time at aggregate level
- [ ] Checked for async/webhook options vs polling
- [ ] Reviewed rate limit structure (per-request vs per-minute vs daily)

### Statistical Methodology

- [ ] Checked whether paired tests are available for paired data
- [ ] Checked whether exact tests are appropriate for small samples
- [ ] Checked whether multiple comparison corrections are needed
- [ ] Verified that the test's assumptions match the data structure
- [ ] Considered whether Bayesian alternatives offer advantages
- [ ] Computed statistical power for the chosen test and sample size

### Data Processing Pipelines

- [ ] Checked whether operations can be parallelised
- [ ] Checked whether intermediate results can be checkpointed
- [ ] Verified that failure handling is granular (per-item, not per-batch)
- [ ] Checked whether streaming/lazy evaluation would reduce memory usage
- [ ] Computed total processing time at aggregate level

### Experimental Design

- [ ] Checked whether blocking or stratification would improve power
- [ ] Verified that the control condition is appropriate
- [ ] Checked whether adaptive or sequential designs are applicable
- [ ] Computed required sample size for target power
- [ ] Reviewed whether confounds have been adequately controlled

## Standards

- UK/Australian English throughout
- Be specific and quantitative — avoid vague qualitative assessments
- State the aggregate numbers, not just per-unit figures
- Present trade-offs honestly — don't oversell alternatives
- Flag when you lack confidence in a recommendation (e.g., "I believe paired
  permutation tests are more appropriate here, but I'd recommend verifying
  with a statistician for this specific design")
