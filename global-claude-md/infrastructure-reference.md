## Infrastructure — Full Reference

**Read this file when** working on hooks, scripts, sync pipelines, integration
points, or troubleshooting the personal-assistant system architecture.

### Architecture Overview

The personal-assistant system is built on three layers:

1. **Extraction** — Hooks capture memories and metadata from Claude Code sessions
2. **Storage** — JSONL (canonical) + PostgreSQL (derived query layer) + pgvector
   (semantic search)
3. **Retrieval** — Session-start loading (Level 1) + on-demand fetch (Level 2)

### Data Canonicality

| Data type | Canonical source | Derived stores |
|-----------|-----------------|----------------|
| Memories | `memories/memories.jsonl` | PostgreSQL `memories` table, pgvector embeddings |
| Sessions | `~/cc-archives/` (JSONL + metadata) | PostgreSQL `sessions` table |
| Tasks | `tasks/*.md` (Markdown) | GitHub Issues (via `/sync-board`) |
| Zotero | `~/Zotero/zotero.sqlite` (Zotero-managed) | None (read-only access) |

**Key principle:** JSONL is always canonical. PostgreSQL can be fully rebuilt
from JSONL at any time via `scripts/rebuild-postgres.py`.

### Data Flow

```text
Claude Code session
  → extraction-hook.py (Haiku, per-response)
    → memories/memories.jsonl (canonical)
      → sync-to-postgres.py (5-min cron)
        → PostgreSQL memories table
          → embed.py (nomic-embed-text, auto in sync)
            → pgvector embedding column
              → fetch-memories.py --semantic (retrieval)

Session end
  → cc-session-toolkit archive hooks
    → ~/cc-archives/ (compressed JSONL + metadata)
      → sync-sessions-to-postgres.py
        → PostgreSQL sessions table (metadata + Three-P summaries, FTS)
      → index-session-content.py (transcript prose, line-oriented)
        → PostgreSQL session_chunks table (per-turn FTS + trgm)
          → search-sessions.py / /search-sessions / search_sessions MCP tool

Session start
  → session-start-retrieval.py
    → Level 1: 54 memories loaded into context
    → Level 2: fetch-memories.py (on-demand, gated)
```

### Commands (21 total)

All symlinked from `commands/` to `~/.claude/commands/`.

| Command | Purpose | Category |
|---------|---------|----------|
| `/standup` | Morning accountability check | Task |
| `/recap` | Evening recap + work log | Task |
| `/track` | Time logging (CSV-based) | Task |
| `/capture` | Quick inbox add | Task |
| `/done` | Mark task complete | Task |
| `/focus` | Manage focus slots | Task |
| `/review` | Weekly review + collaborator reports | Task |
| `/retro` | Monthly retrospective | Task |
| `/sync-board` | GitHub Projects sync | Task |
| `/process-email` | Email triage | Task |
| `/recall` | Search memories + sessions (FTS + semantic) | Memory |
| `/remember` | Manual memory capture | Memory |
| `/read` | Structured Zotero paper reading | Research |
| `/synthesise` | Thematic synthesis | Research |
| `/cite` | Quick citation lookup | Research |
| `/cite-new` | Generate BibTeX from DOI | Research |
| `/gaps` | Literature gap analysis (six dimensions, prioritised) | Research |
| `/craft` | Quick notebook entry | Notes |
| `/tags` | Tag vocabulary gardening (stats, duplicate detection, merge) | Memory |
| `/audit` | Code audit | Meta |
| `/reflect` | End-of-session reflection | Meta |

### Skills (2 total)

Symlinked from `skills/` to `~/.claude/skills/`.

| Skill | Purpose |
|-------|---------|
| `improve-prompt` | Prompt hardening workflow |
| `review-implementation` | Implementation review protocol |

### Hooks (2 total)

Located in `hooks/`, registered in `settings.json`.

