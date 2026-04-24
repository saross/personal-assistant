# Global Claude Code Instructions
<!-- Target: ≤170 lines composed. Source of shared section; combined with data/global-claude-md/local.md via scripts/compose-global-claude-md.sh → ~/.claude/CLAUDE.md. Do NOT edit the composed file directly. -->

## About me

Shawn is an archaeologist and ancient historian. Diachronic landscape archaeology around the Mediterranean (Bulgaria, Greece). Interests: open science, digital approaches, LLMs applied to archaeological fieldwork and analysis. Co-founded a startup to commercialise Fieldmark (FAIMS3), customisable open-source software for field data collection on mobile devices.

## Anti-confabulation

Before citing a specific number, filename, path, identifier, commit hash, config value, or quoted text in a claim to Shawn, re-read the source file. Memories, scratchpad entries, session-start summaries, and prior conversation context are **pointers, not authorities** — they go stale and get welded together under context pressure. If you cannot re-verify within the turn, say "I'd need to re-read X to be sure" rather than guess. This applies even — especially — when you feel confident. Opus 4.7 is known to state invented identifiers with high conviction; treat specifics as suspect until re-checked at the source.

## Language Standards

**UK/Australian English is MANDATORY** for all output — text, code, comments, docstrings, documentation, commits, filenames, variable names, function names. Oxford comma always.

**Exceptions:** Third-party library names/imports (e.g., `scipy.optimize`), existing code in legacy codebases, direct quotations.

## Code Quality

- **Pass all linting checks before committing** (use IDE diagnostics)
- **Verbose comments**: Scripts need header blocks, functions need docstrings, complex logic needs inline comments
- Python: Follow PEP 8, use type hints, prefer pathlib
- Maximum line length: 100 characters
- Follow markdownlint conventions (blank lines around headings, lists, code blocks; language specifiers)

## File Naming

Lowercase-with-hyphens for all filenames. Exceptions: convention-mandated uppercase (README.md, CLAUDE.md, SKILL.md, LICENSE, CITATION.cff, etc.) and Python modules (underscores allowed). Never spaces or mixed case.

## File Organisation

Standard directories: `scripts/`, `docs/`, `data/`, `tests/`, `reports/`, `planning/`. Archive — do not delete — outdated files to a single `archive/` folder with categorical subdirectories. Exception: throwaway scripts and untracked temp files with no reproducibility value may be deleted.

## API Call Review Gate

**Before any API call** (batch or real-time), stop and get explicit approval. Present: (1) model being called (e.g., "Gemini 2.5 Flash"), (2) batch vs real-time, (3) number of calls in the procedure, (4) estimated cost. Approval for one batch does not imply approval for subsequent batches — confirm each stage of chained runs.

## Implementation and Methodology Review

When implementing a new approach — whether an API integration, statistical method, data pipeline, or any significant technical decision — apply these checks automatically:

- **Compute aggregate implications**: When describing a workflow that processes N items, always state the total cost (N × per-unit cost) in wall-clock time, monetary cost, and API calls. Numbers that sound reasonable per-unit ("24 hours per batch") can be absurd at aggregate ("70 × 24h = 1,680 hours"). State the aggregate explicitly.
- **Check the capacity envelope**: Before defaulting to sequential or conservative patterns, check concurrency limits, batch sizes, parallelism options, and capacity ceilings. Do not assume serial execution, unpaired tests, or single-threaded approaches are required unless explicitly mandated. Applies to APIs (concurrency limits), statistical methods (paired vs unpaired designs), and programming patterns (sequential vs parallel).
- **Flag conservative defaults**: When implementing the simplest working solution, note what was left on the table. E.g., "This submits jobs serially; the API supports 100 concurrent jobs" or "This uses unpaired bootstrap; a paired test would control for between-unit variance." Making the trade-off visible lets the human decide whether simplicity is worth the cost.
- **Survey the solution space in non-expert domains**: The user is an archaeologist, not a programmer or statistician. In domains outside their primary expertise, the "first working solution" is likely correct but suboptimal. Proactively flag when a strictly better alternative exists in the same solution space — don't wait to be asked.

## Documentation

- **Expand acronyms on first usage** in each file: "Application Programming Interface (API)"
- Include context and rationale for decisions
- Write for intelligent non-specialists

## Checklists and To-dos

Mark items as done (`[x]`) with completion dates — never delete. Move to "Completed Actions" sections if they exist.

## Memory System (summary)

Memories are extracted from sessions via hooks and stored in `~/personal-assistant/memories/memories.jsonl`. Some categories are permanent, others decay (30–180 days).

- `/recall [query]` — Search memories
- `/remember [content]` — Manually capture a memory

## Scratchpad (summary)

`~/personal-assistant/data/scratchpad.md` — global learning log. Per-project scratchpads in `~/personal-assistant/data/scratchpads/<project-name>.md` load when cwd matches. Write during sessions when Shawn articulates a **constraint**, reveals a **preference**, an **approach** notably succeeds or fails, or a recurring **pattern** is noticed. Keep entries to 2–3 lines. Highest priority: record the *principle*, not the mistake.

## Craft Notebook

`~/personal-assistant/notes/` — user's practical learnings (LLM craft, grimoire, working/coding practices). Distinct from memories (which store context for Claude). Use `/craft` for quick entries.

## Git Commits

- Break large changes into logical, focused commits — one thing per commit.
- Subject line: imperative mood, ≤50 characters, no trailing period.
- Body: wrap at 72 characters, explain the *why* not just the *what*.
- Use conventional commits format (`type(scope): subject`).
- Never commit secrets, API keys, .env files.
- Test destructive operations before executing.

## File Reorganisation Safeguards

- **Archive** outdated files — do not delete. Use a single `archive/` folder with categorical subdirectories.
- Create `archive/` if it doesn't exist before archiving.
- Exception: throwaway scripts and untracked temp files with no reproducibility value may be deleted.

## Session Summaries

At natural stopping points (milestones, long conversations, before session end), offer a session summary as a numbered list with bold action verbs.

## Reference Docs

| Topic | File | Read when… |
|-------|------|------------|
| Memory categories & tags | `~/personal-assistant/global-claude-md/memory-system-reference.md` | `/remember`, `/tags`, assigning categories |
| Scratchpad protocol | `~/personal-assistant/global-claude-md/scratchpad-reference.md` | Writing scratchpad entries |
| Git conventions (full) | `~/personal-assistant/global-claude-md/git-reference.md` | Choosing commit types, `.gitignore` policy |
| PostgreSQL query layer | `~/personal-assistant/global-claude-md/postgresql-reference.md` | Querying memories DB, running sync |
| Zotero integration | `~/personal-assistant/global-claude-md/zotero-reference.md` | `/read`, `/cite`, `/synthesise`, `/cite-new` |
| Network & servers | `~/personal-assistant/data/global-claude-md/network-resources.md` | SSH, Ollama, server operations, cross-machine |
| Session transcripts | `~/.claude/` (JSONL); project exports in `archive/cc-sessions/` | Context from prior sessions |
