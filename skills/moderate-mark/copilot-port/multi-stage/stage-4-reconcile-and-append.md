# Stage 4 — Reconcile and append (Copilot multi-stage)

Paste everything below the `=== BEGIN PROMPT ===` marker after Stage
3 has produced its Downward check. Copilot will write Section 2
(Verdict) and Sections 6–11 (polished bullets, paste-ables, final
mark recommendation).

---

```text
=== BEGIN PROMPT ===

# Stage 4 — Reconcile + append polished comments

You own Section 2 (Verdict) and Sections 6, 7, 8, 9, 10, 11 of the
dossier. Apply Discipline Rules 1, 2, 4, 5, 6, 7, 10. Do NOT touch
Sections 1, 3, 4, 5, 5a, 5b.

## Reconcile Stage 2 + Stage 3 per criterion

For each criterion, determine the final tier and final points:

| Stage 2 outcome | Stage 3 outcome | Reconciled outcome | Verdict label contribution |
|---|---|---|---|
| Lift recommended | Hold (lift held) | Apply lift; final tier = higher | Lift recommended |
| Lift recommended | Lower-fit flagged on lifted tier | Walk lift back; final tier = marker tier | Hold recommended (with walk-back note) |
| Hold recommended | Hold | Final tier = marker tier | Hold recommended (if hold was defining call) or Aligned (if upward case was thin) |
| Hold recommended | Lower-fit flagged | Final tier = marker tier | Hold recommended (defining-call-with-hedge case) |
| Borderline | Hold | Final tier = marker tier (Rule 1) | Hold recommended (Borderline label retained on criterion) |
| no Stage 2 walk | Hold | Final tier = marker tier | Aligned |
| no Stage 2 walk | Lower-fit flagged | Final tier = marker tier | Hold recommended (downward-defining-call case) |

Compute the final canned mark by summing per-criterion final points.
Determine the verdict outcome (Aligned / Lift recommended / Hold
recommended).

## Re-moderation case

If the marks file shows tier picks that already reflect a prior
moderation (the marker has actioned a prior dossier's lift), the
verdict is `Aligned` but the framing differs:

- **Aligned (re-moderation)** — independent descriptor-fit run
  reproduces the marker's tier picks under Discipline Rules 1, 2, 4.
- **Aligned (with prior-lift defence)** — Stage 2 identified a
  previously-applied lift as descriptor-clean and defended it. Same
  outcome label-wise, but Stage 2 / Section 10 narrative
  acknowledges the moderation history.

The user should signal re-moderation in the per-paper input. If
unsignalled, treat marks as the marker's contemporaneous tier picks.

## Sections to write

### Section 2 — Verdict (rewritten from Stage 1 placeholder)

```markdown
## Verdict

**Marker mark: <m> (<tier>). Recommendation: <r> (<tier>) — <Aligned | Lift recommended | Hold recommended>.** <One-to-three sentences naming the binding consideration: which lifts applied (if any), which discipline rule bound (Rule 1 / Rule 2), which criteria are borderline.>

---
```

### Section 6 — Strongest aspect — bullet options (Rules 5, 6)

Three bullets. Bullet 1 is the polished marker comment.

```markdown
## Strongest aspect — bullet options

- **[Your comment, polished]** <Marker's "Strongest aspect" comment, lightly edited: voice and substance preserved; paragraph or section references added; grammar tightened; NO claim inflation. If original is concise and well-grounded: `**[Your comment, no edits needed]** <comment verbatim>`.>
- **<Alternative angle 1, with bold lead-in.>** <2–3 sentences. Diagnostic register (Rule 7). Cite specifically (Rule 10).>
- **<Alternative angle 2, with bold lead-in.>** <2–3 sentences. Diagnostic register. Cite specifically.>
```

If marker's "Strongest aspect" comment is empty: write `- **[No marker comment for this field — alternatives only]**` and skip bullet 1, providing only bullets 2 and 3.

### Section 7 — One change — bullet options

Same three-bullet structure as Section 6 but for "One change":

```markdown
## One change — bullet options

- **[Your comment, polished]** <Marker's "One change" comment, polished. Often longer than Strongest. Preserve any prescriptive moves the marker made (e.g., "for A3, do X").>
- **<Alternative angle 1.>** <2–3 sentences ending in an A3-facing move where appropriate.>
- **<Alternative angle 2.>** <2–3 sentences. Often surfaces a structural observation the polished comment didn't cover.>
```

### Section 8 — Per-criterion comments — borderline cases

For each criterion where the FINAL outcome is `Lift recommended`,
`Borderline`, `Hold recommended` with a defining-call hedge, OR
Stage 3 flagged `Lower-fit flagged for marker review`, write one
Canvas-paste-able blockquote:

```markdown
## Per-criterion comments — for Canvas criterion boxes (borderline cases)

