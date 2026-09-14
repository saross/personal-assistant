<!-- markdownlint-disable MD013 -->
<!-- MD013 is off because the fenced blocks carry verbatim source lines and
     command output. Wrapping them would misrepresent the evidence. All
     prose in this file is within 80 characters. -->

# daily-sync leaks its lock into the sshfs mount daemon

> **Filed into the repo 2026-09-14 22:2x from `~/handoff/`.** Written by a
> concurrent Claude session on amd-tower (the Fieldmark website session) and
> handed over as a file, because agent-mail does not currently carry
> Claude-session to Claude-session traffic (backlog row, 2026-09-14).
>
> ⭐ **INDEPENDENTLY VERIFIED on amd-tower, 2026-09-14 22:1x**, by this session,
> before anything was changed. Every cited line number, code line, inode, PID
> and timestamp checks out:
> `daily-sync.sh:736–741` (the `exec 9>` + `flock -n 9`), `:37` (`LOCK_FILE`),
> `:3397–3399` (the sshfs self-mount), `daily-sync-trigger.sh:455` (the
> contention message); `logs/daily-sync.lock` **is** tracked in the `data`
> submodule and `logs` **is** a symlink to `data/logs`; the live lock inode is
> **5936024** while sshfs **PID 91432** (started **Sun 6 Sep 13:25:15**) still
> holds fd 9 on the **deleted** inode **5928262**, with
> `/proc/91432/fdinfo/9` reading `FLOCK ADVISORY WRITE 91218` — the dead
> parent's PID, kept alive by the inherited description. An audit of the whole
> script found **sshfs is the only child that outlives it** (one call, line
> 3397; no other backgrounding).
>
> **State on amd-tower at filing: NOT blocked.** The live lock path has no
> holder and four syncs completed today (10:48, 13:31, 13:32, 13:38). The log
> shows the leak firing and self-clearing twice this month — **6 Sept 13:25:12**
> (three seconds before PID 91432 started) and **11 Sept 09:42:56**, each
> followed by a successful run within the minute.
>
> ⇒ **Suggested fix 1 APPLIED 2026-09-14** (`9>&-` on the sshfs invocation,
> `bash -n` clean). **Fixes 2 and 3 NOT applied** — see the note at the end.

**Filed:** 2026-09-14, from a Fieldmark website session on amd-tower.
**Component:** `~/personal-assistant/scripts/daily-sync.sh`
**Found because:** memory captures made on zbook were not reaching
amd-tower, and vice versa, whilst both machines reported healthy syncs.

There are two defects here. They partially mask each other, which is
why neither has been noticed before.

## Defect 1: the lock is inherited by a long-lived daemon

The script opens its lock on file descriptor 9 and flocks it:

```bash
scripts/daily-sync.sh:736   if ! exec 9>"$LOCK_FILE"; then
scripts/daily-sync.sh:739   if ! flock -n 9; then
scripts/daily-sync.sh:740       log "Another daily-sync is running (lock held). Exiting."
```

Bash does not set close-on-exec on a descriptor opened that way, so
every child inherits it. Later, the cc-archives stage mounts the
Raspberry Pi share when it is missing:

```bash
scripts/daily-sync.sh:3397   if timeout 20 sshfs -o compression=no,ServerAliveInterval=15,reconnect \
scripts/daily-sync.sh:3398           shawn@rpi-server:/opt/encrypted/workspace/shares \
scripts/daily-sync.sh:3399           "$HOME/mnt/rpi-shares" >>"$LOG_FILE" 2>&1; then
```

`sshfs` daemonises and stays resident. A `flock` is held against the
open file description rather than the descriptor number, so the
inherited copy holds the same lock. When the sync exits, the mount
daemon still has it, and every later run fails the flock.

**Trigger.** Only when the share is unmounted at sync time, so the
self-mount at lines 3386 to 3404 fires. If it is already mounted no
child is spawned and nothing leaks.

**Why it is silent.** The trigger treats exit status 1 as ordinary
contention and says it will retry next session:

```bash
scripts/daily-sync-trigger.sh:455   echo "[daily-sync-trigger] lock contention (another sync / commit-data is running); will retry next session" >&2
```

That is correct for a real overlap and exactly wrong here, because the
condition does not clear on its own. Sync stops and nothing reports a
failure.

## Defect 2: the lock file is version-controlled

```text
$ git -C ~/personal-assistant/data ls-files --error-unmatch logs/daily-sync.lock
logs/daily-sync.lock
```

`LOCK_FILE` is `$LOG_DIR/daily-sync.lock` (line 37), and `logs/` is a
symlink into the `data` submodule, so the lock file is tracked and
travels between machines. A checkout or merge replaces the file, and
with it the inode. Two consequences:

- **It accidentally clears defect 1.** The leaked lock is against the
  old inode. Once git swaps the file, the daemon's lock is orphaned and
  the path is free again. This is why amd-tower has kept syncing.
- **It breaks mutual exclusion.** If git replaces the inode whilst a
  sync legitimately holds the lock, a second sync can start
  concurrently, which is the thing the lock exists to prevent.

## Evidence

### The leak, observed on zbook

zbook self-mounted at 13:33:13 and the daemon inherited the lock. Two
later invocations were refused with no sync running anywhere on the
machine:

```text
[2026-09-14 13:33:13] cc-archives sync: self-mount succeeded
[2026-09-14 13:33:24] === daily-sync complete on zbook-ubuntu ===
[2026-09-14 13:34:08] Another daily-sync is running (lock held). Exiting.
[2026-09-14 13:34:35] Another daily-sync is running (lock held). Exiting.
```

The only holder of the lock was the mount daemon:

