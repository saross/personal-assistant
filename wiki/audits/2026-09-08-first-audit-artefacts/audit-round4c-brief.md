# Audit round 4c — session archive pipeline — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4c`, branch
  `claude/audit-round4c`, at commit d1c3773 (main, which now includes round 4a:
  the conftest hermeticity guard snapshots the canonical store and `logs/`
  through the root symlinks and refuses an unpatched `psycopg2.connect`).
  Suite at the branch point: about 2,453 passed. Sibling agents run in other
  worktrees: round 4a-2 owns `tests/conftest.py`,
  `tests/test_hermeticity_fixture.py`, `scripts/check-memory-drift.py`,
  `scripts/sync-to-postgres.py`, and the memory-store writers; round 4b owns
  the retrieval scripts; another owns `scripts/daily-sync.sh`. Do NOT edit any
  of those. If you find a hermeticity-guard gap, report it; do not patch
  conftest.
- Lens reports: `lensA-4c.md` (correctness, findings 1-27 → cite as AR1-AR27)
  and `lensB-4c.md` (test adequacy, findings 1-14 → ART1-ART14) in this
  directory. Line numbers were taken at b4d0c57; verify before editing.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit it.
- Scope: `scripts/bulk-archive.py`, `scripts/check-archive-drift.py`,
  `scripts/reprocess-sessions.py`, `scripts/backfill-summaries.py`,
  `scripts/validate-session-metadata.py`,
  `scripts/normalise-archive-storage.py`, `scripts/extract-transcript-text.py`,
  `scripts/_scan_archives.py`, `scripts/extraction-prompt-spotcheck.py`,
  `scripts/search-archives-safe.sh`, `scripts/push-archives-to-r2.sh`, their
  tests (create the missing files), and `tests/test_glue_scripts.py` for the
  shell scripts. `cc_session_toolkit` (a separate checkout under `~/Code`) is
  OUT of scope — do not edit it; record what this repository cannot pin.

## Absolute safety rules for this tranche

Never read, copy, list the contents of, or run anything against real
transcripts or archives: `~/.claude/projects/**` (directory NAMES may be
listed; nothing opened), `~/cc-archives/**`, `~/mnt/rpi-shares/**`. Every
test builds a SYNTHETIC `~/.claude/projects` tree and archive root under a
pytest tmp dir, with transcripts you invent in the shapes the hook parses
(top-level `type`, `uuid`, `parentUuid`, `timestamp`, `sessionId`, `cwd`,
`isMeta`, `isSidechain`, `isCompactSummary`, tool_use/tool_result blocks,
thinking blocks, a `subagents/` directory). No LLM, OpenAI, Gemini, Anthropic,
Ollama, rclone, ssh, rsync, or HTTP call may execute — stub every client at
the boundary and assert the stub was or was not called. Never execute
`push-archives-to-r2.sh` outside a sandbox with a stub `rclone` and `df`
first on PATH and HOME pinned. Never write to `~/.cache`, `~/cc-archives`,
`~/.claude`, or the repository's `logs/`, `data/`, `memories/`.

## Must fix (Critical and Medium from both lenses)

Order: AR3, AR1, AR2, AR4, AR5 first (one commit each), then the mediums by
file, then the tests.

AR1 (critical) — ONE "substantive session" rule. Put the predicate in one
shared module (for example `scripts/_archive_substance.py`: content chars of
user/assistant prose excluding `isMeta`/`isCompactSummary`/sidechain, the
4,000-char floor, and the 48-hour grace) and make `check-archive-drift.py`,
`bulk-archive.py discover`, and the `enrich` floor call it. The gate's
remediation line must name a command whose defaults archive exactly what the
gate reported. Test: a 2-turn, 28 KB session is reported by the drift check
AND archived by `discover` at the remediation line's flags; a 5-turn 500-char
session is neither.

AR2 (critical) — `bulk-archive.py:479` must never treat a catalogue id as
archived; disk (`session.meta.json`) is the only dedup key; log the ghost
count and move on. Test: a ghost catalogue entry does not suppress archiving.

AR3 (critical) — completeness guard: `discover` and `cmd_archive` skip a
session whose transcript mtime is within the grace window or whose size
changed between discovery and archive (re-stat immediately before the copy;
compare after the copy too); `cmd_verify` compares archived size with the
meta's recorded size; an interrupted or growing source is reported, never
archived. Test: a transcript that grows between discover and archive is
skipped with a named reason; a stable one is archived; verify flags a
mismatch.

AR4 (critical) — `backfill-summaries.py` gates every API call: print the
model, batch versus real-time, the call count, and an estimated cost, then
require `input()` confirmation unless `--yes` (mirror `bulk-archive.py:2032`).
Test: without `--yes` and with stdin closed, the client stub is never called
and the exit is non-zero; with `--yes` the stub is called.

