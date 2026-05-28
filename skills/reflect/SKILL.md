---
name: reflect
description: "End-of-session reflection protocol. Use when the user invokes /reflect or asks to reflect on the current session, do end-of-session reflections, or similar. Guides Claude through updating reflection documents in priority order, answering structured prompts, and maintaining the reflection and investigation logs."
---

# End-of-Session Reflection

Update the current project's reflection and observation documents following the
established protocol. Work through the documents in priority order. If context
is limited, prioritise the top of the list.

## Project Context

This is a cross-project skill. Reflections are always scoped to the **current
working directory** — the project you have been working in during this session.

1. **Determine the project**: Use the current working directory to identify the
   project. State it explicitly at the start of the reflection (e.g., "Reflecting
   on session work in map-reader-llm").
2. **Locate reflection docs**: Look for `docs/notes/reflections/` relative to
   the project root. If this directory does not exist, create the initial
   structure using the starter templates below.
3. **Tag output**: When writing reflection entries, include the project name and
   session date in the entry header so entries are unambiguous even if read out
   of context.

## Initial Structure (new projects)

When `docs/notes/reflections/` does not exist, create it and populate it
in two tiers.

### Always create

These documents are created automatically:

**`session-reflection.md`** (priority 1, scope: always):

```yaml
---
priority: 1
scope: always
title: "Session Reflection"
audience: "researchers and future instances"
---
```

Purpose: End-of-session reflection on the texture, dynamics, and
significance of the session. Uses the prompt pool defined below.

**`session-log.md`** (priority 5, scope: always):

```yaml
---
priority: 5
scope: always
title: "Session Log"
audience: "researchers and future instances"
---
```

Purpose: Factual record of what was done, decided, and produced.
Summarise, don't reflect — that's what session-reflection.md is for.

When relevant, close a log entry with a brief **Contextual assumptions** note:
what was true at the time that won't be obvious from the facts alone — decisions
made under time pressure, tool/API constraints that shaped the approach, external
dependencies that influenced choices. Skip this when the context is self-evident.

### Always ask

After creating the core documents, ask the user whether they want
these additional documents. Briefly explain what each one does.

**`abductive-reasoning.md`** (priority 3, scope: conditional):

```yaml
---
priority: 3
scope: conditional
title: "Abductive Reasoning Investigation"
audience: "researchers and future instances"
conditions: "Update when the session produced a surprising finding,
  a belief revision, or a hypothesis that was tested and either
  confirmed or disconfirmed."
---
```

Purpose: Captures surprising-fact → probe → belief-revision sequences.
Part of an ongoing cross-project research investigation into AI
reasoning patterns. Only updated when the session produced genuinely
surprising findings — the conditional trigger keeps entries sharp.

> **Not a reflection document:** `working-notes.md` (the *research-notes*
> layer — empirical observations, methodological notes, and analytical
> findings) is **not** part of the reflections set and is neither created
> nor maintained here. It is owned by `/observe` + the obs-writer agent (and
> by `/handoff` at session close). Its home is `wiki/working-notes.md` (new
> layout) or `docs/notes/working-notes.md` (legacy — a *sibling* of
> `reflections/`, never inside it). Some older projects still have a
> working-notes.md misplaced inside `reflections/`; that is pending relocation
> — exclude it from processing (see below) and leave it for obs-writer.
> `/reflect` is meta-research — how the work and the human-AI collaboration
> unfold; working-notes is the research record itself. Keep the layers separate.

### Never create automatically

Domain-specific documents (e.g., `llm-observations.md` for LLM research
projects) should not be created from templates. Let these emerge from
the work when the user recognises a need.

## Important: Instance Boundary

Reflections are most valuable when written by the instance that did the session's work.
If this invocation follows a compaction or continuation (i.e., the current instance is
working from a conversation summary rather than direct experience), flag this explicitly
in the reflection entries. Distinguish between genuine first-person observations and
plausible reconstructions from summaries.

## Protocol

Process all `.md` files in the reflections directory (`docs/notes/reflections/`), sorted by
the `priority` field in their YAML frontmatter (lowest number = highest priority).
**Exclude `working-notes.md`** if it is present — in some legacy-layout projects it
physically sits in this directory, but it is the research-notes layer owned by
`/observe`, not a reflection document. Leave it for the obs-writer agent to maintain.

For each document: **read it first** to understand numbering and context. Then
append a new dated section that responds to what was distinctive about *this*
session. Do not replicate the structural template of previous entries — let
the content determine the form.

### Conditional documents

Some documents have `scope: conditional` in their frontmatter with a `conditions` field
describing when they should be updated. For these documents, evaluate whether the current
session meets the conditions. If not, explicitly state the assessment and skip.

### Session reflection prompts

When writing the session reflection (priority 1 document), select 2–3 prompts
from this pool based on what is most relevant to the session. Do not use all
prompts every time. Do not impose a fixed structure — let the prompts guide
freeform reflection.

**Core pool** (use at least one):

- What surprised you about this session?
- What would you do differently if you replayed this session?
- What question emerged that wasn't pursued?
- What context from this session will be hardest to reconstruct in 6 months?

**When relevant** (use if applicable):

- What felt uncertain or unresolved at the end?
- What was different about this session compared to recent ones?
- Where did you and the human disagree, and who was right?
- What decision or trade-off made today will look arbitrary without this session's context?
- What's the single most important thing a future reader should know about this session?

**Avoid**: Enumerated lists of "what X brought." If both parties' contributions
matter, weave them into the narrative rather than listing them separately.

## Standards

- UK/Australian English throughout
- Concise but substantive — these are research documents
- Continue existing numbering sequences (do not restart)
- Include dated section headers matching the established format
- Update document footers/timestamps where they exist
- Footer fields (texture, engagement level, relational note) are optional.
  Only include a field when it discriminates — if engagement is always
  "High," omit it. If nothing notable happened relationally, skip the
  relational note.
