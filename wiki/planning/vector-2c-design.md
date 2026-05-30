# Vector 2c — focus-aware + project-scoped digest selection

**Status:** implemented + tested, shipped **DARK** 2026-05-30 (flag default
OFF; sentinel `~/.pa-digest-focus` NOT created). Enable on amd-tower **after**
the Vector 2 §8 review (2026-06-13), or accept the §8 confound explicitly.

**Relationship to the parent design:** this operationalises the direction of
the 2026-05-30 Stage 2 reframe in `vector-2-design.md` §6b
("anchored-and-verified-first among records that *have* anchors,
recent-promoted otherwise"). Vector 2c adds the *relevance* dimension the
parent left as soft tag-overlap: it makes the verified bucket focus-aware and
optionally hard-scoped to the active project.

## 1. Problem

The Vector 2 digest (live on amd-tower) ranks the verified-true bucket by
tag-overlap-then-recency. In a project repo that is soft (no hard scope — a
foreign-project memory can still surface). In the personal-assistant hub the
hook nulls `current_project` for cross-project visibility, which makes
`collect_project_tags` return the *whole-corpus* tag set, so `overlap_score`
degenerates to "how many tags does this memory carry" and the ranking
collapses to roughly (tag-count, recency). Result, observed 2026-05-30: of the
4 verified entries surfaced in a PA-hub session, **1 was relevant** to the
session's actual work; the other 3 were the week's most heavily-tagged
research memories, surfaced incidentally.

## 2. Decision (Option 3, coarse)

Two changes to the digest's verified-entry selection, behind **one**
machine-local flag (`PA_DIGEST_FOCUS` / `~/.pa-digest-focus`), default OFF:

1. **Focus-aware ranking.** The active `FOCUS.md` slot projects become the
   primary ranking key. A memory touching a current focus slot outranks an
   equally-recent off-focus one. (Option 3 = ranking + a thin one-line
   legibility label, *not* a redundant focus block — the `# Task Status`
   hook already prints the slots.)
2. **Hard project scope.** In a project repo the verified and fallback pools
   are filtered to that project (`matches_project`, mirroring the hook's
   `is_same_project`: exact encoded-id match, legacy no-project records pass).
   The PA hub is exempt — `current_project` is already nulled there, so scope
   is `None` and the cross-project focus ranking does the prioritisation.

**Coarse by design** (per the chosen "start coarse, go finer only if too
blunt"): the focus key is the *last path segment* of each slot's
`- **Project:**` line — `research/inscriptions` → `inscriptions`,
`business/efn` → `efn` — matched as a substring against the memory's encoded
`project` and its tags. This bridges the logical focus label to both the
encoded cwd project (`-home-shawn-Code-inscriptions`) and differently-named
sibling repos (`efn` matches `…-Groundsite-EFN-Planning`). Keywords <3 chars
are ignored to avoid pathological substring hits.

**Empirical validation (2026-05-30, `data/memories/memories.jsonl`):** of 377
verified-true active in-window memories, the live focus keywords
`{inscriptions, efn}` match **127 (34 %)** — 76 from the inscriptions repo, 45
from `Groundsite-EFN-Planning` via the `efn` substring — confirming the coarse
match selects the right pool.

## 3. Ranking key (and the flag-OFF guarantee)

`_rank_key` has two regimes, chosen by whether focus mode is on:

- **Focus mode (keywords non-empty):** `(focus_score, recency)`. The
  tag-overlap term is *dropped* — in the hub it is degenerate noise (see §1)
  that biases toward the most verbose project and crowds out the other focus
  slots. Recency as the secondary gives balanced, intent-faithful ordering.
- **Flag-OFF (keywords empty):** `(overlap_score, recency)` — byte-for-byte
  the pre-2c key.

Both branches yield same-shape `(int, datetime)` tuples within any one sort
call, so they are comparable. Because the OFF branch is identical to the
original key and all new `build_digest` parameters default to the pre-2c
values, **flag-OFF output is byte-identical** to today's digest — the
condition that keeps the live §8 window unconfounded while 2c sits dark.

## 4. Known limitation — slot balance

Focus-relevant entries are ranked by pure recency, so the focus slot with the
most *recent verified-memory activity* dominates the budget. Observed
2026-05-30: the digest skews entirely to inscriptions (Slot 1, the active
task) because EFN's recent work (Slots 2–3) was meetings/planning, not
verified-true extractions. This is faithful, not a bug — but a user expecting
all slots represented may be surprised.

**Deferred refinement (future lever, not v1):** per-slot round-robin — reserve
≥1 budget slot per active focus keyword before filling the rest by recency.
Revisit only if the recency default proves too single-project after the 2c
observation window.

## 5. Observability

`digest_log_line` gains two trailing fields, `focus=<bool>` and
`scoped=<bool>` (appended last, so positional parsers of the earlier fields
are unaffected). After enable, `data/logs/digest.log` shows whether each
firing ran focus-aware and/or scoped.

## 6. Files

- `scripts/digest.py` — `matches_project`, `focus_score`, `_rank_key`
  (two-regime), `rank_verified`/`rank_fallback` (`project_id`,
  `focus_keywords`), `_assemble`/`build_digest` (`focus_label`),
  `DigestResult` (`focus_active`, `scoped`), `digest_log_line`.
- `hooks/session-start-retrieval.py` — `FOCUS_FLAG_ENV`/`FOCUS_SENTINEL`/
  `FOCUS_FILE`, `focus_digest_enabled()`, `load_focus_profile()`,
  `build_session_digest` (2c args), `main()` wiring.
- `tests/test_digest.py`, `tests/test_retrieval_hook.py` — +37 tests.

## 7. Rollback / enable

Enable: `touch ~/.pa-digest-focus` (or `PA_DIGEST_FOCUS=1`). Roll back:
`rm ~/.pa-digest-focus` (or `PA_DIGEST_FOCUS=0`). Machine-local; never in the
synced `data/` submodule, so amd-tower enablement does not leak to
zbook / rpi-server.
