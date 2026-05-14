# Stage 3 — Downward check

You are running Stage 3 of the `moderate-mark` pipeline. Your job is
to take the Stage 1 + Stage 2 dossier and walk a **downward review**
on every criterion (not just those flagged for upward). This is
diligence: the dossier should be symmetric in its scrutiny up and
down. Apply Discipline Rules 1, 2, 4, and 10.

## Inputs

| Input | Path |
|---|---|
| Stage 1 + 2 dossier (in place) | `reports/marking/dossiers/<stem>-<submission-id>.md` |
| Marker tier picks | `reports/marking/a2-shawn-marks/<stem>-*.md` |
| Submission body text | `data/submissions-lit-review/extracted/<stem>-*.txt` |
| Rubric definition | `reports/marking/a2-rubric-definition.json` |
| Discipline rules | `discipline-rules.md` (re-read Rules 1, 2, 4, 10) |
| Format spec | `dossier-format.md` (Section 5b) |
| Voice reference | `examples/jiang-xinrui-canonical.md` |

## What you produce

You **rewrite Section 5b (Downward check)** of the dossier in place.
Other sections are not touched. The Stage 1 placeholder
`*Pending Stage 3.*` is replaced.

## Step-by-step

### 0. Pre-flight: verify Stage 1 + 2 dossier exists

Before reading anything else, verify the dossier file at
`reports/marking/dossiers/<stem>-<submission-id>.md` exists AND that
Section 5a (Upward check) is not still a Stage 2 placeholder. If
either condition fails, bail with:

```text
Stage 3 requires a Stage 1 + Stage 2 dossier at <path>. <Reason:
file does not exist | Section 5a is still '*Pending Stage 2.*'>.
Run the prior stages first.
```

Do NOT create a dossier from scratch and do NOT run Stage 2 logic
— Stage 3 owns Section 5b only.

### 1. Read the Stage 1 + 2 dossier

Note:
- The marker tier picks (per Section 3, Marker tier column)
- Stage 1's descriptor-fit reads (per Section 3, Descriptor-fit
  column)
- Stage 2's upward check outcomes (per Section 5a) — particularly
  any criteria where Stage 2 recommended a Lift; these need the
  downward check applied to the *recommended new tier*, not the
  marker tier (because if Stage 2 lifted, you're now checking
  whether that lift is itself defensible against a downward read).

### 2. For each criterion (C1–C5), walk the downward case

Per the format spec (Section 5b), each criterion subsection has:

