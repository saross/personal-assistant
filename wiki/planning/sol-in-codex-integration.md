---
title: "Sol-in-Codex — integration plan"
tags: [planning, infrastructure, multi-agent, gpt-hub]
created: 2026-08-20
updated: 2026-08-22
status: approved for phased implementation
---

# Sol-in-Codex — integration plan

## Purpose and authority

Make **Sol** (GPT, running in OpenAI Codex) a first-class agent in Shawn's
infrastructure, with full participation in substantive work, durable continuity,
access to the shared memory and wiki systems, and its own agent-owned home.

The design has four goals:

1. preserve each agent's harness-specific configuration and operating rituals;
2. let both agents read the complete knowledge system and contribute broadly;
3. prevent concurrent sessions from silently sweeping or losing one another's
   work; and
4. use explicit, testable controls at genuinely risky boundaries rather than
   broad repository prohibitions.

Shawn's Claude quota was the immediate driver, but this is not a mechanical-work
offload. Work should be routed by context, tool fit, verification needs, and
available capacity. Sol may own substantive technical, methodological,
evaluative, research, and implementation work.

**Authority.** Sections 1–10 are the current plan. They integrate Shawn's
rulings and the Sol and Fable reviews of 2026-08-20–22. Earlier formulations
remain available through Git; superseded rules are not retained inline because
contradictory instructions are unsafe for humans and agents alike.

---

## 1. Ratified decisions

1. **Read access is broad and reciprocal.** Sol may read all of
   `personal-assistant`, including the private `data/` submodule. Claude may
   read all of `gpt-hub`. There are no secrets *between the agents*.
2. **Harness-specific files have one writer.** Sol does not edit Claude-specific
   configuration or instruction surfaces, including `CLAUDE.md`. Claude does
   not edit Codex-specific surfaces, including `AGENTS.md` and `.codex/`.
3. **The personal-assistant function remains Claude-owned.** Claude runs and
   updates standups, personal task tracking, time tracking, recaps, weekly
   reviews, retrospectives, and their operational records. Sol may read these
   and propose changes, but does not operate them.
4. **`gpt-hub` is Sol's home and agent-owned repository.** It holds Codex
   configuration sources, adapted skills and hooks, Sol's observations,
   cross-repository tools, and integration records. Claude has read and
   proposal access, but does not modify or commit to it.
5. **Ordinary project work is shared.** Both agents may edit code,
   documentation, research records, continuity, and working notes in project
   repositories, subject to the repository's own branch, review, and
   verification rules.
6. **Cross-agent work always uses isolated worktrees.** Claude and Sol do not
   work concurrently in one checkout; each cross-agent workstream gets its own
   checkout, index, `HEAD`, and branch. Same-agent concurrency is governed by
   the scoped rule in §3 (ruled 2026-08-22).
7. **Repository collaboration does not imply distrust.** Trust is based on
   stewardship and input provenance, not collaborator count. FAIMS is a trusted
   repository, while still requiring its normal branch-and-review discipline.
8. **Memory maintenance stays with Claude for now.** This is an expedient, not a
   permanent judgement about capability. Sol does not directly mutate the live
   memory corpus during the first integration phase.
9. **All future online memory writers converge on one write boundary.** The
   service must eventually absorb Claude's and Sol's write paths. Routing only
   Sol through it would not remove the existing concurrency class.
10. **Agent attribution uses one Git convention.** Sol uses a
    `Co-Authored-By` trailer with a Shawn-controlled email alias. No fabricated
    OpenAI address will be used.

---

## 2. Reciprocal ownership and capability model

### Terms

- **Read:** inspect and use as context. Read access does not mean automatic
  ingestion into every session.
- **Write:** edit, generate, overwrite, stage, commit, or run a command whose
  effect changes the surface.
- **Proposal-only:** read freely and prepare a patch or recommendation on an
  agent-owned surface, but let the owning agent or Shawn land it.
- **Shared:** either agent may edit in an isolated worktree, with ordinary Git
  review and exact-path staging.

### Claude-owned surfaces

Sol has read and proposal-only access to:

- global and repository-local `CLAUDE.md` and `.claude/`;
- Claude settings, hooks, agents, commands, skills, output styles, and
  Claude-specific instruction overlays;
