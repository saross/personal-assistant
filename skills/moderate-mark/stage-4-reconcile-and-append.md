# Stage 4 — Reconcile and append

You are running Stage 4 of the `moderate-mark` pipeline. Your job is
to reconcile the Stage 2 (upward) and Stage 3 (downward) findings,
write the final mark recommendation, fill the verdict line at the
top of the dossier, and append the marker-comment paste-ables.

This stage is unified in v0.1.x (reconcile + polished comments +
borderline comments + verdict in one agent run). If during the build
you find this prompt grows unwieldy, splitting into Stage 4a
(reconcile + verdict + final mark recommendation) and Stage 4b
(polished comments + borderline comments) is the documented v2 path.

Apply Discipline Rules 1, 2, 4, 5, 6, 7, 10.

## Inputs

| Input | Path |
|---|---|
| Stage 1+2+3 dossier (in place) | `reports/marking/dossiers/<stem>-<submission-id>.md` |
| Marker tier picks | `reports/marking/a2-shawn-marks/<stem>-*.md` |
| Submission body text | `data/submissions-lit-review/extracted/<stem>-*.txt` |
| Rubric definition | `reports/marking/a2-rubric-definition.json` |
| Discipline rules | `discipline-rules.md` (re-read 1, 2, 4, 5, 6, 7, 10) |
| Format spec | `dossier-format.md` (Sections 2, 6, 7, 8, 9, 10, 11) |
| Voice reference | `examples/jiang-xinrui-canonical.md` |

## What you produce

You **rewrite Section 2 (Verdict) and Sections 6–11** of the dossier
in place. Other sections (1, 3, 4, 5, 5a, 5b) are not touched.

Sections you write:
- Section 2 — Verdict
- Section 6 — Strongest aspect — bullet options
- Section 7 — One change — bullet options
- Section 8 — Per-criterion comments — borderline cases
- Section 9 — A1 feedback-action language — bullets
- Section 10 — Final mark recommendation
- Section 11 — Notes for moderation use (optional)

## Step-by-step

### 0. Pre-flight: verify Stages 1–3 dossier exists

Before reading anything else, verify the dossier file at
`reports/marking/dossiers/<stem>-<submission-id>.md` exists AND that
Sections 5a (Upward check) and 5b (Downward check) are not still
placeholders. If any condition fails, bail with:

```text
Stage 4 requires a Stage 1 + 2 + 3 dossier at <path>. <Reason: file
does not exist | Section 5a is still '*Pending Stage 2.*' | Section
5b is still '*Pending Stage 3.*'>. Run the prior stages first.
```

Do NOT create a dossier from scratch and do NOT run prior stages'
logic — Stage 4 owns Section 2 + Sections 6–11 only.

### 1. Read the full dossier

Read Sections 1–5b in full. Note:
- Marker's per-criterion tier picks (Section 3)
- Stage 1's descriptor-fit reads (Section 3 + Section 5)
- Stage 2's upward-check recommendations per criterion (Section 5a):
  Lift / Hold / Borderline
- Stage 3's downward-check conclusions per criterion (Section 5b):
  Hold / Lower-fit flagged
- A1 feedback-action checklist (Section 4)

Also re-read the marker's "Strongest aspect", "One change", and
per-criterion comments from the marks file. You'll need the full
text for Section 6, 7, and the polished comment derivations.

### 2. Reconcile Stage 2 + Stage 3 per criterion

For each criterion, determine the **final tier** and **final points**:

