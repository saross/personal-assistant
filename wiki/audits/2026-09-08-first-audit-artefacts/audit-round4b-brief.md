# Audit round 4b — retrieval and serving — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4b`, branch
  `claude/audit-round4b`, at commit 7e013f3 (main). Suite at the branch
  point: 2,372 passed, 3 deselected. A sibling agent (round 4a) is fixing the
  memory-store WRITERS in another worktree and owns `tests/conftest.py`,
  `scripts/_sync_cursor.py`, `scripts/_timestamps.py`, and every writer script
  (`dedup-memories`, `tag-gardening`, `recover_anchors`, `sync_memory_edit`,
  `archive-memories`, `apply-decay`, `monthly-archive`). Do NOT edit those
  files. If a fix here needs `_timestamps.py`, use its existing functions
  read-only and say so in your report. A third agent owns `scripts/daily-sync.sh`
  and its tests.
- Lens reports: `lensA-4b.md` (correctness, R-findings) and `lensB-4b.md`
  (test adequacy, RT-findings) in this directory. Line numbers were taken at
  505ca8c; verify before editing.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit
  it.
- Scope: `scripts/fetch-memories.py`, `scripts/memory_mcp.py`,
  `scripts/search-sessions.py`, `scripts/surfacing_stats.py`,
  `scripts/log-recall.py`, `scripts/log-confab-flag.py`,
  `scripts/digest-preview.py`, `scripts/project_id.py`,
  `scripts/resolve_session_id.py`, their tests (create the missing files),
  the legacy four-bucket path in `hooks/session-start-retrieval.py` (only the
  `is_active` filter and surfaced logging noted below), and the documents
  `commands/recall.md`, `commands/forget.md`,
  `global-claude-md/tier-2-retrieval.md`,
  `global-claude-md/infrastructure-reference.md` (the lines the findings name).

## Must fix (Critical and Medium from both lenses)

Order: the four criticals first, one commit each, then the mediums grouped by
file, then the tests that kill the surviving mutations.

R1 (critical) — `fetch-memories.py:513-525` `_parse_datetime` must return an
AWARE datetime for every input (naive → UTC, date-only → midnight UTC, as
`hooks/session-start-retrieval.py:452-453` does; prefer the helper in
`scripts/_timestamps.py` if one fits), so the JSONL fallback (:552-555) and
`search_archive` (:608-611) never raise. Test: a corpus mixing `YYYY-MM-DD`,
naive ISO, and `+10:00` stamps sorts newest-first without error.

R2 + R3 (critical) — forgotten memories must not surface on any path. Add an
`is_active` check (absent key or `True` passes; `False` fails) to
`fetch-memories.matches_filters` and to the JSONL fallbacks in
`memory_mcp.py:250-271,433-445`; fix the `note` strings ("decay rules NOT
applied" must not imply soft-deletes are honoured or not — say exactly what is
and is not applied); add an `is_active` filter step to the `/recall` procedure
in `commands/recall.md:57-70` and correct line 234; make the claim at
`commands/forget.md:62-65` true. Also the legacy path in
`hooks/session-start-retrieval.py:1381-1400` (`retrieve_recent`,
`retrieve_permanent`, `retrieve_middle_aged`, `retrieve_constraints`): filter
`is_active` there (reuse the helper at `scripts/digest.py:253-259` or mirror
it) — minimal change, with a test per bucket that an inactive record is
excluded. Tests: an `is_active: False` record is excluded from every fallback
and from `search_archive`; an absent key is included.

R4 (critical) — `project_id.py:56` must encode the way Claude Code does. Live
evidence: `~/.claude/projects/` contains
`-home-shawn-personal-assistant--claude-worktrees-workstream-g-efficacy` for
`/home/shawn/personal-assistant/.claude/worktrees/workstream-g-efficacy`, so
`.` (and, verify, every character outside `[A-Za-z0-9]`) becomes `-`. Derive
the rule from the directory names (read-only listing of `~/.claude/projects/`
is allowed; never write there), check it against EVERY name there whose
decoded path exists, and decide whether `resolve()` belongs (a symlinked cwd:
does Claude Code resolve it? — test against a live symlinked project if one
exists, else document the assumption). Update `decode_project_id` so the two
stay inverse where possible, and document the lossy cases. Tests: the live
double-dash case; a dotted component; the parity cases already present.

