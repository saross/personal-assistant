# Pre-Survey Data for Rubric Design

When student baseline data is available (e.g., a Week 1 digital skills
self-assessment), it directly informs rubric calibration.

## Most useful fields for rubric design

| Field type | What it reveals | How it informs the rubric |
|---|---|---|
| **Research topic descriptions** (free-text) | Concrete examples for callout boxes and descriptor examples; range of methodological approaches | Use real student topics instead of generic placeholders |
| **Tool experience** (reference managers, LLMs, project management) | Baseline proficiency; whether tool-use criteria are realistic | Calibrate expectations — if near-zero experience, assess engagement and development rather than mastery |
| **LLM experience split** (general vs academic/research) | Gap between casual use and deliberate research use | Confirm that the rubric should assess *academic* LLM use specifically |
| **Prompt engineering experience** | Whether students have any prior structured prompting practice | If near-zero, the "Research Process and Tool Use" criterion should reward engagement with taught prompts rather than assume independent prompt development |
| **Self-assessment confidence** (Likert items on evaluating LLM accuracy, project management, etc.) | Where students feel uncertain | Shape descriptor language — distinguish "engaging but developing" from "not engaging" |
| **Free-text gaps and aspirations** | Theory-practice tension; what students want to learn | Informs methodology expectations — assess whether students can describe and justify a method, not whether it is sophisticated |

## Recommended additions to pre-surveys

These fields were identified as missing from an existing pre-survey
after using the data for rubric design:

1. **Research workflow** — "Describe the steps you typically follow when
   writing an academic paper (from first idea to final submission)"
2. **Peer review experience** — "Have you given or received peer review
   on academic writing before?"
3. **Writing process** — "Do you typically draft everything first and
   then revise, or revise as you go?"
4. **Prior rubric experience** — "Have you used a marking rubric to
   assess your own work or give feedback on a classmate's?"
5. **Research question status** — "Have you already formulated a
   research question, or are you still exploring a topic area?"

## Recommended consolidations

If the pre-survey has many fine-grained tool experience items with
near-uniform responses ("Never used" across most students):

- Collapse command-line tools (terminal, SSH, file management) → 1 item
- Collapse programming languages (Python, R, JS, SQL, etc.) → 1 item +
  free-text "which languages?"
- Collapse open research practices (FAIR, ORCID, DOIs, etc.) → 1 item
- **Keep** Likert self-assessment items (these produce genuine variation)
