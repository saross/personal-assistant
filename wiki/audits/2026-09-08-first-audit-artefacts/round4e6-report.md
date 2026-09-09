# Round 4e-6 report (bake-off tooling, follow-ups after PR #142)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4e-6 complete: seven commits, clean tree, nothing pushed.

## Disposition

| Item | Disposition |
|---|---|
| **M1** — unfalsifiable assertion | **fixed** — `test_the_superseded_batch_is_still_retrievable` now asserts the live wording (`"no session mapped to custom_id"` and `"skipping a result that was ALREADY PAID FOR"` both absent). Confirmed falsifiable: replacing rather than merging the custom_id map — the defect the test exists for — now turns it red, which the stale assertion never did |
| **L2** — stale wording | **fixed** — the `haiku_submit` comment and the test docstring both quote the current message |
| **L3** — `<manifest>` is a redirection | **fixed** — new `rebuild_map_command` uses the manifest path recorded in `batch-state.json`, shell-quoted, and falls back to `PATH-TO-MANIFEST` (no metacharacters) when the state records none. Three tests: the printed line splits into the expected vector and, run through `main()`, actually repairs the map and writes the stranded response; the placeholder form is paste-safe; the unedited placeholder exits 2 rather than crashing |
| **L4** — `setdefault` → assignment | **fixed (tests)** — pinned with a state whose stored mapping *disagrees* with the reconstruction, so "existing entries win" is observable. Only a real submission knows which session a custom_id went out under |
| **L5** — `write_json_atomic` → `write_text` | **fixed (tests)** — crash injection on `os.replace`: the previous state must be byte-identical afterwards and no debris may remain beside it |
| **L6** — `shlex.quote(batch_id)` | **decision: keep the defensive quote**, pinned with a hostile synthetic id. Anthropic ids are `msgbatch_` plus base62 and need no quoting today, but the value is interpolated into a line an operator pastes into a shell; the cost of that assumption changing is a command that does something other than it reads. Stated in the commit message so the choice is on the record |
| **L7** — mirrored expectation | **fixed (tests)** — `test_retrieve_command_quotes_a_directory_with_a_space` spells the quoted string out by hand rather than calling `shlex.quote`, so it cannot follow the implementation |
| **L8** — third `and` fence | **fixed (tests)** — `test_build_rubric_without_paths_exits_2` parametrised over neither / in-only / out-only; `and` → `or` now fails two of three |
| **L9** — 40-hex session id mislabelled | **fixed** — recovery consults the manifest **first**. `build_custom_id` is pure, so hashing each known session id and comparing reverses *both* forms, including a genuine digest, which shape could never do. Shape decides only with no readable manifest, and the wording then says the id could not be recovered *without one* rather than asserting a digest. `haiku_apply` reads the manifest named in the state once, before the loop; every read failure is a quiet empty set |
| **L10** — malformed manifest traceback | **fixed** — seven malformed shapes now raise `ManifestFormatError` (path, and the entry's position for a bad entry) and exit 2 from `main`. Validation completes before anything is written, so a manifest whose second entry is bad leaves the state untouched rather than half-applied |

## Suite (clean `git archive` copy, `HOME` pinned, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`, isolated `--basetemp`)

```
4311 passed, 3 skipped, 19 deselected, 34 subtests passed in 165.91s (0:02:45)
```

Exit code **0**, captured separately.

The strict-mode banner fired again and is worth repeating verbatim, because it bounds what this run proves:

> `PA_HERMETICITY_STRICT=1, but these watched store paths are missing or dangling here … The store half of the hermeticity guard is INERT in this run; only the source-tree half is strict.`

A git-archive export has no `data/` submodule, and my worktree has it uninitialised, so neither environment available to me can exercise the store half. That gap is unchanged from last round and needs a checkout with `data/` populated to close.

```
d98c14c fix(bake-off): refuse a malformed manifest in --rebuild-map
c76a85c fix(bake-off): recover a session id from the manifest first
4047b79 test(bake-off): cover one-of-two on the rubric fence
4cc983b test(bake-off): pin the quoted line literally
60b08b0 test(bake-off): pin the rebuild's two safety properties
58c9322 fix(bake-off): make the repair line survive a paste
6c2d347 test(bake-off): assert the live unmapped wording
```

## Live-behaviour risks

1. **The repair line now names a real path.** Where `batch-state.json` records `manifest_path`, the printed remedy interpolates it — so the line reveals a manifest location in terminal output and logs. That is the same path the state file already carries, but it is now on screen.
2. **`haiku_apply` reads one extra file.** It opens the manifest named in the batch state (once, before the loop) to confirm session ids. If that path has moved or been replaced by an unrelated file, recovery silently falls back to the shape heuristic — no error, slightly vaguer diagnostic.
3. **`--rebuild-map` refuses more inputs than before** (exit 2 on a missing, unreadable, or oddly-shaped manifest). Any wrapper that fed it a placeholder and ignored the outcome will now see a non-zero exit — which is the point.
4. **Diagnostic wording changed again**: `"session id not recoverable from a hashed custom_id"` is now `"session id not recoverable without a manifest — the custom_id looks like a digest"`. Log matchers keyed to the old phrase need updating; the assertion this round fixed was exactly that failure mode, so it is worth grepping for others.
5. **No behaviour change for the ordinary paths** — submit, dry run, gate, retrieval of a healthy batch. Everything this round touched is either a diagnostic, a refusal, or the repair path.
