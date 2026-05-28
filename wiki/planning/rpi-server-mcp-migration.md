# Plan: Migrate Memory MCP Server to rpi-server (Always-On HTTP)

**Status:** Deferred (not yet started)
**Created:** 2026-04-12
**Estimated effort:** 1–2 days
**Trigger to implement:** Booting into Windows on zbook/amd-tower for Cowork
work becomes a regular pattern, OR cross-machine memory access becomes a
recurring need

## Context

The current `memory_mcp.py` is a stdio-only server that runs as a subprocess
on whichever machine is hosting Claude Code. It cannot be reached over the
network, and the data it serves (PostgreSQL memory database, JSONL file) is
single-host: PostgreSQL uses peer-auth via Unix socket, so the server must
run on the machine that owns the database.

Constraint surfacing this plan: the user wants to use **Claude Cowork**,
which is currently macOS/Windows only. The user dual-boots Windows on
`zbook` and `amd-tower`. Booting into Windows means Linux processes
(including memory_mcp.py) are not running. The MCP database becomes
unreachable from Cowork unless the server lives somewhere always-on.

`rpi-server` (192.168.1.100) is the user's intended always-on hub for
network services (DNS-adjacent, storage, light services). Compute and ML
workloads run on `sapphire`. This makes rpi-server the natural host for an
HTTP MCP server: it survives reboots of work machines, is reachable on the
LAN, and matches the existing role split.

## What This Plan Does

Move the canonical memory database (or a reachable copy) to rpi-server, run
`memory_mcp.py` as an HTTP service on it, and have all client machines —
zbook (Linux + Windows/Cowork), amd-tower (Linux + Windows/Cowork),
sapphire — connect via the LAN.

## Architecture

```text
┌──────────────────────────────────────────────────────────┐
│ rpi-server (192.168.1.100) — always on                   │
│                                                          │
│   ~/personal-assistant/                                  │
│     ├─ data/ (pa-data submodule, git-synced)             │
│     │   └─ memories/memories.jsonl (canonical)           │
│     ├─ scripts/memory_mcp.py (HTTP transport)            │
│     ├─ scripts/sync-to-postgres.py (5-min cron)          │
│     └─ venv/                                             │
│                                                          │
│   PostgreSQL claude_memories (TCP listener on            │
│     127.0.0.1:5432, peer-auth via Unix socket            │
│     for the local memory_mcp.py process)                 │
│                                                          │
│   memory_mcp.py listening on 0.0.0.0:8765                │
│   with bearer-token auth                                 │
└──────────────────────────────────────────────────────────┘
                    ▲          ▲          ▲
                    │ HTTP     │ HTTP     │ HTTP
                    │ + auth   │          │
        ┌───────────┴───┐  ┌───┴───────┐  ┌────┴──────┐
        │ zbook (Linux) │  │ zbook     │  │ amd-tower │
        │ Claude Code   │  │ (Windows) │  │ (any OS)  │
        │               │  │ Cowork    │  │           │
        └───────────────┘  └───────────┘  └───────────┘
```

## Key Decisions

### 1. Where does the canonical data live?

Two viable options:

**Option A: rpi-server is canonical.** The pa-data submodule lives on
rpi-server. zbook/amd-tower pull updates via git. PostgreSQL on rpi-server
is the only PostgreSQL instance; `sync-to-postgres.py` runs on rpi-server.

- Pros: single source of truth, no merge conflicts on the JSONL
- Cons: requires rpi-server to host the git remote (or git pull from GitHub
  on a cron); writing memories from a work machine means git push first

**Option B: Each machine keeps its own copy, rpi-server is one of them.**
The pa-data submodule is on every machine via the existing setup. Each
machine has its own PostgreSQL. The MCP server on rpi-server uses
rpi-server's local copies.

- Pros: no change to existing extraction-hook flow; offline work continues
- Cons: rpi-server's database can lag behind work machines that have
  extracted memories but haven't pushed yet

**Recommended: Option A**, with the extraction hook on work machines
configured to push to git after each extraction (or a periodic cron). The
read path is what matters for cross-machine access — writes can be
asynchronous with a few minutes of lag.

### 2. Transport: HTTP vs stdio

- stdio is unusable for cross-machine
- FastMCP supports streamable HTTP via `mcp.run(transport="streamable-http",
  host="0.0.0.0", port=8765)`
- One-line change in `memory_mcp.py`'s entry point, gated by an env var or
  CLI flag so the same script supports both modes

### 3. Authentication

Bearer-token check via FastMCP middleware. Token stored in `.env` on each
machine. On a trusted home LAN this is "good hygiene"; if the server is
ever exposed to the internet (Cloudflare Tunnel, etc.) it becomes
mandatory.

```python
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

EXPECTED_TOKEN = os.environ["MCP_BEARER_TOKEN"]

@mcp.middleware
async def auth(request: Request, call_next):
    auth_header = request.headers.get("authorization", "")
    if auth_header != f"Bearer {EXPECTED_TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)
```

(Exact API depends on FastMCP version — verify at implementation time.)

### 4. PostgreSQL on rpi-server

The Pi's resource constraints matter:

- PostgreSQL with pgvector extension on a Raspberry Pi 4/5 is feasible but
  not generous. The 12K-memory database is small (~50 MB on disk).
- pgvector index build is the heaviest operation; happens once, then
  incremental adds during sync are cheap
- Embeddings are generated by Ollama on **sapphire**, not rpi-server. The
  sync script needs to call Ollama remotely (already supported via
  `OLLAMA_HOST` env var)
