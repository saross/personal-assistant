# Discipline Rules — `moderate-mark` v0.1.1

The 11 locked rules that govern every dossier produced by this skill.
Stage prompts cite these rules by number. **Single source of truth** —
do not duplicate this content into stage prompts; reference it.

These rules are the codification of the marking discipline that
emerged from the HUMN8031 Assessment 2 cohort run (Yi Li → Jiang
Xinrui → overnight cohort, validated against 18 marked papers).

---

## Rule 1 — Default-to-lower at tier boundaries

When a paper's evidence reads on the boundary between two tiers,
**default to the lower tier** unless the descriptor evidence for the
higher tier is clean and unhedged.

- "Clean" means no significant counter-evidence in the descriptor
  comparison, AND the marker's own contemporaneous comment does not
  name a defining feature of the lower tier.
- This rule is the principal anti-inflation safeguard alongside Rule 2.
- Named hedges (e.g., "borderline either way") go through Stage 2 for
  upward review; the default tier in the dossier verdict remains the
  marker's call until Stage 2 concludes a lift is warranted.

## Rule 2 — Marker's contemporaneous comment IS descriptor evidence

If the marker's Canvas "One Change" comment (or any per-criterion
comment) names a defining feature of the **lower tier's descriptor**,
that comment IS descriptor evidence for the lower tier — not
commentary about it. Do not recommend a tier lift on that criterion
without acknowledging the contradiction and giving stronger
counter-evidence.

- This applies in **both** upward and downward stages.
- Upward: a lift recommendation that contradicts the marker's own
  comment must be flagged as such, with explicit reasoning for why
  the comment should be set aside (rare).
- Downward: if the marker's comment matches the lower-tier descriptor,
  that supports a downward call but does not by itself force one —
  Rule 1 (default-to-lower) plus the comment is usually enough.
- Empirical basis: validated this session against five overnight
  reviews where the marker comment correctly anchored the call.

## Rule 3 — Within-A2 descriptor-fit observations (not just A1→A2 regressions)

Descriptor-fit analysis runs on the A2 paper as it stands, not only
on changes since A1. A criterion can warrant a lift or hold based on
A2 evidence alone — the A1→A2 trajectory is **context**, not
**evidence**.

- The A1→A2 trajectory section in the dossier is informational: it
  tells the moderator what to read for, but the descriptor-fit
  judgement comes from the A2 text against the A2 rubric.
- A1 regression on a criterion is an internal trigger inside Stage 2
  (one of several that prompt an upward check), not a verdict.
- A1 improvement on a criterion does not justify a lift; the standard
  is the quality at submission, not the delta.

## Rule 4 — Cohort-relative discipline

The ANU Masters cohort norm is built into v0.1.x as the default:

- Modal mark in the **D band** (70–79), with the cohort mean landing
  in the **low 70s** (validated against the n=18 cohort: mean 73.28).
- HD reserved for clear exceptions (1–2 papers per cohort).
- Cr or below are not failures; the descriptor table determines the
  tier, not "everyone gets at least a Cr".

Stage 3 (downward check) uses this norm explicitly: if a tier call
is borderline at the high end (HD vs D, D vs Cr), the cohort-relative
read favours the lower tier *unless* the descriptor case is
descriptor-clean.

This rule is **configurable in v2** via `config.yaml`. In v0.1.x it
is hardcoded.

## Rule 5 — Bullets-only for suggested comments

All four comment-field outputs in the dossier are **bullet lists**,
not prose. This is a hard format rule, not a stylistic preference.

The four comment fields:

1. **Strongest aspect** — three bullets (polished + 2 alternatives)
2. **One change** — three bullets (polished + 2 alternatives)
3. **A1 feedback-action language** — 2–3 lift-ready bullets
4. **Per-criterion borderline comments** — one short paragraph per
   borderline criterion, formatted as a blockquote bullet for Canvas
   paste

