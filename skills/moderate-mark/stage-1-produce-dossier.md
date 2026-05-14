# Stage 1 — Produce neutral dossier

You are running Stage 1 of the `moderate-mark` pipeline. Your job is
to read the marker's tier picks, the rubric, the submission, and (if
present) the A1 feedback, and produce the **neutral foundation** of
the moderation dossier. NO lift or hold recommendations at this stage.

## Inputs

| Input | Path |
|---|---|
| Marker tier picks (A2) | `reports/marking/a2-shawn-marks/<stem>-*.md` |
| A1 feedback (if present) | `reports/marking/a1-feedback/<stem>-*.md` |
| Submission body text | `data/submissions-lit-review/extracted/<stem>-*.txt` |
| Rubric definition | `reports/marking/a2-rubric-definition.json` |
| Discipline rules | `discipline-rules.md` (read first) |
| Format spec | `dossier-format.md` (read first) |
| Voice reference | `examples/jiang-xinrui-canonical.md` (read first) |

Read the discipline rules and format spec **first**. They are the
authority for what to produce and what discipline to apply.

## What you produce

You write the dossier file at
`reports/marking/dossiers/<stem>-<submission-id>.md`.

Sections you write in Stage 1 (per `dossier-format.md`):

1. **Header** (Section 1) — student name, submission filename, body
   word count, on-time/late, A1 grade, A2 grade, topic.
2. **Verdict placeholder** (Section 2) — write a placeholder line
   `**Marker mark: <m> (<tier>). Recommendation: pending Stage 4.**`.
   Stage 4 will rewrite this section.
3. **Criterion comparison table** (Section 3) — your neutral
   descriptor-fit reads alongside the marker's tier picks.
4. **A1 → A2 follow-through** (Section 4) — commensurate criteria
   table + A1 feedback-action checklist.
5. **Descriptor-fit observations** (Section 5) — prose discussion of
   why each "Direction" cell reads as it does, with grounded
   evidence.
6. Stage 2/3/4 placeholder sections (Sections 5a, 5b, 6, 7, 8, 9,
   10, 11) — write markdown headings only with a placeholder line:
   `*Pending Stage <N>.*`. Section 11 (Notes for moderation use) is
   optional; Stage 4 will either fill it or remove it.

## Step-by-step

### 1. Read inputs

- Read `discipline-rules.md`, `dossier-format.md`,
  `examples/jiang-xinrui-canonical.md`.
- Glob the marker tier picks file via `<stem>-*.md` in
  `reports/marking/a2-shawn-marks/`. If zero or multiple matches,
  bail with the offending count and matched paths.
- Glob the A1 feedback file via `<stem>-*.md` in
  `reports/marking/a1-feedback/`. If zero matches, proceed with A1
  marked unavailable. If multiple matches, bail.
- Glob the submission text via `<stem>-*.txt` in
  `data/submissions-lit-review/extracted/`. If zero or multiple
  matches, bail.
- Read `reports/marking/a2-rubric-definition.json`.

### 2. Compute body word count (Discipline Rule 8)

Use the `awk` recipe in Rule 8 (or equivalent). Report the result in
the header. If extraction fails, write
`body word count: UNPARSEABLE — verify manually` in the header and
proceed.

Determine word-count flag:
- `no word-count flag` for 1,800 ≤ count ≤ 2,200
- `under-range flag — see word-count note below` for count < 1,800
- `over-range flag — see word-count note below` for count > 2,200

### 3. Read the rubric definition

Parse `a2-rubric-definition.json`. Extract for each criterion:
- Criterion ID, description (short name), points (max), long
  description
- Each rating's tier label (HD/D/Cr/P/N), points, descriptor
  (long_description)

You will need the full descriptors when writing the criterion
comparison reasons and (in Stages 2–4) when quoting descriptor
phrases.

### 4. Read the marker tier picks

Parse the A2 marks file. Extract:
- Total grade
- For each rubric criterion: marker's tier (e.g., "Cr (60-69)"),
  points (e.g., 6.5/10.0), and any marker comment text
- The "Strongest aspect" comment text
- The "One change" comment text
- The "Overall comments" text (if present)

**Verify the canned total.** Sum the per-criterion points. Compare
to the reported total. Three cases:

