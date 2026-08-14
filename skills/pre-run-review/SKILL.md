---
name: pre-run-review
description: "Interactive pre-run review of a longer-running automated block. Use BEFORE launching any multi-item automated pipeline that will run largely unattended — a recompute queue, a migration, a batch campaign, a multi-session analysis programme. Walks the operator through six structured sections (artefacts, finished states, stop states, dependency structure, partial-completion semantics, verification stack) as a dialogue, capturing hardenings into the block's controlling document. Trigger phrases: 'pre-run review', 'audit this block', 'what will this produce', 'what are the tripwires', 'walk me through the run plan', 'deeper dive before we run'. Also trigger PROACTIVELY when about to start an automated block expected to span more than one session or more than ~5 chained items without human review between them."
---

# Pre-Run Review: Interactive Audit of an Automated Block

A structured dialogue run *before* a longer automated block executes,
with two co-equal purposes:

1. **Hardening** — surface unstated orderings, missing gates, and
   unverified assumptions while they are still cheap to fix.
2. **Operator comprehension** — the human running the project should
   understand, at this level of detail, what is about to happen. That
   understanding is a deliverable, not a by-product.

Origin: map-reader Session 131 (2026-08-14). One sitting of this
dialogue before a five-item recompute queue produced four hardenings —
a coherence ordering between two overlapping items, a
one-commit-per-document rule, a countable completeness gate against
mixed-vintage artefacts, and a layered verification stack calibrated
to the project's measured claim-defect rate (~8% of decisively
recomputable claims mismatched; 619 of 7,894 in the C4 programme).
Refined the same day from an external Opus review: the verifier
denominator requirement, the disagreement rule, cold derivation for
answer-shaped claims, and the naive-reviewer stance.

## The Naive-Reviewer Stance

The questions that produce hardenings come from ignorance, not
expertise. "Does item 3 depend on item 2?" is askable only by someone
who does not already believe they know — a reviewer with full project
context tends to nod at the dependency structure, which is the one
section where nodding is most expensive. So: **ask the obvious
question anyway, including questions whose answers you believe you
already know.** The cost of asking is one sentence; the cost of
assuming is a re-run. When this review is conducted by a
project-embedded agent rather than the human operator, either hand
§§ 4–5 to a fresh-context reviewer or adopt the stance explicitly and
answer each question from the artefacts, not from familiarity.

## When to Use

- Before starting an automated block expected to run across sessions,
  or more than ~5 chained items without human review between items
- Before delegating a pipeline to background agents or scheduled runs
- When the user asks what a planned block will produce, or what its
  stop conditions are
- **Proactively** at the boundary — do not wait to be asked

## Future Work (noted 2026-08-14, PI)

An automated clean-context agent pass (Opus-class) as a *standing
complement* to the operator's review — never a replacement for it.
Rationale: the first external Opus review of a pre-run stack returned
three actionable gaps (verifier denominator, disagreement rule, cold
derivation) that neither the drafting agent nor the operator had
surfaced, precisely because a clean context has no stake in the
draft's framing. Design sketch when this gets built: run the agent
review AFTER the operator dialogue (so it audits the hardened
contract, not the draft), brief it with the naive-reviewer stance,
and require it to report its denominator like any other verifier.

## Relationship to Sibling Skills

- `/phase-gate` asks whether the *decisions feeding* the next phase
  carry enough statistical power. Run it first at experimental phase
  boundaries.
- `/audit-config` checks *configuration correctness* against protocol
  before API spend.
- `/pre-run-review` (this skill) checks the *execution structure* of
  the block itself: what it emits, when it is done, when it must halt,
  and how its claims get verified. The three chain naturally:
  phase-gate → audit-config → pre-run-review → launch.

## Protocol — Six Sections

Run as a conversation, not a lecture: present each section, invite
probing, and capture every hardening the dialogue produces. Ground
every claim in the actual scripts, documents, and data — open the
code and check output paths rather than reciting from memory; a
review built on recalled filenames inherits the ~1-in-10 error rate
it exists to catch.

### 1. Artefact inventory

For each item in the block: what files, records, or registrations it
produces, where they land, and which existing documents it refreshes.
Name the cross-cutting artefacts too (manifests, changelogs, registers
that tick over). Verify output paths from the emitting code.

### 2. Finished states