R5 — `memory_mcp.py`: every tool that returns memory content logs the ids to
`surfaced.log` through `scripts/surfacing_log.py` with a distinct source
(check the writer's accepted sources; add `mcp` if needed) so
`surfacing_stats` counts it; update `tier-2-retrieval.md:82-92` (four paths)
and `infrastructure-reference.md:118,176` (six tools). Test: the log call
receives exactly the ids returned.

R6 — `fetch-memories.py:732-757`: `--semantic` combined with `--query` or
`--id` must either be rejected with a clear usage error or honoured (document
which); an empty semantic result must fall back to FTS as the stderr text
promises, or the text must change. Test both.

R7 — `fetch-memories.py:389-390` and MCP `semantic_search`: state in the CLI
help, the tool description, and the result envelope that rows without an
embedding are not searched, and report how many active rows lack one (a
COUNT in the same connection). Test via the fake cursor.

R8 — `commands/recall.md:174-187`: replace the raw `psql -c` snippet with an
invocation of `scripts/search-sessions.py` (parameterised). No user text may
be interpolated into SQL anywhere in `commands/`.

R9 — `search-sessions.py` and `memory_mcp.py`: set a statement timeout on
the connection (`options="-c statement_timeout=30000"` or `SET LOCAL`), a
`connect_timeout`, and refuse `--substring` patterns shorter than three
characters with a usage error naming the trigram limit. Tests via a fake
connect that records kwargs.

R10 — `log-recall.py:70-77` `--limit` must be sanitised like the other
fields (`type=int` or collapsed). R11 — `search-sessions.py:98` add a final
`c.id DESC` tiebreak. R13 — `resolve_session_id.py:61` reject a catalogue
`rel` that is absolute or escapes the root (containment check after
resolve). R14 — `resolve_session_id.main` maps `OSError` to exit 2 with a
one-line message. R15 — `format_output` prints the id (the `/forget`
contract), and `commands/recall.md`'s display block shows it. R16 —
`matches_filters(tags=[])` treats an empty list as "no filter". R17 —
`fetch-memories.py:813`, `digest-preview.py:39`, `log-recall.py:87`,
`log-confab-flag.py:169`: apply the S22 pattern from
`scripts/surfacing_log.py:97-127` — a `default_log_path()` resolved at call
time (env override, dormant under pytest, else the shipped path), no
default-argument binding at import; `digest-preview` marks its lines as
preview or writes to its own file. R18 — MCP error envelopes carry a generic
message; the psycopg2 text goes to stderr/log only. R19 — count fixed.

RT1–RT16 (tests) — kill every surviving mutation in `lensB-4b.md`. Build ONE
fake-connection helper (in a new `tests/_fake_pg.py` or inside the test
files) whose cursor records `(sql, params)` and returns rows from a table you
seed, and that applies the `active_memories` semantics (`is_active` true and
not decayed) so that `memories` vs `active_memories`, `AND` vs `OR`, `DESC`
vs `ASC`, `LIMIT`, `embedding IS NOT NULL`, and cosine direction are all
observable — a parsing shim over a sqlite table is acceptable if it stays
under ~150 lines. Then: `try_postgres` query body (RT1–RT3), `main()` end to
end with Postgres up and down (RT4; inject the log path from R17),
`search_sessions` behaviour and its ImportError envelope (RT5), a
`tests/test_search_sessions.py` covering LIKE escaping, the role filter, and
ordering (RT6), the MCP JSONL fallback without stubbing `matches_filters`
(RT7), `try_semantic` (RT8), multi-tag OR (RT9), reader and writer defaults
compared (RT10: assert `surfacing_stats` default == `surfacing_log` shipped
path), `_render_human` and `main()` (RT11), `log-recall.main()` (RT12),
`get_memory` exact match (RT13), the `SchemaVersionError` branch at each
call site (RT14), `decode_project_id` / `repo_set` / `repo_set_for` (RT15),
`tests/test_resolve_session_id.py` (RT16), `digest-preview` smoke (RT17),
and a shape test that `list_recent` and `search_memories` return the same
keys (RT18). Every new test that could reach Postgres must monkeypatch
`psycopg2.connect` at module scope in that file; add an autouse fixture in
each retrieval test file that makes an unpatched `psycopg2.connect` raise.

## Record, do not change

The two archive roots (`search-sessions` reads Postgres built from
`~/cc-archives`; `resolve_session_id` defaults to the rpi share) — note it in
your report; the JSONL-fallback ranking divergence between CLI and MCP — make
them the same (aware-datetime sort) and say so.

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table (finding ID → fixed
with file:line and test name, or not fixed with reason), NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "MCP results now write to `surfaced.log`", "`/recall` output now
shows ids").
