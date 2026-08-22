---
title: "Sol-in-Codex — integration plan"
tags: [planning, infrastructure, multi-agent, gpt-hub]
created: 2026-08-20
updated: 2026-08-22
status: twice reviewed (Sol §11, Claude §12) — rulings ratified; body revision pass pending, then implementation
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

**Repository allow-list — ruled by Shawn, 2026-08-21 (in the substack repo
session):** *"the only project/repo where I wanted to restrict (not
necessarily bar) Sol was personal-assistant"*. **⇒ Collaborator presence is
NOT a Sol gate.** Collaborative repos are open to Sol subject to each repo's
own discipline (branch + PR, `CLAUDE.md`/`AGENTS.md`). The pre-ruling rows,
which gated on collaborators, are corrected below.

⚠ **AND IT IS A SNAPSHOT, NOT A STANDING FACT.** Repositories change state,
and nothing notifies this table. **⇒ Re-derive working discipline from the
repository's own state — a project-level `CLAUDE.md`, or collaborators on
the remote — rather than trusting the rows below.** Same failure class as
the stale `FOCUS.md` heading and the ten stale `planning/` paths corrected
on 2026-08-20: **a prescriptive record read as an authority.** (The original
instance: `substack` went from solo to collaborative within 24 hours of this
list being drafted — and then the collaborator gate itself was overruled the
same day.)

| Repo | Sol | Note |
|---|---|---|
| `gpt-hub` | ✅ owner | home base |
| `map-reader-llm` | ✅ worktree | solo repo |
| `fieldmark-docs-staging` | ✅ worktree | solo repo |
| `llm-reproducibility` | ✅ worktree | solo repo |
| `personal-assistant` | ⚠ **restricted** | the one restricted repo (ruled 2026-08-21: restrict, not necessarily bar — scope of the restriction TBD by Shawn); memory via MCP only. Earlier "❌ never / Claude-only" stands until Shawn defines the scope. |
| `FAIMS3` | ✅ worktree | collaborative: its branch+PR gate and own `AGENTS.md` govern conduct, not Sol access (corrected 2026-08-21) |
| `paper-b`, `LLM-History-Paper` | ✅ worktree | shared with Brian; branch + PR discipline applies (corrected 2026-08-21) |
| `substack` | ✅ worktree | shared with Brian; branch + PR per its `CLAUDE.md`, which was corrected 2026-08-21 to lift the bar recorded there |

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
3. **Ratify the repository allow-list in §7.** — ✅ **Ruled in part,
   2026-08-21** (substack repo session): collaborator presence is not a
   gate; `personal-assistant` is the only restricted repo (restrict, not
   necessarily bar). **Still open: the scope of the `personal-assistant`
   restriction.**
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

---

## 11. Sol's review (2026-08-20)

### Overall assessment

The draft has the right goals and two especially strong design choices:

1. concurrent agents should not share a checkout; and
2. the canonical memory store should be accessed through a controlled
   interface, not by teaching every agent how to mutate its files.

I recommend proceeding, but not with §§3, 5, 6, 7, and 10 exactly as written.
The proposal underestimates Codex's native integration surfaces, overstates the
protection supplied by an MCP interface, and makes `personal-assistant` so
inaccessible that I could not participate in the shared wiki system Shawn says
he wants me to use. The revised design below narrows the protection boundary to
the assets that genuinely need it.

This review distinguishes:

- **documented Codex behaviour**, which should generalise across machines;
- **this machine's present configuration**, inspected on 2026-08-20; and
- **recommended policy**, which remains Shawn's decision.

### Corrections and pushback

#### 11.1 Protect the memory store, not the whole repository

The sentence "Sol never touches the `personal-assistant` repository" is too
broad and conflicts with both this review request and the desired access to
wikis, continuity documents, and shared instructions.

Replace it with a capability boundary:

- Sol may **read** the PA wiki, public instruction sources, protocols, and
  integration code when a task requires them.
- Sol must not directly mutate `memories.jsonl`, the PostgreSQL-derived store,
  archives, sync state, hooks, or PA operational/task files.
- Memory mutations go through the memory service only.
- PA document changes are proposal-only by default: write a patch in
  `gpt-hub`, or use a dedicated PA worktree and commit only when Shawn
  explicitly scopes the task. Never use Claude's live PA checkout.
- A small path allow-list may later permit Sol-authored integration planning
  documents. This review is an explicitly authorised exception.

