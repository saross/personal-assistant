# /tags — Tag Gardening

Monthly review and consolidation of the memory tag vocabulary.

## Usage

```text
/tags              — Full gardening session (stats → duplicates → review → merge)
/tags stats        — Quick statistics only
/tags similar      — Show duplicate candidates only
/tags orphans      — Vocabulary hygiene only
```

## Behaviour

### Quick Modes

If the user provides a specific subcommand (`stats`, `similar`, `orphans`),
run only that subcommand and present results. Do not proceed to the full
gardening workflow.

### Full Gardening Session

When invoked with no arguments (bare `/tags`), run the complete workflow below.

#### 1. Gather Statistics

Run:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py stats
```

Parse the JSON output and present a summary:

```text
## Tag Vocabulary Statistics

Total memories: [N] | Unique tags: [N] | Tag usages: [N]

### Frequency Distribution
  Singletons (1 use):    [N] ([%])
  Low frequency (2-3):   [N]
  Medium (4-10):         [N]
  High (11+):            [N]

### Top 10 Tags
  [tag]: [count]
  ...
```

#### 2. Find Duplicates

Run:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py similar --top 30 --format json
```

Parse the JSON output. Note the counts:
- `plural_count` — plural/singular pairs (high confidence)
- `similar_count` — Levenshtein near-duplicates (medium confidence)
- `prefix_count` — prefix relationships (low confidence)

#### 3. Present Plural Pairs (High Confidence)

Present plural pairs as a batch. These are safe to merge wholesale
(singular form always wins per folksonomy rules).

```text
## Plural Pairs ([N] found)

These can be merged in bulk — singular form wins.

| Singular | Count | Plural | Count |
|----------|-------|--------|-------|
| pipeline | 42    | pipelines | 8  |
| ...      |       |           |    |

Approve all [N] plural merges? (y/n/review individually)
```

If the user approves all, add all plural pairs to the merge plan.
If they want to review individually, present in batches of 10.

#### 4. Present Near-Duplicates (Medium Confidence)

Present Levenshtein near-duplicates in batches of 5-10.
These need human judgement — the suggested winner may be wrong.

```text
## Near-Duplicates (batch 1 of [N])

| Tag A       | Count | Tag B       | Count | Similarity | Suggested |
|-------------|-------|-------------|-------|------------|-----------|
| api-key     | 15    | api-keys    | 3     | 93%        | api-key   |
| ...         |       |             |       |            |           |

For each: approve (a), skip (s), or swap winner (w)?
Or: approve all in this batch (A), skip all (S)
```

#### 5. Present Prefix Pairs (Low Confidence — Optional)

Only present if the user wants to review them. These are informational.

```text
I found [N] prefix relationships (e.g., "api" vs "api-integration").
These are low confidence — want to review them? (y/n)
```

#### 6. Build and Execute Merge Plan

Accumulate all approved merges into a JSON plan.
Write to `/tmp/tag-merge-plan-YYYY-MM-DD.json`.

Run dry run first:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py merge \
    --plan /tmp/tag-merge-plan-YYYY-MM-DD.json --dry-run
```

Present the dry-run summary (memories affected, tags retired).
Ask for confirmation.

If confirmed, execute:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py merge \
    --plan /tmp/tag-merge-plan-YYYY-MM-DD.json
```

#### 7. Vocabulary Hygiene

Run orphan check:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py orphans --action list
```

If orphaned or missing tags found, ask user whether to clean them:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py orphans --action clean
```

#### 8. Final Statistics

Re-run stats to show improvement:

```bash
python3 ~/personal-assistant/scripts/tag-gardening.py stats
```

Present before/after comparison.

#### 9. Record

Capture a system_evolution memory summarising the gardening session:

```text
[Month] [Year] tag gardening: merged [N] tags ([N] plurals, [N] near-duplicates).
Vocabulary reduced from [before] to [after] unique tags.
```

## Notes

- The merge plan JSON format is:
  ```json
  [{"winner": "tag-a", "losers": ["tag-b", "tag-c"], "affected_memory_count": N}]
  ```
- After merging, PostgreSQL will be stale. The 5-minute cron only handles
  new appends — modified records need a full rebuild:
  ```bash
  python3 ~/personal-assistant/scripts/sync-to-postgres.py --full
  ```
  If `--full` is not supported, drop and re-sync:
  ```bash
  psql -d claude_memories -c "DELETE FROM memories;" && \
  python3 ~/personal-assistant/scripts/sync-to-postgres.py
  ```
- Run `/tags` when no other sessions are actively extracting memories.
  The merge does an atomic rename of the JSONL file; any memories
  appended between the read and rename would be lost.