```text
$ lsof /home/shawn/personal-assistant/data/logs/daily-sync.lock
COMMAND    PID  USER   FD   TYPE DEVICE SIZE/OFF     NODE NAME
sshfs   106873 shawn    9w   REG  252,1        0 25990767 /home/shawn/personal-assistant/data/logs/daily-sync.lock

$ ps -o pid,lstart,cmd -p 106873
    PID                  STARTED CMD
 106873 Mon Sep 14 13:33:13 2026 sshfs -o compression=no,ServerAliveInterval=15,reconnect shawn@rpi-server:/opt/encrypted/workspace/shares /home/shawn/mnt/rpi-shares
```

The start time matches the self-mount log line to the second. After
clearing it, the next sync spawned a fresh daemon (PID 108853) which
took the lock again, so it reproduces on demand.

### The same leak on amd-tower, from 6 September

amd-tower's mount daemon has been running since 6 September and still
holds a descriptor on a **deleted** inode:

```text
$ lsof -p 91432 | grep lock
sshfs   91432 shawn   9w   REG   0,61   0  5928262 /home/shawn/personal-assistant/data/logs/daily-sync.lock (deleted)

$ stat -c '%i %n' /home/shawn/personal-assistant/data/logs/daily-sync.lock
5936024 /home/shawn/personal-assistant/data/logs/daily-sync.lock
```

Inode 5928262 is what the daemon holds; the live file is 5936024. That
is defect 2 rescuing defect 1. The daemon started at 13:25:15 on
6 September, three seconds after a blocked invocation, and amd-tower has
completed a sync every day since, so the inode must have been replaced
soon afterwards.

## Scope: both machines, not zbook-only

The defect is in the shared script, so it applies to any machine that
runs it. Per the network notes only zbook-ubuntu and amd-tower-ubuntu
do.

- **zbook** hit it today and was blocked until cleared by hand.
- **amd-tower** demonstrably leaked on 6 September and still carries the
  orphaned descriptor. Its lock path is currently free, and it has
  completed a sync every day from 1 to 14 September.

How long a leak blocks a machine is not deterministic. It lasts until
the next git operation replaces the lock file, which could be seconds or
days.

## Is anything losing data right now? No

Nothing is lost, and nothing is being lost as this is filed.

- The memory store is append-only, and captures are committed locally
  before they are pushed. A blocked sync delays propagation; it does not
  discard records.
- The two stores had genuinely diverged: 6 records only on zbook,
  7 only on amd-tower. All were present on one machine or the other.
- They were reconciled at 13:39 today, verified by comparing per-line
  hashes as sets: 44,996 records on each, zero on either side alone.
  amd-tower has since grown to 45,033 through normal capture.

The real exposure is **silent propagation delay**. A machine can stop
syncing for days whilst reporting benign contention, so recall on either
machine quietly misses the other's work. A secondary exposure is that
the whole sync body is skipped when the lock is refused, including the
append-only push of `~/cc-archives/` to the canonical store on
rpi-server. Transcripts stop reaching canonical for as long as the block
lasts.

## What was already done

Applied on zbook this afternoon, so it is working now:

1. Unmounted `~/mnt/rpi-shares`, which released the inherited descriptor.
2. Remounted with `setsid`, outside the sync's process tree, so nothing
   inherits the lock.
3. Confirmed the lock path has no holder and that `daily-sync.sh
   --dry-run` completes with exit 0.
4. Reconciled the two memory stores, as above.

Nothing in the repository was changed. No fix has been applied.

**Note:** zbook went off the network at about 13:40, so its side cannot
be re-checked from amd-tower until it is back.

## Suggested fix

1. **Stop the daemon inheriting the lock.** Close descriptor 9 for that
   one invocation, by adding `9>&-` to the `sshfs` command at line 3397.
   Worth auditing for any other child that outlives the script; `sshfs`
   is the only one at present.
2. **Untrack the lock file** and add it to the submodule's ignore rules.
   A lock belongs to a machine, not to shared history. Do this second:
   it is what has been masking defect 1, so removing it alone would make
   the leak permanent rather than intermittent.
3. **Make a refused lock legible.** When the flock fails, check whether a
   `daily-sync.sh` process is genuinely running. If none is, say so
   loudly instead of reporting benign contention. The silence is what
   made this costly, more than the leak itself.

The ordering matters. Fix 1 before fix 2, or a leaked lock will never
clear by itself.


---

## Disposition (this session, 2026-09-14)

**Fix 1 — APPLIED.** `9>&-` added to the sshfs invocation with a comment
explaining the open-file-description semantics. `bash -n` passes. This is the
ordering-critical one: it stops new leaks, and it is safe on its own because the
tracked lock file still provides the accidental escape hatch that has been
masking the defect.

**Fix 2 — NOT APPLIED, deliberately.** Untracking `logs/daily-sync.lock`
removes that escape hatch, so it must land *after* fix 1 has been on every
machine that runs the script. **zbook is offline with a failed motherboard and
cannot pull**, so doing it tonight would leave zbook with the old script and no
escape hatch — precisely the "permanent rather than intermittent" case the
report warns about. **Do it when zbook is back and has pulled fix 1.**

**Fix 3 — NOT APPLIED, needs a small design decision.** Making a refused lock
legible means distinguishing a real concurrent `daily-sync.sh` from an orphaned
holder. The obvious check is whether any live process holds the lock path, but
it must not turn genuine contention into a false alarm. **Shawn's call on how
loud "loudly" should be** — a gate line in the session-start digest is the
natural home, since that is where the other infra gates already report.

⚠ **The silence is the expensive part, not the leak.** Both machines reported
healthy syncs while diverging. Fix 3 is the one that would have caught this in a
day rather than eight.
