# Stage 3 — Downward check (Copilot multi-stage)

Paste everything below the `=== BEGIN PROMPT ===` marker after Stage
2 has produced its Upward check. Copilot will rewrite Section 5b
(Downward check) of the dossier.

---

```text
=== BEGIN PROMPT ===

# Stage 3 — Downward check

You own Section 5b (Downward check) of the dossier. Apply Discipline
Rules 1, 2, 4, 10. Do NOT touch other sections.

This is a symmetric counterpart to Stage 2: walk every criterion
(C1–C5), not just those flagged for upward. Diligence is the goal —
the dossier should be symmetric in scrutiny up and down. Most
criteria will Hold; that's correct.

## For each criterion (C1–C5)

```markdown
### C<n> <Criterion name> — <Hold | Lower-fit flagged>

**A2 evidence considered for downward read:** <bulleted evidence that would support a lower tier — paragraph patterns matching the lower descriptor, weaknesses identified by the marker — OR "no descriptor evidence supports a lower tier; the <criterion> is at the cleanly-<tier> level (paragraph X-Y demonstrate Z)" for clean cases>

**Cohort-relative read (Rule 4):** <one sentence on whether the ANU Masters norm — modal D, mean low 70s, HD reserved for 1–2 papers — pulls this tier toward the lower band. Especially relevant for HD calls.>

**Marker comment check (Rule 2):** <one sentence on whether the marker's contemporaneous comment supports the lower tier or the marker tier. If the marker praised the criterion, that's against a downward call. If the marker raised reservations, that's in favour.>

**Conclusion:** Hold at <marker tier>. <Or: Lower-fit flagged for marker review — descriptor case for <lower tier> is descriptor-clean; surface for marker review.>
```

## When does Stage 3 flag a downward case?

Stage 3 flags `Lower-fit flagged` when ALL of these hold:

- The descriptor evidence reads cleanly to the lower tier (e.g.,
  marker called Cr but the predominant pattern matches the P
  descriptor, with higher-tier features appearing in only one or
  two sections);
- AND the cohort-relative read does NOT lift the call back up;
- AND the marker's comment doesn't strongly back the marker tier (or
  the marker's comment names a feature of the lower tier's
  descriptor — Rule 2 in the downward direction).

Do NOT manufacture downward cases for symmetry. Do NOT use cohort-
relative discipline (Rule 4) as the *only* reason for a downward
flag — cohort norm informs; descriptor evidence decides.

When you flag a downward case, surface it as `Lower-fit flagged for
marker review` — do not unilaterally recommend a lower call. Stage 4
reconciles; the marker is the final authority.

## If Stage 2 recommended a lift

Apply the downward check to the **lifted tier** (does the descriptor
evidence cleanly reach the lifted tier, or is the lift borderline?).
If the downward case for the marker tier reads cleanly, that's a
signal: Stage 4 reconciliation should walk back the lift. Note this:
`Downward case for <marker tier> is descriptor-clean; Stage 2 lift
recommendation walked back at Stage 3.`

## Short-form Hold (clean cases)

For criteria where the marker's tier is descriptor-clean, the
subsection can be brief:

```markdown
### C<n> <Criterion name> — Hold

**A2 evidence considered for downward read:** No descriptor evidence supports a lower tier; the <criterion> is at the cleanly-<tier> level (paragraph X demonstrates Y).

**Cohort-relative read (Rule 4):** Cohort-typical <tier>; no pull toward lower band.

**Marker comment check (Rule 2):** Marker's comment praises <feature>, supporting the marker tier.

**Conclusion:** Hold at <tier>.
```

## Output

Output the rewritten Section 5b only. Do not rewrite other sections.

After this, wait for the Stage 4 prompt.

=== END PROMPT ===
```

---

After Copilot produces Section 5b, paste
`stage-4-reconcile-and-append.md` next.
