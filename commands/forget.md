# /forget — Soft-delete a memory

Mark a memory as inactive without losing the record. The entry remains
in `memories.jsonl` and in PostgreSQL for audit purposes, but is hidden
from recall by default. Pair with `/update` (revise content) when you
want to correct rather than retire.

## Usage

```text
/forget [id]
/forget [id] [reason]
```

## Arguments

- `[id]` — Memory ID to mark inactive (required). Format:
  `YYYY-MM-DD-<hash>` (12-char hex suffix). Get IDs from `/recall`.
- `[reason]` — Optional free-text reason (any words after the ID).
  Stored in the `revisions` array with a timestamp for audit.

## Behaviour

1. **Locate the memory** in `~/personal-assistant/memories/memories.jsonl`
   by exact `id` match. Read the line; preserve all existing fields.
2. **If `is_active` is already `false`**: report "already inactive" and
   stop — do not double-stamp the revisions array.
3. **Construct the updated record:**
   - Set `is_active: false`
   - Append a new entry to `revisions[]`:
     `{"revised_at": "<ISO timestamp now>", "action": "forget", "reason": "<reason>"}`
     (omit the `reason` key if no reason supplied)
4. **Rewrite the JSONL line in place** using the same atomic-rewrite
   pattern as `scripts/_bulk_rewrite_guard.py`. Concretely: write a temp
   file with the line replaced, then `os.rename` atomically over the
   original. Hold an exclusive flock on the file during the rewrite to
   serialise against the append-side hook.
5. **Confirm to the user:**

   ```text
   Forgotten: [id]
     Category: [category]
     Was: "[content truncated to ~120 chars]"
     Reason: [reason if provided, else "no reason given"]
   ```

6. **Reconcile PostgreSQL in lockstep (mandatory):**

   ```bash
   python3 ~/personal-assistant/scripts/sync_memory_edit.py --id [id]
   ```

   This is **required**, not optional. `sync-to-postgres.py` is
   INSERT-only (`ON CONFLICT (id) DO NOTHING`), so it does **not**
   propagate an `is_active` flip to a row already in PostgreSQL. The
   PG-reading recall paths — the session-start digest and the autonomous
   `fetch-memories.py` depth-fetch, both via the `active_memories` view
   (`WHERE is_active = TRUE`) — would otherwise keep surfacing the
   forgotten memory until a manual `rebuild-postgres`. The helper issues a
   surgical `UPDATE` so the forget takes effect immediately. It is
   best-effort about the connection: if PostgreSQL is unreachable it prints
   a clear WARNING and exits non-zero (run `rebuild-postgres` later). Note:
   PostgreSQL currently runs only on amd-tower; on a machine without it the
   helper prints a no-op notice, and that machine's recall reads the
   git-synced JSONL directly, so the JSONL edit alone suffices there.

## Autonomous use (Claude self-invocation)

Per the v2 design's L1 memory-correction layer and the self-driving
tenet, Claude may invoke `/forget` autonomously without the user
typing it — for example when a recall surfaces a memory whose specifics
contradict the current session's verified facts. The announcement
format **must** be:

```text
# Forgot memory: [id] — [reason]
```

The leading `# ` plus the literal `Forgot memory:` phrase is a
`COMMAND_MARKERS` entry (see `scripts/_command_markers.py`) so the
extraction hook skips the announcement turn, preventing the autonomous
forget from being re-extracted as a "Claude forgot X" observation.

Then execute the same procedure above.

## Reversal

`/forget` is reversible until decay erases the record. To un-forget:

- Manual: locate the line in `memories.jsonl`, set `is_active` back to
  `true`, append a `{action: "restore"}` entry to `revisions[]`.
- A dedicated `/restore [id]` command can be added if this becomes
  common; not in Phase 1 scope.

## Examples

```text
/forget 2026-05-16-d973d7ee5009 superseded by cross-machine investigation

/forget 2026-04-22-abcdef123456
```

## What `/forget` does NOT do

- It does not edit `content`. Use `/update` for content corrections.
- It does not delete from disk. Hard-delete would break audit trails and
  conflict with the soft-delete decay model already in place.
- It does not propagate to other machines immediately. Sync happens at
  the next daily-sync tick (commit + push + pull on the other machines).

## Implementation notes

- Atomic write pattern: `tmp = path.with_suffix(".tmp")`, write all
  lines, `os.replace(tmp, path)`. Hold `fcntl.flock(LOCK_EX)` on the
  original file's directory during the operation.
- The line-edit approach (find + replace one line) is simpler than a
  full file rewrite. Use a line-iteration with conditional write to
  the temp file.
- All ISO timestamps use `_timestamps.now_iso()` from
  `scripts/_timestamps.py` to match the format used elsewhere.
