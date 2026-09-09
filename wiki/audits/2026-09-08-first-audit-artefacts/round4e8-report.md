# Round 4e-8 report (bake-off tooling, follow-ups after PR #150)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic. The agent's Bash became unusable at the
end (a full /tmp); its four commits were confirmed by `git log` afterwards
(6b7cd19, a11bc0f, 1679b7d, d743873) and the tree was clean.

---

Bash is now unusable — every command fails with `ENOSPC: no space left on device` when the harness tries to create its output file. I am stopping cleanly here, as instructed. Nothing is half-done: all four commits landed and the clean-copy suite ran green immediately before the disk filled.

## ⚠️ Environment: /tmp is full

This affects every agent on this machine, not just me. My last work directory, **`/tmp/tmp.tU7JIB2yce`** (a git-archive copy of the repo plus a pytest basetemp, roughly 50–60 MB), **could not be deleted** — the `rm -rf` failed with ENOSPC like everything else. It needs removing by hand, along with whatever else has accumulated under `/tmp/tmp.*`; when I last measured, sibling agents' repo copies there totalled 268 MB.

## Disposition

| Item | Disposition |
|---|---|
| **M1** — stale `--manifest` help | **fixed** — help now says "Optional but used by `--haiku-apply`: it names the sessions behind unmatched custom_ids and is what `--rebuild-map` restores the map from". Pinned by reading the real parser's `--help`. **My first draft of that test was red and I committed it**; the assertion searched the whole help text and matched `--prompt`'s entry, where "unused by --haiku-apply" is *true*. Scoped to each flag's own entry and amended the commit |
| **M2** (regression) — unreadable `--manifest` defeated a good recorded one | **fixed** — `resolve_manifest` returns both the ids and the manifest they came from. A supplied manifest still wins, but only if readable; otherwise the recorded one is tried, with both paths named on stderr. When nothing is readable the manifest used is `None`, so the remedy line falls back to the placeholder instead of repeating the typo. `_read_manifest_session_ids` distinguishes "cannot be read" (fall back) from "lists nothing" (do not) |
| **L1** — fourth unreadable case silent | **fixed** — a `manifest_path` that is a number, a list, or an empty string now names the value's type and says it is being treated as unrecorded. An *absent* key stays silent, because nothing was claimed; the test asserts both halves |
| **L2** — strip guard rebuild-only and cosmetic | **fixed** — `validate_session_id` is now the single rule, called by `haiku_submit` before the billed create call and by `rebuild_custom_id_map` per entry. Whitespace is **refused, not stripped**: the id must round-trip byte-for-byte between the batch and the response filename, so silent stripping would reconstruct a custom_id that could never match what was submitted |
| **L3** — X/Y asymmetry only in a comment | **fixed** — the "restored N custom_id mapping(s)" line names the manifest it rebuilt from and, when they differ, the one the state still records |
| **L4** — probabilistic first-wins | **fixed** — the fixture passes a *list* in the opposite order to sorted, so the sorted winner is asserted explicitly. The unsorted mutation now dies on every run (verified three consecutive times) rather than roughly two in six |
| **L5** — fsync and the broad handler | **fixed** — the parent directory is fsynced after `os.replace`, ignoring filesystems that refuse. `OSError` now carries the path, because in a loop over a batch's responses a bare "No space left on device" does not say which response was lost. Everything else (KeyboardInterrupt, a caller's serialisation `TypeError`) passes through unrelabelled. **My call on shape**: report and re-raise rather than swallow — a retrieval that cannot write must not look like one that succeeded |

## Suite (clean `git archive` copy, `HOME` pinned, `PA_HERMETICITY_STRICT=1`, `PYTHONDONTWRITEBYTECODE=1`, isolated `--basetemp`)

```
4486 passed, 3 skipped, 19 deselected, 34 subtests passed in 164.54s (0:02:44)
```

Exit code **0**, captured separately. `git status --short` printed nothing in that same invocation, so the tree was clean. The strict-mode banner again reports the **store half of the guard is inert** in an archive export — unchanged, and not closeable from either environment available to me.

## Commits

Four this round. Recorded from each commit's own output as it was made — I could not re-read the log at the end, so treat the hashes as needing a `git log` to confirm:

```
d743873 fix(bake-off): flush the rename, name the file that failed
1679b7d fix(bake-off): validate session ids once, at both entry points
a11bc0f docs(bake-off): correct --manifest help, name both manifests
6b7cd19 fix(bake-off): fall back when the supplied manifest is unusable
```

## Live-behaviour risks

1. **`haiku_submit` now refuses session ids with leading or trailing whitespace, or that are blank** — before the billed call. If any existing manifest carries one, a submit that previously went through will now stop. That is the intent (such a batch was unrepairable), but it is a behaviour change on existing data.
2. **A mistyped `--manifest` no longer wins.** The run falls back to the recorded manifest and says so on stderr. Anyone relying on the argument overriding unconditionally will see different resolution — and, when neither is readable, a remedy line naming the placeholder rather than their path.
3. **New stderr output** in two more cases: a malformed `manifest_path` in the state, and the fallback notice.
4. **Every atomic write now fsyncs the parent directory** in addition to the file. On a slow or network filesystem that is a second sync per file; at bake-off volumes it is negligible.
5. **Write failures now raise `OSError` with the path prepended.** Any handler matching on the exact message text of the underlying error will need to match on substring instead.
6. **Unverified since the disk filled**: I could not re-run anything after the final green suite. The suite result above and the clean tree were observed in the same command, before the failure, and I made no edits afterwards.
