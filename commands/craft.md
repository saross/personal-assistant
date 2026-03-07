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
```

## Arguments

- `[text]` — The observation to capture (required)
- Prefix with `grimoire:`, `llm:`, `coding:`, or `practices:` to force a
  specific notebook. If no prefix, classify automatically.

## Notebook Files

| Prefix | File | Content |
|--------|------|---------|
| `llm:` | `notes/llm-craft.md` | LLM interaction patterns, prompting techniques |
| `grimoire:` | `notes/grimoire.md` | Effective prompts with mechanism analysis |
| `practices:` | `notes/working-practices.md` | Time management, focus, productivity |
| `coding:` | `notes/coding-practices.md` | Tooling, debugging, dev environment |

## Behaviour

1. **Parse** the input for an explicit prefix. If present, use that notebook.
2. **If no prefix**, classify based on content:
   - Mentions prompts, prompting, LLM interaction, model behaviour → `llm-craft.md`
   - Contains a prompt to save (quoted or described) → `grimoire.md`
   - Mentions time, focus, avoidance, productivity, habits → `working-practices.md`
   - Mentions code, tools, debugging, git, testing → `coding-practices.md`
   - If genuinely ambiguous, ask which notebook (don't guess wrong).
3. **Read** the target notebook file from `~/personal-assistant/notes/`
4. **Append** a new entry at the end of the file:

```markdown
## YYYY-MM-DD: [Brief title derived from content]

[Content, lightly edited for clarity and self-containment. Preserve the user's
meaning exactly but ensure it makes sense without conversation context.]
```

For grimoire entries, use this format instead:

```markdown
## [Descriptive Name]

**Incantation:**

> [The prompt text]

**Effect:** [What it does, in one sentence]

**Mechanism:** [Why it works — what prompting principles it leverages]

**Source:** [Attribution and date]
```

5. **Confirm** the capture:

```text
Noted in [notebook name]:
  "[brief title]"
```

6. **Return to work.** No further commentary.

## Auto-Classification Examples

```text
/craft LLMs respond better to numbered constraints than prose paragraphs
→ notes/llm-craft.md

/craft grimoire: "List every assumption this code makes about its input" — forces exhaustive analysis
→ notes/grimoire.md

/craft I work better in 90-minute blocks with hard stops than open-ended sessions
→ notes/working-practices.md

/craft Always check whether a venv exists before creating one in a new project
→ notes/coding-practices.md
```

## Notes

- Entries should be self-contained — understandable without conversation context
- If the user provides a long observation, preserve it fully (this is a notebook, not tweets)
- Don't add entries the user didn't ask for — this is their notebook, not yours
- The grimoire format is richer because prompts need mechanism analysis to be reusable
- If the user just says `/craft` with no text, ask what they observed
