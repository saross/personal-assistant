# Stage 2 — Upward check

You are running Stage 2 of the `moderate-mark` pipeline. Your job is
to take the neutral dossier produced by Stage 1, identify criteria
where Stage 1 flagged a non-`agree` upward direction read, and walk
the upward case for each. Apply Discipline Rules 1, 2, 4, 10, and 11.

## Inputs

| Input | Path |
|---|---|
| Stage 1 dossier (in place) | `reports/marking/dossiers/<stem>-<submission-id>.md` |
| Marker tier picks | `reports/marking/a2-shawn-marks/<stem>-*.md` |
| A1 feedback (if present) | `reports/marking/a1-feedback/<stem>-*.md` |
| Submission body text | `data/submissions-lit-review/extracted/<stem>-*.txt` |
| Rubric definition | `reports/marking/a2-rubric-definition.json` |
| Discipline rules | `discipline-rules.md` (re-read Rules 1, 2, 4, 10, 11) |
| Format spec | `dossier-format.md` (Section 5a) |
| Voice reference | `examples/jiang-xinrui-canonical.md` |

## What you produce

You **rewrite Section 5a (Upward check)** of the dossier in place.
Other sections are not touched. The Stage 1 placeholder
`*Pending Stage 2.*` is replaced with the Upward check content.

## Step-by-step

### 0. Pre-flight: verify Stage 1 dossier exists

Before reading anything else, verify the dossier file at
`reports/marking/dossiers/<stem>-<submission-id>.md` exists. If not,
bail with:

```text
Stage 2 requires a Stage 1 dossier at <path>, but the file does not
exist. Run /moderate-mark stage-1 <student-stem> first, or run the
full pipeline /moderate-mark <student-stem>.
```

Do NOT create a dossier from scratch — Stage 2 owns Section 5a only
and assumes Stage 1 has populated Sections 1, 3, 4, 5.

### 1. Read the Stage 1 dossier

Identify the criteria where Stage 1's "Direction" cell reads:
- `descriptor-fit one tier higher` (clean upward candidate)
- `descriptor-fit one tier higher, with hedge` (borderline upward
  candidate)

These are the criteria you'll walk in Stage 2.

Also note the **internal triggers** (Rule 11) that may surface
additional upward candidates not flagged by Stage 1:

1. **A1→A2 regression** on the commensurate criterion (drift-catch)
2. **Marker-comment-praises-something-that-tier-picks-do-not-reward**
   (potential under-counted strength)
3. **Tier-boundary marks** — the marker picked the bottom of the band
   where descriptor evidence reaches the top
4. **Re-read suggests descriptor-clean upward case** even if Stage 1
   read `agree`

If any of triggers 1–4 fires for a criterion that Stage 1 marked
`agree`, add that criterion to your Stage 2 walk.

### 2. For each candidate criterion, walk the upward case

Per the format spec (Section 5a), each criterion subsection has:

- **Pattern line** — name the trigger(s) that prompted the upward
  re-read. Be honest: if it's pure descriptor re-read with no
  trajectory or comment trigger, say so.
- **A2 evidence supports <higher tier>** — a bulleted list of
  specific evidence with paragraph or source citations (Rule 10).
- **<Higher tier> descriptor reads** — direct quote from the rubric
  descriptor for the higher tier; one sentence on whether the
  evidence fits.
- **<Marker tier> descriptor reads** — direct quote from the marker
  tier's descriptor; one sentence on whether the evidence fits the
  marker tier's "what NOT to count" features.
- **Recommendation** — one of:
  - `Lift to <higher tier> (<old-points> → <new-points>). Canned total moves from <old> → <new>.`
  - `Hold at <marker tier> — <reason>.` Reasons are typically:
    - Marker comment names lower-tier feature (Rule 2)
    - Default-to-lower discipline at boundary (Rule 1)
    - Descriptor case is hedged (Borderline)

### 3. Apply Discipline Rule 2 strictly

For every candidate lift, check the marker's contemporaneous comment
(per-criterion comment, "One change" comment, "Strongest aspect"
comment, "Overall" comment). If any of these names a defining feature
of the marker tier's descriptor (or the lower tier below), this is
descriptor evidence for the marker tier — **not** commentary about it.

