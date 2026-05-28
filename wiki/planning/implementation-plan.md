# Implementation Plan

This document tracks the implementation of the personal assistant system.

**Status:** Phase 1 complete, Phase 2 complete, Phase 3 complete, Phase 4 implemented (needs testing)
**Started:** 2026-02-07
**Last updated:** 2026-02-08 (Phase 4 implementation)

---

## Pre-Implementation Checklist

- [x] Design review complete (cc-design-questions-response.md)
- [x] Repository structure decided (pa-repository-structure.md)
- [x] Repo moved to ~/personal-assistant/
- [x] Directory structure created
- [x] .gitignore created
- [x] Initial commit made (2026-02-07)

---

## Phase 1: Core Extraction (Days 1-3)

Goal: Memories are automatically extracted from sessions and stored in JSONL.

### 1.1 Directory Structure

```bash
mkdir -p ~/personal-assistant/{memories,tasks/projects/{research,business,personal},hooks,scripts,commands,reports/{weekly,collaborators,retros},standups,logs}
```

- [x] Create directory structure
- [x] Create .gitignore
- [x] Create empty memories/memories.jsonl
- [x] Create memories/tag-vocabulary.txt with seed tags
- [x] Create tasks/FOCUS.md, SYSTEM.md, inbox.md, waiting-for.md
- [x] Create tasks/projects/{research,business,personal}/_PROJECT.md
- [x] Create CLAUDE.md with PA persona
- [x] Initial git commit (2026-02-07)

### 1.2 Extraction Hook

File: `hooks/extraction-hook.py`

- [x] Implement transcript parsing (read JSONL, find new content since cursor) (2026-02-07)
- [x] Implement Haiku extraction call with categories prompt (2026-02-07)
- [x] Implement tag normalisation (lowercase, hyphens, skip auto-singularisation) (2026-02-07)
- [x] Implement memory formatting with schema fields (2026-02-07)
- [x] Implement append to memories.jsonl (2026-02-07)
- [x] Implement cursor tracking (only advance after successful append) (2026-02-07)
- [x] Implement error logging to logs/extraction.log (2026-02-07)
- [x] Add `source` field to distinguish extraction vs manual (2026-02-07)

### 1.3 Hook Configuration

File: `~/.claude/settings.json`

- [x] Configure Stop hook → extraction-hook.py (2026-02-07)
- [x] Configure PreCompact hook → extraction-hook.py (2026-02-07)
- [x] Configure SessionEnd hook → extraction-hook.py (2026-02-07)
- [x] Test hooks fire correctly (2026-02-07, live test session 3)

### 1.4 Extraction Testing

- [x] Have a test conversation with extractable content (2026-02-07, synthetic transcript)
- [x] Verify memories.jsonl contains valid JSON (2026-02-07)
- [x] Verify cursor file tracks position (2026-02-07)
- [x] Verify error log captures failures (2026-02-07)
- [x] Verify tag normalisation works (2026-02-07)

### 1.5 Basic Retrieval: SessionStart Injection

File: `hooks/session-start-retrieval.py`

- [x] Query recent memories (last 7 days) (2026-02-07)
- [x] Query permanent categories (decision, architecture, methodology, etc.) (2026-02-07)
- [x] Query active commitments and waiting-for (2026-02-07)
- [x] Format for context injection (2026-02-07)
- [x] Configure SessionStart hook (2026-02-07)
- [x] Test context appears in new sessions (2026-02-07, live test session 3)

### 1.6 /recall Command

File: `commands/recall.md`

- [x] Implement search by keyword (2026-02-07)
- [x] Implement filter by category (2026-02-07)
- [x] Implement filter by tag (2026-02-07)
- [x] Return top 10 matches with context (2026-02-07)
- [x] Test command works (2026-02-07, live test session 3)

### 1.7 /remember Command

File: `commands/remember.md`

- [x] Parse content and optional category/tags (2026-02-07)
- [x] Suggest category if not specified (2026-02-07)
- [x] Apply tag normalisation (2026-02-07)
- [x] Write directly to memories.jsonl with source: "manual" (2026-02-07)
- [x] Confirm capture (2026-02-07)
- [x] Test command works (2026-02-07, live test session 3)

---

## Phase 2: Query Infrastructure (Days 3-5)

