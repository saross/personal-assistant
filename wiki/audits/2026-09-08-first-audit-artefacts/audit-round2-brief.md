# Audit round two — shared brief for fix agents

You are fixing findings from the first repository audit of
`~/personal-assistant`. The durable record, with your finding IDs, is
`wiki/audits/2026-09-08-first-audit.md` in your worktree — read it first.
The full lens reports (quoted code, rationale, surviving mutations) are in
`/tmp/claude-1000/-home-shawn-personal-assistant/ec6964d7-c3f0-4c37-b9d0-0251a15b1e19/scratchpad/lens-reports/<agent-id>.md`;
your prompt names which. Line numbers in the lens reports were taken at
commit 1a546ab; verify against the current file before editing.

## Where to work

- Your worktree is named in your prompt. It is a linked git worktree of
  `~/personal-assistant` on its own branch, at commit 06225a0. `data/` is an
  UNINITIALISED submodule holding empty stub directories, so the root
  symlinks (`memories`, `logs`, `tasks`, ...) resolve to empty dirs. Never run
  `git submodule update` there.
- NEVER edit files under `~/personal-assistant` itself (the main checkout,
  where another session is working) or under any other worktree.
- Run the suite from your worktree with
  `~/personal-assistant/venv/bin/python3 -m pytest -q --no-header -p no:cacheprovider`
  (1263 passed at the branch point). Read the last line AND the exit code;
  a `| tail -1` pipe masks failure.
- Sibling agents run the same suite concurrently in other worktrees. If a
  test collides on a fixed path outside the worktree (under /tmp or $HOME),
  report it; do not weaken the test.

## Hard safety constraints

- Never execute `daily-sync.sh`, `daily-sync-trigger.sh`, `sync-symlinks.sh`,
  `compose-global-claude-md.sh`, `push-archives-to-r2.sh`, `commit-data.sh`,
  `setup.sh`, `archive-memories.py`, `monthly-archive.py`, any
  `*postgres*.py`, `backfill-embeddings.py`, `index-session-content.py`,
  `check-memory-drift.py`, `embed.py`, or any hook against real data or live
  state. Tests exercise them ONLY with `HOME` pinned to a pytest tmp dir,
  throwaway git repositories, mocked `psycopg2`/`urllib`, and no network.
- No Postgres connections, no Ollama or embedding calls, no HTTP, no ssh,
  no rsync, no R2, no API calls of any kind.
- Write only inside your worktree and pytest tmp dirs. Never touch
  `~/.claude`, `~/agent-mail`, `~/gpt-hub`, `~/personal-assistant/data`,
  `~/cc-archives`, any `AGENTS.md`, `.codex/`, or `.env` (a deny rule blocks
  `.env`; do not route around it — tests use tmp env files only).
- No `rm -rf`; use `tempfile` for cleanup. No `git checkout/stash/restore/
  reset` anywhere except on files you changed in your own worktree.
- Do not push. Commit on your branch with explicit pathspecs
  (`git add <paths>` then `git commit -- <paths>`), one focused commit per
  logical change, conventional-commit subject <= 50 chars, body wrapped at
  72 explaining WHY, and end every message with exactly these two lines.
  Before writing the message, run `git diff --cached --stat` and describe
  what is actually staged: three times in this series a commit's message
  described less than it contained (added 2026-09-09 after round 3c-8).
- Wait on a long-running job with ONE background waiter and let its
  completion notification arrive. Never re-issue a polling loop each time
  you check: one agent accumulated 48 sleeping `until … sleep` shells
  across four rounds and the machine ran to 1.2 GB free of 30 GB before
  the system reclaimed them (added 2026-09-11 after round 4d-8).

      Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
      Claude-Session: https://claude.ai/code/session_01EskLWHYW5b4jmqL5yWgNiS

## Code standards

- UK/Australian English everywhere (comments, docstrings, identifiers,
  commit messages); Oxford comma.
- Python: PEP 8, type hints, pathlib, max 100 columns, docstrings on every
  function, header block on every script, inline comments on non-obvious
  logic. Shell: keep the file's existing conventions (`set -euo pipefail`,
  `log` helper, quoting style).
- Every fix gets a test that FAILS on the old code; in the commit body name
  the single-line mutation the test kills. Wiring tests assert consequences
  (the file was not written, the process exited non-zero, the commit
  contains only these paths), not merely returned values. Build fixtures
  through the real code path where one exists.
- Never resolve a finding by weakening a test, widening an `except`, or
  deleting a guard.
- Markdown you touch: markdownlint clean (blank lines around headings,
  lists, and fences; language on fences; <= 100 columns).

## Fixtures are synthetic

Never copy text from `tasks/`, `wiki/`, `data/`, `~/agent-mail`, or a
transcript into a test fixture, even "for the live shape": this is a
PUBLIC repository and those sources are private. Read the shape, then
invent every name, item, date, and sentence. A fixture that quotes a real
row is a blocker, not a nit.

## Findings you may NOT act on

- S2 (what the daily sync may auto-commit) — Shawn's decision is pending;
  leave the `git add -A` semantics alone.
- H1 (extraction sends only the last 30 messages) — decision pending.
- Anything the report marks deferred or rejected.

## Deliverable — your final message (under ~120 lines, no code dumps)

1. A table: finding ID -> disposition. "fixed" carries file:line and the
   test name; "not fixed" carries the reason.
2. Anything NEW you found (file:line, one sentence each), each labelled
   CONFIRMED or SUSPECTED.
3. The suite's last line and `git log --oneline main..HEAD` for your branch.
4. Risks: any change to live behaviour the operator must know before merge
   (for example "on the next cron tick, X will happen").
