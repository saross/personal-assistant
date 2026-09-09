# Round 4c-6 report (session archive pipeline, PR #147 second round)

The fix agent's final report, copied verbatim from the session on 2026-09-09.
Every fixture named is synthetic.

---

Round 4c-6 complete. Tree clean, scratch deleted (104,655 inodes freed).

## Disposition

| ID | Disposition |
|---|---|
| **C1** (blocking) | **fixed** — `push-archives-to-r2.sh` now matches the level marker as a token: `(^\|[[:space:]])(ERROR\|NOTICE)[[:space:]]*:`, still combined with rclone's refusal wording. Every stub in `tests/test_glue_scripts.py` (13 replacements) writes the date-prefixed form rclone actually emits, and a new parametrised matrix pins all six classifications. Restoring `^(ERROR\|NOTICE)` now fails **8 tests** |
| **L-a** | fixed — the `not is_link` conjunct is gone; `info` comes from `lstat`, so `S_ISDIR` already describes the link and can never be true for one. The comment says so |
| **L-b** | fixed — `SIZELESS_IDS_SHOWN` drives both the slice and the remainder. `test_the_shown_ids_and_the_remainder_agree` parses the emitted message and asserts shown + remainder == total; widening the constant fails the paired literal test |
| **L-c** | fixed — `sizeless_sessions` is a required parameter. `test_the_collector_is_a_required_argument` inspects the signature; making it optional again fails |
| **L-d** | fixed — labels are now `stale-temp — dangling symlink` / `stale-temp — symlink`; the tests assert the stutter is absent |
| **L-e** | fixed — the dry-run listing uses `entry.get("size_bytes")` and prints "size not recorded". `test_dry_run_survives_a_sizeless_manifest` fails on the unguarded read |

## C1 — the three-way evidence, reproduced

I confirmed all three before changing anything.

**1. The binary.** `rclone help flags` shows `--log-format Bits … (default date,time)`, and `strings $(command -v rclone)` carries the Go layout `2006/01/02 15:04:05` and the level format `%-6s: %s`. That padding is also why the marker is `ERROR :` (5 chars + pad) but `NOTICE:` (exactly 6, no pad) — my regex tolerates both.

**2. The deployed log** (`~/personal-assistant/logs/r2-push.log`, read-only, three lines as authorised):

```
lines containing ERROR|NOTICE : 9314
matching ^(ERROR|NOTICE)      : 0
2026/05/28 14:31:22 ERROR : README.md: Failed to copy: NotImplemented…
```

Zero of 9,314. Every real line is date-prefixed.

**3. Sandbox stub**, before the fix:

| stub line | exit |
|---|---|
| `2026/09/09 12:00:00 ERROR : … immutable file modified` | **2** ← wrong |
| same line un-prefixed (what the tests wrote) | 3 |
| `2026/09/09 12:00:00 NOTICE: … Timestamp mismatch…` | **2** ← wrong |

After the fix the full matrix is: date-prefixed ERROR refusal → 3; date-prefixed NOTICE refusal → 3; un-prefixed ERROR refusal → 3; INFO path containing "immutable" → 2; the wording at DEBUG → 2; plain ERROR transport failure → 2.

This was my own regression from round 4c-5, and it is the second time in this pipeline that a *narrowing* silently disabled the thing it was meant to sharpen. The tests certified a format rclone never emits, so nothing caught it — the same class as the M1 inert test one round earlier.

**On the removed self-line filter:** it need not return, and the comment now says why. `log()` writes `[YYYY-MM-DD HH:MM:SS] r2-push: …`, which carries no level marker; I checked all 13 log call sites and none contains an `ERROR:`/`NOTICE:` token, so no line this script writes can satisfy the match.

## Suite

Clean `git archive` copy of HEAD, HOME pinned, `--basetemp` isolated, `PYTHONDONTWRITEBYTECODE=1`, `PA_HERMETICITY_STRICT=1`:

```
4327 passed, 3 skipped, 19 deselected, 34 subtests passed in 195.90s (0:03:15)
```

**exit code 0.** The three skips are environmental and not mine: `test_codex_main_tripwire.py` (an archive export has no `.git`) and two `test_style_phase5.py` cases needing numpy. The store half of the hermeticity guard remains inert in an archive copy, as its banner states.

## `git log --oneline main..HEAD`

```
e06c5a2 fix(archive): guard the dry-run listing and tighten the sizeless report
3775a0a fix(r2): match rclone's level marker, not the start of the line
1286407 Merge remote-tracking branch 'origin/main' into claude/audit-round4c-5
2a5c81e fix(archive): summarise sizeless manifest entries once per run
3fa6b85 fix(normalise): count sweep failures, and handle *.tmp symlinks
f78bacb fix(r2): classify on rclone's refusal wording, not the bare word
```

Two new commits this round. Not pushed.

## Live-behaviour risks

1. **The R2 push can once again exit 3.** On this branch before today it could not: every real refusal classified as 2. The immediate consequence is that the refusal already sitting in the deployed log from today 10:28 (`CATALOG.json`) will be reported as an abort the next time it recurs — which is correct, and is the signal main was giving. Anything that has grown used to this branch never returning 3 will see it again.
2. **That refusal is a real one and still needs a human.** `CATALOG.json` is rewritten by `verify --fix-catalogue`, so its size legitimately changes — which is precisely what `--immutable` refuses. Whoever triages it should decide whether the catalogue belongs in an append-only mirror at all; the classifier is now reporting it accurately rather than hiding it.
3. **`archive --dry-run` now succeeds on a legacy manifest** where it previously raised KeyError. If a wrapper treated that crash as "nothing to preview", it will now get a real listing with "size not recorded" entries.
4. **Sweep labels changed** (`dangling symlink`, `symlink`) — a log scraper matching the old `dangling link` / `symlink link` text will stop matching.
5. **`refuse_incomplete_source` signature changed** (the collector is required). It is called from one place inside this repo; any out-of-tree caller would now fail loudly at the call rather than silently losing the report — which is the intent, but it is a breaking signature change.