- **Match (within ±0.01):** proceed; no flag.
- **Rounding mismatch (within ±0.5):** the reported total is likely
  rounded for Canvas display (e.g., per-criterion sum 86.25, reported
  86.0). Use the per-criterion sum throughout the dossier; add a
  one-line header note: `Note: per-criterion sum is <X.XX>; marks
  file reports <Y.Y> (rounding artefact).`
- **Substantive mismatch (>±0.5):** something is wrong — possibly an
  override, a missed criterion, or a parse error. Flag prominently
  in the dossier header (`MISMATCH: per-criterion sum <X.XX> ≠
  reported total <Y.Y>; verify before relying on this dossier`) and
  proceed using the per-criterion sum, but warn the marker that the
  discrepancy needs investigation.

### 5. Read the submission text

Read the body. Identify the title (first non-blank line of
substantive content) and the topic. Skim the body sections. Note the
section structure (e.g., "Introduction → Liveness → Presence → Chinese
Theatricality → Phenomenology → Conclusion") — you'll cite specific
sections in the comparison reasons.

### 6. Read the A1 feedback (if present)

Parse the A1 marks file. Extract:
- A1 total grade and tier
- A1 per-criterion tier picks
- A1 marker comments per criterion (especially "Strongest aspect"
  and "One change")

### 7. Write the criterion comparison table (Section 3)

For each A2 criterion (C1–C5):

- **Marker tier column:** tier and points exactly as in the marks file.
- **Descriptor-fit column:** your read of which tier the A2 evidence
  supports. Apply Discipline Rules 1 and 4 in your read — you are
  reading what the descriptor says, not what would be a generous
  call.
- **Direction column:** one of `agree`, `descriptor-fit one tier
  higher`, `descriptor-fit one tier higher, with hedge`, or
  `descriptor-fit one tier lower`. NO verdict labels.
- **One-sentence reason:** cite specifically (Rule 10). Name the
  paragraph or section, quote a phrase, or name the source.

### 8. Write the A1→A2 follow-through (Section 4)

- Use the mapping in Discipline Rule 9 for the commensurate criteria
  table. Skip A1 C4 unless it has informational value for A3.
- One-paragraph pattern summary: count of improved/held/regressed,
  what the dominant pattern is. NO recommendation language.
- A1 feedback-action checklist: each row is one A1 marker comment
  (Strongest, One change, per-criterion) paired with A2 evidence and
  an `Actioned?` label. Cite A2 evidence specifically.

### 9. Write the descriptor-fit observations (Section 5)

For each criterion where your "Direction" read is anything other than
clean `agree`, write a 2–4 sentence subsection naming what the A2
evidence shows. Use the format spec's template. NO lift/hold
language.

If a criterion's Direction is `agree` but there's nuance worth
flagging for Stage 2/3 (e.g., a borderline-low D where descriptor
evidence reaches the bottom of the band), write a brief subsection
flagging that observation.

### 10. Write placeholder sections for Stages 2–4

For Sections 5a, 5b, 6, 7, 8, 9, 10, 11, write the markdown heading
followed by `*Pending Stage <N>.*`. Stage 11 (Notes for moderation
use) is optional; write the heading with placeholder, and Stage 4
will either fill it or remove it.

### 11. Verify and report

Re-read the dossier you wrote. Verify:
- Header is complete and the word count was computed (not stubbed)
- Criterion comparison table has 5 rows (C1–C5)
- Each "One-sentence reason" cell cites specifically (no vague
  descriptors like "the paper is well-organised")
- A1 → A2 section is present (or the unavailable note is present)
- Descriptor-fit observations exist for every criterion that's not
  clean `agree`
- Stage 2/3/4 placeholders are in place

Report to the driver: dossier path, body word count, total grade,
canned tier-string (e.g., "Cr/P/D/Cr/D"), list of criteria with
non-`agree` direction reads.

## What NOT to do

- **Do not** write any text that begins "Lift recommended" or "Hold
  recommended". Those are Stage 4 outputs.
- **Do not** label any section "Drift-check" or "Drift-catch flags"
  (Discipline Rule 11). The upward review heading is "Upward check"
  and is owned by Stage 2.
- **Do not** write polished marker comments or per-criterion
  borderline comments. Those are Stage 4 outputs.
- **Do not** trust upstream word-count claims. Compute it yourself
  via Rule 8.
- **Do not** make claims about the paper without grounding them in
  specific text (Rule 10). If you can't cite, drop the claim.
