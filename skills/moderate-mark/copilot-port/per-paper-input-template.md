# Per-paper input template — Copilot port

Fill this template with one paper's data, then paste it into the
Copilot chat session that already has the bootstrap loaded. Use the
same template for both single-shot and multi-stage workflows.

**Privacy reminder:** This template, once filled, contains student
data. Paste only into Copilot. Do not cross to other AI tools.

---

## Template (copy from below the line and fill in)

---

```text
## PER-PAPER INPUT

### Student identifier
- Name: <Given Surname>
- Canvas user ID: <id>
- A2 submission ID: <id>
- Topic: <"Title of the literature review">
- A2 submitted: <YYYY-MM-DD>
- On time / late: <on-time | late by N days>
- Body word count: <N words>
- Word-count flag: <none | under-range (<1,800) | over-range (>2,200)>

### A1 grade and feedback
- A1 grade: <N (tier)>  OR  not available (late enrolee)
- A1 submitted: <YYYY-MM-DD>
- A1 per-criterion tier picks:
  - C1 Research Problem, Question, and Aims: <tier> (<pts>/<max>)
  - C2 Contextual Framework and Scholarly Engagement: <tier> (<pts>/<max>)
  - C3 Significance and Contribution: <tier> (<pts>/<max>)
  - C4 Research Design and Feasibility: <tier> (<pts>/<max>)
  - C5 Argumentative Coherence and Communication: <tier> (<pts>/<max>)
  - C6 Research Process and Tool Use: <tier> (<pts>/<max>)
- A1 marker comments (paste verbatim):
  - Strongest aspect: <quote>
  - One change: <quote>
  - Per-criterion (if any): <criterion + comment>

### A2 marker tier picks
- C1 Research Problem, Question, and Aims: <tier> (<pts>/10)
- C2 Scholarly Engagement, Analysis, and Synthesis: <tier> (<pts>/40)
- C3 Gap, Rationale, and Significance: <tier> (<pts>/15)
- C4 Argumentative Coherence and Communication: <tier> (<pts>/20)
- C5 Research Process and Tool Use: <tier> (<pts>/15)
- Total (sum): <N> / 100

### A2 marker comments (paste verbatim)
- Strongest aspect: <quote>
- One change: <quote>
- Per-criterion comments (if any): <criterion + comment>
- Overall comment (if any): <quote>

### A2 submission body text (paste full body)

<Paste the full body of the literature review here. Exclude:
metadata header (the # Source / # Submission ID / # Format lines if
present), the title and byline block, the References / Reference
List / Bibliography section, and the Process Statement / Process
Description section. Body should be ~2,000 words; if PDF extraction
introduced run-on tokens like "sitefor" or "isand", that's fine —
Copilot can handle it.>

### A2 process statement (paste verbatim if present)

<Paste the process statement here, separately from the body. The
process statement informs C5 Process and Tool Use; keep it
distinguishable from the body so Copilot doesn't conflate them.>

### END OF PER-PAPER INPUT
```

---

## Filling notes

### Body word count

Compute manually from the submitted file:

- **Word docs (.docx):** Word's status bar shows live word count. Highlight the body region (excluding title block, references, and process statement); the status bar will report the selection's word count.
- **PDF (.pdf):** Open in a PDF reader (e.g., Acrobat, Foxit). Use the Statistics panel or copy the body region into a Word doc and use Word's count.
- **Text (.txt):** Open in a text editor with a word count tool (most have one); select the body region; report the selection count.

Target range: **1,800–2,200 words** body (90–110% of the 2,000-word
target). Set the word-count flag accordingly.

### Tier names

Use the rubric tier names exactly as they appear in Canvas:

- `HD (80-100)`
- `D (70-79)`
- `Cr (60-69)`
- `P (50-59)`
- `N (0-49)`

If your marks file shows differently formatted tier names, normalise
to the above before pasting.

### Marker comments — verbatim, please

