# Dossier Format Spec — `moderate-mark` v0.1.1

The 10-section structure that every moderation dossier follows.
**Single source of truth for format** — voice and tone authority is
`examples/jiang-xinrui-canonical.md`.

Each stage is responsible for specific sections (Stage column below).
Sections appear in the dossier in the order listed.

| # | Section | Stage |
|---|---|---|
| 1 | Header | 1 |
| 2 | Verdict | 4 |
| 3 | Criterion comparison table | 1 |
| 4 | A1 → A2 follow-through | 1 |
| 5 | Descriptor-fit observations | 1 |
| 5a | Upward check | 2 |
| 5b | Downward check | 3 |
| 6 | Strongest aspect — bullet options | 4 |
| 7 | One change — bullet options | 4 |
| 8 | Per-criterion comments — borderline cases | 4 |
| 9 | A1 feedback-action language — bullets | 4 |
| 10 | Final mark recommendation | 4 |
| 11 | Notes for moderation use (optional) | 4 |

The Verdict (section 2) is written last but appears second; it
summarises the Stage 4 reconciliation in one sentence at the top of
the dossier so a moderator can read just the verdict for triage.

---

## Section 1 — Header

```markdown
# Dossier — <Given Surname> (A1: <a1-mark> <a1-tier> → A2 canned: <a2-mark> <a2-tier>)

**A2 submission:** `<extracted-text-source-filename>` (<body-word-count> words body, <on-time|late>, <word-count-flag-or-no-flag>)
**A1 grade:** <a1-mark> (<a1-tier>) — submitted <a1-iso-date>
**A2 submitted:** <a2-iso-date>
**Topic:** *"<title-from-submission-extract>"*

---
```

### Notes

- "A1 canned" / "A2 canned" = the marker's tier picks summed against
  the rubric weights, before any moderation lift.
- `<a2-mark>` is computed from the marks file's per-criterion ratings,
  not taken from the marks file's reported total — verify both match
  and flag discrepancy if they don't.
- `<body-word-count>` from Discipline Rule 8.
- `<on-time|late>` from comparing A2 submission timestamp to the
  cohort deadline (2026-04-19 23:59 AEST). Late penalty is the ANU
  policy and is *not* applied in the dossier (the dossier is about
  marks; late penalty is applied in Canvas separately).
- `<word-count-flag>`: `no word-count flag` (within 90–110% of 2,000),
  `under-range flag — see word-count note below` (<1,800), or
  `over-range flag — see word-count note below` (>2,200). When flagged,
  add a paragraph after the header explaining the implication.
- `<title>` from the first non-blank line of the submission body, or
  from the marks file overall comment if available, or from the
  submission filename — pick whichever is most readable.

If A1 is unavailable (late enrolee), header reads:
`# Dossier — <Given Surname> (A1: not available → A2 canned: <a2-mark> <a2-tier>)`

---

## Section 2 — Verdict