Goal: PostgreSQL available for structured queries.

### 2.1 PostgreSQL Setup

- [x] Install PostgreSQL native (apt install) (2026-02-08)
- [x] Create database with peer auth: `createdb claude_memories` (2026-02-08)
- [x] Create schema file from design doc (2026-02-08)
- [x] Run schema SQL — 3 tables, 9 indexes, 3 views, 27 category_config rows (2026-02-08)
- [x] Verify tables and views created (2026-02-08)

### 2.2 Sync Script

File: `scripts/sync-to-postgres.py`

- [x] Read memories.jsonl from last sync position (2026-02-08)
- [x] Insert new memories to PostgreSQL (2026-02-08)
- [x] Handle conflicts (ON CONFLICT DO NOTHING) (2026-02-08)
- [x] Update sync cursor after success (2026-02-08)
- [x] Test manual sync works — 390 memories synced (2026-02-08)
- [x] Decay script (scripts/apply-decay.py) with --dry-run support (2026-02-08)
- [x] Rebuild script (scripts/rebuild-postgres.py) for full resync (2026-02-08)
- [x] Unit tests — 24 tests covering cursor, parsing, tuple conversion (2026-02-08)

### 2.3 Cron Setup

- [x] Add cron job for sync every 5 minutes (2026-02-08)
- [x] Verify sync runs automatically — confirmed firing at 5-min intervals (2026-02-08)
- [x] Check logs for errors — clean runs in logs/sync.log (2026-02-08)

### 2.4 /catchup Command — Dropped

Dropped per Phase 2 planning: extraction hook's stale-cursor recovery handles the main use case.

---

## Phase 3: Task System (Days 5-10)

Goal: Focus tracking and accountability operational.

### 3.1 Task File Structure

- [x] Create tasks/FOCUS.md with current reality (2026-02-08)
- [x] Create tasks/SYSTEM.md with initial parameters (2026-02-07)
- [x] Create tasks/inbox.md (empty) (2026-02-07)
- [x] Create tasks/waiting-for.md (empty or with current items) (2026-02-07)
- [x] Create tasks/projects/research/_PROJECT.md (2026-02-07)
- [x] Create tasks/projects/business/_PROJECT.md (2026-02-07)
- [x] Create tasks/projects/personal/_PROJECT.md (2026-02-07)

### 3.2 Core Commands

File: `commands/capture.md`
- [x] Append to inbox.md with timestamp (2026-02-08)
- [x] Confirm capture (2026-02-08)
- [ ] Test command works

File: `commands/focus.md`
- [x] Implement add/remove/swap (2026-02-08)
- [x] Enforce 2-item limit (2026-02-08)
- [x] Track focus changes (2026-02-08)
- [ ] Test command works

File: `commands/done.md`
- [x] Find matching task in focus or inbox (2026-02-08)
- [x] Archive to done/YYYY-MM.md (2026-02-08)
- [x] Remove from FOCUS.md if present (2026-02-08)
- [x] Prompt for next focus if slot freed (2026-02-08)
- [ ] Test command works

File: `commands/standup.md`
- [x] Load FOCUS.md, SYSTEM.md, inbox.md, waiting-for.md (2026-02-08)
- [x] Calculate days in focus, overdue deadlines (2026-02-08)
- [x] Detect patterns from memories (if available) (2026-02-08)
- [x] Generate standup with escalation levels (2026-02-08)
- [x] Save to standups/YYYY-MM-DD.md (2026-02-08)
- [ ] Test command works

### 3.3 SessionStart Accountability Hook

File: `hooks/session-start-accountability.py`

- [x] Count inbox items (2026-02-08)
- [x] Count waiting-for items (2026-02-08)
- [x] Load focus summary (2026-02-08)
- [x] Display session start banner (2026-02-08)
- [x] Prompt for /standup (2026-02-08)
- [ ] Test hook fires on new sessions

### 3.4 Memory Integration

- [x] Add slip detection to extraction prompt (retrospective categories) (2026-02-08)
- [x] Add system_evolution, system_friction, system_success categories (2026-02-08)
- [ ] Test extraction captures task-related patterns

---

## Phase 4: Reviews and Integrations (Days 10-14)

Goal: Weekly reviews and external integrations working.