| Hook | Trigger | Purpose |
|------|---------|---------|
| `extraction-hook.py` | Stop, PreCompact, SessionEnd | Memory extraction via Haiku. Cursor-tracked, slash-command filtered, tag-normalised. Extracts 24 categories of structured memories. `EXTRACTION_MAX_TOKENS = 8000` (raised from 2000 in P10, 2026-06-06); truncated responses are salvaged via `_salvage_truncated_array()` + `stop_reason == "max_tokens"` branch rather than dropped. |
| `session-start-retrieval.py` | SessionStart | Level 1 retrieval. 54 memory slots (35 same-project + 11 cross-project + 8 constraints). Loads scratchpad, task status, and Tier 2 retrieval instructions. Also logs surfaced memory IDs to `data/logs/surfaced.log` via `surfacing_log.log_surfaced()` (item 16 earned-utility instrumentation, 2026-06-06). |

### Scripts

Located in `scripts/`.

**Memory system:**

| Script | Purpose |
|--------|---------|
| `sync-to-postgres.py` | JSONL → PostgreSQL sync + auto-embed (5-min cron). P8 (2026-06-06): now syncs `is_active` in its INSERT so a row forgotten before its first sync lands inactive rather than being resurrected. |
| `sync_memory_edit.py` | Surgical PG `UPDATE` for `/forget` and `/update` (P8, 2026-06-06). Reads the already-edited JSONL record and mirrors the six mutable columns (`is_active`, `content`, `confidence`, `verified`, `anchors`, `revisions`) into PostgreSQL. Idempotent. Called as a mandatory step by both commands. PG-only: runs on amd-tower; no-op notice on other machines. |
| `apply-decay.py` | Mark expired memories inactive (weekly cron, Sun 3am) |
| `fetch-memories.py` | CLI retrieval: `--query` (FTS), `--semantic` (pgvector), `--tag`, `--category`, `--id`. `--semantic` carries its own query text and cannot filter by id, so it is **mutually exclusive** with `--query` and `--id` (a usage error since 2026-09-08; it used to discard them silently) — `--tag` and `--category` still apply. It searches embedded rows only and reports how many active rows lack an embedding. Logs surfaced memory IDs via `surfacing_log` (item 16, 2026-06-06). |
| `embed.py` | Shared Ollama embedding client (nomic-embed-text, 768d) |
| `backfill-summaries.py` | Bulk summary generation via Haiku Batch API |
| `backfill-embeddings.py` | Bulk embedding via Ollama |
| `rebuild-postgres.py` | Truncate + full resync from JSONL |
| `tag-gardening.py` | Tag vocabulary analysis + merge (stats, similar, merge, orphans). Called by `/tags`. |
| `sync-to-zotero.py` | Push `source_insight` memories to Zotero item notes via pyzotero API. Manual invocation; idempotent via footer markers. |
| `memory_mcp.py` | Local MCP server exposing memory DB as 6 read-only tools (`search_memories`, `semantic_search`, `search_sessions`, `get_memory`, `list_recent`, `memory_statistics`). stdio transport, FastMCP. The four that return memory records log surfaced ids via `surfacing_log` under `path=mcp` (2026-09-08). |
| `surfacing_log.py` | Append-only writer for `data/logs/surfaced.log` (item 16, 2026-06-06). Logs one tab-separated line per surfaced memory ID, tagged `path=digest\|fetch\|recall\|mcp`. Pure formatter + best-effort I/O; never raises. CLI: `--path <path> --ids "<ids>"`. |
| `surfacing_stats.py` | Read-only aggregator over `surfaced.log` (item 16, 2026-06-06). Reports per-memory `active_retrievals`, `digest_exposures`, `last_active_at`; weights active fetch/recall above passive digest. Importable as `aggregate_surfacing()` for the health report. |
| `drift-sweep.py` | Anchor drift trend (item 8, 2026-06-06). Re-resolves the full anchored memory back-set and appends a trend line to `data/logs/drift-sweep.jsonl`. `--alert-threshold` sets an exit-1 threshold on the fail percentage. Read-only against the corpus. |
| `memory-health-report.py` | Standing health report (run by `/weekly-review`). Gained section [G] Memory surfacing (reads `surfaced.log` via `surfacing_stats.aggregate_surfacing()`) and section [H] Anchor drift trend (reads `drift-sweep.jsonl` via `drift_trend()`), both added 2026-06-06. |

**Session archiving:**

