# Plan: MCP Memory Server V2 — Write Tools

**Status:** Deferred (not yet started)
**Created:** 2026-04-12
**Estimated effort:** 1 day
**Trigger to implement:** A concrete need to capture memories from a Claude
instance other than Claude Code (e.g., Cowork autonomous tasks producing
research insights worth keeping)

## Context

The V1 MCP memory server (`scripts/memory_mcp.py`, completed 2026-04-12) is
read-only. It exposes 5 query tools but no way to add, update, or delete
memories. This is fine for the immediate use case (querying from Claude
Desktop / claude.ai) but creates an asymmetry: a Claude instance using the
read tools cannot remember anything new from its own work. Insights die
with the session.

V2 adds write capability so any Claude instance with MCP access can
contribute to the memory database with the same normalisation, validation,
and tagging behaviour as the existing extraction hook.

This plan was deliberately deferred from V1 because write tools require
duplicating logic from `extraction-hook.py` (tag normalisation, vocabulary
updates, ID generation, schema validation). That duplication is non-trivial
and was the main reason for shipping V1 read-only.

## Goal

Add three write tools to `memory_mcp.py`:

1. `store_memory` — create a new memory with full validation
2. `update_memory` — modify an existing memory by ID (limited fields)
3. `delete_memory` — soft-delete (mark `is_active = false`)

All writes go to the **canonical JSONL first**, then propagate to
PostgreSQL via the existing 5-min sync cron (or trigger an immediate sync
if the latency matters).

## Tool Surface

### `store_memory`

```python
@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
))
async def store_memory(
    content: str,         # Required, ≥10 chars
    category: str,        # Required, must be in valid category set
    tags: list[str],      # Required, ≥1 tag, normalised
    confidence: str = "medium",   # high/medium/low
    source_context: str = "",
    zotero_key: str | None = None,    # Validated 8-char if present
    deadline_at: str | None = None,    # ISO datetime, only for commitment
) -> str:
```

**Validation rules:**

- `category` must match the existing 24-category vocabulary (from
  `category_config` in PostgreSQL or hardcoded list as fallback)
- `tags` are normalised through the same `normalise_tag` function used by
  the extraction hook (lowercase, hyphenated, deduplicated)
- New tags trigger an update to `tag-vocabulary.txt`
- `zotero_key`, if present, must match `^[A-Z0-9]{8}$`
- `deadline_at` is required when category is `commitment`

**ID generation:** `YYYY-MM-DD-<12-char hash>` matching the existing
extraction hook format.

**Side effects:**

1. Append to `memories/memories.jsonl` (canonical)
2. Update `tag-vocabulary.txt` if any new tags
3. Optionally trigger immediate sync to PostgreSQL (configurable)

**Source field:** Set `source = "mcp"` to distinguish from `extraction`,
`manual` (via /remember), and any future sources. This is important for
auditing — knowing which memories came from autonomous Cowork sessions vs.
intentional human capture is valuable.

### `update_memory`

```python
@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
))
async def update_memory(
    memory_id: str,
    content: str | None = None,
    tags: list[str] | None = None,
    confidence: str | None = None,
    zotero_key: str | None = None,
) -> str:
```

**Behaviour:** Replace specified fields, preserve all others. Memories are
append-only in the JSONL today, so update means rewrite-the-whole-file via
the same atomic-rename pattern used by `tag-gardening.py merge`.

**Constraint:** Cannot change `id`, `category`, `created_at`, or
`session_id`. These are identity-fixing; changing them would break
referential integrity with sessions.

### `delete_memory`

```python
@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
))
async def delete_memory(memory_id: str) -> str:
```

**Soft delete only.** Sets `is_active = false` and `decayed_at = now()`.
Never removes the line from JSONL — the audit trail is the whole point of
the canonical-JSONL design. The `active_memories` view automatically
excludes soft-deleted records, so subsequent searches won't return them.

**Why this is safe to expose:** soft delete is reversible by another
update. If a Cowork session deletes the wrong memory, the record is still
in the JSONL — just flipped back via `update_memory(id, is_active=true)`.
But that requires also exposing `is_active` as an updateable field. Or
better: a separate `restore_memory` tool that's the inverse of delete.

## Design Decisions

### 1. Schema validation: shared module or duplicate?

**Option A: Extract a shared module.** Move tag normalisation, ID
generation, and category validation into a new `scripts/memory_lib.py`
module that both `extraction-hook.py` and `memory_mcp.py` import.

- Pros: single source of truth, no drift
- Cons: refactor of working code (extraction hook is the most-used path
  in the system); risk of breaking the hook for marginal benefit

