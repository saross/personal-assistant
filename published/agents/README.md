# Published Agents

Subagent definitions recommended for external reuse. **Each entry is a
sanitised copy** of the canonical working version in `../../agents/` —
copies only, no symlinks, per the 2026-06-15 policy in
[`../README.md`](../README.md). Local tooling invocations are replaced
with placeholders (see each file's header note); the empirical findings
cited (error rates, catch rates) come from real runs in the source
system.

## Format

Claude Code agent definitions — Markdown with YAML frontmatter. Place in
`~/.claude/agents/` (user-wide) or `.claude/agents/` (project-specific).

## Current entries (all published 2026-08-03)

Two proposer–verifier pairs. In each, the proposer emits a draft with an
explicit `VERIFICATION PENDING` marker and a machine-readable claims
block; the verifier runs as a **separate, serially-invoked agent in a
fresh context**. Proposers must not spawn their own verifiers — nested
dispatch does not work in this harness; orchestrate the pair from a
slash command or the parent session.

- **`lit-scout.md`** — Systematic academic literature discovery with
  bibliography chaining via CrossRef, Semantic Scholar, and OpenAlex;
  diversified seeding to counter corpus bias; DOI-first deduplication
  against a local Zotero library; mandatory per-row metadata
  verification with length-gated author rendering.

- **`lit-scout-verifier.md`** — Adversarial verifier for lit-scout
  drafts: re-queries every claim against authoritative metadata APIs in
  a fresh context, produces a corrections-applied audit trail and a
  verdict, and supports a closed iterate loop via stable claim IDs.

- **`prior-art-scout.md`** — Searches for existing implementations,
  libraries, tools, and approaches before building something new —
  GitHub, GitLab, package registries, Hugging Face, and methodological
  literature.

- **`prior-art-scout-verifier.md`** — Adversarial verifier for
  prior-art reports: re-checks every cited repository, package, model,
  and paper against its authoritative source API (existence, stats,
  activity, licence).

## Adapting

The pairs assume a small API-helper script (rate limiting, provider
fallback chains) and a reference-manager query module — both replaced
with placeholders in these copies. Substitute your own; the discovery
methodology, verification contracts, and claims schemas are the
portable part.