### 4.1 /review Command

File: `commands/review.md`

- [x] Gather completion data for the week (2026-02-08)
- [x] Gather focus item history (2026-02-08)
- [x] Gather commits per project (from git) (2026-02-08)
- [x] Generate internal review with scorecard, patterns, hard question (2026-02-08)
- [x] Generate collaborator reports from tasks/collaborators.md (2026-02-08)
- [x] Save to reports/weekly/ and reports/collaborators/ (2026-02-08)
- [ ] Test command works

### 4.2 /retro Command

File: `commands/retro.md`

- [x] Gather system metrics (completion rate, focus churn, etc.) (2026-02-08)
- [x] Review system interactions from memories (2026-02-08)
- [x] Generate retrospective with parameter review (2026-02-08)
- [x] Propose adjustments with evidence (2026-02-08)
- [x] Apply approved changes to SYSTEM.md (2026-02-08)
- [x] Save to reports/retros/ (2026-02-08)
- [ ] Test command works

### 4.3 /sync-board Command

File: `commands/sync-board.md`

- [x] Map markdown state to GitHub Issues (2026-02-08)
- [x] Create/update/close issues via `gh` CLI (2026-02-08)
- [x] Label setup and management (2026-02-08)
- [x] Diff preview before execution (2026-02-08)
- [ ] Test command works

### 4.4 /process-email Command

File: `commands/process-email.md`

- [x] Determine email access method — Gmail MCP with manual fallback (2026-02-08)
- [x] Categorise emails (action, waiting-for, reference, unclear, skip) (2026-02-08)
- [x] Create tasks from actionable emails to inbox.md (2026-02-08)
- [x] Add to waiting-for as appropriate (2026-02-08)
- [x] Manual paste fallback mode (2026-02-08)
- [ ] Gmail MCP server setup (infrastructure prerequisite)
- [ ] Test command works

### 4.5 Infrastructure

- [x] Create tasks/collaborators.md with Brian entry (2026-02-08)
- [x] Add COMMAND_MARKERS for 4 new commands in extraction-hook.py (2026-02-08)
- [x] Add .last-email-triage to .gitignore (2026-02-08)

---

## Phase 5: Zotero and Polish (Week 3+)

Goal: Scholarly workflow integration.

### 5.1 Zotero Read Integration

- [ ] Implement /read command (fetch item, present overview, guided reading)
- [ ] Implement /cite command (search Zotero, insert citation)
- [ ] Implement /synthesise command (load collection, thematic synthesis)
- [ ] Test commands work with real Zotero library

### 5.2 Zotero Write Sync

File: `scripts/sync-to-zotero.py`

- [ ] Find source_insight memories with zotero_key since last sync
- [ ] Create/append to child notes in Zotero
- [ ] Handle edge cases (deleted items, rate limits)
- [ ] Set up cron job for hourly sync
- [ ] Test sync works

### 5.3 /tags Command

File: `commands/tags.md`

- [ ] Load tag statistics from PostgreSQL
- [ ] Identify singleton tags
- [ ] Identify similar tags (Levenshtein)
- [ ] Suggest consolidations
- [ ] Apply changes to JSONL and Postgres
- [ ] Test command works

### 5.4 /research-extract Command

File: `commands/research-extract.md`

- [ ] Load full transcript for specified session
- [ ] Run extraction with no thinking truncation
- [ ] Tag with research_session marker
- [ ] Test command works

---

## Dependencies

### Python Packages

```bash
pip install anthropic psycopg2-binary pyzotero
```

### Environment Variables

```bash
export ANTHROPIC_API_KEY="..."
export CLAUDE_MEMORIES_DB="postgresql://localhost/claude_memories"
export ZOTERO_LIBRARY_ID="..."
export ZOTERO_API_KEY="..."
export ZOTERO_LIBRARY_TYPE="user"
```

### External Services

- PostgreSQL (local or Docker)
- Zotero account with API access (Phase 5)
- Gmail access (Phase 4, if using /process-email)

---

## Notes

- JSONL is always canonical. PostgreSQL is derived.
- Zotero read operations work before write sync is implemented.
- Commands are implemented as markdown files in commands/ that Claude interprets.
- Hooks are Python scripts that fire on Claude Code events.
