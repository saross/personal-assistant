---
title: "First code audit of personal-assistant — 2026-09-08"
tags: [audit, quality, hooks, sync, postgres, agent-mail]
created: 2026-09-08
updated: 2026-09-08
status: in-progress
---

# First code audit of personal-assistant

Shawn asked (2026-09-08) for `/audit` on the code written on 7–8 September,
then widened it: "I don't think we've ever done an audit in this repo
before." This is the durable record. Each finding carries a disposition,
because a finding that lives only in a chat log is rediscovered at the
worst moment and the weaker claim it implies is forgotten first.

## Method

- Scope: 94 source files (~41k lines of implementation, ~19k of tests),
  in tranches by risk. First wave: today's code; the session hooks; the
  git and sync writers; the memory-to-Postgres pipeline. Later waves (not
  yet run): memory-store maintenance, retrieval and serving, the session
  archive pipeline, external services, style-analyser tooling.
- Two orthogonal lenses per tranche, each a fresh-context Opus agent,
  read-only: Lens A (does the code do what it claims?) and Lens B (assume
  it is wrong: would the tests notice? — mutation testing in throwaway
  copies). The author never reviews their own code in the same context.
- Verdicts: CONFIRMED means reproduced or demonstrated; SUSPECTED means
  read-only inference the lens could not confirm.
- Dispositions: **fixed** (commit named), **next** (queued for this
  audit's fix rounds), **decision** (needs Shawn), **deferred** (recorded,
  not planned), **rejected** (false positive after verification).

## Tranche 0 — code written 7–8 Sep (mail, tripwire, archiver, checker, verifier)

