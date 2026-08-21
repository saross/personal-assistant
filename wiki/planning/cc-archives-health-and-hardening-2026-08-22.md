---
title: "cc-archives — health assessment and hardening brief"
tags: [planning, infrastructure, session-archive, diagnostics]
created: 2026-08-22
updated: 2026-08-22
status: brief — for Fable to investigate and propose durable fixes
---

# cc-archives — health assessment and hardening brief

**Purpose.** A session reported a *"12-week hole"* in the session transcript archive. **It is
not real.** This document records what was actually found on 2026-08-22, so that (a) nobody
remediates a non-problem, and (b) the two *genuine* faults — both in replication, not in the
data — get a durable fix rather than another patch.

**Audience: Fable.** You are asked to **investigate and propose durable solutions, and harden
the system generally.** Everything below was verified on 2026-08-22 and is re-checkable; where
something is an inference rather than a measurement, it says so.

**⚠ Standing guardrails (`data/global-claude-md/network-resources.md`):** **never reboot
rpi-server** — LUKS-encrypted drives need physical unlock; **always verify mounts before
writing** to its external storage.

---

## Part A — the `.gz` story: there is no hole

### A1. What was measured

| Copy | sessions | raw `.jsonl` | `.gz` | **no transcript** |
|---|---:|---:|---:|---:|
| amd-tower `~/cc-archives` | 851 | 122 | 729 | **0** |
| zbook `~/cc-archives` | 853 | 122 | 731 | **0** |
| rpi-server *canonical* | 850 | 122 | 728 | **0** |

*rpi-server canonical path: `/opt/encrypted/workspace/shares/cc-archives-consolidated`.*

**Every session directory on every machine has a transcript.** Local size 4.8 GB
(1.1 GB raw + 2.6 GB gz + metadata).

**Integrity was checked, not just presence:** 80 `.gz` files sampled across March, May, July
and August — **0 corrupt** (`gzip -t`), **0 suspiciously small**, median **2.3 MB**
uncompressed (min 46 KB, max 12.6 MB). These are real transcripts, not gzipped shells.

### A2. What produced the false alarm

**Most sessions store `session.jsonl.gz` and no plain `session.jsonl`.** A count that globs
`*.jsonl` without `*.jsonl.gz` therefore reports those sessions as transcript-less. Because
the uncompressed copies happen to cluster in the earlier months, **the artefact presents as a
hole that begins at a plausible date** — which is why it was believed.

⚠ **Recorded so the correction is legible rather than tidy: I made this error first**, and was
one command from reporting a **seven-month** hole. The reported 12 weeks is the same artefact
over a shorter window. **The instrument was never wrong** — `~/.cache/cc-archives-gate` reads
`0`, correctly, and has all along.

⛔ **DO NOT BACKFILL.** ~545 sessions would be "restored" over good data. Note also that
`~/.claude/projects/*.jsonl` is a **different population** (amd-tower 2,792 files, zbook 2,336)
— live working transcripts, not archive inputs — so a naive backfill from there would not
merely be redundant, it would be wrong.

### A3. ⭐ The real finding in Part A: three storage states, no invariant

The raw-vs-gz split is **not** a date transition. It tracks session *kind*:

| kind | raw only | raw + gz | gz only |
|---|---:|---:|---:|
| **agent** (subagent sessions) | **47** | 1 | 0 |
| **main** | **41** | 33 | **729** |

**Three states coexist: gz-only (729), raw-only (88), and both (34).** Agent sessions are
almost entirely uncompressed (47 of 48).

**⇒ There is no declared invariant for how a transcript is stored, so every tool that touches
the archive has to guess — and any tool that guesses `*.jsonl` gets a confident wrong answer.**
This is the actual defect behind the false alarm, and it will keep producing false alarms until
an invariant exists.

**Worth proposing:** a single canonical form, a documented accessor that resolves either form,
and a one-off pass to normalise the 122 stragglers. **The 88 raw-only files are also ~1.1 GB
that compression has never touched.**

---

## Part B — replication: two of three paths are down, and the canonical copy is the stalest

### B1. Currency, which is the finding that matters

| Copy | newest archived session |
|---|---|
| zbook | **2026-08-20**T08-23 |
| amd-tower | 2026-08-19T11-53 |
| **rpi-server (canonical)** | **2026-08-18**T00-27 |

**⚠ The canonical store is two days behind the freshest working copy, and the three copies are
drifting apart right now** (853 / 851 / 850). Nothing is lost — but *"canonical"* currently
names the least current copy, which inverts what the word is doing.

### B2. Path 1 — daily-sync mount: **dead since 8 June**

`scripts/daily-sync.sh` (≈ lines 640–698) reconciles `~/cc-archives` against
`$HOME/mnt/rpi-shares/cc-archives-consolidated`, and logs
*"cc-archives sync: mount point missing — skipped"*.

- **30 skips** in `data/logs/daily-sync.log`; **first 2026-06-08**, most recent **2026-08-20**.
- **4 lifetime successes.**
- **The mount is absent on both workstations.** ✅ **rpi-server itself is healthy** —
  `workspace`, `qnap` and `vantec` are all mounted `rw`. **This is a client-side mount problem,
  not a storage problem.**

### B3. Path 2 — Syncthing mesh: **broken on both workstations**

`~/.cache/syncthing-gate` reports **3 problems on each machine**:

