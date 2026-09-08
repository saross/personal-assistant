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

## Tranche 0 — code written 7–8 Sep (agent mail, tripwire, archiver, credential checker, admission verifier)

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
| `check-credentials.py` has no tests | **next** (Lens B supplied the case list) |
| Tripwire never examines local `main` when `origin/main` resolves | deferred (the token pushes to origin; a local-only Codex commit is not the threat) |
| Archiver sort key mixes `Date:` and `sent` formats | deferred (deterministic; all live headers are ISO) |

## Tranche 1 — session hooks

Lens A: 4 critical, 12 medium, 12 low. Lens B: 57 mutations, 38 survived.

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| H1 | `hooks/extraction-hook.py:601,1148` — only the last 30 messages of a window go to the model, but the cursor advances past the whole window: everything before the tail is lost forever. 471 of 9,095 firings (5.2%) had >30 messages; the largest dropped 254. | CONFIRMED from `data/logs/extraction.log` | **decision** — chunk the window (more Haiku calls per firing, cheap) or raise the cap; either changes API spend, so Shawn approves |
| H2 | `hooks/session-start-code-state.py:128-136` — `commit_at_start` overwritten on resume/compact (same session id); 37 of 42 multi-write sessions recorded a changed commit. | CONFIRMED from the sidecar log | **next** (first write wins) |
| H3 | `hooks/session-start-retrieval.py:644-667,821-862` — the legacy four-bucket path surfaces `verified: "false"` memories as fact; 738 such records, 401 in permanent categories; the digest path filters, the legacy path does not. | CONFIRMED (grep: `verified` read nowhere in retrieval) | **next** (apply the stated anti-confabulation rule on the legacy path) |
| H4 | `scripts/_command_markers.py:61-62` — `/forget` and `/update` markers no longer match their command headers, so those exchanges (which contain the deleted/superseded memory text) are re-extracted. | CONFIRMED against `commands/*.md` | **next** (fix markers; derive the test fixture from `commands/*.md`) |
| H5 (B) | `extraction-hook.py:1021,1145` — the persistence path is untested: truncating the store on every session close, or never writing, passes 1,208 tests; `tests/test_jsonl_flock.py` re-implements the append instead of importing it. | CONFIRMED (mutations survived) | **next** (test `append_memories` and a successful `main()` end to end, asserting bytes appended) |
| H6 (B) | `session-start-accountability.py:265` — `build_banner()` can return a constant; the counts can be swapped; slot delimiters can vanish; all green. | CONFIRMED | **next** (banner tests) |
| H7 (B) | `session-start-retrieval.py:1262` — on this machine the digest path is live and the tests assert only scaffolding; the digest can surface zero memories with tests green. The autouse fixture forces all machine flags off, so the suite tests the path this machine no longer takes. | CONFIRMED | **next** |

### Medium (hooks)

| # | Finding | Disposition |
|---|---|---|
| H8 | Accountability strikethrough regex needs the whole first cell struck; live rows append a project tag, so 23 of 25 done rows count as open; banner says 58, truth ~35 | **next** (match `^~~.+~~` anywhere in the cell; the test that asserts the opposite is changed with it) |
| H9 | Accountability `Started:` regex misses the live `- **Rotated in:**` field; no slot ever gets a day counter | **next** |
| H10 | Accountability prose deadline reads as "no deadline"; unparseable ≠ absent | **next** (report "deadline not parsed") |
| H11 | Extraction skip-flag consumed by a tool-only assistant entry (52 of 585 cases) — command responses survive into extraction | **next** |
| H12 | Extraction crashes at import when `data/` is uninitialised (`logs` symlink dangles) | **next** |
| H13 | "Prefer existing tags" prompt gets the alphabetical head of a 56,698-line vocabulary | **next** (seed from the most common tags in recent records) |
| H14 | `source_message_uuid` may be a non-message entry and is not "last included" | tied to H1 |
| H15 | `MAX_LOAD_RECORDS = 50000` vs 42,291 records today; binds in ~8 weeks; comments stale | **next** (raise; fix comments) |
| H16 | Cursor advances past "too short" and "parse failed" windows (736 so far) | **next** (do not advance on either; short windows accumulate) |
| H17 | Locale-dependent `read_text()` in five places; no top-level guard in retrieval `main()` | **next** |
| H18 | Vocabulary updated inside `format_memories`, before the append that may fail | **next** (move after append) |
| H19 | Anchor verification can spawn up to 72 git subprocesses per unresolved anchor inside a 30 s hook | deferred (measure first) |
| H20 (B) | No output bound pinned in the retrieval suite; the one cap test uses exactly the cap | **next** |
| H21 (B) | Flock guards in extraction removable with tests green; no double-firing test | **next** (test `main()` twice) |
| H22 (B) | `isMeta` / `isSidechain` entries are fed to the model as user turns; fixtures never carry them | **next** (filter; fixture from a real transcript shape) |
| H23 (B) | Project-id encodings diverge on dotted segments between writer and reader (latent) | deferred |
| H24 (B) | code-state sidecar contract pinned only by a hand-built fixture in another repo | tied to H2 |

