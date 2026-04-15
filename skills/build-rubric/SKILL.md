---
name: build-rubric
description: >-
  This skill should be used when the user asks to "build a rubric",
  "create a rubric", "design a rubric", "make a marking rubric",
  "assessment rubric", or "rubric for [assessment name]". Also trigger
  when the user mentions needing to mark or assess student work and
  a rubric does not yet exist. Do not trigger for rubric review or
  revision of an existing rubric — only for building a new one.
version: 0.2.0
---

# Build Rubric

Build an analytic, task-specific marking rubric through a structured
collaborative process. The rubric is designed for three audiences:
the marker, student peer reviewers, and automated evaluation (Claude).

## Process overview

The rubric-building process has seven phases. Do not skip phases.
Each phase builds on the previous one.

```text
1. Gather  →  2. Interview  →  3. Research  →  4. Propose
   ↓                                               ↓
7. Revise  ←  6. Audit  ←  5. Draft
```

## Phase 1: Gather context

Collect all available source material before asking the user anything.
Read in parallel:

- **Course learning outcomes** — search for CLOs, ILOs, or learning
  outcomes in course documentation, Canvas materials, or syllabi
- **Assessment description** — the published task specification
  students will read
- **Teaching materials** — runsheets, lecture notes, slides, and
  Canvas module pages for weeks preceding the assessment deadline
- **Textbook or reading references** — what chapters/readings were
  assigned before the due date
- **Student baseline data** — pre-survey, self-assessment, or
  diagnostic data if available (see `references/pre-survey-guide.md`)
- **Institutional rubric guidance** — check
  `references/rubric-design-principles.md` for cached guidance; if
  the institution differs from ANU, do a web search for their rubric
  policy
- **Existing rubrics** — check whether rubrics exist for other
  assessments in the same course

### Evolving from an existing rubric

If building a rubric for a later assessment in a scaffolded sequence
where an earlier rubric already exists (and is available as a worked
example in `references/`):

- **Start from the existing rubric's structure**, but be prepared to
  adapt it. Different assessment types need fundamentally different
  criterion structures (see Phase 4). Evolve, don't just relabel.
- **Carry forward named concepts** (red thread, assert vs. demonstrate,
  etc.) and extend them for the new context.
- **Design backward references** deliberately — each criterion should
  note what carries forward and what has escalated.
- **Check for carry-forward notes** — previous sessions may have
  documented specific design decisions, deferred items, or
  recommendations for the next rubric. These are high-value context.
- Phases 1 and 2 will typically be faster because many sources and
  decisions are already known. Focus Phase 2 questions on what is
  *new* — changed CLOs, new assessment components, shifted weighting
  rationale.

Synthesise what was gathered, then produce a **teaching timeline**:
map which textbook chapters, class activities, and course tools were
introduced *before* the assessment deadline vs. after it. This
timeline directly determines:

- What the rubric can **fairly assess** (taught before deadline)
- What must be **excluded** (introduced after deadline — hard rule,
  not just lower-weighted)
- How criteria should be **weighted** (more teaching time = higher
  weight is defensible, but equal weighting across components with
  comparable teaching support is often fairer than unequal weighting
  based on abstract importance)

## Phase 2: Interview the convenor

Interview the user to understand priorities, constraints, and design
decisions. **Ask one question at a time.** Do not batch questions.

Suggested interview sequence (adapt as needed):

1. Grading scale and rubric format (e.g., HD/D/Cr/P/N, analytic vs
   holistic, institutional template requirements)
2. How will the rubric be used — marking only, or also peer review
   and/or automated evaluation?
3. Should tool/AI use be assessed, and if so, how prominent should
   it be? (Separate criterion, integrated, or hybrid?)
4. What are the highest-priority qualities in a submission?
5. Any constraints or strong preferences?

Continue until you have enough to propose a structure. Typically
3–6 questions suffice. When documented carry-forward notes exist from
a previous rubric build, review them first and skip questions already
answered — typically 2–4 new questions suffice for later rubrics in
a sequence.

## Phase 3: Research best practice

Load cached guidance from `references/rubric-design-principles.md`.
Then run a **delta search**: web search for recent developments in
rubric design (particularly AI/LLM assessment, which evolves rapidly).
Search terms: "rubric design [current year]", "AI assessment rubric
higher education", "analytic rubric best practice".

Key frameworks to check for updates:
- AI Assessment Scale (Perkins et al.) — levels of permitted AI use
- TEQSA assessment reform guidance (Australian context)
- AAC&U VALUE rubrics (general rubric models)

## Phase 4: Propose structure

