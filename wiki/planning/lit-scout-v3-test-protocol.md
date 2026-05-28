# lit-scout v3 Scrutinised Test Protocol

## Purpose

Run a deliberate, observable test of `lit-scout` that validates
what the v1→v2 arc only *implied*: specifically, that the Phase 8
adversarial verifier sub-agent (Guard B) actually fires, actually
re-queries metadata in a fresh context, and produces a corrections
audit trail that survives to disk.

The v2 run on 2026-04-17 demonstrated that Guard A (the Phase 6
mandatory metadata re-query inside the proposer's workflow)
prevented the author-attribution confabulation that v1 exhibited.
But the stream died during Phase 7 before Guard B was reached, and
no Agent tool calls appear in the v2 sub-agent transcript. Guard B
has not been empirically tested.

This protocol fills that gap. Run it from a fresh session.

## Preconditions

Before invoking the agent, confirm:

1. **Clean output directory.** `ls /tmp/lit-scout-verifier/ 2>/dev/null`
   should be empty or non-existent. If prior runs are present, move
   them or clear them so a new run is unambiguous.
2. **Fresh BibTeX target.** No stale file at
   `/tmp/paper-b-lit-scout-*.bib` or similar from prior tests —
   otherwise timestamps may collide and make attribution ambiguous.
3. **Verifier persistence is in place.** Read
   `agents/lit-scout-verifier.md` and confirm the "Persist the
   verification report to disk (mandatory)" section is present.
   Added 2026-04-19. If absent, the test cannot proceed as
   specified.
4. **Network is stable.** Test on a wired connection if possible.
   The v2 test lost prose output to a LAN drop; we want to see
   what Phase 8 does on a clean run first, before stress-testing
   resilience.
5. **Time budget.** Reserve ~30 minutes of wall clock. A clean
   v2-equivalent run takes ~10 minutes; the added verifier phase
   adds 3–8 minutes depending on the number of rows to re-query.
6. **Second terminal open.** You will want to `watch` or `ls -la`
   `/tmp/lit-scout-verifier/` during the run to confirm the
   verifier has written to disk without disturbing the sub-agent.

## Query selection

Pick a **fresh query** — not the Paper B brief. Re-using the Paper B
query would prime the agent with context we have already reasoned
about extensively and would contaminate the test. Options (pick one):

- **Munsell colour standardisation in soil science and archaeology.**
  Good domain-knowledge match to the user; bounded literature;
  should surface a mix of old (1940s–80s) and new (2010s–20s) work.
  Useful practical output (feeds the colour-names repo).
- **Bayesian methods for archaeological dating uncertainty.**
  Genuinely unfamiliar enough to minimise priming; well-populated
  literature; a venue-analysis pass will have varied targets.
- **Consensus aggregation methods for geospatial tile-level
  detection.** Direct relevance to map-reader-llm; the user has
  been looking for peers on this specific methodological problem.
  Slight priming risk (we've discussed this).

Recommendation: **Bayesian dating uncertainty** — minimises priming
while still being a domain where the user can judge output quality
(knows the field but hasn't been reasoning about specific papers in
this session).

## Invocation

From a fresh session, give lit-scout a brief like:

```text
Run lit-scout on a literature scout of [chosen query].

Target venues: [venue 1] (primary), [venue 2] (fallback).

Follow `~/.claude/agents/lit-scout.md` exactly. Phase 8
(adversarial verification) is mandatory — spawn the verifier
sub-agent and integrate its output verbatim.

This is a scrutinised test per
`planning/lit-scout-v3-test-protocol.md`. Snapshot outputs as
specified in that document.
```

Keep the brief short. Do not brief the agent with priming context
about what we are testing — we want to observe what the agent
actually does under a normal invocation, not what it does when it
knows it is being tested on a specific failure mode.

## Active monitoring

While the agent runs, the observer (you) should:

1. **Note the sub-agent ID** as soon as lit-scout launches. It appears
   in the background-agent launch confirmation.
2. **Watch `/tmp/lit-scout-verifier/`** in a second terminal:
   ```bash
   watch -n 2 ls -la /tmp/lit-scout-verifier/
   ```
   When a file appears, it means Phase 8 completed. Timestamp it.
3. **Do not interact with the sub-agent** while it runs — no
   SendMessage, no interruption. The point is to observe default
   behaviour.
4. **Time the phases** if you can infer them from tool-call
   descriptions visible via the harness UI:
   - Phase 1 (seeds): first 2–3 minutes
   - Phase 3 (chains): next 3–5 minutes
   - Phase 5–7 (Zotero, metadata, draft): next 3–5 minutes
   - Phase 8 (verifier sub-agent): **the phase we are testing**
   - Phase 9 (integration): final 30–60 seconds
   - Phase 10 (BibTeX): ~10 seconds

## Post-completion snapshots

When the run completes (or dies), capture:

1. **Verifier report.** Copy
   `/tmp/lit-scout-verifier/report-<timestamp>.md` to
   `data/notes/lit-scout-v3-verifier-report-<date>.md`. This is the
   primary empirical output.
2. **BibTeX file.** Whatever was generated at
   `/tmp/paper-b-lit-scout-*.bib` (or equivalent per the agent's
   default path).
3. **Sub-agent transcript.** Before `/tmp` is cleaned, copy
   `/tmp/claude-*/-home-shawn-personal-assistant/*/tasks/<agent-id>.output`
   somewhere durable. Without this we cannot confirm whether
   nested Agent tool calls appeared (i.e., whether the verifier
   was actually spawned).
4. **Main session's final output.** The parent conversation's last
   message containing lit-scout's return value. This is what the
   user normally sees.

## Evaluation criteria

The run passes the **"Phase 8 actually ran"** test if:

- [ ] A file exists at `/tmp/lit-scout-verifier/report-<timestamp>.md`
  **and** it contains a Summary block with "Rows verified: N"
  where N matches the size of the findings table.
- [ ] The sub-agent transcript contains at least one `Agent` tool
  call (distinct from the outer Agent call that spawned lit-scout
  itself).
- [ ] The final output includes a "Verification" section with
  corrections-applied and/or no-corrections-required text.
- [ ] The final output's findings table row count matches the
  verifier's "Rows verified" count.

The run passes the **"verifier actually did its job"** test if:

- [ ] The verifier's metadata re-queries (visible in the sub-agent
  transcript) number ≥ the row count in the findings table
  (one metadata call per row, minimum).
- [ ] If any corrections are applied, they are specific (row number,
  field, claimed value, verified value) — not vague.
- [ ] The verifier's report matches the observable ground truth on
  3 random spot-checks (i.e., run `metadata DOI` by hand on 3
  random rows and confirm the verifier's claim about their
  authors/year matches).
- [ ] The "Unverifiable rows" section, if present, gives a specific
  reason per row (HTTP error, DOI format issue, etc.).

The run passes the **"no silent passing"** test if:

- [ ] If the verifier reports zero corrections on a 30+ row table,
  the verifier's output explicitly acknowledges this as a
  high-vigilance state (per its system prompt's "re-check before
  concluding clean" instruction).

## Failure modes to watch for

Explicit predictions of what might go wrong:

1. **Phase 8 never fires.** Lit-scout stops at Phase 9 integration
   without spawning the verifier. Sub-agent transcript has no
   `Agent` calls. Means: the instruction to spawn the verifier
   isn't being followed reliably. Diagnostic: check whether the
   proposer's output includes a "Verification" section anyway —
   if yes, the proposer is self-verifying (a same-context check
   that doesn't count) and claiming architectural independence it
   doesn't have.
2. **Verifier spawns but rubber-stamps.** Verifier reports
   corrections: 0 on a large table without genuinely re-running
   metadata. Diagnostic: metadata call count in sub-agent transcript
   should match row count; if much lower, the verifier is cheating.
3. **Same-context leak.** Verifier's report mentions specific
   analysis from the proposer ("the landscape summary says...") —
   a sign that the verifier had access to more than just the
   findings table. Should not happen if context isolation is
   working.
4. **Persistence file not written.** Phase 8 output is returned to
   parent but the durable file at `/tmp/lit-scout-verifier/` is
   missing. Means: the 2026-04-19 persistence instruction wasn't
   obeyed. Test is still informative but resilience gap remains.
5. **Network drop mid-Phase-8.** Same failure as v2 but now at a
   different phase. Durable file partial-or-missing; we learn what
   Phase 8 was in the middle of doing.

## What to do with the results

After the run, return to this session (or a new session with
context) and:

1. **Update the case study.** `data/notes/lit-scout-case-study.md`
   §4 currently says Guard B is "present but untested." If the
   test passes, update to "present and validated, run N on
   YYYY-MM-DD." If the test fails in an interesting way, capture
   the new finding.
2. **Update the abductive-reasoning entry.** Same file,
   `docs/notes/reflections/abductive-reasoning.md` entry 1's
   confidence note.
3. **Update the Paper B working notes.** The 2026-04-19 update
   section claims architectural independence is "not yet
   empirically settled." Reclassify per test outcome.
4. **If the test reveals a new failure mode**, capture it in
   `data/notes/paper-b-working-notes.md` as a candidate addition
   to Paper B's failure taxonomy. Every failure mode observed in
   a purpose-built tool with explicit guards is candidate
   taxonomy material.

## Why this matters

Paper B's argument depends on what actually happened, not what was
designed. A scrutinised test validates the architectural claim
(independent-context verification catches what same-context
self-checks miss), weakens it (the verifier rubber-stamps, revealing
that context-independence alone isn't enough), or refines it (the
verifier works but only under conditions X and Y). Any of those
outcomes is scientifically useful. What isn't useful is citing an
architectural fix as validated when in fact only a procedural fix
was tested.

This protocol exists to close that gap.