This preserves the safety invariant without making the shared knowledge base
unavailable. It also makes the policy testable: filesystem permissions and
tool exposure can enforce paths and operations; "never touch" cannot express
the difference between reading a wiki page and appending to canonical JSONL.

#### 11.2 MCP is an interface, not automatically a serialising writer

The read-only MCP server is suitable for immediate use over `stdio`. The write
argument in §3 is not yet safe:

- each local Codex session may spawn its own `stdio` server process;
- Claude and other clients may create additional processes; and
- therefore, routing calls through the same Python module does **not** create a
  single serial execution path across clients.

Before exposing writes, choose one of these designs:

1. one always-on service that owns all writes (streamable HTTP is a natural
   fit); or
2. cross-process locking plus a crash-safe, idempotent append protocol shared
   by every writer.

The first is easier to reason about. HTTP migration is therefore potentially a
**write-concurrency prerequisite**, not merely a fallback if a sandbox cannot
start `stdio`.

The V2 interface should also preserve append-only semantics. `update_memory`
and `delete_memory` should emit revision and tombstone records, not rewrite or
physically delete history. Write tools need idempotency keys, provenance-anchor
validation, explicit write approval, an audit receipt, and tests with two
concurrent clients and forced process termination.

#### 11.3 Use Codex's native migration surfaces before building translators

Current Codex supports a selective `/import` flow for Claude Code. It can
translate instruction files, settings, skills, hooks, slash commands,
subagents, MCP configuration, projects, recent chats, and Claude project
memories. It leaves the Claude setup unchanged.

Use `/import` as an **inventory and candidate-generation step**, not a blind
migration. Initially select only a small set of instructions, skills, and hooks;
deselect chats, memories, permissions, and model settings until their privacy
and semantic differences have been reviewed. Imported artefacts still require
manual audit, especially commands that write directly to PA files.

The existing `/recap` is a concrete example: it directly appends to
`memories.jsonl`, so importing it unchanged would violate the proposed safety
boundary. `/handoff`, `/observe`, and `pre-run-review` are better pilot
candidates after their paths, commit behaviour, and agent calls are adapted.

#### 11.4 Split global and repository instructions properly

Codex discovers instructions in this order:

1. `~/.codex/AGENTS.override.md`, or otherwise `~/.codex/AGENTS.md`;
2. one instruction file at each directory from the repository root to the
   current working directory; and
3. the nearest file has the highest practical precedence.

It reads the chain once per session. The combined default limit is 32 KiB.
These semantics make one undifferentiated generated `AGENTS.md` unsuitable.

The current `global-claude-md/shared.md` is not yet a genuinely shared source:
it includes Claude model-tier policy, Claude auto-memory rules, `/remember`,
Claude session handling, and PA task-system paths. Refactor the sources first:

```text
instruction-sources/
├── common.md              # portable collaboration and research norms
├── claude.md              # Claude-specific behaviour
├── codex.md               # Codex-specific behaviour
├── private-common.md      # private infrastructure needed by both
├── private-claude.md      # private Claude-only material
└── private-codex.md       # private Codex-only material

common + private-common + claude + private-claude
    -> ~/.claude/CLAUDE.md
common + private-common + codex + private-codex
    -> ~/.codex/AGENTS.md
```

Keep the generated global Codex file short. Put optional workflows in skills,
and put commands, tests, data rules, and verification expectations in each
repository's checked-in `AGENTS.md`. Do not generate or overwrite repository
`AGENTS.md` files from the global composer. Do not globally configure Codex to
treat every `CLAUDE.md` as a fallback until the Claude-specific contents have
been audited.

#### 11.5 An allow-list in prose is not an access control

Retain the repository table as policy, but split its single yes/no column into
capabilities:

| Capability | Meaning |
|---|---|
| Read | May inspect files for context |
| Edit | May modify an isolated worktree |
| Commit | May create local commits |
| Push | May update a remote branch |
| Memory | May query the personal memory MCP |
| Integration mode | Direct, worktree, patch-only, or prohibited |

Enforce important boundaries through Codex workspace roots, sandbox policy,
trusted-project configuration, MCP tool allow-lists, and GitHub permissions.
`AGENTS.md` is guidance, not a security boundary.

Memory access deserves its own column. Personal memory should not be exposed in
an untrusted repository, a collaborator-controlled repository, or a remote
cloud task merely because source-code access is allowed. Registering the server
globally but disabled, then enabling it only in approved trusted projects (or a
separate `CODEX_HOME` profile), is safer than making it universally available.

