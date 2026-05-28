# Plan: First Real Tag Gardening Run

**Status:** Deferred (not yet started)
**Created:** 2026-04-12
**Estimated effort:** 30–60 minutes (interactive)
**Trigger to implement:** When you have a focused half-hour for vocabulary
hygiene, OR when search noise from near-duplicate tags becomes annoying

## Context

The `/tags` command was built and audited on 2026-04-12 but has never been
run for real consolidation. Current state of the vocabulary (per the most
recent `tag-gardening.py stats`):

- **11,173 unique tags** across 23,336 memories
- **5,032 singletons** (45.0%) — used exactly once
- **196 plural pairs** detected (high confidence)
- **1,001 near-duplicates** (medium confidence, Levenshtein-based)
- **4,104 prefix relationships** (low confidence)

The infrastructure is built and tested (36 unit tests) but the actual
vocabulary cleanup hasn't happened. This plan is the first real run.

## Goal

Reduce the active tag vocabulary by:

- Merging all 196 plural pairs (singular form wins) — bulk approve
- Reviewing and merging high-value near-duplicates — selective approve
- Optionally cleaning vocabulary orphans (9 currently)

Target: vocabulary count reduction of 200–400 tags, no change to memory
content. Singletons stay as-is — they're not noise per se, just rarely
reused.

## Workflow

This is an **interactive** session, not a batch script. The `/tags`
command guides the user through three phases:

### Phase 1: Plural pairs (high confidence, bulk approve)

```text
/tags
```

The command runs `tag-gardening.py stats`, then `similar --top 30`. The
196 plural pairs appear first because they're high-confidence.

Sample output:

```text
196 plural pairs detected. Top 20 by combined usage:

| Singular        | Count | Plural          | Count |
|-----------------|-------|-----------------|-------|
| fair-principle  | 180   | fair-principles | 2     |
| ensemble-method | 28    | ensemble-methods| 92    |
| field-method    | 106   | field-methods   | 2     |
| field-type      | 16    | field-types     | 70    |
| error-mode      | 78    | error-modes     | 4     |
| ...
```

User decision: **approve all 196**, OR review individually for any
surprises. Recommend approve-all on the first run — the rule (singular
wins) is unambiguous and the test fixtures have already exercised the
exclusion list.

### Phase 2: Near-duplicates (medium confidence, selective)

The command then shows the top 30 near-duplicates by combined usage. Some
will be obvious merges (`experiment-design` / `experimental-design`), others
will be tags that are similar but mean different things. The user reviews
in batches of 10.

**Decision rules to apply during review:**

- If both forms are in the same domain and one is clearly the standard
  form: merge
- If the difference is a meaningful distinction (e.g., `prompt-effectiveness`
  vs. `prompt-efficacy`): keep both
- If one is a typo (`api-kye` vs. `api-key`): merge
- If unsure: skip — better to leave a near-duplicate than collapse a real
  distinction

Estimated approval rate: 30–50% of medium-confidence candidates.

### Phase 3: Prefix relationships (low confidence, mostly skip)

4,104 prefix pairs is too many to review. Most are legitimate
generalisations (`documentation` vs. `documentation-architecture`) that
should NOT be merged. Skip this phase on the first run; revisit if a
specific prefix family becomes a known nuisance.

### Phase 4: Apply the merge plan

Once approvals are gathered, the command builds a JSON merge plan and
shows a dry-run summary:

```text
Merge plan: 220 tags to retire → 200 winners
  Memories affected: ~3,400
  Tag replacements: ~3,500
```

User confirms, the merge runs against `memories.jsonl` (atomic rewrite),
then triggers a PostgreSQL rebuild.

### Phase 5: Verify and capture as system_evolution memory

Re-run `tag-gardening.py stats`:

- Before: 11,173 tags
- After: ~10,950 tags (estimated)
- Singletons: minimal change

Capture a `system_evolution` memory via `/remember`:

```text
/remember category:system_evolution Tag gardening 2026-04-12: merged 220
tags (196 plural pairs, ~24 near-duplicates). Vocabulary reduced from
11,173 to 10,950. First real run of /tags command since it was built.
```

## Pre-flight Checks

1. **Backup the JSONL**: `cp data/memories/memories.jsonl
   data/memories/memories.jsonl.pre-gardening-2026-04-12`
2. **Confirm no extraction in progress**: stop any running session that
   might be appending to memories.jsonl. The merge does a JSONL rewrite;
   concurrent appends would be lost.
3. **Confirm PostgreSQL is reachable** (`tag-gardening.py stats` exits
   without error)
4. **Verify the tag-gardening tests still pass** (`pytest
   tests/test_tag_gardening.py`)

## Verification

1. **Diff the JSONL before/after**: line count unchanged, modified records
   have new tags
2. **Spot-check 5 modified memories**: verify the merge replaced loser
   tags with winners and deduplicated correctly
3. **PostgreSQL state**: `psql claude_memories -c "SELECT tag, COUNT(*)
   FROM memories, UNNEST(research_tags) AS tag WHERE tag = 'pipelines'
   GROUP BY tag;"` should return 0 for any merged loser tag
4. **Vocabulary file**: confirm losers removed, winners present, sorted

## Rollback

If something goes wrong:

```bash
cp data/memories/memories.jsonl.pre-gardening-2026-04-12 data/memories/memories.jsonl
venv/bin/python3 scripts/rebuild-postgres.py
```

The backup makes this trivial. The merge operation is reversible by
restoring the backup, since the JSONL is the canonical source.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Wrong merge collapses a real distinction | Manual review for medium-confidence merges; backup for rollback |
| Concurrent extraction during merge | Stop sessions before running; document in pre-flight |
| PostgreSQL drift after merge | Trigger rebuild after merge, not just incremental sync |
| Vocabulary file out of sync with JSONL | tag-gardening.py rewrites both atomically |

## Out of Scope

- Singleton cleanup (5,032 tags) — not noise, just rarely reused. Skip.
- Cross-project tag namespace separation — different concern, not this run
- Automatic merging via cron — risky without human review
- Tag taxonomy redesign — separate, larger project

## Why Defer

The infrastructure is built and tested but running it requires:

- 30–60 minutes of focused interactive review
- Mental load of judging 30+ near-duplicate candidates
- A backup workflow and rollback plan

None of this is hard but it's not a 10-minute task. Better done when the
user has uninterrupted time and isn't mid-research-session. The friction
from tag noise is currently low — search still works, retrieval is still
relevant. This is a maintenance task, not a blocker.