Lows (both lenses): docstring arithmetic (78 not 68), five lines over 100 columns, `os.write` return unchecked, vocabulary dedup outside the lock (9 duplicates exist), dict-equality collapse in `other_take`, `focus_limit` regex takes the first match anywhere, non-dict stdin payloads, unstripped anchor refs, an unreachable branch, a few boundary flips uncaught. Recorded; not planned.

## Tranche 2 — git and sync writers

Lens A: 5 critical, 11 medium, 14 low. Lens B: 20 mutations survived of ~28; `daily-sync.sh` effectively has no behavioural test (its one end-to-end fixture dies at line 618 before the sync body and the test passes anyway).

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| S1 | `scripts/daily-sync.sh:510-577` — a data-submodule commit made while the tree is clean afterwards is never pushed, but the parent pointer bump that references it IS pushed: origin points at a commit the other machine cannot fetch. Happened today at 09:29. `monthly-archive.py:522-539` already works around this locally. | CONFIRMED from `logs/daily-sync.log` and `git ls-tree` | **next** (push whenever `HEAD` is ahead of `@{u}`) |
| S2 | `daily-sync.sh:512` — `git add -A` after the stash pop sweeps concurrent sessions' half-written prose into an automated commit and pushes it (`e433eee`, `549d9aa`), contradicting the script's own comment and the hub rule. | CONFIRMED from history | **decision** — the daily sync is also how scratchpad and notes *appends* get committed; Shawn rules which paths the auto-commit may take |
| S3 | `daily-sync.sh:475-501` — stash-pop conflicts feed every conflicted path, prose included, to the line-union resolver; a conflicted `wiki/continuity.md` is rewritten as an interleaved union. The rebase path partitions correctly. | CONFIRMED by reading both paths | **next** (partition like the rebase path; abort on prose) |
| S4 | `daily-sync.sh:196,287` — `git checkout --ours` during a rebase takes origin's side, the opposite of the comment's intent (git-checkout(1)). | CONFIRMED against git documentation | **next** (`--theirs`, both sites) |
| S5 | `daily-sync.sh:358,405-423` run before the detached-HEAD guard at 438-445; on a detached HEAD the memory commit and the archive commit are orphaned and the working tree reverted. Likely trigger: `sync-symlinks.sh:126 git submodule update` detaching HEAD. | CONFIRMED by ordering; trigger SUSPECTED | **next** (move the guard above every commit site) |
| S6 (B) | `scripts/resolve-merge-conflicts.py` has zero tests; keeping only "ours" passes the whole suite. | CONFIRMED | **next** (tests with real conflict markers) |
| S7 (B) | `scripts/daily-sync-trigger.sh` has zero tests; "never runs again" and "breaks the hook chain" both pass. | CONFIRMED | **next** |
| S8 (B) | `archive-memories.py::apply_archive` untested: evicting without archiving, or archiving without evicting, passes. `monthly-archive.py::_apply` halts removable with tests green. | CONFIRMED | **next** |

### Medium (sync)

| # | Finding | Disposition |
|---|---|---|
| S9 | Archiver call lacks a `DRY_RUN` guard; `--dry-run` commits | **next** |
| S10 | Two Syncthing gate-file layouts; the trigger reads one; the early-exit path renders a headerless problem | **next** |
| S11 | `sync-symlinks.sh:97` `ln -sf` on a symlink-to-directory writes inside it; needs `-sfn` | **next** |
| S12 | Resolver: a valid-JSON non-object line raises `AttributeError`, aborting the sync with a conflicted tree | **next** |
| S13 | `compose-global-claude-md.sh:102` truncates `~/.claude/CLAUDE.md` before writing | **next** (temp + `mv`) |
| S14 | `push-archives-to-r2.sh:91` version probe kills the script under `pipefail` | **next** |
| S15 | `archive-memories.py:369-373` releases the flock before its commit | **next** |
| S16 | `archive-memories.py:413`, `commit-data.sh:49,58` commit without a pathspec | **next** |
| S17 | A conflicted orphan-stash pop wedges every later session with no gate line | **next** (gate line) |
| S18 | Syncthing SSH probe runs inside the 90 s SessionStart budget | deferred |
| S19 | Unchecked `exec` redirect and `cd` misreported as lock contention | **next** |
| S20 (B) | Explicit-pathspec contract untested for the data-submodule committers; `commit-data.sh` lock and branch guard removable | **next** |
| S21 (B) | The end-to-end fixture would, if repaired, run `sync-symlinks.sh` against the real `~/.claude/settings.json` and rsync/R2 against real archives; pin `HOME` first | **next** (before any fixture repair) |