- **A2 evidence considered for downward read** — bulleted evidence
  that would support a lower tier (paragraph patterns that match the
  lower tier's descriptor, weaknesses identified by the marker, etc.).
  Cite specifically (Rule 10).
- **Cohort-relative read (Rule 4)** — one sentence on whether the
  ANU Masters cohort norm (modal D, mean low 70s, HD reserved)
  pulls this tier toward the lower band. Especially relevant for
  HD calls (where the cohort-relative read is "are 1–2 papers per
  cohort doing this — and is this paper one of them?") and for D
  calls at the upper end.
- **Marker comment check (Rule 2)** — one sentence on whether the
  marker's own contemporaneous comment supports the lower tier or
  the marker tier. If the marker praised the criterion, that's
  evidence against a downward call. If the marker raised
  reservations, that's evidence in favour.
- **Conclusion** — `Hold at <current tier>.` (the common case) or
  `Lower-fit flagged for marker review` (the unusual case where
  descriptor evidence + cohort norm + marker comment all point lower).

### 3. The common case: Hold

Most criteria will conclude `Hold at <marker tier>`. The downward
check is diligence; it's not a search for downgrades. Do not
manufacture downward cases to look balanced. If the marker's tier
is descriptor-clean, write a brief subsection saying so:

> **A2 evidence considered for downward read:** No descriptor evidence supports a lower tier; the <criterion> is at the cleanly-D level (paragraph X-Y demonstrate Z).
>
> **Cohort-relative read (Rule 4):** Cohort-typical D; no cohort-relative pull toward Cr.
>
> **Marker comment check (Rule 2):** Marker's comment praises <feature>, supporting the marker tier.
>
> **Conclusion:** Hold at D.

### 4. The unusual case: Lower-fit flagged

When does Stage 3 flag a downward case?

- The descriptor evidence reads cleanly to the lower tier (e.g., the
  marker called Cr but the predominant pattern matches the P
  descriptor, with the higher-tier features appearing only in one
  or two sections);
- AND the cohort-relative read does not lift the call back up (e.g.,
  this isn't a paper that the cohort norm would push into the
  marker tier);
- AND the marker's own comment doesn't strongly back the marker
  tier — or, more strongly, the marker's comment names a feature
  of the lower tier's descriptor (Rule 2 in the downward direction).

When you flag a downward case, do not "recommend a lower call"
unilaterally. Surface it as `Lower-fit flagged for marker review`
and let Stage 4 reconcile. The downward case is rare and the marker's
contemporaneous judgement should usually win unless the descriptor
evidence is overwhelming.

Example downward-flag pattern:

> **C2 Synthesis — Lower-fit flagged for marker review**
>
> **A2 evidence considered for downward read:** The predominant
> pattern in Sections 1–4 is one source per paragraph with brief
> end-of-section synthesis paragraphs (Auslander gets three
> paragraphs alone in Section 1; Bay-Cheng/Radak each get individual
> paragraphs in Section 2). The P descriptor's "series of individual
> source summaries with limited connection between them" matches
> the dominant pattern; the Cr descriptor's "moments of analysis…
> appear in one or two sections" reads as already-generous given the
> source-by-source pattern across all four sections.
>
> **Cohort-relative read (Rule 4):** Cohort-typical Cr/P boundary
> case; no cohort norm pulls toward Cr.
>
> **Marker comment check (Rule 2):** Marker's "One Change" comment
> names the P descriptor's defining feature ("sources presented
> serially, usually one-per-paragraph") almost verbatim. This is
> descriptor evidence for P.
>
> **Conclusion:** Lower-fit flagged for marker review. The
> descriptor-strict read is P; the marker's tier is Cr. Stage 4 will
> reconcile (likely outcome: Hold at Cr under default-to-marker,
> because the marker's tier is the call of record and the descriptor
> case is debatable; but the lower-fit observation should be visible
> in the dossier so the moderator can see the case).

### 5. If Stage 2 recommended a lift, apply the downward check to the lifted tier

If Stage 2 recommended C3 lift from Cr to D, Stage 3 walks the
downward case for D on C3 (does the descriptor evidence cleanly
reach D, or is this a borderline lift?). Most lifts will hold under
Stage 3 because Stage 2 already required descriptor-clean evidence,
but the discipline of checking is what the symmetric pipeline is for.

If the downward check on a Stage-2-lifted criterion reads cleanly
back to the marker tier, that's a signal: Stage 4 reconciliation
should walk back the lift. Note this in the downward subsection's
conclusion: `Downward case for <marker tier> is descriptor-clean;
Stage 2 lift recommendation walked back at Stage 3.`

### 6. Verify and report

Re-read your Section 5b content. Verify:
- Every criterion (C1–C5) has a subsection (even short ones)
- Every subsection cites specifically (Rule 10)
- Every Conclusion line uses one of the two allowed labels
- Any downward-flagged criteria explain the binding evidence

Report to the driver: list of criteria walked, conclusions per
criterion (Hold / Lower-fit flagged), any cases where Stage 2's lift
recommendation should be walked back.

## What NOT to do

- **Do not** flag downward cases for the sake of symmetry. Most
  criteria will hold; that's correct.
- **Do not** override the marker tier unilaterally. The downward
  case is *flagged for marker review*, not *recommended*. Stage 4
  reconciles; the marker is the final authority.
- **Do not** rewrite other sections. Stage 3 owns Section 5b only.
- **Do not** make claims without grounding (Rule 10).
- **Do not** apply cohort-relative discipline (Rule 4) as the *only*
  reason for a downward flag. Cohort norm informs; descriptor evidence
  decides. A downward flag needs both.
