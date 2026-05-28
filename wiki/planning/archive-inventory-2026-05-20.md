# Archive transcript inventory — 2026-05-20 (amd-tower-ubuntu)

Read-only inventory of every Claude Code (CC) session transcript on
amd-tower-ubuntu, in preparation for the Phase 0 consolidation pass.
zbook + rpi-server are explicitly out of scope (zbook in a separate
pass; rpi-server is destination-only, mount-based, no toolkit
installed).

## Summary

- **307 unique main-thread session IDs** across all locations on
  amd-tower (the 32-session figure in earlier planning was the
  archived-and-needing-F3 subset, not the full population).
- **1,360 candidate transcript files** total (433 main-thread + 927
  subagent files), summing **~1.97 GB**. Subagent files inherit the
  parent session ID and live under `<session-id>/subagents/`.
- **Format breakdown:** 1,196 `.jsonl` (~1.49 GB) + 164 `.jsonl.gz`
  (~478 MB). Of the gzipped files, 135 in per-project archives are
  in fact Git LFS pointer stubs (~130 B each); their real content
  lives under git-lfs storage or in the worktree-archive mirror
  (see below).
- **170 main-thread session IDs appear in more than one location**
  ("conflict candidates" per the size/SHA rule), but all 170 are the
  expected live-plus-gzip-archive pairing — same `sessionId`, the
  live copy is uncompressed and growing while the archive copy is
  the final gzipped snapshot. **No genuine content conflicts found.**
- **32 archived main-thread sessions need F3 backfill** (meta exists
  but `auto_generated.purpose == "Auto-metadata unavailable"`). This
  matches the existing F3 estimate of $1.26 mean / $2.79 p90.
- **61 live-only main-thread sessions** have not yet been archived
  (~177 MB on disk under `~/.claude/projects/`). These should be
  swept into the consolidated archive before or during Phase 0; they
  represent ~91 of the 102 live main-thread files plus their
  subagents (a few of the 102 are sessions whose archive copies
  already exist).
- **182 manual `.txt` exports** (~10.7 MB) live under three
  `archive/cc-interactions/` directories. These predate
  auto-archiving (Oct–Nov 2025) and are not JSONL-parseable. They
  need a separate handling strategy at consolidation time.
- **No genuinely unexpected discoveries**: every JSONL/JSONL.GZ
  outside the five known patterns is something else (VSCode chat
  sessions, processing logs, test fixtures, memories.jsonl, etc.) —
  not CC transcripts.

## Per-location breakdown

| Location | Main files | Main bytes | Subagent files | Subagent bytes | Unique main SIDs | With meta.json | Needs F3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `~/.claude/projects/` (LIVE) | 102 | 391,633,278 | 895 | 311,813,425 | 102 | 0 (live = no meta) | n/a (live) |
| `~/Code/<project>/archive/cc-sessions/` (per-project, current default) | 203 | 749,577,140 | 0 | 0 | 202 | 203 | 0 |
| `~/Code/map-reader-llm/.claude/worktrees/agent-…/archive/cc-sessions/` | 87 | 434,562,702 | 0 | 0 | 86 | 87 | 0 |
| `~/cc-archives/<project>/` (legacy global) | 40 | 53,237,041 | 32 | 31,130,722 | 40 | 40 | 32 |
| `~/personal-assistant/archive/cc-sessions/` (pa-stray, gitignored) | 1 | 88,021 | 0 | 0 | 1 | 1 | 0 |
| `~/personal-assistant/data/archive/cc-sessions/` (pa-data submodule) | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Notes on subtleties:

- **Per-project byte totals are misleading.** Of the 203
  per-project files, **135 are 130-byte Git LFS pointer stubs**
  (LLM-History-Paper 49 of 49; map-reader-llm 86 of 87) and only 68
  contain real bytes. The 749 MB total is dominated by
  llm-reproducibility's 67 smudge-pulled sessions (~749 MB).
- **Per-project breakdown by repo:**
  - `LLM-History-Paper`: 49 sessions, all LFS-pointer stubs locally
    (~6 KB on disk; real content in git-lfs storage).
  - `llm-reproducibility`: 67 sessions, smudge-pulled real files
    (~749 MB on disk).
  - `map-reader-llm`: 87 files, 86 LFS-pointer stubs + 1 small real
    (~11 KB on disk; real content is mirrored in the worktree
    archive below).
- **Worktree archive is the real content for map-reader-llm.** The
  87 files at `~/Code/map-reader-llm/.claude/worktrees/agent-a59a9dae0bff3f27b/archive/cc-sessions/`
  are NOT a true duplicate of the per-project archive — they are
  the **canonical bytes** that the per-project LFS pointers reference
  (87 files / 86 unique SIDs / ~434 MB). When consolidating, the
  worktree archive is the source-of-truth for map-reader-llm
  sessions; the per-project archive is just an LFS-tracked pointer
  layer.
