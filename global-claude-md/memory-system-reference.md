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
