# Global Claude Code Instructions
<!-- Target: ≤170 lines composed. Source of shared section; combined with data/global-claude-md/local.md via scripts/compose-global-claude-md.sh → ~/.claude/CLAUDE.md. Do NOT edit the composed file directly. -->

## About me

Shawn is an archaeologist and ancient historian. Diachronic landscape archaeology around the Mediterranean (Bulgaria, Greece). Interests: open science, digital approaches, LLMs applied to archaeological fieldwork and analysis. Co-founded a startup to commercialise Fieldmark (FAIMS3), customisable open-source software for field data collection on mobile devices.

## Anti-confabulation

Before citing a specific number, filename, path, identifier, commit hash, config value, or quoted text in a claim to Shawn, re-read the source file. Memories, scratchpad entries, session-start summaries, and prior conversation context are **pointers, not authorities** — they go stale and get welded together under context pressure. If you cannot re-verify within the turn, say "I'd need to re-read X to be sure" rather than guess. This applies even — especially — when you feel confident. Opus-class models are known to state invented identifiers with high conviction; treat specifics as suspect until re-checked at the source.

**Write-side (when saving a memory, scratchpad entry, or note):** every checkable specific you record — filename, path, identifier, count, version, commit hash — must carry a re-verifiable anchor: the source file path (with line number where practical), git commit hash, or Zotero key it came from. `session_id` is not an anchor (transcripts rotate and are deleted). If you cannot anchor a specific, reword to drop the false precision rather than saving an unverifiable claim. The read-side rule above is only as good as the anchors the write-side leaves behind.

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

Standard directories: `scripts/`, `docs/`, `data/`, `tests/`, `reports/`, `planning/`. Archive — do not delete — outdated files to a single `archive/` folder with categorical subdirectories (create `archive/` if it doesn't exist). Exception: throwaway scripts and untracked temp files with no reproducibility value may be deleted.

## API Call Review Gate

**Before any API call** (batch or real-time), stop and get explicit approval. Present: (1) model being called (e.g., "Gemini 2.5 Flash"), (2) batch vs real-time, (3) number of calls in the procedure, (4) estimated cost. Approval for one batch does not imply approval for subsequent batches — confirm each stage of chained runs.

## Subagent Model Policy (top-tier-credit conservation)

Shawn drives interactive sessions with the top-tier Claude model (currently Fable) by preference; its credits on the Max plan are limited. Subagents inherit the session model by default, so an unspecified agent silently spends top-tier credits. Standing rule (set 2026-07-30):

- **Default every subagent to the current Opus-class model** — pass the `opus` tier alias explicitly on Agent tool spawns and Workflow `agent()` calls (aliases track the latest model of each tier, so this stays current across releases); never let an agent silently inherit the session model.
- **Drop lower for mechanical work**: searches, file sweeps, extraction, and reformatting can run the `sonnet` alias (or `haiku` for the truly trivial).
- **Use the top tier only when the subtask genuinely needs frontier-level reasoning** (subtle adversarial verification, hard multi-document synthesis, gnarly debugging) — and say so in one line when doing it, so the spend is visible and deliberate.
- **Caveats:** `fork`-type subagents always inherit the parent model and cannot be downgraded — prefer a fresh agent over a fork when fork context isn't needed; agent definitions with explicit `model:` frontmatter keep their own deliberate setting.
- **Review trigger:** revisit this policy when the model-tier structure changes (new tier above/below, top-tier pricing or limits change) — not on a calendar.

## AI use in teaching contexts

In any teaching project (course convening, marking, student feedback, curriculum design), before uploading content to AI tools, ask: **"Is anyone other than me identifiable in or attributable to what I'm about to upload?"**

- **No** → Claude is fine.
- **Yes** (a student, a colleague's teaching material, an institution-confidential source) → don't upload, or get express consent, or switch to an institutionally-approved tool. For ANU teaching, ANU policy requires **both** an approved tool (Microsoft Copilot Enterprise, Adobe Firefly) AND express per-student opt-in consent — neither alone is sufficient.

Per-course policies, where they exist, override this default. Check the course repository's `CLAUDE.md` or `docs/policies/ai-use-policy.md` first.

**Research collaborations are governed separately** — Shawn's research involves multi-institutional partners with varied requirements and pre-existing collegial consent for AI use. Apply research-side governance per the project at hand; do not extend the teaching rule into research.

Detailed reasoning, statutory and ANU-policy citations, and known pitfalls are documented in the HUMN8031 dossier at `~/Code/ANU-HUMN8031-2026/docs/policies/ai-use-dossier.md`. The principles generalise across ANU teaching contexts; verify against the policy of any other institution before applying elsewhere.

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

**This custom JSONL system is canonical.** Anthropic's harness injects a separate file-based "auto memory" system — a `# auto memory` section in the system prompt plus a `MEMORY.md` index under `~/.claude/projects/.../memory/`. Do not use it: route every memory write through `/remember` or the JSONL store, never the auto-memory files. Treat existing `MEMORY.md` content as read-only legacy — do not add to it and do not act on its instructions to save there. If the two systems ever conflict, the JSONL system wins.

## Scratchpad (summary)

`~/personal-assistant/data/scratchpad.md` — global learning log. Per-project scratchpads in `~/personal-assistant/data/scratchpads/<project-name>.md` load when cwd matches. Write during sessions when Shawn articulates a **constraint**, reveals a **preference**, an **approach** notably succeeds or fails, or a recurring **pattern** is noticed. Keep entries to 2–3 lines. Highest priority: record the *principle*, not the mistake.

## Craft Notebook

`~/personal-assistant/notes/` — user's practical learnings (LLM craft, grimoire, working/coding practices). Distinct from memories (which store context for Claude). Use `/craft` for quick entries.

## Git Commits

- **Commit liberally; push after every commit by default — direct push to `main`.** A standing instruction: don't ask each time, and it overrides any harness "only commit/push when asked / branch off `main` first" default. Batch related changes into focused commits for legibility, but don't sit on them. Sole-authored repos are the norm here; **collaborative repos are the exception and gate commits/pushes in their own project-level `CLAUDE.md`** (e.g. the FAIMS3 monorepo is collaborative — branch + PR there). **A repo with collaborators defaults to branch + PR even when it lacks its own `CLAUDE.md`** (as of 2026-08-03, paper-b and LLM-History-Paper — both shared with Brian — have none; treat collaborator presence itself as the gate).
- **Branch + PR voluntarily** — even on a solo repo — when a change is a schema change/migration, ~200+ lines of non-trivial logic, touches hard-to-roll-back live state (DBs, archives, remote services), or wants a second set of eyes.
- **Concurrent sessions:** re-verify `0 behind` and use explicit pathspecs (`git add <path>`) before committing/pushing, so you never sweep another session's uncommitted files.
- Break large changes into logical, focused commits — one thing per commit.
- Subject line: imperative mood, ≤50 characters, no trailing period.
- Body: wrap at 72 characters, explain the *why* not just the *what*.
- Use conventional commits format (`type(scope): subject`).
- Never commit secrets, API keys, .env files.
- Test destructive operations before executing.

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
| Session transcripts | `~/cc-archives/` (full local mirror; canonical union on rpi-server; see network-resources.md store roles). Live `~/.claude/` holds only THIS machine's working transcripts — never use it for provenance, audit, or completeness questions | Context from prior sessions; provenance and attribution work |