Lens A: 3 critical, 11 medium, 11 low. Lens B: 113 mutations, 59 survived
(48% killed); 6 critical, 9 medium. Plus the Codex-side review of PR #113.
All fixed in one commit on 2026-09-08 (see the commit "fix: audit round
one on the 2026-09-07/08 code"), suite 1,250:

| Finding | Disposition |
|---|---|
| Tripwire window started "now" not midnight (`--since` bare date) | fixed |
| Tripwire `--max-count` applied before `--reverse` drops oldest commits | fixed (cap in Python after reverse) |
| Control characters in filenames / header values / subjects forge context lines | fixed (printable-only, bounded, no brackets; NUL-separated fixed records) |
| Watcher reports "cleared" on a transient error | fixed (unknown, not zero) |
| Watcher `--root` not expanded; missing root silent | fixed |
| Archiver: symlinked outbox/seen, unbounded read, no size cap | fixed (parity with the hook) |
| Archiver: failed commit never retried | fixed |
| Archiver: Codex `Read:` receipts not parsed (29 of 45 lost their time) | fixed |
| Checker: `NAME =value` passes, quoted `#` flagged, empty source passes, unparseable expiry skipped silently, unquoted path | fixed |
| Verifier: case asymmetry, zero-width characters, `%2F` in remote, trimmed field list crashes | fixed |
| Hook: linked worktree's git root is the worktree, not the repository (Astra, #113) | fixed (remote repository name, common-dir fallback) |
| Tests: no entry-point coverage; commit pathspec untested on commit; 5 verifier fixtures testing the wrong rule; `attempt()` untested; watcher loop untested | fixed (67 tests in the five files, from 38) |
| `check-credentials.py` has no tests | fixed in PR #115 (b0f3269): the case list, the wiring, and the bash divergences, each verified by probe |
| Tripwire never examines local `main` when `origin/main` resolves | deferred (the token pushes to origin; a local-only Codex commit is not the threat) |
| Archiver sort key mixes `Date:` and `sent` formats | deferred (deterministic; all live headers are ISO) |

### Round 1b — re-audit of the round-one fixes (fresh agent, 2026-09-08)

The protocol requires a fresh-context pass over each round of fixes. The
re-audit of 0577648 found 1 critical, 8 medium, 9 low; 18 findings. The
critical and every medium in Claude-owned code are fixed in 06225a0 and
5798dc9 (suite 1,275); the checker's two are on the hook-tests branch.

| # | Finding | Disposition |
|---|---|---|
| 1 | 0577648 trips its own tripwire (it credits the Codex agent as co-author for a reviewed patch) and shipped the suite red — `pytest \| tail -1` masked the exit status | fixed in 06225a0: a `Claude-Session` trailer exempts a commit; process: never pipe the suite through `tail` without checking the exit status |
| 2, 3 | Hook and watcher print the unsanitised `Project:` header on the "Other projects" line (CONFIRMED: raw ANSI reached hook stdout) | fixed in 5798dc9: `route()` keys the counts by `safe_value` |
| 4, 5 | `safe_value` stripped brackets only; `Lane: fable; project: x` forged a second field, and the test pinned the forged output as correct | fixed in 5798dc9: a value is a slug (`[A-Za-z0-9._-]`, ≤60) or `invalid`; test rewritten |
| 6 | A printable filename with brackets forged a bracket group on the listing line | fixed in 5798dc9: names must match `[A-Za-z0-9._-]+\.md` (all 97 live names conform) |
| 7 | Checker misses `NAME= value` (bash runs the secret as a command with NAME empty) | fixed in PR #115 (b0f3269) |
| 8 | Checker's `quoted` guard turned `TOKEN='abc' # comment` from a true positive into a silent false negative | fixed in PR #115 (b0f3269) |
| 9 | Verifier coverage-guard test's `else: pass` — the guard was deletable with the test green (CONFIRMED by mutation) | fixed in 5798dc9: removes every case for one rule and requires the refusal |
| 10 | Tripwire `SINCE` had no zone; a UTC or US host narrowed the window by up to 17 h | fixed in 5798dc9: `+10:00` pinned; boundary test across three zones |
| 11 | A trailing `%2F` in an admitted remote defeated the segment count | fixed in 5798dc9: slash counts compared |
| 12 | Admitted clone paths are ASCII-only, so `~/café-notes` cannot be admitted | rejected (deliberate: look-alike characters are the threat; revisit if a real path needs it) |
| 13 | A failing `--git-common-dir` query skipped the `--show-toplevel` fallback | fixed in 5798dc9: separate try blocks |
| 14 | Archiver refusals were silent and the size cap also applied to the archive scan, so an accepted message could drop out of the index | fixed in 5798dc9: refusals counted and named; archive scanned uncapped |
| 15 | `when_from_note` lost two live receipt shapes (`Read and assessed … on <date>`; `Read: <date> <time> UTC`) | fixed in 5798dc9: first date-shaped token, time normalised |
| 16 | Watcher WARN line undocumented in the runbook | fixed in 5798dc9 |
| 17 | Archiver returned 0 after a failed commit, so `daily-sync.sh` never warned | fixed in 5798dc9: exit 1; `OSError` caught too |
| 18 | Weak tests: constant-only `SINCE` tests; `printable(author)` unpinned; wiring test by byte offset; wall-clock watcher test | tripwire tests fixed in 5798dc9; wiring test → sync-writers branch; wall-clock test deferred (flake risk noted) |

Also found while building the fix worktrees: two modules create `logs/` at
import time and fail collection when the data submodule is uninitialised
(`tests/test_jsonl_flock.py`, `tests/test_tag_gardening.py`; H12's class).
Deferred; the worktrees stub the directories.

### Round 1c — re-audit of round 1b (fresh agent, 2026-09-08)

No critical; 5 medium, 10 low; every round-1b finding confirmed fixed
under mutation, no live mail regresses. Fixed in 0f94722 (suite 1,283):

| # | Finding | Disposition |
|---|---|---|
| M-1 | Tripwire output bracket-forgeable: an author name closed the `[author]` group and planted text in the relayed block (CONFIRMED) | fixed: `printable()` drops brackets |
| M-2 | `Claude-Session` exemption is a one-line, Codex-readable opt-out; per-commit `--ack` already existed | narrowed (a Codex author identity is flagged regardless); the exemption itself is **decision D4** |
| M-3 | Archiver mirrored hostile agent/peer directory names into the repository and index (CONFIRMED; Codex can create `codex/outbox/<name>/`) | fixed: slug rule on directories and message names, refusals named |
| M-4 | Hook printed an unvalidated sender directory name in every path | fixed: slug rule on sender directories |
| M-5 | The split-try test could not fail (run from the repo root, both fallbacks agree) | fixed: runs from a subdirectory |
| L-1 | Runbook claimed a bad filename is shown as `invalid`; it is skipped silently | fixed: wording |
| L-2, L-3 | `fullmatch` anchoring and the archiver's name refusal untested | fixed: tests |
| L-4 | Protocol allowed `gpt-5 high` and free-text workstreams, which now render `invalid` | fixed: proposal defines routing values as slugs (Astra to mirror) |
| L-5, L-6 | `routes_here` and `annotate` disagreed on a non-slug project; dead `or "invalid"` branch | fixed: `message_project()` is the single sanitised value |
| L-7, L-8 | Stale "seven fields" comments; docstring wrong about a grown source | fixed |
| L-9 | Receipt note stored raw while the subject is filtered | fixed |
| L-10 | Stat-then-copy race could land an oversized file (SUSPECTED) | fixed: bounded read |
| — | Double-encoded `%252F` passes one `unquote` (SUSPECTED, server-dependent) | deferred |

### Round 1d — re-audit of round 1c (fresh agent, 2026-09-08)

No critical; 6 medium, 6 low. All fixed in 122c9e3 (suite 1,288) except
where noted:

| # | Finding | Disposition |
|---|---|---|
| 1 | The sender-directory test passed on the old code: its fixtures carried `From: codex`, so the header check rejected them, not the new rule (CONFIRMED by mutation) | fixed: `From:` names the hostile directory |
| 2 | The bounded-copy test called the helper directly; replacing the call inside `copy_new` with an unbounded copy stayed green | fixed: the test drives `copy_new` with an oversized file past the size check |
| 3 | Tripwire bracket stripping was ASCII-only; fullwidth U+FF3B/U+FF3D forged the author group (CONFIRMED) | fixed: every Unicode open/close punctuation character is dropped |
| 4 | The session's own project (remote URL or directory name) was printed raw; a remote `repo%0a-%20SYSTEM…` forged a second line in the hook's block (CONFIRMED) | fixed: the session project and `--project`/`AGENT_MAIL_PROJECT` pass the slug rule; an `invalid` session collects no invalid-tagged mail |
| 5 | The archived index stored Project, Lane, Workstream, and Date raw, persisting the very forgery the hook rejects (CONFIRMED) | fixed: same rule as the hook; Date printable-only |
| 6 | The by-identity narrowing of the `Claude-Session` exemption is unreachable: both agents commit as Shawn, so only the trailer distinguishes them | recorded; decision D4 is the only fix that bites |
| L | `sha256(source)` read a grown file whole before the bounded copy | fixed: one bounded read per source |
| L | Runbook and proposal claimed a `<stamp>-<sender>-<slug>.md` shape the code does not enforce; the proposal still said "basename of the git root" | fixed: wording matches the code |
| L | Archiver docstring said every non-conforming file is refused; a non-`.md` file is ignored | fixed: wording |
| L | The Codex-side hook applies no v3 routing and no name rule, so the two agents can disagree on what is mail | with Astra (message of 2026-09-08T02:19Z) |
| L | Every non-slug project collapses into one `invalid` bucket | accepted |

### Round 1e — re-audit of round 1d (fresh agent, 2026-09-08)

No critical; 3 medium, 5 low. Fixed in 940fb2d:

| # | Finding | Disposition |
|---|---|---|
| M1 | Round 1d's bracket stripping removed parentheses from 89% of relayed subjects (`fix(scope):` became `fixscope:`), and a test pinned the damage (CONFIRMED) | fixed: NFKC then only bracket-like characters go; ASCII parentheses stay |
| M2 | `Sm`-category bracket pieces (U+23A1, U+23A4) still forged the author group (CONFIRMED) | fixed: the author passes an allowlist; the subject drops anything named BRACKET |
| M3 | A source that vanished between listing and read aborted the whole archive run before the index and the refusal report (CONFIRMED) | fixed: skipped, seen next run |
| L1 | Hook and watcher docstrings still said "basename of the git root" | fixed |
| L2 | The archiver's copy of the slug rule could drift from the hook's | fixed: a test pins the two |
| L3 | `this session is invalid` undocumented | fixed: runbook |
| L4 | Index `Date` kept free text after control stripping | fixed: ISO stamp or `invalid` |
| L5 | The archive-side comparison read was unbounded | fixed |

The re-audit also confirmed no real repository under the home directory
(45 checked) resolves to `invalid` or `any`, and the archiver reproduces
the live mailbox exactly (98 files, 50 messages, 48 receipts, 0 refused).

## Tranche 1 — session hooks

Lens A: 4 critical, 12 medium, 12 low. Lens B: 57 mutations, 38 survived.

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| H1 | `hooks/extraction-hook.py:601,1148` — only the last 30 messages of a window go to the model, but the cursor advances past the whole window: everything before the tail is lost forever. 471 of 9,095 firings (5.2%) had >30 messages; the largest dropped 254. | CONFIRMED from `data/logs/extraction.log` | **decision** — chunk the window (more Haiku calls per firing, cheap) or raise the cap; either changes API spend, so Shawn approves |
| H2 | `hooks/session-start-code-state.py:128-136` — `commit_at_start` overwritten on resume/compact (same session id); 37 of 42 multi-write sessions recorded a changed commit. | CONFIRMED from the sidecar log | fixed in 300ee10 (first write wins) |
| H3 | `hooks/session-start-retrieval.py:644-667,821-862` — the legacy four-bucket path surfaces `verified: "false"` memories as fact; 738 such records, 401 in permanent categories; the digest path filters, the legacy path does not. | CONFIRMED (grep: `verified` read nowhere in retrieval) | fixed in 300ee10 (apply the stated anti-confabulation rule on the legacy path) |
| H4 | `scripts/_command_markers.py:61-62` — `/forget` and `/update` markers no longer match their command headers, so those exchanges (which contain the deleted/superseded memory text) are re-extracted. | CONFIRMED against `commands/*.md` | fixed in 300ee10 (fix markers; derive the test fixture from `commands/*.md`) |
| H5 (B) | `extraction-hook.py:1021,1145` — the persistence path is untested: truncating the store on every session close, or never writing, passes 1,208 tests; `tests/test_jsonl_flock.py` re-implements the append instead of importing it. | CONFIRMED (mutations survived) | fixed in PR #115 (squash-merged b0f3269) (test `append_memories` and a successful `main()` end to end, asserting bytes appended) |
| H6 (B) | `session-start-accountability.py:265` — `build_banner()` can return a constant; the counts can be swapped; slot delimiters can vanish; all green. | CONFIRMED | fixed in PR #115 (squash-merged b0f3269) (banner tests) |
| H7 (B) | `session-start-retrieval.py:1262` — on this machine the digest path is live and the tests assert only scaffolding; the digest can surface zero memories with tests green. The autouse fixture forces all machine flags off, so the suite tests the path this machine no longer takes. | CONFIRMED | fixed in PR #115 (squash-merged b0f3269) |

### Medium (hooks)

| # | Finding | Disposition |
|---|---|---|
| H8 | Accountability strikethrough regex needs the whole first cell struck; live rows append a project tag, so 23 of 25 done rows count as open; banner says 58, truth ~35 | fixed in 300ee10 (match `^~~.+~~` anywhere in the cell; the test that asserts the opposite is changed with it) |
| H9 | Accountability `Started:` regex misses the live `- **Rotated in:**` field; no slot ever gets a day counter | fixed in 300ee10 |
| H10 | Accountability prose deadline reads as "no deadline"; unparseable ≠ absent | fixed in 300ee10 (report "deadline not parsed") |
| H11 | Extraction skip-flag consumed by a tool-only assistant entry (52 of 585 cases) — command responses survive into extraction | fixed in 300ee10 |
| H12 | Extraction crashes at import when `data/` is uninitialised (`logs` symlink dangles) | fixed in 300ee10 |
| H13 | "Prefer existing tags" prompt gets the alphabetical head of a 56,698-line vocabulary | fixed in 300ee10 (seed from the most common tags in recent records) |
| H14 | `source_message_uuid` may be a non-message entry and is not "last included" | tied to H1 |
| H15 | `MAX_LOAD_RECORDS = 50000` vs 42,291 records today; binds in ~8 weeks; comments stale | fixed in 300ee10 (raise; fix comments) |
| H16 | Cursor advances past "too short" and "parse failed" windows (736 so far) | fixed in 300ee10 (do not advance on either; short windows accumulate) |
| H17 | Locale-dependent `read_text()` in five places; no top-level guard in retrieval `main()` | fixed in 300ee10 |
| H18 | Vocabulary updated inside `format_memories`, before the append that may fail | fixed in 300ee10 (move after append) |
| H19 | Anchor verification can spawn up to 72 git subprocesses per unresolved anchor inside a 30 s hook | deferred (measure first) |
| H20 (B) | No output bound pinned in the retrieval suite; the one cap test uses exactly the cap | fixed in PR #115 (squash-merged b0f3269) |
| H21 (B) | Flock guards in extraction removable with tests green; no double-firing test | fixed in PR #115 (squash-merged b0f3269) (test `main()` twice) |
| H22 (B) | `isMeta` / `isSidechain` entries are fed to the model as user turns; fixtures never carry them | fixed in PR #115 (squash-merged b0f3269) (filter; fixture from a real transcript shape) |
| H23 (B) | Project-id encodings diverge on dotted segments between writer and reader (latent) | deferred |
| H24 (B) | code-state sidecar contract pinned only by a hand-built fixture in another repo | tied to H2 |
| H25 | `scripts/digest.py:432,536,546` — `rank_fallback` admits anchored `verified: "false"` records and renders them under the heading "Verified-true entries", above the anti-confabulation line saying such content is not surfaced (CONFIRMED by the round-two agent; `tests/test_digest.py:214,323` pin it as deliberate) | fixed in PR #118 (merged 190bc7c) |
| H26 | `hooks/session-start-accountability.py:100` — `^~~.+?~~` needs the strikethrough to close inside the first cell; two live done rows close it in the last cell and count as open (23 detected, 2 missed) | fixed in PR #118 (merged 190bc7c) |
| H27 | **Private content in a public branch.** The round-two agent's banner fixtures on `claude/audit-hook-tests` (PR #115) copied rows from the private `tasks/waiting-for.md` and inbox — third-party names, a family-law item, a supplier, a car — into `tests/test_accountability_hook.py`, and the branch was pushed to the public repository (CONFIRMED by the branch's re-audit, 2026-09-08). One such name has been on `main` since commit 82f5035 (2026-05-02, line 122). | branch tip fixed with synthetic fixtures (normal commit); the history rewrite and force-push, and the `main` history, are **decision D6** |
| H28 | `hooks/extraction-hook.py` — a window shaped `[real user, real assistant, /command]` extracts normally and advances past the pending command skip, so the command's response is re-extracted on the next firing (the twin of the empty-window case fixed on PR #115; predates the branch; CONFIRMED by the round-two agent) | fixed on PR #115 (fifth round, 943da8d) after two attempts that encoded the pending skip in the cursor POSITION and each broke an invariant: the cursor record is now `{uuid, skip_pending}` per session, so position and pending state are separate facts; ten tests through `main()` assert the cursor file after each firing |
| H29 | `hooks/extraction-hook.py` marker branch — a non-meta user entry whose text merely contains a slash-command header (a tool result echoing `commands/*.md` or `scripts/_command_markers.py`) sets the skip flag and drops the next genuine assistant turn (SUSPECTED by the round-four re-audit; one such entry exists, created by this audit session) | fixed in PR #118 (merged 190bc7c) |
| H30 | `hooks/extraction-hook.py` — the command skip is a boolean, not a counter: `[cmd, cmd]` then `[resp, resp]` sends the second response to the model (CONFIRMED by the fifth re-audit; pre-existing) | fixed in PR #118 (merged 190bc7c) |

Lows (both lenses): docstring arithmetic (78 not 68), five lines over 100
columns, `os.write` return unchecked, vocabulary dedup outside the lock (9
duplicates exist), dict-equality collapse in `other_take`, `focus_limit` regex
takes the first match anywhere, non-dict stdin payloads, unstripped anchor refs,
an unreachable branch, a few boundary flips uncaught. Recorded; not planned.

## Tranche 2 — git and sync writers

Lens A: 5 critical, 11 medium, 14 low. Lens B: 20 mutations survived of ~28;
`daily-sync.sh` effectively has no behavioural test (its one end-to-end fixture
dies at line 618 before the sync body and the test passes anyway).

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| S1 | `scripts/daily-sync.sh:510-577` — a data-submodule commit made while the tree is clean afterwards is never pushed, but the parent pointer bump that references it IS pushed: origin points at a commit the other machine cannot fetch. Happened today at 09:29. `monthly-archive.py:522-539` already works around this locally. | CONFIRMED from `logs/daily-sync.log` and `git ls-tree` | fixed in PR #116 (merged 0d1d391) (push whenever `HEAD` is ahead of `@{u}`) |
| S2 | `daily-sync.sh:512` — `git add -A` after the stash pop sweeps concurrent sessions' half-written prose into an automated commit and pushes it (`e433eee`, `549d9aa`), contradicting the script's own comment and the hub rule. | CONFIRMED from history | **decision** — the daily sync is also how scratchpad and notes *appends* get committed; Shawn rules which paths the auto-commit may take |
| S3 | `daily-sync.sh:475-501` — stash-pop conflicts feed every conflicted path, prose included, to the line-union resolver; a conflicted `wiki/continuity.md` is rewritten as an interleaved union. The rebase path partitions correctly. | CONFIRMED by reading both paths | fixed in PR #116 (merged 0d1d391) (partition like the rebase path; abort on prose) |
| S4 | `daily-sync.sh:196,287` — `git checkout --ours` during a rebase takes origin's side, the opposite of the comment's intent (git-checkout(1)). | CONFIRMED against git documentation | fixed in PR #116 (merged 0d1d391) (`--theirs`, both sites) |
| S5 | `daily-sync.sh:358,405-423` run before the detached-HEAD guard at 438-445; on a detached HEAD the memory commit and the archive commit are orphaned and the working tree reverted. Likely trigger: `sync-symlinks.sh:126 git submodule update` detaching HEAD. | CONFIRMED by ordering; trigger SUSPECTED | fixed in PR #116 (merged 0d1d391) (move the guard above every commit site) |
| S6 (B) | `scripts/resolve-merge-conflicts.py` has zero tests; keeping only "ours" passes the whole suite. | CONFIRMED | fixed in PR #116 (merged 0d1d391) (tests with real conflict markers) |
| S7 (B) | `scripts/daily-sync-trigger.sh` has zero tests; "never runs again" and "breaks the hook chain" both pass. | CONFIRMED | fixed in PR #116 (merged 0d1d391) |
| S8 (B) | `archive-memories.py::apply_archive` untested: evicting without archiving, or archiving without evicting, passes. `monthly-archive.py::_apply` halts removable with tests green. | CONFIRMED | fixed in PR #114 (merged 8c61bb8) |

### Medium (sync)

| # | Finding | Disposition |
|---|---|---|
| S9 | Archiver call lacks a `DRY_RUN` guard; `--dry-run` commits | fixed in PR #116 (merged 0d1d391) |
| S10 | Two Syncthing gate-file layouts; the trigger reads one; the early-exit path renders a headerless problem | fixed in PR #116 (merged 0d1d391) |
| S11 | `sync-symlinks.sh:97` `ln -sf` on a symlink-to-directory writes inside it; needs `-sfn` | fixed in PR #114 (merged 8c61bb8) |
| S12 | Resolver: a valid-JSON non-object line raises `AttributeError`, aborting the sync with a conflicted tree | fixed in PR #116 (merged 0d1d391) |
| S13 | `compose-global-claude-md.sh:102` truncates `~/.claude/CLAUDE.md` before writing | fixed in PR #114 (merged 8c61bb8) (temp + `mv`) |
| S14 | `push-archives-to-r2.sh:91` version probe kills the script under `pipefail` | fixed in PR #114 (merged 8c61bb8) |
| S15 | `archive-memories.py:369-373` releases the flock before its commit | fixed in PR #114 (merged 8c61bb8) |
| S16 | `archive-memories.py:413`, `commit-data.sh:49,58` commit without a pathspec | fixed in PR #114 (merged 8c61bb8) |
| S17 | A conflicted orphan-stash pop wedges every later session with no gate line | fixed in PR #116 (merged 0d1d391) (gate line) |
| S18 | Syncthing SSH probe runs inside the 90 s SessionStart budget | deferred |
| S19 | Unchecked `exec` redirect and `cd` misreported as lock contention | fixed in PR #116 (merged 0d1d391) |
| S20 (B) | Explicit-pathspec contract untested for the data-submodule committers; `commit-data.sh` lock and branch guard removable | fixed in PR #114 (merged 8c61bb8) |
| S21 (B) | The end-to-end fixture would, if repaired, run `sync-symlinks.sh` against the real `~/.claude/settings.json` and rsync/R2 against real archives; pin `HOME` first | fixed in PR #116 (merged 0d1d391) (before any fixture repair) |
| S22 | The suite writes into the live private submodule through the `logs → data/logs` symlink: `scripts/_bulk_rewrite_guard.py:76` and `scripts/rebuild-postgres.py:204` (fixed on PR #117) (CONFIRMED by three round-two agents; `rebuild.log` grew during today's runs; the guard opens its file handler at import) | guard half fixed in PR #118 (lazy handler, merged 190bc7c; the guard's lock path also crashed on a dangling `logs` symlink and now refuses instead); `rebuild.log` fixed in PR #117 (merged 773a0bd), whose suite also owns its `HOME`; `scripts/surfacing_log.py:75-76` has the same `__file__`-derived shape and wrote `logs/surfaced.log` when the retrieval hook was exercised (CONFIRMED by the PR #118 re-audit) — fixed in **PR #120** (round 3b, merged 69a7590: the path resolves at call time, nothing opens at import, the production path is tested in a child process) |
| S23 | `daily-sync.sh` shrink detector checks only the auto-sync commit; a truncation already on disk is committed by the earlier append-only block unguarded (SUSPECTED, round-two agent) | **PR #119** (`claude/audit-round3c`; first re-audit found C1 and M1-M5, fixed in e91362e-c1f4dd6; the second re-audit found a regression in that fix (`applied` drops a stash whose tracked half never landed) and an ancestor clobber, fixed in 5b4985c-3b328a5; the third re-audit found the evidence test still foolable by a concurrent write, fixed in 947ac45-bb96d27 (reverse-apply evidence); the fourth re-audit's verdict was merge — **merged 87db26b**; its follow-ups (a merge parent lacking the corpus counts as zero and can wave a truncation through, and an unattributable shrink fails open — never reachable in 1,525 data commits; the sweep marker name; two unpinned sweep clauses; binary and rename-only stash wording) are round 3c-5) |
| S24 | The parent repository has S1's hole: an unpushed parent commit with an unchanged data pointer is never pushed (CONFIRMED) | **decision** (pushing would publish another session's parent commits; see D5) |
| S25 | `resolve_rebase_conflicts`'s submodule branch is unreachable (only called for the data repository, which holds no gitlink) | deferred (dead code, harmless) |
| S26 | The rebase-abort path leaves a divergence every later run re-hits, with no gate line (S17's class) | fixed in PR #116: every non-zero exit writes a gate line |
| S27 | `scripts/daily-sync.sh` — a `git stash apply` that conflicts on a tracked path while failing to restore an untracked file (already present at the other side's content) is classified as conflicted, resolved, and dropped; the untracked file's only copy survives nowhere (CONFIRMED by the tenth re-audit of PR #116; pre-existing, byte-identical at the branch point) | **PR #119** (`claude/audit-round3c`; first re-audit found C1 and M1-M5, fixed in e91362e-c1f4dd6; the second re-audit found a regression in that fix (`applied` drops a stash whose tracked half never landed) and an ancestor clobber, fixed in 5b4985c-3b328a5; the third re-audit found the evidence test still foolable by a concurrent write, fixed in 947ac45-bb96d27 (reverse-apply evidence); the fourth re-audit's verdict was merge — **merged 87db26b**; its follow-ups (a merge parent lacking the corpus counts as zero and can wave a truncation through, and an unattributable shrink fails open — never reachable in 1,525 data commits; the sweep marker name; two unpinned sweep clauses; binary and rename-only stash wording) are round 3c-5) |
| S28 | The stash-state sidecar is wiped by the early-exit trap of a run that only read it, so the attribution decays after one idle session start; supersede-by-SHA over-matches through the stack listing; the write side lacks the applied-outranks-conflicted precedence (CONFIRMED, same pass) | **PR #119** (`claude/audit-round3c`; first re-audit found C1 and M1-M5, fixed in e91362e-c1f4dd6; the second re-audit found a regression in that fix (`applied` drops a stash whose tracked half never landed) and an ancestor clobber, fixed in 5b4985c-3b328a5; the third re-audit found the evidence test still foolable by a concurrent write, fixed in 947ac45-bb96d27 (reverse-apply evidence); the fourth re-audit's verdict was merge — **merged 87db26b**; its follow-ups (a merge parent lacking the corpus counts as zero and can wave a truncation through, and an unattributable shrink fails open — never reachable in 1,525 data commits; the sweep marker name; two unpinned sweep clauses; binary and rename-only stash wording) are round 3c-5) |
| S4 note | Measured on the branch: neither `--ours` nor `--theirs` changes a conflicted gitlink's index entry; the following `git add` records the checked-out HEAD, which is why the live sync resolved these correctly despite the inverted flag. The fix is legibility, not data loss. | recorded |

Lows recorded: hardcoded interpreter path at 802; `[[ "None" -gt 0 ]]` under
`set -u`; raw interpolation into `bash -c`/`ssh`/Python in
`syncthing-health.sh`; diff3 markers unsupported (latent); stale co-author in
`commit-data.sh`; two drifting rebase resolvers; `--porcelain` without `-z`;
psql `IN (...)` from 10,000 ids; cc-archives gate not rewritten when the mount
is absent; EXIT trap pops the top stash; `/tmp` lock ownership; only `$1`
inspected for `--dry-run`; two shrink detectors disagree by one line;
`sync_memory_edit.py` reads via the root symlink; `advance_or_quarantine` has no
callers.

## Tranche 3a — memory-to-Postgres pipeline (Lens A; Lens B not yet run)

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| P1 | `scripts/sync-sessions-to-postgres.py:543-552,652-658` — every `psycopg2.Error` is reported as "PostgreSQL may be down" and the cursor held. Two archive metadata files carry a NUL in LLM-generated narrative; Postgres rejects `\x00` in jsonb; the `sessions` table has been stale since 2026-08-17 with 48 sessions unsynced and the wrong diagnosis in the log. | CONFIRMED live | fixed in PR #117 (merged 773a0bd) (split outage from data errors; quarantine the row; per-row fallback after a failed batch; sanitise NUL at ingest) |
| P2 | `scripts/sync-to-postgres.py:656-665,950-954,312` — same conflation in the memories path; `created_at` unguarded (`TIMESTAMPTZ NOT NULL`); a NUL in content raises `ValueError` outside the handler. | CONFIRMED by reading; free-text dates have reached `deadline_at` repeatedly | fixed in PR #117 (merged 773a0bd). Live confirmation found at merge time: `logs/sync-cron.log` holds 2,527 refusals of one memory (`2026-06-15-46328e405d0c`, no `session_id`, SQLSTATE 23502), each logged as "PostgreSQL may be down"; the merged sync quarantines it on the first tick and raises the quarantine gate, to be acknowledged with `--ack-quarantine` once the record is repaired |
| P3 | `scripts/embed.py:37` — `OLLAMA_BASE_URL=""` from `ollama-endpoint.sh`'s failure path yields `ValueError: unknown url type` outside the degradation ladder; the documented fallback does not exist. | CONFIRMED by repro | fixed in PR #117 (merged 773a0bd) (`or` default; fix the wrapper's comment) |

### Medium (Postgres)

| # | Finding | Disposition |
|---|---|---|
| P4 | `rebuild-postgres.py` never truncates `session_chunks` | fixed in PR #117 (merged 773a0bd) |
| P5 | `index-session-content.py` has no schema-version guard and tracebacks on an outage | fixed in PR #117 (merged 773a0bd) |
| P6 | `backfill-embeddings.py --limit` not honoured (200 embedded for `--limit 5`) | fixed in PR #117 (merged 773a0bd) |
| P7 | `backfill-embeddings.py --catch-up` tracebacks on a DB error mid-batch | fixed in PR #117 (merged 773a0bd) |
| P8 | `check-memory-drift.py --recover` resurrects soft-deleted memories (`is_active` and history fields not selected) | fixed in PR #117 (merged 773a0bd) |
| P9 | `check-memory-drift.py:298` is the only canonical writer without the flock | fixed in PR #117 (merged 773a0bd) |
| P10 | `.get(key, default)` on a NOT NULL column right after the comment warning against it | fixed in PR #117 (merged 773a0bd) |
| P11 | Sessions cursor is naive local time compared lexicographically; a clock step back skips sessions forever | deferred (document `--full-resync`; fix with UTC when the archive format changes) |
| P12 | No embedding-dimension validation; a wrong-dimension model re-embeds the same rows forever with a warning | fixed in PR #117 (merged 773a0bd) (check `len == 768` once) |
| P13 | Two quarantine record shapes in one file; dedup sees one | deferred |
| P14 | Poison lines re-quarantined every 5 minutes while the cursor is halted | fixed in PR #117 (merged 773a0bd) (dedup before append) |
| P15 | Drift recovery pulls the whole table to filter in Python | deferred |
| P16 | Three processes read-modify-write `sync-cursors.json` without lock or atomic rename | fixed in PR #117 (merged 773a0bd) (atomic write; the memories sync already has the flock pattern) |
| P17 | `scripts/sync-to-zotero.py:129` is the third writer of `sync-cursors.json` and still writes unlocked and non-atomically; P16 protects the other two (CONFIRMED, round-two agent) | fixed in PR #117: all four cursor writers take the flock and write atomically |

Lows recorded: three constant f-string SQL sites; handler stacking; `tool_calls:
0` stored as NULL; 235 MB steady-state RSS per 5-minute tick; `split()` vs
`splitlines()`; id-less stash lines; U+2028 latent; stale comments; docstring
"bounded memory" claim.

## Tranche 3b — memory-store writers (both lenses, 2026-09-08 evening)

Scope: `dedup-memories.py`, `tag-gardening.py`, `recover_anchors.py`,
`sync_memory_edit.py`, `archive-memories.py`, `apply-decay.py`
(PostgreSQL-only), `monthly-archive.py`, `_timestamps.py`,
`_schema_version.py`, and their tests. Lens A: 3 critical, 10 medium, 8 low.
Lens B: 63 mutations over 170 tests; 4 critical, 11 medium. Fix round 4a on
`claude/audit-round4a`.

### Critical (writers)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| W1 | `scripts/dedup-memories.py:293` writes `ensure_ascii=False` and `:98` reads with `splitlines()`: a record holding U+2028/U+2029/U+0085 (escaped by the hook's `json.dumps`) is split into two malformed lines on the second run; same write at `tag-gardening.py:591,647`; the Postgres cursor is a `splitlines()` count, so it drifts from every file-iteration reader | CONFIRMED by repro | fixed in **PR #121** (merged d1c3773) |
| W2 | `scripts/tag-gardening.py:744` — `orphans --action clean` rewrites the protected `tag-vocabulary.txt` with a bare `write_text`: no guard, no lock, no temp-and-rename; the hook appends under a shared lock, `/tags` step 7 runs it routinely | CONFIRMED by repro | fixed in **PR #121** (merged d1c3773) |
| W3 | `scripts/recover_anchors.py:434,302-352` — the plan is built outside the rewrite lock and whole stale records are written back, reverting a `/forget` or `/update` that landed in between (the docstring claims parity with `archive-memories`, which re-reads inside the lock) | CONFIRMED by repro | fixed in **PR #121** (merged d1c3773) |
| WT1 | `scripts/sync_memory_edit.py:107-110` — the UPDATE's WHERE clause is untested (`id != %s` stays green; the test compares the constant with itself); a `/forget` would blank every other Postgres row | CONFIRMED (mutation) | fixed in **PR #121** (merged d1c3773) |
| WT2 | `scripts/recover_anchors.py:333` — the write path is untested: deleting the verbatim `else: out.write(line)` (corpus reduced to the modified records), the guard (:317), the lock (:319), the atomic rename (:320), and the `--apply` gate (:441) all stay green | CONFIRMED (mutation) | fixed in **PR #121** (merged d1c3773) |
| WT3 | `scripts/dedup-memories.py` has no test file; its module constants resolve to the real store from `__file__` | CONFIRMED | fixed in **PR #121** (merged d1c3773) |
| WT4 | A test in `tests/test_tag_gardening.py` that forgets to patch the store path rewrites the REAL canonical store and the suite stays green: the autouse `_bypass_rewrite_guard` (:31-56) noops the one refusing check and the conftest hermeticity guard (`tests/conftest.py:220-260`) watches only `~/.cache` | CONFIRMED by repro in a copy | fixed in **PR #121** (merged d1c3773) |

### Medium (writers)

| # | Finding | Disposition |
|---|---|---|
| W4 | `tag-gardening.py:676-687,744` — both vocabulary rewrites drop every `#` comment line (eight section headers live) | fixed in **PR #121** (merged d1c3773) |
| W5 | `tag-gardening.py:501` — the bulk guard runs before the `--dry-run` branch: a dry run takes the exclusive daily-sync lock and exits 2 on a dirty tree | fixed in **PR #121** (merged d1c3773) |
| W6 | `dedup-memories.py:383` logs a backup file that nothing creates; the script's only deletion-safety claim is false | fixed in **PR #121** (merged d1c3773) |
| W7 | `recover_anchors.py:233,328` — `json.loads` with no `try`: one malformed line aborts both modes with a traceback and orphans `memories.jsonl.tmp` | fixed in **PR #121** (merged d1c3773) |
| W8 | `tag-gardening.py:692` — a tag merge never reaches Postgres and the printed remedy (`sync-to-postgres.py`, which is insert-only past the cursor) is wrong; `commands/tags.md:167` says a full rebuild | fixed in **PR #121** (merged d1c3773) |
| W9 | Line-position cursor plus mid-file deletion: `archive-memories --apply` or `dedup-memories` run with an unsynced backlog leaves the deleted count of never-synced records below the cursor forever (`sync-to-postgres.py:1354-1382` resets only when the cursor passes the end); `monthly-archive` syncs first (SUSPECTED, no Postgres) | fixed in **PR #121** (merged d1c3773) (refuse while a backlog exists) |
| W10 | `dedup-memories.py:160,292` — the re-id path records no old-to-new mapping; `surfaced.log`, `superseded_by`, and the Postgres row and embedding under the old id are orphaned | fixed in **PR #121** (merged d1c3773) |
| W11 | `sync_memory_edit.py:55,107` — `/update` replaces content but keeps the embedding; refill is `WHERE embedding IS NULL`, so semantic recall matches the old text (SUSPECTED) | fixed in **PR #121** (merged d1c3773) (`embedding = NULL` on content change) |
| W12 | `tag-gardening.py:541,581,634` — plan keys stored raw, matched lower-cased: a loser with any uppercase replaces nothing while reporting "Tags retired: 1" | fixed in **PR #121** (merged d1c3773) |
| W13 | `dedup-memories.py:244,402` — one unclassified group aborts the whole run (invariant exit) though the comment says such groups are kept verbatim | fixed in **PR #121** (merged d1c3773) |
| WT5 | `tag-gardening.py:613` — a malformed line is dropped on decode error and no test notices (`archive-memories` has the equivalent test) | fixed in **PR #121** (merged d1c3773) |
| WT6 | `tag-gardening.py:501-505,603,673,662-664` — guard, both flocks, and the atomic rename unpinned | fixed in **PR #121** (merged d1c3773) |
| WT7 | `apply-decay.py:107,111-112,102` — the decay predicate is asserted by substring: `NOW() + interval`, `<` to `>`, `AND` to `OR` all green | fixed in **PR #121** (merged d1c3773) |
| WT8 | `apply-decay.py:88-93` — the schema-version call is deletable | fixed in **PR #121** (merged d1c3773) |
| WT9 | `archive-memories.py:337,372,534` — JSONL flock, atomic rename, and `--apply` gate unpinned (a dry run that archives, rewrites, and commits stays green) | fixed in **PR #121** (merged d1c3773) |
| WT10 | `archive-memories.py:427-430` — the `Rewrite-Class: bulk` trailer (what stops the daily sync's shrink detector resetting the commit) is droppable | fixed in **PR #121** (merged d1c3773) |
| WT11 | `archive-memories.py:441-442` — `git add --literal-pathspecs -- <paths>` to `add -A` stays green (sweeps unstaged work) | fixed in **PR #121** (merged d1c3773) |
| WT12 | `recover_anchors.py:155,185` — stale `verified` kept in the written record; `revisions` overwritten instead of appended | fixed in **PR #121** (merged d1c3773) |
| WT13 | `recover_anchors.py:133,100,234` — "already resolves" gate, absolute refs, and `build_plans` selecting `verified == "true"` all green; `build_plans` untested | fixed in **PR #121** (merged d1c3773) |
| WT14 | `sync_memory_edit.py:128` — dropping the `with conn` transaction stays green: the UPDATE is discarded on close while "PostgreSQL reconciled" prints | fixed in **PR #121** (merged d1c3773) |
| WT15 | `monthly-archive.py:112,491-494,484-485` — the sanity cap is asserted as `CAP + 1` (never pinned), the post-apply re-check is deletable, the partition HALT can become `return 0` | fixed in **PR #121** (merged d1c3773) |

Lows recorded: W14 parent directories not fsynced; W15 `tag-gardening`
rewrites without flush or fsync and builds the corpus in memory; W16 merge
log stamped naive local time; W17 `sync_memory_edit` skips
`assert_schema_version`; W18 `apply-decay` has no `PERMANENT_OVERRIDES` net
and the schema seed cannot repair a legacy 180-day row; W19 partition month
is UTC (10-11 h out of step with the local month — decision D7); W20
`recover_anchors` commits after releasing the lock (the S15 window); W21
`archive-memories` and `recover_anchors` pin the corpus to `Path.home()`, so
an `--apply` from a copy targets the live store (deliberate; decision D8);
WT16-19 case-folding, field precedence, a vacuous `Z` test on Python 3.13,
fsync and the merge log unobserved. Cross-file: `_timestamps.py` is imported
by no writer; serialisation differs between the hook and two writers (W1);
Postgres change detection is line position only, so every in-place edit needs
its own surgical UPDATE (`tag-gardening` has none); adjacent,
`hooks/extraction-hook.py:1375` ignores the return value of `os.write`.
Verified correct: decay boundaries and edge cases, CRLF round-trip,
blank-line preservation in three writers, partition append fsynced before the
corpus rename, idempotent retry, locks held across read-modify-rename (except
W3), temp files beside their targets, no injection, no import-time writes,
UK spelling. Round 4a-2 (the PR #121 re-audit's follow-ups M1-M8 plus
the network guard and the widened store guard) is **PR #123**
(`claude/audit-round4a-2`; re-audit verdict merge after one shadowed test name was
un-shadowed; **merged bb616b7**). Its re-audit's follow-ups (a lone CR still
splits the cursor and gate definitions; the network guard's comment overstates
its scope — UDP, child processes, and C-level connectors are covered only by
the PGHOST environment; a fixture that repoints PGHOST plus an import-bound
connector reaches the live database; PGSERVICE pops untested; four surviving
mutations; the midnight flake in `test_daily_sync_trigger.py`, a module-level
`date.today()`) are round 4a-3, now **PR #127** (`claude/audit-round4a-3`; it also makes the store guard tolerate live appends and warn rather than fail on concurrent source edits unless `PA_HERMETICITY_STRICT=1`, and pins the trigger tests' shell date). Its re-audit refused on two small items — the advisory warning is swallowed by pytest's capture so the operator never sees it, and the documented strict invocation runs from an archive copy that has no venv and no data, where the store half watches nothing — with follow-ups (the source-tree exemption untested through the session path; appends tolerated with content unverified; a rotation false-fails; `tests/` not watched); round 4a-4 done, and the third re-audit — which exercised the store half of the guard against a populated synthetic store for the first time — found nothing blocking: **merged 282e6b3**. Round 4a-5 is **PR #137** (the three operator-facing notes pinned through nested pytest runs under default capture; one classification per teardown; the vocabulary rule compares the raw line; compressed rotations, new log files, and a half-written trailing line tolerated and reported in advisory mode, fatal under strict; both halves report before one failure; a self-caught test that made the session summary cry wolf scoped by an `isolated_report` fixture; re-audit running, asked to run the strict suite against a populated synthetic store for the first time). A
separate flake investigation confirmed the midnight mechanism by reproduction
(`tests/test_daily_sync_trigger.py:29-30` are the suite's only live-clock
module constants; any full run starting in the ~80 s before local midnight
fails exactly those two tests) and found that the widened store guard
snapshots the REAL checkout's source trees and logs, so a concurrent
session editing `wiki/` or the extraction hook appending a log during a run
fails that run at teardown — a recurring false failure in a repository
worked by several sessions. Round 4a-3 is asked to accept appends to the
store and logs, and to make the source-tree watch advisory unless
`PA_HERMETICITY_STRICT=1` (set by clean-copy and re-audit runs).

## Tranche 3c — retrieval and serving (both lenses, 2026-09-08 evening)

Scope: `fetch-memories.py`, `memory_mcp.py`, `search-sessions.py`,
`surfacing_stats.py`, `log-recall.py`, `log-confab-flag.py`,
`digest-preview.py`, `project_id.py`, `resolve_session_id.py`, their tests,
and the `/recall` and `/forget` command documents. Lens A: 4 critical,
5 medium, 10 low. Lens B: 18 mutations, 18 survived; 8 critical, 8 medium.
Fix round 4b on `claude/audit-round4b`.

### Critical (retrieval)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| R1 | `scripts/fetch-memories.py:513-525,552-555,608-611` — the JSONL fallback sorts naive and aware datetimes together (date-only legacy records are still on disk), so `/recall`'s depth fetch dies with a `TypeError` exactly when Postgres is down; the retrieval hook fixed the same defect at `session-start-retrieval.py:452` and this script did not | CONFIRMED by repro | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| R2 | `scripts/fetch-memories.py:462-510` (`matches_filters`) and `scripts/memory_mcp.py:250-271,433-445` never check `is_active`, so every non-Postgres path returns forgotten memories, ranked first, unmarked; `commands/forget.md:62-65` promises the opposite | CONFIRMED by repro | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| R3 | `commands/recall.md:57-70,234` — the `/recall` procedure itself filters on content, category, and tag only and states that all memories are searched; it is the path `/forget` names as its id source | CONFIRMED by reading | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| R4 | `scripts/project_id.py:56` does not encode `.` the way Claude Code does (live: `-home-shawn-personal-assistant--claude-worktrees-…`, double dash); any cwd with a dot component sees zero same-project memories, which is the drift the module docstring exists to prevent; `resolve()` breaks a symlinked cwd the same way | CONFIRMED by repro and directory evidence | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT1 | `scripts/fetch-memories.py:241-301` — the whole Postgres query body is unreachable by the suite (a hard-coded result after connect passes 130 of 130); reading `memories` instead of `active_memories` (:248, and `memory_mcp.py:491`), `AND` to `OR` (:281-283), `DESC` to `ASC`, and `LIMIT` ignored all stay green | CONFIRMED (mutation) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT2 | `scripts/fetch-memories.py:710-803` — `main()` has no test: deleting the JSONL fallback and the `--limit` validation pass; `parse_args`, `_staleness_warning`, and `_log_invocation` are unreferenced by any test | CONFIRMED (mutation) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT3 | `scripts/memory_mcp.py:390-392,251-271` — `search_sessions` returning a hard-coded list is green; the JSONL fallback test stubs `matches_filters` to `True`, so dropping the project filter, reversing the sort, and dropping the limit pass together | CONFIRMED (mutation) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT4 | `scripts/search-sessions.py` has zero coverage in the full suite (LIKE escaping, the role filter, and the rank order all mutable); `scripts/fetch-memories.py:318-430` `try_semantic` is never called (worst matches first stays green) | CONFIRMED (mutation, full suite) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |

### Medium (retrieval)

| # | Finding | Disposition |
|---|---|---|
| R5 | `scripts/memory_mcp.py` — six tools serve memories and none logs to `surfaced.log`; `tier-2-retrieval.md:82-92` names three paths, MCP is an undeclared fourth, so earned-utility counts are biased | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| R6 | `scripts/fetch-memories.py:732-757` — `--semantic` silently discards `--query` and `--id`, and an empty semantic result never falls back to FTS despite the stderr text (SUSPECTED) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| R7 | `scripts/fetch-memories.py:389-390` — rows without an embedding are dropped, not ranked last: a memory written since the last backfill is invisible to `--semantic` and MCP `semantic_search`, undocumented | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) (document and count) |
| R8 | `commands/recall.md:174-187` — the session-search snippet interpolates user text into `plainto_tsquery(...)` inside a `psql -c` shell string | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) (use `search-sessions.py`) |
| R9 | `scripts/search-sessions.py:70-86` — a `--substring` pattern under three characters cannot use the trigram index and no statement or connect timeout exists anywhere in `scripts/`; the MCP tool exposes it (SUSPECTED) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT5 | `scripts/fetch-memories.py:496` — multi-tag OR to AND survives (every tag test passes one tag) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT6 | `scripts/surfacing_stats.py:42` — the reader's default path is never compared with the writer's; `_render_human` and `main()` untested | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT7 | `scripts/log-recall.py:106-141` — `main()` untested; writing `source=fetch` for a recall passes | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT8 | `scripts/memory_mcp.py:437` — `get_memory` prefix match survives | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT9 | The `SchemaVersionError` guard is unpinned at every read call site (`fetch-memories.py:237,377`, `memory_mcp.py:111`) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT10 | `scripts/project_id.py:59-81,119-208` — `decode_project_id`, `repo_set`, `repo_set_for` untested (every id decoding to `/` passes) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT11 | `scripts/resolve_session_id.py` — zero coverage, nothing imports it; the planned `tests/test_resolve_session_id.py` does not exist | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |
| RT12 | Write side: `log-recall.py:87` and `log-confab-flag.py:169` bind a `__file__`-derived default log path at import with no pytest guard, and `fetch-memories.py:813` has no injection point — a throwaway test created `logs/fetch-memories.log` and `logs/confab-flags.log` in the checkout and the suite stayed green (S22's fix reached one of four writers) | fixed in **PR #122** (merged 46e7dac after two re-audits); round 4b-3 is **PR #130** (merged after one re-audit: the soft-delete token set matches Postgres's with both writers sending a real boolean, the session query on stdin for both `/recall` and `/search-sessions`, the fake database raising on any SQL it cannot emulate; lows left: PostgreSQL also accepts unique leading prefixes of its boolean words, the true-token set is inert, a query line equal to the heredoc delimiter, `--query-stdin` with `--show` reads stdin needlessly) |

Lows recorded: R10 `log-recall --limit` not sanitised (forged columns);
R11 FTS order has no final tiebreak; R12 `show_turns` multiplies rows with
sub-agent chunks; R13 catalogue `rel` unvalidated (escapes the root); R14
`resolve_session_id` tracebacks on a stale mount instead of exit 2; R15
`/recall` output never shows the id that `/forget` needs; R16
`matches_filters(tags=[])` excludes everything; R17 `fetch-memories.py:813`
and `digest-preview.py:39` write into the private submodule by default
(digest-preview lines carry no preview marker); R18 psycopg2 error text
crosses the MCP boundary; R19 "5 read-only MCP tools" is six; RT13
`digest-preview` zero coverage; RT14 `list_recent` omits `verified`.
Cross-file: the flag-OFF legacy path in `hooks/session-start-retrieval.py:1381-1400`
applies no `is_active` filter and logs nothing surfaced; two archive roots
(Postgres built from `~/cc-archives` versus the rpi share) not
cross-referenced; the JSONL-fallback ranking differs between CLI and MCP.
Verified correct: parameterisation of every Python query; LIKE escaping;
`is_active` on all four Postgres paths via `active_memories`; connections
closed on every path; limit bounds; exact-match ids; empty and
punctuation-only queries; no embedding call without an explicit flag
(Ollama on localhost only, no cloud path); UK spelling.

## Tranche 4 — session archive pipeline (both lenses, 2026-09-08 night)

Scope: `bulk-archive.py`, `check-archive-drift.py`, `reprocess-sessions.py`,
`backfill-summaries.py`, `validate-session-metadata.py`,
`normalise-archive-storage.py`, `extract-transcript-text.py`,
`_scan_archives.py`, `extraction-prompt-spotcheck.py`,
`search-archives-safe.sh`, `push-archives-to-r2.sh`, and their tests. Lens A:
5 critical, 13 medium, 9 low. Lens B: 31 mutations, 31 survived; 4 critical,
7 medium. The archive write path itself lives in `cc_session_toolkit` (a
separate checkout) and is not pinned by this repository. Fix round 4c on
`claude/audit-round4c`.

### Critical (archive)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| AR1 | `check-archive-drift.py:66` (4,000 prose chars) and `bulk-archive.py:2286-2298` (five turns by default) disagree on "substantive", so a session the gate reports is refused by the archiver at the flags the gate's own remediation line names: a permanent session-start gate | CONFIRMED by repro | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR2 | `bulk-archive.py:479` treats a catalogue id as archived, three lines after logging that it has no metadata on disk, against the docstring and `infrastructure-reference.md:191`; a ghost entry suppresses archiving while the drift check keeps flagging it | CONFIRMED by repro | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR3 | `bulk-archive.py` has no completeness guard (no grace, no size re-check at archive time; `verify` checks existence only; validation never opens a transcript): a transcript copied mid-session is frozen as canonical and every check reports clean | CONFIRMED (absence) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR4 | `backfill-summaries.py:312,466` reach the Anthropic API on the default path with no estimate and no confirmation, against the API review gate every sibling honours | CONFIRMED by reading | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR5 | `backfill-summaries.py:275-285` writes a summary for any id in the model's reply found in the canonical; a hallucinated id overwrites an unrelated memory's summary | CONFIRMED by repro | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART1 | `check-archive-drift.py` has zero tests: reporting zero drift always, or treating every session as trivial, leaves the full suite green; it is the sole tripwire for the failure class of the 77-session gap of 2026-07-28 | CONFIRMED (mutation, full suite) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART2 | `bulk-archive.py:516,535,334` — the incremental skip, the triviality predicate, and the on-disk id set are all unpinned (re-archive everything, or archive nothing, stays green); no test calls `discover_sessions` or any `cmd_*` entry point (ART3: swallowed failures, a blinded `verify`, a truncated catalogue all green) | CONFIRMED (mutation) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART4 | `normalise-archive-storage.py` has zero tests and deletes transcripts: removing the sha256 round-trip verify, or unlinking in the DIVERGENT branch, stays green | CONFIRMED (mutation, full suite) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |

### Medium (archive)

| # | Finding | Disposition |
|---|---|---|
| AR6 | `reprocess-sessions.py:211,520` — selection counts `source == "extraction"` but the writer stamps `"reprocessing"`: not idempotent, re-spends every run, appends byte-identical duplicate ids | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR7 | `reprocess-sessions.py:640` — `custom_id` uses eight hex characters of the session id; a prefix collision mis-attributes or rejects the batch | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR8 | `reprocess-sessions.py:769-773` — `apply BATCH_ID` never checks the state's batch id (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR9 | `normalise-archive-storage.py:166-167,185` — the raw file is unlinked before the meta is repointed, the repoint is a bare write, and a failed run never self-heals | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR10 | `bulk-archive.py:288-291` — a live store with no top-level transcript at scan time is read as a merged snapshot and session directories become projects, silently | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR11 | `reprocess-sessions.py:261-336` — no `isMeta`/`isSidechain` filter although the docstring claims parity with the hook; harness text can become memories | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR12 | `data/logs/bulk-archive-progress.json` is git-tracked and honoured unconditionally, so a checkpoint synced from the other machine skips sessions this machine never archived | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) (re-verify on disk) |
| AR13 | `bulk-archive.py:2152-2159` — `_enrich_apply` replaces `auto_generated` wholesale (drops `three_ps`) and writes non-atomically (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR14 | `bulk-archive.py:737-748` — `archive_subagents` overwrites an existing archive with no temp file (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR15 | `bulk-archive.py:452` — the token counter is built before the toolkit is on `sys.path`, so the preferred `--min-content-tokens` floor is the one that fails to import | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR16 | `bulk-archive.py:2254` — `CATALOG.json` written unlocked and non-atomically; a truncated file crashes the next `discover` at `:472` (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR17 | `push-archives-to-r2.sh:67-70` sources `.env` (shell-executes it, exports every secret to child processes); `rclone copy --s3-disable-checksum` lets a truncated canonical with a newer mtime overwrite the last offsite copy (SUSPECTED, never executed) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| AR18 | One batch-state slot per script (`bulk-archive.py:54`, `reprocess-sessions.py:55`): a second submit before apply destroys the first's map (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART5 | `search-archives-safe.sh:177,132` — the single-run `flock` and the nice/ionice/timeout prefix (the 2026-06-21 hard-lock fix) are untested | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART6 | `push-archives-to-r2.sh:141,116` — dropping `--dry-run` or the mount guard survives; the one test stops at the version probe | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART7 | `_scan_archives.py:91,118` — the per-line truncation (the OOM guard) and the exception tuple are untested | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART8 | `reprocess-sessions.py:235,238,758,285` — the already-extracted skip, the session directory, the rewrite guard, and the partial-last-line handling are all mutable | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART9 | `validate-session-metadata.py` (537 lines) has zero tests; disabling `check_schema` stays green | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART10 | `backfill-summaries.py:241,228` — the line-count invariant and the temp-and-rename are removable; `:234` also writes `ensure_ascii=False` (the round-4a re-audit's M1) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |
| ART11 | `extract-transcript-text.py` and `extraction-prompt-spotcheck.py` have zero tests (SUSPECTED) | fixed in **PR #124** (merged 3360630 after two re-audits; the first refused on six blockers — a session that grew during a copy lands in `failed_ids` and is never retried, so AR3 turns "silently truncated" into "permanently unarchivable"; the checkpoint is written non-atomically and read unguarded; `verify` exits 0 with issues; `rclone copy` to `sync` (which deletes from R2) survives the suite; the normaliser's raw-longer divergent case is uncovered and destructive; the drift gate's fixtures have one project — plus mediums (the during-copy size check unpinned, the corrupt-catalogue branch dead, the catalogue lock unpinned, two divergences from the hook's marker and skip accounting, the raw-only normaliser branch non-atomic, no check that the R2 variables loaded) — all twenty-five closed in round 4c-2 (failed sessions retried and pruned against disk; the checkpoint atomic and self-healing; `verify` exits 1 on any finding; `copy` pinned on both R2 branches; the raw-longer divergent case covered; two project directories in the drift fixture; the reprocess marker and skip accounting match the hook; per-batch state in the backfill; one toolkit path helper); the second re-audit closed all six with mutation-resistant tests and found nothing that can lose an archive; round 4c-3 is **PR #136** (only this run's log bytes classified; a shrunken source refused at archive time because `verify` would compare a truncation against itself; the owed-response cap; a broken checkpoint repaired loudly — an empty `stats` object had been marking every archived session failed; stale temporaries swept by age and excluded from the push; the retry policy decided as no cap, once per window, logged; **merged** after a re-audit that killed every mutation but one — the stale-temporary age threshold is unpinned — and left eight lows: a `.tmp` directory reported as swept, a legacy manifest entry without a size silently disabling the shrink refusal, the no-cap policy absent from `--help`, a pre-existing `rc=$?` that is always zero in the R2 script's transport message, a dry-run failure bypassing its exit-code contract, two loose test windows, one asymmetric exclusion test) |

Lows recorded: AR19 documented `--resume` flag absent; AR20 `setup_logging`
tracebacks on a dangling `logs` symlink; AR21 `_scan_archives` and `verify`
accept different transcript names; AR22 unvalidated path joins from manifest
and catalogue data; AR23 non-atomic gate write and a BOM dropping the first
record; AR24 spot-check glob includes flat agent files; AR25 style; AR26
`data/.gitignore` does not ignore `logs/*.json`, so 95 files including LLM
summaries of private transcripts are tracked in the private submodule
(Shawn's call); AR27 a worktree run takes a different daily-sync lock, so the
guard does not serialise against the live hook; ART12-13 two tautological
tests that cannot fail, one probing the operator's real filesystem; ART14
the cross-machine "largest wins" tie-break unpinned. Cross-file: three
substantive rules; atomicity per author; every script defaults to
`~/cc-archives` except `resolve_session_id` (the rpi share); no fixture
carries the entry shapes production writes (`type`, `isMeta`, `isSidechain`,
`uuid`, tool and thinking blocks). Verified correct: no shell interpolation
of filenames; `search-archives-safe.sh` honours the 2026-06-21 lesson;
`_scan_archives` bounded; the spot-check is dry by default; BOM, CRLF, and
partial lines tolerated by every parser; normalisation verifies a round-trip
before unlinking; the R2 push never deletes.

## Tranche 5 — external services and machine glue (both lenses, 2026-09-08 night)

Scope: `zotero.py`, `add-doi-to-zotero.py`, `lit-scout-zotero-import.py`,
`lit-search.py`, `review-paper-prepass.py`, `_http_retry.py`,
`_openai_key.py`, `llm-use-inventory.py`, `publish-dashboard.py`,
`ollama-endpoint.sh`, `syncthing-health.sh`, `syncthing-bind-heal.sh`,
`env-fingerprint.sh`, `sync-symlinks.sh`, `compose-global-claude-md.sh`, and
their tests. Lens A: 1 critical, 10 medium, 13 low. Lens B: 26 mutations, 26
survived (eleven applied at once still pass the full suite); 5 critical,
10 medium. Fix round 4d on `claude/audit-round4d`.

### Critical (external)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| E1 | `lit-scout-zotero-import.py:894` — the only duplicate guard on both Zotero write paths is an exact DOI match with no URL or scheme normalisation, while `zotero.py:328-372` normalises; an item stored as `https://doi.org/…` (the connector's form) is invisible, so `--live` imports and `add-doi-to-zotero.py` create duplicates and the latter's safety claim is false | CONFIRMED by repro | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET1 | `lit-scout-zotero-import.py:1341-1560` — the whole write path is untested: always-create, publish-on-dry-run, wrong collection, no credential check, read-write SQLite, and no manifest idempotency each stay green | CONFIRMED (mutation) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET2 | `publish-dashboard.py:540` — `main()` is never invoked: publish without `--publish`, without a token or canvas id, a failed Slack call reporting success, an empty dashboard published, and a repointed API host all stay green | CONFIRMED (mutation) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET3 | `zotero.py:70` — the read-only (`immutable=1`) promise is untested because every test replaces `_connect`; a read-write open of the live Zotero database stays green | CONFIRMED (mutation) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET4 | `lit-search.py:262,395` — per-host pacing and `Retry-After` handling are deletable (the suite pays the pacing cost without asserting it) | CONFIRMED (mutation) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET5 | `sync-symlinks.sh:61-75` — `prune_stale_symlinks`, the only `rm` in the tranche, has zero coverage: `-L` to `-e` and `rm` to `rm -rf` stay green and would together delete real directories under `~/.claude` | CONFIRMED (mutation) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |

### Medium (external)

| # | Finding | Disposition |
|---|---|---|
| E2 | `lit-scout-zotero-import.py:463-477` — `.env` loader keeps surrounding quotes and mis-parses `export` lines; `env-fingerprint.sh` reports the same file healthy | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E3 | `lit-search.py:203` — the Semantic Scholar key is set client-wide and sent to CrossRef, OpenAlex, and DataCite, against the rule the docstring above it states | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E4 | `lit-scout-zotero-import.py:1117` — CrossRef `date-parts: [[null]]` writes the literal string "None" as the Zotero date | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E5 | `lit-scout-zotero-import.py:1099` — the title is written with HTML intact while the abstract is stripped | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E6 | `add-doi-to-zotero.py:139` — reads only the retirement-candidate key; breaks when it is revoked (SUSPECTED) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E7 | `publish-dashboard.py:479` — the bearer token follows redirects to any host (stdlib redirect handler) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E8 | `lit-scout-zotero-import.py:1277` — `ensure_subcollection` reads one unpaginated page, so a same-named twin is created once the staging collection grows (SUSPECTED) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E9 | `sync-symlinks.sh:243` — `pip install --upgrade -r requirements.txt` runs unattended at session start whenever one probe import is missing (SUSPECTED) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E10 | `sync-symlinks.sh:133` — `git submodule update --init --recursive` at every session start detaches an initialised `data/` and can orphan a concurrent session's commits (SUSPECTED) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| E11 | `compose-global-claude-md.sh:25-30` — sources from the script's tree, target from `$HOME`: run from a worktree it overwrites the live global instructions with the branch's content | CONFIRMED in sandbox; fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET6-7 | `_http_retry.py:249,265` — the timeout kwarg and the exception tuple are mutable unnoticed | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET8-10 | `compose-global-claude-md.sh:85,78,117` — `--dry-run` writing, layer order, and a write to a Sol-owned surface all stay green | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET11 | `sync-symlinks.sh:120` — the "real file, leave it" branch untested | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET12 | `zotero.py:397,406` — `_normalise_doi` and `find_by_doi` have no test anywhere (a prior silent-failure defect is recorded in `wiki/working-notes.md:577`) | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET13 | `lit-scout-zotero-import.py:1271` — subcollection idempotency untested | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET14 | `env-fingerprint.sh` — zero tests for the one script whose purpose is handling secrets safely | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |
| ET15 | `syncthing-bind-heal.sh:43-46` — the precondition before `docker compose up --force-recreate` is untested | fixed in **PR #125** (merged after two re-audits; the first refused because the Syncthing peer-absence check had regressed to permanently green and the fingerprint salt travelled in argv, both fixed in round 4d-2 along with the composer's `--target` bypass, a live-root guard for the symlink script, the submodule gate, and a SQLite `TRIM` divergence; an absent live root in the composer warns rather than refuses — accepted, since the script lives inside the checkout in production; round 4d-3 is **PR #133** (merged 96650de after one re-audit; round 4d-4 fixes the one regression it found — the `--allow-worktree` flag was treated as "is a worktree", so a plain clone run with it skipped the init and half-migrated `~/.claude` — plus a remedy message naming a command git refuses, a fixture that never gives the script a `.git` directory, and six lows) |

Lows recorded: E12 dead "n.d." default; E13 only the exact `--dry-run`
spelling is safe; E14 POST retried without an idempotency rule; E15
`--simulate-need` breaks "always exits 0"; E16 shell and Python
interpolation in `syncthing-health.sh`; E17 guard anchors escape the repo;
E18 BibTeX key collisions; E19 organisation authors dropped; E20 the Ollama
endpoint producer's failure signal is discarded by its own idiom; E21
`--project` escapes the root; E22 stderr comment; E23 the fingerprint salt
is a public constant and the output includes the exact length, so a
low-entropy value is recoverable by sweep (a value oracle); E24 URI slashes
and encoding; ET16-19 Ollama, backoff, three untested scripts, and the
Syncthing health script used only as a fixture. Cross-file: the fingerprint
tool and the loader disagree on quoting; two DOI normalisers with the
weaker on the write path; three `Retry-After` parsers; two HTML policies in
one function. Verified correct: no key value reaches any message, log, or
report; no script writes the Zotero database (every open is immutable);
the dashboard never re-posts after a timeout; timeouts and bounded waits in
the retry helper; the symlink pruner cannot follow a link into `data/`;
the composer is atomic and never touches a Sol-owned surface; no host is
rebooted, restarted, or unmounted except a local docker recreate behind
three preconditions.

## Tranche 6 — bake-off and style tooling (both lenses, 2026-09-09 early)

Scope: `bake-off-metadata.py`, `resample-bake-off-manifest.py`,
`analyse-wiki-vocabulary.py`, the two `corpus-style-analyser` agent
definitions, and the path defaults of four `scripts/style-analyser/`
scripts. No tests exist for any of the three scripts. Lens A: 1 critical,
14 medium, 10 low. Lens B: 3 damaging mutations, all green; 4 critical,
5 medium, plus a minimum-suite specification. Fix round 4e on
`claude/audit-round4e`. The remaining fourteen files under
`scripts/style-analyser/` are a later tranche.

### Critical (bake-off)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| AS1 | `bake-off-metadata.py:1126` — `--build-rubric` replaces a literal marker pair, so on an already-populated rubric (or any separation between the markers) the body is left as it was while the blind key is regenerated from the current arms; every blinded score then decodes to the wrong model, and "Wrote populated rubric" prints either way | CONFIRMED by repro | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AST1 | Same site from the test side: a template with one blank line between the markers produced a five-line empty rubric, exit 0, with a fully populated key beside it | CONFIRMED by repro | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AST2 | `resample-bake-off-manifest.py:550-564` — dedup keeps the LIVE copy (the sort key puts `~/.claude/…` before `~/cc-archives/…`), inverting the comment's stated preference; every dual-resident session loses its meta and drops out of both tiers | CONFIRMED | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AST3 | `resample-bake-off-manifest.py:52-57,518` — hard-coded absolute path to the live manifest, no arguments, no dry run, unconditional non-atomic overwrite: any invocation, from any copy, destroys the manifest the committed responses were generated against (Lens A AS4) | CONFIRMED | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AST4 | The hermeticity guard does not watch `reports/` or `wiki/`: an analyser that writes into the public tree stays green | CONFIRMED (mutation) | round 4a-2 (guard widening) |

### Medium (bake-off)

| # | Finding | Disposition |
|---|---|---|
| AS2 | `bake-off-metadata.py:1054` — a fifth arm is silently dropped from rubric and key; the blinding is reverse-only (two permutations, not twenty-four) | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS3 | `bake-off-metadata.py:112-113` — Sonnet prices the comment says went stale on 1 Sep 2026; estimates under-count by a third | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS5 | `resample-bake-off-manifest.py:470,487` — `generated_at` from the clock, so the same seed is not byte-reproducible | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS6 | `bake-off-metadata.py:293,472` — `custom_id` uses eight characters of the session id and the map collapses duplicates (sub-agent ids share long prefixes): one session's output written under another's id | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS7 | `bake-off-metadata.py:1263-1278` — the live prompt names no model, count, mode, or cost, and `--yes` skips it; the API review gate is not presented | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS8 | `bake-off-metadata.py:1251` — `--haiku-apply` reaches the API before the confirmation block (free retrieval; the launch plan claims otherwise) | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) (document) |
| AS9 | `bake-off-metadata.py:668,826,922` — bare response writes; a re-run overwrites a complete response with an error object; usage replaced wholesale | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS10 | `analyse-wiki-vocabulary.py:191,196,149` — empty or undated corpus and non-string tags crash `/weekly-review` step 5b | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS11-13 | `agents/corpus-style-analyser-v2.md:657,765-767,574` — Safeguard 5 names the wrong section (§9 for §11); the "correct" mean sentence length contradicts the file's own appendix and the results JSON (21.45 and 1.605 for the colon rate — both re-read from `data/style-corpus/phase1-results-clean.json` by the coordinator on 2026-09-09); Steps 1-2 require a tmpfs manifest with no regeneration path while a durable one exists | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS14 | `scripts/style-analyser/phase3_promotion.py:38-39` and three siblings — relative output paths with no override, so the documented invocations write into the wrong tree from any other cwd | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AS15 | `bake-off-metadata.py:1,482` — the shebang and the printed recovery command use the system interpreter, which lacks the toolkit and the clients | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |
| AST5-9 | Fifth-arm truncation, empty-manifest crash after the cost file is written, silent under-filled strata, two-permutation blinding, `.env` hydrated before the dry-run branch | fixed in **PR #126** (merged 81eb4d3); round 4e-2 is **PR #131** (merged after one re-audit: no second billed batch, refusal exits 3, the pinned properties; round 4e-3 is **PR #134** (`--resubmit` makes the top-up reachable while `--force` keeps its meaning; a real double-count of empty-content results found and fixed; the re-audit verified all six commits but found the pinned recovery line does not run as printed — two required flags are missing from it — and that a top-up replaces the batch's id map so a superseded batch's paid results become unreachable — both fixed in round 4e-4 (the printed line is parsed by the real argument parser in a test; the id map accumulates across top-ups; every named mutation killed; the tree snapshot walks `.git`); **merged** after the second re-audit — lows left: the printed recovery line breaks on an out-dir containing a space (no `shlex.quote`), the two `and` fences unpinned for the one-of-two-flags case, `n_requests` unpinned after a top-up, watching `.git` adds a flake surface in the main clone only, an old-format state file skips a superseded batch's results with a message that names a custom id and suggests nothing) |

Lows recorded: AS16 chars-over-four token heuristic (recorded as
authoritative); AS17-19 docstrings out of date (two arms, thinking budget,
100-token floor); AS20 under-filled stratum silent; AS21-22 status
vocabulary and counts in the agent definitions ("fifth status" of six,
"five scripts" of fourteen, "§§1-8" after the relayout); AS23 no NFC
normalisation; AS24 empty manifest; AS25 the committed manifest predates
the committed writer (bare-date `generated_at`); AST10-14 crashes,
strip/lower asymmetry, `EOFError` on closed stdin, two clock reads, the
out-of-repo extractor unpinned. Cross-file: v1 and v2 definitions disagree
on section count, status vocabulary, and pipeline; v2 contradicts itself on
reconciliation; response-to-manifest provenance is one-directional (no
model id, prompt hash, or manifest hash beside the responses). Verified
correct: no output lands in the public tree; nothing here writes the
memory store; no network call outside `bake-off-metadata.py`; no session
sampled twice; no US spellings.

## Tranche 7 — memory readers, reports, and anchors (Lens A, 2026-09-09; Lens B running)

Scope: `memory-health-report.py`, `drift-sweep.py`, `anchor_verify.py`,
`triage_anchors.py`, `audit-postgres-sync.py`, and the commands that invoke
them. Lens A: 3 critical, 7 medium, 8 low. Lens B: 68 mutations, 39
survived; five criticals of its own — the Postgres reconciliation engine
and the health report's entry points are unreached by any test (an inverted
set difference, a hard-coded table, and an injected DELETE all pass the
full suite), and the repository discovery resolves from the home directory
so a worktree run verifies against the wrong repositories. Fix round 4f on
`claude/audit-round4f`: `--literal-pathspecs` and a magic gate in the
verifier; transient failures are "pending" and never lower confidence;
recovery scoped to the memory's own project (`--allow-cross-repo` to
override); the audit compares row fingerprints and refuses writes through
a SQL-evaluating fake; the health report drives its entry points, filters
`is_active`, counts only verifiable anchors, and treats an unreadable
quarantine file as UNKNOWN; the sweep refuses a degraded repository set and
fails when a trend row is lost; one repository discovery shared with
`project_id`. Recorded for Shawn: AN15 (a rule for absolute anchors); the
conftest watch list additions; unifying the two fake-Postgres helpers.
Live consequence: the first `audit-postgres-sync` run after merge will
likely exit 1 on the live store (every record edited by `/update`,
`/forget`, or anchor recovery diverges from Postgres under the insert-only
sync), and fifteen glob-referenced anchors re-verify false.

### Critical (anchors)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| AN1 | `anchor_verify.py:98-106` — `git log --all -- <ref>` runs without `--literal-pathspecs`, so a file reference with glob characters is matched as a pattern and a junk anchor verifies true (then `confidence: high`); fifteen live records carry such a reference | CONFIRMED by repro | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN2 | `anchor_verify.py:195-222` with `triage_anchors.py:50-88` — the recovery index pools every repository's file list into one namespace, so a dead path in project A "recovers" to a same-suffix file in project B, verifies true, and `recover_anchors.py:131-155` writes the foreign reference into the corpus | CONFIRMED by repro | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN3 | `anchor_verify.py:93-95,109-110,258-259` — a missing `git`, an unreadable repository, or an unmounted mount returns "false", never "pending", against the module contract at `:32-35`; the drift sweep then logs a permanent bogus failure spike and `recover_anchors` rewrites `verified` and `confidence` from it | CONFIRMED by repro | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |

### Medium (readers)

| # | Finding | Disposition |
|---|---|---|
| AN4 | `memory-health-report.py:721` reaches `audit-postgres-sync.py:246-250`, which `sys.exit(2)`s on a schema mismatch inside a library function, so a schema bump kills `/memory-health` with no report although most sections need no Postgres | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN5 | `memory-health-report.py:197-224` — "anchored" counts records whose anchors are all of unknown type (103 live), overstating verifiable coverage; a string-valued `anchors` iterates per character | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN6 | `drift-sweep.py:69-86` — a record with a missing or unparseable `created_at` is silently excluded from the "never ages out" back-set | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN7 | `drift-sweep.py:79-86` — no floor on the repository set: a degraded set (other machine, unmounted repo) makes every anchor false and appends the fabricated spike to the append-only trend log | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN8 | `memory-health-report.py:63,490-503` — an unreadable quarantine file becomes a count of zero and an overall PASS; the quarantine path is the one constant without the symlink fallback | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN9 | `audit-postgres-sync.py:139-168,282-291` — the audit compares id sets only, so divergent content, duplicate lines collapsed to one id, and Postgres-only orphans all read "clean" although content divergence is the sync's expected failure mode | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |
| AN10 | `drift-sweep.py:83-85`, `memory-health-report.py:771-773` — unmemoised resolvers: one unresolvable reference costs up to 72 git spawns, repeated per duplicate across 5,537 anchored records (SUSPECTED) | **PR #129** (`claude/audit-round4f`; re-audit refused on four small items — the drift sweep's repository floor is a one-way ratchet with no override and the worktree's own discovery counts one more repository than the live checkout's; `--tier-c` in the health report tracebacks on empty discovery instead of degrading; one new line uses the identity test the shared soft-delete predicate exists to abolish; a false sentence about the anchored gap — plus mediums (the statement timeout set after the schema query and its value unpinned; the audit fake's view semantics differ from the schema; one broken repository makes every absent reference pending corpus-wide) and eleven surviving mutations — all closed in round 4f-3 (a discovery-only repository count with `--min-repos`; tier C degrades instead of tracebacking; the shared predicate; a broken repository is excluded after one warning rather than making every absent reference pending; the timeout first and its value pinned; short commit references pending, never stripped; the ten live-corpus values in the anchor test fixture scrubbed); **merged 31b585c** after a second re-audit that reproduced every fix; round 4f-4 takes its follow-ups: a degraded discovery whose only repository is the running checkout still sweeps and logs a fabricated row with zero repositories, excluded repositories are not reported, an excluded repository's own anchors read false rather than pending, a transient error excludes a repository for the whole process) |

Lows recorded: AN11 `..` escapes the repository in the existence check; AN12
four-character hex accepted as a commit reference across 36 repositories;
AN13 the two surfaced-log readers still ignore `PA_SURFACED_LOG`; AN14 four
schema-dependent queries before any schema check, no statement timeout; AN15
659 absolute or tilde-rooted anchors have no recovery path; AN16 no
`is_active` filter in any report section; AN17 top-five surfaced ids without
a corpus membership check; AN18 the trend appender swallows every exception.
Cross-file: three definitions of a line (the sync's is being unified on PR
#123); `--literal-pathspecs` passed to `git add` and `git commit` in
`recover_anchors` but not to the verifier's `git log`; two independently
maintained repository sets that are identical today. Verified correct: no
shell, every git call an argv list; empty-corpus arithmetic guarded; exactly
one write site (the trend log); reports emit ids and counts only; UK
spelling.

## Tranche 8 — style-analyser scripts (Lens A, 2026-09-09; Lens B running)

Scope: the fourteen scripts under `scripts/style-analyser/`. Lens A:
5 critical, 10 medium, 18 low; Lens B: zero tests, seven damaging mutations
all green, four criticals of its own (a self-including "held-out" sanity
check; the blinding key inside the judge's directory; an empty corpus is a
traceback; the verifier skips most claims and never checks per-1k rates)
plus the missing-dependency finding (numpy, scipy, scikit-learn, spaCy are
absent from the venv, so four modules cannot import). No external call exists
in any of them. Fix round 4g on `claude/audit-round4g`: judge answers scored
honestly (ties and refusals are `unusable`, pairs collapsed, exact binomial),
the key moved outside the judge directory with randomised sides, the
verifier verifies (feature-to-metric map, per-1k checks, UNVERIFIED rows),
hapax over types and passive per sentence as documented, atomic writes and
`--dry-run` on every writer with a provenance block, validators pointed at
the live corpus, 239 tests. Recorded for Shawn: the dependency additions to
`requirements.txt`; the nominalisation stop-list (ST24); the length-matched
gate (ST30); the generator-side provenance sidecar. Live consequence: every
published figure derived from hapax, passive, nominalisation, short-text
MATTR, or announcement colons changes definition, so phase 1 must be re-run
and the guide's numbers re-derived before the verifier passes again.

### Critical (style analyser)

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| ST1 | `efficacy_score_judges.py:54` — any judge choice that is not the guide's side (a tie, a refusal, an empty string) is scored as a baseline win, biasing the headline result by the number of unusable judgements | CONFIRMED by repro | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST2 | `efficacy_score_judges.py:47` — judgements parsed with a bare `json.loads`: a fenced or prose reply aborts, an empty file divides by zero, a duplicated pair id counts twice, a missing pair is silently dropped | CONFIRMED by repro | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST3 | `efficacy_build_judge_tasks.py:129` — the unblinding key is written into the directory handed to the judge; pair ids also encode the key deterministically and each pair is emitted twice as identical files | CONFIRMED | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST4 | `phase3_guide_verifier.py:394-403` — the count-over-words confabulation check matches the claimed number against any integer in the aggregate, so a figure attached to the wrong feature passes | CONFIRMED by repro | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST5 | `phase1_pipeline.py:303-308` — hapax ratio divides by tokens while its docstring and the efficacy reference define it over types; the published figure is a different measure with a larger length artefact | CONFIRMED by repro | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |

### Medium (style analyser)

| # | Finding | Disposition |
|---|---|---|
| ST6 | `phase3_guide_verifier.py:294-337` — an incidental word ("lower", "range") in the snippet downgrades a numeric FAIL to WARN | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST7 | `phase3_guide_verifier.py:196,417-426` — any eight-character upper-case token is treated as a Zotero key, producing spurious FAILs | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST8 | `phase1_pipeline.py:383-396` — passive counted per verb (ratio above one possible) where the definition says presence per sentence | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST9 | `phase1_pipeline.py:397` — nominalisation per 1k words uses a punctuation-inclusive denominator unlike every other per-1k rate | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST10 | `efficacy_build_reference.py:137,146` — windows measured before citation stripping land about a seventh short of the length they are matched to | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST11 | `phase5_evaluator.py:948,1002-1012` — the "held-out real" sanity fixture is scored against a fit that includes itself (SUSPECTED) | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST12 | `phase5_evaluator.py:1019-1021` — the sanity footer can say PASS over a table showing a fixture that is not farther | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST13 | `efficacy_score_judges.py:36-39,83-89` — counterbalanced orders counted as independent trials, no test or interval, and the provenance line hard-coded | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST14 | Both validators read a stale `/tmp` corpus layout: one crashes, the other silently reports zero examples, so neither precision estimate can be re-derived | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |
| ST15 | `phase1_pipeline.py:106-148` — a body line beginning "References" in the last third truncates the document, including already-clean text | **PR #128** (`claude/audit-round4g`; re-audit called the round strong but refused on five items — the MATTR fix crashes phase 5 on any input under 100 words; a legacy judge key collapses every judgement into one group and renders a null result as a finished analysis; the announcement validator's default results path does not exist; the live phase-1 results predate the metric redefinitions with no version stamp, so new-definition inputs would be scored against an old-definition corpus; the agent definition still names the old manifest path — round 4g-2 done — the metric-schema stamp every phase-1 consumer checks, the impute for unmeasurable features, refusal of an unidentifiable judge key, the shared results-file default, the key under `private/`, provenance bound to its own repository, and the fixture stamping that two round 4e-2 tests needed after the merge; the second re-audit reproduced the interlock end to end but refused on one two-line mismatch — the scorer's default key directory still names the old location, so a freshly built or migrated experiment is unscoreable at the defaults — with follow-ups (the announcement validator is a sixth phase-1 consumer with no stamp check; phase 5 and the efficacy scorer check phase 1's stamp but not phase 3's; the migrate-key guard untested); round 4g-3 running) |

Lows recorded: ST16-ST33 (indentation collapsed in the injected guide;
citation stripping mismatches its docstring; curly quotes and a numeric
colon case; no NFC normalisation; MATTR silently becomes TTR under 100
words; "exclude" matches "not excluded"; cross-paragraph exemplar splicing;
documented counts wrong; suffix scan false positives; a length mismatch
disarms the promotion guard; always-positive metrics auto-promote; excluded
topics enter the feature profile; dead code and an unreachable allow-list;
absolute thresholds on short passages; a re-run deletes collected
judgements; the manifest written a level up; sentence filters that exclude
words from one denominator but not another). Cross-file: three definitions
of "passive" and two of "announcement colon"; no atomic write in twenty-odd
output paths; no provenance (no hash, commit, model version, judge model,
or prompt hash) in any output. Verified correct: MATTR windows; genuine
leave-one-out; zero-variance guard; the exact sign-flip test; pairing by
topic; deterministic ordering; no shell, eval, pickle, or YAML; no `.env`.

## State at 2026-09-09 08:00 (resume point)

Merged from this audit (thirty-seven PRs): #114, #115, #116, #117, #118
(round two); #119 (daily sync, four re-audit rounds); #120 (round 3b);
#121, #123 (memory-store writers and the hermeticity guards); #122, #130
(retrieval); #124 (session archive pipeline); #125, #133 (external services
and glue); #138, #149 (machine glue, two re-audits each); #126, #131, #134
(bake-off tooling); #127, #137 (concurrency-
tolerant guard, midnight flake, hermeticity follow-ups); #143
(hermeticity round 4a-6); #155 (hermeticity round 4a-7/8, the audit
hook); #129, #140, #145, #152
(memory readers and anchors); #132, #135, #139, #148, #153 (daily-sync
lows);
#136, #141, #147
(archive follow-ups); #128, #144, #151 (style-analyser scripts, three re-audits,
then one, then two);
#142, #146, #150, #154, #156 (bake-off rounds 4e-5 to 4e-9).