- **amd-tower** (checked 2026-08-20): config bind **DETACHED** — the container sees a different
  inode than the host path, so it runs a **stale config**; and **WRONG IDENTITY** — *"advertising
  7OXIKQ7… but the mesh expects TNOT4GW…; peers will refuse it and it will sync nothing."*
- **zbook** (checked 2026-08-21): **rpi-server unreachable over SSH** from zbook; **cannot reach
  amd-tower**.

⚠ **This corrects an inference made earlier the same day.** On finding path 1 dead, I reasoned
that *"the copies converge anyway, presumably via Syncthing."* **They do not.** Syncthing is
also down, and B1 shows the copies diverging. **The apparent convergence was the residue of past
syncing, not evidence of current syncing.**

### B4. Path 3 — R2 offsite: ✅ **working**

`data/logs/r2-push.log` records a clean completion **2026-08-19 22:36**, 399.5 MiB transferred,
driven by `scripts/push-archives-to-r2.sh` from amd-tower (the designated `R2_PUSH_HOST`).

**⇒ The only functioning replication path is the offsite backup.** That is a real safety net —
and it is also the single point of failure, which is not what a three-path design intended.

### B5. Why none of this was noticed

**Two gates exist and both were doing their job.** The cc-archives completeness gate (B7,
2026-07-22) correctly read `0`. The Syncthing gate (added 2026-08-07) has been reporting **3
problems per machine**, on every session start, to stderr.

**⇒ The failure is not detection. It is that a gate printing to stderr at session start is not
a channel anyone reads.** The Syncthing gate's own comment records the precedent it was built
for: the mesh *"sat dead for three [periods] and nothing anywhere reported either fault."*
**It then happened again, to the gate built to prevent it.**

**This is the same shape as two other findings this week** — the memory drift signal buried
under 4,684 legitimately-archived records, and a stale `FOCUS.md` heading the session-start hook
faithfully repeated every morning. **A signal that is emitted but not surfaced is
indistinguishable from no signal.** That generalisation, not the individual fixes, is probably
the most valuable thing here.

---

## Prior work — read before proposing

| Document | Why it matters |
|---|---|
| `wiki/planning/transcript-archive-diagnosis-2026-07-28.md` (492 lines) | Characterises the error *shape*; explicitly **does not fix the pipeline**. Its §3 keeps a superseded characterisation that was wrong on three counts — the same discipline this document follows. |
| `wiki/planning/session-archiving-upgrade-plan-2026-07-21.md` (297 lines) | The tiered architecture and the **B7/B8** items. ⏰ **Shawn raised B7+B8 to "URGENT and blocking" on 2026-07-28** (line ~127). **Check their status first — this brief may be re-deriving work already scoped there.** |
| `tasks/backlog.md` — *"Archive-integrity session — B6 recursion, ~201 duplicates, `922bf6ff`, indexer fixes, then re-index"* | ⛔ **Gates any `--full-resync`.** Explicitly *"BEFORE any --full-resync"*. |
| `tasks/backlog.md` — *"Sub-agent archive PR — follow-on cluster"* | Subagent archiving is where the 47 raw-only agent sessions come from. |
| `~/Code/cc-session-toolkit` | The capture/archive floor itself. |
| `scripts/daily-sync.sh`, `scripts/daily-sync-trigger.sh`, `scripts/push-archives-to-r2.sh` | The three replication paths and both gates. |
| `~/.cache/cc-archives-gate`, `~/.cache/syncthing-gate` | Live gate state. |
| `tasks/inbox.md` 2026-08-22 rows | The two captures this brief expands. |

---

## Open questions for Fable

1. **What is the canonical storage form for a transcript**, and what one-off pass normalises the
   122 stragglers (88 raw-only, 34 dual) without touching the 729 that are already correct?
2. **Should there be a single accessor** that resolves raw-or-gz, so no future tool can repeat
   this class of error? Where does it live — cc-session-toolkit, or a shared helper?
3. **Fix the mount, or retire path 1 deliberately?** Half-alive and logging skips nobody reads
   is the worst of the three options.
4. **Syncthing: repair or replace?** It has now failed twice in a way nobody noticed. ⚠ The
   amd-tower faults are specific and fixable (detached config bind, wrong device identity) —
   but *"fixable"* was true last time too.
5. **Should `rpi-server` still be called canonical** when it is the stalest copy? Either make it
   authoritative in fact, or rename the role to match reality.
6. **⭐ How should gate output actually reach Shawn?** Both gates work and neither is read.
   This is the general problem, and a fix here retires a whole class of silent failure — the
   memory drift detector shipped 2026-08-20 has exactly the same weakness.
7. **What is the verification story?** Presence was checked here; integrity was only *sampled*
   (80 of 763). A full `gzip -t` sweep is cheap and would close it properly.

---

## Verified vs inferred

**Verified by measurement on 2026-08-22:** all session/transcript counts; the three storage
states; gz integrity on an 80-file sample; the newest-session dates per machine; the 30 skips
and 4 successes in `daily-sync.log`; the mount states on all three hosts; both gate files; the
R2 completion.

**Inferred, and flagged as such:** that Syncthing *was* the historical convergence mechanism
(the copies match closely enough that something replicated them, but this was not confirmed
against Syncthing's own logs); and that the 47 raw-only agent sessions come from the subagent
archiving path rather than a separate cause.
