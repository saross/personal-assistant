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

## Sol/Codex lane

- Worktree: `~/worktrees/personal-assistant/sol-phase1-test`
- Branch: `sol/phase1-test`
- Neutral shared-path edit: successful.
- Ownership-policy source and verification-case walker added under
  `global-agent-guidance/` on the same branch.
- Merge status: deliberately unmerged pending Claude review and the Claude
  worktree lane.

## Claude lane

Pending Claude's independent worktree edit and review.

## Joint exit conditions

- [x] Sol can edit a neutral PA path from an isolated worktree.
- [ ] Claude can edit the same neutral PA path from its isolated worktree.
- [ ] Both reciprocal machine-local deny layers pass policy-derived attempted
  write tests.
- [ ] The ownership-policy pull request receives other-party review.
- [ ] Both worktree contributions are integrated without using the live shared
  checkout for concurrent work.
