# LLM-History-Paper — Split Execution Plan

## Context

Following the 2026-04-15 strategic pivot from one paper to two (Stage 0
atom extraction and Stage 0.5 destination routing pipeline shipped:
commits 32a4a46, ffabbd2, 81891a6), this plan decomposes the remaining
work into task-sized slot items.

This is the first use of the revised task-system convention introduced
2026-04-18: focus slots hold tasks sized 1h–1wk, days-in-focus counts
against the current task, and when a task completes the next one
rotates in under the same project tag.

Project tag for all tasks below: **research/llm-history-paper**

## Paper A track (Shawn builds, hands to Brian)

Sequential execution — each task feeds the next. Total estimate: ~3 days.

| # | Task | Estimate | Deliverable |
|---|------|---------:|-------------|
| A1 | Complete Paper A assembly from Stage 0.5 routing outputs | 1 day | Draft manuscript with all Paper-A-routed atoms integrated |
| A2 | Run Paper A through infrastructure pass — lit-scout for unsupported claims + llm-reproducibility pipeline for implicit arguments | 1–2 days | Annotated draft with claim audit log |
| A3 | Handover to Brian — clean manuscript + feedback summary + outstanding-question notes | 0.5 day | Shared draft + email to Brian |

## Paper B track (Shawn's focus after A3 handover)

| # | Task | Estimate | Deliverable |
|---|------|---------:|-------------|
| B0 | Set up Paper B repo with Overleaf submodule integration (reuse pattern from `2026-mq-llm-dh-ideation-writing`) | 0.5 day | Working repo + Overleaf sync confirmed |
| B1 | Complete Paper B assembly from Stage 0.5 routing outputs | 1–2 days | Draft manuscript with Paper-B-routed atoms integrated |
| B2 | Adapt to the yesterday's reframing — failure taxonomy + prompt-engineering-as-method + researchers' workbench contributions | 1–2 days | Restructured draft matching the three-contribution frame, with verified Paper B BibTeX integrated |
| B3 | Infrastructure pass — lit-scout for gaps + llm-reproducibility for unsupported claims + adversarial review from Claude | 1–2 days | Annotated draft with verification trail |
| B4 | Prepare for submission — formatting to JASIST style (≤7k words) or IP&M (if over), cover letter, submission checklist | 0.5 day | Submission-ready manuscript + cover letter |

## Sequencing notes

- **A1–A3 must complete before B0 starts.** Brian is waiting on Paper A;
  delaying his handover to work on Paper B's repo plumbing is backwards.
- **B0 is infrastructure, not writing.** Half a day to set up the Overleaf
  submodule pattern. Do this once; write in it for B1–B4.
- **B2 is the largest conceptual task.** The reframing (failure taxonomy,
  prompt engineering as method, researchers' workbench) is where Paper B
  earns its three contributions. Don't rush this.
- **B3's adversarial review** is the analog of what lit-scout-verifier
  does for bibliographies — independent-context critique that catches
  what the same-context self-check misses. Spawn a dedicated subagent
  for it.

## Focus slot rotation

As each task completes, Slot 1 rotates:

```text
Day 1:    Slot 1 = A1 (assembly)
Day 2-3:  Slot 1 = A2 (infrastructure pass)
Day 4:    Slot 1 = A3 (handover)
          → A3 closes Paper A for Shawn; Brian takes over
Day 5:    Slot 1 = B0 (repo setup)
Day 6-7:  Slot 1 = B1 (Paper B assembly)
...
```

Days-in-focus counts from each task's start. Paper A's A1 at day 1, not
day 19. This is the point of the revised convention.

## Reference

Previous Overleaf submodule pattern: `~/Code/2026-mq-llm-dh-ideation-writing/`
(check for the submodule config and any notes there).

## Trigger conditions

- A1 becomes active immediately once current focus slot 1 is re-scoped
- B0 is gated on A3 completion (Brian handover)

## Out of scope (handled separately)

- Promote the paper-split pipeline to a permanent skill — already in
  backlog (row added 2026-04-15)