- PA standups and personal task state under `standups/` and `tasks/`;
- time logs, work logs, weekly reviews, and retrospectives under `reports/`;
- PA session rituals and the code or command definitions that operate them;
- `claude-observations.md`; and
- live memory-maintenance operations during the initial integration phase.

Sol may identify defects and draft exact changes to these surfaces. The draft
lands in `gpt-hub`, a shared planning document, or the current conversation;
Claude or Shawn applies it.

### Sol-owned surfaces

Claude has read and proposal-only access to:

- global and repository-local `AGENTS.md` and `.codex/`;
- Codex configuration, hooks, skills, plugins, and agent definitions;
- all files in `gpt-hub`, including `sol-observations.md`; and
- scripts whose sole purpose is installing or operating Sol's environment.

Claude may review and propose exact changes. Sol or Shawn applies them.

### Shawn-owned or gated surfaces

- `user-observations.md` records Shawn's observations. Agents may draft
  labelled candidates using the relevant ritual, but Shawn decides their final
  status.
- Credentials, account settings, external publication, and destructive live
  operations always remain subject to Shawn's explicit authority.
- The exact Sol email alias is supplied by Shawn before the attribution rule is
  activated.

### Shared surfaces

Both agents may edit, in isolated worktrees:

- ordinary code, tests, documentation, and research artefacts in project
  repositories;
- project `wiki/continuity.md` and `wiki/working-notes.md`;
- agent-neutral integration plans and memory-service code when that build is
  explicitly in scope; and
- the planned portable common-instruction source described in §6.

Within `personal-assistant`, this means the repository is **not** globally
Claude-only. Its personal-assistant operations and Claude harness are
Claude-owned, while neutral planning, testing, and explicitly assigned
infrastructure work may be shared. Sol uses a dedicated PA worktree for any
authorised edit and never Claude's live checkout.

---

## 3. Isolation, trust, and enforcement

### Worktree rule

Use a unique branch and worktree per active agent workstream:

```bash
git worktree add ~/worktrees/<repo>/<agent>-<workstream> \
  -b <agent>/<workstream>
```

Launch the agent with that worktree as its workspace root. Keep worktrees
outside `gpt-hub` and outside the primary checkout. Remove them after the work
is integrated.

A worktree prevents one checkout's `git add` from sweeping another checkout's
files. It does not prevent shared-ref contention, absolute-path side effects,
or semantic merge conflicts. Before every commit:

1. fetch and check branch divergence;
2. inspect the complete worktree status;
3. stage explicit pathspecs;
4. verify the cached file census; and
5. use branch-and-review rules required by the repository.

### Scope of the worktree rule (ruled 2026-08-22)

- **Cross-agent (Claude × Sol): worktrees always.** Permanent simultaneity
  across two harnesses with no shared session awareness admits no exception.
- **Same-agent, project repositories: worktrees by default** for substantive
  parallel workstreams. They are cheap where no hooks or submodules are
  entangled.
- **Same-agent, `personal-assistant` hub: pathspec discipline remains the
  default**, per that repository's `CLAUDE.md`, with worktrees the escape
  hatch for genuinely simultaneous infrastructure work. The hub's value is
  ambient shared state — session hooks, the `data/` submodule, high-churn
  shared logs — which makes per-session worktrees expensive; and the
  index-sweep failure the discipline guards against is recoverable (a
  misattributed commit, preserved in history), unlike the stash and checkout
  classes, which have been separately fixed or banned.

Evidence threshold: a recurrence of an index sweep despite explicit-pathspec
commits reopens this ruling. This scoping also removes the apparent conflict
between this plan and the PA `CLAUDE.md` concurrent-sessions convention.

### Ownership guardrails

The reciprocal boundary should be made mechanically visible:

- Claude receives a settings-level deny rule for writes under `gpt-hub` and
  for Codex-owned instruction/configuration paths.
- Codex receives an equivalent path policy for Claude-owned PA surfaces and
  `CLAUDE.md`/`.claude/` files.
- Each agent's instruction file states the proposal route for a blocked path,
  so the control does not stop useful review.
- A small ownership-policy test exercises representative allowed and denied
  paths before rollout.

