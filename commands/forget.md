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

6. **PostgreSQL sync is automatic** — the next `sync-to-postgres.py`
   tick (every 5 min via cron) picks up the change. Recall via
   `active_memories` view filters by `is_active = TRUE` so the
   forgotten entry disappears from results.

## Autonomous use (Claude self-invocation)

Per the v2 design's L1 memory-correction layer and the self-driving
tenet, Claude may invoke `/forget` autonomously without the user
typing it — for example when a recall surfaces a memory whose specifics
contradict the current session's verified facts. Use the announcement
format so the extraction hook can skip the announcement turn (avoiding
double-extraction of the correction):

```text
Marking memory [id] as forgotten: [reason]
```

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