Rule 2 produces three possible outcomes, mapped to the locked
verdict vocabulary (`Lift recommended` / `Hold recommended` /
`Borderline`):

- **Marker comment supports the lift** (rare): the comment praises
  something at the higher tier and your descriptor evidence backs
  it. → Recommendation line uses **`Lift recommended`**.
- **Marker comment is silent on the criterion** (common): the comment
  doesn't speak to this descriptor. Apply Rule 1 (default-to-lower).
  Two sub-cases:
  - **Descriptor case for higher tier is clean and unhedged** →
    Recommendation line uses **`Lift recommended`** (Rule 1 doesn't
    block a clean upward case).
  - **Descriptor case for higher tier is hedged** (mixed indicators,
    some features fit, some don't) → Recommendation line uses
    **`Hold recommended`** with the criterion labelled `Borderline`
    in the dossier prose ("Hold at <tier> under Rule 1 — descriptor
    case for the higher tier is hedged; Borderline").
- **Marker comment names the lower tier's defining feature**: this
  is the principal anti-inflation case. → Recommendation line uses
  **`Hold recommended`**, citing Rule 2 as the binding consideration
  ("Hold at <tier> under Rule 2 — marker's One Change comment names
  the P descriptor's defining feature almost verbatim").

In the dossier prose, the `Borderline` label is a **hedge tag** that
qualifies a Hold recommendation — it signals "the descriptor case
for the higher tier is genuinely defensible; a second reader weighting
differently could lift". The recommendation outcome itself is one of
`Lift recommended` or `Hold recommended`; `Borderline` annotates a
Hold to surface the hedge to the moderator.

### 4. Apply Discipline Rule 1 at boundaries

If the descriptor evidence is genuinely borderline between two tiers
(e.g., 2 of 4 indicators in higher tier, 2 in lower), default to the
lower tier. Do not lift on a 50/50 read; lift requires a clean upward
case.

### 5. Recommendation labels (locked vocabulary)

Use only:

- **Lift recommended** — descriptor evidence is clean for the higher
  tier; Rule 2 does not block.
- **Hold recommended** — descriptor evidence reads borderline-to-
  upward but Rule 1 or Rule 2 keeps the marker tier.
- **Borderline** — descriptor case is genuinely defensible either way;
  surfaced for transparency, not as a recommendation. (This is a
  hedge label, not a recommendation outcome — it tells the moderator
  the call could go either way.)

### 6. If no criteria are candidates

If Stage 1 flagged no upward candidates AND none of the internal
triggers 1–4 surface additional ones, write a single-line section:

```markdown
## Upward check

No upward candidates. All criteria read `agree` in Stage 1; no internal triggers (A1→A2 regression, marker-comment praise mismatch, tier-boundary marks, re-read upward case) surface additional candidates.

---
```

### 7. Verify and report

Re-read your Section 5a content. Verify:

- Every candidate criterion has a subsection
- Every subsection cites specific evidence (no vague claims)
- Every Recommendation line uses the locked vocabulary
- Every Hold recommendation names which discipline rule binds (Rule
  1, Rule 2, or `Borderline` hedge)
- Lift recommendations include the points change and updated canned
  total

Report to the driver: list of criteria walked, recommendation
outcomes per criterion (Lift / Hold / Borderline), updated canned
total if any lifts are recommended.

## What NOT to do

- **Do not** label this section "Drift-check flags" or "Drift-catch
  flags" (Rule 11). The heading is **"Upward check"**.
- **Do not** introduce drift-catch as a named protocol in your prose.
  It's one trigger among several; mention it in the Pattern line if
  it fired ("A1 C3 D → A2 C3 Cr triggered an upward re-read of the
  gap section"), but don't elevate it.
- **Do not** recommend a lift that contradicts the marker's
  contemporaneous comment unless you have explicit, strong
  counter-evidence (and explain that counter-evidence). Default is
  Hold under Rule 2.
- **Do not** rewrite Sections 1–5 or Section 5b. Stage 2 owns Section
  5a only.
- **Do not** make claims without grounding (Rule 10).
