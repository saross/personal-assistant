# Round 4e-7 report (bake-off tooling, follow-ups after PR #146)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4e-7 complete: five commits, clean tree, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **M1** (blocking) — repair path could not use the manifest | **fixed** — `rebuild_custom_id_map` now records `manifest_path` in the state (`setdefault`, so a real submission's provenance is never overwritten by whatever file someone repaired with), and `main` threads `args.manifest` into `haiku_apply`, which prefers it over the state's record for both reversing a custom_id and for any remedy line it still prints. **My first draft of this commit claimed a mutation kill it did not have**: once the rebuild records the path, the end-to-end test finds the manifest through the *state* and cannot see the threading at all. I added `test_the_entry_point_threads_manifest_without_rebuild_map` — stale recorded path, no `--rebuild-map`, digest-form session id — and amended the commit; dropping `manifest_path=args.manifest` now fails |
| **M2** — unquoted manifest in the remedy | **fixed (tests)** — the literal quoted string is pinned, plus an end-to-end check that the emitted line splits back into the same path. Same class as the retrieve line |
| **M3** — `or` → `and` in the session-id guard | **fixed** — added empty, blank, and tab-only ids. The blank cases exposed a real gap: `"   "` is truthy, so it passed validation and would have named a response file `   .json`. The guard now strips before testing |
| **L1** — silent fallback | **fixed** — each unreadable-manifest case prints to stderr naming the path and the reason, and suggests `--manifest` with a readable copy. Silence let an operator read "not recoverable" and conclude "digest" when the manifest simply could not be read |
| **L2** — unguarded `manifest_path` type | **fixed** — one `state_manifest_path` helper used by both readers. A numeric value used to raise `TypeError` at the *end* of a retrieval, after responses were written |
| **L3** — `{"sessions": []}` accepted | **fixed — my call is to refuse (exit 2)**, stated in the commit: an empty manifest cannot repair anything, the named file is almost certainly wrong, and rewriting the only handle on a paid-for batch to achieve nothing is the wrong default |
| **L4** — rebuild dropped a collision | **fixed** — refuses, naming both ids, matching `haiku_submit`. Tested with the constructed pair (a long id and the id equal to its own digest prefix). A repeated session id is still fine, and a differing *stored* entry remains "existing wins" rather than a collision |
| **L5** — re-hashing per result | **fixed** — `custom_id_lookup` builds the dict once per retrieval; first-wins preserved, and pinned |
| **L6** — "Order matters" over-claim | **fixed** — the comment now says the manifest is consulted first because it is the better answer, not because order changes the result; what matters is that shape is not consulted alone |
| **L7** — no fsync | **fixed** — flush plus `os.fsync` before `os.replace`. **The mutation survives and I say so in the commit**: durability across a power loss is not observable from a test process, and the existing crash pin covers the in-process half |

## Suite (clean `git archive` copy, `HOME` pinned, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`, isolated `--basetemp`)

```
4421 passed, 3 skipped, 19 deselected, 34 subtests passed in 196.04s (0:03:16)
```

Exit code **0**, captured separately. The strict-mode banner again reports that the **store half of the guard is inert** in an archive export (no `data/` submodule); only the source-tree half is strict. Unchanged from the last two rounds, and not closeable from either environment available to me.

```
df9ec6e perf(bake-off): build the custom_id lookup once, and fsync
6d4aa59 fix(bake-off): refuse an empty or self-colliding manifest
526adb7 fix(bake-off): guard and explain the manifest lookup
e554dd0 fix(bake-off): quote the remedy's manifest, reject a blank id
71072fb fix(bake-off): let the repair run use the manifest it is given
```

## Live-behaviour risks

1. **`--rebuild-map` now writes `manifest_path` into `batch-state.json`** when the state does not already record one. Anything that diffs state files will see a new key on repaired states.
2. **`--haiku-apply` reads `--manifest` when supplied**, even without `--rebuild-map`. Previously the flag was accepted and ignored on that path; passing a *wrong* manifest now affects the diagnostic wording (never the response files, which are keyed on the stored map).
3. **Two more inputs are refused with exit 2**: a manifest listing no sessions, and one whose sessions collide onto a single custom_id. A wrapper that fed either and ignored the outcome will now see a failure.
4. **A whitespace-only `session_id` in a manifest is now rejected** where it was previously accepted. If any real manifest carries one, `--rebuild-map` will stop on it — which is the intent, but it is a behaviour change on existing data.
5. **New stderr output** from `known_session_ids` when a recorded manifest cannot be read. Retrieval still succeeds; log scrapers keyed on a silent stderr will see traffic.
6. **`_atomic_write` now fsyncs every write** — responses, batch state, the rubric, the blinding key, the dry-run cost file. On a slow or network filesystem that is measurably slower per file; at bake-off volumes (tens of files) it is negligible, but it is a global change to every write in the script.