Lows recorded: hardcoded interpreter path at 802; `[[ "None" -gt 0 ]]` under `set -u`; raw interpolation into `bash -c`/`ssh`/Python in `syncthing-health.sh`; diff3 markers unsupported (latent); stale co-author in `commit-data.sh`; two drifting rebase resolvers; `--porcelain` without `-z`; psql `IN (...)` from 10,000 ids; cc-archives gate not rewritten when the mount is absent; EXIT trap pops the top stash; `/tmp` lock ownership; only `$1` inspected for `--dry-run`; two shrink detectors disagree by one line; `sync_memory_edit.py` reads via the root symlink; `advance_or_quarantine` has no callers.

## Tranche 3a — memory-to-Postgres pipeline (Lens A; Lens B not yet run)

### Critical

| # | Finding (file:line) | Verdict | Disposition |
|---|---|---|---|
| P1 | `scripts/sync-sessions-to-postgres.py:543-552,652-658` — every `psycopg2.Error` is reported as "PostgreSQL may be down" and the cursor held. Two archive metadata files carry a NUL in LLM-generated narrative; Postgres rejects ` ` in jsonb; the `sessions` table has been stale since 2026-08-17 with 48 sessions unsynced and the wrong diagnosis in the log. | CONFIRMED live | **next** (split outage from data errors; quarantine the row; per-row fallback after a failed batch; sanitise NUL at ingest) |
| P2 | `scripts/sync-to-postgres.py:656-665,950-954,312` — same conflation in the memories path; `created_at` unguarded (`TIMESTAMPTZ NOT NULL`); a NUL in content raises `ValueError` outside the handler. | CONFIRMED by reading; free-text dates have reached `deadline_at` repeatedly | **next** |
| P3 | `scripts/embed.py:37` — `OLLAMA_BASE_URL=""` from `ollama-endpoint.sh`'s failure path yields `ValueError: unknown url type` outside the degradation ladder; the documented fallback does not exist. | CONFIRMED by repro | **next** (`or` default; fix the wrapper's comment) |

### Medium (Postgres)

| # | Finding | Disposition |
|---|---|---|
| P4 | `rebuild-postgres.py` never truncates `session_chunks` | **next** |
| P5 | `index-session-content.py` has no schema-version guard and tracebacks on an outage | **next** |
| P6 | `backfill-embeddings.py --limit` not honoured (200 embedded for `--limit 5`) | **next** |
| P7 | `backfill-embeddings.py --catch-up` tracebacks on a DB error mid-batch | **next** |
| P8 | `check-memory-drift.py --recover` resurrects soft-deleted memories (`is_active` and history fields not selected) | **next** |
| P9 | `check-memory-drift.py:298` is the only canonical writer without the flock | **next** |
| P10 | `.get(key, default)` on a NOT NULL column right after the comment warning against it | **next** |
| P11 | Sessions cursor is naive local time compared lexicographically; a clock step back skips sessions forever | deferred (document `--full-resync`; fix with UTC when the archive format changes) |
| P12 | No embedding-dimension validation; a wrong-dimension model re-embeds the same rows forever with a warning | **next** (check `len == 768` once) |
| P13 | Two quarantine record shapes in one file; dedup sees one | deferred |
| P14 | Poison lines re-quarantined every 5 minutes while the cursor is halted | **next** (dedup before append) |
| P15 | Drift recovery pulls the whole table to filter in Python | deferred |
| P16 | Three processes read-modify-write `sync-cursors.json` without lock or atomic rename | **next** (atomic write; the memories sync already has the flock pattern) |

Lows recorded: three constant f-string SQL sites; handler stacking; `tool_calls: 0` stored as NULL; 235 MB steady-state RSS per 5-minute tick; `split()` vs `splitlines()`; id-less stash lines; U+2028 latent; stale comments; docstring "bounded memory" claim.

## Decisions for Shawn

1. **H1 — extraction drops everything before the last 30 messages.** Fix is to process the window in chunks of 30, which multiplies Haiku calls on the 5% of firings that need it (never more than ten calls for the largest window seen). Approve the spend, or choose a larger single window.
2. **S2 — what the daily sync may auto-commit.** Today it commits everything dirty in the data submodule after the stash pop, prose included. The hub's own comments say prose must never be swept, but scratchpad and notes appends are left for it deliberately. Options: (a) an explicit allow-list of append-only paths (memories, scratchpads, notes inbox); (b) keep sweeping everything; (c) sweep but never push a commit that touched `tasks/` or `wiki/`. Recommendation: (a).
3. **Sessions table stale since 17 August (P1).** Fixing the error split and sanitising NUL will let 48+ sessions sync on the next run. No decision needed unless you want to inspect the two affected archive files first.

## Fix rounds

- Round 1 (done): tranche 0.
- Round 2 (next): hooks H2–H4, H8–H13, H15–H18, H20–H22; sync S1, S3–S5, S9–S17, S19–S21; Postgres P1–P10, P12, P14, P16. Each round is re-audited by a fresh agent before it closes.
- Remaining tranches (3b, 3c, 4a, 4b, 5a, 5b, 6) run after round 2 lands, so their findings arrive against corrected code.