Present to the user:

- **Criteria** (recommend 4–6). Each criterion maps to one or more
  CLOs. Name each criterion clearly. The number of criteria should
  reflect the assessment's complexity — focused assessments (e.g.,
  a literature review) may need fewer criteria than multi-component
  assessments (e.g., a research proposal with distinct sections).
- **Weighting**. Weight criteria according to what was *actually
  taught* by the submission deadline, not abstract importance. If
  key skills were introduced late or not yet covered, reduce
  weight accordingly.
- **Performance levels**. Use the institutional grade scale.
- **Minimum standards** (gating requirements). Identify compliance
  items (word count, formatting, required components) that should
  be pass/fail gates, not graduated criteria. Gating requirements
  should cover **task-specific** requirements only. Reference
  institutional policies (late submission, academic integrity,
  special consideration) without duplicating their specifics — e.g.,
  "ANU late submission policy applies" rather than stating the
  penalty schedule — so the rubric does not fall out of sync if the
  policy changes.

### Assessment type and criterion structure

Different assessment types need fundamentally different criterion
structures:

- **Multi-component assessments** (proposals, reports with distinct
  sections) — criteria map to *components*. Each major component
  gets a criterion because the components are separately assessable
  and serve different purposes. 6 criteria is typical.
- **Focused assessments** (literature reviews, essays, reflective
  pieces) — criteria decompose *quality dimensions* of a single
  activity. The assessment is one thing done at varying depths,
  not several distinct things. 4–5 criteria is typical.
- **Mixed assessments** (research projects with both written and
  presented components, or digital projects with exegeses) — may
  need a hybrid approach: some component-based criteria (e.g.,
  methodology, findings) and some quality-dimension criteria (e.g.,
  argumentative coherence, communication). Consider whether the
  components are independently assessable or tightly interleaved.

When evolving from a previous rubric in a sequence, the assessment
type may shift (e.g., proposal → literature review → research
project). Do not assume the previous rubric's structure carries
over — examine whether the new assessment's type demands a different
criterion architecture.

Present as a table. Ask for feedback before drafting descriptors.

### Multi-assessment sequences

If this rubric is part of a scaffolded assessment sequence:

- **First assessment:** Tool use and process are assessed
  *inferentially* from observable quality indicators (no process
  statement required). Use the "what would tools have caught" lens
  to frame peer reviewer indicators.
- **Later assessments:** Add a lightweight **process statement**
  (150–250 words, appended after references, excluded from word
  count) that makes the research workflow explicit. Ask two focused
  questions: (1) which tools were used (list), (2) most significant
  way a tool shaped the work. Optionally add a reflective question.
  **Crucially, the process statement adds a direct channel; it does
  not replace the inferential one.** Continue to assess observable
  quality indicators alongside the student's self-report. The power
  is in the combination: the student claims "I used the self-review
  prompt to check my argument structure," and the marker verifies
  whether the argument structure actually shows signs of review.
  Claims without evidence are hollow; evidence without claims is hard
  to interpret. Together they are diagnostic.
