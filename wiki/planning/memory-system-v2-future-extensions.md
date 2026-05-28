# Memory System v2 — Future Extensions

**Status:** Living register of work explicitly deferred from the v2
implementation plan. Not a commitment to do these — a place to capture them
so they don't get lost.
**Created:** 2026-05-15
**Author:** Claude (Opus 4.7) + Shawn
**Related:** `planning/memory-system-v2-design.md`,
`planning/memory-system-v2-implementation-plan.md`,
`planning/memory-corpus-audit-2026-05-14.md`.

## Purpose

Each entry below is something we considered during v2 design but explicitly
chose not to do now. Capturing them here means: (a) future sessions can find
them rather than reinventing them; (b) when one becomes relevant (e.g. the
verifier surfaces a new failure mode that test tooling would have caught),
the prior reasoning is available; (c) the v2 plan stays scoped.

Group by area, not priority. Add new entries as they come up.

## A. Test tooling (beyond what v2 ships)

The v2 plan introduces pytest with realistic fixtures and ~14 test files
covering the new code paths. The following test-engineering capabilities are
*not* in v2 scope — defer until evidence of need.

- **Continuous Integration (CI).** GitHub Actions workflow that runs the
  suite on push and on PR. Useful once collaborators contribute, or once
  test runs become painful to remember locally. Today: solo repo, manual
  `make test` acceptable.
- **Coverage tooling.** `pytest-cov` + a coverage gate in CI. Useful for
  ensuring new code can't merge without tests. Today: too soon — we don't
  have CI and "every public function has at least one test" is the working
  target.
- **Property-based testing.** `hypothesis` for invariant checks: JSONL
  round-trip preserves arbitrary records, tag normalisation is idempotent,
  anchor parsing accepts any well-formed input. High value for the storage
  layer; defer until v2 ships and we know where the brittle edges are.
- **Performance benchmarks.** `pytest-benchmark` for hot paths (extraction
  hook completion time, recall query latency, drift sweep throughput).
  Useful once corpus size pushes us toward a perf cliff; today's measured
  latencies are comfortable.
- **Mutation testing.** `mutmut` or similar to verify test quality. Heavy
  tooling for a small codebase; defer indefinitely unless a regression
  shows the suite was deceptively green.
- **Postgres integration tests.** Spin up a real Postgres in `/tmp` per
  test run. Useful when the schema or query layer gets more complex than
  it is today; current surface is small enough that schema-apply smoke
  checks suffice.

## B. Memory system features deferred from v2

- **Retroactive anchor pass on the existing 25k.** Cost-gated; held until
  the Phase 5 drift sweep + bulk-flag pass produces data on whether it's
  worth doing for high-value permanent categories.
- **Recall ranking algorithm changes** beyond anchor-resolution gating.
  Current recall is keyword + tag + semantic; v2 adds a `verified` filter
  but does not re-weight. Future: incorporate `verified`/`stale`/`links` as
  ranking signals; experiment with prompt-level re-ranking. Wait until the
  v2 corpus has enough verified entries to make ranking changes measurable.
- **MCP server write tools.** Staying read-only. Future possibility: an
  `mcp_save_memory` tool callable from any Claude instance (Desktop,
  claude.ai). Requires careful auth + audit-trail design.
- **Memory archival / cold storage.** Decay erases transient categories but
  doesn't move them anywhere — they're gone. Could archive instead, with a
  separate query layer for historical research. Defer until decay actually
  loses something we wish we had.
- **Cross-machine extraction coordination.** Hooks run independently on
  each machine; coordination is via the daily-sync. Race window is small
  but real (saw this on 2026-05-14). Could coordinate via the Postgres
  layer. Defer unless the race becomes a real problem.

## C. Session-start payload reduction (vector 2)

Acknowledged 2026-05-15 as a known problem requiring its own design pass.
Captured here so it doesn't get lost.

Observed payload at one session start (2026-05-14): 43.6 KB of recall
memories alone, plus harness-injected `# auto memory` (~150-250 lines),
plus skills listings, plus tool schemas, plus CLAUDE.md (143 lines), plus
project CLAUDE.md (90 lines). The recall dump is the fattest controllable
channel.

Open questions for the eventual design:

- **Lazy vs. eager loading.** Should session-start dump *anything* by
  default, or load on first `/recall` invocation? A small "what changed
  since last session" digest may still be valuable; the full 30-entry
  dump probably is not.
- **Channel budget.** Set an explicit budget (e.g. ≤4 KB) for the
  session-start retrieval hook, and force it to choose what to surface.
- **Anti-confabulation framing in the dump itself.** Currently the
  banner says "pointers, not authorities". With v2 `verified` field, the
  dump could de-weight or omit unverified entries entirely.
- **Differential surfacing.** Only show memories whose anchors *do* still
  resolve (per the drift sweep), since stale ones are exactly the
  primacy-effect risk.

Not a v2 item. Open a separate planning doc when ready.

## D. Other deferred ideas surfaced during v2 design

- **Schema versioning on memory records.** A `schema_version` field per
  record would make future migrations cleaner. v2 introduces fields without
  versioning; if v3 ever changes shape incompatibly, this gap matters.
- **`why_not` field for `decision` and `gotcha`.** Captures rejected
  alternatives. Useful for re-litigating decisions years later. Defer until
  we miss it.
- **Confidence interval on the verifier.** Currently the output verifier is
  binary (caught a confabulation / didn't). A confidence score on each
  flagged item would let us tune thresholds. Belongs to the verifier
  workstream, not memory v2.
- **Memory `provenance` chain.** A memory derived from another memory (via
  reprocessing) currently loses the chain. A `derived_from` link would help
  trace contamination after the fact. Phase 4 typed-links covers some of
  this; a dedicated provenance relation may be worth adding to the relation
  vocabulary later.

## E. How to use this doc

- When a v2 implementation session surfaces something out of scope, add an
  entry here rather than expanding the v2 plan.
- When something in here graduates to being worth doing, lift it into a
  proper planning doc of its own.
- Periodically (e.g. during `/retro`), review whether any entry has become
  load-bearing and should be promoted.