One bold sentence stating the marker's mark, the dossier's
recommended mark, and the verdict outcome. Followed by 1–3 sentences
of context (what drives the recommendation, what's borderline,
what's binding).

```markdown
## Verdict

**Marker mark: <m> (<tier>). Recommendation: <r> (<tier>) — <Aligned | Lift recommended | Hold recommended>.** <One-to-three sentences of context.>

---
```

Verdict outcome vocabulary (locked):

- **Aligned** — descriptor evidence supports the marker's tier; no
  lifts or holds change the canned mark.
- **Lift recommended** — descriptor evidence supports a higher tier
  on at least one criterion; canned mark moves up.
- **Hold recommended** — at least one criterion read borderline-to-
  upward, but Stage 2 + Stage 3 reconciliation (Discipline Rules 1,
  2, 4) keeps the marker's tier; canned mark unchanged.

If both upward and downward findings appear and the net result is
unchanged, default to **Aligned** with a note in the context
sentence ("upward case on C3 walked back by Stage 3").

---

## Section 3 — Criterion comparison table

```markdown
## Criterion comparison

| Criterion | Marker tier | Descriptor-fit | Direction | One-sentence reason |
|---|---|---|---|---|
| C1 Problem | <tier> (<m>/<max>) | <tier> | <agree | descriptor-fit one tier higher | descriptor-fit one tier higher, with hedge | descriptor-fit one tier lower> | <one sentence with grounded reason> |
| C2 Synthesis | … | … | … | … |
| C3 Gap | … | … | … | … |
| C4 Coherence | … | … | … | … |
| C5 Process | … | … | … | … |

---
```

### Notes

- "Marker tier" column shows the marker's pick exactly as in the
  marks file, with the points awarded.
- "Descriptor-fit" column shows the dossier's read of which tier the
  A2 evidence supports. Use the same tier vocabulary as the rubric
  (HD / D / Cr / P / N).
- "Direction" column shorthand:
  - `agree` — descriptor-fit matches marker tier
  - `descriptor-fit one tier higher` — Stage 2 candidate
  - `descriptor-fit one tier higher, with hedge` — Borderline
  - `descriptor-fit one tier lower` — Stage 3 candidate (unusual but
    surface it)
- "One-sentence reason" must cite specific evidence (Discipline Rule
  10): a paragraph reference, a quoted phrase, or a named source.
- This is **Stage 1's neutral output**. No "lift recommended" or
  "hold recommended" labels at this stage — those come from Stages 2
  and 4.

---

## Section 4 — A1 → A2 follow-through

Two sub-sections: a commensurate criteria comparison table, and an
A1 feedback-action checklist.

```markdown
## A1 → A2 follow-through

### Commensurate criteria comparison

| A1 criterion | A1 tier | A2 criterion | A2 tier | Direction |
|---|---|---|---|---|
| C1 Problem | <tier> | C1 Problem | <tier> | <improved ↑ | held | regressed ↓> |
| C2 Scholarship | <tier> | C2 Synthesis | <tier> | … |
| C3 Significance | <tier> | C3 Gap | <tier> | … |
| C5 Coherence | <tier> | C4 Coherence | <tier> | … |
| C6 Process | <tier> | C5 Process | <tier> | … |

<Brief one-paragraph pattern summary: how many improved, held, regressed; what the dominant pattern is.>

### A1 feedback-action checklist

| A1 feedback item | A2 evidence | Actioned? |
|---|---|---|
| <quote or paraphrase from A1 marker comment> | <specific A2 evidence: section reference, quote, or "did not appear"> | <Yes (explicit) | Yes | Partial | Maintained | No> |

<Brief one-paragraph pattern summary: which items were actioned and which weren't, what the pedagogical signal is.>

---
```

### Notes

- A1↔A2 mapping per Discipline Rule 9.
- If A1 is unavailable, replace this section with: "**A1 → A2
  follow-through:** A1 feedback unavailable (late enrolee or
  equivalent). Dossier proceeds on A2 evidence alone."
- "Actioned?" labels:
  - `Yes (explicit)` — A2 directly responds to the A1 item, often
    naming the change
  - `Yes` — A2 substantively addresses the A1 item without naming it
  - `Partial` — A2 addresses part of the item or addresses it at a
    different level than asked
  - `Maintained` — A1 strongest-aspect carries through (not a "change"
    item, so "actioned" doesn't quite apply, but the strength is
    preserved)
  - `No` — A2 evidence does not address the A1 item

---

## Section 5 — Descriptor-fit observations

Stage 1's prose discussion of the per-criterion descriptor-fit reads.
This is where the dossier explains *why* each "Direction" cell in
the criterion comparison table reads as it does, with specific
evidence (Rule 10).

```markdown
## Descriptor-fit observations

<For each criterion where Stage 1's read is anything other than a
clean "agree", a short subsection explaining the read. Order: by
criterion number. Skip criteria where read is "agree" with no nuance
to flag.>

### C<n> <Criterion name>

<2–4 sentences naming what the A2 evidence shows that fits the
descriptor-fit tier vs the marker tier. Cite specific paragraphs,
quotes, or sources. No verdict labels here — this is observation,
not recommendation.>

---
```

### Stage 5a — Upward check (Stage 2)

After Section 5, Stage 2 appends:

```markdown
## Upward check

<For each criterion identified by Stage 1 as borderline-or-suggestive
(direction = one tier higher, with or without hedge): a subsection
that walks the upward case.>

### C<n> <Criterion name> — <Lift recommended | Hold recommended | Borderline>

**Pattern:** <triggers that prompted re-read: A1→A2 regression, marker comment mismatch, descriptor re-read, tier-boundary mark>.

**A2 evidence supports <higher tier>:**

- <bulleted evidence with specific citations>

**<Higher tier> descriptor reads:** <quote from rubric>. <Sentence on fit.>

**<Marker tier> descriptor reads:** <quote from rubric>. <Sentence on fit.>

**Recommendation:** <Lift to <higher tier> (<old-points> → <new-points>). Canned total moves from <old> → <new>. | Hold at <marker tier> — <reason: marker comment names lower-tier feature (Rule 2) | default-to-lower discipline (Rule 1) | descriptor case is hedged>.>

---
```

### Stage 5b — Downward check (Stage 3)

After the Upward check, Stage 3 appends:

```markdown
## Downward check

<For each criterion: a subsection evaluating whether descriptor +
cohort-relative norms (Rule 4) support a lower tier. Most subsections
will conclude "Hold at <marker tier>" — the downward check is
diligence, not a search for downgrades. But surface any genuine
downward-fit reads (e.g., a Cr that's actually a P under the
predominant pattern).>

### C<n> <Criterion name> — <Hold | Lower-fit flagged>

**A2 evidence considered for downward read:**

- <bulleted evidence with specific citations>

**Cohort-relative read (Rule 4):** <one sentence on whether the cohort
norm pulls this tier toward the lower band>.

**Marker comment check (Rule 2):** <one sentence on whether the marker's
own comment supports the lower tier or the marker tier>.

**Conclusion:** Hold at <marker tier>. <Or: descriptor case for
<lower tier> is descriptor-clean; downward fit flagged for marker
review.>

---
```

If Stage 3 finds no genuine downward-fit reads (the common case),
the section can be a single line:

```markdown
## Downward check

Hold across all criteria. Cohort-relative norm (Rule 4) and marker comments (Rule 2) do not support a lower tier on any criterion.

---
```

---

## Section 6 — Strongest aspect — bullet options

Three bullets. Bullet 1 is the marker's polished comment (Rule 6).
Bullets 2 and 3 are alternative angles drawn from the descriptor-fit
analysis.

```markdown
## Strongest aspect — bullet options

- **[Your comment, polished]** <The marker's own Canvas comment for "Strongest aspect", lightly edited: voice and substance preserved; paragraph or section references added; grammar tightened; no claim inflation.>
- **<Alternative angle 1, with bold lead-in.>** <2–3 sentences. Diagnostic register. Cite specifically.>
- **<Alternative angle 2, with bold lead-in.>** <2–3 sentences. Diagnostic register. Cite specifically.>
```

If the marker's original comment is already concise and well-grounded,
bullet 1 is `**[Your comment, no edits needed]** <comment verbatim>`.

---

## Section 7 — One change — bullet options

Same structure as Section 6.

```markdown
## One change — bullet options

- **[Your comment, polished]** <Marker's One Change comment, polished. Often longer than Strongest because the diagnostic content is denser. Preserve any prescriptive moves the marker made (e.g., "for A3, do X").>
- **<Alternative angle 1.>** <2–3 sentences ending in an A3-facing move where appropriate.>
- **<Alternative angle 2.>** <2–3 sentences. Often the place to surface a structural observation that didn't fit the polished comment.>
```

---

## Section 8 — Per-criterion comments — borderline cases

Produce one Canvas-paste-able blockquote bullet **per borderline
criterion** that names what the paper does that meets the
adjacent-tier descriptor and what keeps it (or moves it) at the
chosen tier.

### Which criteria get a paste-able

A criterion qualifies for a paste-able when **any** of these hold:

- The criterion's final outcome is **`Lift recommended`** (the lift
  itself warrants a per-criterion explanation for the student)
