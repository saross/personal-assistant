# Archived global-instruction sources

## `shared.md`

Superseded 2026-08-25 by the Phase 2 instruction refactor of the
Sol-in-Codex integration plan (`wiki/planning/sol-in-codex-integration.md`
§6, §10 Phase 2). Its content was split, without rewording except where
noted below, into:

- `global-agent-guidance/common.md` — portable, agent-neutral guidance,
  composed into **both** `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`;
- `global-claude-md/claude.md` — the Claude-owned overlay (subagent model
  policy, memory system, scratchpad, craft notebook, reference docs).

Five wording changes were made so that portable sections read correctly in a
non-Claude harness ("Claude is fine" → "proceeding with an AI tool is fine",
`CLAUDE.md` → agent instructions (`CLAUDE.md` / `AGENTS.md`), and an
"Opus-class models" claim generalised to "Frontier models — Opus-class among
them"). The *Agent Ownership Boundaries* section was rewritten rather than
copied, because its original phrasing was Claude-first and would have been
backwards in Sol's instructions; the reciprocal policy now sits in
`common.md` and Claude's concrete paths in `claude.md`.

Kept for audit trail. Do not edit; do not restore into the composer.
