# Cross-agent code review — workflow design

**Status:** proposed 2026-08-26. Shared surface — Sol may review and propose
changes from an isolated worktree, per `global-agent-guidance/ownership.toml`.

**The value of this is unproven, deliberately.** Others report significant gains
from cross-vendor review; Shawn has not seen it for himself and wants to. This
document is therefore written as a trial with a question and a way to answer it,
not as a policy asserting a benefit. If the evidence does not support it, the
right outcome is to stop.

## The open question

Does review by an agent from a different vendor catch defects that
same-vendor machinery misses?

The distinction that matters:

- **Cross-tier, same vendor** (Fable authors, Opus reviews) catches slips,
  missed edge cases, and forgotten requirements. It is blind to anything both
  models get wrong for the same reason.
- **Cross-vendor** (Claude ↔ Sol) is the only configuration that can catch a
  **shared blind spot** — a wrong mental model, a bad idiom, an assumption
  inherited from similar training data.

Shawn has already ruled on this principle in a different domain. The plan for
validating LLM-generated interpretive fields requires a different vendor for
re-adjudication, on the grounds that *re-checking Claude with Claude measures
self-consistency, not correctness*
(`wiki/planning/cross-model-verification-plan-2026-07-27.md`, and the
corresponding `tasks/inbox.md` row). The same argument carries to code. What is
untested is the size of the effect.

## What this is not

It does not duplicate existing machinery. `/audit`, `/code-review`, the
verifier subagents, `phase-gate`, and `pre-run-review` already cover
correctness sweeps, adversarial verification, and pre-spend gates. Cross-agent
review is scoped to the **shared-blind-spot class** and should be judged on
that alone.

A review that only produces style preferences, restates what `/code-review`
found, or approves without comment is a failed review, not a cheap one. The
failure mode to watch for is ceremony outliving its value: everyone skims, the
step survives, and nothing is caught.

## The gate — reuse what exists

No new rulebook. `global-agent-guidance/common.md` already says branch + PR
when a change is "a schema change/migration, ~200+ lines of non-trivial logic,
touches hard-to-roll-back live state (DBs, archives, remote services), or wants
a second set of eyes."

Those are the cross-review triggers too. Everything below that line ships
without cross-review, and that must remain the common case — reviewing trivial
changes trains both agents to skim.

## Timing — tier by risk, not by clock

- **Synchronous** for anything hitting the gate above. Architectural errors
  found a day late arrive after work has been built on them, so the expensive
  findings land when they are most expensive to act on.
- **Batched** (daily is fine) for everything else, where findings are local and
  cheap to apply late.

## Patterns to pilot

Named so that outcomes can be compared. "Flexibility to explore" without named
variants produces impressions rather than evidence.

| # | Pattern | Use |
|---|---------|-----|
| 1 | Claude authors → Sol reviews | Default for agenda-driven work |
| 2 | Sol authors → Claude reviews | Work delegated to Sol |
| 3 | Claude specifies → Sol implements → Claude reviews | Spec-first |
| 4 | Sol drives extended work → Claude reviews at milestones | Sol-led projects |
| 5 | No cross-review | Must be an explicit choice, not an omission |

## Evidence capture

One line per reviewed change, or it will not get done:

    pattern | repo | reviewer | changed anything? | class | rough cost

`class` is the useful field: **blind-spot** (something same-vendor machinery
would not have caught), **ordinary defect** (it would have), **style**, or
**noise**. The trial succeeds only if the blind-spot column is non-empty.

**Phase 6 of the integration plan is the evaluation vehicle** — a two-week
operating pilot already collecting "model, effort, latency, quota pressure,
failure, rework, continuity, and merge-conflict evidence", exiting when "the
evidence supports a revised routing policy". Feed that; do not build a parallel
process.

## Budget asymmetry — a real argument, independent of quality

The Claude plan (~$200/month) is routinely exhausted; the OpenAI plan
(~$20/month) is not. Cross-vendor review is the only form of review that does
not compete with the work it reviews for the same budget. Prefer Sol as
reviewer for that reason alone, and treat spare Claude capacity as better spent
authoring.

## Prerequisites

1. **Context symmetry.** A reviewer who sees a diff without the rationale
   produces "why didn't you use X" when X was ruled out three sessions ago. PR
   bodies must carry the *why*, and the reviewing agent must read the governing
   plan and continuity before reviewing.
2. **Continuity surfacing for Sol.** As of 2026-08-25 `gpt-hub`'s only
   `SessionStart` hook surfaces agent mail, which is read-once and silent after
   receipt; `wiki/continuity.md` is current but nothing points a fresh session
   at it. Until that is fixed, cross-review is being bought from an agent with
   amnesia. Sol has this on its own next-session list.
3. **Distinct GitHub identity**, if reviews are to be native. GitHub hard-blocks
   pull request authors from approving their own PRs and no branch-protection
   setting overrides it. Two agents acting through one account cannot review
   each other in GitHub's model. See "Starting before credentials exist" for
   why this is not a blocker for the trial.

## Carve-outs — what cross-review must not absorb

Two agents agreeing is not authority. Ownership boundaries, the trust norm,
credential grants, and security posture remain Shawn's, per
`ownership.toml` ("agents attempt consensus, then Shawn decides"; loosening
requires his sign-off). Cross-review must not become the venue where those are
quietly settled.

Shawn and the Claude models continue to drive the agenda. Review is advisory;
it does not confer a veto, and a reviewing agent cannot stall work indefinitely
— disagreement escalates rather than blocks.

## Starting before credentials exist

The question "does cross-vendor review catch anything?" is separable from the
question "should Sol hold GitHub credentials?", and the first is much cheaper
to answer. Sol already has local read access to every repository on the
machine.

**Trial mode:** Sol reviews from the local checkout and writes its findings to
agent mail; the review is posted to the pull request by Shawn or Claude. This
loses native review mechanics and the approval workflow, but it exercises the
actual question at zero credential risk, and it can begin immediately.

Invest in the identity and credential work only if the blind-spot column turns
out to be non-empty.

## Open decisions

- Identity model if the trial succeeds: GitHub App versus machine user.
- Whether cross-tier same-vendor review (Fable authoring, Opus reviewing) is
  worth running as a control arm, to separate "a second reader helps" from
  "a *different vendor* helps". Without it, a positive result is ambiguous.
- Review depth: full diff versus changed-behaviour summary, for large changes.