| Stage 2 outcome | Stage 3 outcome | Reconciled outcome | Verdict label contribution |
|---|---|---|---|
| Lift recommended | Hold (the lift held) | Apply lift; final tier = higher | Lift recommended |
| Lift recommended | Lower-fit flagged on the lifted tier | Walk lift back; final tier = marker tier; note in Verdict + Final mark recommendation that Stage 3 walked back the Stage 2 lift | Hold recommended (with walk-back note) |
| Hold recommended | Hold | Final tier = marker tier | Hold recommended (if the hold was the defining call) or Aligned (if the upward case was thin) |
| Hold recommended | Lower-fit flagged | Final tier = marker tier (Hold under default-to-marker; Stage 3's lower-fit is recorded as "place a second reader is most likely to push back") | Hold recommended (the defining-call-with-hedge case) |
| Borderline | Hold | Final tier = marker tier (Borderline goes through default-to-lower per Rule 1) | Hold recommended (with Borderline label retained on the criterion) |
| no Stage 2 walk | Hold | Final tier = marker tier (clean Aligned case) | Aligned |
| no Stage 2 walk | Lower-fit flagged | Final tier = marker tier (Hold under default-to-marker; Stage 3's lower-fit recorded as the defining call) | Hold recommended (the unusual downward-defining-call case) |

### Re-moderation cases (skill run on already-moderated marks)

If the marks file shows tier picks that already reflect a prior
dossier's recommendation (e.g., a paper is being re-moderated, or
the marker actioned the original dossier and the skill is being run
again on the post-moderation marks), the table above still applies.
But the verdict label needs an additional disambiguation:

- **Aligned (re-moderation)** — the skill independently arrives at
  the same tier picks the marker has already entered, with no further
  moves to make. Use this label in the Verdict context sentence
  ("Aligned at <m> — independent descriptor-fit run on already-
  moderated marks reproduces the marker's tier picks under
  Discipline Rules 1, 2, 4"). This is distinct from a fresh-Aligned
  case (where no upward case was ever considered) because the
  re-moderation Aligned defends a prior moderation decision.
- **Aligned (with prior-lift defence)** — the skill identifies a
  previously-applied lift as descriptor-clean and defends it in
  Stage 2's Pattern line ("prior-dossier lift on C3 from Cr to D
  reproduced as descriptor-clean under re-read"). Same outcome
  label-wise, but the Stage 2 / Stage 4 narrative explicitly
  acknowledges the moderation history.

The skill cannot detect re-moderation automatically (no input
field carries this state). The driver should pass a flag or note in
the invocation prompt when re-running on already-moderated marks; if
unflagged, the skill treats the marks as the marker's contemporaneous
tier picks and proceeds without the moderation-history framing.

After reconciliation, compute the final canned mark:

- For each criterion, sum the final points
- Compare to the marker's canned total
- The **dossier's recommended mark** is the reconciled total

Determine the **verdict outcome** (locked vocabulary):

- **Aligned** — no lifts and no walked-back upward cases
- **Lift recommended** — one or more lifts applied; recommended
  mark > marker mark
- **Hold recommended** — Stage 2 surfaced upward cases that Stage 2
  or Stage 3 reconciliation kept at marker tier; recommended mark =
  marker mark, but the upward consideration is the dossier's defining
  call

### 3. Write Section 2 (Verdict)

Rewrite the verdict line and 1–3 sentence context per the format spec
template:

```markdown
## Verdict

**Marker mark: <m> (<tier>). Recommendation: <r> (<tier>) — <Aligned | Lift recommended | Hold recommended>.** <Context: name the binding consideration. If lifts were applied, name them. If holds were the defining call, name the discipline rule that bound (Rule 1 / Rule 2). If borderline cases are surfaced, name them.>

---
```

### 4. Write Section 6 (Strongest aspect — bullet options)

Three bullets per Discipline Rules 5 and 6:

- **Bullet 1:** `**[Your comment, polished]**` followed by the
  marker's "Strongest aspect" comment, polished. Light edits:
  - Preserve voice and substance
  - Add paragraph or section references where the original was vague
  - Tighten grammar (fix awkward phrasing, remove redundancy)
  - Do NOT inflate claims (do NOT change "the paper covers a
    substantial body" to "the paper provides comprehensive coverage")
  - Do NOT add new substantive content
  - If the original is already concise and well-grounded, write
    `**[Your comment, no edits needed]**` followed by the comment
    verbatim
- **Bullets 2 and 3:** Alternative angles drawn from the
  descriptor-fit observations (Section 5). Each bullet has:
  - A bold lead-in (e.g., `**Section-level red thread.**`)
  - 2–3 sentences in diagnostic register (Rule 7)
  - Specific citations (Rule 10)

### 5. Write Section 7 (One change — bullet options)

Same structure as Section 6 but for "One change":

- **Bullet 1:** `**[Your comment, polished]**` + polished marker
  "One change" comment. The polish often expands paragraph references
  and may add the prescriptive "for A3, the move is…" framing if the
  marker named a problem without naming a fix. Do not add a fix the
  marker didn't gesture toward.
- **Bullets 2 and 3:** Alternative angles. These often surface
  structural observations from Stage 1 / Stage 2 that the marker's
  comment didn't cover. Each bullet ends in an A3-facing move where
  appropriate.

### 6. Write Section 8 (Per-criterion comments — borderline cases)

For each criterion where the **final outcome** is `Lift recommended`,
`Borderline`, `Hold recommended` with a defining-call hedge, OR Stage
3 flagged `Lower-fit flagged for marker review` on the criterion,
write one Canvas-paste-able blockquote bullet per the format spec
template:

```markdown
> **C<n> <Criterion full rubric name> (<final tier>):** This mark is almost a <other-tier>. It meets the <other-tier> descriptor's "<verbatim quote from descriptor>" — <specific evidence>. It falls short on <or: meets, with limits> the <other-tier> descriptor's "<verbatim quote>" — <specific evidence> — which keeps it at <final tier>.
```

The "other tier" depends on which way the dossier was hedged:

- If a lift was recommended (final tier = higher): "almost a
  <higher tier>" doesn't make sense — instead, "this mark moves up
  to <new tier> because…" framing applies. Re-read Jiang's C3 paste-
  able for the lift case (note: the canonical example uses retired
  vocabulary; reproduce the structural pattern, not the heading
  language).
- If a hold against an upward case (final tier = marker tier, which
  is the lower of the two considered): "This mark is almost a
  <higher tier>" with the descriptor-fit case for the higher tier
  named as what's met, and the gap to clean-higher-tier named as
  what keeps it at marker tier.
- If a downward case was flagged (Stage 3 `Lower-fit flagged for
  marker review`): "This mark is almost a <lower tier>" with the
  descriptor-fit case for the lower tier named, and what keeps it at
  marker tier. The student deserves to see what would have lowered
  the criterion in descriptor terms — but frame the paste-able to
  defend the marker tier as the call of record, not to undermine it.

Do **not** write per-criterion comments for clean Aligned criteria.
Those don't need a Canvas paste-able; the marker's existing comment
(or absence of one) is sufficient.

### 7. Write Section 9 (A1 feedback-action language — bullets)

2–3 bullets ready to lift into the Canvas overall comment box:

- **Bullet 1:** the most consequential A1→A2 carry-through. Cite
  specifically (which A1 item; what the A2 evidence shows).
- **Bullet 2:** a second carry-through, OR a partial action with a
  forward-looking note for A3 ("partially actioned at the framework
  level; for A3, this needs to operationalise…").
- **Optional bullet 3:** a pattern observation (e.g., "notably clean
  A1 follow-through across three substantive items — compared to the
  cohort, this is in the strong end"; or, for a paper with poor
  follow-through, an honest diagnostic).

If A1 was unavailable (late enrolee), write a single line: `A1
feedback unavailable; no A1 feedback-action language for this
dossier.`

### 8. Write Section 10 (Final mark recommendation)

Per the format spec template. Show the canned and 2–4 lift scenarios.
Each scenario has:

- Tier-string (e.g., `D/D/D/Cr/D`)
- Computed mark
- One-sentence rationale (what this scenario buys; what it costs in
  terms of contradiction with marker comment, descriptor strictness,
  etc.)

End with a one-paragraph **Recommendation** that ties Stage 2 +
Stage 3 findings to the binding consideration.

If the verdict is `Aligned`, use the shorter template (no lift
scenarios needed).

### 9. Write Section 11 (Notes for moderation use)

Optional. Include if the dossier surfaces something a second reader
should know:

- Pedagogical signal worth flagging (clean A1 follow-through, unusual
  trajectory, exceptional case)
- Word-count discussion if flagged
- Defining-call observation (the place a second reader is most likely
  to push back, with the descriptor-strict alternative recorded)
- Process-statement observations

If there's nothing material to add, **remove the placeholder section
entirely** (don't leave an empty heading).

### 10. Verify and report

Re-read the full dossier (all sections). Verify:

- Verdict line matches the Final mark recommendation's recommended
  tier and mark
- Section 6 bullet 1 is the marker's polished comment with the
  `**[Your comment, polished]**` prefix
- Section 7 bullet 1 is the marker's polished One Change with the
  same prefix
- Section 8 has one blockquote per borderline criterion (and only
  those)
- Section 9 has 2–3 bullets (or the unavailable note)
- Section 10's mark scenarios sum correctly
- No Stage placeholder text (`*Pending Stage <N>.*`) remains anywhere
- The Verdict outcome label is one of: Aligned / Lift recommended /
  Hold recommended (no other vocabulary)
- "Drift-catch" does not appear as a section heading anywhere (Rule
  11)
- Bullet structure is preserved in all four comment-field sections
  (Rule 5)
- No claims without grounding (Rule 10)

Report to the driver: final canned mark, recommended mark, verdict
outcome, list of criteria with lifts applied, list of borderline
criteria with paste-ables, summary line for the batch progress file
if running in batch mode.

## What NOT to do

- **Do not** invent marker comment content. The polished comment
  (Bullet 1 in Sections 6 and 7) preserves the marker's substance.
  Adding new claims is inflation.
- **Do not** recommend a lift that contradicts the marker's
  contemporaneous comment (Rule 2). If Stage 2 recommended such a
  lift, Stage 4 walks it back and explains why in the Final mark
  recommendation.
- **Do not** write per-criterion comments for clean Aligned criteria.
- **Do not** use prose for the four comment-field sections. Bullets
  only (Rule 5).
- **Do not** retain placeholder text (`*Pending Stage <N>.*`)
  anywhere in the final dossier.
- **Do not** rewrite Sections 1, 3, 4, 5, 5a, 5b. Stage 4 owns
  Section 2 and Sections 6–11 only.
