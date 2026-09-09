# Round 4e-5 report (bake-off tooling, PR pending)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4e-5 complete: five commits, clean tree, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **L1** — unquoted paths in the recovery line | **fixed** — `haiku_retrieve_command` (`scripts/bake-off-metadata.py:690`) now passes the batch id and the output directory through `shlex.quote`; quoting a value that needs none is a no-op, so the ordinary case reads unchanged. `test_the_emitted_line_actually_runs` submits into a directory called `bake off runs` and asserts the split argument vector element by element before handing it to `main()`. Dropping the quote on `--out-dir` now fails |
| **L2** — `and` → `or` on both fences | **fixed (tests)** — `test_a_live_run_still_demands_manifest_and_prompt` and `test_build_rubric_still_demands_manifest_and_prompt` are parametrised over neither / manifest-only / prompt-only. The mutation now fails four of the six cases; previously all six passed |
| **L3** — `n_requests` vs map size | **fixed (tests)** — `test_resubmit_tops_up_only_the_missing_sessions` asserts `n_requests == 1` while `len(custom_id_to_session) == 3` after a top-up, pinning the two apart. `n_requests = len(custom_id_map)` now fails |
| **L4** — threshold only pinned `> 2` | **fixed (tests)** — three boundary fixtures: 100 entries must be rejected (kills `> 2`), 101 must be accepted (kills `> 100000`), and the degenerate two-entry case is kept |
| **L6** — stranded results | **fixed** — the diagnostic recovers the session id when the `custom_id` carries it verbatim (`recover_session_id_from_custom_id`; a 40-hex digest is not reversible and it says so), states the result was **ALREADY PAID FOR**, and prints the exact repair command once at the end. The summary now reports both kinds of skip, so every result is accounted for. New `--rebuild-map` (with `--haiku-apply` and `--manifest`) reconstructs the mapping from the manifest — every `custom_id` is a pure function of a session id — with existing entries winning. `test_the_remedy_actually_recovers_the_result` runs the suggested command end to end and asserts the stranded response lands |
| **L5** | noted, no action — watching `.git` remains a flake surface in the main clone during a concurrent git operation; the failure message names the offending paths |

## Suite (clean `git archive` copy, `HOME` pinned, `PA_HERMETICITY_STRICT=1`, isolated `--basetemp`)

```
3917 passed, 1 skipped, 3 deselected, 34 subtests passed in 156.67s (0:02:36)
```

Exit code **0**, captured separately. The skip is `tests/test_codex_main_tripwire.py:117: no checkout to calibrate against` — expected with no `.git`.

**`PA_HERMETICITY_STRICT` now has a consumer** (round 4a-3 has landed on main), and it earned its keep immediately by printing:

> `PA_HERMETICITY_STRICT=1, but the canonical store is not present here … The store half of the hermeticity guard is INERT in this run — an archive export has no data/ submodule, so those paths dangle. Only the source-tree half is strict.`

So this run exercised the source-tree half strictly and the store half not at all. My worktree has the same uninitialised submodule, so it cannot close that gap either — exercising the store half needs a checkout with `data/` populated, which is outside what I should run in. Worth knowing before treating a clean-copy pass as full strict coverage.

```
bb5143a feat(bake-off): explain and repair a stranded batch result
5d00e54 test(vocab): fix the snapshot threshold from both sides
384fb9c test(bake-off): pin n_requests to the batch, not the map
0743ae6 test(bake-off): cover one-of-two on both argument fences
7a67844 fix(bake-off): quote the paths in the recovery line
```

## Live-behaviour risks

1. **New flag `--rebuild-map`** writes to `batch-state.json` (atomically, merging rather than replacing). It is refused without `--haiku-apply` (exit 2), without `--manifest` (exit 2), and when there is no state file (exit 2). It only ever *adds* entries, so running it against a healthy state is a no-op reporting `restored 0`.
2. **The `--haiku-apply` summary gained a line.** Anything scraping the retrieval output now sees `[haiku] skipped N already-complete and M unmapped result(s)` between the totals and the kept-responses line.
3. **The unmatched-result message changed wording** — `unknown custom_id X — skipping` is now `no session mapped to custom_id X (probably session Y) — skipping a result that was ALREADY PAID FOR`. Any log matcher keyed to the old phrase needs updating.
4. **The recovery line is now shell-quoted.** For ordinary paths the text is byte-identical; for a path containing a space or a shell metacharacter it now carries quotes, so an exact-string comparison against a previously recorded line could differ.
5. **Existing state files are still not migrated automatically.** A pre-accumulation state that already lost its entries stays broken until someone runs `--rebuild-map` — but it now says so, names the probable session, and hands over the command instead of printing a bare id.