| Script | Purpose |
|--------|---------|
| `bulk-archive.py` | 4-mode: discover, archive, enrich, verify. Haiku Batch API for metadata enrichment. Checkpoint/resume. |
| `reprocess-sessions.py` | Extract memories from pre-hook sessions. Haiku Batch API, windowed (30 exchanges). |
| `sync-sessions-to-postgres.py` | Session metadata → PostgreSQL `sessions` table |
| `index-session-content.py` | Transcript prose → PostgreSQL `session_chunks` (per-turn FTS). Line-oriented, incremental by mtime. |
| `search-sessions.py` | Indexed full-text search of session content + verbatim turn retrieval. Backs `/search-sessions` and the `search_sessions` MCP tool. |
| `search-archives-safe.sh` + `_scan_archives.py` | Crash-proof bounded fallback grep of raw `.gz` (nice/ionice/timeout/cgroup/flock; Python line-scan engine). |

**Zotero:**

| Script | Purpose |
|--------|---------|
| `zotero.py` | Read-only Zotero SQLite client (immutable mode). Functions: `search_items`, `get_item`, `get_pdf_path`, `get_notes`, `get_collections`, `list_collections`, `get_collection_items`, `format_citation`. |

**Other:**

| Script | Purpose |
|--------|---------|
| `schema.sql` | PostgreSQL schema (memories + sessions tables, pgvector, 11+ indexes, views) |
| `commit-data.sh` | Submodule two-step commit helper |

### Integrations

**PostgreSQL (`claude_memories` database):**

- ~14,900 memories with pgvector embeddings (nomic-embed-text, 768d)
- ~335 sessions with Haiku-generated metadata
- Full-text search (tsvector) + trigram similarity on content
- pgvector HNSW index for semantic search
- `active_memories` view (applies decay rules)
- `category_config` table (15 categories with decay rules)
- Cron: sync every 5 min, decay weekly (Sun 3am)
- Full reference: `global-claude-md/postgresql-reference.md`

**Ollama (local):**

- nomic-embed-text — embedding generation (768d, ~1ms per embedding)
- Auto-embedded during sync cron (100 records per batch)
- Full model inventory and machine roles: `data/global-claude-md/network-resources.md`

**Zotero (local):**

- `~/Zotero/zotero.sqlite` — 3,763+ items, 1,060 PDFs, 82 collections
- Read-only immutable mode (safe while Zotero is running)
- Write-back via pyzotero API (`sync-to-zotero.py`, manual invocation)
- Full reference: `global-claude-md/zotero-reference.md`

**Local MCP servers:**

- `memory_mcp.py` — exposes the memory database as 6 read-only MCP tools
  (`search_memories`, `semantic_search`, `search_sessions`, `get_memory`,
  `list_recent`, `memory_statistics`). stdio transport via FastMCP. Wraps the
  `fetch-memories.py` query engine, and `search-sessions.py` for the
  transcript search.
- Registration: `claude mcp add memory --scope user -- <python> <script>`
- Dependency: `mcp` package (`pip install mcp`)
- Use case: query memories from Claude Desktop, claude.ai, or other
  Claude instances that cannot access the local filesystem directly
- Critical invariant: stdio MCP servers must never write to stdout

**Session archives (`~/cc-archives/`):**

- ~850 distinct sessions (2026-08-22; ~1,120 metas on disk including
  duplicate and nested entries), most enriched with generated metadata
- Storage invariant (2026-08-22): transcript form is `session.jsonl.gz`;
  resolve via `cc_session_toolkit.transcript_text.resolve_transcript()`
- `CATALOG.json` is a **derived index and under-reports** (depth-2
  rebuild; plan item B6) — never use it as a dedup key or for counts;
  walk `session.meta.json` on disk instead
- Subagent archives nested under parent sessions (5,300+ transcripts)

**Replication & integrity (see network-resources.md "Session-archive
stores" for the full topology):**

- `daily-sync.sh` cc-archives passes 1–4 converge local mirrors with the
  canonical union on rpi-server (SSHFS; **self-mounting** since
  2026-08-22), then amd-tower pushes to Cloudflare R2 (additive-only)
- Four session-start gates, all surfaced on hook **stdout** so they land
  in the assistant's context: `cc-archives-gate` (meta without local
  transcript), `syncthing-gate` (personal-docs mesh — NOT archives),
  `memory-drift-gate` (memory records in only one store),
  `cc-archive-drift-gate` (substantive raw sessions never archived)
