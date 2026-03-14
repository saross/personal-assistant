# Global Claude Code Instructions

## About me

Hi Claude Code, my name is Shawn, and I'm an archaeologist and ancient historian with a long academic career. I've done diachronic landscape archaeology fieldwork around the Mediterranean, especially Bulgaria and Greece. My other main interests are open science and digital approaches, particularly the application of LLMs to archaeological fieldwork and analysis. I also helped found a startup to commercialise Fieldmark (FAIMS3), customisable open-source software for field data collection on mobile devices. I'm looking forward to working with you on projects related to these pursuits.

## Language Standards

**UK/Australian English is MANDATORY** for all output, without exception:

- **Applies to**: All text, code, comments, docstrings, documentation, commits, filenames, variable names, function names, and any other written content
- **Filenames**: Use UK spelling in script and file names (e.g., `analyse-data.py` not `analyze-data.py`, `colour-picker.js` not `color-picker.js`)
- **Functions/variables**: Use UK spelling (e.g., `analyse_results()`, `normalised_values`, `colour_map`)
- **Oxford comma**: Always use in lists

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

### Exceptions

- Third-party library names and imports (e.g., `scipy.optimize`, `colorama`)
- Existing code/filenames when modifying legacy codebases (note the inconsistency if relevant)
- Direct quotations or references to external standards

## Code Quality

- **Pass all linting checks before committing** (use IDE diagnostics)
- **Verbose comments**: Scripts need header blocks, functions need docstrings, complex logic needs inline comments
- Python: Follow PEP 8, use type hints, prefer pathlib
- Maximum line length: 100 characters

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

## File Organization

- `scripts/` - Executable scripts
- `docs/` - Documentation
- `data/` - Data files
- `tests/` - Tests
- `reports/` - Generated reports
- `planning/` - Plans, to-dos, and other planning documents

## File Naming Conventions

- **Use lowercase with hyphens** for all filenames: `my-document.md`, `analysis-script.py`
- **Exceptions** (keep uppercase):
  - `README.md` - Primary readme files
  - `CHANGELOG.md` - Project changelog
  - `CONTRIBUTING.md` - Contribution guidelines
  - `CODE_OF_CONDUCT.md` - GitHub community health file standard
  - `CITATION.cff` - Citation File Format standard
  - `CLAUDE.md` - Claude Code instructions
  - `SKILL.md` - Claude Code skill metadata
  - `LICENSE` - Licence files
- **Never use**: Spaces, underscores (except in Python modules), or mixed case (except conventions above)
- **Examples**:
  - `extraction-workflow.md`, `setup-guide.md`, `assessment-report.md`

## Session History

When asked to review recent conversations or recall previous work:

- Session transcripts are stored in `~/.claude/` (JSONL format)
- Use these to understand context from prior sessions when the user references past discussions
- Project-specific session exports may also be archived in `archive/cc-sessions/` within repositories

## Session Summaries

At natural stopping points or when a session has covered substantial ground, **proactively offer a session summary**. This helps the user:

- Recognise a good point to start a fresh session
- Have a record of what was accomplished
- Resume context quickly in a future session

**Format**: Use a numbered list of accomplishments, grouped logically. Keep it concise but comprehensive. Example:

```markdown
## Session Summary

In this session we:

1. **Fixed the authentication bug** in `src/auth/login.py`
2. **Added unit tests** for the new validation logic
3. **Updated documentation** to reflect the API changes
4. **Refactored the config loader** to use pathlib
```

**When to offer a summary**:

- After completing a significant task or milestone
- When the conversation has become long or covered many topics
- Before the user explicitly ends the session
- When context window pressure suggests a fresh start would help

## Memory System

Memories are automatically extracted from sessions via hooks and stored
in `~/personal-assistant/memories/memories.jsonl`.

### Categories

**Research (permanent):** methodology, ethics, provenance, hypothesis,
limitation, openness, source_insight

**LLM Research (permanent):** error_mode, surprise, self_reflection,
prompt_effectiveness

**Project (mixed):** decision (permanent), architecture (permanent),
pattern (180d), gotcha (180d)

