---
title: "Sol-in-Codex — integration plan"
tags: [planning, infrastructure, multi-agent, gpt-hub]
created: 2026-08-20
updated: 2026-08-20
status: draft — for Sol's review, then Shawn's ruling
---

# Sol-in-Codex — integration plan

**Purpose.** Make **Sol** (GPT, running in OpenAI Codex) a first-class agent in
Shawn's infrastructure, with its own home base, its own voice in the record, and
read access to the shared memory system — without putting the memory store or
the personal-assistant repo at risk.

**Driver, stated plainly:** Shawn is exhausting his weekly Claude Max quota.
This is a division-of-labour change first and a plumbing change second. The
plumbing exists to make the division safe.

**Audience.** Drafted by Claude for **Sol to review**. §8 is a list of questions
only Sol can answer; the design below is provisional wherever it depends on
them.

---

## 1. Decisions already made (Shawn, 2026-08-20)

These are settled and the rest of the document assumes them.

1. **`personal-assistant` stays Claude-only.** Shawn works with Claude there on
   standups, tracking, recap, weekly review, and retro. **Sol does not commit to
   that repo.**
2. **`gpt-hub` is Sol's home base and coordination surface** — worktrees, scratch
   space, cross-repo scripts, and Sol's own wiki artefacts.
3. **Sol works directly in other repositories where the work is**, not by proxy
   through the hub.
4. **Continuity is shared per repository, tagged by agent** — not a separate
   continuity file per agent (see §4).
5. **Observations are separate per voice**, in both directions (see §4).
6. **Sol gets its own git worktrees.** Sharing a checkout with Claude is
   prohibited, not merely discouraged (see §2).

---

## 2. ⭐ The isolation argument, and why it is not theoretical

**On 2026-08-20 this system lost 41 memory records and did not notice.** Two
`daily-sync.sh` runs overlapped on one working tree: the first stashed
uncommitted `memories.jsonl` appends at 10:20:34, was killed before it could pop
(it runs as a Claude Code SessionStart hook child with a 90 s timeout, and a
killed shell does not run its `EXIT` trap), and a second run started three
seconds later onto the now-clean tree. 38 records survived only in PostgreSQL;
3 more, from an earlier instance on 2026-07-18, survived only in a stash and had
been invisible for a month.

Anchors: recovery commits `data` **108d044** and **43fcd15**; crash-safety fix
and drift detector, parent **3ad6fa6**; detector at
`scripts/check-memory-drift.py`.

**That was two runs of one script.** `CLAUDE.md` already documents the more
general hazard — concurrent sessions share one checkout, so `git add <shared-file>`
sweeps another session's pending edits — and names git worktrees as the escape
hatch for genuinely simultaneous infrastructure work.

**A second agent is not occasionally simultaneous. It is permanently
simultaneous.** So the escape hatch becomes the default:

```bash
git worktree add ../<repo>-sol -b sol/<workstream>
# work + commit on the branch, then PR/merge
git worktree remove ../<repo>-sol
```

A separate directory is a separate index and HEAD, which makes the sweep
*structurally* impossible rather than merely discouraged. The cost is merge
overhead on shared documents. That is the correct trade against silent data loss.

---

## 3. ⭐⭐ Architecture: the memory store is an API, not a repository

**Shawn's "personal-assistant is Claude-only" constraint produces a better design
than the one originally proposed, and it is worth stating explicitly because it
is the load-bearing idea in this document.**

- Sol **never touches the `personal-assistant` repository** — not the JSONL, not
  the archives, not the sync scripts.
- Sol reaches memory **only through the MCP server** (`scripts/memory_mcp.py`).

**This enforces by construction the rule that would otherwise be a matter of
discipline:** `memories.jsonl` is append-only and safe under concurrent writers
*only if every write serialises through one path*. Two agents appending to the
file directly is the corruption class that was just repaired. Making MCP the
sole interface means Sol *cannot* violate that rule, rather than being asked not
to.