- **Backward references:** Later rubrics should reference earlier ones
  ("In Assessment 1, research process was assessed inferentially from
  observable quality; in this assessment, you also demonstrate it
  explicitly through your process statement"). This creates continuity
  without adding cognitive load to the earlier rubric.
- **Weight escalation:** The process/tool-use criterion can carry
  more weight in later assessments as students develop proficiency.
- **Gating escalation:** Skills assessed on a graduated scale in
  earlier assessments can become binary gating requirements in later
  ones (e.g., reference manager use: observable indicator in
  Assessment 1 → gating requirement in Assessment 2). Flag any such
  escalation clearly in the rubric so students notice.
- **Fairness notes carry forward:** If the first rubric included a
  note about student baseline or developing proficiency, update and
  carry it to later rubrics. The cohort context is still relevant —
  students' starting point hasn't changed, even if expectations have
  grown.
- **Standard over delta:** Descriptors in later rubrics should assess
  quality *at the point of submission*, not improvement since the
  previous assessment. Improvement is valuable context and always
  counts in the student's favour, but making it the primary criterion
  creates a ceiling for strong students (small delta despite
  consistently high quality) and a perverse incentive where a weak
  first submission is advantageous (large delta available). Use
  teaching callout boxes (e.g., "Carrying forward from Assessment 1")
  to acknowledge the growth narrative and explain that improvement is
  expected and rewarded — but keep the descriptor table focused on
  the quality standard for this assessment.

## Phase 5: Draft descriptors

Write descriptors following these principles (detailed guidance in
`references/rubric-design-principles.md`; worked example in
`references/example-rubric-assessment1.md`):

### Descriptor writing rules

1. **Descriptive, not evaluative.** Describe what the work looks
   like, not how good it is. Avoid "excellent", "sophisticated",
   "appropriate" unless operationalised.
2. **Strengths-based at all levels.** Even the lowest level describes
   what IS present, not what is absent. "Names a broad area of
   interest but does not formulate a research problem" not "Does not
   identify a research problem."
3. **Parallel structure.** Every level addresses the same dimensions
   at different quality. If HD mentions framework, question, and
   title, so do D, Cr, P, and N.
4. **Action verb differentiation.** Use verbs as the key
   differentiator: synthesises → analyses → describes → lists →
   names.
5. **Observable and measurable.** Every descriptor must answer: "What
   would I see in the student's text?" If a peer reviewer or LLM
   cannot operationally check it, rewrite it.
6. **Surface diagnostic logic in descriptors.** If a criterion uses
   a diagnostic framework (e.g., comparing process statement claims
   against observable quality indicators), that logic must appear in
   the descriptor table — not only in guidance prose. Markers
   determine grades from the descriptor table; guidance they read
   before the table informs but does not replace the descriptors.
7. **Use real examples from the cohort.** Draw from student pre-survey
   data, declared topics, or course running examples — not generic
   X/Y/Z placeholders. Students recognise their own concerns, which
   makes the rubric feel relevant and teaches through familiarity.
8. **Standard over delta (multi-assessment sequences).** In later
   assessments, descriptors must assess quality at the point of
   submission — not improvement since the previous assessment.
   Avoid language like "refined since Assessment 1" or "clearer
   than the proposal" in descriptor tables. Instead, describe what
   the quality looks like at each level. Use "Carrying forward"
   callout boxes to acknowledge growth expectations and explain
   that improvement counts in the student's favour. See the
   multi-assessment sequences section in Phase 4 for the full
   rationale.

### Teaching callout boxes

Add a blockquoted teaching callout between each criterion description
and its descriptor table. Each callout follows the pattern:

1. **Name the skill** that distinguishes quality levels
2. **Explain it concretely** with a before/after example (drawn from
   the cohort where possible)
3. **Point to the course tool** that teaches or practises the skill

Target the **Cr/D boundary** — that is where most students cluster
and where the most actionable improvements sit. These callouts
transform the rubric from a summative instrument into a formative
teaching tool (the "dual structure": descriptor tables = assessment
instrument, callout boxes = teaching instrument).

### Name transferable concepts

When a quality distinction recurs across criteria or across
assessments, give it a name that students can carry forward:

Named concepts become shared vocabulary between instructor, students,
and peer reviewers. They make feedback more precise ("your
significance section asserts rather than demonstrates") and help
students self-diagnose. The inventory grows as rubrics are built —
later rubrics carry forward earlier concepts and introduce new ones.

**Current inventory** (update as new concepts are named):

| Concept | Introduced | Meaning |
|---------|-----------|---------|
| **Topic vs. problem** | Assessment 1 | Area of study vs. what is unresolved within it |
| **Assert vs. demonstrate** | Assessment 1 | Claiming significance vs. grounding it in evidence |
| **Red thread** (*der rote Faden*) | Assessment 1 | The continuous argument connecting all sections |
| **Cosmetic satisficing** | Assessment 1 | LLM improves surface polish but structural problems remain |
| **Name vs. plan** | Assessment 1 | Naming a method vs. explaining what you will do with it |
| **Summary vs. analysis vs. synthesis** | Assessment 2 | Three levels of engagement with sources (describes → evaluates → connects) |
| **Scope as deliberate choice** | Assessment 2 | Explaining where boundaries are drawn and why |
| **Grounding** | Assessment 2 | Citing specific sources that create a gap, rather than asserting the gap exists |
| **Judgement vs. taste** | Assessment 2 | Knowing a tool is appropriate (judgement) vs. choosing between tools based on fit (taste) |

### Tool-use criterion: the "what would tools have caught" lens

When designing a criterion for research process or tool use, frame
peer reviewer indicators as **weaknesses that collaboration with
course tools would likely have caught**. For each observable
indicator, name the specific tool:

- Circular argument → writing self-review prompt would flag this
- Unrealistic timeline → feasibility audit prompt would surface this
- Topic-as-question → research question refinement prompt addresses
  this
- Assertion without evidence → self-review prompt checks for this

This creates a **feedback loop**: peer reviewers learn both what is
wrong *and* which tool to recommend. Students receiving feedback
get actionable next steps, not just a diagnosis.

### Start from the top

Write the HD descriptor first, then work downward. The HD descriptor
defines what excellence looks like; lower levels are qualitative
variations, not quantitative reductions.

### Peer reviewer accessibility

If the rubric will be used for peer review:
- Add a glossary for specialist terms
- Add criterion-specific guidance where peer reviewers lack
  disciplinary expertise
- Add guidance for the process/tool-use criterion explaining what
  observable indicators to look for

### Automated evaluator instructions

If the rubric will be used for automated evaluation:
- Add a dedicated instructions section for Claude
- Note limitations (e.g., image-based Gantt charts cannot be read)
- Require quoted evidence from the submission for every claim
- Require assessment of each criterion independently

## Phase 6: Audit

Run a systematic audit of the draft rubric against **every source
from Phase 1**, plus:

- **Three-audience test**: For each criterion, can the marker
  distinguish adjacent levels? Can a peer reviewer apply it? Can
  Claude operationally assess it?
- **Alignment check**: Does every component in the assessment
  description have a home in the rubric? Does the rubric add
  requirements not in the description?
- **CLO operationalisation check**: For each CLO listed in the
  rubric header, can a marker trace it to at least one concrete
  observable indicator in a descriptor? If a CLO is new to this
  assessment (not assessed in earlier ones), it needs visible and
  distinct operationalisation — not just a CLO number in the
  criterion header.
- **Fairness check**: Does the rubric assess what was *taught* by
  the deadline? Are expectations realistic given the student
  baseline data?
- **Best practice check**: Are descriptors strengths-based, parallel,
  observable, verb-differentiated? (See
  `references/rubric-design-principles.md`)

Report issues by severity: critical (would cause assessment problems),
important (reduces effectiveness), minor (would improve quality).

## Phase 7: Revise

Address all critical and important issues from the audit. Update the
revision log in the rubric. Present the revised rubric to the user
for final review.

## Output structure

The final rubric should include:

1. Header (assessment details, CLOs assessed, AI Assessment Scale
   level)
2. Minimum standards (gating requirements as a checklist)
3. Criteria with teaching callout boxes and descriptor tables
4. Scoring table with weighting
5. **Instructions** for peer reviewers (use "Instructions", not
   "Notes" — signals operational guidance, not optional commentary)
6. **Instructions** for automated evaluation (if applicable)
7. Revision log

### Section naming convention

Use **"Instructions for"** rather than "Notes for" when the content
is operational guidance that readers should follow. Use **"Guidance
for"** when the content is criterion-specific and applies to both
markers and peer reviewers. Reserve "Note" for contextual information
(e.g., "Note on assessment context" explaining that mastery is not
expected).

## Stretch goals

Offer these if the user is interested:

- **Claude-as-evaluator for comparison marking.** The marker grades
  by hand, then Claude evaluates the same submission against the
  rubric. Comparing the two reveals where the rubric's descriptors
  are ambiguous (marker and Claude disagree) and where they are
  well-operationalised (they converge). Requires the rubric's
  automated evaluation instructions to be thorough.
- **Running submissions against course prompts.** Submit student work
  to the same LLM prompts students had access to (e.g., a writing
  self-review prompt) and compare the LLM's feedback with the
  submission's actual qualities. This reveals whether students used
  the tools — if the prompt flags issues the student didn't address,
  they likely didn't use it. Resource-intensive but diagnostic.

## Companion documents

After the rubric is finalised, offer to produce:

- **Student-facing rubric guide** — plain-language explanation with
  worked examples drawn from the cohort's declared research interests,
  self-assessment steps, peer feedback guidance (including how to
  distinguish surface from structural feedback), and FAQ. Should be
  standalone (readable without the rubric open alongside) and treat
  students as emerging researchers, not schoolchildren. Aim for
  2000–2500 words (15–20 min read).
- **Next-delivery improvements** — friction points discovered during
  rubric construction, for revising the assessment description next
  time the course runs. Each recommendation should cite the specific
  rubric criterion and description text that revealed the friction.
  The rubric-building process *always* reveals assessment description
  gaps — capture them systematically.
- **Pre-survey improvements** — which survey fields were useful for
  rubric design, suggested additions, and suggested consolidations.
  See `references/pre-survey-guide.md`.
- **Assessment description updates** (if multi-assessment sequence) —
  revise later assessment descriptions to add process statements,
  strengthen tool requirements, add component structure, and include
  teaching callouts (e.g., "What 'analyse, synthesise, and discuss'
  means"). These are clarifications, not task changes.