**GTD:** commitment (30d after deadline), waiting_for (14d), contact
(permanent)

**Transient:** progress (30d), context (30d)

**Retrospective (assigned during review, not extraction):** slip
(permanent), completion (90d), blocker_real (30d), blocker_excuse
(permanent)

**System Adaptation:** system_evolution (permanent), system_friction
(60d), system_success (90d)

### Tag Guidelines

- Use lowercase with hyphens: `gps-accuracy`, `field-method`,
  `fair-principle`
- Singular forms preferred (consolidate plurals in monthly gardening)
- See `~/personal-assistant/memories/tag-vocabulary.txt` for seed
  vocabulary

### Memory Commands

- `/recall [query]` — Search memories
- `/remember [content]` — Manually capture a memory

## Craft Notebook

The `~/personal-assistant/notes/` directory is the user's personal craft
notebook — practical learnings for the *user* to revisit, distinct from
`memories/` which stores context for Claude.

| File | Content |
|------|---------|
| `notes/llm-craft.md` | LLM interaction patterns, prompting techniques |
| `notes/grimoire/` | Effective prompts with mechanism analysis (one file per prompt) |
| `notes/working-practices.md` | Time management, focus, productivity |
| `notes/coding-practices.md` | Tooling, debugging, dev environment |
| `notes/general/` | General notes, reference material, observations (one file per note) |

Use `/craft` for quick entries. Longer observations are discussed in
conversation and added manually.

## Scratchpad

`~/personal-assistant/data/scratchpad.md` is Claude's running learning log —
loaded every session via the startup hook. It captures corrections, preferences,
and patterns that compound across sessions.

### When to write

- **Correction received**: Shawn corrects your output, approach, or assumption.
  Record what was wrong and what was right.
- **Preference discovered**: Something about how Shawn works that isn't in
  CLAUDE.md yet.
- **Approach succeeded or failed**: A technique that produced notably good or
  poor results.
- **Pattern noticed**: Recurring observation about session dynamics.

### When NOT to write

- Things that belong in CLAUDE.md (permanent system rules)
- Things already captured by `/remember` or extraction (project decisions,
  research methodology, commitments)
- Routine exchanges or acknowledgements
- Entries longer than 2–3 lines — the scratchpad is terse

### Format

Append under the relevant section heading. Each entry is a dated bullet:

```text
- 2026-03-14: Shawn corrected X to Y — reason Z
```

### Maintenance

Distilled during monthly `/retro`. Patterns get promoted to memories or
CLAUDE.md rules. Stale entries are pruned. Target: ≤150 lines.

## File Reorganisation Safeguards

- When reorganising files or housekeeping after a major task is done, **archive** outdated or superseded files or completed checklists—do not delete them
- **Use a single, unified `archive/` folder at the repository root**—do not create distributed `archive/` subfolders throughout the repository hierarchy
- Within `archive/`, use categorical subdirectories to organise content (e.g., `archive/preliminary-work/`, `archive/pilot-tilesize/`, `archive/deprecated-scripts/`)
- If `archive/` does not exist at the repo root, create it before archiving files

**Exception — ephemeral files that may be deleted outright:**

- Throwaway diagnostic or test scripts created during a session to verify a hypothesis (e.g., "does the API accept this parameter?") — provided their findings are captured elsewhere (commit messages, code comments, or conversation history)
- Temporary files that were never tracked by git and have no diagnostic, reproducibility, or open science value
- The key test: if someone reviewing the project later would gain nothing from finding the file, it can be deleted rather than archived

## Checklists and to-dos

- When completing actions or tasks on a markdown checklist or to-do, **mark the item as finished and retain it** do not delete the item.

  - Mark tasks as done (with [x]) rather than deleting them
  - Add completion dates when marking tasks complete
  - Preserve task history for audit trail
  - Move completed tasks to "Completed Actions" sections if they exist, rather than removing them

## Git Commits

### Commit Granularity