Paste the marker comments **verbatim** from Canvas. Do not paraphrase
or summarise. The skill applies Discipline Rule 2 (the marker's
comment IS descriptor evidence): if the marker named a defining
feature of a lower tier's descriptor, the dossier should not lift
that criterion. This rule only works if Copilot has the marker's
exact wording.

### Submission body — exclude references and process statement

Paste only the body of the literature review. Exclude:

- Title and byline block (1–3 lines at the top)
- Metadata header lines (anything starting with `# `)
- The References / Reference List / Bibliography section
- The Process Statement section (paste this separately in its own
  block)

If the submission has the title and byline awkwardly merged with the
first body paragraph, include them — the small over-count won't
matter to Copilot's analysis.

### Optional A1 fields

If a student is a late enrolee with no A1 submission, set `A1 grade`
to `not available (late enrolee)` and skip the A1 per-criterion
table and A1 marker comments. Copilot will note "A1 feedback
unavailable" in the dossier and proceed on A2 evidence alone.

---

## Worked example (anonymised)

Below is what a filled template looks like. **The data below is
fabricated; not a real student.** Use this only to confirm the shape
is right.

```text
## PER-PAPER INPUT

### Student identifier
- Name: Pat Example
- Canvas user ID: 1234567
- A2 submission ID: 7654321
- Topic: "Place-Making in Post-Industrial Riverfronts: A Literature Review"
- A2 submitted: 2026-04-19
- On time / late: on-time
- Body word count: 1,945 words
- Word-count flag: none

### A1 grade and feedback
- A1 grade: 70 (D)
- A1 submitted: 2026-03-22
- A1 per-criterion tier picks:
  - C1 Research Problem, Question, and Aims: D (15/20)
  - C2 Contextual Framework and Scholarly Engagement: Cr (13/20)
  - C3 Significance and Contribution: D (15/20)
  - C4 Research Design and Feasibility: D (15/20)
  - C5 Argumentative Coherence and Communication: D (7.5/10)
  - C6 Research Process and Tool Use: Cr (6.5/10)
- A1 marker comments:
  - Strongest aspect: Problem clearly articulated; you have a real research question, not just a topic.
  - One change: The framework section names sources but doesn't show how they relate to your question. Pull the framework into the argument rather than summarising it separately.

### A2 marker tier picks
- C1 Research Problem, Question, and Aims: D (7.5/10)
- C2 Scholarly Engagement, Analysis, and Synthesis: D (30/40)
- C3 Gap, Rationale, and Significance: Cr (9.75/15)
- C4 Argumentative Coherence and Communication: D (15/20)
- C5 Research Process and Tool Use: D (11.25/15)
- Total (sum): 73.5 / 100

### A2 marker comments
- Strongest aspect: The four-section architecture (industrial decline → community claims → planning interventions → post-industrial identity) maps directly onto the gap statement, and each section ends by setting up the next.
- One change: The gap section reads more as a closing summary than a positioning argument. For A3, the gap should follow from end-of-section limitations across the body, not be re-asserted at the end.
- Per-criterion comments: (none)
- Overall comment: Reference list well-formatted with DOIs throughout.

### A2 submission body text

Place-making has emerged as a central concept in urban studies of post-industrial transformation. This review examines how scholarship has addressed the reconstruction of riverfront identity following industrial decline, with particular focus on the tensions between heritage preservation and economic redevelopment...
[continue pasting full body — typically 1,800–2,200 words]

### A2 process statement

I used Zotero throughout to manage references and tag sources by section theme. The literature discovery meta-prompt from Week 6 helped me find sources outside my initial keyword search — particularly the heritage-preservation work that I'd otherwise have missed. Claude assisted with self-review of the gap section; the AI flagged that my original gap statement was "asserting rather than demonstrating" and prompted me to ground it in specific source limitations from the body.

### END OF PER-PAPER INPUT
```

This is the shape Copilot expects. Replace each field with the real
paper's data; keep the structure (the `### Section name` headings
and the field names) intact so Copilot's parsing is unambiguous.
