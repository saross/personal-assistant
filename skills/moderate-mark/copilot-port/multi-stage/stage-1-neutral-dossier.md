# Stage 1 — Neutral dossier (Copilot multi-stage)

Paste everything below the `=== BEGIN PROMPT ===` marker, then
**immediately follow it with the filled per-paper input block**.
Copilot will produce Sections 1, 3, 4, and 5 of the dossier (plus
placeholders for the rest).

---

```text
=== BEGIN PROMPT ===

# Stage 1 — Produce the neutral dossier foundation

You own Sections 1, 3, 4, and 5 of the dossier. Apply Discipline
Rules 3, 5, 9, 10. Do NOT make lift or hold recommendations at this
stage — that's Stage 2's job.

The per-paper input follows this prompt below. Read it carefully.

## Verify inputs (Rule 8)

Before writing, confirm the per-paper input contains:

- Student identifier (name, IDs, topic, submission date, body word
  count)
- A2 marker tier picks (5 criteria + total)
- A2 marker comments (Strongest aspect, One change, any per-criterion)
- A2 submission body text
- A2 process statement (if present)
- A1 grade and feedback (optional — late enrolees may skip)

If any required field is missing, ask before producing the dossier.

## Verify the canned total

Sum the per-criterion points. Compare to the reported total:

- **Match (within ±0.01):** proceed; no flag.
- **Rounding mismatch (within ±0.5):** add a header note: `Note:
  per-criterion sum is <X.XX>; marker reports <Y.Y> (rounding
  artefact).`
- **Substantive mismatch (>±0.5):** flag prominently: `MISMATCH:
  per-criterion sum <X.XX> ≠ reported total <Y.Y>; verify before
  relying on this dossier.` Proceed using the per-criterion sum.

## Sections to write

### Section 1 — Header

```markdown
# Dossier — <Given Surname> (A1: <a1-mark> <a1-tier> → A2 canned: <a2-mark> <a2-tier>)

**A2 submission ID:** `<id>` (<body-word-count> words body, <on-time | late>, <word-count-flag-or-no-flag>)
**A1 grade:** <a1-mark> (<a1-tier>) — submitted <a1-date>
**A2 submitted:** <a2-date>
**Topic:** *"<title>"*
```

If A1 not available: replace the bracket text with `A1: not available`.

If the word-count flag is `under-range` or `over-range`, add a brief
paragraph after the header explaining the implication (e.g.,
"under-range may compound a synthesis weakness" / "over-range
triggers ANU 10% policy review").

### Section 2 — Verdict (placeholder only)

```markdown
## Verdict

*Pending Stage 4.*

---
```

### Section 3 — Criterion comparison table

```markdown
## Criterion comparison

| Criterion | Marker tier | Descriptor-fit | Direction | One-sentence reason |
|---|---|---|---|---|
| C1 Problem | <tier> (<m>/10) | <tier> | <agree | descriptor-fit one tier higher | descriptor-fit one tier higher, with hedge | descriptor-fit one tier lower> | <one sentence with grounded reason — Rule 10> |
| C2 Synthesis | <tier> (<m>/40) | <tier> | ... | ... |
| C3 Gap | <tier> (<m>/15) | <tier> | ... | ... |
| C4 Coherence | <tier> (<m>/20) | <tier> | ... | ... |
| C5 Process | <tier> (<m>/15) | <tier> | ... | ... |

---
```

Direction-column vocabulary: only the four labels above. NO verdict
language ("Lift recommended", "Hold recommended") at this stage.

Apply Rule 1 (default-to-lower) in your read: read what the
descriptor says, not what would be generous.

Every "One-sentence reason" cell must cite specifically (Rule 10): a
paragraph reference, a quoted phrase, or a named source.

### Section 4 — A1 → A2 follow-through

Two sub-tables.

#### Sub-table 4a — Commensurate criteria comparison

Use the A1↔A2 mapping in Rule 9. Skip A1 C4 unless informational for
A3.

```markdown
### Commensurate criteria comparison

| A1 criterion | A1 tier | A2 criterion | A2 tier | Direction |
|---|---|---|---|---|
| C1 Problem | <tier> | C1 Problem | <tier> | <improved ↑ | held | regressed ↓> |
| C2 Scholarship | <tier> | C2 Synthesis | <tier> | ... |
| C3 Significance | <tier> | C3 Gap | <tier> | ... |
| C5 Coherence | <tier> | C4 Coherence | <tier> | ... |
| C6 Process | <tier> | C5 Process | <tier> | ... |

<Brief one-paragraph pattern summary: improved/held/regressed counts; dominant pattern. NO recommendation language.>
```

#### Sub-table 4b — A1 feedback-action checklist

```markdown
### A1 feedback-action checklist

| A1 feedback item | A2 evidence | Actioned? |
|---|---|---|
| <quote from A1 marker comment> | <specific A2 evidence — Rule 10> | <Yes (explicit) | Yes | Partial | Maintained | No | N/A — A2 has no direct surface> |

<Brief one-paragraph pattern summary.>
```

If A1 not available: replace Section 4 entirely with `## A1 → A2 follow-through\n\nA1 feedback unavailable (late enrolee or equivalent). Dossier proceeds on A2 evidence alone.`

### Section 5 — Descriptor-fit observations

For each criterion where Direction is anything other than clean
`agree`, write a 2–4 sentence subsection. Cite specifically (Rule 10).
NO lift/hold language.

```markdown
## Descriptor-fit observations

### C<n> <Criterion name>

<2–4 sentences naming what the A2 evidence shows that fits the descriptor-fit tier vs the marker tier. Cite specific paragraphs, quotes, or sources.>
```

If a criterion's Direction is `agree` but nuance is worth flagging
for Stage 2 (e.g., a borderline-low D where evidence reaches the
bottom of the band), write a brief subsection flagging that
observation.

### Sections 5a, 5b, 6, 7, 8, 9, 10, 11 (placeholders)

Write these as markdown headings with a placeholder line:

```markdown
## Upward check

*Pending Stage 2.*

---

## Downward check

*Pending Stage 3.*

---

## Strongest aspect — bullet options

*Pending Stage 4.*

---

[... and so on for 7, 8, 9, 10, 11]
```

## Output

Output the entire dossier as a single markdown document with all
sections in order (1 → 11). End your response with the dossier; no
preamble. After this, wait for the Stage 2 prompt.

The per-paper input follows.

=== END PROMPT ===
```

---

**Immediately after pasting the prompt above, paste the filled
per-paper-input-template.md block in the same chat message** (or in
a follow-up message — Copilot will pick it up either way).