Markers paste these directly into Canvas; bullet structure is what
makes them paste-able. Prose paragraphs are harder to lift cleanly
into criterion comment boxes.

## Rule 6 — Polished-marker-comment as bullet 1

In **Strongest aspect** and **One change**, bullet 1 is always the
marker's own Canvas comment, polished — preserving voice and
substance, adding paragraph/section references where the original
was vague, tightening grammar without inflating claims.

- Prefix: `**[Your comment, polished]**`
- Bullets 2 and 3 are alternative angles drawn from the descriptor-fit
  analysis. They are not better than bullet 1 by default; they are
  options the marker can use as supplemental Canvas comments or in
  place of bullet 1 if preferred.

If the marker's original comment is already concise and well-grounded,
the polish is light (or none — note "[Your comment, no edits needed]"
in that case).

## Rule 7 — Diagnostic register default; normative for mission-critical only

Marker comments default to **diagnostic register** — describing what
the paper does and where it falls short, in the rubric's own
descriptor language, with paragraph or section references. Avoid
normative language ("you should", "you must", "this is wrong")
except for **mission-critical** issues (academic integrity, severely
malformed submission, missing required components).

- Diagnostic example: "The intro packs three research questions into
  one long sentence; a marker shouldn't need to read the body first
  to understand the intro."
- Normative (reserved): "The submission has no reference list; this
  must be addressed before resubmission."

Strongest-aspect bullets are inherently positive-diagnostic
(describing what works). One-change bullets are diagnostic-with-
direction ("for A3, the move is...").

## Rule 8 — Body word count discipline (deterministic awk extraction)

The skill computes body word count itself. **Do not trust upstream
categorisations** (e.g., word-count lists in planning files; file
word counts that include reference lists and process statements).

### Extraction procedure

1. **Prefer the `.docx` source over the `.txt` extract when available.**
   `.docx` extractors typically preserve block structure and put running
   headers in metadata rather than the text stream, avoiding two
   recurring `.txt`-extract problems: (a) PDF page-break running
   headers (e.g., `<Student Name> <Student ID>` repeated every ~30
   lines) that inflate the count, and (b) lost inter-word spaces in
   PDF extraction (e.g., `sitefor`, `isand`) that under-count.
   The `.docx` files live alongside the extracts at
   `data/submissions-lit-review/<original-filename>.docx` (when the
   submission was a docx). For PDFs, the `.txt` extract is the only
   option — apply the sanity check below.
2. Skip the 3-line metadata header (`# Source:` / `# Submission ID:` /
   `# Format:`).
3. Identify the body **end** marker — the line that begins with one
   of: `References`, `Reference List`, `Bibliography`, `Works Cited`,
   or `Process Statement` (case-insensitive, **may be followed by a
   colon**, may be a heading line on its own). The body ends at the
   line **before** this marker. Once a body-end marker is hit, **all
   subsequent lines are excluded** — the body region is contiguous
   from start to first end-marker.
4. Identify the body **start** marker — typically the first
   substantive content line after the title block. The title block is
   typically 1–3 lines (title + optional byline + optional date); err
   on the side of including borderline lines (the over-count from
   including a 5-word title is small).
5. Count words in the body region. A "word" is a whitespace-separated
   token that contains at least one alphanumeric character.
6. **Sanity check.** If the count falls outside 1,400–2,400 (i.e.,
   ±20% beyond the rubric range), open the file and visually inspect
   the body-end marker detection. PDF extracts in particular may use
   `References:` with a trailing colon, or may have a non-standard
   heading style that the awk regex misses. When in doubt, count by
   selecting the body region in a text editor and pasting into a
   word counter as cross-validation.

A working `awk` recipe (illustrative — adapt to the actual file):

