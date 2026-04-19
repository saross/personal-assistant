# llm-reproducibility — Headless Pipeline for 25-Paper Batch

## Context

The llm-reproducibility pipeline was carefully decomposed into manageable
chunks in October 2025 to fit the LLM agency capabilities of the time.
Post-2026-04 CC/Agent upskilling, the decomposition is still sound but
the orchestration can move from manual invocation to automated headless
batches. Goal: run reproducibility experiments on ~25 papers soon,
without each paper requiring an interactive session.

## Approach: shell pipeline with headless CC

Each existing stage becomes a shell script that invokes Claude Code
non-interactively via `claude -p`. A driver script loops over the 25
papers. The decomposition work is done; this is wrapping.

### Proposed structure

```text
llm-reproducibility/
├── scripts/
│   ├── stage-1-extract-methods.sh    # claude -p "<extract methods prompt>"
│   ├── stage-2-classify-claims.sh    # claude -p "<classify claims prompt>"
│   ├── stage-3-identify-reprod.sh    # claude -p "<identify reprod targets>"
│   ├── stage-4-generate-protocol.sh  # claude -p "<generate protocol>"
│   ├── verify-stage.sh               # /audit-style verifier per stage
│   ├── run-paper.sh                  # driver: all stages for one paper
│   └── run-batch.sh                  # outer loop: 25 papers, parallelism-capped
├── state/
│   └── <paper_id>/
│       ├── stage-1-in.json
│       ├── stage-1-out.json
│       ├── ...
│       └── status.json               # which stages complete
└── logs/
    └── <paper_id>/
        └── stage-N.log
```

## Design principles

1. **Idempotency.** Every stage: if valid output file exists, skip.
   Enables resume from failure without rework.
2. **Stage gates.** Each stage output passes through a verifier
   (`/audit`-style subagent) before the next stage starts. Interactive
   mode catches problems in real-time; headless cannot.
3. **Structured output.** Use `--output-format stream-json` for
   machine-parseable results. Stage N's JSON output becomes stage N+1's
   input.
4. **Parallelism cap.** GNU parallel with `-j 3` or `-j 5` to avoid
   Max-plan rate limits. 25 papers × ~4 stages is bounded work.
5. **Cost gate before batch.** Run one pilot paper end-to-end in
   interactive mode first. Measure wall-clock and tokens.
   Multiply × 25 for batch estimate. Confirm with Shawn before
   launching the full batch (per API gate discipline in preferences).

## Implementation sequence

1. **Wrap existing decomposition** — convert each stage's current
   invocation pattern into a shell script calling `claude -p`
2. **Add stage verifier** — `/audit`-style subagent that validates
   stage output structure and content plausibility
3. **Build driver** — `run-paper.sh <id>` runs all stages with
   idempotency checks
4. **Build batch driver** — `run-batch.sh` iterates over the 25
   papers with capped parallelism
5. **Pilot on one paper** — end-to-end, measure cost, verify outputs
6. **API gate** — present batch cost estimate to Shawn before running
7. **Run 25 papers** — `nohup bash run-batch.sh papers/*.pdf > batch.log 2>&1 &`
8. **Review outputs** — spot-check random papers, flag any that need
   re-run

## Scoping estimate

- Stages 1-4 wrapping: 2-3 hours
- Pilot paper: 30 min calibration
- Batch execution: overnight (depending on stage cost × 25)
- Total wall-time to first batch result: 1 day

## Non-obvious considerations

- **Stage verifier is not optional.** Bad stage N output silently
  corrupts stage N+1 input. Interactive mode catches this; headless
  doesn't. Budget for the verifier explicitly.
- **Paper IDs must be stable.** If paper IDs are re-derived at each
  stage, idempotency breaks. Assign stable IDs (DOI or content hash)
  once, early.
- **Logs must be diffable.** Stream-json logs should be one JSON
  object per line so `jq` can extract specific stage outputs without
  re-parsing everything.
- **Auth for headless.** `claude -p` uses the same credentials as
  interactive CC; no additional auth needed on Max plan. But if the
  batch runs on sapphire/amd-tower rather than zbook, the credentials
  file must exist on that machine (or the user must be logged in).

## Trigger conditions

This task becomes active when:
- 25 candidate papers are identified and in the papers/ directory
- llm-reproducibility decomposition is confirmed stable (no
  recent changes to the stage prompts)
- Shawn has ~3 hours of focused time to wrap the stages + pilot