- ⛔ Rebuild preconditions for `--full-resync` / `rebuild-postgres.py`
  are in `postgresql-reference.md` — drift check first, always

### Searching past sessions — the escalation ladder

Four rungs, cheapest first. **Never grep raw `.gz` ad hoc** — a
`zcat | tr | grep -oiE` search hard-locked the machine on 2026-06-21
(diagnosis: `Code/inscriptions/planning/archive-search-crash-diagnosis-2026-06-21.md`).

| Rung | Tool | Searches |
|---|---|---|
| 0 | `/recall`, `search_memories`/`semantic_search` MCP | distilled **memories** |
| 1 | `/recall` session search, `sessions` table FTS | session **metadata** + Three-P summaries |
| 2 | `/search-sessions`, `search-sessions.py`, `search_sessions` MCP | transcript **content** (`session_chunks`) |
| 3 | `search-sessions.py --show <dir> --turn <n>` | the **exact turn(s)**, verbatim from the index |
| fallback | `search-archives-safe.sh` | bounded ad-hoc grep of raw `.gz` (last resort) |

- **`session_chunks`** (PostgreSQL): one row per user/assistant prose turn,
  GENERATED `tsvector` (GIN) + `gin_trgm_ops` (substring/identifier). Populated
  by `index-session-content.py` (incremental by mtime; main sessions by default,
  `--include-subagents` for the rest). Excludes thinking/tool noise — matches are
  conversation, not base64. A pgvector semantic column is designed but deferred
  (lexical-first, 2026-06-21).
- **`search-archives-safe.sh`** is the safe fallback when the index lacks
  something. Its engine is `_scan_archives.py` (pure-Python, line-oriented) — not
  ripgrep/grep, which on this machine are shell functions routing to the Claude
  Code binary, not standalone tools. Wrapped in nice/ionice/timeout + a
  systemd-run cgroup + a single-run flock so it cannot recreate the crash.

### Cron Jobs

```text
*/5 * * * * venv/bin/python3 scripts/sync-to-postgres.py   # memory sync + auto-embed
0 3 * * 0   venv/bin/python3 scripts/apply-decay.py         # weekly decay
```

`daily-sync.sh` is NOT cron — it runs once per calendar day from the
SessionStart hook via `daily-sync-trigger.sh` (first session of the day;
retries next session on failure). It carries the git sync, the
cc-archives convergence passes, the R2 push, the symlink refresh, and
both drift checks.

### Sync exit codes and gates (audit round two, 2026-09-08)

The PostgreSQL pipeline scripts distinguish "retry later" from "a human
must do something". Non-zero is not automatically an emergency — read the
list, and read the gate line, which names the remedy.

`sync-to-postgres.py` and `sync-sessions-to-postgres.py`:

- **0** — ran to completion (possibly syncing nothing).
- **1** — unexpected error.
- **2** — schema-version mismatch: the script is older or newer than the
  database.
- **4** — the run stopped and the cursor did not move, for one of two
  reasons the gate distinguishes. An *environment fault*: PostgreSQL is
  reachable but not in the expected state — a revoked grant, a missing
  table or column, a full disk. Or a *correlated refusal*: five or more
  rows refused with the same SQLSTATE and none accepted, which is either
  correlated poison or a schema fault (a migration adding a NOT NULL
  column, a unique index the upsert does not name). Nothing was
  quarantined in either case.
- **6** — a rebuild cleared this sync's cursor key mid-run, so the
  position was deliberately not written back. Confirm the rebuild was
  intended; the next run replays from the canonical.
- **7** — more rows were refused in one run than `PA_PG_QUARANTINE_CAP`
  allows (default 200). The database is fine and the rows may genuinely
  be poison; there are simply too many to skip without someone looking.
- **8** — `--quarantine-anyway` was asked for but another instance held
  the advisory lock, so the override did not run. Re-run it.


`index-session-content.py`:

- **0** — ran to completion.
- **2** — psycopg2 missing, a schema-version mismatch, **or an archive
  root that is absent, or exists but contains no `session.meta.json`**.
  The last two are a missing mount or the wrong path, and the indexer
  refuses to run on them rather than concluding that every archive was
  deleted. Every variant raises a problem: a missing psycopg2 or a schema
  mismatch raises `fault`, an absent or empty root raises `degraded`.