```bash
awk '
  # Skip the metadata header (any line starting with `# <Word>:` is
  # treated as metadata; covers the standard 3 lines plus optional
  # extras like `# Status: LATE submission`).
  /^# [A-Za-z][A-Za-z ]*:/ { next }

  # One-way ended flag — once set, stays set for the rest of the file.
  # The regex matches body-end markers with these allowed variants:
  #   - References / Reference / Reference List / Bibliography /
  #     Works Cited / Process Statement / Process Description
  #   - Optional leading whitespace
  #   - Optional leading numeric prefix (e.g., "5." or "5 ")
  #   - Optional trailing ASCII colon (:) OR full-width Chinese colon (：)
  #   - Optional trailing whitespace
  /^[[:space:]]*[0-9]*[.[:space:]]*([Rr]eferences?( [Ll]ist)?|[Bb]ibliography|[Ww]orks [Cc]ited|[Pp]rocess [Ss]tatement|[Pp]rocess [Dd]escription)[[:space:]]*[:：]?[[:space:]]*$/ { ended = 1 }
  ended { next }

  # Count whitespace-separated tokens that contain at least one
  # alphanumeric character.
  { for (i = 1; i <= NF; i++) if ($i ~ /[A-Za-z0-9]/) count++ }

  END { print count }