- **Legacy-global breakdown by project:**
  - `ANU-HUMN8031-2026`: 4 sessions (~6.3 MB)
  - `LLM-History-Paper`: 3 sessions (~2.3 MB)
  - `client-materials`: 4 sessions (~5.1 MB)
  - `fieldmark-docs-staging`: 2 sessions (~1.5 MB)
  - `inscriptions`: 3 sessions (~34.5 MB)
  - `pa-data`: 1 session (~0.4 MB)
  - `personal-assistant`: 6 sessions (~6.5 MB)
  - `vlm-burial-mound-detection`: 13 sessions (~26.1 MB)
  - `voice-assistant`: 4 sessions (~1.7 MB)
- **Live (`~/.claude/projects/`)** holds every active session CC has
  ever opened until manually removed — including 61 sessions never
  yet archived (the toolkit only archives at SessionEnd/PreCompact,
  so any session that exited via Ctrl-C or crash stays only in
  live).

## Live-only main-thread sessions (not yet archived) by project slug

These are the 61 sessions present **only** in `~/.claude/projects/`
with no archive copy anywhere on amd-tower:

| CC project slug | Live-only sessions |
|---|---:|
| `-home-shawn-personal-assistant` | 10 |
| `-home-shawn-Code-ANU-HUMN8031-2026` | 9 |
| `-home-shawn-Code-LLM-History-Paper` | 8 |
| `-home-shawn-Code-map-reader-llm` | 20 |
| `-home-shawn-Code-inscriptions` | 5 |
| `-home-shawn-Code-voice-assistant` | 4 |
| `-home-shawn-Code-fieldmark-docs-staging` | 2 |
| `-home-shawn-Code` | 2 |
| `-home-shawn-Code-2026-mq-llm-dh-judgement-paper-b` | 1 |
| **TOTAL** | **61** |

Total bytes ~177 MB across these 61 main-thread files (subagent
files for the same sessions add more).

## Manual exports (.txt, pre-December-2025)

These are pre-auto-archive manual exports, before Shawn knew CC was
auto-archiving. Different format (.txt, not .jsonl) and cannot be
parsed for `sessionId`. They will need a `manual-exports/` subdir at
the consolidated archive root and are out of scope for F3
auto-metadata.

| Project | Path | Files | Bytes |
|---|---|---:|---:|
| `llm-reproducibility` | `~/Code/llm-reproducibility/archive/cc-interactions/` | 118 | 6,234,438 |
| `blue-mountains` | `~/Code/blue-mountains/archive/cc-interactions/` | 63 | 4,391,901 |
| `fieldmark-docs-staging` | `~/Code/fieldmark-docs-staging/archive/cc-interactions/` | 1 | 75,686 |
| **TOTAL** | | **182** | **10,702,025** |

## Duplicates (same session ID in multiple locations)

170 main-thread session IDs appear in more than one location. Every
one of these follows the same pattern: a live copy at
`~/.claude/projects/<slug>/<session-id>.jsonl` plus a gzipped
archive copy at one of the archive roots. The live copy is the
authoritative running transcript; the archive copy is the final
snapshot captured at SessionEnd / PreCompact.

Categorisation of the 170 duplicates:

| Pattern | Count |
|---|---:|
| live + legacy-global gzip archive | 32 |
| live + per-project archive | 137 |
| live + pa-stray gzip archive | 1 |

(Plus 86 cases where the per-project copy is an LFS pointer and the
worktree-archive copy holds the real bytes — same SID, both under
`~/Code/map-reader-llm/`. Counted once in the per-project row above.)

## Conflicts (same session ID, different content)

**Zero genuine content conflicts found.** All 170 size-mismatches
between live and archive copies are explained by the gzip-vs-plain
or LFS-stub-vs-real-content distinction. No two archive copies of
the same session were observed to differ in content.

