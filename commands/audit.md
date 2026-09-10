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

### 2a-note. Running the suite during an audit

Two runs, because they cover different halves of the hermeticity guard.

**1. A clean copy — proves the suite does not write to the source trees.**

```bash
D=$(mktemp -d) && git archive --format=tar HEAD | tar -x -C "$D"
H=$(mktemp -d)
cd "$D" && env -i PATH=/usr/bin:/bin HOME="$H" LANG=C.UTF-8 \
  PA_HERMETICITY_STRICT=1 \
  ~/personal-assistant/venv/bin/python3 -m pytest -q --basetemp="$H/bt"
```

The interpreter comes from the **live venv**: `venv/` is gitignored, so an
archive export has no `venv/bin/python3` in it. Note also that the export has
no `data/` submodule, so `memories/` and `logs/` are dangling symlinks and the
**store half of the guard is inert there** — the run says so at the end, under
a `hermeticity` banner. What this run does prove is the source-tree half:
nothing the suite does touches `wiki/`, `scripts/`, `commands/`, `hooks/`,
`tests/`, `global-claude-md/`, `global-agent-guidance/`, or `tasks/`.

`--basetemp` inside the pinned HOME matters when other agents are running
suites: pytest's `/tmp/pytest-of-<user>` numbered directories are shared, and
concurrent runs collide there.

**2. The live checkout (or a worktree with the submodule populated) — proves
the suite does not write to the memory store.**

```bash
cd ~/personal-assistant && PA_HERMETICITY_STRICT=1 venv/bin/python3 -m pytest -q
```

Run this only when **no other session is editing the repository**: strict mode
makes a concurrent session's wiki edit fatal, which is a false failure. Without
`PA_HERMETICITY_STRICT` the source-tree half is advisory — a warning naming the
paths, printed through the terminal reporter so it survives output capture —
while the store half stays strict either way, with one allowance described
below.

**The append allowance, and what catches what it misses.** An append to the
store is verified as an append — the bytes before it must still hash to what
they hashed at session start, and for `memories.jsonl` and the vocabulary the
appended text must be the shape that writer produces — and is then TOLERATED,
including under `PA_HERMETICITY_STRICT=1`. Its path and byte count are printed
under the `hermeticity` banner.

That allowance cannot distinguish a test's well-formed append from the
extraction hook's: after the fact they are the same file, the same operation,
and the same result. So a second, independent guard runs alongside it. A
`sys.addaudithook` installed at session start watches this interpreter for a
write-mode `open` of a canonical store path. The extraction hook runs in
another PROCESS, so its appends are invisible to it, while a test that forgot
to patch its path opens the file here and is named — with its node id — in
advisory mode, and fails the run under STRICT.

What that leaves: the audit hook under-detects, never over-detects. A write
from a subprocess the test spawned, or from C code that bypasses Python's
`open`, is missed. It cannot produce a false failure in a live checkout,
which is what makes it safe to leave armed where other sessions are working.

Measured cost: **+2.5 s on a full run, about +1.6 %**, from paired runs — and
about **+0.5 µs per `open`** (0.588 µs measured over 40 000 opens on this
machine; the re-auditor measured 0.45 µs). An earlier note here claimed "none
detectable"; that came from two unpaired runs on a machine running other
suites, where the difference was buried in noise. The cost is small, but it is
real and it is proportional to how many files the suite opens.

What the snapshot half still catches on its own: a rewrite, a shrink, a
deletion, appended text that is not a well-formed record or a bare tag, and a
file created where none was. That last one has exceptions in advisory mode,
all under `logs/` and all reported: a `*.lock` file, a log rotation (including
a compressed one), a new `.log`/`.json`/`.jsonl`, and a new subdirectory.
Under `PA_HERMETICITY_STRICT` none of those is excused. Note what the shape
check does not say: a blank or whitespace-only appended line passes it, and so
does an unterminated tail that opens a JSON object (reported as an append in
progress in advisory mode, fatal under STRICT).

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