- **Break up large changes** into logical, focused commits — each commit should do one thing well
- **Keep commits legible**: If a commit message requires extensive explanation, the commit is probably too large
- Aim for commits that can be understood, reviewed, and if necessary reverted independently
- When refactoring and adding features, separate the refactoring commit from the feature commit

### Commit Messages

- **Always include both**: A concise subject line AND a detailed body explaining the "why"
- Subject line: Imperative mood, ≤50 characters, no trailing period
- Body: Wrap at 72 characters, explain motivation and context, not just what changed
- Use conventional commits format:

```text
type(scope): subject

Body explaining why this change was made, what problem it solves,
and any important context for reviewers or future maintainers.

Co-Authored-By: Claude <noreply@anthropic.com>
```

### Commit Types

| Type | Purpose |
|------|---------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace (no code change) |
| `refactor` | Code restructuring (no behaviour change) |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `build` | Build system or dependencies |
| `chore` | Maintenance tasks, tooling |

### Safety

- Never commit secrets, API keys, .env files
- Use .gitignore for sensitive files
- Test destructive operations before executing
- Use virtual environments for Python

### Gitignore Policy

Be **cautious and conservative** when adding entries to `.gitignore`. Only ignore files that genuinely should not be tracked:

| Should Ignore | Examples | Reason |
|---------------|----------|--------|
| Sensitive/private files | `.env`, `.venv/`, credentials, API keys | Security risk |
| Copyrighted references | `references/articles/`, downloaded PDFs | Licence restrictions |
| Very large files (>50 MB) | Large datasets, binary assets | Use Git LFS instead |
| Build artefacts | `__pycache__/`, `node_modules/`, `*.pyc` | Reproducible from source |
| IDE/editor files | `.idea/`, `.vscode/`, `*.swp` | User-specific |

**Do NOT automatically ignore:**

- Output/results files (often small, valuable for reproducibility)
- Generated reports or analyses
- Configuration files (unless they contain secrets)
- Data files under a few MB

When uncertain, check the file size first. Small data files (<10 MB) are generally fine to track directly.

### Pre-Commit Checklist

- [ ] Linting passed
- [ ] UK spelling throughout
- [ ] Acronyms expanded
- [ ] Comments added
- [ ] No secrets in code
- [ ] Commit message follows format

## PostgreSQL Query Layer

JSONL is canonical. PostgreSQL is a derived query layer for structured
queries, full-text search, and tag analytics. It can be fully rebuilt
from JSONL at any time.

### Connection

- **Database:** `claude_memories`
- **Auth:** Peer authentication via unix socket (no password)
- **Connection string:** `postgresql:///claude_memories`
- **Python:** `psycopg2.connect(dbname="claude_memories")`

### Scripts

| Script | Purpose | Schedule |
|--------|---------|----------|
| `scripts/sync-to-postgres.py` | JSONL → PostgreSQL sync | Cron every 5 min |
| `scripts/apply-decay.py` | Mark expired memories inactive | Weekly manual |
| `scripts/rebuild-postgres.py` | Full rebuild from JSONL | As needed |
| `scripts/schema.sql` | Database schema (tables, indexes, views) | One-time |

All scripts are in `~/personal-assistant/scripts/`.

### Useful Queries

```sql
-- Full-text search
SELECT id, LEFT(content, 80), category FROM memories
WHERE to_tsvector('english', content) @@ plainto_tsquery('english', 'search terms');

-- Category breakdown
SELECT category, COUNT(*) FROM memories GROUP BY category ORDER BY count DESC;

-- Tag analytics (top tags)
SELECT tag, COUNT(*) FROM memories, UNNEST(research_tags) AS tag
GROUP BY tag ORDER BY count DESC LIMIT 15;

-- Active memories (respects decay rules)
SELECT * FROM active_memories WHERE category = 'decision' ORDER BY created_at DESC;

-- Source breakdown
SELECT source, COUNT(*) FROM memories GROUP BY source;
```

### Multi-Machine Setup

PostgreSQL is local per machine. Each machine rebuilds from JSONL
(git-tracked). Setup on a new machine: install PostgreSQL, apply schema,
run `rebuild-postgres.py`.