- Avoid running `apply-decay.py` cron during peak hours; weekly Sunday 3am
  is fine

### 5. Ollama dependency for semantic search

`semantic_search` tool needs Ollama for query embeddings. Two approaches:

- **Run Ollama on rpi-server** — too slow on Pi hardware for embeddings
- **Call Ollama on sapphire from rpi-server** — set `OLLAMA_HOST` env var
  to `http://sapphire:11434` in the rpi-server's MCP server environment.
  Sapphire is already always-on per the network plan.

Recommended: sapphire-hosted Ollama, accessed by rpi-server over the LAN.
Adds a hop but avoids putting CPU-heavy embedding work on the Pi.

### 6. Cowork-specific configuration

Cowork (Windows) needs to register the MCP server in its config file. The
exact format depends on Cowork's MCP support. Likely a JSON file in
`%APPDATA%\Claude\` with an entry like:

```json
{
  "mcpServers": {
    "memory": {
      "transport": "http",
      "url": "http://192.168.1.100:8765/",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

Verify against current Cowork docs at implementation time. Note: this
config has the bearer token in plaintext on the Windows partition. If
that's a concern, use OS keychain integration.

## Implementation Sequence

### Phase 1: HTTP transport mode for memory_mcp.py (1–2 hours)

- Add `--http` and `--port` CLI flags to memory_mcp.py
- Branch on the flag to call either `mcp.run()` (stdio default) or
  `mcp.run(transport="streamable-http", host=..., port=...)`
- Run locally on zbook, register from a second Claude Code session via
  `claude mcp add memory --transport http http://localhost:8765/`
- Verify all 5 tools work end-to-end via HTTP transport

### Phase 2: Authentication (2–3 hours)

- Add bearer-token middleware
- Generate a 32-character random token, store in `.env` as
  `MEMORY_MCP_TOKEN`
- Update tests to mock the auth layer
- Test that requests without the token return 401

### Phase 3: rpi-server provisioning (4–6 hours)

- Install PostgreSQL + pgvector extension on rpi-server
- Clone personal-assistant + pa-data submodule
- Apply schema.sql, sync from JSONL via rebuild-postgres.py
- Configure cron jobs (sync-to-postgres every 5 min, apply-decay weekly)
- Configure systemd service for memory_mcp.py (always running)
- Verify ports, firewall rules
- Set up sync mechanism for the JSONL — see next phase

### Phase 4: Multi-machine sync mechanism (3–4 hours)

The hard part. Options:

a. **Git-based**: extraction-hook commits + pushes after each extraction.
   rpi-server pulls on a 5-min cron. Lag: up to 5 min.
b. **rsync-based**: extraction-hook syncs the JSONL via rsync to
   rpi-server. Lag: seconds. Doesn't update git.
c. **MCP write tools**: extraction-hook posts new memories to the rpi
   server via MCP write tool. Requires V2 MCP server with write tools
   (separate plan: `mcp-server-v2-write-tools.md`).

Recommended: **(a) git-based for V1**, simple and matches existing pattern.
Migrate to (c) if the lag becomes annoying.

### Phase 5: Client registration (1 hour)

- On each work machine, register the rpi-server MCP via
  `claude mcp add memory --transport http --scope user --header "Authorization: Bearer ..." http://192.168.1.100:8765/`
- Test from each machine
- Document the registration command in `infrastructure-reference.md`

### Phase 6: Cowork registration (1 hour, after first Windows boot)

- Boot into Windows on zbook
- Install Cowork
- Add the MCP server to Cowork's config file
- Test from Cowork

### Phase 7: Decommission stdio-only flow (optional)

- Once HTTP works reliably from all machines, the local stdio mode is
  redundant for normal use
- Keep the stdio mode in the script as a fallback for offline work
- Document when to use which

## Verification

1. `/audit` over all changed code (memory_mcp.py, any new scripts)
2. Unit tests for the auth middleware
3. End-to-end test from each Linux machine
4. End-to-end test from Cowork (Windows)
5. Network failure test: kill the MCP server, verify clients get a clear
   error
6. Performance test: 100 sequential queries to measure round-trip latency

## Open Questions

- **Submodule sync conflict resolution**: if zbook and amd-tower both
  extract memories before either pushes, the JSONL gets a merge conflict.
  How to handle? (Likely: extraction-hook always rebases before commit;
  conflicts are JSONL line-level so trivially resolvable by appending
  both sides.)
- **pgvector on Pi performance**: real-world latency for semantic search
  on rpi-server hardware? May need to benchmark.
- **Cowork's exact MCP config format**: not documented in current public
  Anthropic materials we've seen — verify at implementation time.
- **What happens to the existing local-only flow?** Keep both modes, or
  deprecate stdio? Recommend keeping both — stdio is useful for working
  offline or on a laptop disconnected from the LAN.

## Out of Scope

- Internet exposure (Cloudflare Tunnel, etc.) — separate decision
- Multi-user / multi-tenant support — single-user assumption
- Migrating to a different always-on host (NAS, cloud VM)
- Replacing the JSONL canonical with a different storage layer

## Why Defer

This is real work (1–2 days) for a use case that hasn't materialised yet.
Cowork on Linux may launch and obsolete the Windows-boot motivation.
Cross-machine memory access is currently aspirational rather than urgent.
Better to revisit when there's a concrete trigger:

- Boot into Windows for Cowork at least 3 times in a 2-week window
- A research workflow concretely benefits from Cowork's autonomous mode +
  memory access
- The CC Max audit reveals a different architectural direction