A countable completion criterion per item and for the block overall
("8/8 cells carry both metrics against the new reference, drift-check
clean" — never "looks done"). State where the finish line sits
relative to human sign-off: authored-and-committed is usually the
automation's finish; approval gates belong to the operator.

### 3. Stop states (tripwires)

Enumerate the halt-and-escalate conditions explicitly. Common classes:

- **Spend**: any unplanned API or compute cost migrates the item to a
  gated queue — hard stop, never absorb silently
- **Invariant breakage**: a gate battery, census test, or lint that
  must stay green; red means stop before building anything on top
- **Surprising results**: a rank flip, a headline moving beyond its
  documented uncertainty band, a direction reversal — a finding, not
  a formality; verify the pipeline, then escalate to the operator
- **Missing or ambiguous inputs**: stop rather than substitute a
  near-enough source — substitution is how reference taints happen
- **Sequencing violations**: downstream items must not start early
- **Environment**: compute placement, host availability — check,
  never silently fall back

### 4. Dependency structure

Draw the DAG. Distinguish **hard data dependencies** (item B consumes
item A's outputs) from **artefact-coherence orderings** (A and B would
each produce a copy of the same artefact; order them so exactly one
does). State which items are genuinely simultaneous-safe. Coherence
orderings are the ones nobody writes down and the first thing a
parallel execution breaks.

### 5. Partial-completion semantics

What happens if an item stops halfway: is the computation
deterministic and resumable from committed inputs? Is partial state
*visible* (missing rows, absent changelog entries) or silent? Name the
mixed-vintage risk — a downstream item consuming an upstream item that
is only partly refreshed — and gate it with the countable criteria
from § 2. For prose artefacts, adopt the one-commit rule: a document's
numbers and its changelog entry move in one commit, so no document
ever straddles two states across a commit boundary.

### 6. Verification stack

Layers, calibrated to measured error rates at each boundary (use the
project's own figures where they exist; the synthesis boundary —
numbers flowing from computation into prose — typically runs ~1 in 10
and deserves the heaviest layer):

- **Layer 0**: machine-readable results first; prose cites them; every
  checkable specific carries a source anchor. This layer reads like a
  preliminary; it is the foundation, and the one to protect under time
  pressure — without anchors, Layer 2 has nothing to re-derive against
  and Layer 3 has nothing to sweep
- **Layer 1**: code-level — tests, linters, audit pass on new scripts
- **Layer 2**: blind fresh-context verification — an agent that has
  not seen the drafting reasoning re-derives every checkable claim
  from committed artefacts and returns a corrections table.
  Non-negotiable for the block's highest synthesis-density item;
  proportionate elsewhere. Three requirements that keep it
  verification rather than confirmation:
  - **Report the denominator.** A clean pass and a lazy pass produce
    the same empty corrections table. The verifier must report what it
    checked — claims identified, claims re-derived, artefacts opened.
    "0 corrections across 34 re-derived claims" is evidence; "no
    corrections found" is not. (Precedent: a folder-health gate that
    called a nonexistent CLI subcommand and reported clean; only fault
    injection exposed that it was checking nothing.)
  - **Corrections are claims, not verdicts.** The ~1-in-10 rate
    applies to the verifier too, and a wrong correction that lands
    automatically carries the verification layer's authority, making
    it harder to catch than the original error. Name the disagreement
    rule up front: a correction that conflicts with the draft triggers
    a third re-derivation from the data (or operator adjudication) —
    never "the verifier wins" by default.
  - **Ask answer-shaped questions cold.** Directionality and
    winner claims are put to the verifier as questions ("which
    configuration wins on each metric?"), derived cold from the metric
    files and then diffed against the prose — never handed over as
    statements to check. A verifier anchored on the answer before it
    starts is confirming, not verifying. Same pattern for comparison
    tables: rebuild independently from the sources, then diff
- **Layer 3**: mechanical cross-document consistency — drift checks,
  citation-site sweeps for every number that moved
- **Layer 4**: operator gates — sign-off fields, accept/edit/discard
  reviews, slow-lane claim-extraction programmes

## Exit

The review ends with three things, or it did not happen:

1. **Recorded hardenings** — every rule or gate the dialogue produced,
   written into the block's controlling document (the queue register,
   spec, or plan — not left in chat scrollback), with a changelog
   entry
2. **An explicit go / no-go** from the operator
3. **The comprehension check, inverted** — the operator can state the
   block's stop conditions back; if they cannot, the review is not
   finished, whatever the checklist says
