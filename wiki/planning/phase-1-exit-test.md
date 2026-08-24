---
title: "Sol/Claude integration — Phase 1 joint exit test"
tags: [planning, integration, worktrees, ownership]
created: 2026-08-23
updated: 2026-08-24
status: in-progress
---

# Phase 1 joint exit test

This neutral shared file is the integration target for the Phase 1 worktree
test. Each agent edits it only from an isolated personal-assistant worktree;
neither agent uses Claude's live PA checkout.

## Claude lane

- Worktree: `~/worktrees/personal-assistant/claude-phase1-test`
- Branch: `claude/phase1-test` (based on `main`; the merge with
  `sol/phase1-test` is expected to raise a visible add/add conflict on this
  file — that conflict, and its adjudication, is itself part of the test:
  worktrees turn silent overwrites into visible merges, per plan §3)
- Neutral shared-path edit: successful.
- Tool-layer verification of Claude's three declared cases
  (`claude-gpt-hub`, `claude-codex-home`, `claude-agents-md`): all denied by
  settings-level rules on 2026-08-24. OS-level probes of the same cases
  succeed by design — Claude has no OS sandbox; its enforcement is
  tool-layer. See the PR #107 review for the enforcement-layer finding.