- **3** — PostgreSQL unreachable, at connect time or mid-run. Not
  critical: the archive tree is canonical and the index is rebuildable.
  Feeds the `outage` streak, so three in a row raise a problem that the
  next connected run lowers — a `fault` here could never be lowered,
  because the run after an outage usually finds everything already
  indexed and processes nothing.
- **4** — environment fault, as above. Raises `fault`.
- **5** — one or more transcripts were refused **this run**. A transcript
  refused on an earlier run does not fail later runs; it is reported once
  at WARNING and through the gate.

`backfill-embeddings.py`:

- **0** — ran (possibly embedding nothing).
- **1** — Ollama unavailable, or the model not pulled.
- **2** — schema-version mismatch.
- **3** — the endpoint returned wrong-width vectors. Nothing was written.

#### Session-start gates

Three gate files, one per script, all relayed by
`daily-sync-trigger.sh` under the "Infra gates — RELAY THESE TO SHAWN"
header:

- `~/.cache/postgres-sync-memories-gate`
- `~/.cache/postgres-sync-sessions-gate`
- `~/.cache/index-session-content-gate`

Each has a sidecar `<gate>.state.json`, which is the source of truth; the
gate file is *rendered* from it and should never be edited by hand. The
state holds a set of **independent problems**, and the gate's first line
is how many are standing, one detail line each. Problems therefore never
overwrite each other, and the trigger prints all of them.

The problems, and what lowers each — the rules live in
`scripts/_sync_gate.py::next_state`, and the transition table is a test:

