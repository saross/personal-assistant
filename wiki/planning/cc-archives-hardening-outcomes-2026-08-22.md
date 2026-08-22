---
title: "cc-archives — hardening outcomes"
tags: [planning, infrastructure, session-archive, hardening]
created: 2026-08-22
updated: 2026-08-22
status: record of decisions and fixes — answers the 2026-08-22 health brief
---

# cc-archives — hardening outcomes (2026-08-22)

Companion to `cc-archives-health-and-hardening-2026-08-22.md` (the brief).
Everything here was implemented and verified on 2026-08-22 in the
session-archiving hardening session (Fable), with Shawn's rulings recorded
where a decision was his. Commits: personal-assistant public repo + `data`
submodule (this session's batch), cc-session-toolkit `a5f4680`,
map-reader-llm `703c28af`.

## Corrections to the brief (recorded so the record is right)

1. **Path 1 was never "dead since 8 June" — it was manual-mount-dependent.**
   `daily-sync.log` shows **25 successes and 30 skips** since 2026-06-08
   (the brief said 4 lifetime successes). The 2026-08-19 22:34→22:35
   sequence (skip, skip, success 63 s later) shows the pattern: the pass
   ran whenever someone mounted rpi-shares by hand and skipped otherwise.
2. **Syncthing was NEVER a cc-archives replication path.** Its one folder
   is `Sync` = `~/Documents/sync` (personal documents). The brief's B3
   inference — "the copies converge, presumably via Syncthing" — was wrong
   twice: convergence came from the 25 manual-mount daily-sync runs, and
   Syncthing being down never affected the archive. (It was still genuinely
   broken for personal docs — fixed below.)
3. **The archive was never at risk from a single path.** With Syncthing out
   of the picture, the real topology was: rsync passes (working, when
   mounted) + R2 (working). Fragile, but never one-path-deep.

## Answers to the brief's nine questions

**1. Canonical storage form.** `session.jsonl.gz`, ruled and enforced.
The three-state population (157 raw-only, 35 dual, rest gz-only as
measured per-meta) had ONE cause: `archive_session(use_gzip=False)`
default, with hooks passing `--gzip`, bulk runs hardcoding it, and old
manual runs not. Fixed at the source (toolkit `a5f4680`): gzip is the
default (`--no-gzip` to opt out), gz writes are verified by decompress
round-trip sha256, the meta records `jsonl_sha256_uncompressed`, and an
identical raw sibling is removed at archive time. The one-off pass
(`scripts/normalise-archive-storage.py`) ran on the local mirror AND the
canonical store: **157 compressed + 35 dedup'd on each, 0 divergent, 0
errors — every dual pair was byte-identical**. ⚠ zbook must run the same
pass (inbox row, 2026-08-22) or its append-only push re-seeds raw files.

**2. Accessor.** `cc_session_toolkit.transcript_text.resolve_transcript()`
(+ public `open_transcript()`, which also survives mis-labelled legacy
`.gz`). The indexer now resolves both forms; the remaining gz-only
consumers (`reprocess-sessions.py`, `_scan_archives.py`, `bulk-archive.py
enrich`) matter less now the stores are normalised, and should migrate to
the accessor opportunistically.

**3. Path 1: fixed, not retired.** `daily-sync.sh` now **self-mounts**:
5 s SSH probe (fast skip when away from home), stale-FUSE-endpoint
cleanup, then the same sshfs invocation as the `mount-rpi-shares` alias.
Verified live: mount, 4-pass convergence, completeness gate 0, R2 push
complete — all on 2026-08-22.

**4. Syncthing: repaired, and the recurrence closed.** The amd-tower
detached bind + wrong identity were repaired (`docker compose down/up`,
mesh now verifies clean end-to-end). **Root cause of recurrence found:**
`/home/shawn` is eCryptfs (mounts at login) while the container has
`restart: always` — after every reboot Docker binds the un-mounted
underlay before login (verified: boot 09:54, container start 09:56).
Durable fix: `scripts/syncthing-bind-heal.sh` via the systemd user unit
`syncthing-bind-heal.service` (fires at login, after eCryptfs; installed
and enabled on amd-tower). "Repair vs replace" resolves to repair — with
the boot-race closed, the 2026-08-08-class recurrence mechanism is gone.

**5. Canonical naming stands.** rpi-server stays canonical; the staleness
was the manual mount, which the self-mount fixes. Canonical was brought
current same-day (10 pushed up, 6 pulled down, gate 0).

**6. Gate surfacing — the general fix.** Root cause found:
**SessionStart-hook stderr never reaches the session context; stdout
does.** Every gate printed to stderr, which is why the Syncthing gate
"reported" 3 problems every session for two weeks unseen. All four gates
(cc-archives, syncthing, memory-drift NEW, archive-drift NEW) now print
to hook **stdout** under a "RELAY THESE TO SHAWN" header, so the
assistant sees and reports them. Shawn ruled the stdout relay sufficient
(no push notifications, no /standup line, 2026-08-22).

**7. Verification story.** Full `gzip -t` sweep of the local mirror:
**6,278 files (sessions + subagents), 0 corrupt** — the brief's 80-file
sample is now a complete pass. Prospectively, every new gz write is
round-trip verified at archive time (Q1), which is stronger than any
periodic sweep.

**8. Project-identity map.** `data/config/project-identities.json` —
canonical names → aliases (map-reader-llm ← vlm-burial-mound-detection;
fieldmark-docs-staging ← FAIMS3/faims3/fieldmark; paper-b long/short).
**Shawn's ruling: `map-reader-llm` is canonical.** The fork's mechanism
was `get_project_name()` preferring a CLAUDE.md `# Project:` line over
the git remote, and map-reader's CLAUDE.md declaring
`vlm-burial-mound-detection`; the line is fixed (map-reader `703c28af`)
and the toolkit now warns loudly whenever a CLAUDE.md name diverges from
the directory name. Physical merge of the two archive trees remains a
deliberate migration for the archive-integrity session.

**9. Transparency spec.** Shawn ruled: **amend, don't restore.**
Amendment 1 (dated) now heads the spec, correcting location (consolidated
store), storage form (gz), and project identity (both names, alias map),
and the addendum carries a pointer note. map-reader's CLAUDE.md §Session
Archiving rewritten to match, including the read-the-archive-never-the-
live-store rule and the read-BOTH-names rule.

## Beyond the brief — shipped the same session

- **B7 indexer fix** (URGENT since 2026-07-28): `index-session-content.py`
  no longer promotes the transport envelope to a speaker attribution —
  records without `message.role`, `isMeta`, compact summaries, and
  task-notification content are skipped, never mislabelled (they were
  40.0% of indexed `user` chunks). Discovery is now recursive (nested +
  `_legacy/` trees included — 1,126 sessions vs the old depth-2/gz-only
  view) and handles both storage forms. ⛔ The re-index itself stays
  double-gated (drift check + archive-integrity session).
- **B8 class-fix**: `scripts/check-archive-drift.py` — daily raw↔archive
  id-diff per machine (substantive sessions only, 48 h grace), riding
  daily-sync with its own session-start gate. **Its first run caught two
  substantive sessions that had leaked since the July backfill** (both
  archived same day, --stats-only, no API calls) — the leak was live, not
  historical.
- **Memory-system clearances**: drift-check standing rule landed in
  `postgresql-reference.md` (rebuild preconditions section); memory-drift
  gate surfaces at session start; the two orphaned stashes dropped after
  a clean drift re-check; amd-tower PG sync verified current (the
  2026-07-04 backlog verification row closed); issues #53/#55 confirmed
  closed on GH and their backlog rows annotated.
- **Docs de-staled**: `infrastructure-reference.md` (replication topology,
  gates, counts, daily-sync cadence), `network-resources.md` (Syncthing
  scope + root cause + heal unit; store roles + invariant + self-mount),
  `shared.md` session-transcripts row (live store never used for
  provenance), upgrade-plan duplicate IDs disambiguated (E-section B7/B8
  → E4/E5).

## Residuals (known, deliberate)

1. **zbook follow-throughs** — inbox row 2026-08-22 (normalise its mirror
   ⚠ load-bearing; verify self-mount; optional heal unit).
2. **daily-sync control flow**: a git failure early in the script still
   aborts the cc-archives passes (observed 2026-08-22: SSH auth failure →
   archive passes skipped). Not restructured — the script's crash-safety
   was rebuilt on 2026-08-20 and reordering it opportunistically risks
   more than it buys. Candidate for the next infra session: run the
   archive passes before/independent of the git sections.
3. **Catalogue depth-2 (B6)** and the **~276 duplicate archive dirs**:
   archive-integrity session (agenda updated; placement rulings are
   Shawn's).
4. **gz-only consumers** not yet on the accessor: `reprocess-sessions.py`,
   `_scan_archives.py`, `bulk-archive.py enrich` — harmless post-
   normalisation; migrate opportunistically.
5. **R2 keeps superseded raw copies** (additive-only by design) —
   acceptable residue, noted here so nobody reads them as divergence.
6. **GitHub SSH auth from hook/sandbox environments** — ~~residual~~
   **CLOSED same day (Shawn's request).** Root cause: the session ran
   over SSH from zbook, so hooks inherited a *forwarded* agent holding
   only zbook's keys, while `IdentitiesOnly yes` pinned github.com to
   amd-tower's passphrase-protected key — non-interactive processes
   could neither offer a forwarded key nor unlock the pinned one. Fix:
   `origin` in personal-assistant AND pa-data switched to HTTPS with a
   per-repo `credential.helper = !gh auth git-credential` (machine-local
   config on amd-tower; nothing scripted runs `git submodule sync`, so
   the SSH URL still recorded in `.gitmodules` cannot silently revert
   it — left unchanged deliberately so zbook's SSH setup is untouched).
   Verified end-to-end 2026-08-22 10:58: full daily-sync incl. pull,
   push, archive passes, R2, gates — zero SSH involvement. Hooks now
   work identically from desktop and SSH-in sessions.