```text
┌─────────────────────────┐        ┌──────────────────────────────┐
│ Claude Code             │        │ Sol (Codex)                  │
│ ~/personal-assistant    │        │ ~/gpt-hub  +  repo worktrees │
│ direct file access      │        │ NO access to personal-assistant│
└───────────┬─────────────┘        └───────────────┬──────────────┘
            │ hooks + files                        │ MCP tools only
            ▼                                      ▼
      ┌──────────────────────────────────────────────────┐
      │ memory store  —  JSONL canonical, PG derived      │
      │ single serialising write path                     │
      └──────────────────────────────────────────────────┘
```

### Current state of the MCP server (verified 2026-08-20)

| | |
|---|---|
| File | `scripts/memory_mcp.py` (last modified 21 June 2026) |
| Transport | **stdio only** — `mcp.run()` with no transport argument |
| Tools | 6, **all read-only**: `search_memories`, `semantic_search`, `search_sessions`, `get_memory`, `list_recent`, `memory_statistics` |
| Tests | `tests/test_memory_mcp.py` — **44 passing** |
| Registration | **none** — no MCP servers are registered in `~/.claude.json` |

**⇒ Reads are nearly free to enable.** Registration is one command and the
server already works.

**⇒ Writes are the hard half, and are already scoped in the backlog.** The row
*"MCP server V2 — write tools"* specifies `store_memory`, `update_memory`,
`delete_memory`, and names its own prerequisite: extracting `memory_lib.py` from
`hooks/extraction-hook.py`. **Its stated trigger — "capturing memories from
non-Code Claude" — has effectively fired**, with Sol standing where Cowork was
imagined.

**⚠ One behavioural asymmetry to design for rather than paper over:** Claude's
memories are captured automatically by a Claude Code hook
(`hooks/extraction-hook.py`, wired in `~/.claude/settings.json`). **Sol gets no
such hook.** Unless Codex exposes an equivalent lifecycle event (§8 Q5), Sol must
capture memories by explicit call — which means fewer, more deliberate memories,
and that is a difference in the record's texture, not just its plumbing.

**⚠ Transport may need to change sooner than expected.** stdio requires the
client to spawn the server as a local subprocess. If Codex runs sandboxed or
containerised (§8 Q2), stdio will not reach and the backlog row *"Migrate memory
MCP to rpi-server (HTTP, always-on)"* becomes a prerequisite rather than a
someday item. Plan: `wiki/planning/rpi-server-mcp-migration.md`.

---

## 4. The record: what is shared, what is separate

**Principle: shared for *what is true and what happened*; separate for *what I
noticed about how we work*.**

### Continuity — shared per repository, tagged by agent

One `wiki/continuity.md` per repository, written by whichever agent worked
there. **Not one file per agent.** A handoff surface that only records half the
work is not a handoff surface — the first time Sol needs to know why a decision
was reversed, it must not be reading a file that does not say.

The existing session-log convention already tags by workstream:

```markdown
### 2026-08-20 (Thu, latest PA) — SESSION CLOSE …
```

**Extend the tag to name the agent:**

```markdown
### 2026-08-20 (Thu, latest MR/claude) — …
### 2026-08-21 (Fri, latest MR/sol) — …
```

`personal-assistant`'s own continuity stays Claude-only as a *consequence* of
decision 1, not as a separate rule.

### Observations — four registers, one per voice per direction

`personal-assistant/wiki/` already carries `claude-observations.md`
(Claude-owned, about working with Shawn) and `user-observations.md` (Shawn's
observations of Claude). **`gpt-hub/wiki/` mirrors it exactly:**

| Register | Owner | Subject | Location |
|---|---|---|---|
| `claude-observations.md` | Claude | working with Shawn | `personal-assistant/wiki/` (exists) |
| `user-observations.md` | Shawn | Claude | `personal-assistant/wiki/` (exists) |
| **`sol-observations.md`** | **Sol** | **working with Shawn** | **`gpt-hub/wiki/` (new)** |
| **`user-observations.md`** | **Shawn** | **Sol** | **`gpt-hub/wiki/` (new)** |

