# /audit — Code Audit

Line-by-line debug audit using anti-satisficing techniques. Finds semantic
bugs, logic errors, data format assumptions, edge cases, and cross-module
inconsistencies that standard review misses.

Based on Pliny the Prompter's incantation (see `notes/grimoire/pliny-debug-audit.md`),
extended with structured output, category guidance, and cross-file analysis.

## Usage

```text
/audit                          # audit files changed since last commit
/audit [file1] [file2] ...     # audit specific files
/audit --scope git-diff         # audit staged + unstaged changes
/audit --scope project          # audit all source files in project
```

## Arguments

- `$ARGUMENTS` — File paths to audit, or `--scope` flag.
  If empty, defaults to files changed since last commit.

## Instructions

### 1. Determine scope

Parse `$ARGUMENTS`:

- **No arguments**: Run `git diff --name-only HEAD` to find changed files. If no
  changes, report "No changed files to audit" and stop.
- **`--scope git-diff`**: Run `git diff --name-only` (staged + unstaged).
- **`--scope project`**: Find all source files (`.py`, `.js`, `.ts`, `.sh`, etc.)
  under the project root, excluding `node_modules/`, `.venv/`, `__pycache__/`,
  `archive/`, and other generated directories.
- **Explicit file paths**: Use the listed files.

Filter to source code files only — skip binary files, images, data files,
lock files, and generated output.

Report the file list before proceeding: "Auditing N files: [list]"

### 2. Audit each file

For each file, perform a FULL, COMPREHENSIVE, GRANULAR code audit line by line.
Presuppose that bugs exist — your job is to find them, not to confirm the code
works.

**Use subagents** to audit files in parallel when there are 2+ files. Each
subagent receives the full audit prompt below. Collect results and present a
consolidated report.

For each file, check every line against these categories:

#### Logic errors

- Off-by-one errors, boundary conditions
- Incorrect boolean logic (and/or confusion, negation errors)
- Wrong comparison operators (`<` vs `<=`, `==` vs `is`)
- Short-circuit evaluation bugs (`x or default` when x could be 0 or "")
- Missing `return` statements, unreachable code

#### Data format assumptions

- Assuming a key exists in a dict without `.get()` or guard
- Assuming a list is non-empty before indexing
- Assuming a string format (JSON, ISO date, etc.) without validation
- Type confusion (str vs Path, int vs float, None vs empty)

#### Edge cases

- Empty inputs, None values, missing keys
- Filesystem paths: symlinks, permissions, non-existent parents
- Unicode, encoding issues
- Concurrent access, race conditions

#### Cross-module consistency

- Function signatures matching how callers invoke them
- Return value contracts (does the caller handle all return types?)
- Shared data structures mutated in unexpected places
- Import cycles, circular dependencies

#### Security

- Command injection, path traversal
- Secrets in code, logs, or error messages
- Unsafe deserialisation

#### Project conventions

- UK/Australian English in all text (comments, docstrings, strings, variable
  names, filenames) — see CLAUDE.md for the conversion table
- Code style compliance (PEP 8 for Python, etc.)

### 3. Cross-file analysis

After individual file audits, perform a cross-file consistency check:

- Do function signatures match their call sites across files?
- Are shared data structures (dicts, return values) used consistently?
- Are error handling patterns consistent (`.get()` vs direct access)?
- Do file-level conventions (naming, imports) align?

### 4. Report findings

Present a consolidated report with this structure:

```text
## Audit Report — [N] files, [date]

### Critical (must fix)
[issues that would cause crashes, data loss, or wrong results]

### Medium (should fix)
[issues that would cause problems in edge cases or violate contracts]

### Low (note for later)
[style, performance, missing coverage]

### Cross-file issues
[consistency problems across modules]

### No issues found
[explicitly list categories checked where nothing was found]
```

For each issue, include:

- **File:line** — exact location
- **Category** — which check category found it
- **Description** — what is wrong, in one sentence
- **Impact** — what would go wrong in practice

### 5. Loop

Review your own findings. For each finding, verify it is real — not a
false positive caused by misunderstanding the code's intent. Remove any
false positives.

Then re-read the files looking specifically for anything you missed in
the first pass. The goal: a sceptical developer who believes prompting
cannot find real bugs would be proven wrong by this report.