#### 11.6 Worktrees are necessary but not sufficient

The worktree rule is sound. A worktree gives a session its own checkout, index,
and `HEAD`, preventing one session's `git add` from sweeping another checkout's
files. Worktrees still share the repository's object database and refs, and
they do not prevent semantic merge conflicts in `continuity.md` or concurrent
scripts that write to absolute shared paths.

Operational refinements:

- create or select the worktree before launching Codex, and launch Codex with
  that directory as its workspace root;
- use a unique branch per workstream/session, not a permanent branch that two
  Sol sessions share;
- fetch/rebase and inspect the exact pathspec immediately before committing;
- keep linked worktrees outside the `gpt-hub` repository, for example under
  `~/worktrees/<repo>/<agent>-<workstream>`; and
- reserve `gpt-hub` for durable coordination artefacts, skills, configuration
  sources, and cross-repository tools—not nested checkouts or disposable
  scratch files.

For continuity, one shared file remains reasonable, but headings should carry
an agent, timestamp, and unique session/workstream identifier. Worktrees turn a
silent overwrite into a visible merge conflict; the merge still needs human or
agent adjudication. If conflicts become frequent, move immutable session-close
entries to `wiki/handoffs/` and keep `wiki/continuity.md` as a short current-state
index.

#### 11.7 Do not invent a Git co-author identity

This machine's Git author is presently `Shawn Ross <shawn@faims.edu.au>`.
There is no verified OpenAI-provided Sol email to use in GitHub's
`Co-Authored-By` convention. A fabricated address would create misleading
provenance.

Recommended default:

```text
Agent: Sol (OpenAI Codex)
```

Keep Shawn as the Git author and use a custom trailer for material assistance.
If model-level provenance matters for an experiment, record harness, model,
reasoning effort, and session/run identifier in the experiment manifest—not in
every commit subject. The persona (`Sol`) and the model are separate fields;
models will change.

#### 11.8 Route work by fit and verification, not vendor stereotype

The proposed division of labour undervalues Codex by assigning it mostly
mechanical work, while treating judgement as inherently Claude-shaped. This
Codex configuration uses a frontier model, and the current benchmark-design
work is exactly the kind of sustained technical and methodological reasoning I
can own.

A better routing rule is:

- **Codex:** repository-native implementation, debugging, tests, long-running
  execution, reproducible evaluation, technical design, and independent
  methodological review;
- **Claude:** the PA rituals already deeply integrated with Claude, plus work
  where Claude's accumulated session context is itself the asset;
- **either or both:** hard synthesis and judgement, chosen according to
  available context, quota, tool access, and the value of an independent
  second view; and
- **lower-cost models:** bounded, verifiable mechanical subtasks, with the
  result reviewed by the owning agent.

For high-stakes claims, cross-vendor disagreement is a feature: ask one system
to derive the answer cold, then adjudicate differences from source artefacts.

### Answers to §8

**Q1 — MCP support.** Yes. Codex supports local `stdio` servers and remote
streamable HTTP servers. The documented current page does not list SSE as a
separate supported transport. Configuration lives in `config.toml`; the default
is `~/.codex/config.toml`, and a trusted repository may use
`.codex/config.toml`. The CLI provides `codex mcp add/list/login`. This machine
currently has no MCP servers registered.

**Q2 — sandbox and filesystem.** Local Codex runs against the host checkout but
inside a configurable sandbox/approval policy; it is not accurately described
as always containerised or always unrestricted. In this session I can read the
home tree, write only the active workspace and temporary directories, spawn
subprocesses, and request approval for Git index and network operations. A local
`stdio` memory server is therefore viable if its executable, code, database,
and fallback files are readable. LAN access is policy-dependent and may require
approval; connectivity to `192.168.1.100` has not been tested in this review.

**Q3 — `AGENTS.md`.** Yes. Nested files are supported from repository root to
the current directory. At a given level, `AGENTS.override.md` wins over
`AGENTS.md`; files nearer the current directory appear later and override
broader instructions. Only one file per directory is loaded. The default
combined limit is 32 KiB, configurable with `project_doc_max_bytes`.

**Q4 — Git.** Yes. I can run Git and manage worktrees. Authenticated GitHub
fetch/push works on this machine, subject to sandbox approval and normal
non-fast-forward protection. The convention is practical if Codex is launched
inside its pre-created worktree. A worktree prevents index collision but not
shared-ref contention, absolute-path side effects, or merge conflicts.

