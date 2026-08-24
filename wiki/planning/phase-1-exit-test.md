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

- Worktree: `~/worktrees/personal-assistant/claude-phase1-test`
- Branch: `claude/phase1-test` (based on `main`; this merge raised the
  expected add/add conflict on this file — that conflict, and its
  adjudication in this very commit, is itself part of the test: worktrees
  turn silent overwrites into visible merges, per plan §3)
- Neutral shared-path edit: successful.
- Tool-layer verification, 2026-08-24: all five declared Claude checklist
  cases denied (`claude-gpt-hub`, `claude-codex-home`, `claude-agents-md`,
  `claude-credential-backup-read` fresh; `claude-credential-env-read` by
  same-day rule-family evidence, deliberately without a fresh attempt on the
  live credentials file). Evidence gathered after the Write/Edit
  adjudication: the five inert `Write(path)` deny rules were removed and
  enforcement re-proven under Edit-only rules, so the recorded denials
  reflect the final settings. OS-level probes of the same cases succeed by
  design — Claude has no OS sandbox; its enforcement is tool-layer.
- Review: first review and approving re-review posted on PR #107
  (2026-08-24); R9 active-status flip authorised and applied at merge.

## Joint exit conditions

- [x] Sol can edit a neutral PA path from an isolated worktree.
- [x] Claude can edit the same neutral PA path from its isolated worktree.
- [ ] Both reciprocal machine-local deny layers pass policy-derived attempted
  write tests. (Held open for S5: Sol repoints its hook to the canonical
  policy path and reruns the full suite against the merged file.)
- [x] The ownership-policy pull request receives other-party review.
- [x] Both worktree contributions are integrated without using the live shared
  checkout for concurrent work. (Completed by this adjudicated merge.)
