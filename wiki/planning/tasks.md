# Active Task List

**Last updated:** 2026-02-08

## Current Status

Phase 1 (memory extraction, injection, /recall, /remember) is complete and live-tested.
Phase 3 (task system) is implemented — commands, accountability hook, and memory integration done. Needs live testing.
Phase 4 (reviews and integrations) is implemented — /review, /retro, /sync-board, /process-email commands created. Needs live testing. Gmail MCP server setup still pending.
Project-specific memory loading implemented — extraction tags memories with project, retrieval boosts same-project memories.

---

## Backlog: Phase 1 Polish

Minor issues identified during live testing. None are blockers.

- [x] **Verify /remember deduplication fix** — `COMMAND_MARKERS` filter in extraction-hook.py needs to be exercised by a real Stop hook firing after a /remember usage. Will confirm naturally in next session that uses /remember. (2026-02-08: COMMAND_MARKERS list verified complete for all 6 commands)
- [x] **/recall: no-argument behaviour** — Updated recall.md with explicit stats display format: total count, source breakdown, category breakdown (top 10), and 5 most recent memories as preview. (2026-02-08)
- [x] **/recall: zero-match guidance** — Updated recall.md with explicit zero-match response template suggesting broader keywords, dropping filters, tag search, recent browse, and bare /recall for categories. (2026-02-08)
- [ ] **/recall: `recent` keyword + 10-result limit interaction** — Unclear whether `recent` (last 7 days) should also be capped at 10 results or show all recent memories.
- [ ] **/remember: no minimum content length guard** — Extraction hook requires 500 chars; manual capture accepts anything. Probably fine as-is (short phrases are legitimate), but worth a conscious decision.

## Backlog: Phase 3 — Live Testing

Commands are implemented. Partially verified in live session 2026-02-08:

- [x] SessionStart accountability hook fires — banner appears alongside memory context (2026-02-08)
- [x] `/capture test item` — verified inbox.md has new entry (2026-02-08)
- [ ] `/focus` — not yet tested as slash command (manually edited FOCUS.md instead)
- [ ] `/focus remove` — not yet tested
- [ ] `/focus add` — not yet tested
- [x] `/standup` — full output with escalation (day 1 = neutral), saves to standups/ (2026-02-08)
- [ ] `/done` on a test item — verify archive created, slot cleared, refocus prompt
- [ ] Extraction hook still works — new COMMAND_MARKERS filter Phase 3 commands

## Backlog: Phase 2 — Query Infrastructure

- [x] PostgreSQL setup — native install with peer auth, pg_trgm enabled (2026-02-08)
- [x] Schema — 3 tables (memories, sync_state, category_config), 9 indexes, 3 views (2026-02-08)
- [x] Sync script (JSONL → PostgreSQL) — 390 memories synced, cursor-based (2026-02-08)
- [x] Decay script — marks expired memories inactive per category_config rules (2026-02-08)
- [x] Rebuild script — truncate + resync from JSONL (2026-02-08)
- [x] Unit tests — 24 new tests (94 total), all pass (2026-02-08)
- [x] Cron job for sync — installed and verified running every 5 minutes (2026-02-08)
- [x] `/catchup` command — dropped; extraction hook's stale-cursor recovery handles this (2026-02-08)

## Backlog: Phase 4 — Live Testing

Commands are implemented. Need live testing:

- [ ] `/review` — run with current week's data, verify scorecard, collaborator report for Brian
- [ ] `/retro` — run with February data (partial month), verify metrics and parameter review
- [ ] `/sync-board` — run initial sync, verify Issues created from FOCUS.md
- [ ] `/process-email` — test manual paste mode (Gmail MCP not yet configured)
- [ ] Gmail MCP server selection and setup (infrastructure prerequisite for /process-email MCP mode)

---

## Completed

- [x] **Phase 1: Memory system** — extraction hook, SessionStart injection, /recall, /remember (2026-02-07)
- [x] **Deduplication fix** — extraction hook now filters /remember and /recall exchanges from transcript before sending to Haiku (2026-02-07)
- [x] **Code audit** — 5-agent audit cycle, all critical/medium issues resolved (2026-02-07)
- [x] **Phase 3: Task system** — /capture, /focus, /done, /standup commands; SessionStart accountability hook; memory integration updates; FOCUS.md populated (2026-02-08)
- [x] **Dedup cleanup** — removed 2 duplicate memories from JSONL (3 copies of infrastructure/time-management decision → 1) (2026-02-08)
- [x] **focus_limit bump to 3** — SYSTEM.md, FOCUS.md, /focus command spec, accountability hook, and CLAUDE.md all updated. Hook reads limit dynamically from SYSTEM.md. (2026-02-08)
- [x] **/recall spec polish** — no-argument stats display and zero-match guidance added to recall.md (2026-02-08)
- [x] **Phase 2: PostgreSQL query layer** — native install, schema, sync/decay/rebuild scripts, 24 unit tests (2026-02-08)
- [x] **Project-specific memory loading** — extraction-hook.py tags memories with project identifier from transcript path; session-start-retrieval.py derives project from cwd and boosts same-project memories (35 slots) over other-project (15 slots) with overflow when one bucket is underutilised; /remember command updated with project field; schema.sql, sync-to-postgres.py updated with project column; live database migrated (2026-02-08)
- [x] **Phase 4: Reviews and integrations** — /review (weekly review + collaborator reports), /retro (monthly system retrospective), /sync-board (GitHub Issues sync), /process-email (email triage with manual fallback); tasks/collaborators.md created; extraction-hook.py updated with COMMAND_MARKERS for all 4 new commands; .gitignore updated (2026-02-08)