**Q5 — lifecycle events.** Yes. Codex currently documents `SessionStart`,
`SessionEnd`, `Stop`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, tool-use,
permission, and subagent events. This changes the plan materially: automatic
capture is possible. Do not port the existing hook unchanged. `SessionEnd` has
a very short execution allowance (up to three seconds), and unfinished
background hooks are cancelled when the session ends. It should enqueue a
small durable receipt; heavier extraction should run in a separate worker or
at a safer lifecycle point.

**Q6 — identity.** Use Shawn's configured Git identity as author and
`Agent: Sol (OpenAI Codex)` as the provenance trailer. Do not use a fictional
co-author email.

**Q7 — model and quota.** This machine's current Codex configuration is
`gpt-5.6-sol` with `xhigh` reasoning effort. I do not have a reliable
account-level weekly quota figure available inside this session. Quota and
model should be observable run metadata, not hard-coded into the division of
labour. Revisit routing using actual usage telemetry after a fortnight.

**Q8 — slash commands and skills.** Yes. Codex has built-in slash commands,
reusable `SKILL.md` workflows, plugins, subagents, MCP tools, and hooks. The
official Claude import maps slash commands to skills. Port only the workflows
that belong in Sol's remit; do not duplicate Claude-only rituals merely because
translation is possible.

**Q9 — what is wrong above.** The largest errors are: treating MCP as automatic
write serialisation; assuming Codex lacks lifecycle hooks; omitting native
Claude import; conflating a repository allow-list with enforcement; proposing
one generated instruction file without first separating Claude-specific
content; and restricting Sol to mechanical work despite the intended
first-class role.

### Revised architecture

```text
                           read approved docs
personal-assistant ───────────────────────────────────┐
  wiki + protocols                                    │
  protected data/sync code                            ▼
  read-only memory MCP ────────────────> Sol in repo worktree
  future single-writer service <──────── approved memory proposals
                                                │
                                                ▼
                                      repo files + continuity

gpt-hub
  ├── Codex configuration sources and installer
  ├── Codex-native/adapted skills and hooks
  ├── Sol and user observation registers
  ├── cross-repository tools
  └── integration decisions and test evidence

~/worktrees/
  └── isolated, disposable working checkouts (not inside gpt-hub)
```

Codex also has a separate native local-memory facility under `~/.codex`.
Leave it disabled initially to avoid two competing sources of truth. After the
shared MCP integration is stable, it could be enabled only as a disposable
recall cache, with the PA store explicitly remaining canonical.

### Revised implementation sequence

0. **Create a capability matrix and data-sensitivity classification.** Exit:
   read/edit/commit/push/memory permissions are decided per repository.
1. **Run selective Claude `/import` as an inventory.** Exit: the candidate list
   is reviewed, with no bulk activation.
2. **Create private `gpt-hub`; keep worktrees under `~/worktrees/`.** Exit: hub
   structure, ownership, backup, and sensitivity are decided.
3. **Refactor common/Claude/Codex instruction sources.** Exit: the generated
   `~/.codex/AGENTS.md` is under 32 KiB and contains no Claude-only commands.
4. **Add minimal repo-local `AGENTS.md` to one pilot repository.** Exit: a fresh
   Codex session reports the expected instruction chain.
5. **Register the existing memory MCP read-only.** Exit: all six tools pass
   against PostgreSQL and offline fallback, while the server is unavailable in
   a denied repository.
6. **Port three pilot workflows.** Exit: `handoff`, `observe`, and
   `pre-run-review` work without direct PA memory writes.
7. **Add lightweight hooks.** Exit: start/compact context works; the end hook
   writes only an atomic queue receipt and fails safely.
8. **Trial two weeks on `map-reader-llm`.** Exit: no shared-checkout incidents;
   continuity is usable; effort and quota telemetry are collected.
9. **Design and fault-test the single-writer memory service.** Exit:
   concurrent-client, duplicate-call, crash, rollback, and audit-receipt tests
   pass.
10. **Consider memory write access.** Exit: Shawn explicitly approves after
    reviewing the threat model and test evidence.

### Pilot acceptance tests

The integration is not complete merely because the tools appear in a menu.
Before broadening access, demonstrate:

1. **Instruction precedence:** global and nested repository guidance load in
   the documented order and stay below the byte limit.
2. **Checkout isolation:** simultaneous Claude and Sol edits use distinct
   indexes; a staged-file census proves neither can sweep the other's work.