The naive size+SHA-mismatch flag fired on 170 sessions because:
1. `session.meta.json` in every location lacks an
   `jsonl_sha256_uncompressed` field in the locations checked here
   (it is computed at write time but stored under a key our parser
   didn't normalise across schema versions). So the SHA check
   degenerated to a size check.
2. Live JSONL is uncompressed and continues to grow; archive
   `.jsonl.gz` is the gzipped snapshot at session-end time. Sizes
   will *always* differ — this is expected, not a conflict.

Bottom line: **safe to dedupe by either copy** for every duplicate,
treating the archived gzip copy as authoritative once present.

## Unexpected locations

None genuinely surprising. The deeper find (maxdepth 12) surfaced:

- `~/Code/map-reader-llm/.claude/worktrees/agent-…/archive/cc-sessions/`
  (87 files) — this is the **canonical content** for map-reader-llm
  sessions; the per-project archive at
  `~/Code/map-reader-llm/archive/cc-sessions/` holds LFS pointer
  stubs.
- Various non-CC JSONLs filtered out: VSCode chat sessions
  (`~/.config/Code/User/workspaceStorage/.../chatSessions/*.jsonl`),
  processing logs (`~/Code/inscriptions/runs/.../*.jsonl`,
  `~/Code/map-reader-llm/outputs/.../*.jsonl`,
  `~/Code/map-reader-llm/archive/outputs-*/.../verifier_requests.jsonl`),
  CC keystroke history (`~/.claude/history.jsonl`), test fixtures
  (`~/.claude/plugins/.../fixtures/*.jsonl`,
  `~/Code/FAIMS3/api/test/backup.jsonl`), and the memory store
  (`~/personal-assistant/data/memories/memories.jsonl`, plus pytest
  tmp dirs under `/tmp/pytest-of-shawn/`).

External mountpoints (`~/mnt/rpi-shares/`, `~/mnt/rpi-qnap/`,
`~/mnt/rpi-vantec/`, `~/mnt/.claude/`) are present but unmounted at
inventory time — no transcripts to count there. The
`~/personal-assistant/data/archive/cc-sessions/` directory exists
but is empty.

## Recommended consolidation sequence

1. **Pre-sweep**: mount rpi-server's SSD share on the working
   machine. Resolved 2026-05-21 — destination is
   `~/mnt/rpi-shares/cc-archives-consolidated/<project>/<session>/`,
   reached via the existing `mount-rpi-shares` SSHFS alias
   (`~/.bash_aliases:9` →
   `rpi-server:/opt/encrypted/workspace/shares`). 393 GB capacity /
   ~300 GB free; layout structure (READMEs + reserved `_indexes/` +
   `manual-exports/` subdirs) already published on the mount. Confirm
   the mount is live with `df -h ~/mnt/rpi-shares` before any rsync
   pass (silent-empty-dir failure mode if unmounted).
2. **Live → archive sweep first**, before consolidation. Run the
   toolkit's `cc_session_toolkit.cli archive` over the 61
   unarchived live main-thread sessions so they pick up the current
   meta.json contract and the Gemini Flex auto-metadata. Avoids
   F3-backfilling them later. Order: smallest project first
   (`fieldmark-docs-staging`, `2026-mq-llm-dh-judgement-paper-b`)
   to validate the path, then scale to map-reader-llm (20 sessions).
3. **Copy archives to consolidated destination** in this order
   (preserves "archive copy is authoritative once present" rule):
   1. Legacy global (`~/cc-archives/*`) — 40 main + 32 subagent
      files, ~84 MB. F3 backfill needed on 32 of these — do this in
      situ before the copy, so the consolidated copy already has
      Three-Ps-populated meta.json.
   2. Per-project current-default archives:
      - `llm-reproducibility` (67 real files, ~749 MB)
      - `LLM-History-Paper` (49 LFS pointers — copy LFS contents
        from git-lfs, not the stubs)
      - `map-reader-llm` — **use the worktree-archive as source**
        (87 real files, ~434 MB); skip the per-project LFS stubs.
   3. `pa-stray` (1 file, 88 KB) — copy then remove the source
      directory at `~/personal-assistant/archive/cc-sessions/`
      (already gitignored, just a stray).
   4. The 182 manual `.txt` exports → `manual-exports/<project>/`
      under the consolidated root. Out of scope for F3.
4. **Conflict policy**: zero genuine content conflicts found, so the
   policy is trivially "prefer the archive gzip copy where one
   exists; live → archive at SessionEnd will produce the
   archive copy for any remaining live-only session". The only
   nuance is the map-reader-llm worktree-vs-pointer pair: prefer
   the worktree-archive copy (it carries the real bytes).
5. **Total destination footprint estimate**:
   - Per-project archives: ~1.18 GB (749 MB llm-reproducibility +
     434 MB map-reader-llm worktree + ~6 KB LFS-stub layer for
     LLM-History-Paper, which will need the real LFS-stored bytes
     pulled separately before the move, an unknown additional
     volume).
   - Legacy global: ~84 MB.
   - Live-only sweep: ~177 MB (uncompressed; ~30–50 MB gzipped).
   - Manual `.txt` exports: ~11 MB.
   - Subtotal currently visible on disk: **~1.45 GB** (excluding the
     unfetched LLM-History-Paper LFS contents).
6. **Then-and-only-then**: enable per-project archive-defaults that
   point at the consolidated mount, decommission `~/cc-archives/`
   (after a one-week tombstone), and document the new layout in
   `session-archiving-redesign.md`.

## Out-of-scope (for future passes)

- **zbook inventory** — separate machine, separate pass. Estimates:
  unknown population; planning's existing $1.26-$2.79 figure was
  amd-tower-only.
- **rpi-server** — by design, no CC transcripts (infrastructure-only
  NAS, no toolkit installed). Destination only, mounted from the
  working machine; not a source.
- **External drives** — none currently mounted on amd-tower; flag
  for manual follow-up if Shawn knows of any backup tarballs.
- **Cloud backups (R2 bucket)** — out of scope; this inventory is
  on-disk only. R2 wiring is Phase 0e per continuity.md.