' "$EXTRACTED_TXT"
```

**Common bugs to avoid in the awk recipe:**

- Do NOT use a state machine that resets `in_body = 0` on the marker
  line and then unconditionally sets `in_body = 1` on the next line —
  that lets reference-list lines back into the count. Use the
  one-way `ended` flag pattern shown above.
- Do NOT use a regex that requires the marker to be exactly
  `References` with no trailing characters — `References:` (with
  colon) is common and must match.
- For PDFs with running-header artefacts, consider piping through
  `grep -v '^[Pp]age [0-9]' | grep -v '<student-name-pattern>'`
  before awk, OR cross-check with a docx extraction if available.

### Reporting

- Report the measured count in the dossier header: e.g., "1,627 words
  body, on-time, under-range flag".
- Target range: 1,800–2,200 words (90–110% of the 2,000-word target).
- Under-range (<1,800): label "under-range flag — see word-count note
  below"; the note discusses whether the under-range is symptomatic
  of a quality dimension (e.g., synthesis weakness manifesting as
  short end-of-section paragraphs).
- Over-range (>2,200): label "over-range flag — see word-count note
  below"; per ANU policy, over-range >10% incurs a penalty unless the
  marker's discretion overrides.
- If extraction fails (no clear References marker, malformed file),
  report "body word count: UNPARSEABLE — verify manually" in the
  dossier header and proceed.

### Why this rule exists

The cohort progress file's overshoot list was empirically wrong for
~6 students because it used file word count (including references
and process statement) rather than body word count. Rule 8 prevents
this class of error.

## Rule 9 — A1→A2 commensurate criterion mapping

The HUMN8031 A1 (proposal) and A2 (literature review) rubrics are
structurally different but several criteria carry forward. Use this
mapping for the A1→A2 trajectory section:

| A1 criterion | A2 criterion | Direction of travel |
|---|---|---|
| C1 Research Problem, Question, and Aims | C1 Research Problem, Question, and Aims | Same dimension; A2 expects sharper problem framing and explicit scope justification |
| C2 Contextual Framework and Scholarly Engagement | C2 Scholarly Engagement, Analysis, and Synthesis | Carries forward but escalates: A1 situates within field; A2 builds an argument across sources |
| C3 Significance and Contribution | C3 Gap, Rationale, and Significance | A1 asserts significance; A2 demonstrates it through grounded gap argument |
| C4 Research Design and Feasibility | (no direct A2 equivalent) | A2 has no research-design criterion; A1 C4 is informational only |
| C5 Argumentative Coherence and Communication | C4 Argumentative Coherence and Communication | Same dimension; A2 weight increased from 10% to 20% (red thread now primary, not secondary) |
| C6 Research Process and Tool Use | C5 Research Process and Tool Use | Same dimension; A2 adds explicit process statement on top of inferential indicators |

The **commensurate criteria comparison** table in the A1→A2 section
of the dossier uses this mapping. A1 C4 (Research Design) is
typically not included since it has no A2 equivalent — note this
explicitly if the student had strong A1 C4 work that informs A3.

### Handling A1-research-design-focused feedback

When a student's A1 marker comments are **predominantly about C4
Research Design** (e.g., concerns about data plan vagueness, fallback
plans, methodological specificity), the A1 → A2 follow-through
section needs careful framing because A2 has no Research Design
surface. The A1 feedback-action checklist will tend toward "Partial"
or "N/A — A2 has no surface for this A1 item" labels, which can
underplay the legitimate point that the student couldn't directly
action C4 feedback in a literature review.

Three handling moves:

1. **Use the `N/A — A2 has no direct surface` label** on the
   `Actioned?` column for A1 items where the A2 assessment type
   doesn't have a place to address them. This is honest and not
   a negative reflection on the student.
2. **Note in the pattern summary** that the A1 feedback was
   predominantly research-design-focused, which means the A2 → A3
   trajectory is where the action will land (rather than A1 → A2).
   Frame this constructively: the student has the feedback queued
   for A3; the A2 may show framework-level uptake (e.g., "phenomenology
   committed as method, with a precedent source") even when
   operationalisation has to wait.
3. **A1 feedback-action language bullets (Section 9)** should
   acknowledge the A3-facing nature explicitly: "the A1 one-change
   item about [data operationalisation] is partially actioned at the
   framework level; for A3, this needs to operationalise — which
   productions, how interviewees recruited, what fallback if
   interviews aren't viable".

## Rule 10 — Anti-confabulation: cite specific paragraphs/phrases

Every descriptor-fit claim in the dossier must be **grounded in the
submission text** with one of:

- A direct quoted phrase (in italics or quote marks)
- A paragraph reference (e.g., "Section 1, paragraph 2")
- A specific source citation that the student uses (e.g., "the
  Auslander paragraph in Section 1")

Do not assert "the paper does X" without showing where. If the claim
cannot be grounded, the claim is wrong or under-evidenced — drop it
or escalate to a hedge.

This applies especially to:

- Drift-catch claims in Stage 2 (the "A2 evidence supports D" section
  must cite the A2 evidence)
- Per-criterion borderline comments in Stage 4 (the Canvas paste-ables
  must name what the paper does that meets each tier descriptor)
- A1 feedback-action checklist (each row's "A2 evidence" cell must
  cite specifically)

## Rule 11 — Drift-catch as one internal trigger inside Stage 2 (NOT a named protocol)

Drift-catch is the heuristic "marker has been reading for hours; an
A1→A2 regression on a criterion is a candidate for re-reading on the
upward side." It is **retired as a named protocol** because the n=18
cohort data did not support the asymmetric "fatigue → under-mark"
hypothesis (about half the lifts held; half were corrected down).

In v0.1.x, drift-catch lives as **one internal trigger among
several** inside Stage 2. The triggers that can prompt an upward
review of a criterion are:

1. A1→A2 regression on the commensurate criterion (drift-catch)
2. The marker's contemporaneous comment praises something that the
   tier picks do not reward (potential under-counted strength)
3. Descriptor-fit reading on a re-read suggests the higher tier is a
   clean case (default-to-lower can be overcome)
4. The criterion is borderline by tier-boundary marks (e.g., the
   marker picked the bottom of D where descriptor evidence reaches
   the top of D)

None of these triggers is a "drift-catch flag" in the dossier output.
Stage 2's section heading is **"Upward check"**, never
"Drift-check flags". The triggers are visible in Stage 2's reasoning
("A1 C3 D → A2 C3 Cr triggered an upward re-read of the gap
section…") but the dossier verdict labels are the locked vocabulary:
`Aligned`, `Lift recommended`, `Hold recommended`, `Borderline`.