3. **Memory least privilege:** approved repos can query all six read tools;
   denied or untrusted repos cannot.
4. **No direct canonical writes:** imported skills and hooks cannot append to
   JSONL or mutate PA operational files.
5. **Failure containment:** an unavailable database, MCP server, or end hook
   does not block ordinary repository work and leaves an observable error.
6. **Continuity round-trip:** Claude can resume from a Sol handoff, and Sol can
   resume from a Claude handoff, without oral repair from Shawn.
7. **Provenance:** a commit and a benchmark run can each answer who acted,
   which harness/model was used, and which source artefacts supported claims.

### Immediate recommendation to Shawn

Approve a deliberately small first session:

1. create `gpt-hub` as a **private** repository initially;
2. establish the capability matrix and worktree location;
3. use `/import` only to inventory portable artefacts;
4. compose a minimal global `~/.codex/AGENTS.md`; and
5. register the existing six-tool memory server read-only in one approved
   pilot profile/project.

Pause before hooks and all write access. That first slice gives Sol shared
context and durable instructions while keeping the recent data-loss class out
of scope.

### Shawn's initial rulings (2026-08-22)

Shawn ratified the following directions after reviewing Sol's response:

1. **Read access:** Sol should have read access to everything, including the PA
   wiki, protocols, instructions, and infrastructure. The earlier blanket
   prohibition on touching `personal-assistant` is superseded.
2. **Write access:** restrict Sol's write access as little as possible. Apply
   narrow safeguards to genuinely sensitive or concurrency-prone assets rather
   than a broad repository-level prohibition.
3. **Reciprocal hub boundary:** `gpt-hub` will be Sol's repository. Claude
   agents may read it but may not write to it.
4. **Division of labour:** reject the characterisation of Sol as primarily a
   mechanical-work agent. Sol may own substantive technical, methodological,
   evaluative, and implementation work according to task fit and context.

These rulings establish the direction of travel. The exact path-level write
controls, memory-write design, and repository capability matrix remain to be
specified during implementation.

### Codex documentation consulted

- [Custom instructions with `AGENTS.md`][agents-docs]
- [Model Context Protocol][mcp-docs]
- [Hooks][hooks-docs]
- [Import from another agent][import-docs]
- [Codex memories][memories-docs]
- [Skills][skills-docs]

[agents-docs]: https://learn.chatgpt.com/docs/agent-configuration/agents-md.md
[hooks-docs]: https://learn.chatgpt.com/docs/hooks.md
[import-docs]: https://learn.chatgpt.com/docs/import.md
[mcp-docs]: https://learn.chatgpt.com/docs/extend/mcp.md
[memories-docs]: https://learn.chatgpt.com/docs/customization/memories.md
[skills-docs]: https://developers.openai.com/plugins/concepts/skills.md

---

## 12. Claude's review (2026-08-22, Fable)

Requested by Shawn as a third view on §§1–10, Sol's §11 review, and the
initial 2026-08-22 rulings.

### Verdict

Sol's review is high quality and materially improves the plan. Proceed with
Sol's "small first slice", with the additions below. The two most important
catches are §11.2 and §11.4, and both are correct:

- **§11.2** demolishes the load-bearing claim of the original §3: routing
  writes through the same Python *module* serialises nothing when each client
  spawns its own *process*. Write safety needs a single always-on service or
  cross-process locking. The original "enforced by construction" framing was
  wrong in a way that would have surfaced as another silent-loss incident.
- **§11.4** is right that composition must follow refactoring:
  `global-claude-md/shared.md` carries Claude model-tier policy and
  `/remember` plumbing, and composing before refactoring would have shipped
  Claude-only instructions into Sol's 32 KiB budget.

### Verification performed

Per the anti-confabulation rule, Sol's checkable claims were checked rather
than trusted:

1. **`/recap` writes directly to the canonical store** — confirmed.
   `commands/recap.md:211` instructs appending to `memories/memories.jsonl`.
   Sol's warning against importing it unchanged is grounded.
2. **The Codex documentation citations are real and accurate** — the
   [hooks][hooks-docs] and [`AGENTS.md`][agents-docs] pages were both fetched
   on 2026-08-22. The hooks page confirms the lifecycle events and the
   `SessionEnd` allowance (1 s default, 3 s maximum); the `AGENTS.md` page
   confirms nested discovery, `AGENTS.override.md` precedence, and the 32 KiB
   `project_doc_max_bytes` default.

