# Round 4f-4 report (memory readers and anchors, PR #140)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4f-4 complete. Five commits on `claude/audit-round4f-4`, working tree clean, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **M-a** degraded discovery | **fixed** — `broad_repo_set_detail` tests emptiness on *discovery*, not the augmented list; `drift-sweep.main` also refuses to log any row whose `repos` is 0. `TestTheAugmentationNeverSubstitutesForDiscovery`, `test_a_degraded_machine_refuses_without_stubbing_discovery` (only `project_id.repo_set` and `PA_DIR` stubbed), `test_a_zero_repo_result_is_never_logged`, `test_the_floor_skips_a_degraded_row_already_in_the_log` |
| **M-b** unreported exclusions | **fixed** — trend row carries `unusable` (paths), `_render` lists them, `[F]` prints "repositories EXCLUDED : N of M" and names them; both callers reset the registry first. `test_the_trend_row_names_the_repositories_left_out`, `TestTierCNamesTheExcludedRepositories` |
| **M-c** excluded repo's own anchors | **fixed** — an excluded repository contributes `unknown`, which blocks a committal verdict in `verify_file` (both branches) and `verify_commit`. `test_a_ref_living_only_in_the_broken_repo_is_pending` (5 good repos + 1 taken away after the file was committed), `test_an_absolute_ref_inside_the_broken_repo_is_pending`, `test_commit_refs_are_pending_beside_a_broken_repo` |
| **M-d** bare `OSError` | **fixed** — `_PERMANENT_REPO_ERRORS` (FileNotFound / NotADirectory / Permission) excludes; every other `OSError` stays ref-level pending. Parametrised over ENOMEM, EMFILE, EINTR, EWOULDBLOCK |
| `:212-213` early return | **killed** — `test_the_broken_repo_is_probed_once_not_once_per_ref` (subprocess count, not verdict) |
| `:518-520` verify_commit skip | **killed** — `test_verify_commit_skips_the_excluded_repository` |
| `:90` once-per-process guard | **killed** — asserted directly on `note_unusable_repo`; the resolvers' short-circuit hides it from any integration test |
| `:172-175` `_resolves_inside` | **killed** — `except → True` and dropping `real == root` both fail (`TestResolvesInside`) |
| mhr `:578` rollback | **killed** — `test_a_schema_mismatch_ends_the_transaction` |
| `:336-339` absolute `continue` → `pending_seen` | **equivalent mutant, recorded** — after M-c both flags feed the same `if not checked_any or pending_seen or unknown_seen` expression, so no observable difference remains. The two absolute-ref cases the brief asked for are added; they pin the behaviour, not that distinction |
| **L-b** dead `scoped or` | **fixed** — branch removed (project candidates ⊆ union, so ambiguity at home is ambiguity in the union); the test now says it checks an invariant and cannot fail |
| **L-c** E302 | **fixed** |
| **L-d** WARN wording | **fixed** — names `--min-repos` / `--no-log` / "the last logged sweep"; both branches tested |
| **L-e** case-folded write-back | **fixed** — the record's own spelling returns ("High" stays "High"); comparison stays case-insensitive |
| **L-g** `MPZHXY3P` | **fixed** — replaced at both sites |
| **L-f** | note only, no change |

## Suite

Clean `git archive HEAD` copy in `mktemp -d`, `HOME` pinned inside it, isolated `--basetemp`, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`:

`3868 passed, 1 skipped, 3 deselected, 34 subtests passed in 161.19s (0:02:41)` — exit code **0**.

One caveat the run printed itself, worth passing on: **`PA_HERMETICITY_STRICT=1` is only half-strict in an archive copy.** The export has no `data/` submodule, so `memories/memories.jsonl` and `memories/tag-vocabulary.txt` dangle and the store half of the guard is inert; only the source-tree half was enforced. The same is true of this worktree (uninitialised submodule). Exercising the store half needs the live checkout, which I did not run against.

```text
c139769 fix(anchors): five small corrections from the re-audit
457cb3e test(anchors): pin the symlink guard's edges and the rollback
5f25281 feat(anchors): report the repositories resolution left out
a3ce064 fix(anchors): an excluded repository answers "unknown", not "absent"
a0d35f0 fix(anchors): a lone checkout is not a repository set
```

## Live-behaviour risks

1. **M-c partly reverses M6's posture, deliberately.** An excluded repository now blocks a `false` verdict, so a sweep taken while a mount is away reports those anchors pending and the pending-rate floor then says "unreliable" and writes no row. That is the intended posture — it is the alternative to recording absence we did not observe — but it means a flaky mount turns sweeps into refusals rather than into drift spikes. The `unusable` list in the row and in `[F]` is how an operator sees why.
2. **`/memory-health --tier-c` and the sweep will now refuse on a machine where discovery finds nothing**, where before they would resolve against the running checkout alone. On this machine discovery finds ~36, so no change is expected; a container or a fresh clone is where it bites.
3. **`--min-repos` is now the only way past a shrunken set**, and the WARN names it. The first post-merge sweep may still need one reset run if the last logged row came from a worktree.
4. **`bind_confidence` no longer normalises case.** A record carrying `"High"` keeps it through a pending re-verification instead of being rewritten to `"high"`; anything downstream that compares confidence exactly should case-fold.
5. Unchanged from 4f-3: `audit-postgres-sync` and `/memory-health` both fail on a PostgreSQL-only row; short commit refs read pending rather than false; the symlink guard may flip anchors whose path leaves its repository through a symlink.