**Option B: Duplicate the logic.** Copy the relevant functions from
`extraction-hook.py` into a private module imported by `memory_mcp.py`.

- Pros: no risk to the extraction hook
- Cons: code drift over time, two places to update normalisation rules

**Recommended: Option A**, but as a careful refactor with strong tests
before touching the extraction hook. Run the existing extraction hook
tests against the refactored code; if they all pass, the refactor is safe.

### 2. JSONL append concurrency

Multiple Claude instances writing simultaneously could corrupt the JSONL.
Today, only the extraction hook writes, and it runs serially per session.
With write tools exposed via MCP, concurrent writes become possible (e.g.,
multiple Cowork tasks running in parallel).

**Solution: file locking via `fcntl.flock`** on append. The append is
atomic at the OS level for writes ≤4 KB on most filesystems, but locking
is safer for multi-line writes or future expansion.

The same lock pattern was needed for `tag-gardening.py merge` (where it
turned out unnecessary for the rename use case but is appropriate here).

### 3. Tag normalisation + vocabulary updates

The vocabulary file (`tag-vocabulary.txt`) is read by extraction prompts to
seed Haiku's tag suggestions. New tags from MCP write tools should be
added to it, but the file is currently rewritten in full by some scripts —
need to ensure append doesn't conflict with rewrite.

**Solution:** treat the vocabulary file the same way: lock + read + add +
write. This is rare (one new tag per memory at most) so performance doesn't
matter.

### 4. PostgreSQL propagation latency

After writing to JSONL, when does the new memory show up in queries from
other clients?

- **5-min sync cron**: lazy, fine for most use cases
- **Immediate sync**: write to JSONL, then call `sync-to-postgres.py` as a
  subprocess, then return
- **Direct PostgreSQL insert**: write to JSONL AND PostgreSQL in the same
  transaction (risk: if one succeeds and the other fails, divergence)

**Recommended: 5-min sync** as default, with an optional `immediate=True`
parameter on `store_memory` for cases where the caller needs the memory
queryable right away. The default mirrors the existing extraction hook's
laziness.

### 5. Authentication / authorisation

V1 has no auth (stdio is process-local). If V2 ships alongside the
rpi-server HTTP migration, the existing bearer-token auth covers writes
too. But there's a question of **per-tool permissions**: should the same
token grant both read and write, or should writes require a stronger
credential?

For a single-user system, same token is fine. For a multi-user system,
two tokens (read-only and read-write) makes sense.

**Recommended: single token for V1**, document upgrade path to two-token
in V3 if multi-user becomes a need.

## Implementation Sequence

1. **Refactor: extract `memory_lib.py`** (3–4 hours)
   - Move `normalise_tag`, `normalise_tags`, `update_vocabulary`,
     `generate_memory_id`, `validate_category` from extraction-hook.py
   - Update extraction-hook.py to import from the new module
   - Run all extraction hook tests; they must all pass unchanged
2. **Add `store_memory` tool** (2–3 hours)
   - Pydantic schema with all validation rules
   - Append to JSONL via locked write
   - Optional immediate-sync trigger
   - Tests with mocked filesystem
3. **Add `update_memory` tool** (2 hours)
   - Atomic rewrite of JSONL via tag-gardening's pattern
   - Tests
4. **Add `delete_memory` tool** (1 hour)
   - Soft delete only
   - Tests
5. **Run `/audit`** on all changes
6. **Update `infrastructure-reference.md`** with the new tools
7. **Live test** from a real client

## Verification

1. `/audit` over all changed code
2. All existing 401+ tests still pass (regression check after refactor)
3. New unit tests for each write tool
4. Live test: store a memory via MCP, verify it appears in `/recall`
5. Live test: update a memory, verify the change persists across PG sync
6. Live test: delete a memory, verify it disappears from active_memories
7. Concurrency test: two simultaneous writes don't corrupt the JSONL

## Out of Scope

- Hard delete (removing the JSONL line entirely) — never; the canonical
  log is append-only by design
- Bulk import (CSV, JSON file) — separate use case
- Multi-user permissions — V3+
- Memory versioning / edit history — would require schema changes

## Why Defer

V1 read-only ships value immediately. Write tools are speculative until
there's a concrete need to capture memories from a non-Code Claude
instance. The extraction-hook refactor is the highest-risk part of this
plan and benefits from being done deliberately, not under pressure.

Realistic trigger: the first time a Cowork autonomous research session
produces an insight worth keeping and there's no clean way to capture it
short of copying it back into a Claude Code session.
