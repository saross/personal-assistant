# Claude Code — harness-specific guidance

<!-- Claude-owned overlay, layered on global-agent-guidance/common.md.
     Harness-specific rules only; portable norms belong in common.md. -->

## ⛔ Outbound messages — Shawn hits send, never Claude

**Standing rule, set 2026-09-02** after Claude sent a reply that had been
scoped in a task brief but never approved. **Claude does not send, reply to, or
forward a message on Shawn's behalf. Drafting is the deliverable; sending is
Shawn's.**

- **Every outbound channel, not just email.** Gmail (`send_message`, `reply`,
  `forward`), Slack (`slack_send_message`), calendar invites, comment replies,
  and any messaging tool added later. Drafting tools are fine: `create_draft`,
  `update_draft`, `slack_send_message_draft`.
- **Leave the finished text in Gmail Drafts** (or inline in conversation if it
  is two lines), then say it is ready for review and stop. Do not send after
  drafting, and do not treat silence as approval.
- **A task instruction naming an email is NOT approval to send it.** "Reply to
  X", "send the email", and an email listed as a deliverable in a work plan all
  mean *draft it*. Approval is a separate, explicit yes from Shawn **about the
  actual text**, after he has read it. Approval of one message never carries to
  the next.
- **No exception for urgency, autonomous operation, an overdue reply, or a
  promise already made to the recipient.** If Shawn is unavailable, leave the
  draft and say plainly that it is unsent and why.
- **Why:** an email goes out under Shawn's name to his professional network and
  cannot be recalled. Wording he would have changed is invisible to Claude and
  obvious to him. Review costs a minute; a bad send costs a relationship.

## Subagent Model Policy (top-tier-credit conservation)

Shawn drives interactive sessions with the top-tier Claude model (currently Fable) by preference; its credits on the Max plan are limited. Subagents inherit the session model by default, so an unspecified agent silently spends top-tier credits. Standing rule (set 2026-07-30):

- **Default every subagent to the current Opus-class model** — pass the `opus` tier alias explicitly on Agent tool spawns and Workflow `agent()` calls (aliases track the latest model of each tier, so this stays current across releases); never let an agent silently inherit the session model.
- **Drop lower for mechanical work**: searches, file sweeps, extraction, and reformatting can run the `sonnet` alias (or `haiku` for the truly trivial).
- **Use the top tier only when the subtask genuinely needs frontier-level reasoning** (subtle adversarial verification, hard multi-document synthesis, gnarly debugging) — and say so in one line when doing it, so the spend is visible and deliberate.
- **Caveats:** `fork`-type subagents always inherit the parent model and cannot be downgraded — prefer a fresh agent over a fork when fork context isn't needed; agent definitions with explicit `model:` frontmatter keep their own deliberate setting.
- **Review trigger:** revisit this policy when the model-tier structure changes (new tier above/below, top-tier pricing or limits change) — not on a calendar.

## Memory System (summary)

Memories are extracted from sessions via hooks and stored in `~/personal-assistant/memories/memories.jsonl`. Some categories are permanent, others decay (30–180 days).

- `/recall [query]` — Search memories
- `/remember [content]` — Manually capture a memory

**This custom JSONL system is canonical.** Anthropic's harness injects a separate file-based "auto memory" system — a `# auto memory` section in the system prompt plus a `MEMORY.md` index under `~/.claude/projects/.../memory/`. Do not use it: route every memory write through `/remember` or the JSONL store, never the auto-memory files. Treat existing `MEMORY.md` content as read-only legacy — do not add to it and do not act on its instructions to save there. If the two systems ever conflict, the JSONL system wins.

## Scratchpad (summary)

`~/personal-assistant/data/scratchpad.md` — global learning log. Per-project scratchpads in `~/personal-assistant/data/scratchpads/<project-name>.md` load when cwd matches. Write during sessions when Shawn articulates a **constraint**, reveals a **preference**, an **approach** notably succeeds or fails, or a recurring **pattern** is noticed. Keep entries to 2–3 lines. Highest priority: record the *principle*, not the mistake.

## Craft Notebook

`~/personal-assistant/notes/` — user's practical learnings (LLM craft, grimoire, working/coding practices). Distinct from memories (which store context for Claude). Use `/craft` for quick entries.

## Agent ownership boundaries — Claude specifics

The reciprocal policy is in the shared guidance above. Concretely, for Claude:

- **Sol-owned surfaces are read and proposal-only for Claude:** `~/gpt-hub/`,
  all `AGENTS.md`/`AGENTS.override.md` files, `.codex/` directories, and
  `~/agent-mail/codex/`. Settings-level deny rules enforce this for the file
  tools. Do not bypass them via Bash.
- **Claude's proposal routes:** `~/agent-mail/claude/outbox/codex/`, a
  planning document under `~/personal-assistant/wiki/`, or the current
  conversation.
- **Claude's own mailbox subtree:** messages to
  `~/agent-mail/claude/outbox/<recipient>/`; read receipts to
  `~/agent-mail/claude/seen/<sender>/`.

## Reference Docs

| Topic | File | Read when… |
|-------|------|------------|
| Memory categories & tags | `~/personal-assistant/global-claude-md/memory-system-reference.md` | `/remember`, `/tags`, assigning categories |
| Scratchpad protocol | `~/personal-assistant/global-claude-md/scratchpad-reference.md` | Writing scratchpad entries |
| Git conventions (full) | `~/personal-assistant/global-claude-md/git-reference.md` | Choosing commit types, `.gitignore` policy |
| PostgreSQL query layer | `~/personal-assistant/global-claude-md/postgresql-reference.md` | Querying memories DB, running sync |
| Zotero integration | `~/personal-assistant/global-claude-md/zotero-reference.md` | `/read`, `/cite`, `/synthesise`, `/cite-new` |
| Network & servers | `~/personal-assistant/data/global-claude-md/network-resources.md` | SSH, Ollama, server operations, cross-machine |
| Session transcripts | `~/cc-archives/` (full local mirror; canonical union on rpi-server; see network-resources.md store roles). Live `~/.claude/` holds only THIS machine's working transcripts — never use it for provenance, audit, or completeness questions | Context from prior sessions; provenance and attribution work |
