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
| `check-credentials.py` has no tests | **round 2** (branch `claude/audit-hook-tests`; Lens B supplied the case list) |
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
| 7 | Checker misses `NAME= value` (bash runs the secret as a command with NAME empty) | **round 2** (branch `claude/audit-hook-tests`, with the checker's first tests) |
| 8 | Checker's `quoted` guard turned `TOKEN='abc' # comment` from a true positive into a silent false negative | **round 2** (same branch) |
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
| H5 (B) | `extraction-hook.py:1021,1145` — the persistence path is untested: truncating the store on every session close, or never writing, passes 1,208 tests; `tests/test_jsonl_flock.py` re-implements the append instead of importing it. | CONFIRMED (mutations survived) | **round 2** (branch `claude/audit-hook-tests`) (test `append_memories` and a successful `main()` end to end, asserting bytes appended) |
| H6 (B) | `session-start-accountability.py:265` — `build_banner()` can return a constant; the counts can be swapped; slot delimiters can vanish; all green. | CONFIRMED | **round 2** (branch `claude/audit-hook-tests`) (banner tests) |
| H7 (B) | `session-start-retrieval.py:1262` — on this machine the digest path is live and the tests assert only scaffolding; the digest can surface zero memories with tests green. The autouse fixture forces all machine flags off, so the suite tests the path this machine no longer takes. | CONFIRMED | **round 2** (branch `claude/audit-hook-tests`) |

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
| H20 (B) | No output bound pinned in the retrieval suite; the one cap test uses exactly the cap | **round 2** (branch `claude/audit-hook-tests`) |
| H21 (B) | Flock guards in extraction removable with tests green; no double-firing test | **round 2** (branch `claude/audit-hook-tests`) (test `main()` twice) |
| H22 (B) | `isMeta` / `isSidechain` entries are fed to the model as user turns; fixtures never carry them | **round 2** (branch `claude/audit-hook-tests`) (filter; fixture from a real transcript shape) |
| H23 (B) | Project-id encodings diverge on dotted segments between writer and reader (latent) | deferred |
| H24 (B) | code-state sidecar contract pinned only by a hand-built fixture in another repo | tied to H2 |
| H25 | `scripts/digest.py:432,536,546` — `rank_fallback` admits anchored `verified: "false"` records and renders them under the heading "Verified-true entries", above the anti-confabulation line saying such content is not surfaced (CONFIRMED by the round-two agent; `tests/test_digest.py:214,323` pin it as deliberate) | **next** (after PR #115 merges: exclude disproved records from the fallback or head them honestly) |
| H26 | `hooks/session-start-accountability.py:100` — `^~~.+?~~` needs the strikethrough to close inside the first cell; two live done rows close it in the last cell and count as open (23 detected, 2 missed) | **next** (a first cell that opens with `~~` is struck) |
| H27 | **Private content in a public branch.** The round-two agent's banner fixtures on `claude/audit-hook-tests` (PR #115) copied rows from the private `tasks/waiting-for.md` and inbox — third-party names, a family-law item, a supplier, a car — into `tests/test_accountability_hook.py`, and the branch was pushed to the public repository (CONFIRMED by the branch's re-audit, 2026-09-08). One such name has been on `main` since commit 82f5035 (2026-05-02, line 122). | branch tip fixed with synthetic fixtures (normal commit); the history rewrite and force-push, and the `main` history, are **decision D6** |

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
| S1 | `scripts/daily-sync.sh:510-577` — a data-submodule commit made while the tree is clean afterwards is never pushed, but the parent pointer bump that references it IS pushed: origin points at a commit the other machine cannot fetch. Happened today at 09:29. `monthly-archive.py:522-539` already works around this locally. | CONFIRMED from `logs/daily-sync.log` and `git ls-tree` | **round 2** (branch `claude/audit-sync-writers`) (push whenever `HEAD` is ahead of `@{u}`) |
| S2 | `daily-sync.sh:512` — `git add -A` after the stash pop sweeps concurrent sessions' half-written prose into an automated commit and pushes it (`e433eee`, `549d9aa`), contradicting the script's own comment and the hub rule. | CONFIRMED from history | **decision** — the daily sync is also how scratchpad and notes *appends* get committed; Shawn rules which paths the auto-commit may take |
| S3 | `daily-sync.sh:475-501` — stash-pop conflicts feed every conflicted path, prose included, to the line-union resolver; a conflicted `wiki/continuity.md` is rewritten as an interleaved union. The rebase path partitions correctly. | CONFIRMED by reading both paths | **round 2** (branch `claude/audit-sync-writers`) (partition like the rebase path; abort on prose) |
| S4 | `daily-sync.sh:196,287` — `git checkout --ours` during a rebase takes origin's side, the opposite of the comment's intent (git-checkout(1)). | CONFIRMED against git documentation | **round 2** (branch `claude/audit-sync-writers`) (`--theirs`, both sites) |
| S5 | `daily-sync.sh:358,405-423` run before the detached-HEAD guard at 438-445; on a detached HEAD the memory commit and the archive commit are orphaned and the working tree reverted. Likely trigger: `sync-symlinks.sh:126 git submodule update` detaching HEAD. | CONFIRMED by ordering; trigger SUSPECTED | **round 2** (branch `claude/audit-sync-writers`) (move the guard above every commit site) |
| S6 (B) | `scripts/resolve-merge-conflicts.py` has zero tests; keeping only "ours" passes the whole suite. | CONFIRMED | **round 2** (branch `claude/audit-sync-writers`) (tests with real conflict markers) |
| S7 (B) | `scripts/daily-sync-trigger.sh` has zero tests; "never runs again" and "breaks the hook chain" both pass. | CONFIRMED | **round 2** (branch `claude/audit-sync-writers`) |
| S8 (B) | `archive-memories.py::apply_archive` untested: evicting without archiving, or archiving without evicting, passes. `monthly-archive.py::_apply` halts removable with tests green. | CONFIRMED | **round 2** (branch `claude/audit-sync-helpers`) |

### Medium (sync)

| # | Finding | Disposition |
|---|---|---|
| S9 | Archiver call lacks a `DRY_RUN` guard; `--dry-run` commits | **round 2** (branch `claude/audit-sync-writers`) |
| S10 | Two Syncthing gate-file layouts; the trigger reads one; the early-exit path renders a headerless problem | **round 2** (branch `claude/audit-sync-writers`) |
| S11 | `sync-symlinks.sh:97` `ln -sf` on a symlink-to-directory writes inside it; needs `-sfn` | **round 2** (branch `claude/audit-sync-helpers`) |
| S12 | Resolver: a valid-JSON non-object line raises `AttributeError`, aborting the sync with a conflicted tree | **round 2** (branch `claude/audit-sync-writers`) |
| S13 | `compose-global-claude-md.sh:102` truncates `~/.claude/CLAUDE.md` before writing | **round 2** (branch `claude/audit-sync-helpers`) (temp + `mv`) |
| S14 | `push-archives-to-r2.sh:91` version probe kills the script under `pipefail` | **round 2** (branch `claude/audit-sync-helpers`) |
| S15 | `archive-memories.py:369-373` releases the flock before its commit | **round 2** (branch `claude/audit-sync-helpers`) |
| S16 | `archive-memories.py:413`, `commit-data.sh:49,58` commit without a pathspec | **round 2** (branch `claude/audit-sync-helpers`) |
| S17 | A conflicted orphan-stash pop wedges every later session with no gate line | **round 2** (branch `claude/audit-sync-writers`) (gate line) |
| S18 | Syncthing SSH probe runs inside the 90 s SessionStart budget | deferred |
| S19 | Unchecked `exec` redirect and `cd` misreported as lock contention | **round 2** (branch `claude/audit-sync-writers`) |
| S20 (B) | Explicit-pathspec contract untested for the data-submodule committers; `commit-data.sh` lock and branch guard removable | **round 2** (branch `claude/audit-sync-helpers`) |
| S21 (B) | The end-to-end fixture would, if repaired, run `sync-symlinks.sh` against the real `~/.claude/settings.json` and rsync/R2 against real archives; pin `HOME` first | **round 2** (branch `claude/audit-sync-writers`) (before any fixture repair) |
| S22 | The suite writes into the live private submodule through the `logs → data/logs` symlink: `scripts/_bulk_rewrite_guard.py:76` and `scripts/rebuild-postgres.py:204` (fixed on PR #117) (CONFIRMED by three round-two agents; `rebuild.log` grew during today's runs; the guard opens its file handler at import) | **next** (pin both log paths in tests; `rebuild.log` on the Postgres branch) |
| S23 | `daily-sync.sh` shrink detector checks only the auto-sync commit; a truncation already on disk is committed by the earlier append-only block unguarded (SUSPECTED, round-two agent) | **next** (round 3) |
| S24 | The parent repository has S1's hole: an unpushed parent commit with an unchanged data pointer is never pushed (CONFIRMED) | **decision** (pushing would publish another session's parent commits; see D5) |
| S25 | `resolve_rebase_conflicts`'s submodule branch is unreachable (only called for the data repository, which holds no gitlink) | deferred (dead code, harmless) |
| S26 | The rebase-abort path leaves a divergence every later run re-hits, with no gate line (S17's class) | **next** (round 3) |
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
| P1 | `scripts/sync-sessions-to-postgres.py:543-552,652-658` — every `psycopg2.Error` is reported as "PostgreSQL may be down" and the cursor held. Two archive metadata files carry a NUL in LLM-generated narrative; Postgres rejects ` ` in jsonb; the `sessions` table has been stale since 2026-08-17 with 48 sessions unsynced and the wrong diagnosis in the log. | CONFIRMED live | **round 2** (branch `claude/audit-postgres`) (split outage from data errors; quarantine the row; per-row fallback after a failed batch; sanitise NUL at ingest) |
| P2 | `scripts/sync-to-postgres.py:656-665,950-954,312` — same conflation in the memories path; `created_at` unguarded (`TIMESTAMPTZ NOT NULL`); a NUL in content raises `ValueError` outside the handler. | CONFIRMED by reading; free-text dates have reached `deadline_at` repeatedly | **round 2** (branch `claude/audit-postgres`) |
| P3 | `scripts/embed.py:37` — `OLLAMA_BASE_URL=""` from `ollama-endpoint.sh`'s failure path yields `ValueError: unknown url type` outside the degradation ladder; the documented fallback does not exist. | CONFIRMED by repro | **round 2** (branch `claude/audit-postgres`) (`or` default; fix the wrapper's comment) |

### Medium (Postgres)

| # | Finding | Disposition |
|---|---|---|
| P4 | `rebuild-postgres.py` never truncates `session_chunks` | **round 2** (branch `claude/audit-postgres`) |
| P5 | `index-session-content.py` has no schema-version guard and tracebacks on an outage | **round 2** (branch `claude/audit-postgres`) |
| P6 | `backfill-embeddings.py --limit` not honoured (200 embedded for `--limit 5`) | **round 2** (branch `claude/audit-postgres`) |
| P7 | `backfill-embeddings.py --catch-up` tracebacks on a DB error mid-batch | **round 2** (branch `claude/audit-postgres`) |
| P8 | `check-memory-drift.py --recover` resurrects soft-deleted memories (`is_active` and history fields not selected) | **round 2** (branch `claude/audit-postgres`) |
| P9 | `check-memory-drift.py:298` is the only canonical writer without the flock | **round 2** (branch `claude/audit-postgres`) |
| P10 | `.get(key, default)` on a NOT NULL column right after the comment warning against it | **round 2** (branch `claude/audit-postgres`) |
| P11 | Sessions cursor is naive local time compared lexicographically; a clock step back skips sessions forever | deferred (document `--full-resync`; fix with UTC when the archive format changes) |
| P12 | No embedding-dimension validation; a wrong-dimension model re-embeds the same rows forever with a warning | **round 2** (branch `claude/audit-postgres`) (check `len == 768` once) |
| P13 | Two quarantine record shapes in one file; dedup sees one | deferred |
| P14 | Poison lines re-quarantined every 5 minutes while the cursor is halted | **round 2** (branch `claude/audit-postgres`) (dedup before append) |
| P15 | Drift recovery pulls the whole table to filter in Python | deferred |
| P16 | Three processes read-modify-write `sync-cursors.json` without lock or atomic rename | **round 2** (branch `claude/audit-postgres`) (atomic write; the memories sync already has the flock pattern) |
| P17 | `scripts/sync-to-zotero.py:129` is the third writer of `sync-cursors.json` and still writes unlocked and non-atomically; P16 protects the other two (CONFIRMED, round-two agent) | **next** (external-services tranche, or round 3) |

Lows recorded: three constant f-string SQL sites; handler stacking; `tool_calls:
0` stored as NULL; 235 MB steady-state RSS per 5-minute tick; `split()` vs
`splitlines()`; id-less stash lines; U+2028 latent; stale comments; docstring
"bounded memory" claim.

## Decisions for Shawn

1. **H1 — extraction drops everything before the last 30 messages.** Fix is to
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

4. **D4 — the tripwire's `Claude-Session` exemption.** A Claude-session
   commit that credits the Codex agent as co-author (every reviewed patch)
   would otherwise trip the wire on every machine until acked there, since
   the ack file is per machine. The exemption is a one-line opt-out that
   Codex could add to its own commits; it guards against mistakes, not an
   adversary (a Codex author identity is still flagged). Options: keep it
   (recommended, matching the guardrails-not-obstacles stance), or drop it
   and ack each such commit on each machine.

5. **D5 — should the daily sync push unpushed parent-repository commits
   (S24)?** Today a parent commit with an unchanged data pointer sits
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
   `wiki/`, or the data submodule (added to the shared brief).

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
    Fixed (0a0a147: forward-only, gitlink-only, SHAs read directly). Fourth,
    narrow pass running.
  - PR #115, first pass: **private content in a public branch** (H27, D6);
    a false comment about cursor advance on harness-only windows; unpinned
    digest constants; loose banner assertions; three checker divergences
    from bash (`$VAR`, trailing backslash, CRLF); deletable checker passes;
    an untested cursor prune; two old tests reading the real scratchpads.
    Tip purged (41ae79b); the rest fixed in ten commits (2d36e39–5c1e7a1;
    the agent also desensitised three older fixtures with collaborator
    names). Second pass running. `tests/test_zotero.py` carries published
    author surnames from a bibliographic fixture; Shawn's call.
  - PR #116, first pass: **two new criticals** — on a detached HEAD the S5
    guard pushes a second stash and only one is popped, so a run that
    reports success leaves the day's appends in a stash (the very loss
    class the branch closes); and the append-only block stages an unmerged
    `memories.jsonl`, so conflict markers left by the S3 abort are committed
    by the next run and published by the S1 push. Plus: the S1 bump goes
    ahead when `origin/main` is absent; a parent stash-pop conflict has no
    gate; one commit body over-claims its mutation kills. Being fixed on
    the branch.
  - PR #117, first pass: **a regression class** — `ProgrammingError` and
    `InternalError` (revoked privilege, missing table, aborted transaction)
    were routed to "row refused", so an environment fault would quarantine
    every pending row and advance the cursor with exit 0 where the old code
    held it; the per-row replay lacks a defensive rollback; two of four
    cursor writers still unlocked; the rebuild truncates before resetting
    the cursor with no lock against the cron; `index-session-content.py`
    still lacks NUL sanitising and refused-row handling. Being fixed on the
    branch.
- Round 3 (queued, on main after the branches merge): H25, H26, H27 (the
  fixture on `main`), S22 (the guard's import-time handler), S23, S26, P17.
- Remaining tranches (3b, 3c, 4a, 4b, 5a, 5b, 6) run after round 2 lands, so
  their findings arrive against corrected code.