- The criterion is labelled **`Borderline`** in the dossier prose
  (Stage 2 hedged the upward case)
- The criterion's outcome is **`Hold recommended`** with a defining-
  call hedge — i.e., the upward descriptor case was substantive but
  Rule 1 or Rule 2 bound the hold (the student deserves to see what
  would have lifted the criterion)
- Stage 3 flagged a **`Lower-fit flagged for marker review`** outcome
  on the criterion (the student deserves to see what would have
  lowered the criterion, framed in descriptor terms)

A criterion does NOT get a paste-able when:

- The outcome is a clean **`Aligned`** with no upward or downward
  case considered (the marker's existing comment, or the absence of
  one, suffices for the student)
- Stage 2 did walk an upward case but found the descriptor evidence
  thin (no Borderline label; the criterion reads cleanly at the
  marker tier on re-read)

### Soft cap

Aim for **2–3 paste-ables per dossier**. If more than 4 criteria
qualify, the dossier is signalling either an unusually borderline
paper (legitimate — produce all paste-ables) OR over-production by
the skill (sift back to the most defensible borderline calls).
Surface the count in the Notes for moderation use section if 4+.

### Format

```markdown
## Per-criterion comments — for Canvas criterion boxes (borderline cases)

> **C<n> <Criterion full rubric name> (<final tier>):** This mark is almost a <other-tier>. It meets the <other-tier> descriptor's "<quoted descriptor phrase>" — <specific evidence with paragraph or source reference>. It falls short on <or: meets, with limits> the <other-tier> descriptor's "<quoted descriptor phrase>" — <specific evidence> — which keeps it at <final tier>.
```