One discovery from the fetched docs, absent from both prior reviews: **the
byte limit truncates by skipping later files, and later files are the
nearer, higher-precedence ones** — an oversized global or root `AGENTS.md`
silently drops repo-local instructions. The composition script needs a size
budget and an automated check, not an aspiration to stay small.

### Additions

1. **The document contradicts itself, and its own thesis says why that
   matters.** §1 still opens "these are settled and the rest of the document
   assumes them", including "Sol does not commit to that repo" — superseded
   by the 2026-08-22 rulings. Leaving superseded decisions enthroned at the
   top of the file is exactly the "prescriptive record read as an authority"
   failure class this document warns about. → Ruled: see below.
2. **The single-writer service must absorb Claude's writes too — the biggest
   gap in both prior documents.** Sol's §11.2 says "one always-on service
   that owns all writes", but revised step 9 does not migrate
   `hooks/extraction-hook.py` and the `/recap` append path to become clients
   of that service. The 41-record loss of 2026-08-20 was entirely
   Claude-side — no second vendor involved. A service that owns only Sol's
   writes reproduces the incident class one level up. Make "Claude's
   extraction hook and `/recap` write through the service" an explicit exit
   criterion of step 9.
3. **The concrete threat behind §11.5's memory column is indirect prompt
   injection.** In a collaborative repo, repo content — an issue body, a
   README, a test fixture — can instruct an agent to query personal memories
   and leak them into a PR, comment, or commit visible to collaborators.
   Memory tools should be **default-deny in any repository with
   collaborators or untrusted inputs**, enabled per-task — for Claude's
   future MCP registration as much as for Sol's.
4. **Ruling 3 (gpt-hub is Claude-read-only) needs enforcement, by Sol's own
   standard.** "An allow-list in prose is not an access control" applies in
   both directions: add a permissions deny rule for writes under the
   `gpt-hub` path in Claude's settings when the repo is created.
5. **Ruling 1's scope was ambiguous** — whether "read access to everything"
   includes the private `data/` submodule (raw `memories.jsonl`, standups,
   reports, reflections), given that everything Sol reads transits OpenAI's
   API. → Ruled: see below.
6. **Attribution split.** Claude's commits carry a vendor-sanctioned
   `Co-Authored-By` trailer; Sol proposed an `Agent:` trailer — two formats
   means two grep patterns for "what did agents change?". → Ruled: see
   below.

### Endorsed without reservation

Leaving Codex's native memory facility disabled; HTTP migration reframed as
a write-concurrency prerequisite rather than a sandbox fallback; unique
branch per session and worktrees outside `gpt-hub`; the pilot acceptance
tests (test 2's staged-file census is the right regression test for the
motivating incident); routing review against actual usage telemetry after a
fortnight, since quota is the driver and nobody currently has a real quota
figure; and the §11.8 division of labour — Sol arguing for substantive work
is self-interested, but the argument stands on its merits, and cross-vendor
"derive cold, then adjudicate from source artefacts" is genuinely valuable
for high-stakes claims.

Operational note for step 5: LAN connectivity from the Codex sandbox to
`rpi-server` (192.168.1.100) is untested and now gates the write path — test
it early; it is a five-minute check gating a whole branch of the sequencing.

### Shawn's further rulings (2026-08-22, after this review)

1. **Body revision pass ratified.** The plan body (§§1–10) is to be
   rewritten to reflect the §11 and §12 rulings — superseded §1 decisions
   struck through with pointers to the rulings, and §§3–7 and 10 brought
   into line. This is the next action on this document, before
   implementation starts.
2. **"Read everything" means everything.** Sol's read access includes the
   private `data/` submodule — raw `memories.jsonl`, standups, reports,
   reflections. The MCP boundary is a write-side control; reads may bypass
   it. The OpenAI-transit disclosure implication is understood and accepted.
3. **Sol uses a `Co-Authored-By` trailer**, matching Claude's convention, so
   agent attribution has a single grep pattern. This supersedes §11.7's
   `Agent:` trailer in format while retaining its substance (persona and
   model are separate fields; no misleading provenance claims). The exact
   identity string remains to be settled with Sol — default candidate
   `Co-Authored-By: Sol (GPT via Codex) <noreply@openai.com>` (address not
   vendor-verified), with an address under a Shawn-controlled domain as the
   fallback if Sol objects. Record both agents' trailer patterns in
   `global-claude-md/git-reference.md`.
