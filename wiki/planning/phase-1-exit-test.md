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
- Claude's first review was incorporated as schema 2: owner-first default
  denial, OS/tool-layer case separation, the R3-R10 surface and credential
  rulings, and an empty reviewed credential-grant mechanism.
- Candidate rerun: all 11 Codex OS cases pass; five Claude tool-layer cases are
  emitted as a checklist for Claude to exercise and record.
- Claude's re-review of `46b212f` approved R1-R10 with no blockers and recorded
  all five tool-layer cases denied, for 16/16 candidate cases across both
  enforcement layers.
- Merge status: PR #107 integrated through the adjudicated merge commit with
  `policy_status = "active"`; Claude's independent worktree lane remains the
  next integration step.

## Claude lane

Pending Claude's independent worktree edit and review.

## Joint exit conditions

- [x] Sol can edit a neutral PA path from an isolated worktree.
- [ ] Claude can edit the same neutral PA path from its isolated worktree.
- [ ] Both reciprocal machine-local deny layers pass policy-derived attempted
  write tests.
- [x] The ownership-policy pull request receives other-party review.
- [ ] Both worktree contributions are integrated without using the live shared
  checkout for concurrent work.