Same filenames in both repos, disambiguated by location — which is what the PA
wiki index already prescribes: *"Every project gets its own `wiki/`."*

### Working notes

Repo-local `wiki/working-notes.md` stays shared, one numbered Obs series per
repository, with the author named in each entry. Two parallel numbering schemes
in one repository would make cross-references ambiguous.

---

## 5. Instruction files: compose `AGENTS.md`, never hand-maintain it

There is currently **no `AGENTS.md` in `personal-assistant`** (the only one on
disk is `~/Code/FAIMS3/AGENTS.md`).

`scripts/compose-global-claude-md.sh` already builds `~/.claude/CLAUDE.md` from
`global-claude-md/shared.md` (public) plus `data/global-claude-md/local.md`
(private). **Extend it to emit both files from the same sources**, with a thin
per-agent overlay:

```text
shared.md ──┬── + claude-overlay.md + local.md ──> ~/.claude/CLAUDE.md
            └── + sol-overlay.md    + local.md ──> AGENTS.md
```

- **Shared:** UK/Australian English, Oxford comma; anti-confabulation (read and
  write sides); file naming and organisation; git conventions; documentation
  standards; checklist conventions.
- **Claude-only overlay:** subagent model policy; Skill-tool usage; the PA task
  system.
- **Sol-only overlay:** worktree requirement; MCP-only memory access; the
  repository allow-list (§7); commit trailer (§6).

**Why this matters more than it looks.** Two hand-maintained instruction files
drift, and drift in instruction files is not hypothetical here — it happened
twice on 2026-08-20 alone. `FOCUS.md`'s Slot 1 heading was three days stale, so
the session-start hook announced the wrong slot every morning; and two backlog
rows cite `planning/…` for documents that have lived at `wiki/planning/…` since
May. **A prescriptive document is a pointer, not an authority.** Generating both
files from one source removes the failure mode instead of managing it.

---

## 6. Attribution

Sol's commits carry their own trailer, mirroring Claude's:

```text
Co-Authored-By: Sol (GPT via Codex) <...>
```

Plus the workstream tag already required by `CLAUDE.md` in commit subjects.
`git log --author` / `--grep` should be able to answer *"what did Sol change?"*
without guesswork. **Exact identity string is Sol's to confirm — §8 Q6.**

---

## 7. Division of labour, and the repository allow-list

**This is the point of the exercise; the plumbing only makes it safe.** Shawn's
existing subagent model policy already encodes the principle — mechanical work
drops to a cheaper tier, frontier reasoning stays where it is. **This extends
that policy across vendors rather than inventing a new one.**

**Send to Sol:** file sweeps and searches; extraction and reformatting;
documentation generation; test writing; mechanical migrations; cross-repo
consistency passes; anything high-volume and verifiable.

**Keep with Claude:** the standup's confrontation; multi-document synthesis
where being confidently wrong is expensive; adversarial verification; the
judgement calls.

**Repository allow-list — proposed, for Shawn's ruling:**

| Repo | Sol | Note |
|---|---|---|
| `gpt-hub` | ✅ owner | home base |
| `map-reader-llm` | ✅ worktree | solo repo |
| `fieldmark-docs-staging` | ✅ worktree | solo repo |
| `llm-reproducibility` | ✅ worktree | solo repo |
| `personal-assistant` | ❌ **never** | Claude-only (decision 1); memory via MCP only |
| `FAIMS3` | ❌ | collaborative, branch+PR gated, has its own `AGENTS.md` |
| `paper-b`, `LLM-History-Paper` | ❌ default | shared with Brian; collaborator presence is the gate |

---

## 8. ⭐ Questions for Sol

**The design above is provisional wherever it depends on these. Please answer
concretely — "it depends" is less useful here than a wrong-but-checkable
answer.**