| Problem | Raised by | Lowered by |
|---|---|---|
| `fault` | any non-zero exit (1, 2, 4, 6, 7, 8) | a later run of the same script that completed: connected, lock taken, ≥1 row processed, none refused |
| `correlated` | a wholly-refused batch held rather than quarantined | the same as `fault` |
| `quarantine` | any run that quarantined ≥1 row (running total of rows actually written to the quarantine file) | **only** `--ack-quarantine` on that script — later rows are not evidence about the rows that were dropped |
| `degraded` | a missing canonical, an absent or unpopulated archive root, ids dropped with the cursor held | a later run that completes, or that is idle without being degraded again |
| `outage` | three consecutive runs that could not reach PostgreSQL | any run that connected — and lowering it touches nothing else |
| `refusals` | transcripts the indexer could not index (whole memory, not this run's scope) | any run after which the memory is empty — the count is already whole-memory, so the run's scope is irrelevant |

**A PostgreSQL outage is not an exit code.** Both syncs exit 0 when the
database is unreachable: the JSONL and the archive tree are canonical, so
an outage is not a failure of the sync, and failing loudly every five
minutes would train everyone to ignore it. The `outage` problem is what
surfaces it, after about fifteen minutes.

`--ack-quarantine` is a **state-only** operation: it runs no sync, takes
no advisory lock, and opens no database connection, so a busy cron tick
can never stop you dismissing something you have read. It records
`{acked_at, acked_count}` in the sidecar, reports "nothing to do" when
no problem stands, and exits **9** if the state on disk still carries the
problem afterwards — its verdict comes from re-reading the file, not from
what it meant to write.

Every read-modify-write of a gate — including that one — is serialised by
an exclusive `<gate>.lock` (bounded at ten seconds, then reported) and
written atomically, so a tick and an acknowledgement cannot interleave to
resurrect a dismissed problem.

**A gate that cannot be written never changes what a script does.** If
`~/.cache` is unwritable, a schema mismatch still exits 2 and an absent
archive root still exits 2; the failure to persist is logged at ERROR in
its own right. The acknowledgement is the one command for which a
persistence failure *is* the error, and it exits 9.

The trigger also reports a gate that has **never been written**: a script
that is not running writes no gate at all, which is the one failure a
gate cannot report about itself.

Beyond that, the two kinds of gate are judged differently, because they
fail differently:

- **`postgres-sync-memories-gate` is written by cron every five
  minutes**, so silence itself is the signal, and only the *kind* of
  silence differs. A gate written since boot is late when its own age
  passes 30 minutes (`PA_GATE_STALE_MINUTES`): cron was running and
  stopped. A gate *older than the boot* means cron has not run at all
  since the machine came up, and that is reported once the uptime passes
  a 10-minute grace (`PA_GATE_BOOT_GRACE_MINUTES`) — waiting out the
  full window there would only delay the news.
- **`postgres-sync-sessions-gate` and `index-session-content-gate` are
  written by session hooks**, and wall-clock age says nothing about
  them: a fortnight away, or one very long session, leaves them
  untouched and nothing is wrong. They are late only when a session has
  *ended* and the hook did not run — that is, when a `session.meta.json`
  under `~/cc-archives` (`PA_CC_ARCHIVES`) is more than 15 minutes
  (`PA_HOOK_GATE_LAG_MINUTES`) newer than the gate. If that root does
  not exist, the trigger says the liveness check is **off** rather than
  saying nothing: a check that cannot run is not a clean bill of health.

The freshness test looks at the newest of the gate file and its
`.state.json` sidecar, so a run that saved its state but could not render
the gate is reported as a missing gate file rather than as a dead script.

To clear a quarantine problem once the rows have been dealt with:

```bash
~/personal-assistant/venv/bin/python3 \
    ~/personal-assistant/scripts/sync-to-postgres.py --ack-quarantine
```

#### Environment variables

- `PA_PG_QUARANTINE_CAP` (default 200) — how many rows one run may
  quarantine before it stops and reports instead. `0` stops at the first
  refusal. A negative or non-numeric value is warned about and ignored.
- `PA_PG_QUARANTINE_ANYWAY=1` — for one run, quarantine a wholly-refused
  batch instead of holding the cursor. Use after checking the schema.
  Equivalent to `--quarantine-anyway`.
- `OLLAMA_BASE_URL` — the embedding endpoint; an empty value falls back
  to localhost.
- `PA_GATE_STALE_MINUTES` (default 30) — how long the cron-written
  memories gate may go unrefreshed before the trigger calls the sync
  dead.
- `PA_GATE_BOOT_GRACE_MINUTES` (default 10) — how long after boot the
  cron gate is left alone.
- `PA_HOOK_GATE_LAG_MINUTES` (default 15) — how much newer than a
  hook-written gate an archived `session.meta.json` must be before the
  hook is called late.
- `PA_CC_ARCHIVES` (default `~/cc-archives`) — where the trigger looks
  for archived sessions when judging the hook-written gates.
- `PA_UPTIME_FILE` (default `/proc/uptime`) — where the trigger reads the
  machine's uptime. Overridable so the boot rules can be tested without a
  reboot.

  Each of the three numeric values must be a positive integer; anything
  else falls back to the default, because they are expanded inside
  `$(( ))` where bash would otherwise evaluate them as arithmetic
  expressions. `PA_GATE_STALE_HOURS` is retired — a single wall-clock age
  described neither kind of gate.

### Test Suite

Tests in `tests/` covering extraction hook, retrieval hook, fetch-memories,
sync scripts, session sync, bulk archive, embedding client, tag gardening,
and Zotero queries. Run with `pytest` from the repo root (venv required).

### Architectural Decisions

- **JSONL is canonical; PostgreSQL is derived** — rebuildable from JSONL
- **Embeddings are PostgreSQL-only** — not stored in JSONL (derived data)
- **Local-first Zotero** — reads are SQLite (immutable mode), writes are
  API-only (never write to Zotero SQLite)
- **Ollama for embeddings ($0)** — Haiku for extraction (quality matters more)
- **Batch API + prompt caching** — for cost optimisation on all Haiku bulk work
- **Summaries generated at extraction time** — ≤150 chars via Haiku, stored in
  JSONL, displayed in session-start retrieval

### What's Not Built Yet

- **Auto-index session content at archive time.** `index-session-content.py` is
  run manually / incrementally; wiring it into the post-archive hook chain
  (alongside `sync-sessions-to-postgres.py`) would keep `session_chunks` fresh
  with no manual step. Designed for, not yet wired (2026-06-21).
- **Semantic session-content search.** The `session_chunks.embedding` pgvector
  column + HNSW index are designed (commented in `schema.sql`) but deferred —
  lexical FTS first. Activate by backfilling embeddings (reusing `embed.py`).
- _Otherwise empty — see backlog for remaining non-infrastructure items._
