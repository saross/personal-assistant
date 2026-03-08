# /craft — Quick Craft Notebook Entry

Capture a practical learning to the craft notebook. Auto-classifies into the
right file based on content.

## Usage

```text
/craft [text]
/craft grimoire: [prompt text] — [what it does]
/craft llm: [observation]
/craft coding: [observation]
/craft practices: [observation]
/craft general: [any note, observation, or reference material]
```

## Arguments

- `[text]` — The observation to capture (required)
- Prefix with `grimoire:`, `llm:`, `coding:`, `practices:`, or `general:` to
  force a specific notebook. If no prefix, classify automatically.

## Notebook Files

| Prefix | Location | Content |
|--------|----------|---------|
| `llm:` | `notes/llm-craft.md` | LLM interaction patterns, prompting techniques |
| `grimoire:` | `notes/grimoire/` | Effective prompts with mechanism analysis (one file per prompt) |
| `practices:` | `notes/working-practices.md` | Time management, focus, productivity |
| `coding:` | `notes/coding-practices.md` | Tooling, debugging, dev environment |
| `general:` | `notes/general/` | General notes, reference material, observations (one file per note) |

## Behaviour

1. **Parse** the input for an explicit prefix. If present, use that notebook.
2. **If no prefix**, classify based on content:
   - Mentions prompts, prompting, LLM interaction, model behaviour → `llm-craft.md`
   - Contains a prompt to save (quoted or described) → `grimoire/`
   - Mentions time, focus, avoidance, productivity, habits → `working-practices.md`
   - Mentions code, tools, debugging, git, testing → `coding-practices.md`
   - Anything else → `general/`
   - If genuinely ambiguous between the four specific notebooks, ask. But if
     nothing fits, use `general/` without asking — it's the default.
3. **Route** to the appropriate handler:

#### Single-file notebooks (llm, practices, coding)

**Read** the target file from `~/personal-assistant/notes/`, then **append**:

```markdown

## YYYY-MM-DD: [Brief title derived from content]

[Content, lightly edited for clarity and self-containment. Preserve the user's
meaning exactly but ensure it makes sense without conversation context.]
```

#### Directory notebooks (grimoire, general)

**Create a new file** in the appropriate directory under
`~/personal-assistant/notes/`.

For **general** entries, use this format:

- **Filename**: `YYYY-MM-DD-slug.md` (lowercase, hyphenated slug from title)
- **Content**:

```markdown
---
title: [Brief descriptive title]
tags: [tag1, tag2, tag3]
source: [where this came from — conversation, web, standard-notes, etc.]
created: YYYY-MM-DD
---

[Content, lightly edited for clarity and self-containment. Preserve the user's
meaning exactly but ensure it makes sense without conversation context.]
```

Choose 2–4 tags from existing usage where possible. Tags should be lowercase
with hyphens. Check existing files in `notes/general/` for tag consistency.

For **grimoire** entries, follow the existing format in `notes/grimoire/`
(see `notes/grimoire/README.md` for the template).

4. **Confirm** the capture:

```text
Noted in [notebook name]:
  "[brief title]"
```

5. **Return to work.** No further commentary.

## Auto-Classification Examples

```text
/craft LLMs respond better to numbered constraints than prose paragraphs
→ notes/llm-craft.md

/craft grimoire: "List every assumption this code makes about its input" — forces exhaustive analysis
→ notes/grimoire/assumption-audit.md

/craft I work better in 90-minute blocks with hard stops than open-ended sessions
→ notes/working-practices.md

/craft Always check whether a venv exists before creating one in a new project
→ notes/coding-practices.md

/craft MCP servers expose tools via JSON-RPC over stdio — simpler than REST for local integrations
→ notes/general/2026-03-08-mcp-server-architecture.md

/craft general: Flinders wants HECVAT assessment — need to prepare security documentation
→ notes/general/2026-03-08-flinders-hecvat-prep.md
```

## Notes

- Entries should be self-contained — understandable without conversation context
- If the user provides a long observation, preserve it fully (this is a notebook, not tweets)
- Don't add entries the user didn't ask for — this is their notebook, not yours
- The grimoire format is richer because prompts need mechanism analysis to be reusable
- If the user just says `/craft` with no text, ask what they observed