### Notes

- One blockquote per borderline criterion.
- Format: "This mark is almost a <higher tier>" if a Lift was
  considered (whether or not it landed); "This mark is almost a
  <lower tier>" if a Hold was applied with a downward case.
- Quote the rubric descriptor phrases verbatim (use the marks file's
  rubric definition or `a2-rubric-definition.json`).
- Paste-able directly into Canvas criterion comment boxes.

---

## Section 9 — A1 feedback-action language — bullets

Bullets that name what the student did with their A1 feedback,
ready to lift into the Canvas overall comment box. 2–3 bullets.
Diagnostic register, positive where warranted.

```markdown
## A1 feedback-action language — bullets (to lift into the comment box)

- <Bullet on the most consequential A1→A2 carry-through. Cite specifically.>
- <Bullet on a second carry-through, or on a partial action with a forward-looking note for A3.>
- <Optional third bullet: pattern observation (e.g., "notably clean A1 follow-through across three substantive items — compared to the cohort, this is in the strong end").>
```

---

## Section 10 — Final mark recommendation

```markdown
## Final mark recommendation

- **Current canned:** <m> (<C1-tier>/<C2-tier>/<C3-tier>/<C4-tier>/<C5-tier>)
- **With C<n> lift to <tier> (recommended):** <m+lift> (<new-tier-string>) — <one-sentence rationale>
- **With C<n1> + C<n2> lifts to <tier>:** <m+lifts> (<new-tier-string>) — <one-sentence rationale: defensible? contradicts marker comment? etc.>
- <Add additional scenarios as needed; cap at 4–5 to stay readable.>

**Recommendation: <recommended-action>.** <One-paragraph rationale that ties the Stage 2 + Stage 3 findings together and points to the binding consideration (cohort norm, marker-comment-as-evidence, descriptor-clean upward case, etc.).>
```

If the verdict is `Aligned`, the section is shorter:

```markdown
## Final mark recommendation

- **Current canned:** <m> (<tier-string>)
- **No lifts recommended.** Stage 2 found <none | one borderline-with-hedge case>; Stage 3 found no downward-fit cases.

**Recommendation: hold at <m>.** <Brief sentence on what makes this an aligned case — descriptor-clean across criteria, marker comments well-anchored, no cohort-relative concerns.>
```

---

## Section 11 — Notes for moderation use (optional)

Optional. Include if the dossier surfaces something a second reader
or course convenor should know:

- Pedagogical signal worth flagging (clean A1 follow-through, unusual
  trajectory, exceptional case)
- Word-count discussion if flagged
- Defining-call observation (the place a second reader is most likely
  to push back, with the descriptor-strict alternative recorded)
- Process-statement observations (genuine engagement vs perfunctory)

```markdown
## Notes for moderation use

- <Bullet 1>
- <Bullet 2>
- <Optional bullet 3>
```

If there's nothing material to add, omit this section entirely.