Open, each with its verdict so far:

- **#128** (style-analyser scripts, round 4g): refused twice, the second
  time on one two-line mismatch (`efficacy_score_judges.py` defaults
  `--key-dir` to the old location). Round 4g-3 delivered 2026-09-09 10:27:
  the key location fixed and exercised (build → answer → score at the
  defaults), `validate_announce_colon.py` made the sixth interlock
  consumer, phase 3's stamp checked by the phase-5 evaluator and the
  efficacy scorer, `--migrate-key` isolation, the version-less stamp, the
  untracked-files `dirty` case, and the error marker now cleared only after
  the bundle's outputs exist (seven commits 916e223-33a5159; clean-copy
  suite 4009 passed, exit 0). Merged with main and pushed as 6330be4
  (coordinator suite 4228 passed, 2 skipped, 19 deselected, exit 0).
  Third re-audit verdict merge: the key location fixed at the constant,
  every fix survived its worst single-line mutation, the six consumers
  confirmed exactly six. **Merged 7ee29c9** 2026-09-09 12:0x. LIVE NOW:
  the re-auditor verified at source that
  `data/style-corpus/phase1-results-clean.json` carries no `metric_schema`,
  so all six consumers exit 2 until `phase1_pipeline.py --clean-corpus`,
  then `phase3_promotion.py`, then the downstream stages are re-run
  (operator action 1); and the live experiment has neither key directory,
  so the scorer takes the legacy fallback and warns until `--migrate-key`
  is run (intended). Follow-ups are round 4g-4 (`claude/audit-round4g-4`):
  the phase-3 stamp checks pinned by membership not position (moving
  either check below the consuming load survives); the two end-to-end
  judge tests monkeypatch both defaults so only the constant test catches
  a reverted default; `provenance_block` never passes a path hint so its
  tracked-ness branch is unreachable; bundle atomicity is per-file (an
  interruption on a never-failed paper leaves no marker). Round 4g-4
  delivered (325d5a1-2a9034e): the stamp checks pinned by position; the
  judge layout described once in `style_support` with both scripts'
  defaults derived at call time (the round 4g-3 report's "exercised, not
  just asserted" claim corrected); `provenance_block` records the calling
  script; an `extraction-incomplete.txt` marker written before any bundle
  output and removed after the last. Merged with main (b071f4d),
  coordinator suite 4318 passed, 2 skipped, 19 deselected, exit 0;
  **PR #144, merged 1375fee** 2026-09-09 13:4x: the re-audit confirmed
  both named moves fail and every path byte-identical at the defaults,
  and found two gaps in the guard rather than the code — the BUILDER's
  argparse defaults are still unguarded (the round trips hand the writer
  explicit directories, so reverting the builder's defaults reopens L2
  through the CLI with all 26 tests green), and "line precedes" is a
  proxy that a nested helper, an environment gate, or a `[:0]` on the
  iterable defeats (nothing in either numpy-bound script executes in this
  venv, so the AST tests ARE the interlock). The round 4g-4 report's
  claim that reverting the scorer constant fails the round trips is
  wrong (only the constant test fails; reverting the scorer's argparse
  default fails the round trips and not the constant test) — corrected
  in round 4g-5. Follow-ups are round 4g-5 (`claude/audit-round4g-5`):
  exercise the builder at its defaults; a runtime stamp-check-then-load
  helper both mains call first (or a stated structural-untestability
  note); the exception failure return's marker removal and the marker's
  content untested; the "one base" moves only the judge paths (passages
  and five other scripts still hard-code the experiment root); a caller
  without `__file__` falls back silently to `style_support`'s own state;
  the explicit-path test is vacuous in an export; nothing consumes either
  marker (the style-analyser agent definition still reads a partial
  bundle silently). Round 4g-5 delivered (4d5d314-3fd442f), correction
  first (the agent re-ran both mutations one line at a time and confirmed
  the re-auditor's account): `style_support.load_checked_payloads` makes
  the stamp check a runtime guarantee (no payload is returned on any
  failure; both mains call it first; the AST assertions reduced to
  "called once, given every input, before any consumer"); the builder
  run at its own defaults; the crashing-extractor path and the marker's
  content tested; one experiment root derived in all six scripts with
  `passages_dir()`; a caller without `__file__` records a note; the
  explicit-path test builds its own repository; `extract_corpus` warns on
  leftover markers and the agent definition skips marked bundles.
  Merged with main (7f146ad), coordinator suite 4431 passed, 2 skipped,
  19 deselected, exit 0; **PR #151**. Re-audit verdict **do not merge**
  — C1: `efficacy_score.py:105-109` discards the loader's return and
  builds its list with a conditional comprehension, then
  `load_corpus_space` re-reads all three files, so the scorer is still
  check-then-reload and the one-word mutation `is not None` → `is None`
  skips every stamp check with 183 passed (the PR #144 finding
  re-entered; phase 5 is genuinely by construction). M1: the phase-5
  "both inputs" assertion was deleted and not replaced (`[args.phase1,
  args.phase1]` survives). M2: four of the five root-derivation
  assertions compare values, so a reverted literal survives. Lows: dead
  `EXP`/`PASSAGES`/`REPO_ROOT`; one remaining layout literal; the agent
  document's example command lacks two required flags; no test ties the
  marker names in the document to the code. **DEFERRED** (stop point
  2026-09-09 15:5x): the fix is two lines in the scorer (feed the
  returned payloads into `load_corpus_space`, an explicit list, an AST
  non-emptiness assertion) plus the phase-5 argument-set assertion; PR
  #151 stays open on `claude/audit-round4g-5` in the 4g worktree.
  Resumed 2026-09-10: round 4g-6 delivered (46a93b9, f53f10e): the scorer
  hands the loader an explicit three-element list, unpacks the payloads,
  and feeds them to `load_corpus_space` (signature now takes payloads;
  `load_json` gone from the module); the phase-5 argument set restored;
  derivation checked structurally for all nine constants across six
  scripts; dead constants removed; the last layout literal derived; the
  agent document's example completed with a doc-to-code test; the
  newer-than-code stamp wording corrected. Coordinator suite 4492
  passed, 19 deselected, exit 0 (the numpy skips gone now the stack is
  installed); pushed. Second re-audit verdict merge — C1 closed at
  runtime (phase 3 unstamped → exit 2 before any spaCy load; a
  comprehension is no longer possible; the re-read-by-comprehension
  mutation fails both new tests); the six consumers now accept the live
  stamped files. **Merged 2026-09-10.** DEFERRED follow-ups: the
  derivation check is a shape check (a hard-coded base passed to the
  helper passes; correct indirection through a constant fails); the
  "no re-read" guarantee rests on the `payloads` unpack plus a substring
  scan for `load_json` (a re-read spelled `json.loads(...read_text())`
  added after the unpack survives, in both scripts); the doc-example
  regex crosses fence boundaries (an earlier bash block in the document
  would break the test); the example's path values unchecked; the
  argument order into `load_corpus_space` unpinned (fail-loud at
  runtime); nested `add_argument` calls not recovered.
- **#134** (bake-off follow-ups, rounds 4e-3/4e-4): **merged** 2026-09-09 08:3x;
  five lows recorded in the tranche 6 section.
- **#136** (archive follow-ups, round 4c-3): **merged** 2026-09-09 08:2x; its
  eight lows are recorded in the tranche 4 section for a later round.
- **#137** (hermeticity follow-ups, round 4a-5): **merged 927cff1**
  2026-09-09 10:4x. The re-audit's strict run against a populated synthetic
  store (five records, four tags, two `.log` files) passed with the store
  byte-identical and no banner; nothing blocking. Its follow-ups are round
  4a-6 (`claude/audit-round4a-6`): the `_DEFERRED_REPORT` queue is
  unguarded (a test that forgets `isolated_report` makes the summary cry
  wolf, nothing fails); advisory mode accepts an unterminated garbage
  fragment (`_line_problem` never runs on the partial); STRICT does not
  catch a well-formed append (the documented allowance at
  `commands/audit.md:176-180`, to be stated as a limit); new directories
  and `.json`/`.jsonl` files under `logs/` are violations although the real
  `data/logs/` holds both; the tolerated-entry wording; dead `_under_logs`;
  `.xz`/`.Z` and the missing-directory banner clause unpinned. Round 4a-6
  delivered (9a60123): `isolated_report` autouse with a session-level net;
  an unterminated tail judged by `_line_problem` (a truncated JSON record
  is now a violation in both modes); the well-formed-append allowance
  documented in `commands/audit.md` and the conftest as a limit, with the
  three rejected ways of closing it recorded in the round report; new
  `.json`/`.jsonl` files and directories under `logs/` tolerated advisory
  only; entries labelled by kind; `_under_logs` load-bearing; all
  survivors killed. Its clean-copy run with a populated synthetic store:
  3951 passed, exit 0, no banner, store byte-identical. Merged with main
  (7741d84), coordinator suite 3952 passed, exit 0; **PR #143, merged
  85f0593** 2026-09-09 13:0x: the re-audit found the M1 documentation
  accurate and all four real-state runs (strict with a populated store,
  advisory with a live append, strict with a truncated append, worktree
  with the real HOME) behaving as specified. Its follow-ups are round
  4a-7 (`claude/audit-round4a-7`): the tolerated-kind label's call site
  is untested (a literal survives the full suite); `isolated_report` is
  function-scoped, so a session-scoped fixture still pollutes the queue,
  and the "session-level net" is vacuous (the autouse isolation empties
  the queue it inspects); M2 narrowed advisory tolerance to the one
  mid-write state a single `os.write` almost never produces (a truncated
  JSON tail is now a violation even in advisory mode); three false
  sentences in the new documentation; a new directory under `logs/` falls
  through to the ambiguous label; dead code in the suffix arm; the STRICT
  note calls a fatal item "tolerated". The re-auditor also proposed
  closing M1 (the well-formed-append hole) with `sys.addaudithook` on
  in-process opens of the canonical paths — under-detection only, never a
  false failure — which round 4a-7 is to prototype and measure. Round
  4a-7 delivered (bce57d2, dddae66): the label's call site pinned by two
  classes through the terminal; the leak net moved into
  `pytest_sessionfinish` (runs after every fixture of every scope; a queue
  entry under the basetemp is dropped, reported, and fails the session;
  the vacuous test deleted, three nested tests replace it); an
  unterminated tail judged structurally (a JSON-object prefix is
  in-progress, garbage a violation; STRICT fatal for both; the false
  docstring corrected); the three false sentences corrected; a directory
  labelled as one; two dead branches deleted; the STRICT note reworded.
  The audit-hook proposal was prototyped, measured (no detectable
  overhead: 179.5 s against 185.3 s), and **shipped**: `sys.addaudithook`
  on `open` events for the resolved canonical paths in a write or append
  mode, resolving via `os.fspath` (a `PosixPath` from `Path.open`) and
  consulting flags as well as mode (`os.open` passes `mode=None`);
  advisory names the test, STRICT fails the run; under-detection only (a
  subprocess or C-level write evades) so it cannot fail a live checkout
  falsely. Four runs: clean copy with a populated store under STRICT 4364
  passed, no banner, store byte-identical; advisory with an
  out-of-process well-formed append passed with the note and the hook
  silent; STRICT with a truncated append exit 1; worktree with the real
  HOME 4351 passed (a first attempt failed with 338 `test_zotero` errors
  under concurrent suite load and passed on re-run — the round 4a-3
  transient). Merged with main (72177ca), coordinator suite 4504 passed,
  2 skipped, 19 deselected, exit 0; **PR #155**. Re-audit (2026-09-10)
  verdict **do not merge** — C1: the hook compares the RAW path the
  `open` event carries against a set of RESOLVED paths, and the
  canonical files are the symlink paths `memories/...` that every
  production module uses, so an append through the symlink is silent
  under STRICT (reproduced; the `resolve()` mutation survives all 172
  tests because the nested store has no symlink). M2: the recorded root
  cause of the first prototype's failure (a `PosixPath` reaching the
  event) is false on Python 3.13 — the event always carries `str`. M1:
  the `store_writes` advisory still says "Set PA_HERMETICITY_STRICT=1"
  when it is set. The cost is +1.6 % (+0.45 µs per `open`), not
  "none". Everything else (leak net in `pytest_sessionfinish`, the
  structural tail, labels, wording, the never-raises guard, no arming
  without a store) verified. Round 4a-8 (closing): realpath before the
  set test with a basename pre-filter, a symlinked-store nested case,
  the false narrative corrected, the advisory branched, the cost stated;
  then a narrow re-audit of that hunk. Round 4a-8 delivered (398290a):
  a basename pre-filter then `os.path.realpath` (follows the symlink,
  anchors a relative path against the cwd at event time); a nested store
  laid out as the repository is (`memories -> data/memories`) with the
  append made through the symlink, a relative open after `chdir`, a
  silent read, and a test that `realpath` is not called for a
  non-matching name; the false PosixPath narrative replaced by the true
  cause (C1 itself) in both places; the advisory branched under STRICT;
  the cost stated as +2.5 s per run and about 0.5 µs per open; a red
  "EXIT STATUS 1" line before pytest's green summary on a queue leak
  (the summary line itself cannot be changed without private reporter
  API). Its clean-copy run with the store reached through the symlink:
  4567 passed, exit 0, no banner, store byte-identical; the
  out-of-process append via the symlink reported with the hook silent.
  Coordinator suite 4652 passed, exit 0; pushed. Narrow re-audit
  verdict merge: C1 genuinely fixed and pinned by four tests (bytes paths
  caught too — decoded before the basename filter; a different symlink to
  the same directory caught; a relative open after chdir caught; the
  subprocess route reported by the snapshot half); the corrected
  narrative empirically true; the per-open cost 0.5-0.7 µs; a full run
  with the store reached through the symlink 4637 passed, exit 0, no
  banner, store byte-identical. **Merged** 2026-09-10. DEFERRED: the
  full-path equality check is unpinned (matching on basename alone
  passes all 179 tests — a decoy `memories.jsonl` outside the store
  would then fire); bytes paths decoded with `replace` rather than
  `os.fsdecode`; `realpath` unwrapped against a NUL-bearing path
  (unreachable — `open` raises before the event); a hard link to the
  store is undetected (undocumented); the retracted "179.5 s against
  185.3 s" figure survives in this report's round 4a-7 paragraph (it is
  retracted here: the cost is +2.5 s per run, about 0.5 µs per open).