**Q1 — MCP support.** Does Codex support MCP servers? Which transports —
stdio, streamable HTTP, SSE? Where does server configuration live, and in what
format? Can it be scoped per project?

**Q2 — Sandbox and filesystem.** Does Sol run containerised or directly on the
host? What can it read and write? Can it spawn subprocesses (needed for a stdio
MCP server)? Can it reach the LAN — specifically `rpi-server` at
`192.168.1.100` — if the memory server moves to HTTP?

**Q3 — `AGENTS.md` semantics.** Does Codex read directory-scoped/nested
`AGENTS.md` files the way Claude Code reads nested `CLAUDE.md`? What is the
precedence order when several apply? Is there a practical size limit we should
compose against?

**Q4 — Git.** Can Sol run `git` directly, including `worktree`? Does it hold
push credentials, or does a human push? Any constraint that would make the
worktree convention in §2 impractical?

**Q5 — Lifecycle events.** Does Codex expose hooks or events at session
start/stop, comparable to Claude Code's `Stop` hook? This decides whether Sol's
memory capture can be automatic or must be an explicit call (§3).

**Q6 — Identity.** What name and email should Sol commit and be attributed as?

**Q7 — Model and quota.** Which model, and what does the quota look like
(per-day, per-week, token or request based)? The §7 split should be tuned to the
real constraint, not a guessed one.

**Q8 — Slash commands / skills.** Does Codex have an equivalent to Claude Code's
skills and slash commands? Several PA workflows (`/recap`, `/observe`,
`/handoff`) are skill-shaped, and knowing whether they can be ported decides
whether Sol's rituals are automated or manual.

**Q9 — Anything above that is wrong.** This was written by an agent that has not
used Codex. **Please push back on any assumption that does not survive contact
with how you actually run.**

---

## 9. Questions for Shawn

1. **Where does `gpt-hub` live** — GitHub under `saross`, public or private?
   Does it need a private `data/` submodule like PA has, or is nothing in it
   sensitive?
2. **Does Sol get memory *write* access at all**, or is read-only the durable
   answer? Read-only is available almost immediately; writes need `memory_lib.py`
   extracted first.
3. **Ratify the repository allow-list in §7.**
4. **Does Sol run its own daily-sync equivalent?** If it commits to repos on this
   machine, something has to push. ⚠ **Note that the crash-safety work of
   2026-08-20 is specific to `daily-sync.sh`; a second sync mechanism would need
   the same treatment, and is a good reason to have Sol push directly instead.**

---

## 10. Sequencing

**Steps 1–3 are roughly a session and deliver most of the value.**

| # | Step | Depends on |
|---|---|---|
| 1 | `AGENTS.md` composition; worktree convention; commit trailer | Q3, Q4, Q6 |
| 2 | Register `memory_mcp.py` for Sol, **read-only** | Q1, Q2 |
| 3 | Create `gpt-hub` + `wiki/{continuity,sol-observations,user-observations}.md`; adopt agent-tagged continuity headers | Shawn Q1 |
| 4 | Extract `memory_lib.py`; add MCP write tools | Shawn Q2 |
| 5 | HTTP transport on rpi-server | **only if Q2 says stdio cannot reach** |

---

## Anchors

`scripts/memory_mcp.py` · `tests/test_memory_mcp.py` (44 tests) ·
`scripts/check-memory-drift.py` · `scripts/daily-sync.sh` ·
`scripts/compose-global-claude-md.sh` · `hooks/extraction-hook.py` ·
`wiki/planning/rpi-server-mcp-migration.md` ·
`wiki/planning/mcp-server-v2-write-tools.md` ·
`tasks/backlog.md` rows *"Migrate memory MCP to rpi-server (HTTP, always-on)"*,
*"MCP server V2 — write tools"*, *"MCP server V2 — session search tools"* ·
commits `3ad6fa6` (parent), `108d044` / `43fcd15` (data).
