# Stage 2 — Upward check (Copilot multi-stage)

Paste everything below the `=== BEGIN PROMPT ===` marker after Stage
1 has produced its dossier. Copilot will rewrite Section 5a (Upward
check) of the dossier.

---

```text
=== BEGIN PROMPT ===

# Stage 2 — Upward check

You own Section 5a (Upward check) of the dossier. Apply Discipline
Rules 1, 2, 4, 10, 11. Do NOT touch other sections.

## Identify candidates

From the Stage 1 dossier, identify criteria where:

- Direction is `descriptor-fit one tier higher` (clean upward
  candidate)
- Direction is `descriptor-fit one tier higher, with hedge`
  (borderline upward candidate)

Also check the four internal triggers (Rule 11) that may surface
additional candidates not flagged by Stage 1's Direction column:

1. **A1→A2 regression** on the commensurate criterion (drift-catch)
2. **Marker comment praises something the tier picks do not reward**
3. **Tier-boundary marks** (marker picked the bottom of the band
   where descriptor evidence reaches the top)
4. **Re-read suggests descriptor-clean upward case** even where
   Direction read `agree`

If any of these triggers fires for an `agree`-marked criterion, add
that criterion to your Stage 2 walk.

## Walk each candidate criterion

```markdown
### C<n> <Criterion name> — <Lift recommended | Hold recommended | Borderline>

**Pattern:** <name the trigger(s) that prompted the upward re-read: A1→A2 regression, marker comment mismatch, descriptor re-read, tier-boundary mark>.

**A2 evidence supports <higher tier>:**

- <bulleted evidence with specific citations — Rule 10>

**<Higher tier> descriptor reads:** <verbatim quote from rubric descriptor for higher tier>. <One sentence on whether evidence fits.>

**<Marker tier> descriptor reads:** <verbatim quote from rubric descriptor for marker tier>. <One sentence on whether evidence fits the marker tier's "what NOT to count" features.>

**Recommendation:** <see locked vocabulary mapping below>
```

## Recommendation outcomes (locked vocabulary mapping)

- **Marker comment supports the lift** (rare): comment praises
  something at the higher tier and descriptor evidence backs it. →
  `Lift recommended`. Recommendation line: `Lift to <higher tier>
  (<old-points> → <new-points>). Canned total moves from <old> →
  <new>.`
- **Marker comment is silent on the criterion** (common): comment
  doesn't speak to this descriptor. Apply Rule 1.
  - **Descriptor case for higher tier is clean and unhedged** →
    `Lift recommended` (Rule 1 doesn't block clean upward).
  - **Descriptor case for higher tier is hedged** → `Hold
    recommended` with the criterion labelled `Borderline`.
    Recommendation line: `Hold at <tier> under Rule 1 — descriptor
    case for the higher tier is hedged; Borderline.`
- **Marker comment names the lower tier's defining feature** (Rule 2
  case): → `Hold recommended`. Recommendation line: `Hold at <tier>
  under Rule 2 — marker's One Change comment names the <P> descriptor's
  defining feature almost verbatim.`

## If no upward candidates

If no candidates at all (no Direction flag, no internal trigger
fires), output:

```markdown
## Upward check

No upward candidates. All criteria read `agree` in Stage 1; no internal triggers (A1→A2 regression, marker-comment praise mismatch, tier-boundary marks, re-read upward case) surface additional candidates.

---
```

## Output

Output the rewritten Section 5a only. Do not rewrite or restate
other sections.

After this, wait for the Stage 3 prompt.

=== END PROMPT ===
```

---

After Copilot produces Section 5a, paste
`stage-3-downward-check.md` next.