- **#138** (machine-glue follow-ups, round 4d-4): re-audit verdict **do
  not merge as-is** — C1: the new `DATA_REMEDY` ("remove `data` entirely")
  prints for every non-worktree run that reaches the `local.md` check,
  including an initialised submodule that merely lacks the file, so the
  round's headline fix replaced impossible advice with advice that deletes
  the private submodule; the composer's branch tests emptiness rather than
  initialisation and has the same defect. Also M-a (`--dry-run` on a
  worktree exits 1 where the real run exits 0), M-b (the `git` stub never
  populates `data/`, so the fresh-clone happy path is inspected but cannot
  pass), three lows, and three surviving mutations. Round 4d-5 delivered
  (31efd4f, 251d2c4, 24daadd): the remedy is chosen by the submodule state
  and the destructive advice is reachable only when git reports no
  checkout; the composer branches on `data/.git`; `--dry-run` sets
  `SKIP_COMPOSE` and a dry run on a broken clone narrates to step 8 and
  exits 0; the git stub populates the submodule; the remedy text, the
  composer consultation, and the empty-`data/` case pinned; the Zotero
  trim comment recounted to 22; worktree detection reads the `.git`
  pointer's shape. Merged with main (259d4fe), coordinator suite 3957
  passed, exit 0, pushed. Second re-audit verdict approve: the destructive
  advice reachable only for an uninitialised submodule (every other
  state, an absent line, and a failing git all get the non-destructive
  message), the stub matches real git, the fresh-clone path genuinely
  succeeds, the 22-character count recomputed, all prior survivors dead.
  **Merged 8eb78c3** 2026-09-09 13:2x. Nine lows are round 4d-6
  (`claude/audit-round4d-6`): the trim-set count test counts only
  whitespace so a non-whitespace addition is invisible; a worktree
  preview could print the wrong note; the dry-run branch never prints the
  remedy it previews; the composed file's content unasserted; the `--
  data` pathspec and the composer's `-e` breadth unpinned; and three
  notes (pointer regex needs a literal `/.git/`; `$submodule_state` read
  before assignment under `set -u` if ever called early; a status that
  prints `-` and fails is treated as authoritative). Round 4d-6
  delivered (734a28d-7fc6dd6): the trim set asserted whitespace-only;
  the preview prints the remedy it previews; both dry-run notes pinned in
  both directions; the composed file's three layers asserted in order;
  the stub honours the pathspec (two-submodule cases); the directory-
  shaped `data/.git` case; the destructive remedy additionally requires
  `git submodule status` exit 0 (a failed query gets its own "state is
  unknown" message); safe defaults declared near the top; the pointer
  regex's limits recorded. Merged with main (c4cc548), coordinator suite
  4409 passed, 2 skipped, 19 deselected, exit 0; **PR #149**. Re-audit
  verdict **do not merge** — M1: the destructive advice is printed in
  TWO places and the L9 conjunct guards only one; `sync-symlinks.sh:
  383-384` prints `$DATA_REMEDY` inline, gated on the `-` prefix alone,
  so a `-` line from a failing git still yields "remove data entirely"
  at step 1 and "state is unknown … Do NOT delete" at step 7 — and the
  round's test passes on a prefix technicality (it asserts "Remedy:
  remove" absent while :384 emits the sentence without the prefix). M2:
  the dry-run branch calls `say_data_remedy` unconditionally (:423), so
  a fresh-clone preview that has just narrated the init is told to
  delete `data/`. Lows: empty output plus a failed query is still a
  confident "no submodule declared" (:265 tests `-z` before the status);
  `assert_composed` cannot see a duplicated layer; the `char()` regex
  can silently narrow to a subset. Everything else verified (status
  observable; preview and real remedy byte-identical; order checked;
  pathspec pinned; ten mutations killed). **DEFERRED** (stop point):
  round 4d-7 routes :383-384 through `say_data_remedy` (or adds the
  conjunct), gates the dry-run remedy on the state a real run would
  reach, tests the empty-output-and-failed-query cell and a duplicated
  layer, and tightens the `char()` extraction; then re-audit; PR #149
  stays open on `claude/audit-round4d-6` in the 4d worktree. Resumed
  2026-09-10: round 4d-7 delivered (e6e8686, 72f7f6f): the destructive
  advice emitted from exactly one site (`say_data_remedy`), pinned at
  source level, and the test asserts the sentence across stdout and
  stderr; a `WOULD_INIT` flag makes a fresh-clone preview say the init
  would supply the file, print no remedy, and not claim a real run would
  refuse (the companion test runs that state for real); the failed-query
  test moved to the front of `say_data_remedy`; `assert_composed`
  requires each marker exactly once; the trim-set extraction parses
  whole argument lists and refuses non-integer literals. Coordinator
  suite 4502 passed, 19 deselected, exit 0; pushed. Second re-audit
  verdict "merge after M-1": all six matrix rows hold through the real
  script and every claimed kill re-verified, but the new
  `assert_no_destructive_advice()` duplicates the fragment from the
  script and no positive control requires the word "entirely", so a
  benign rewording disarms it (124 passed with a re-injected regression);
  and `submodule_state` is never re-read after a successful init, so a
  just-cloned submodule lacking `local.md` still gets the destructive
  sentence (bounded: `data/` was empty). Round 4d-8 (closing): derive the
  fragment from the script source, gate the destructive branch on
  `WOULD_INIT -eq 0`, pin step 1's remedy; then merge on a green suite
  with the one-line test fix verified by mutation rather than a third
  re-audit. Round 4d-8 delivered (cee582c): the fragment parsed from the
  `DATA_REMEDY=` literal, the destructive branch gated on `WOULD_INIT
  -eq 0` (a just-initialised submodule lacking `local.md` is told to look
  inside it, never to delete it), step 1's remedy pinned, printed twice
  by design and pinned at two; the coordinator verified by mutation that
  a reworded remedy plus a re-injected regression fails the fresh-clone
  preview test. **Merged 2a80630** 2026-09-10. Process slip recorded: the
  merge command gated on GitHub mergeability, not on the coordinator
  suite line, and that pre-merge run (554 s under load) showed one
  failure; a captured full run on main afterwards named it —
  `tests/test_analyse_wiki_vocabulary.py::TestWritesNothing::
  test_repository_tree_and_home_are_untouched`, a whole-checkout
  snapshot that includes the live `data/` submodule, so the extraction
  hook's five-minute appends (reported by the hermeticity summary in the
  same run) fail it whenever they overlap the run; it passes alone and in
  every clean copy. Not caused by #149. DEFERRED: exclude the canonical
  store paths (or tolerate the hermeticity guard's verified live appends)
  in that snapshot; and the coordinator's merge step now checks the
  suite line first.
- Round **3c-7** delivered (four commits 102fb0e-a35f7e6 on
  `claude/audit-round3c-7`): an unmeasurable merge is dismissed only by a
  trailered commit whose own transition spans the whole observed drop, and
  every unmeasurable merge is logged; the quiet-grep lint tokenises
  statements; the vacuity guard names the allowed set; `render_sync_gate`
  driven directly; record paths escaped on both sides. Merged with main,
  coordinator suite 3913 passed, exit 0; **PR #139, merged d07c174**
  2026-09-09 12:3x: the re-audit found all nine span-rule decisions
  correct and order-independent, every unmeasurable merge logged without
  touching the gate, and the upgrade path safe (status records are never
  persisted, so the round report's "in-flight comparison" risk cannot
  arise). Follow-ups are round 3c-8 (`claude/audit-round3c-8`), all
  coverage and lint-reach gaps: the span check's second condition is
  untested (a one-token mutation republishes an unaccounted shrink); the
  heredoc skip is dead (the opener regex is anchored before the script's
  only heredoc's redirections, so the embedded Python is linted as
  shell); the quiet-grep pattern misses `grep -E -q`, `--silent`,
  `egrep`, `zgrep`; the vacuity set is per-function not per-site; the
  rename branch of the path escaping is untested; the gate-render tests
  assert membership not the exact list. Round 3c-8 delivered (8d2d208-
  b222df1, tests only plus a comment recording the two deliberate
  span-rule edges): both span conditions pinned by a linear-chain fixture
  (the agent's first fixture built the merge off to one side and did not
  kill the mutant — rebuilt); the heredoc skip made real and instrumented
  (a planted quiet grep inside the embedded Python must not trip the
  lint, and restoring the old anchor makes it trip); openers honoured only
  in command position; the pattern widened to eight spellings; the
  vacuity guard counts per function; three rename fixtures; two of three
  gate-render tests assert the exact list (`-qxF`→`-qF` is equivalent
  under the present key vocabulary and recorded as such). Merged with
  main (fcca012), coordinator suite 4384 passed, 2 skipped, 19
  deselected, exit 0; **PR #148, merged 33afc07** 2026-09-09 15:1x: the
  re-audit killed all four span mutations, confirmed the fixture linear
  and not passing for the wrong reason, and caught sixteen quiet-grep
  spellings. Follow-ups are round 3c-9 (`claude/audit-round3c-9`): the
  command-position guard covers only full-line comments (a `<<WORD` in a
  quoted string or a trailing comment still blinds the scan — latent,
  the script has one heredoc); the comment fixture sits at column 0;
  `_quiet_grep_offenders` judges only the first match on a statement; an
  indented `<<-` terminator unpinned; and four pre-existing script
  weaknesses exposed by mutation (a `bulk-anything` trailer passes the
  gate; a copy record desynchronises the status stream; the last rather
  than the first unmeasurable merge named; `--reverse` unpinned). Round
  3c-9 delivered (4a9793c, ef8e29f; tests only, the script byte-identical
  to PR #148): a quote-state tokeniser replaces the comment heuristic
  (the opener must start outside quotes; its delimiter may be quoted);
  fixtures indented; every quiet grep on a statement judged by whether IT
  is downstream of a pipe; the `<<-` terminator and the here-string
  lookbehind pinned; four script guards pinned (a `bulk-extra` trailer
  refused, the copy record keeps the field stream aligned, the first
  shortening commit and the first unmeasurable merge named). The agent
  records two fixture traps its own earlier tests caught. Merged with
  main (92fc79e), coordinator suite 4468 passed, 2 skipped, 19
  deselected, exit 0; **PR #153, merged c713cd5** 2026-09-10 (re-audit
  verdict merge: the script byte-identical, every claim re-checked, the
  four script-guard mutations each killed by exactly the named test, the
  L6 trap genuinely closed). **DEFERRED** lows from that re-audit: the
  `#`-at-word-start rule (the tokeniser handles `${#a[@]}`, `${x#y}`, and
  `foo#bar` correctly but no fixture pins it — `if char == "#":` survives
  4,467 tests while silently deleting 1,430 characters of the real
  script's statement stream); `_pipes_before`'s `||` exclusion unpinned;
  `;#` and `&&#` are comments the word-start rule misses (latent);
  first-match opener search rejects a quoted opener rather than finding
  the first unquoted one (over-report); quote state resets per line
  though ten real lines end mid-quote; `_pipes_before` ignores quoting
  and `;` (noise).