Because both harnesses run as Shawn's Unix user, harness rules are guardrails
against mistakes, not hard security against a malicious local process. That is
proportionate here: there are no secrets between the agents, and the objective
is clean ownership rather than adversarial isolation. Operating-system users,
read-only mounts, or separate credentials are deferred unless evidence shows
the lighter controls are inadequate.

### Ownership policy file (ruled 2026-08-23)

- The machine-readable ownership policy lives at
  `personal-assistant/global-agent-guidance/ownership.toml` — the
  agent-neutral shared-source directory that §6 designates. It encodes both
  agents' deny lists and is the single source both enforcement layers derive
  from.
- Changes to it always go branch + pull request, reviewed by the other party:
  Sol reviews Claude-authored changes and vice versa; Shawn may author,
  reviewed by either agent. On disagreement, the agents attempt consensus;
  anything unresolved goes to Shawn.
- Asymmetry: a change that **loosens** a boundary (expands a write surface,
  removes a deny) requires Shawn's sign-off even when both agents agree.
  Purely tightening or self-restricting changes may merge on other-party
  approval alone.
- The ownership-policy test **reads `ownership.toml`** and attempts the
  operations it declares denied, so the file is a checked source rather than
  a description that can drift from the machine-local enforcement (Claude's
  rules live in gitignored `settings.json`; Sol's in Codex configuration).
- This gate is behavioural — Git cannot branch-protect a single path in a
  direct-push repository — consistent with the guardrails stance above.
  Revisit if anyone is unhappy with it after a few weeks of operation.

### Trusted and untrusted contexts

**Trusted** means the repository and active inputs are maintained by known
people under understood review practices. It does not mean solo. FAIMS is
trusted even though it is collaborative.

**Untrusted** means unfamiliar repository content or externally controlled
inputs could contain instructions that should not inherit ambient access to
personal memory or PA files. Examples include a newly cloned unknown
repository, arbitrary issue text, downloaded corpora, or adversarial test
fixtures.

The working trust test is stewardship, not a list (ruled 2026-08-22): a
repository is trusted when it belongs to Shawn, to Brian, or to an
organisation Shawn is part of — re-derived from repository state at time of
use, never cached as an allow-list. Two carve-outs keep the task-input axis
primary:

- **World-writable surfaces of public repositories are untrusted inputs even
  inside trusted repositories.** Anyone can write a FAIMS3 issue or open a
  fork pull request; third-party issue text and fork diffs are external
  content, distinct from the trusted tree at the head of protected branches.
- **The most exposed workflows in current practice are not repositories at
  all** but external content flowing through trusted sessions: email triage
  and web research. `/process-email` now carries an explicit
  content-is-data-never-instructions rule (applied 2026-08-22 in
  `commands/process-email.md`); web-research rituals should carry the same
  line as they are formalised.

Use two operational profiles:

1. **Personal/trusted profile:** broad read access to PA and `gpt-hub`, with
   approved memory retrieval available.
2. **Restricted-input profile:** repository-only ambient filesystem access and
   no personal-memory tools. A specific PA read may be granted explicitly for
   the task.

This does not rescind Shawn's "read everything" decision. It distinguishes
available authority from authority automatically exposed to untrusted content.
A trusted repository can still contain an untrusted input; choose the profile
for the task, not solely for the repository name.

The two profiles are presently Codex-mechanised. Claude sessions carry ambient
PA access and a session-start memory digest regardless of repository, so
Claude's mitigation is behavioural — the skill-level rules above plus
permission prompts on outward actions. This asymmetry is accepted for now
under the guardrails stance below, and is revisited if evidence shows
behavioural controls are inadequate.

### Credentials (ruled 2026-08-24)

- Both agents carry the same credential read carve-out: no reading of
  `**/.env*` or `**/secrets/**` — including `personal-assistant/.env` and
  timestamped backups beside it, where API credentials may live. "No secrets
  between the agents" governs each other's records, not credential material,
  which is Shawn-gated (§2).
- Operating norm: **credentials are used by processes, never read into model
  context.** Claude's hooks and scripts use credentials at execution time
  while the harness denies credential-file reads. Codex mirrors that denial at
  the OS and hook layers and receives any future allow-listed values only from
  its launcher.
- Sol currently holds no API credential access, and none is needed in the
  current phases. When a need arises, access is granted per service through
  the trust-profile launcher (§9.3): the personal/trusted profile is
  launched with a filtered subset of `.env` injected as environment
  variables, per `global-agent-guidance/credential-grants.toml`. The list is
  initially empty and changes through the ownership-policy PR protocol; adding
  a grant is a loosening, so Shawn signs off. The restricted-input profile
  never receives credentials, closing the injection-exfiltration channel where
  untrusted content is processed.
- `personal-assistant/.env*` is also write-denied for Sol. The launcher parses
  the file without shell-sourcing it and never emits values: malformed
  variable names have caused shell sourcing to echo credential-bearing lines
  to stderr in two real incidents (2026-05-22 and 2026-07-27). After any
  credential-file edit, Shawn or Claude runs `scripts/check-credentials.py`
  outside model context.
- Grant names map one-to-one to environment-variable names. Credential files
  use one variable per service and scope, with per-machine variables for paid
  services. PA loaders use `setdefault`, so launcher-injected variables take
  precedence without rewriting the credential file.

---

## 4. Memory architecture

### Current read path

The existing `scripts/memory_mcp.py` is a six-tool, read-only MCP server using
`stdio`. As verified on 2026-08-20, its tools are:

- `search_memories`;
- `semantic_search`;
- `search_sessions`;
- `get_memory`;
- `list_recent`; and
- `memory_statistics`.

Codex supports both local `stdio` and remote streamable-HTTP MCP servers.
Register the current server read-only during the first implementation slice.
In trusted contexts, Sol may also read PA files directly when a document or raw
record is the authoritative source. MCP is a convenient retrieval interface,
not a mandatory read-side security boundary.

Personal-memory tools and direct PA filesystem access are disabled in the
restricted-input profile. Disabling MCP alone is insufficient if the same
session can read the raw files directly.

Codex's separate native memory facility stays disabled initially. The PA store
remains canonical, avoiding two competing recall systems.

### Current write path

Claude continues routine live-memory maintenance during the first phase. Sol
does not directly append, rewrite, archive, backfill, or reconcile operational
memory data.

This restriction applies to **data mutation**, not to capability. Sol may
review or, when explicitly assigned, implement and test memory-service code in
an isolated PA worktree. Tests use fixtures or temporary stores, never the live
corpus without a separate operational approval.

### Future single-writer boundary

An MCP module does not by itself serialise writes: separate clients can spawn
separate `stdio` processes. The future write architecture must supply one
actual concurrency boundary across agents and machines.

Before exposing any Sol write tool:

1. inventory every direct corpus mutator, not only the extraction hook and
   `/recap`;
2. migrate all online writers, including extraction, `/remember`, `/recap`,
   `/update`, and `/forget`, to the writer boundary;
3. route maintenance tools through an administrative interface or an exclusive
   maintenance lease;
4. require idempotency keys, locking/transactions, provenance validation,
   explicit write approval, and durable audit receipts; and
5. test concurrent clients, duplicate calls, forced termination, network
   interruption, and recovery.

The first migration should preserve the current data model and update
semantics. A true append-only event redesign may be valuable, but combining it
with writer centralisation would make the safety migration unnecessarily
large.

A single always-on streamable-HTTP service is the clearest cross-machine
design. Test Codex connectivity to `rpi-server` early, but treat that host as a
candidate until availability, backup, and network-partition behaviour are
reviewed.

Claude keeps running the current maintenance tasks until this service and its
administrative path are proven. That allocation is explicitly temporary.

---

## 5. Continuity and records

### Project continuity

Keep one `wiki/continuity.md` per project repository. Either agent may update
it from an isolated worktree. Session entries carry an agent, timestamp, and
unique workstream/session identifier, for example:

```markdown
### 2026-08-22T16:00+10:00 — map-reader / sol / benchmark-plan
```

Adopt this header format only after a census of everything that parses
continuity headers (session-start hooks, "latest"-marker consumers), and
update the documented convention in each repository's instruction files in
the same change — otherwise the format change itself recreates the stale
prescriptive-record class this plan abolishes.

If parallel merge conflicts become frequent, move immutable session-close
entries to `wiki/handoffs/` and retain `wiki/continuity.md` as a short
current-state index.

PA continuity is part of the Claude-owned personal-assistant function.
`gpt-hub` continuity is Sol-owned. Each agent may read the other and propose a
correction.

### Observations

Keep one register per voice and direction:

- PA `claude-observations.md`: Claude-owned observations about working with
  Shawn;
- PA `user-observations.md`: Shawn's observations about Claude, maintained
  through the existing gated ritual;
- `gpt-hub/wiki/sol-observations.md`: Sol-owned observations about working with
  Shawn; and
- `gpt-hub/wiki/user-observations.md`: Shawn's observations about Sol, with a
  parallel gated ritual.

Project `wiki/working-notes.md` remains shared. Use one numbered observation
series per repository, with the author named in each entry, so cross-references
remain unambiguous.

### Personal-assistant records

Sol may use standups, focus state, reports, retrospectives, and time logs as
context. Sol does not run their rituals or update their records. If project work
reveals a task, time entry, or personal-assistant correction, Sol records a
proposal in project continuity or `gpt-hub`; Claude incorporates it during the
appropriate PA ritual.

---

## 6. Instructions, skills, hooks, and import

### Source layout

Refactor before composing either harness's global instructions:

```text
personal-assistant/global-agent-guidance/
└── common.md                  # portable; shared editing surface

personal-assistant/global-claude-md/
├── claude.md                  # Claude-owned overlay
└── supporting references     # Claude-owned

gpt-hub/instructions/
├── codex.md                   # Sol-owned overlay
└── supporting references     # Sol-owned
```

Private machine details should remain in the appropriate agent-owned local
overlay or in an authoritative reference loaded only when needed. Do not inject
the full network and operational dossier into every session.

The existing `global-claude-md/shared.md` must first be split because it
contains both portable norms and Claude-specific model, command, memory, and
session behaviour.

**Status (2026-08-25, `9786a71`):** the split is done on the Claude side. The
layout above is the current state, not a target. `shared.md` is archived at
`archive/global-claude-md/shared.md` with a README recording the mapping. The
split is verbatim apart from five wordings that de-Claude-ify portable
sections and the ownership section, which was rewritten because its original
phrasing was Claude-first and would have read backwards in Sol's
instructions. The Codex composer/installer remains Sol's to build.

### Composition and ownership

- PA's composer writes only `~/.claude/CLAUDE.md` from the portable common
  source plus Claude-owned overlays.
- A `gpt-hub` installer writes only `~/.codex/AGENTS.md` from the same portable
  source plus Sol-owned overlays.
- Neither composer writes the other harness's output.
- Both agents may edit the portable common source from isolated worktrees.
- Only Claude edits Claude overlays and generated `CLAUDE.md` files.
- Only Sol edits Codex overlays and generated `AGENTS.md` files.

Repository-local instruction files follow the same boundary. Put genuinely
shared project policy in ordinary documentation where both agents may edit it;
keep `CLAUDE.md` and `AGENTS.md` as concise harness-specific entry points.

### Instruction-size safety

Codex assembles instructions global-first: `~/.codex/AGENTS.md`, then one file
per directory from the repository root down to the working directory
(`AGENTS.override.md` wins over `AGENTS.md` at each level). It reads the chain
once per session, and stops once the combined size reaches
`project_doc_max_bytes`. The default is **32,768 bytes**, verified in the
installed binary at codex-cli 0.149.1, not merely from documentation.

**The hazard is the ordering, not the size.** Because global comes first, the
content lost when the cap is reached is the *tail* — the nearest, most
specific repository instructions, which should carry the highest practical
precedence. Truncation is silent, with no warning in the interface
(openai/codex#7138). A fat global file therefore does not fail loudly; it
quietly starves the files that matter most.

Budget (revised 2026-08-25, against measurement):

- global `~/.codex/AGENTS.md`: at most **14 KiB**;
- maximum tested global-plus-project chain: at most **24 KiB**; and
- retain at least **8 KiB** of headroom below the 32 KiB cap.

The Codex composer must fail its check if the budget is exceeded. An acceptance
test starts fresh sessions from a repository root and a nested directory and
verifies the loaded instruction sources and key sentinel rules. **Do not raise
`project_doc_max_bytes` itself** — that hides bloat rather than fixing it, and
it spends the headroom that keeps truncation from reaching real instructions.

**Why 14 KiB, and why the earlier 8 KiB is retired.** The original 8 KiB
target was set at ratification (`594c2b7`) before anyone measured the portable
core; Sol's capability review had said only that the generated `AGENTS.md`
should be under 32 KiB. Measured afterwards, the extracted portable source is
11,264 bytes on its own, so 8 KiB was never reachable without cutting rules.
The revised figure is set from what the chain actually costs on this machine:

| | bytes |
|---|---|
| Cap (`project_doc_max_bytes`) | 32,768 |
| `~/.codex/AGENTS.md` today | 2,399 |
| Global with the portable core composed in | 13,663 |
| Remaining for the whole project chain | 19,105 |

Against real repository files — `gpt-hub/AGENTS.md` at 2,021 bytes, the
proposed `map-reader-llm/AGENTS.md` at roughly 1.2 KiB — a realistic chain
spends 4–6 KiB of that. Capacity is therefore not the binding constraint, and
a budget that implied otherwise was distorting the design.

**Byte pressure and context economy are separate questions.** The portable
source is loaded into every session on both harnesses, so there is an
independent argument for keeping it lean that has nothing to do with the cap.
That argument should be made on its own merits, section by section, and not
smuggled in under a capacity limit that does not bind.

### Selective Claude import

Codex's `/import` can translate Claude instructions, settings, skills, hooks,
slash commands, subagents, projects, recent chats, memories, and MCP
configuration. Use it first as an inventory and candidate-generation tool.

Initially import or adapt only reviewed instructions, skills, and hooks. Do not
bulk-import chats, memories, permissions, model settings, or PA commands.
`/recap`, `/remember`, and similar commands contain Claude-owned PA operations
and direct memory writes; they must not be ported unchanged.

Good pilot workflow candidates are:

- project `/handoff`, adapted to reciprocal continuity ownership;
- project `/observe`, adapted to Codex subagents and repository discipline;
  and
- `pre-run-review`, which is agent-neutral after model references are removed.

Codex supports lifecycle hooks, including `SessionStart`, `Stop`, and
`SessionEnd`. Heavy extraction must not run in `SessionEnd`, whose documented
allowance is at most three seconds. A future end hook should write only a small,
durable queue receipt; a separate worker performs expensive processing.

---

## 7. Division of labour, repositories, and attribution

### Routing work

Route by the needs of the task:

- **Sol/Codex:** repository-native implementation, debugging, tests,
  long-running execution, evaluation design, technical and methodological
  reasoning, and independent review;
- **Claude:** the established PA rituals and, for now, live memory maintenance;
- **either or both:** difficult synthesis and judgement, selected according to
  context, tools, capacity, and the value of an independent second derivation;
  and
- **lower-cost models:** bounded, verifiable subtasks whose outputs are reviewed
  by the owning agent.

For high-stakes claims, prefer cross-vendor cold derivation followed by
adjudication against source artefacts. Do not presume that one vendor owns
judgement and the other owns mechanical work.

Review the routing after a two-week pilot using actual model, effort, quota,
latency, failure, and rework evidence.

### Repository policy

Repository state and task inputs determine discipline; this document is not a
permanent allow-list.

- **`gpt-hub`:** Sol-owned; Claude read and proposal-only.
- **`personal-assistant`:** capability-specific ownership from §2; PA
  operations and Claude configuration are Claude-owned, while authorised
  neutral engineering and planning may be shared.
- **`map-reader-llm`, `fieldmark-docs-staging`, and
  `llm-reproducibility`:** both agents may work in isolated worktrees.
- **FAIMS:** trusted and available to both agents; its `AGENTS.md`, branch,
  pull-request, and verification rules govern changes.
- **Other collaborative repositories:** available to both agents under their
  own branch-and-review rules. Collaborator presence alone is not a gate.
- **Unknown repositories or tasks with untrusted inputs:** use the
  restricted-input profile from §3.

### Attribution

Shawn remains the configured Git author. Material Sol assistance uses:

```text
Co-Authored-By: Sol (OpenAI Codex) <shawn@faims.edu.au>
```

This canonical string uses Shawn's configured primary Git address. Record the
final Claude and Sol trailer strings in
`global-claude-md/git-reference.md` and the Codex equivalent.

Do not encode a changing model identifier in hand-authored Git identities.
Claude's harness-supplied trailer is model-versioned
(`Co-Authored-By: Claude <model> <noreply@anthropic.com>`) and remains as the
harness emits it; attribution queries key on `Co-Authored-By:.*(Claude|Sol)`,
which is stable across model versions. Experiments and evaluations record
agent persona, harness, model, reasoning effort, temperature, run identifier,
and operational metrics in their manifests.

---

## 8. Verified Codex capabilities and current state

The following were checked against current official OpenAI documentation and
this machine on 2026-08-20–22:

1. **MCP:** Codex supports local `stdio` and remote streamable-HTTP servers.
   Configuration may be global in `~/.codex/config.toml` or project-scoped in a
   trusted `.codex/config.toml`.
2. **Filesystem and processes:** local Codex works against host checkouts under
   a configurable sandbox and approval policy. It can spawn subprocesses and
   use Git; filesystem and network authority depend on the active profile.
3. **Instructions:** Codex discovers global, repository-root, and nested
   `AGENTS.md`/`AGENTS.override.md` files. Nearer files appear later, but the
   default combined size limit is 32 KiB.
4. **Git:** direct commits, worktrees, fetches, and authenticated GitHub pushes
   work on this machine, subject to sandbox approval and normal Git protections.
5. **Hooks:** Codex supports session, compaction, prompt, tool, permission, and
   subagent lifecycle events.
6. **Skills and migration:** Codex supports `SKILL.md` workflows, plugins,
   subagents, slash commands, and selective Claude Code import.
7. **Current configuration:** the local default is `gpt-5.6-sol` with `xhigh`
   reasoning effort. No reliable account-level weekly quota figure is exposed
   inside the session; capture actual usage during the pilot.

Official sources:

- [`AGENTS.md` instructions][agents-docs]
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

## 9. Remaining implementation decisions

These do not reopen the ratified architecture:

1. **`gpt-hub` remote:** default to a private repository under Shawn's GitHub
   account unless Shawn chooses otherwise.
2. **Guardrail strength:** begin with harness path policies, isolated
   worktrees, and tests. Add operating-system isolation only if this proves
   insufficient.
3. **Trust-profile launcher (ruled 2026-08-24):** use one `CODEX_HOME`, two
   named configuration/permission profiles, and a small wrapper. For the
   personal/trusted profile only, the wrapper parses `.env` without shell
   sourcing, validates variable names, injects only names present in
   `global-agent-guidance/credential-grants.toml`, and never logs values. The
   restricted-input launch removes any grant-listed variables and disables
   personal-memory MCP access. The Phase 1 grant list is empty. Acceptance is
   authoritative: restricted-input can alter only its active repository and
   receives neither credentials nor personal memory.
4. **Writer-service host:** test `rpi-server` connectivity and then rule on
   placement using availability, backup, latency, and partition behaviour.
5. **Maintenance migration:** Claude owns current operations while the service
   is built. The later administrative interface and cut-over order require a
   dedicated pre-run review.

---

## 10. Implementation sequence and acceptance gates

### Phase 0 — authoritative plan

Rewrite and commit this document so §§1–10 contain one current policy.

**Exit:** the original Opus draft and the Sol and Fable reviews are integrated;
superseded prose remains available through Git, not inline.

### Phase 1 — establish Sol's home and ownership policy

Create `gpt-hub`, its wiki registers, instruction/skill directories, and the
machine-readable ownership policy at `global-agent-guidance/ownership.toml`
in `personal-assistant` (ruled 2026-08-23; protocol in §3). Keep linked
worktrees under `~/worktrees/`.

**Exit:** Claude can read but cannot accidentally write representative
`gpt-hub` paths; Sol has an explicit proposal route for Claude-owned PA paths;
the ownership-policy test derives its cases from `ownership.toml`; and both
agents can edit a neutral shared project file from isolated worktrees.

### Phase 2 — refactor and compose instructions

Extract the portable common guidance, create agent-owned overlays, build the
Codex composer/installer, and update the Claude composer without crossing
ownership boundaries. In pilot repositories, extract shared project policy
from `CLAUDE.md` into a neutral documentation file referenced from both
concise harness entry points.

**Exit:** fresh sessions report the expected instruction chain; Claude-specific
rules do not appear in Codex; Codex-specific rules do not appear in Claude;
the maximum tested Codex chain is at most 24 KiB; and pilot repositories hold
shared project policy in a neutral file, not in either harness's entry point.

### Phase 3 — inventory native import

Run selective `/import`, capture the candidate inventory, and adjudicate each
item as import, adapt, replace, or reject.

**Exit:** no imported workflow directly operates Claude-owned PA functions or
the live memory corpus.

### Phase 4 — enable read-only shared memory

Register the current six-tool MCP server for the personal/trusted profile and
test both PostgreSQL and offline fallback behaviour.

**Exit:** approved contexts can use all six tools; the restricted-input profile
cannot use the tools or directly read PA; database/server failure does not block
ordinary project work; and every failure is observable.

### Phase 5 — port pilot workflows and continuity

Adapt `handoff`, `observe`, and `pre-run-review`; establish reciprocal
continuity and observation conventions.

**Exit:** Claude can resume from a Sol handoff and Sol from a Claude handoff
without oral reconstruction by Shawn. Neither workflow writes an agent-owned
surface belonging to the other agent.

### Phase 6 — two-week operating pilot

Use the system on `map-reader-llm` and at least one other trusted repository.
Collect model, effort, latency, quota pressure, failure, rework, continuity, and
merge-conflict evidence.

**Exit:** no shared-checkout incidents; no ownership-policy violations;
continuity is usable; and the evidence supports a revised routing policy.

### Phase 7 — writer discovery and service design

Inventory all online and maintenance mutators, test LAN connectivity, choose
the writer host and protocol, and run a dedicated pre-run review.

**Exit:** the design has a complete writer denominator, concurrency and crash
tests, rollback/recovery semantics, an administrative maintenance path, and an
explicit cut-over plan for Claude's existing writers.

### Phase 8 — migrate online writers

Move Claude's extraction and interactive commands, then Sol's future write
tools, behind the proven writer boundary. Preserve current storage semantics in
this phase.

**Exit:** no unsanctioned online direct mutations remain; concurrent-client,
duplicate-call, crash, and partition tests pass; and audit receipts reconcile
with the canonical store.

### Phase 9 — migrate or gate maintenance operations

Move bulk and repair tools behind an administrative interface or an exclusive
maintenance lease. Claude remains the operator until the migration is proven;
agent ownership may then be reconsidered from evidence.

**Exit:** a mechanical census finds no unclassified corpus writer, maintenance
failure is recoverable, and Shawn approves the operational handover policy.

---

## Review and decision record

Git is the historical record for the deliberation that produced this plan:

- `38ae5d4` — Opus drafts the initial proposal;
- `e44b2d7` — Sol reviews Codex capabilities and architecture;
- `0b7c7d8` — Fable verifies and reviews Sol's response;
- `594c2b7` — integrates Shawn's access, trust, attribution, maintenance, and
  body-rewrite rulings into a single current policy; and
- `f0197f6` — applies Fable's second-round review as ratified by
  Shawn: scopes the worktree rule by agent pair and repository, defines the
  stewardship trust test with a world-writable-surface carve-out, records the
  `/process-email` injection guard, assigns repo-local shared-policy
  extraction to Phase 2, requires a parser census before the continuity
  header format changes, and exempts Claude's harness-supplied
  model-versioned trailer;
- `3fba09e` — finalises Sol's attribution string; and
- the current revision — records the ownership-policy rulings of 2026-08-23:
  canonical location at `global-agent-guidance/ownership.toml`, the
  PR-with-other-party-review protocol with Shawn as tie-break, the
  loosening-needs-Shawn asymmetry, and the requirement that the
  ownership-policy test read the file it enforces.

Key corrections integrated here include the real multi-process write hazard,
Codex's native hooks and import support, instruction-chain truncation, all-writer
cut-over, indirect prompt injection, reciprocal harness ownership, and the
rejection of a mechanical-only division of labour.

## Anchors

`scripts/memory_mcp.py` · `tests/test_memory_mcp.py` ·
`scripts/check-memory-drift.py` · `scripts/daily-sync.sh` ·
`scripts/compose-global-claude-md.sh` · `hooks/extraction-hook.py` ·
`commands/{recap,remember,update,forget}.md` ·
`wiki/planning/rpi-server-mcp-migration.md` ·
`wiki/planning/mcp-server-v2-write-tools.md` ·
`global-claude-md/git-reference.md` · commits `3ad6fa6`, `108d044`, and
`43fcd15`.
