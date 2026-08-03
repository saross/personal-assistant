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

## Before you start — two non-negotiables

**1. Commit the code first.** Auditing agents run in the same working tree.
An agent that applies a mutation and restores with `git checkout` will destroy
uncommitted work, and that work is recoverable from nowhere. Commit (or use a
worktree) before delegating. If the code cannot be committed yet, do the audit
inline rather than delegating it.

**2. Never audit your own work in your own context.** If you wrote the code in
this session, you cannot review it here — you will re-derive the same
assumptions and confirm them. This is measured, not theoretical: same-context
self-checks reliably *false-confirm* (a guard reporting "match" against a value
that was wrong by two orders of magnitude), and code that passed its author's
entire test suite has shipped with a defect that made the feature unusable.
Delegate to fresh context, or state plainly in the report that the audit was
same-context and is therefore weak evidence.

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

### Delegate to TWO ORTHOGONAL LENSES, not N copies of one

Do not fan out one prompt across files. Run **two subagents with different
questions**, each in fresh context, both covering the whole change:

- **Lens A — implementation correctness.** Does the code do what it claims?
  Work through the categories below.
- **Lens B — test adequacy.** *Assume the implementation is wrong and ask
  whether these tests would catch it.* A suite that passes while the feature is
  broken is worse than no suite.

Orthogonality is the point. Two agents asked the same question return the same
answer, including the same mistake; two asked different questions find disjoint
defect classes. In practice Lens A finds the bug and Lens B finds *why it got
past review* — which is the finding that prevents the next one.

Give both lenses the same constraints:

- **READ-ONLY. No edits, no commits, and explicitly NO `git checkout`,
  `git stash`, or `git restore`** on any file. If a lens wants to know whether a
  mutation survives, it must reason from the assertions rather than applying it.
- Anchor every finding to `file:line` with the offending code quoted. Anything
  unconfirmed is labelled `SUSPECTED — needs X to confirm`, never asserted.
- Remove false positives on a second pass; a finding that misreads intent is
  worse than no finding.

Tell each lens what changed and *why*, not just which files. A lens that
understands the intent can tell you the intent was not achieved.

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

### 2b. Lens B — test adequacy

Not "are there tests?" but "would these tests fail if the feature were broken?"

**Mutation reasoning.** For each test, name a concrete single-line change to the
implementation that would make it wrong while leaving the test green. Be
specific — "the tests are weak" is useless; "changing `>=` to `>` on line N
leaves all seven green" is actionable. Reliable survivors worth checking:

- deleting the call site that *wires* a guard into the pipeline
- flipping a boundary operator
- narrowing an emptiness test (`not in (None, "")` → `is not None`)
- widening an exception clause to swallow everything
- returning a constant that satisfies the assertions
- removing a set difference or filter so a check fires on everything

**Is the wiring tested, or only the functions?** Unit tests of pure helpers can
all pass while the helper is never called, or is called after the thing it was
meant to protect. Look for at least one test that exercises the real entry point
end to end and asserts the *consequence* (the file was not written; the process
exited non-zero), not merely a returned value.

**Do fixtures match what the pipeline actually produces?** A hand-built fixture
can encode a shape the real code path cannot emit — the test then passes against
an object that never exists in production. This is a recurring root cause of
defects shipping green. Prefer building fixtures through the real constructor;
where a test hand-builds one, check it against a live artefact.

**Are negatives pinned?** A test asserting that something fires is half a test.
Without a case asserting it does *not* fire in the ordinary situation, a
mutation that makes it fire always will pass.

**Does the test exercise the path a user takes?** Tests that only pass an
injected `tmp_path`, mock, or override may never reach the default branch that
production uses — so a mutation scoped to that branch survives.

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
[issues that would cause crashes, data loss, or wrong results —
 INCLUDING "the feature could be broken with every test green"]

### Medium (should fix)
[issues that would cause problems in edge cases or violate contracts]

### Low (note for later)
[style, performance, missing coverage]

### Surviving mutations
[each: the one-line change, its location, and what it would let through]

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

### 6. Resolve, then re-audit if the fixes were substantial

Fix everything Medium and above, plus any Low that is load-bearing. Then, if the
fixes were more than cosmetic, **run the audit again on the fixes** — they are
new code written under time pressure by someone who has just been told they were
wrong, which is not a state associated with careful work. A second pass over a
first round of fixes routinely finds fresh defects.

When a finding is deliberately *not* fixed, record the decision and its reasoning
somewhere durable, along with what the code may and may not be claimed to do
as a result. An unresolved finding that lives only in a chat log will be rediscovered
at the worst moment, and the weaker claim it implies will be forgotten first.
