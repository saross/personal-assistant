---
name: academic-prose
description: >-
  Use when drafting, revising, or reviewing academic prose — papers,
  preregistrations, grant text, supplements. Loads the project's
  register note (or the canonical register) before touching prose,
  then enforces the drafting contract: concept skeletons at target
  density, five per-sentence tests, and countable exit checks.
---

# Academic prose — delivery discipline

**Announce at start:** "I'm using the academic-prose skill; loading
the register before I touch prose."

This skill is a **delivery mechanism, not a style guide**. The
register — voice, punctuation, targets — lives in notes files and is
loaded at the gate below. The skill supplies what the notes cannot:
the gate itself, the drafting contract, the per-sentence tests, and
the exit checks. Architecture borrowed with thanks from Brian
Ballsun-Stanton's academic-writing skill (denubis-plugins), with the
register externalised per its external review (2026-07-18).

## Gate: load the register (once per session, before the first prose edit)

Read, in order, stopping at the first hit for each layer:

1. **Project register:** `ls .notes/ 2>/dev/null | grep -Ei
   'register|prose|style|voice|writing'` — read every match in full.
2. **Canonical register (always read; project notes override it):**
   `~/personal-assistant/data/notes/style-guides/academic/reference_register-academic.md`

The CLAUDE.md summary or a memory of the rules is a pointer, not the
rule. Re-open the files. This gate fires for every kind of prose
work, including a two-sentence tweak deep in a long session.

| Rationalisation | Reality |
|---|---|
| "I read them earlier this session" | A skim forty tool-calls ago is not the rule in front of you. Re-open. |
| "It's a tiny edit" | Small edits are where drift regrows fastest. Same gate. |
| "This is only a preregistration / review note" | Registered documents outlive papers. Same gate. |
| "I know Shawn's voice by now" | The mined corpus shows 4–12% sentence survival on exactly that belief. |

If the project has prose conventions not yet captured in a
`.notes/reference_register-*.md`, propose creating one at session end.

## The drafting contract

Deliverable = **concept skeleton at target density**, not polished
voice. Shawn is always the prose editor; the draft's job is to make
his edit fast. Voice-mimicry optimises the wrong objective (measured:
near-verbatim survival 4–12% on the voice-optimised Paper B draft).

Per load-bearing point, all three legs: **mechanism + one concrete
instance + honest boundary**. Per section type, opposite disciplines:
framing prose (abstract/intro/background) compresses — no rhetoric;
evidence prose (methods/results/discussion) expands — full skeleton
per point. Anchor-density targets are in the register note.

## The five per-sentence tests

Run these on every sentence drafted or revised:

1. **Subject test** (filler): is the sentence's subject the *study*
   or the *manuscript*? Manuscript-as-subject — significance
   announcements, structural narration, trailing segues,
   self-justifying appositions, colon-appended interpretive tags —
   gets cut or rewritten to state the substance. Leading roadmaps at
   section heads are exempt; backward/sideways narration is not.
2. **Skeleton test** (compression): if the sentence carries a
   load-bearing claim, do mechanism, instance, and boundary all
   appear within its paragraph? Missing legs are the largest measured
   editing cost — add them now, not "later".
3. **Anchor test** (confabulation): does every specific — number,
   name, date, origin, model identity — trace to the project record?
   If it cannot be verified this session, write `[unverified: …]`
   rather than stating it smoothly. Never invent a plausible
   specific.
4. **Density test** (starvation): does every claim running more than
   ~3 sentences carry a concrete instance? Check section density
   against the register targets before declaring a section done.
5. **Flourish test** (performed voice): figurative language,
   "not X but Y" antithesis, ornate parallelism, intensifiers,
   performed candour, identity-where-similarity — strip on sight.
   Plain, data-forward, argued with explicit connectives.

## Revision and review passes

For revision of existing prose (including reviewing a draft someone
else wrote): run the tests as a classifier, not a rewriter. Produce a
finding per flagged sentence — test failed, why, proposed fix — and
apply fixes only where the pass was requested as an edit. When a
reviewer or co-author asks to "signpost", "make explicit", or
"clarify the connection", satisfy it with substance (the claim,
stated plainly, where it belongs), never with a sentence about the
manuscript.

Never launder prior AI output: working text that looks authored may
be an unreviewed draft. Verify against the primary source before
promoting it.

## Countable exit checks (run before declaring prose done)

Run on the changed prose (adjust path):

```bash
# Em-dashes (LaTeX and Unicode), semicolons, colons
grep -o -- '---\|—' FILE | wc -l
grep -o ';' FILE | wc -l
# Booster deny-list
grep -n -iE '\b(clearly|obviously|certainly|definitely|undoubtedly)\b' FILE
# Whilst / the authors / it is important to note
grep -n -iE '\bwhilst\b|the authors\b|important to note' FILE
# Three consecutive short sentences (crude): eyeball any cluster
grep -nE '(\b\w+\b[[:space:]]+){0,4}\w+[.!?][[:space:]]+(\b\w+\b[[:space:]]+){0,4}\w+[.!?][[:space:]]+(\b\w+\b[[:space:]]+){0,4}\w+[.!?]' FILE
```

Report the counts against the register-note gate table. A deviation
is a flag for judgement, not an automatic fail — but an unreported
count is a skipped check.

## Red flags — stop if you catch yourself thinking

- "I'll add the example/gloss later." → Later never comes. Now.
- "The number is roughly right." → Anchor it or mark `[unverified]`.
- "This sentence sounds like Shawn." → Wrong objective. Is it plain,
  anchored, and skeleton-complete?
- "The section flows nicely." → Flow is his job. Density is yours.
- "It's reviewer-facing, so pre-empt the objection." → Defensive
  hedging is scar; state the design, put limits in limitations.
- "I'll skip the gate; the register hasn't changed." → The gate has
  no size threshold.

## Before declaring the prose done

- [ ] Gate run this session; register notes read in full
- [ ] Five tests run on every new or revised sentence
- [ ] Every load-bearing point skeleton-complete (3/3 legs)
- [ ] Section anchor density checked against register targets
- [ ] All specifics anchored or explicitly `[unverified]`
- [ ] Countable exit checks run and counts reported
- [ ] Changed facts/names/thresholds propagated across the project
