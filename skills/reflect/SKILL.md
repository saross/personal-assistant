---
name: reflect
description: "End-of-session reflection protocol. Use when the user invokes /reflect or asks to reflect on the current session, do end-of-session reflections, or similar. Guides Claude through updating reflection documents in priority order, answering structured prompts, and maintaining research observation logs."
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
   the project root. If this directory does not exist, inform the user and offer
   to create the initial structure.
3. **Tag output**: When writing reflection entries, include the project name and
   session date in the entry header so entries are unambiguous even if read out
   of context.

## Important: Instance Boundary

Reflections are most valuable when written by the instance that did the session's work.
If this invocation follows a compaction or continuation (i.e., the current instance is
working from a conversation summary rather than direct experience), flag this explicitly
in the reflection entries. Distinguish between genuine first-person observations and
plausible reconstructions from summaries.

## Protocol

Process all `.md` files in the reflections directory (`docs/notes/reflections/`), sorted by
the `priority` field in their YAML frontmatter (lowest number = highest priority).

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

**When relevant** (use if applicable):

- What felt uncertain or unresolved at the end?
- What was different about this session compared to recent ones?
- Where did you and the human disagree, and who was right?
- What's the single most important thing a future instance should know?

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