- Round **4f-4** delivered (five commits a0d35f0-c139769 on
  `claude/audit-round4f-4`): a lone checkout is not a repository set;
  excluded repositories reported in the trend row and in `[F]`; an excluded
  repository answers "unknown" and blocks a committal verdict; only
  permanent `OSError`s exclude; the confidence write-back keeps the
  record's spelling. Merged with main, coordinator suite 3930 passed, exit
  0; **PR #140, merged c7dcada** 2026-09-09 11:5x: the re-audit confirmed
  all four fixes, re-verified every claimed kill, and found no path that
  mints a false verdict. Its residuals are round 4f-5
  (`claude/audit-round4f-5`): the history probe's transient-error branch
  and the commit path's permanent-error branch untested (a `return
  "false"` mutation survives — the AN3 class); `unusable` reaches no
  standing surface (`[H]` never renders it, `/weekly-review` runs without
  `--tier-c`, cron discards stdout); exclusion discovery is lazy, so
  `unusable` under-reports unless some ref forces resolution to reach the
  broken repository; one flaky mount makes every sweep a refusal with the
  gap invisible; one repository counts as a set on a first run; the
  refusal names no override; the real key `MPZHXY3P` remains in
  `tests/test_sync_to_zotero.py`; both registry resets untested. Round
  4f-5 delivered (fb46317-97632e4): `probe_repos` asks every repository
  once before resolving; `[H]` names exclusions and marks degraded runs;
  a degraded sweep (pending rate over the floor AND known exclusions)
  writes a row flagged `degraded: true` that the floor and `[H]` skip
  rather than refusing (option b; dropping unknown-blocked refs from the
  denominator rejected as a fail rate over a silently smaller
  population); `MIN_DISCOVERED_REPOS = 3` when the log offers no count;
  the refusal says it has no override; `consulted` beside `repos`;
  eleven real Zotero keys replaced; resets and the history-probe
  handlers tested. Merged with main (1b1a4aa), coordinator suite 4330
  passed, 2 skipped, 19 deselected, exit 0; **PR #145, merged 07a69d1**
  2026-09-09 14:4x: the re-audit confirmed the probe's classification
  for every constructed shape and the shared registry, and found four
  mediums, all follow-up — `degraded` fires on ANY exclusion rather than
  on the pending rate (one chronic stale directory would mark every
  future row for ever); the `last_repo_count` skip guards a field
  degradation cannot touch (three degraded rows collapse the floor);
  `probe_repos`'s error branches are untested (five surviving
  mutations, including inverting the permanent-error classification);
  the tier-C call site is unpinned. Plus a third real Zotero key; one
  `--min-repos` override silently becomes the standing floor; `[H]`
  over-claims and under-marks; a degraded row's deflated fail rate is
  still alert-tested; a nested emptied directory probes usable. Round
  4f-6 (`claude/audit-round4f-6`) takes all of them. Round 4f-6
  delivered (bc7e1f0, 5360da1, 5ea690c): `degraded` is the judgement
  (exclusions AND a pending rate over the floor) with `unusable` the
  fact; the `last_repo_count` skip removed; `probe_repos` tested per
  branch on both the return and the registry, and it now compares
  `--show-toplevel` with the path it asked about so a nested emptied
  directory is excluded rather than answering for its parent; the tier-C
  probe pinned; the third real key replaced (two remaining occurrences in
  the style-analyser scripts are operational configuration naming the
  operator's reference papers, noted); the floor is `max(recorded, 3)`
  unless `--min-repos` is passed that run, with a WARN naming a low
  recorded count; `[H]`'s headline marked and its wording matched to
  behaviour; the alert comparison skipped for a degraded row with a
  NOTE. Merged with main (f5a2a6b), coordinator suite 4454 passed, 2
  skipped, 19 deselected, exit 0; **PR #152, merged 9737c3e** 2026-09-09
  16:2x: the re-audit confirmed the predicate, the shared denominator,
  all four cells, the probe matrix (one subprocess per repository), the
  floor's WARN-then-refuse, `[H]`, and re-killed all eleven named
  mutations. **DEFERRED follow-ups** (stop point): two stale messages
  still say "the floor and the fail-rate trend skip it"
  (`drift-sweep.py:304`, `:422`, comment at `:410`); a sub-threshold
  exclusion is alert-tested on a rate deflated by up to the 10 % pending
  bound (document the bound); four surviving mutations — the symlink
  `resolve()` at `anchor_verify.py:190` unpinned, the `>` at
  `drift-sweep.py:229` duplicated from `:418` so exactly 10.0 % disagrees,
  the degraded early-return's log-failure exit untested (`:454`), and
  `[H]`'s `degraded` key co-varying with `unusable` in every fixture
  (`memory-health-report.py:895`); `build_basename_index` never consults
  `repo_is_unusable`; six real Zotero keys remain in five style-analyser
  scripts as operational configuration (not fixtures; `tests/` is
  clean).
- Round **4c-4** delivered (four commits 9eaa2f3-1d2209f on
  `claude/audit-round4c-4`): the eight lows from #136, plus one new defect
  found while testing — the R2 push's failure classifier grepped a log
  slice that included the script's own lines, so any store path containing
  "immutable" would have made every transport failure a corruption abort.
  Merged with main, coordinator suite 3916 passed, exit 0; **PR #141,
  merged aa39a70** 2026-09-09 12:2x: the re-audit confirmed all eight
  items and the classifier fix (rclone is not piped; all thirteen log
  call sites carry the prefix; the sandbox exit-code matrix holds).
  Follow-ups are round 4c-5 (`claude/audit-round4c-5`): the new
  classifier test is inert (its rename round-trips and pytest truncates
  the tmp basename, so the filter is covered only by two older tests'
  directory names); rclone's own INFO lines can still carry the word in a
  path element; an unremovable temporary is counted nowhere and exits 0;
  `*.tmp` symlinks are followed or skipped forever; the sizeless warning
  is unbounded per run. Round 4c-5 delivered (f78bacb, 3fa6b85, 2a5c81e):
  the classifier matches rclone's own ERROR/NOTICE refusal wording
  (verified against the installed v1.74.2 binary with `strings`; a future
  phrasing fails safe to exit 2) and the now-unreachable `grep -v` was
  removed rather than kept as a dead guard; the fixture HOME carries the
  word deliberately; sweep failures counted in `errors` and the exit
  status; `*.tmp` symlinks judged by their own age and removed as links
  (a dangling one was invisible for ever); the sizeless warning once per
  run with a count. The round 4c-4 report's claim that its test pinned
  the filter is corrected. Merged with main (1286407), coordinator suite
  4318 passed, 2 skipped, 19 deselected, exit 0; **PR #147**. Re-audit
  verdict **do not merge** — C1: the new `^(ERROR|NOTICE)` anchor can
  never match real rclone output, because rclone's default `--log-format`
  prefixes every log-file line with a date and time; the branch's stubs
  all write the un-prefixed form, so the tests certify a format rclone
  never emits, and the deployed `logs/r2-push.log` holds 19,156 rclone
  lines of which none match — including a REAL `--immutable` refusal on
  `CATALOG.json` at 10:28 today that main classifies exit 3 and this
  branch exit 2. The branch would trade the false positive for a false
  negative on the one signal the classifier exists to raise. Round 4c-6
  (same branch): match the level marker, not the line start, and make
  every stub write the date-prefixed form; plus a dead `not is_link`, an
  unpinned id count, a silent-by-default parameter, a label, and a
  pre-existing `KeyError` on a sizeless manifest in the dry-run listing.
  Round 4c-6 delivered (3775a0a, e06c5a2): the level marker matched as a
  token, every stub date-prefixed, a six-way classification matrix
  (restoring the old anchor fails eight tests); the agent reproduced the
  three-way evidence itself (0 of 9,314 level-carrying lines in the
  deployed log match the old anchor) and records that this was its own
  regression, the second time in this pipeline a narrowing silently
  disabled what it sharpened; the dead conjunct, the id count, the
  required collector, the labels, and the dry-run `KeyError` fixed.
  Merged with main (fe9c570), coordinator suite 4438 passed, 2 skipped,
  19 deselected, exit 0; pushed. Second re-audit verdict **do not merge**
  — C-1 (new, confirmed end to end): the classifier at
  `push-archives-to-r2.sh:301-303` pipes `grep -E` into `grep -q` under
  `set -o pipefail`; `grep -q` exits at the first match, the upstream
  grep dies on SIGPIPE, the matched pipeline returns 141, and a real
  refusal is reported "safe to retry" (exit 2) whenever more than one
  pipe buffer (~64 KB) of ERROR/NOTICE output follows it — N=1000
  trailing lines → 2,2,2; the deployed log holds 4,658 `ERROR :` lines
  in 2.5 MB, so the regime is ordinary. Every stub writes one line, the
  same certify-the-wrong-regime shape as C1; and it is the exact
  `| grep -q` class the daily-sync lint forbids. The one-line fix is
  verified by the re-auditor: a single `grep -qE '(^|[[:space:]])(ERROR|
  NOTICE)[[:space:]]*:.*(immutable file modified|immutable objects)'`
  fed by a here-string, plus a test with at least 1,000 marker-level
  lines after the refusal. Also M-1 (the comment attributes "Timestamp
  mismatch" to ERROR level and the parametrisation pairs it with NOTICE
  — neither attested; `strings` verified wording, never level), M-2
  (`--log-format date,time` should be pinned in `RCLONE_FLAGS`, since
  `RCLONE_LOG_FORMAT`/`--use-json-log` would make every refusal exit 2),
  and three lows (the dry run still never shows the "re-run discover"
  remedy; `entry.get("turns", "?")` untested; the shown-id constant is
  pinned by the pre-existing test, not the new one). **DEFERRED** (stop
  point 2026-09-09 16:4x): PR #147 stays open on `claude/audit-round4c-5`
  in the 4c worktree; round 4c-7 takes C-1, M-1, M-2, then a third
  re-audit. Resumed 2026-09-10: round 4c-7 delivered (e813336, 9d5e404):
  one `grep -qE` over a here-string, no pipe, reproduced at every scale
  (1,000 trailing marker lines: 2 before, 3 after); a repository-scope
  lint (`tests/test_pipefail_grep_lint.py`, importing the daily-sync
  tokeniser) that on its first run found two MORE `| grep -q` sites in
  the same script (`df … | tail -1 | grep -q` at :179 and `listremotes |
  grep -q` at :184), both fixed rather than allow-listed; the attested
  levels separated from the defensive match; `--log-format date,time`
  pinned; the dry run prints the sizeless remedy. And the LIVE fix Shawn
  approved: `CATALOG.json` is excluded from the immutable copy
  (`--exclude "/CATALOG.json"`) and pushed afterwards with `rclone
  copyto` without `--immutable`; the copyto runs only after a successful
  copy, its failure is exit 2 ("the archive copy SUCCEEDED, only the
  derived index is stale"), an absent catalogue is skipped, and the dry
  run previews both. Merged with main (032d48d), coordinator suite 4541
  passed, 19 deselected, exit 0; pushed. Third re-audit verdict merge:
  no pipe anywhere in the classifier, the scale table reproduced (3 at
  every size, 2 with no refusal; a bash here-string above the pipe
  buffer is a temp file, so nothing can be SIGPIPEd), the lint real and
  the repository clean, every attestation checked against the deployed
  log, the copyto argv right and a copyto failure unable to reach exit 3.
  One test-integrity medium: the copy-before-copyto ordering guard is
  hollow (the `_rclone_writing` stub never records argv), taken in a
  closing round 4c-8 with two dead-comment/dead-assignment lows; deferred
  lows: no fixture exceeds ten manifest entries; the lint skips
  `setup.sh`; the `| head -1` SIGPIPE class is unlinted. Round 4c-8
  delivered (fbb5a2d): the stub records argv per subcommand, the
  ordering test asserts the copy ran, a positive control asserts copyto
  runs after a successful copy; the coordinator verified independently
  that moving the catalogue push above the copy now fails the named
  test. Coordinator suite 4586 passed, exit 0. **Merged 0a49f15**
  2026-09-10 — the live R2 fix is on main.
- Round **4e-5** delivered (five commits 7a67844-bb5143a on
  `claude/audit-round4e-5`): the recovery line shell-quoted; both argument
  fences covered one-of-two; `n_requests` pinned apart from the map; the
  vocabulary threshold pinned from both sides; a stranded batch result
  names the probable session, says it was paid for, counts the skip, and
  prints the repair, with a new `--rebuild-map` that reconstructs the
  mapping from the manifest. Merged with main, coordinator suite 3939
  passed, exit 0; **PR #142, merged a20f5e6** 2026-09-09 12:1x: the
  re-audit reproduced every claim and confirmed recovery can never name
  the wrong session. Follow-ups are round 4e-6 (`claude/audit-round4e-6`):
  a regression assertion on the retired message wording is now
  unfalsifiable; the remedy line's `<manifest>` placeholder is a shell
  redirection; "existing entries win" and the atomic rebuild write are
  unpinned; a third `and` fence uncovered; a 40-hex session id is wrongly
  declared unrecoverable; a malformed manifest tracebacks. Round 4e-6
  delivered (6c2d347-d98c14c): the live wording asserted; the repair line
  names the manifest path recorded in the state (shell-quoted) or a
  paste-safe placeholder; "existing entries win" and the atomic write
  pinned by a disagreeing state and a crash on `os.replace`; the batch id
  quote kept and pinned; the rubric fence covered; session-id recovery
  consults the manifest first (reversing both forms); a malformed
  manifest raises `ManifestFormatError` and exits 2 before anything is
  written. Merged with main (f8a0489), coordinator suite 4333 passed, 2
  skipped, 19 deselected, exit 0; **PR #146, merged de5ab68** 2026-09-09
  13:5x: the re-audit confirmed the reverse matching, the write ordering,
  and the atomic pin, and found the round's headline claim unreachable
  from the route the tool prints — `--rebuild-map` neither records
  `manifest_path` nor threads `--manifest` into the same invocation's
  `haiku_apply`, so on the old-format state the remedy still reports
  "not recoverable without a manifest" and prints the placeholder again.
  Follow-ups are round 4e-7 (`claude/audit-round4e-7`): that threading;
  the new `shlex.quote` and the `or` guard unpinned (a third `and`/`or`
  fence); the quiet manifest fallback prints nothing; an asymmetric
  `isinstance` guard that raises at the end of `haiku_apply`; an empty
  session list "restores 0"; a constructed custom-id collision handled
  three different ways; the reverse map re-hashed per result; an
  over-claiming comment; no `fsync` before `os.replace`. Round 4e-7
  delivered (71072fb-df9ec6e): `--rebuild-map` records `manifest_path`
  and `main` threads `--manifest` into the same invocation's
  `haiku_apply` (a stale-path test pins the threading, which the
  end-to-end test could not see once the rebuild recorded the path — the
  agent's first draft claimed a kill it did not have and was amended);
  the remedy's manifest quoted and pinned; empty, blank, and tab-only
  session ids refused (a whitespace-only id was truthy and would have
  named a response file `   .json`); the unreadable-manifest fallback
  explains itself on stderr; one helper guards the recorded path's type;
  an empty session list and a self-colliding manifest refused with exit
  2; the lookup built once; `fsync` before `os.replace` (its mutation
  survives by nature, stated). Merged with main (06aff0f), coordinator
  suite 4422 passed, 2 skipped, 19 deselected, exit 0; **PR #150, merged
  1c6b598** 2026-09-09 15:3x: the re-audit confirmed the threading, the
  collision handling, the empty-list refusal, the once-per-run messages,
  and the write paths (15 of 17 mutations killed). Follow-ups are round
  4e-8 (`claude/audit-round4e-8`): the `--manifest` help still says
  "unused by --haiku-apply"; a supplied-but-unreadable `--manifest`
  defeats a good recorded one (a regression against main, mitigated by
  the new warning); the non-string recorded path is the one unreadable
  case still silent; the strip guard is rebuild-only and the id is used
  unstripped downstream (validate once, in one helper, at both entry
  points); the rebuild's summary names neither manifest when they
  differ; first-wins pinned only probabilistically; the parent directory
  not `fsync`ed and a failing `fsync` aborts a retrieval mid-loop. Round
  4e-8 delivered (6b7cd19, a11bc0f, 1679b7d, d743873): the help text
  corrected and pinned per flag (the agent's first assertion matched
  another flag's entry and was amended); `resolve_manifest` prefers a
  readable supplied manifest, falls back to the recorded one naming both,
  and yields the placeholder when neither is readable; a malformed
  recorded path named by type; `validate_session_id` is the single rule
  at submit (before the billed call) and rebuild, refusing rather than
  stripping whitespace so the id round-trips byte-for-byte; the summary
  names both manifests when they differ; first-wins pinned
  deterministically; the parent directory `fsync`ed after the rename and
  write failures re-raised with the path. The agent's shell died on a
  full /tmp after its green clean-copy run (4486 passed); its work
  directory was removed by hand. Merged with main (dd046f8); coordinator
  suite 4487 passed, 2 skipped, 19 deselected, exit 0; **PR #154, merged
  165068a** 2026-09-10 (re-audit verdict merge: `create` never reached
  for an unusable id; the decision table, validation order, fsync order,
  and fd hygiene confirmed). Its three coverage gaps — a readable
  manifest naming no session still defeats a good recorded one silently
  and prints a remedy the rebuild path refuses; submit validation pinned
  by single-session fixtures only; the directory-fsync target unpinned —
  plus an uncaught `SessionIdError` after the cost gate, the ENOSPC
  decoration missing `mkstemp`, a collapsed exception type, a duplicate
  diagnostic, an unguarded `build_custom_id`, and a mis-scoped help
  slice are round 4e-9 (`claude/audit-round4e-9`), the last on this
  branch for the cycle. Round 4e-9 delivered (9fa7533-4481e9b): a
  sessionless supplied manifest falls back like an unreadable one,
  naming both; a two-request fixture with the fault in the second id;
  the fsync target stat'ed while open (the closed temp fd's number is
  reused, which silently overwrote the agent's first attempt); the
  session-id check before the cost gate with exit 2; `mkdir`/`mkstemp`
  inside the decorated block; the same exception class re-raised with
  errno intact and the path in `strerror`; the malformed-path
  diagnostic reported once by parameter (a state-dict marker was
  rejected as a leak); `assemble_requests` validates first;
  `known_session_ids` removed; the help slice scoped within the options
  section. Merged with main (a163fcb), coordinator suite 4550 passed,
  19 deselected, exit 0; **PR #156, merged** 2026-09-10 (re-audit
  verdict merge: every claimed behaviour reproduced; the remedy never
  names a file the rebuild refuses; validation before `create` and before
  the cost gate; the fsync target pinned by inode). DEFERRED: the
  exception-type test passes for the wrong reason (`OSError(ENOENT, …)`
  auto-maps to `FileNotFoundError`, so `raise OSError(` survives); the
  RECORDED-manifest side of `if found:` is unpinned and silent (an empty
  recorded manifest yields the placeholder with no stderr, unlike the
  supplied side); `exc.filename` dropped by the two-argument re-raise;
  an errno-less `OSError` loses its message; `setdefault` treats a
  malformed recorded path as an existing record; the assemble error's
  position wording unpinned; two tests assign `sys.modules` directly.
  The bake-off branch is closed for this cycle.

Resumed 2026-09-09 ~08:00 after the spend-limit interruption; if it
recurs, everything needed to resume is in `2026-09-08-first-audit-artefacts/`
(briefs, lens reports, round reports): a fresh session re-spawns each
round's agent with the shared brief, the round brief, and the round
report's last paragraph.

Operator actions pending, in order of consequence:

1. ~~Re-run phase 1 (`phase1_pipeline.py --clean-corpus`), then promotion,
   then re-derive the guide — required after #128 merges (metric
   definitions changed; the interlock refuses the old results).~~
   **Done 2026-09-10 10:xx** (Shawn approved installing the stack):
   `numpy`, `scipy`, `scikit-learn`, `spacy` 3.8.16, and
   `en_core_web_sm` 3.8.0 installed into the project venv and added to
   `requirements.txt` (2ecc6e0); the step-2 manifest rebuilt from the
   durable extraction output as `data/style-corpus/extract-input-
   manifest.json` (the agent document's recipe; the extractor's own copy
   does not exist yet because extraction has not been re-run); phase 1
   re-run over the 18 clean bundles and `phase1-results-clean.json` now
   carries `metric_schema` version 2 (the redefined metrics moved as
   documented: hapax ratio 0.0344 → 0.4158 over types; passive and
   nominalisation now means of papers; n_words 127,720 → 127,718 under
   NFC); `phase3_promotion.py` re-run, exit 0, its output stamped 2;
   both committed to the data submodule (fb1e9a0). Phase 1 exits 1
   because 12 of 13 "regression vs run 1" anchors are out of tolerance —
   this is PRE-EXISTING (the previous clean file also passed 1 of 13):
   the anchors in plan §2.5 were calibrated on the raw run-1 corpus
   (139,105 words, references included), not the clean corpus. Decision
   D9 below. The guide itself (`phase3_guide_verifier`, phase 5) has NOT
   been re-derived — that is the analyser agent's run, not an operator
   step.
2. ~~Run `sync-to-postgres.py` before any `archive-memories --apply` or
   `dedup-memories` (both refuse while the cursor is behind or unreadable).~~
   **Done 2026-09-10 14:40**: the cursor sits at the store's last line
   (43,398); the gate reads 0; Postgres holds 47,943 rows (the surplus is
   the known Postgres-only set).
3. Agree an `ENV_FINGERPRINT_SALT` out of band before the next cross-machine
   `.env` comparison (the tool refuses without it; old fingerprints are not
   comparable). Shawn's to hold in his password manager and type in at
   comparison time (`read -rs`), never in `.env` or on a command line
   (2026-09-10).
4. Expect the first `audit-postgres-sync` and `/memory-health` after #129 to
   FAIL on content divergence and Postgres-only orphans (real, not noise).
5. Expect the first drift sweep to refuse once with a `--min-repos` line if
   the last trend row came from a worktree.
6. `push-archives-to-r2.sh` now refuses to overwrite; `.tmp` objects already
   in R2 need a manual delete; run `normalise-archive-storage.py --dry-run`
   on the canonical mount before `--apply` (it now sweeps stale
   temporaries). **Live now (found by the PR #147 re-audit reading
   `logs/r2-push.log`):** the push has been refusing on `CATALOG.json`
   ("immutable file modified", 2026-09-09 10:28) — the catalog is a file
   that legitimately changes, so it needs to be exempted from
   `--immutable` (or pushed separately without it) before the next push
   can complete; until then every push exits 3. **Closed 2026-09-10**:
   PR #147 pushes the catalogue separately; the merged script's dry run
   against the bucket exited 0; and Shawn's own `rclone ls --include
   "*.tmp"` over the bucket (credentials sourced in his shell) listed
   nothing, so no temporary was ever pushed.
7. `PA_HERMETICITY_STRICT=1` is the contract for audit and clean-copy runs
   (see `commands/audit.md`); shared checkouts warn instead of failing on
   concurrent edits.
8. The stale `data/style-corpus/corpus-manifest.json` should be deleted (the
   extractor now writes it inside the output directory); the judge key can
   be moved out of the live `judge-tasks/` with `--migrate-key`.
9. Decisions D1-D8 below; the dependency additions for the style analyser
   (`numpy`, `scipy`, `scikit-learn`, `spacy` + `en_core_web_sm==3.8.0`); the
   nominalisation stop-list; `data/.gitignore` for `logs/*.json` (AR26);
   whether the dedup journal stays committed. The dependency additions are
   **resolved** (installed and in `requirements.txt`, 2026-09-10).

## Closing summary (2026-09-10)

**What was audited.** Every script under `scripts/` and `hooks/`, the
slash-command definitions they serve, and their tests — nine tranches
(0-8), each read by two fresh-context lenses (implementation
correctness; test adequacy by mutation) before any fix was written.
Fourteen lens reports produced about 190 anchored findings; every fix
round was re-audited by a fresh agent before merging, forty-two round
reports in all. Shawn stopped the first pass on 2026-09-09 16:5x for
cost and resumed on 2026-09-10 to close the open branches; follow-ups
found after that point are deferred and listed below.

**What changed.** Thirty-seven pull requests merged (#114-#127, #129-#156), about 800
commits on main, and the test suite grew from about 1,250 to about 4,650
tests.
The defects with live consequences, all fixed and verified:

- The daily sync could drop a stash whose tracked half had never landed,
  commit a truncation already on disk unguarded, and lose the only copy
  of an untracked file on a partial apply; it now tracks stashes by SHA,
  never pops what it cannot prove, and refuses an unaccounted corpus
  shrink.
- The Postgres syncs and the indexer could silently skip refused rows and
  hold a cursor past them; they now quarantine, gate on evidence, and
  expose exit codes 4-9 at session start.
- The memory-store writers could interleave and truncate under
  concurrency; the readers and the drift sweep could fabricate a spike
  from an unmounted repository set and mark absent anchors false.
- The archive pipeline could publish a half-written temporary as a
  permanent object; the R2 push's classifier could report a real
  corruption signal as "safe to retry" (twice, by two different
  mechanisms) and had been refusing the derived catalogue since
  2026-09-09 — fixed and confirmed by a dry run against the bucket.
- The style analyser measured four metrics under names whose definitions
  had changed and scored new-definition inputs against an old-definition
  corpus; a metric-schema interlock now refuses that, phase 1 has been
  re-run under the new schema, and the scorer consumes the bytes it
  checked.
- `sync-symlinks.sh` could advise deleting the private data submodule;
  `check-credentials.py` and the agent-mail hooks had the round-1 set of
  defects fixed on day one.
- The test suite itself gained a hermeticity guard: no network, no live
  Postgres, the canonical store snapshotted and, in-process, watched
  through the path the repository actually writes.

**What it cost.** In the order of 25M subagent tokens over two days,
roughly 45 fix rounds and 60 re-audits. Every branch's first re-audit
found at least one critical in the fix code itself; the median branch
needed three rounds. The two lessons worth keeping are in the
scratchpad: build fixtures from an attested live shape and prove the
test fails against the defect; put class-level lints at repository
scope.

**What remains** is in "Deferred" entries throughout (search
`DEFERRED`), the decisions D1-D9, and operator actions 2-9 above. None
of the deferred items changes a live result; the one with stakes is D6
(private names in a public branch's history).

## Stop point 2026-09-09 16:5x (resume here)

Shawn stopped the audit at this juncture for cost (about ten million
subagent tokens since the 08:00 resume; every re-audit was still finding
one to four mediums, almost all test-adequacy or diagnostic). Thirty PRs
from the audit are merged (#114-#127, #129-#146, #148, #150, #152). No
further fix rounds were launched after 15:5x. What remains, per branch,
with the exact next action:

| PR | Branch / worktree | State | Next action |
|---|---|---|---|
| **#147** | `claude/audit-round4c-5` in `claude-audit-round4c` | Refused twice; round 4c-6 fixed the log-line anchor, then the second re-audit found `\| grep -q` under `pipefail` (SIGPIPE) dropping a real refusal to exit 2 past ~64 KB of output | Round 4c-7: the single here-string `grep -qE` (verified by the re-auditor), a test with 1,000+ marker-level lines after the refusal, the attested-level comment (M-1), `--log-format date,time` pinned (M-2), the three lows; then a third re-audit; then merge |
| **#149** | `claude/audit-round4d-6` in `claude-audit-round4d` | Refused: the destructive "remove `data/`" advice is still printed inline at `:383-384` without the status conjunct, and the dry-run remedy over-fires on a fresh-clone preview | Round 4d-7: route the inline remedy through `say_data_remedy`, gate the dry-run remedy on the state a real run reaches, the three lows; then re-audit; then merge |
| **#151** | `claude/audit-round4g-5` in `claude-audit-round4g` | Refused: the scorer discards the checked loader's return and re-reads the files (one word disables the interlock); the phase-5 "both inputs" assertion lost; four root-derivation assertions compare values | Round 4g-6: feed the returned payloads into `load_corpus_space`, explicit list, AST non-emptiness assertion; restore the phase-5 argument-set assertion; derivation checks by AST or monkeypatch; the lows (dead constants, the agent document's example command, a doc-to-code marker-name test); then re-audit; then merge |
| **#153** | `claude/audit-round3c-9` in `claude-audit-round3c` | Delivered, suite green, pushed; NOT re-audited | Fresh-context re-audit (tests only: the quote-state tokeniser, per-match pipe judgement, four pinned script guards); merge on a clean verdict |
| **#154** | `claude/audit-round4e-8` in `claude-audit-round4e` | Delivered, suite green, pushed; NOT re-audited | Fresh-context re-audit (manifest fallback, single session-id rule at both entry points, directory `fsync`, path in write errors); merge on a clean verdict |
| **#155** | `claude/audit-round4a-7` in `claude-audit-round4a` | Delivered, suite green (4504 passed), pushed; NOT re-audited | Fresh-context re-audit with attention to the permanent `sys.addaudithook` (guard path, cost, `PosixPath`/`os.open` routes, archive-copy inertness); merge on a clean verdict |

Deferred follow-ups already recorded in the tranche sections (search the
report for "DEFERRED"): PR #152's six (two stale "the floor skips it"
messages; the sub-threshold alert on a deflated rate; four surviving
mutations; recovery candidates from an excluded repository); PR #150's
were taken by round 4e-8; PR #146's by 4e-7; PR #148's by 3c-9; PR
#145's by 4f-6; PR #144's by 4g-5 (now #151); PR #143's by 4a-7; PR
#138's by 4d-6 (now #149).

Two patterns worth a standing rule, recorded in the scratchpad: tests
that certify a regime the deployment does not occupy (un-prefixed rclone
lines; one-line logs; a rename that round-trips; a comment at column 0)
passed green through three rounds while the shipped classifier could not
fire — fixtures must be built from an attested live shape and the test
must fail when the shape is wrong; and `| grep -q` under `pipefail`
recurred in a second script after the daily-sync lint was written for
it, so the lint belongs at repository scope, not per script.

Housekeeping for the resuming session: the seven audit worktrees under
`~/worktrees/personal-assistant/claude-audit-round{3c,4a,4c,4d,4e,4f,4g}`
are on the branches named above (4f is on `claude/audit-round4f-6`,
merged — remove it or move it to the next round); `/tmp` filled twice
more today (once by inodes, once by a re-auditor's 12 GB real-HOME
basetemp) — one suite at a time per agent, `--basetemp` under the
agent's own `mktemp -d`; the venv's `pytest` is
`~/personal-assistant/venv/bin/pytest` (not on a background shell's
PATH).

## Decisions for Shawn

**D9 (added 2026-09-10) — re-baseline the phase-1 regression anchors.
DONE 2026-09-10** (Shawn's choice: re-baseline): the table now holds the
clean corpus's schema-2 values with the bands unchanged; phase 1 exits 0
with all thirteen anchors within tolerance. The table edit itself was
not put through a fresh-context audit. Background: the anchors were
run 1's (2026-05, raw corpus, 139,105 words); the clean corpus (127,718
words) had failed 12 of 13 since 2026-05-24, so every clean run exited 1
although its results were written and stamped.

**D6 — filed 2026-09-10.** Shawn deleted the remote branch and filed a
GitHub Support request (via Repository features → Branches) naming
`refs/pull/115/head` and the five commits whose trees carry the private
rows (4baee34, 093f0bc, 4d5d94c, 5bdcdfd, 6b14323); the squash commit on
main is clean. Awaiting the ticket's reply; verify by a 404 on a commit
URL. Other clones may still hold the branch (zbook to check).

1. **H1 — extraction drops everything before the last 30 messages.
   DECIDED 2026-09-10: chunking approved (inbox row captured; needs its own
   PR and re-audit).** Fix is to
   process the window in chunks of 30, which multiplies Haiku calls on the 5% of
   firings that need it (never more than ten calls for the largest window seen).
   Approve the spend, or choose a larger single window.
2. **S2 — what the daily sync may auto-commit.** Today it commits everything
   dirty in the data submodule after the stash pop, prose included. The hub's
   own comments say prose must never be swept, but scratchpad and notes appends
   are left for it deliberately. Options: (a) an explicit allow-list of
   append-only paths (memories, scratchpads, notes inbox); (b) keep sweeping
   everything; (c) sweep but never push a commit that touched `tasks/` or
   `wiki/`. Recommendation: (a).
3. **Sessions table stale since 17 August (P1).** Fixing the error split and
   sanitising NUL will let 48+ sessions sync on the next run. No decision needed
   unless you want to inspect the two affected archive files first.

4. **D4 — the tripwire's `Claude-Session` exemption. DECIDED 2026-09-10: keep.** A Claude-session
   commit that credits the Codex agent as co-author (every reviewed patch)
   would otherwise trip the wire on every machine until acked there, since
   the ack file is per machine. The exemption is a one-line opt-out that
   Codex could add to its own commits; it guards against mistakes, not an
   adversary (a Codex author identity is still flagged). Options: keep it
   (recommended, matching the guardrails-not-obstacles stance), or drop it
   and ack each such commit on each machine.

5. **D5 — should the daily sync push unpushed parent-repository commits
   (S24)? DECIDED 2026-09-10: leave as is.** Today a parent commit with an unchanged data pointer sits
   unpushed until something else pushes. Pushing it would publish whatever
   another session committed but chose not to push. Options: leave as is
   (recommended, since the hub rule is push-after-commit anyway), or push
   when ahead and accept that the sync publishes every local commit.

6. **D6 — purge private names from public git history (H27).** The
   branch tip no longer carries them, but six commits on
   `claude/audit-hook-tests` do, and `main` has carried one third-party name
   in a test fixture since 2026-05-02 (82f5035). Options: (a) rewrite the
   branch (filter-branch or a fresh branch from `main` with the same
   changes) and force-push, then ask GitHub support to drop the orphaned
   commits from their cache — needed for the branch, cheap; (b) also rewrite
   `main` back to May, which invalidates every clone and worktree on both
   machines and needs GitHub support for cached views; or (c) leave `main`'s
   history and replace the fixture in a normal commit (queued in round 3
   either way). Recommendation: (a) now, (c) for `main`, and a standing
   rule for fix agents: fixtures are synthetic, never read from `tasks/`,
   `wiki/`, or the data submodule (added to the shared brief). Whatever is
   decided, PR #115 should be squash-merged so the six commits carrying
   the rows never enter `main`'s history.

7. **W19 — the archive partition month is UTC.** `archive-memories.py:328`
   names the partition from `datetime.now(timezone.utc)`, so a run in the
   first 10-11 hours of a local (AEST/AEDT) month files into the previous
   month. Deterministic and idempotent, so nothing is lost; the question is
   which calendar the partitions should follow. Recommendation: leave UTC
   and say so in the partition README, because every other stamp in the
   system is UTC.
8. **W21 — two writers pin the corpus to the home directory.**
   `archive-memories.CORPUS` and `recover_anchors.CORPUS` are
   `Path.home()`-derived, so an `--apply` from a copy or worktree still
   targets the live store. Deliberate (a worktree must not archive its own
   stub), but it means cwd never sandboxes them. Recommendation: keep, and
   require `--corpus` to be explicit when `PA_DIR` is not the home checkout.

## Fix rounds

- Round 1 (done, 0577648): tranche 0. Re-audited four times: rounds 1b
  (06225a0, 5798dc9), 1c (0f94722), 1d (122c9e3), and 1e (940fb2d).
- Round 2, hooks (done, 300ee10): H2–H4, H8–H13, H15–H18. Re-audit pending.
- Round 2, remainder (four branches, each in its own worktree, reviewed and
  merged by PR after a fresh-agent re-audit): hook tests H5–H7, H20–H22 and
  the checker's tests and two fixes (PR #115, `claude/audit-hook-tests`);
  sync helpers S8, S11, S13–S16, S20 (PR #114, `claude/audit-sync-helpers`);
  sync core S1, S3–S7, S9, S10, S12, S17, S19, S21 (PR #116,
  `claude/audit-sync-writers`); Postgres P1–P10, P12, P14, P16 and the
  `rebuild.log` half of S22 (PR #117, `claude/audit-postgres`).
- Branch re-audits (each a fresh agent; fixes land on the branch before
  merge). Every branch's first pass found at least one critical in the fix
  code itself, which is the protocol's point:
  - PR #114, first pass: the new `commit-data.sh` staging logic latched into
    a silent no-op after a failed run, and glob pathspecs swept lookalike
    files. Fixed (ae35435–689c949). Second pass: the in-progress guard
    missed unmerged index entries with no marker file (a conflicted stash
    pop pushed conflict markers with exit 0); the exit-3 remedy advised the
    very sweep the fix prevents; a stale parent pointer was never bumped.
    Fixed (2e3d616). Third pass: the new pointer bump rolled the pointer
    BACKWARDS when the parent was ahead of the checkout (a pull without a
    submodule update), with exit 0 — a regression in the fix; `data` tracked
    as plain files would have had its contents committed into the public
    parent; the staleness probe was silenced by submodule ignore settings.
    Fixed (0a0a147: forward-only, gitlink-only, SHAs read directly). Fourth
    pass: merge, with the guard moved before the data push and four
    untested guards pinned (d68af93). **Merged as 8c61bb8**; main suite
    1,333.
  - PR #115, first pass: **private content in a public branch** (H27, D6);
    a false comment about cursor advance on harness-only windows; unpinned
    digest constants; loose banner assertions; three checker divergences
    from bash (`$VAR`, trailing backslash, CRLF); deletable checker passes;
    an untested cursor prune; two old tests reading the real scratchpads.
    Tip purged (41ae79b); the rest fixed in ten commits (2d36e39–5c1e7a1;
    the agent also desensitised three older fixtures with collaborator
    names). Second pass: no critical; the new cursor advance could drop a
    pending slash-command skip and re-extract a `/remember` response
    (being fixed); two archiver commit tests depended on the operator's
    `~/.gitconfig` (fixed on main, b25fe3e); CR-only `.env` files now
    parse wrongly and backtick/`&` values go unflagged (being fixed); the
    desensitised fixture still reads as this week's house move. Third
    round (48736e9–1b96351): all fixed; the agent's sweep also found six
    more fixtures in the same file carrying the real focus slot verbatim
    (project, slug, rotation date, the prose deadline and its client),
    several from its own earlier work — all replaced by an invented 2024
    equipment log. `tests/test_digest.py` and `tests/test_retrieval_hook.py`
    carry project slugs the repository names openly (left);
    `tests/test_zotero.py` carries published author surnames from a
    bibliographic fixture (Shawn's call). Third pass: **do not merge as
    is** — the pending-skip guard covered only the empty-window advance; the
    two non-empty advances still step past a trailing command (H28, now
    being fixed with the safe-advance design); a subagent assistant entry
    consumes the skip flag; the substitution guard checks the opening
    quote, so `A='abc'$(id)` (which bash executes) is unreported; no test
    covers a file without a trailing newline (dropping `|$` from the line
    splitter silences the whole parse); `tests/conftest.py` still carries
    the real focus slots and an institution. Fourth round done
    (c6087ff–fc03226): the safe-advance position on all three cursor
    writes (six tests including a two-firing run); subagent entries dropped
    before the command branch; the checker guards on the closing quote,
    adds `<`/`>`, scopes the operator scan to the value before a comment,
    and decodes a BOM; `conftest.py` fixtures retired. Fourth pass:
    **hold** — the safe-advance position regresses on `[real, /cmd,
    real-user]`: the later message is extracted but the cursor stays
    behind it, so it is re-extracted every firing (a live shape). Fifth
    round running: the cursor record persists the pending-skip state
    per session, so the cursor always advances to the last processed
    entry and the skip carries over; a legacy cursor sitting on a command
    entry sets the flag; tab-delimited comments; two untested lines
    pinned. Fifth round done (943da8d–453625c). Fifth pass: **no
    critical; merge after one fix** — the comment-start regex used `\s`,
    wider than bash's blanks, so a vertical tab before `#` muted the
    operator scan; plus four surviving mutations, a non-dict cursor file
    crashing the hook, and eight older tests reading the operator's real
    memory store into a prompt. Sixth round done (33d9102–8efa1e6; suite
    1,487 measured three times). Final narrow pass: no critical, nothing
    touches the live store; two mediums of the branch's own classes
    remain — the `^#` comment alternative is wrong (bash starts a comment
    only at a word start, so `A=#c>z` lost its redirect finding) and a
    malformed content BLOCK still crashes the hook — plus backslash parity
    in the lookbehind and the sibling blank-class assumption in the
    whitespace check. Closing round done (ef3fa0d, 6e86f91; the
    coordinator reviewed the diff). **Squash-merged as b0f3269**; main
    suite 1,555; no private row on `main`. The branch on GitHub still
    carries the six commits (D6). Design note worth keeping: the first two cursor fixes each
    satisfied one invariant by breaking another because they stored two
    facts (position, pending skip) in one pointer; only separating them
    satisfies all four. Merge strategy: squash, so the six commits
    carrying private rows never enter `main`'s history; the branch itself
    is D6.
  - PR #116, first pass: **two new criticals** — on a detached HEAD the S5
    guard pushes a second stash and only one is popped, so a run that
    reports success leaves the day's appends in a stash (the very loss
    class the branch closes); and the append-only block stages an unmerged
    `memories.jsonl`, so conflict markers left by the S3 abort are committed
    by the next run and published by the S1 push. Plus: the S1 bump goes
    ahead when `origin/main` is absent; a parent stash-pop conflict has no
    gate; one commit body over-claims its mutation kills. Fixed
    (221acd4–ca10efa): every stash is tracked by SHA and popped
    oldest-first (the boolean flags are gone); an unmerged memory file is
    refused with a gate; the bump is withheld when `origin/main` is absent;
    the trigger survives an unset `HOME`. Second pass: **two more
    criticals in the round-two fixes** — a stash pop that is refused (two
    stashes touching one file) rather than conflicted orphans the remainder
    with no gate and the next run exits 0; the marker check reads the index,
    so a marker-laden memory file that has been `git add`ed (which the gate
    text itself advises) is committed and published. Plus: `push_stash` can
    return a foreign stash's SHA; `daily-sync.sh` itself still dies on an
    unset `HOME`; seven mutations of the round's own stash logic survive
    the suite (the SHA resolution is untested). Third round done
    (409e848–fd02e2f), briefed as invariants: a run never exits with its
    own stash unrecovered without naming it in the gate; no memory file
    whose content holds a marker line is staged at any of the five sites;
    only a run's own stashes are popped or dropped; an unusable `HOME`
    fails at the start; orphans recovered by SHA; all seven surviving
    mutations killed. Third pass: merge after fixing two — diff3/zdiff3
    `|||||||` markers pass the content check and the resolver keeps them
    (a corpus with one reached origin, exit 0, clean gate; no such config
    is set on either machine today); a resolved data conflict latches off
    the parent-half stash restore. Also: five new mutations survive (the
    marker regex, the file loop, two of the five refusal sites, orphan pop
    by selector); every `fail` on the rebase and push paths wedges the
    sync with no gate line; the marker re-scan runs after `rebase
    --abort`. Fourth round done (bb029fd–9ebbbd7): diff3/zdiff3 markers
    recognised and the base section dropped whole (stripping only the
    marker line resurrected records both machines had deleted); the latch
    reset; `fail` itself gates every non-zero exit; the marker list
    captured before the abort; orphans applied by commit; a non-existent
    `HOME` refused; the five surviving mutations killed. Suite 1,398.
    Fourth pass: **do not merge** — two more criticals in the round-four
    fixes: the resolver's new base-section handling truncates a file to
    the end on a stray `|||||||` line outside any conflict block (and the
    gate text tells the operator to run that resolver); the post-resolver
    stash drop uses a selector resolved before the pop, and a concurrent
    drop in that window destroyed another session's stash with exit 0.
    Also: `fail` skips its gate line after a non-fatal gate; the trigger's
    `mkdir -p` creates a phantom `HOME` before the sync's guard can refuse
    it; the orphan apply-by-commit fix has no discriminating test;
    `--dry-run` now writes a gate. Thirty-six real merge conflicts across
    three conflict styles resolved correctly otherwise. Fifth round done
    (cef4743–daf5d7d; suite 1,414): the resolver is positional and leaves
    a file with only stray marker-shaped lines byte-identical; `git stash
    pop` is gone from the script — every restore applies by commit and
    re-resolves the selector at the drop; every failure reason appends to
    the gate; the trigger checks `HOME` first and prints the diagnosis on
    stdout; a dry run never gates. Fifth pass: **do not merge** — three
    criticals in the round-five fixes: the gate now duplicates its
    paragraph on every failing run (nothing resets it); the guard and the
    resolver still disagree on "has markers", so a corpus with a lone
    `=======` wedges behind advice to run a resolver that then skips it;
    a nested conflict is rewritten with live markers left in and reported
    as resolved. Plus: the diff3 base section is dropped only to its first
    `=======`; a failed drop after a successful apply is gated as
    "unrecovered" work (popping it again would duplicate records); eight
    call sites still truncate the gate. Sixth round running: the gate is
    rendered once at exit from an in-run list; guard and resolver share
    one marker predicate; an unbalanced block structure is refused.
    Sixth round done (3530620–a2c84f5, merged with main as 4b451a2; suite
    1,704): the gate is built in memory and rendered once from the EXIT
    handler; the guard calls the resolver's new `--check` mode; unbalanced
    structures exit 3 untouched; the separator is the last `=======`
    before the closer; applied work is never called unrecovered; one relay
    header; an unwritable lock surfaced. Sixth pass: **do not merge** —
    three new criticals in the round-six wiring: the exit-time render
    writes `0` over a live gate on lock contention, SIGTERM, or SIGINT
    (and a test pinned that design); a resolver crash exits 1, which the
    guard reads as "resolvable" and gates the traceback as marker lines;
    a missing venv interpreter accuses a clean corpus. Plus: a conflicted
    apply is still told to pop; the `applied` classification is untested;
    a THEIRS line that is literally `=======` is deleted under the
    last-separator rule; a vanished file reads as "manual". Seventh
    round running: the gate is cleared only where the run completed;
    `--check` has its own failure code and the guard maps only 0/1/3 to
    corpus verdicts; the interpreter is verified first. Seventh round
    done (9a58f13–17f5aeb; suite 1,718): all three fixed as briefed;
    signals exit 130/143 and append an interruption line; a
    conflicted-then-abandoned apply is a third state; a block with more
    than one separator is refused; and the agent found the corpus guard
    was being called inside `$(...)`, so its gate details were discarded
    and its `fail` exited only the subshell — now an array in the main
    shell. Seventh pass: **merge after fixing two** — the third state was
    added on the data half only (a conflicted parent apply is still told
    to pop, and a test pinned that advice); the exit handler re-applies a
    stash the run already applied when its drop failed, leaving markers
    in the live corpus with exit 0. Plus: a run killed mid-rebase is
    misdiagnosed by every later run; the third-state advice survives one
    run; every marker fixture puts its problem on a single-digit line, so
    narrowing the line-number regex publishes markers with the suite
    green; the checker's broad exception handler is untested. Eighth
    round done (1fa64df, 99b7672; suite 1,727): the parent half has the
    third state and distinguishes a refused from a conflicted apply; the
    exit handler never re-applies what the run applied; an in-progress
    rebase, merge, or unmerged tree is named at the start; a failing run
    keeps the previous interruption line; the guard and the interrupted
    check run before orphan reconciliation; the marker parser fails
    closed (tested at line 13); the resolver runs under `timeout 60`.
    Eighth pass: **do not merge** — the exit handler can itself create a
    conflicted apply without classifying it (so the gate says pop for a
    tree holding markers); the new interrupted-state advice orders the
    deletion of an unnamed stash before orphan reconciliation has run;
    the parent repository is never checked for in-progress state; `git
    am`, a resolved-but-uncommitted merge, cherry-pick, and revert get the
    wrong command; the completion flag and the start-of-run guard are
    untested. Ninth round running: classify a conflicted restore; name
    every stash by SHA and only claim "in the tree" for a proven applied
    one; check both repositories; per-operation commands. Ninth round
    done (43b08ea; suite 1,743): a failed restore is classified; a run
    records what it did to its stashes in `~/.cache/daily-sync-stash-state`
    so the next run names only a proven one and lists the rest without
    condemning them; both repositories checked; `git am`, cherry-pick,
    revert, and resolved-but-uncommitted operations get the right
    command; the completion flag and the start-of-run guard pinned; a
    missing tool reported as missing. Ninth pass: **do not merge** — the
    exit handler classifies a restore by scanning the whole repository,
    so after the first conflict every later stash is branded conflicted
    and condemned (the only-copy harm the round removed elsewhere), and
    the new sidecar carries that misattribution to the next run and never
    expires; a bisect is derailed by the branch guard; the parent check
    now blocks the data half; a backtick in the new gate text executes
    `timeout`; the sidecar's write side and the conflicted-versus-refused
    discrimination are untested. Tenth round running: per-apply
    classification from an unmerged-path snapshot before and after each
    apply (with a third "blocked" outcome); sidecar rows carry the paths
    a stash produced and expire with the entry. Tenth round done
    (2bfe6e5; suite 1,754): per-apply classification with a "blocked"
    outcome; a resolved conflict outranks an abandoned one; sidecar rows
    carry repo, SHA, state, and paths; attribution needs a path
    intersection; a later word about a SHA supersedes; a bisect stops
    the sync without moving HEAD; the parent check no longer blocks the
    data half; the backtick removed. Tenth pass running, asked to weigh
    what remains. Both machines at 17:05: corpora pass `--check`, no
    stash, no in-progress operation or bisect in either repository,
    `timeout` present, no `merge.conflictStyle`.
    Tenth pass: **merge** — a strict improvement on every shape tested,
    advice never destructive; one pre-existing critical (S27) and three
    sidecar mediums (S28) open round 3c. **Merged as 0d1d391**; main
    suite 1,786.
  - PR #117, first pass: **a regression class** — `ProgrammingError` and
    `InternalError` (revoked privilege, missing table, aborted transaction)
    were routed to "row refused", so an environment fault would quarantine
    every pending row and advance the cursor with exit 0 where the old code
    held it; the per-row replay lacks a defensive rollback; two of four
    cursor writers still unlocked; the rebuild truncates before resetting
    the cursor with no lock against the cron; `index-session-content.py`
    still lacks NUL sanitising and refused-row handling. Fixed
    (fbddbcc–dafcb20): three-way classification with `ProgrammingError`
    split by SQLSTATE, an all-alike rule, a 200-row quarantine cap, exit 4
    with the cursor held; all four cursor writers locked and atomic; the
    rebuild holds the cursor lock and a sync whose key vanished exits 6;
    the indexer sanitises and skips. Second pass: **do not merge as is** —
    the all-alike rule (prescribed by the coordinator) re-creates P1 on
    correlated poison (two NUL sessions in one batch hold the cursor forever
    with exit 4), and exit 4 reaches nobody (cron discards status; the
    settings hook chain `sessions-sync && indexer` now silently stops the
    indexer); the sessions sync's compare-and-set is untested; a refused
    file is retried and unreported every run; `DiskFull`/`QueryCanceled`
    are `OperationalError` and were routed to "outage, exit 0". Third
    round: classify by SQLSTATE class (22/23 row; 42/53/54/55/57/58/25/0A
    environment; connection-level outage), tunable cap, a
    `postgres-sync-gate` relayed at session start, indexer refusals
    remembered and reported. Done (4183962–dc7f782; the agent also caught
    two of its own tests writing fabricated gate and refusal files under
    the real `~/.cache` and fixed them). Third pass: **block** — one gate
    file, two writers, unconditional clear (either sync's clean, contended,
    or outage run erased the other's alarm within a tick); the indexer's
    remembered refusal made every later run exit 5 forever and `--force`
    never cleared it; a whole batch refused under a data-class SQLSTATE
    (a migration adding a NOT NULL column) still quarantined up to 200 rows
    per tick and advanced with exit 0 and no gate; the new hook chain
    swallowed an archive failure; a cap overflow read as an environment
    fault; five mutations survived (the trigger's gate threshold, the
    archive `&&`, the locked read in both syncs, the cap clamp). Fourth
    round running, briefed as invariants: a gate is cleared only by a full
    successful cycle of the script that raised it; exit 5 only for a
    refusal this run; any quarantine raises a warning gate; five or more
    rows refused alike with no success hold and gate, with a named escape
    hatch. Fourth round done (f276454–fbe17f4): one gate per script,
    cleared only by a completed cycle; exit 5 only for a refusal this
    run, `--force` clears, vanished archives pruned; correlated hold at
    five or more with `--quarantine-anyway`; the hook chain fails on an
    archive failure again; exit 7 for a cap overflow; malformed SQLSTATE
    → environment; transient remedy for classes 40 and 57; a structural
    test pins every gate write to an injectable path after the suite
    wrote a fabricated gate under the real `~/.cache` a third time. Suite
    1,540, measured. Fourth pass: **block** — three criticals of one
    shape: a run that did no work (nothing new to sync; an unmounted
    archive root; a `--project`-scoped indexer run; an empty root that
    made the prune loop wipe the refusal memory) is labelled a completed
    cycle and lowers a gate it learnt nothing about, so the quarantine
    warning self-erases within one tick. Also: the indexer gates nothing
    on exit 3/4; the syncs gate nothing on exit 1/2 (a schema mismatch
    stalls invisibly); a degraded run's quarantines are discarded; a
    persistent outage has no signal at all; the sessions gate policy and
    the memories correlated hold are untested; the structural gate test
    is substring-based. Fifth round running, briefed as one invariant: a
    gate is lowered only by evidence that the fault is gone; absence of
    work is not evidence (an idle outcome that never touches the gate;
    the indexer gate reflects the whole refusal memory; an outage counter
    that gates after three consecutive runs). Fifth round done (suite
    1,573 measured): the rule lives once in `_sync_gate.py`; idle never
    touches a gate; completed needs a processed row; absent or empty
    root is degraded; the indexer gate reflects the whole memory and an
    empty root is refused; exits 1/2 gate; a degraded run's quarantines
    gate; outage streak of three gates; AST structural test; a test-count
    tripwire after a scripted edit silently truncated fourteen tests (the
    agent also reported destroying its own uncommitted work with a
    `git checkout --` and redoing it). Fifth pass running. After merge
    the PreCompact and SessionEnd hook commands in `~/.claude/settings.json`
    on both machines must follow the new template, and `~/cc-archives`
    must be mounted when the sessions sync runs.
    Fifth pass: **do not merge** — four criticals in the gate semantics
    again: a quarantine gate lowered by the next run that processes any
    unrelated row; an outage overwriting the standing reason and any later
    connected run (even contended) clearing both; every degraded outcome
    silent, including a cursor-held stall; an indexer refusal stranded
    forever by a `.gz` swap. Sixth round running, briefed as a state
    machine: per script, independent problems (fault, correlated,
    quarantine, degraded, outage streak, refusals), each with its own
    raise and lower evidence, a rendered gate derived from them, and a
    transition-matrix test.
    Sixth round done (8b1abf7, 4026d9e; suite 1,618): the machine lives
    once in `_sync_gate.py`; a quarantine carries a running count and
    stands until `--ack-quarantine`; an outage lowers only itself; every
    degraded return carries its reason; indexing either transcript form
    forgets a refusal; thirty matrix rows are executable; the AST test
    covers every reader and writer of a gate or its sidecar. Sixth pass:
    **block** — the core transitions hold; three edge defects: the
    acknowledgement ran a full sync and was silently dropped under lock
    contention while logging success; the sidecar is an unlocked,
    non-atomic read-modify-write (a cron tick can resurrect an acked
    quarantine); the indexer gates nothing on a schema mismatch, an import
    failure, or an absent root. Plus: fault coupled to quarantine; indexer
    outages raise a fault an idle run cannot lower; idle runs never report
    connected; the quarantine count tallies attempts, not rows written;
    the matrix-coverage test cannot fail; the AST test is name-based.
    Seventh round done (b4e87fe; suite 1,642): the ack is state-only
    (no sync, no lock, exit 9 if unwritable); every sidecar read-modify-
    write runs under a per-gate flock with atomic writes; a contended run
    touches no state; the indexer gates a schema mismatch and a missing
    driver as faults and an absent root as degraded; a completed run
    lowers a fault regardless of quarantines; indexer outages use the
    streak; the count is rows written; the AST test rejects direct writes;
    the refusal memory is read-only against a foreign root. Seventh pass:
    **do not merge** — the ack reports success and exits 0 when the state
    write fails (its exit-9 test monkeypatched the transition to a no-op);
    the quarantine count still counts duplicates, so a held cursor inflates
    it by the batch every tick; a gate-lock failure changes the script's
    exit code; an outage during the advisory-lock query is an unexpected
    fault, not an outage; degraded returns drop proven connectivity; the
    ack lowers a degraded problem; the AST test is defeated by a one-line
    alias; the trigger cannot see a dead pipeline. Eighth round done
    (aeab185; suite 1,656): the verdict is keyed to what is on disk after
    a re-read inside the lock; only newly written rows reach the count; a
    gate or lock failure never changes an exit code; outages during the
    schema check or lock query feed the streak; the acknowledgement is
    its own event; the AST check resolves aliases; an autouse session
    fixture asserts the suite left nothing under the real `~/.cache`; the
    trigger reports a never-written or stale gate; the flock is bounded.
    Eighth pass: **do not merge** — a mixed slice with one bad line never
    reports its quarantine (the parse-layer count reaches the result only
    on the empty-slice return); the new staleness check fires three false
    alarms after any sleep longer than six hours; two more degraded returns
    still drop connectivity; the indexer takes the gate lock unguarded
    outside the machine; the ack reports success over a half-written gate;
    rows re-refused after an ack and a rebuild count as duplicates and say
    nothing; a lock timeout loses that tick's count; the staleness hours
    variable is an arithmetic-injection sink. Ninth round running: the
    quarantine problem is re-derived from the append-only quarantine file
    against an acked position stored in the sidecar (reset on a cursor
    reset), so no tick can be lost and no delta can be wrong; the
    staleness check is guarded by uptime and boot time. Ninth round done
    (4a1eedf–fe10832; suite 1,704): the quarantine problem is derived from
    the file against an acked position (reset on a cursor reset); staleness
    is asserted only once uptime exceeds the window (a suspend longer than
    the window still reports, since Linux counts suspended time —
    documented); connectivity on every return, enforced by an AST test; the
    indexer's direct lock read is guarded; the ack names which half of a
    partial write failed; the stale-hours override is validated; the
    hermeticity guard covers all eight gate globs and deletions; nine
    mutations killed. Ninth pass: **block** — the acked position is
    computed but never persisted (one line undoes the round's fix); an
    ordinary rebuild without a sync in flight never resets it; a missing
    quarantine file counts as zero and lowers the alarm; the ack on a
    healthy pipeline exits 9 calling an empty sidecar corrupt; the uptime
    amnesty runs before the boot-epoch check; the hermeticity guard blames
    the suite for other processes' writes and would fail at random after
    merge. Tenth round running: persist the acked block; detect a cursor
    reset from the stored last position; per-gate-kind staleness (cron
    gate by age since boot, hook gates by a newer session archive); the
    whole suite runs under a tmp `HOME`. Tenth round done (7a9e488–
    f6893c6, merged with main as 9154cca; suite 2,066 on the merged
    branch): the acked block is persisted (sidecar asserted); a rebuild is
    detected by the cursor moving back; a missing quarantine file is
    unknown; the ack tells missing, clean, and corrupt apart; per-kind
    staleness (cron gate by age since boot with a grace; hook gates by a
    newer session archive); the suite owns its `HOME` from conftest
    import; connectivity checked at every constructor. Tenth pass: **do
    not merge** — a complete quarantine row with no trailing newline is
    seen by the deduper but not by the counter, so it is invisible to the
    gate for ever (a regression from the coordinator's "complete lines
    only" instruction; the invariant is that the two readers agree); a
    string-typed cursor fires one false rebuild and then disables
    detection; the post-boot grace is documented but inert; a symlinked
    or absent archive root silently switches off the hook-gate liveness
    check; one pre-existing unmarked test connects to the live database
    on a plain run. Eleventh round done (d068593–4d56a52; suite 2,121 on
    the merged branch): one parser for the quarantine file shared by the
    gate, the writer, and the health report; cursor types normalised at
    read; the post-boot grace made real; symlinked and absent roots
    handled; the live-database test marked integration with a structural
    guard; five more mutations killed. Eleventh pass running, asked to
    weigh what remains as merge-blocking versus follow-up. Eleventh pass:
    **hold on one item, then merge** — the second quarantine writer never
    repairs a missing separator, so a newline-less row the counter now
    counts is destroyed by the next append (one call to fix); follow-ups:
    the timestamp cursor is not validated (a garbage value idles the
    sessions sync for ever), a fourth quarantine reader is unguarded, a
    negative cursor resets the ack silently. Closing round done (e78211a–fb4f9da; suite 2,163):
    one code path appends to a quarantine file and repairs the separator
    first; the timestamp cursor must parse; the dedup reader is the shared
    parser; a negative cursor is reported. The coordinator reviewed the
    closing diff and reconciled the merge with PR #116 (the trigger sandbox
    now holds a quiet PostgreSQL state). **Merged as 773a0bd**; main suite
    2,362. Live hook commands on both machines updated to the template
    (backups beside `settings.json`). First session after merge reports all
    three gates as never written until each script has run once.
- Round 2 is complete: all five branches merged (#114 8c61bb8, #115
  b0f3269 squash, #116 0d1d391, #117 773a0bd, #118 190bc7c); main suite
  2,362 (from 1,250 at the start). Every branch's first re-audit found at
  least one critical in the fix code itself; the two long branches took
  ten and twelve rounds. Two decisions (D4, D6) and the two behavioural
  decisions (D1, D2) remain Shawn's.
- Round 3: hook-side items H25, H26, H29, H30 and the guard half of S22 are
  on PR #118 (`claude/audit-round3`, suite 1,575). First pass: no critical;
  mergeable after two wording fixes in the digest (the new "nothing verified
  is available" heading was false when the fallback fires on thin coverage;
  "never checked" was false for pending records) and two counter edges (a
  uuid-less trailing command double-counts; the count never decays). Closing
  round done (5ddfb6c–43a4eba: the heading says why the fallback fired;
  pending records are "unchecked or inconclusive"; a uuid-less command arms
  nothing; the owed count is capped at two, under-skipping by design).
  **Merged as 190bc7c**; main suite 1,587. H27's fixture on `main` is done
  (8e2425f). S23 and S26 sit with PR #116; P17 with PR #117;
  Round 3c (S23, S27, S28) is PR #119. Its first re-audit found C1 (the
  partial-stash gate advised a `checkout` that would overwrite the other
  machine's copy: `missing` and `differs` were not distinguished) and
  M1-M5 (orphan partial not persisted; an untracked symlink unrestored for
  ever; a byte-identical collision refused; the shrink check had to run
  before the push of already-committed data; two untested exit-handler
  mutations). Fixed in e91362e-c1f4dd6: per-path `missing`/`differs`
  states with advice that never overwrites a present file (invariant test
  runs every advised command); a fifth apply outcome `applied`;
  `abort_on_published_shrink` before both data pushes (exit 4, resets
  nothing); `reset --mixed`; the shrink report under `logs/`; carry-forward
  examines each entry once. 13 of 13 mutations killed; suite 2,424 with
  main merged (bad919b). The second re-audit refused the merge: the new
  `applied` outcome is a regression (git restores a stash's untracked half
  before its tracked merge, so an apply whose tracked change is refused
  looks "applied" from a status difference and is dropped, losing the only
  copy of the tracked work — deterministic on git 2.48.1), and the advised
  `checkout` for a `missing` path still clobbers an ancestor that is a file
  or a symlink (this repository's root layout). Follow-ups: conflicted
  sidecar rows lost on an early exit; the bulk trailer waving through an
  unrelated truncation in the same range; the shrink guard silent without
  `origin/main`; four surviving mutations. Third round (5b4985c, 3b328a5:
  sidecar written whole or not at all; `applied` only on evidence; ancestor
  check; per-commit trailers; both pushes gated; 15 of 15 mutations killed;
  suite 2,450 with main merged, d08beef). The third re-audit refused again:
  the evidence test compared status LINES, so a concurrent hook write to a
  second tracked path during a refused merge still reads as applied and
  drops the only copy; a legitimate bulk rewrite arriving via a merge
  commit is now a false stop; `grep -c ''` counts NUL bytes as lines.
  Fourth round done (947ac45-bb96d27): `applied` requires the entry's own
  tracked diff to reverse-apply cleanly to the files on disk AND every
  tracked path's status to have moved (binary paths never count as landed);
  a merge is measured against the smallest of its parents; `grep -ac ''`;
  a blob that cannot be counted is exit 4, not zero; the shrink guard
  re-runs between the retry rebase and the retry push; orphaned sidecar
  temps swept under the flock; the real write-failure path tested. 13 of
  13 mutations killed; suite 2,549 with main merged (eca875e). The fourth
  re-audit found nothing blocking and **PR #119 merged as 87db26b** (main
  suite 2,895 after the round-4 merges); M1 (a corpus-less merge parent
  counts as zero; an unattributable shrink fails open — unreachable today)
  and four lows are round 3c-5, **PR #132, merged** (an unjudgeable merge
  refused, the sweep marker, renames, and a real find: `| grep -q` under
  `pipefail` returns 141 on a long message with the trailer at the top, so a
  legitimate bulk-trailered archive run could be refused and, at the commit
  site, reset — both push gates now read the text; the re-audit reproduced
  all seven merge shapes and found nothing that can lose data; seven lows
  (the source contract pins the helpers not the call sites; a gate-line
  class arm and the sweep glob uncoupled from their writers; the loop stops
  at the first corpus-less merge; quoted rename paths; four bounded
  `| grep -q` remain; old markers not migrated) are round 3c-6, now **PR #135**
  (a whole-file lint with no allow-list, `--porcelain=v1 -z` so paths with
  spaces are measurable — the SUSPECTED item confirmed — an unmeasurable merge
  recorded rather than stopping the scan; **merged** after a re-audit that
  verified all four conversions semantically identical; round 3c-7 takes
  the last lows: an unjudgeable merge beside a trailered shrink publishes
  unrecorded, the lint misses a pipe written as a trailing operator, its
  vacuity guard is a count, `render_sync_gate` supersession untested, a
  newline in a path splits the record stream).
- Round 3b (`surfacing_log.py`, S22's third member, plus the eleventh
  re-audit's follow-ups L1 and L6 from PR #117) is **PR #120, merged
  69a7590**; main suite 2,372. Four fixes (bab4990 lazy log path, 01efef0
  named message constants, 5a59bf6 `utf-8-sig`, 99586fe future gate stamp).
  Its re-audit: no critical; one merge-blocking flake (the future-stamp
  test asserted `120m` where a fractional fixture mtime truncates to 119
  about once in a hundred runs) and two follow-ups fixed before merge
  (18489e5: the clamp after the future-stamp report changes no outcome,
  so the comment and docstring now call it belt-and-braces; the
  live-resource guard's `pytest.mark` clause gained the case that kills
  deleting it). Verified live: the suite run from the worktree with the
  real `HOME` left `data/logs/surfaced.log` unchanged (md5 before and
  after), so S22 is closed on all three members. **Carried as
  follow-ups (round 4 material):** (i) the `__file__`-derived log-default
  shape survives in over a dozen scripts, mitigated only by per-test
  monkeypatching (13 by `grep -l __file__ scripts/*.py hooks/*.py` filtered
  to a `logs/` path; the 3b agent's wider sweep counted about seventeen);
  the suite triggers none of them (whole-tree snapshot before and after a
  full run); (ii) the two readers, `scripts/surfacing_stats.py:42` and
  `scripts/memory-health-report.py:71-73`, derive the path from `PA_DIR`
  and ignore `PA_SURFACED_LOG`, so an overridden writer and the readers
  disagree; (iii) `utf-8-sig` strips only a stream-leading byte-order
  mark — a mark mid-file (only a non-Python tool writes one) still hides
  the record after it and defeats the dedup, re-appending it; (iv) the
  shell's own `REFUSED` wording in `scripts/daily-sync.sh` is not tied to
  `_sync_gate.QUARANTINE_REFUSED_WORD`; (v) a gate stamped persistently
  in the future (clock stepped back and never corrected) keeps the
  staleness rule off — the banner says so and the next cron write heals
  it, but it is disclosed rather than caught; (vi) dormancy under pytest
  is silent: a production process that happens to import `pytest` would
  lose the surfacing log without a diagnostic.
- Tranches 3b, 3c, 4, 5, and 6 ran on 2026-09-08/09 against corrected code
  (sections above); tranches 7 and 8 (the memory readers and the
  style-analyser scripts) have their Lens A sections above and Lens B running.
  Every script under `scripts/` and `hooks/` is now covered by a tranche.