AR5 (critical) — `backfill-summaries.py:275-285` applies only ids present in
the batch's own index map; any other id in the reply is logged and ignored.
Test: a reply with one out-of-batch id changes exactly the in-batch records.

AR6, AR7, AR8 — `reprocess-sessions.py`: selection recognises
`source == "reprocessing"` as already done (idempotent; test that a second
run selects nothing and appends nothing); `custom_id` carries enough of the
session id to be unique (full id or a hash; test two ids sharing an 8-char
prefix); `apply BATCH_ID` refuses when the state's batch id differs.
AR11 — its transcript reader filters `isMeta` and `isSidechain` exactly as
the hook does (reuse the hook's helper if importable; test with both flags).
AR18 — batch state per batch id, not one slot (both scripts).

AR9 — `normalise-archive-storage.py`: repoint the meta (atomic write) BEFORE
unlinking the raw file; a failed repoint leaves the raw in place; a re-run
self-heals a gz-present-raw-absent-meta-stale state. Test the ordering with a
failure injected at each step.

AR10 — the layout probe must not silently read a live store as a snapshot:
require an explicit `--layout` when the probe is ambiguous, or warn loudly
and refuse to treat UUID-shaped directories as projects. Test.

AR12 — the progress checkpoint is honoured only after re-verifying the
session exists on disk in this machine's archive; stale entries are dropped
with a log line. Test with a checkpoint naming an unarchived session.

AR13, AR14, AR16 — atomic writes everywhere: `_enrich_apply` merges
`auto_generated` (never drops `three_ps`) and writes temp+replace;
`archive_subagents` writes temp+replace and refuses to overwrite an existing
archive unless `--force`; `cmd_verify --fix-catalogue` writes the catalogue
temp+replace under a lock, and `get_archived_session_ids` tolerates a corrupt
catalogue (log and treat as empty, never crash `discover`). Tests: crash
injection at the write leaves the previous file intact.

AR15 — put the toolkit on `sys.path` before `_make_token_counter`. Test.

AR17 — `push-archives-to-r2.sh`: read the two R2 variables from `.env`
without sourcing it (grep the two names, no `$(...)` evaluation, export only
those two); make the transfer refuse to modify an existing object
(`--immutable` or an equivalent — reason from rclone's documented flags; the
archive is append-only, so an object that changed size is a corruption
signal, not an update) and say so in the header. Tests in
`tests/test_glue_scripts.py` with a stub `rclone` that records argv: dry-run
never drops `--dry-run`; an unmounted canonical refuses; a `.env` line with
`$(touch marker)` never executes; only the two variables reach the stub's
environment.

Lens B — ART1: `tests/test_check_archive_drift.py` (the six cases listed).
ART2/ART3: `bulk-archive.py` entry-point tests through `main()` against a
synthetic tree — `discover` (skip archived, skip trivial, skip growing),
`archive` (files created with the right names and metadata, checkpoint
updated, failure recorded in `failed_ids`, exception not swallowed silently),
`verify` (missing transcript reported; catalogue rebuilt atomically),
`subagents`, and the size tie-break (ART14). ART4:
`tests/test_normalise_archive_storage.py` (verify-before-unlink; DIVERGENT
touches nothing). ART5: `search-archives-safe.sh` in a sandbox — a held lock
exits 3 with REFUSED; `LIMIT_PREFIX` present in the executed argv (stub
`nice`/`ionice`/`timeout` that record argv). ART7: `_scan_archives.py`
per-line truncation and the exception tuple pinned. ART8:
`reprocess-sessions.py` skip, wrong-directory, guard wiring, partial last line.
ART9: `tests/test_validate_session_metadata.py`. ART10:
`backfill-summaries.py` line-count invariant and temp+rename pinned; also
switch its `ensure_ascii=False` at :234 to default escaping (the round-4a
re-audit's M1 — a raw U+2028 written here re-creates the record-splitting
hazard) with a test. ART11: the re-export shim's names resolve; the spotcheck
default makes zero API calls. ART12/ART13: delete or rewrite the tautological
tests so each calls production code and can fail.

## Lows — fix where cheap

AR19 (docstring flag), AR20 (dangling `logs` symlink → clear message, not a
traceback), AR21 (`_scan_archives` and `verify` agree on accepted transcript
names), AR22 (contain the joins), AR23 (atomic gate write; BOM tolerated),
AR24 (glob agreement), AR25 (style).

## Record, do not change

AR26 (`data/.gitignore` does not ignore `logs/*.json`; private submodule —
Shawn's call), AR27 (worktree runs take a different lock), the
`cc_session_toolkit` write path (no temp staging, no lock, outside this repo),
the two archive roots. Mention each in your report.

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table (finding ID → fixed
with file:line and test name, or not fixed with reason), NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "the next drift gate will report N more sessions", "the R2 push now
refuses to overwrite").
