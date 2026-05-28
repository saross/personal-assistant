# Memory System Benchmarking: Open Brain vs Personal Assistant

Created: 2026-03-04
Source: Nate's Substack — "Grab the System That Closes Open Loops" and "Every AI You Use Forgets You — Here's the Fix"

## Context

Nate (natesnewsletter.substack.com) is an LLM productivity specialist who has
built and documented a personal memory/knowledge management system called "Open
Brain." His two articles describe complementary layers: a conceptual framework
(8 building blocks, 12 rules) and a concrete implementation (PostgreSQL + Model
Context Protocol (MCP) server + semantic embeddings).

This document benchmarks our personal-assistant system against his, identifies
gaps worth closing, and notes areas where we're already ahead.

## Comparative Analysis

### Where we're comparable or ahead

| Capability | Open Brain | Personal Assistant | Assessment |
|---|---|---|---|
| **Capture friction** | Manual drop box (Slack, chat) | Hook-based auto-extraction from CC sessions + `/capture` for manual | **Ahead** — hooks extract without user action |
| **Classification** | Embedding-based auto-sort | LLM classification at extraction time (category, tags, salience) | **Comparable** — different mechanisms, similar outcome |
| **Lifecycle management** | Not described (appears permanent) | Decay rules per category, `/retro` reviews, active/inactive status | **Ahead** — memories expire appropriately |
| **Retrieval** | Semantic search via embeddings | Full-text search (PostgreSQL `tsvector`) + `/recall` command | **Mixed** — see gaps below |
| **Weekly synthesis** | Weekly review prompt | `/review` weekly + `/retro` monthly + `/standup` daily | **Ahead** — more granular accountability cycle |
| **Self-hosting** | PostgreSQL + MCP server (~$0.10–0.30/month cloud) | JSONL + local PostgreSQL (zero cost, fully offline) | **Comparable** — different trade-offs |
| **Structured categories** | Not described in detail | 15+ categories with different retention, salience levels | **Ahead** — more nuanced taxonomy |
| **Accountability integration** | Not described | Confrontational standup, escalation rules, focus limits | **Ahead** — memory feeds into behaviour change |

### Where Open Brain is ahead (our gaps)

| Gap | Description | Severity | Effort to close |
|---|---|---|---|
| **MCP server for cross-tool access** | Open Brain exposes memories to *every* MCP-capable tool (Claude.ai, ChatGPT via plugin, Cursor, etc.). Our memories are locked inside CC sessions only. Open WebUI, other AI tools, and even CC sessions in other projects can't query them. | **High** | Medium — we have the database; need to build the MCP server |
| **Semantic / embedding search** | Open Brain uses vector embeddings for conceptual similarity ("things like X"). Our FTS only finds keyword matches. Misses conceptual neighbours (e.g., searching "debugging false assumptions" won't find the brightness/display memory unless those exact words appear). | **Medium** | Medium — add pgvector extension, generate embeddings via Ollama, update sync script |
| **Cross-tool portability** | His system works identically whether he's in Claude, ChatGPT, Cursor, or anything else MCP-capable. Ours requires being inside a CC session in this repository. | **High** | Solved by the MCP server (same gap) |

### Things to *not* adopt

| Open Brain feature | Why skip it |
|---|---|
| 8 building blocks framework | Designed for people starting from zero. Our hook + JSONL + PostgreSQL pipeline is already more capable. Adopting this would be a regression. |
| 45-minute copy-paste setup | Marketing for his audience. Our system is bespoke and deliberately so. |
| Cloud hosting | We have local infrastructure (sapphire, zbook) that's more private and cheaper. No reason to move to cloud. |
| Permanent storage (no decay) | Our lifecycle/decay model is a deliberate design choice — it prevents memory bloat and keeps retrieval sharp. Nate's system will face this problem eventually. |

## Key Insight

Nate's best conceptual contribution: **"the system does work whether or not you
feel motivated today."**

Our hooks already embody this for the *extraction* side — memories get captured
regardless of user motivation. But the *retrieval* side still depends on the
user remembering to ask (`/recall`), or on CC's startup hook loading recent
memories.

An MCP server that lets any AI tool passively query context would close this
loop: retrieval becomes automatic too, not just extraction.

## Recommended Actions

1. **MCP memory server** (added to backlog 2026-03-04) — highest-value gap to
   close. Exposes our existing PostgreSQL memory database to any MCP-capable
   tool. Enables cross-tool access without changing the underlying data model.

2. **Semantic embeddings** (future, not yet backlogged) — add pgvector to
   PostgreSQL, generate embeddings via Ollama (sapphire or zbook), update
   `sync-to-postgres.py` to embed on ingest. Improves recall quality for
   conceptual searches. Can be done incrementally after MCP server exists.

3. **Monitor Open Brain's evolution** — Nate's audience will stress-test his
   system at scale. Watch for solutions to problems we haven't hit yet
   (embedding model choice, MCP auth patterns, memory deduplication at scale).
