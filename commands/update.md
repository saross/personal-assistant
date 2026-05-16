# /update — Revise the content of an existing memory

Replace the `content` of a memory while preserving the audit trail.
The prior content moves to `revisions[]` with a timestamp and optional
reason. Use when a memory was correctly *captured* but the underlying
claim has been refined or partially corrected. Pair with `/forget`
when the right move is retirement rather than revision.

## Usage

```text
/update [id] [new content]
/update [id] reason:"[why this revision]" [new content]
```

## Arguments

- `[id]` — Memory ID to revise (required). Same format as `/forget`:
  `YYYY-MM-DD-<hash>`.
- `reason:"..."` — Optional reason for the revision (quoted to allow
  spaces). Recorded in `revisions[]` alongside the prior content.
- `[new content]` — The replacement content (required). Multi-word; the
  parser takes everything after the recognised prefixes.

## Behaviour

1. **Locate the memory** by `id` in
   `~/personal-assistant/memories/memories.jsonl`. Preserve all other
   fields (category, tags, project, etc.).
2. **If the new content is identical to the existing content** (after
   whitespace normalisation): report "no change" and stop.
3. **Construct the updated record:**
   - Move the current `content` to a new entry in `revisions[]`:
     `{"revised_at": "<ISO now>", "action": "update",
       "prior_content": "<old content>", "reason": "<reason if provided>"}`
   - Replace `content` with the new value
   - Clear `verified` (reset to `null`) — anchors may no longer match
     the revised claim; Phase 2's verification pipeline will re-evaluate
   - Clear `anchors` (reset to `[]`) — same reasoning; new anchors
     should be supplied via a follow-up edit if needed, or left for
     Phase 2 extraction to populate.
4. **Atomic line rewrite** (same pattern as `/forget`): tmp file +
   `os.replace`, with `LOCK_EX` flock to serialise against the append
   path.
5. **Confirm to the user:**

   ```text
   Updated: [id]
     Category: [category]
     Was: "[prior content truncated ~120 chars]"
     Now: "[new content truncated ~120 chars]"
     Reason: [reason if provided, else "no reason given"]
     Verified flag cleared (anchors will be re-evaluated by Phase 2 sweep).
   ```

6. **PostgreSQL sync is automatic** — next sync-to-postgres tick picks
   up the JSONB change.

## Autonomous use (Claude self-invocation)

Same L1 memory-correction pattern as `/forget`. When Claude detects a
recalled memory has a content-level error (claim slightly wrong, but
the core observation is still useful), invoke `/update` with the
correction. Announcement format:

```text
Marking memory [id] as updated: [reason]
```

The extraction hook's COMMAND_MARKERS (Phase 3 extension) skips this
turn so the correction isn't re-extracted as a fresh memory.

## What `/update` does NOT do

- It does not modify `category`, `id`, `created_at`, `session_id`, or
  `project`. Those are stable identity fields. To re-categorise a
  memory, `/forget` it and `/remember` a fresh entry with the right
  category.
- It does not add `links` or change `superseded_by`. Those are managed
  by Phase 4 (typed links) and Phase 2 verification.
- It does not edit `revisions[]` — that's append-only.

## Examples

```text
/update 2026-05-16-d973d7ee5009 reason:"cross-machine investigation showed 92% of transcripts are present" The earlier "422 transcripts lost" claim was wrong; transcripts are split across amd-tower and zbook, only ~40 are truly missing.

/update 2026-04-22-abcdef123456 The original count was 1,383 sub-agent transcripts; current is 1,639.
```

## Implementation notes

- Atomic write + flock as in `/forget`.
- `_timestamps.now_iso()` for the timestamp.
- The `prior_content` field in revisions preserves the entire previous
  string — do not truncate. The audit trail needs to be complete.
- `verified` reset is deliberate: a verified memory whose claim is
  revised becomes "unknown again" until the verification pipeline
  re-checks. Better than silently inheriting a stale "verified: true".
