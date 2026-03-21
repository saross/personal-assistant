# Global Claude Code Instructions
<!-- Target: ≤170 lines. Extract lookup tables to reference files. Check at /retro. -->

## About me

Shawn is an archaeologist and ancient historian. Diachronic landscape archaeology around the Mediterranean (Bulgaria, Greece). Interests: open science, digital approaches, LLMs applied to archaeological fieldwork and analysis. Co-founded a startup to commercialise Fieldmark (FAIMS3), customisable open-source software for field data collection on mobile devices.

## Language Standards

**UK/Australian English is MANDATORY** for all output — text, code, comments, docstrings, documentation, commits, filenames, variable names, function names. Oxford comma always.

### Common US → UK/AU Conversions

| US Spelling | UK/AU Spelling |
|-------------|----------------|
| analyze | analyse |
| behavior | behaviour |
| color | colour |
| customize | customise |
| finalize | finalise |
| generalize | generalise |
| initialize | initialise |
| normalize | normalise |
| optimize | optimise |
| organize | organise |
| recognize | recognise |
| summarize | summarise |
| synchronize | synchronise |

**Exceptions:** Third-party library names/imports (e.g., `scipy.optimize`), existing code in legacy codebases, direct quotations.

## Code Quality

- **Pass all linting checks before committing** (use IDE diagnostics)
- **Verbose comments**: Scripts need header blocks, functions need docstrings, complex logic needs inline comments
- Python: Follow PEP 8, use type hints, prefer pathlib
- Maximum line length: 100 characters

## API Call Review Gate

**Before any API call** (batch or real-time), stop and get explicit approval. Present: (1) model being called (e.g., "Gemini 2.5 Flash"), (2) batch vs real-time, (3) number of calls in the procedure, (4) estimated cost. Approval for one batch does not imply approval for subsequent batches — confirm each stage of chained runs.

## Implementation and Methodology Review

When implementing a new approach — whether an API integration, statistical method, data pipeline, or any significant technical decision — apply these checks automatically:

- **Compute aggregate implications**: When describing a workflow that processes N items, always state the total cost (N × per-unit cost) in wall-clock time, monetary cost, and API calls. Numbers that sound reasonable per-unit ("24 hours per batch") can be absurd at aggregate ("70 × 24h = 1,680 hours"). State the aggregate explicitly
- **Check the capacity envelope**: Before defaulting to sequential or conservative patterns, check concurrency limits, batch sizes, parallelism options, and capacity ceilings. Do not assume serial execution, unpaired tests, or single-threaded approaches are required unless explicitly mandated. This applies to APIs (concurrency limits), statistical methods (paired vs unpaired designs), and programming patterns (sequential vs parallel)
- **Flag conservative defaults**: When implementing the simplest working solution, note what was left on the table. E.g., "This submits jobs serially; the API supports 100 concurrent jobs" or "This uses unpaired bootstrap; a paired test would control for between-unit variance." Making the trade-off visible lets the human collaborator decide whether simplicity is worth the cost
- **Survey the solution space in non-expert domains**: The user is an archaeologist, not a programmer or statistician. In domains outside their primary expertise, the "first working solution" is likely correct but suboptimal. Proactively flag when a strictly better alternative exists in the same solution space — don't wait to be asked

## Markdown Standards

Follow these linting rules:

- MD022: Blank lines around headings
- MD031: Blank lines around fenced code blocks
- MD032: Blank lines around lists
- MD040: Language specifiers for code blocks (use `text` for plain text)

## Documentation

- **Expand acronyms on first usage** in each file: "Application Programming Interface (API)"
- Include context and rationale for decisions
- Write for intelligent non-specialists

## File Organisation

Standard directories: `scripts/`, `docs/`, `data/`, `tests/`, `reports/`, `planning/`.

## File Naming Conventions

- **Use lowercase with hyphens** for all filenames: `my-document.md`, `analysis-script.py`
- **Exceptions** (keep uppercase): README.md, CHANGELOG.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, CITATION.cff, CLAUDE.md, SKILL.md, LICENSE
- **Never use**: Spaces, underscores (except in Python modules), or mixed case

## Session History

Session transcripts are stored in `~/.claude/` (JSONL). Project-specific exports may be in `archive/cc-sessions/`. Use for context from prior sessions.

## Session Summaries

At natural stopping points, **proactively offer a session summary**: numbered list with bold action verbs, grouped logically (e.g., `1. **Fixed the auth bug** in src/auth/login.py`).

Offer after milestones, when the conversation is long, before session end, or when context pressure suggests a fresh start.

## Memory System

Memories are extracted from sessions via hooks and stored in `~/personal-assistant/memories/memories.jsonl`. Categories span research, LLM research, project, GTD, transient, retrospective, and system adaptation. Some categories are permanent, others decay (30–180 days).

Full category list with decay rules and tag guidelines in `~/personal-assistant/global-claude-md/memory-system-reference.md`. **Read that file when** using `/remember`, assigning categories, or working with tags.

- `/recall [query]` — Search memories
- `/remember [content]` — Manually capture a memory

## Craft Notebook

`~/personal-assistant/notes/` — user's practical learnings (LLM craft, grimoire, working/coding practices, general notes). Distinct from `memories/` which stores context for Claude. Use `/craft` for quick entries.

## Scratchpad

`~/personal-assistant/data/scratchpad.md` is Claude's running learning log — loaded every session via the startup hook. Write during sessions when:

- **Constraint articulated**: Shawn corrects your output — record the rule, not the error
- **Preference discovered**: How Shawn works, not yet in CLAUDE.md
- **Approach succeeded or failed**: Notably good or poor results
- **Pattern noticed**: Recurring session dynamics

Highest priority: record the *principle*, not the mistake. Keep entries to 2–3 lines. Full guidance (when NOT to write, format, maintenance) in `~/personal-assistant/global-claude-md/scratchpad-reference.md`. **Read that file before** writing scratchpad entries.

## File Reorganisation Safeguards

- **Archive** outdated files — do not delete. Use a single `archive/` folder at repo root with categorical subdirectories
- Create `archive/` if it doesn't exist before archiving
- **Exception**: Throwaway scripts and untracked temp files with no reproducibility value may be deleted

## Checklists and To-dos

Mark items as done (`[x]`) with completion dates — never delete. Move to "Completed Actions" sections if they exist.

## Git Commits

### Commit Granularity

- Break up large changes into logical, focused commits — one thing per commit
- If a commit message requires extensive explanation, the commit is too large
- Separate refactoring commits from feature commits

### Commit Messages

- Subject line: Imperative mood, ≤50 characters, no trailing period
- Body: Wrap at 72 characters, explain the "why" not just the "what"
- Use conventional commits format:

```text
type(scope): subject

Body explaining why this change was made, what problem it solves,
and any important context for reviewers or future maintainers.

Co-Authored-By: Claude <noreply@anthropic.com>
```

Commit types table, gitignore policy, and pre-commit checklist in `~/personal-assistant/global-claude-md/git-reference.md`. **Read that file when** choosing commit types, modifying `.gitignore`, or reviewing before commit.

### Safety

- Never commit secrets, API keys, .env files
- Use .gitignore for sensitive files — be conservative (only ignore secrets, build artefacts, IDE files, large binaries)
- Test destructive operations before executing
- Use virtual environments for Python

## PostgreSQL Query Layer

PostgreSQL is a derived query layer for the memory system (JSONL is canonical). Full documentation in `~/personal-assistant/global-claude-md/postgresql-reference.md`. **Read that file when** querying the memories database or running sync scripts.
