# Round 4f-6 report (memory readers and anchors, follow-ups after PR #145)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4f-6 complete. Three commits on `claude/audit-round4f-6`, working tree clean, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **M-a** `degraded` on any exclusion | **fixed** — `unusable` stays the fact, `degraded` becomes the judgement: true only when exclusions coincide with a pending rate over `MAX_PENDING_PCT`. A shared `pending_pct` helper computes the rate for the row and for the message that explains it. Both cells tested (`test_an_exclusion_with_a_low_pending_rate_is_an_ordinary_row`, `..._is_degraded`), plus the unchanged unexplained-rate cell |
| **M-b** floor starved by degraded rows | **fixed** — the skip is gone; `repos` is the discovery-only count and independent of consultability. `test_a_degraded_row_still_carries_its_discovery_count` (three consecutive degraded rows at `repos: 10`) |
| **M-c** `probe_repos` untested | **fixed** — `TestProbeRepos`, one case per branch, each asserting **both** the returned subset and the registry, so the return value is no longer free |
| **M-d** tier-C probe unpinned | **fixed** — `test_tier_c_probes_every_repository_before_resolving`: 20 anchors resolving in the first repository, emptied mount second, `[F]` must still name it |
| **L-a** `9B2FJ6SL` | **fixed** — replaced in `tests/test_sync_to_zotero.py`. Also present in `scripts/style-analyser/validate_passive_detection.py:89` and `efficacy_build_judge_tasks.py:92` as operational configuration naming the operator's reference papers — noted, not touched (another round's tooling) |
| **L-b** minimum was first-run-only | **fixed** — the recorded count is used only when it clears `MIN_DISCOVERED_REPOS`; a lower recorded count WARNs, naming it and how to accept it. `test_a_recorded_count_below_the_minimum_does_not_become_the_floor` |
| **L-c** `[H]` marker and wording | **fixed** — the headline carries the marker, the legend is conditional, and it now says what the sweep actually does (no alert on a degraded run) rather than "the floor skips them", which after M-b would have been false. Single-degraded-run case tested |
| **L-d** alert on a deflated rate | **fixed** — the threshold comparison is skipped for a degraded row with a NOTE; clean runs still alert |
| **L-e** nested emptied directory | **implemented, not just noted** — the probe now asks `--show-toplevel` and compares the answer with the path it asked about; a mismatch is an exclusion reading "not a repository root (git answered for a parent)". Genuine nested checkouts are kept. Two tests |

Mutations killed (all verified failing): `"degraded": bool(unusable)`; reinstating the degraded skip in `last_repo_count`; making the minimum first-run-only; dropping the degraded early return before the alert; appending on a permanent error; excluding on a timeout; excluding on a transient `OSError`; deleting the `repo_is_unusable` pre-skip; `return []`; dropping the toplevel comparison; dropping the tier-C `probe_repos` call; dropping the headline marker; restoring the old legend wording.

## Suite

Clean `git archive HEAD` copy in `mktemp -d`, `HOME` pinned inside it, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`:

`4438 passed, 3 skipped, 19 deselected, 34 subtests passed in 166.41s (0:02:46)` — exit code **0**.

The store half of the hermeticity guard was inert again, and now says so explicitly: an archive export carries no `data/` submodule, so those watched paths dangle. Only the source-tree half was enforced.

```text
5ea690c fix(memory-health): mark the degraded run the reader can actually see
5360da1 fix(drift-sweep): degrade on the numbers, not on any exclusion
bc7e1f0 fix(anchors): test probe_repos, and make it answer for the right repo
```

## Live-behaviour risks

1. **`degraded` will be rarer than after 4f-5, and that is the point** — but it means a row can now carry a populated `unusable` list with `degraded: false`. Any reader that treated a non-empty `unusable` as "ignore this row" must switch to the flag.
2. **The alert threshold no longer fires on a degraded run.** If a genuine drift spike coincides with an absent mount, the sweep exits 0 and says so in a NOTE rather than alerting. The spike is still visible in `[H]`, marked.
3. **L-e tightens what counts as a repository.** A discovered path that is no longer its own repository root — an emptied directory nested inside another checkout, or a subdirectory that found its way into discovery — is now excluded rather than silently answering for its parent. On this machine I expect none; if `~/Code` holds such a directory it will appear in `[F]`/`[H]` on the next run, which is the intended surfacing but will look like a new fault.
4. **The floor is now `max(recorded, 3)` unless `--min-repos` is passed for that run.** A machine that legitimately has fewer than three repositories must pass the flag every time, not once.
5. Unchanged from earlier rounds: an excluded repository's own anchors read pending, not false; short commit refs read pending; `audit-postgres-sync` and `/memory-health` fail on a PostgreSQL-only row; the trend log's schema keeps growing (`consulted`, `degraded`, `unusable`), so any external parser must ignore unknown keys.
