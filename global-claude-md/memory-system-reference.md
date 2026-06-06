## Memory System — Full Reference

Memories are automatically extracted from sessions via hooks and stored
in `~/personal-assistant/memories/memories.jsonl`.

### Categories

**Research (permanent):** methodology, ethics, provenance, hypothesis,
limitation, openness, source_insight

**LLM Research (permanent):** error_mode, surprise, self_reflection,
prompt_effectiveness

**Project (mixed):** decision (permanent), architecture (permanent),
pattern (180d), gotcha (180d)

**GTD:** commitment (30d after deadline), waiting_for (14d), contact
(permanent)

**Transient:** progress (30d), context (30d)

**Retrospective (assigned during review, not extraction):** slip
(permanent), completion (90d), blocker_real (30d), blocker_excuse
(permanent)

**System Adaptation:** system_evolution (permanent), system_friction
(60d), system_success (90d)

### Tag Guidelines

- Use lowercase with hyphens: `gps-accuracy`, `field-method`,
  `fair-principle`
- Singular forms preferred (consolidate plurals via `/tags` monthly gardening)
- See `~/personal-assistant/memories/tag-vocabulary.txt` for seed
  vocabulary
- `/tags` command runs `scripts/tag-gardening.py` — detects plural pairs,
  Levenshtein near-duplicates, and prefix relationships. Merge plans are
  reviewed interactively then applied atomically to the canonical JSONL.

## v2 Schema (2026-05-16)

Each memory record may carry these additional fields. They are
optional on `/remember` captures and populated by the extraction hook
when present in the transcript.

- `anchors` — array of `{type, ref, line?}` for re-verifying claims.
  Types: `file`, `commit`, `zotero`, `url`. Required (in spirit) for
  the **anchor-required categories**: `decision`, `progress`,
  `architecture`, `gotcha`, `provenance`, `completion`. A memory in
  these categories without an anchor will be bound to `confidence: low`
  by the binding rubric. Anchors must be **transcript-verbatim** —
  never invented or paraphrased.
- `verified` — `true` / `false` / `pending` / `stale` / `tier3` /
  `null`. Set by `scripts/anchor_verify.py` after each write. Pre-v2
  memories carry `null`.
- `links` — array of `{relation, target_id}` typed links to other
  memories. Relations: `revises`, `supersedes`, `supports`,
  `contradicts`, `refines`, `depends-on`. Populated by Phase 4
  gardening; not by write-time hooks.
- `why` / `how_to_apply` — free text for **guidance-bearing
  categories**: `feedback`, `decision`, `gotcha`, `methodology`,
  `pattern`, `error_mode`. The `why` (reason behind the rule) and
  `how_to_apply` (when/where it kicks in) survive content drift; the
  binding rubric only awards `confidence: high` to guidance memories
  that have both populated.
- `superseded_by` — memory id of the entry that replaces this one.
  Set by `/forget`, `/update`, or Phase 4 cross-session supersession.
- `revisions` — append-only audit trail of `/update` operations.
- `is_active` — soft-delete flag. `/forget` sets to `false`; recall
  filters by `is_active = true` via the `active_memories` view.
  P8 (2026-06-06): `/forget` and `/update` now call
  `scripts/sync_memory_edit.py` as a mandatory step to propagate
  the change to PostgreSQL immediately (previously edits were silently
  lost until a manual `rebuild-postgres`).

## Autonomous capture (memory-system v2, Phase 3)

Per the v2 self-driving tenet, Claude may write to the memory store
without an explicit user `/remember`, `/forget`, or `/update`. Each
autonomous write **must** begin with a heading-marker line so the
extraction hook can skip the announcement and avoid re-extraction.

Triggers (default — be conservative; ~1–3 autonomous saves per
session is the right ballpark, not 10):

- User articulates a **durable preference or constraint** ("always…",
  "never…", "I want…", "don't…")
- A **non-obvious decision** is made with rationale that future sessions
  would want context for
- An **approach succeeds or fails** in an instructive way (record the
  approach + why, not just the outcome)
- An **error mode** emerges with a correction (record the correction,
  not the pre-correction claim — matches the extraction hook's
  self-correction handling)

### Announce formats (exact strings)

| Action | First line of the assistant turn |
|---|---|
| Save | `# Saved to memory: [category] — [summary]` |
| Forget | `# Forgot memory: [id] — [reason]` |
| Update | `# Updated memory: [id] — [reason]` |

The leading `# ` (markdown H1) plus the specific phrase forms a
[`COMMAND_MARKERS`](../scripts/_command_markers.py) entry. The
extraction hook treats any assistant turn containing one of these
markers as a write-side announcement and excludes it from extraction.

### What autonomous capture is *not*

- It is **not** a license to save commentary, observations, or
  reflections that wouldn't survive a "would I want a future Claude
  to read this?" test. Use `/track`-style ephemera or session
  summaries for those; autonomous save is for durable knowledge.
- It is **not** a replacement for `/remember`. The user-invoked path
  remains the primary write surface. Autonomous capture handles the
  cases where the user has signalled durable intent but hasn't typed
  the command.
- It is **not** asynchronous — write immediately when the trigger
  fires, in the same turn as the announcement, so subsequent recall
  can find the entry.

## Memory-correction layers (v2)

Three layers for fixing memories that turn out to be wrong:

- **L1 — explicit commands** (`/forget`, `/update`): in Phase 1.
  User-invoked or autonomous (with the announce-markers above).
- **L2 — extraction-time self-correction**: in Phase 2. The
  `EXTRACTION_PROMPT` instructs Haiku to extract only the corrected
  version when the transcript contains a revision; the pre-correction
  claim never enters the corpus.
- **L3 — cross-session supersession** via typed links: in Phase 4.
  Gardening pass detects semantically-overlapping memory pairs where
  one contradicts the other; auto-applies `supersedes` / `contradicts`
  links and sets `superseded_by`. Pending Phase 4.