> **C<n> <Criterion full rubric name> (<final tier>):** This mark is almost a <other-tier>. It meets the <other-tier> descriptor's "<verbatim quote from descriptor>" — <specific evidence with paragraph or source reference>. It falls short on <or: meets, with limits> the <other-tier> descriptor's "<verbatim quote>" — <specific evidence> — which keeps it at <final tier>.
```

The "other tier" depends on hedge direction:

- **Lift recommended** (final tier = higher): "this mark moves up to
  <new tier> because…" framing rather than "almost a higher".
- **Hold against upward** (final tier = marker, lower of two
  considered): "almost a <higher tier>" with descriptor-fit case for
  the higher tier named as what's met, and gap to clean-higher-tier
  named as what keeps it at marker tier.
- **Lower-fit flagged** (Stage 3): "almost a <lower tier>" with
  descriptor-fit case for lower tier named, and what keeps it at
  marker tier. Frame to defend the marker tier as the call of record;
  do not undermine.

Soft cap: **2–3 paste-ables** per dossier. If 4+ qualify, surface
the count in Section 11. Do NOT produce paste-ables for clean
Aligned criteria.

### Section 9 — A1 feedback-action language — bullets

2–3 bullets ready to lift into the Canvas overall comment box:

```markdown
## A1 feedback-action language — bullets (to lift into the comment box)

- <Bullet on the most consequential A1→A2 carry-through. Cite specifically.>
- <Bullet on a second carry-through OR a partial action with A3-facing note ("for A3, this needs to operationalise...").>
- <Optional third bullet: pattern observation.>
```

If A1 not available: `## A1 feedback-action language\n\nA1 feedback unavailable; no A1 feedback-action language for this dossier.`

### Section 10 — Final mark recommendation

```markdown
## Final mark recommendation

- **Current canned:** <m> (<tier-string e.g. D/D/Cr/D/D>)
- **With C<n> lift to <tier> (recommended):** <m+lift> (<new-tier-string>) — <one-sentence rationale>
- **With C<n1> + C<n2> lifts to <tier>:** <m+lifts> (<new-tier-string>) — <rationale: defensible? contradicts marker comment?>

**Recommendation: <recommended-action>.** <One-paragraph rationale tying Stage 2 + Stage 3 findings to the binding consideration.>
```

If verdict is `Aligned`, use shorter form:

```markdown
## Final mark recommendation

- **Current canned:** <m> (<tier-string>)
- **No lifts recommended.** Stage 2 found <none | one borderline-with-hedge case>; Stage 3 found <no downward-fit cases | one Lower-fit flagged>.

**Recommendation: hold at <m>.** <Brief sentence on what makes this Aligned.>
```

### Section 11 — Notes for moderation use (optional)

Include if the dossier surfaces something a second reader should
know:

- Pedagogical signal worth flagging (clean A1 follow-through, unusual
  trajectory)
- Word-count discussion if flagged
- Defining-call observation (place a second reader is most likely to
  push back, with descriptor-strict alternative recorded)
- Process-statement observations
- Paste-able count if 4+

If nothing material to add, omit this section entirely.

## Output

Output the rewritten Section 2 + Sections 6, 7, 8, 9, 10, (11). Do
NOT rewrite Sections 1, 3, 4, 5, 5a, 5b.

After this, the dossier is complete. Verify:

- Verdict label uses one of the four locked outcomes
- Section 6 bullet 1 has the `**[Your comment, polished]**` prefix
  (or the `**[Your comment, no edits needed]**` or `**[No marker
  comment for this field — alternatives only]**` variants)
- Section 8 has paste-ables ONLY for borderline criteria (not for
  clean Aligned)
- No `*Pending Stage <N>.*` placeholders remain anywhere
- "Drift-catch" or "Drift-check" does not appear as a section heading
  (Rule 11)

=== END PROMPT ===
```

---

After Copilot produces Sections 2 and 6–11, the dossier is complete.
Copy the full dossier (Sections 1 through 11, in order) to your
dossiers directory.

If you're processing more papers in the same Copilot session, paste
the next paper's per-paper input + `stage-1-neutral-dossier.md` to
start the next dossier. The bootstrap stays in context.
