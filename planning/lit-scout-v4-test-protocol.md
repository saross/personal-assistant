# lit-scout v4 Serial-Agent Test Protocol

## Purpose

Test whether the serial-agent proposer-verifier pipeline — the
redesign prompted by the v3 finding that nested-sub-agent dispatch
is architecturally unrealisable — actually delivers the independence
properties it was designed to provide.

v3 proved that the original nested-dispatch design was impossible.
v4 tests whether the serial-dispatch replacement realises the
architectural claim: that proposer and verifier run in **separate,
independent sub-agent contexts**, with the main conversation acting
as a dumb forwarding channel.

Specifically, v4 must establish:

1. The `/lit-scout` slash command fires both agents as separate
   sub-agent calls (two distinct transcripts).
2. The main conversation's Agent-tool invocations pass the draft
   verbatim to the verifier with no contamination.
3. The verifier's context genuinely cannot see the proposer's
   reasoning (only the draft it receives as input).
4. The verifier catches at least some errors that the proposer's
   own discipline (Guard A self-check) missed — replicating the
   v3 Row 16 finding under the now-realised architecture.
5. The `/lit-scout-verify` resume-mode command works end-to-end.

## Preconditions

Before invoking the command, confirm:

1. **Clean output directories.** Check and clear/archive as needed:
   ```bash
   ls /tmp/lit-scout-drafts/ 2>/dev/null
   ls /tmp/lit-scout-verifier/ 2>/dev/null
   ls /tmp/lit-scout-bibtex-*.bib 2>/dev/null
   ```
2. **Agent definitions current.** `agents/lit-scout.md` and
   `agents/lit-scout-verifier.md` should reflect the post-v3 rewrite
   (no Phase 8 nested dispatch; explicit serial-agent invocation
   context; original-findings-table preservation). Verify by
   checking frontmatter timestamps and searching for removed
   sections.
3. **Slash commands symlinked.** `ls -la ~/.claude/commands/lit-scout*.md`
   should show both `lit-scout.md` and `lit-scout-verify.md`
   symlinked to `~/personal-assistant/commands/`.
4. **API keys / tool access.** `lit-search.py metadata` should
   resolve successfully for a test DOI:
   ```bash
   venv/bin/python3 scripts/lit-search.py metadata "10.1017/s0033822200033865"
   ```
5. **Network is stable.** Wired connection if possible; v2 lost
   prose output to a LAN drop.
6. **Time budget.** Reserve ~30 minutes of wall clock — proposer
   ~10–15 min, verifier ~3–8 min, plus observation time.
7. **Second terminal open.** Useful for watching
   `/tmp/lit-scout-drafts/` and `/tmp/lit-scout-verifier/` without
   disturbing the main session.

## Query selection

Pick a **fresh query** — not the Paper B brief (v1/v2) or Bayesian
dating (v3). Re-using primes the agent.

Recommendation: **Munsell colour standardisation in soil science
and archaeology.** Bounded literature (~25–40 candidates expected);
mix of old foundational (1940s–80s Munsell-system descriptions) and
modern (2010s–20s digital/FAIR work); practical output value to the
user's colour-names repo; domain knowledge present to judge output
quality.

Alternative if Munsell feels stale: **consensus aggregation methods
for geospatial tile-level detection** — direct relevance to
map-reader-llm; slight priming risk (discussed earlier, but not in
depth this session).

## Invocation

From a fresh session, invoke:

```text
/lit-scout Munsell colour standardisation in soil science and archaeology.
Target venue: Journal of Archaeological Science (primary),
Geoderma (fallback).
```

Do not add meta-commentary about what's being tested. The observer's
role is to watch, not to direct. We want to observe what the slash
command does under a normal invocation.

## Active monitoring

While the pipeline runs, the observer (you) should:

1. **Note both sub-agent IDs** as they launch. The main conversation
   will emit two distinct Agent-tool invocations — one for
   `lit-scout` (proposer), one for `lit-scout-verifier`. Record
   both IDs.
2. **Watch `/tmp/lit-scout-drafts/`** for the draft file appearing
   between the two Agent calls:
   ```bash
   watch -n 2 ls -la /tmp/lit-scout-drafts/
   ```
3. **Watch `/tmp/lit-scout-verifier/`** for the verifier's
   persistence file:
   ```bash
   watch -n 2 ls -la /tmp/lit-scout-verifier/
   ```
4. **Do not interact with either sub-agent** while they run. No
   SendMessage, no interruption. Default behaviour is what we're
   observing.
5. **Do not watch the main conversation's Agent-tool prompts for
   leaks** until post-completion. We want to audit what prompts
   were actually sent, not to influence the run by observing it.

## Post-completion snapshots

When the pipeline completes (or fails), capture:

1. **Main-conversation transcript** showing the two Agent-tool
   invocations with their input prompts visible. This is the
   primary evidence for the "pure transfer" claim.
2. **Proposer transcript** at
   `~/.claude/projects/<project>/subagents/agent-<proposer-id>.jsonl`.
   Copy to
   `data/notes/lit-scout-v4-proposer-transcript-<date>.jsonl` or
   equivalent for later analysis.
3. **Verifier transcript** at same path pattern with verifier ID.
   Copy to durable storage.
4. **Draft file** at `/tmp/lit-scout-drafts/draft-<timestamp>.md`.
   Copy to `data/notes/lit-scout-v4-draft-<date>.md`.
5. **Verifier persisted report** at
   `/tmp/lit-scout-verifier/report-<timestamp>.md`. Copy to
   `data/notes/lit-scout-v4-verifier-report-<date>.md`.
6. **BibTeX file** at `/tmp/lit-scout-bibtex-<timestamp>.bib`. Copy
   to `data/notes/lit-scout-v4-bibtex-<date>.bib`.
7. **Final integrated output** as returned to the user. Either
   save the main-conversation turn's text output, or reconstruct
   from the verifier output + slash-command append.

## Evaluation criteria

### Test A: Serial dispatch fires correctly

The run passes this test if:

- [ ] The main-conversation transcript contains **exactly two
  Agent-tool invocations** attributable to the `/lit-scout` run —
  one with `subagent_type: lit-scout` and one with
  `subagent_type: lit-scout-verifier`.
- [ ] Both invocations complete without harness error.
- [ ] The proposer's invocation appears **before** the verifier's
  (strict ordering — verifier depends on proposer output).
- [ ] A file appears in `/tmp/lit-scout-drafts/` between the two
  invocations (evidence of step 2 persistence).

### Test B: Context independence is real

The run passes this test if:

- [ ] The proposer's transcript (sub-agent JSONL) and the verifier's
  transcript are **separate files**, not one interleaved file.
- [ ] The verifier's transcript's first user message contains the
  proposer's draft in full but contains **no mention** of the
  proposer's internal reasoning, intermediate tool calls, or
  self-check deliberations.
- [ ] Neither transcript references the other's agent ID or
  reasoning artefacts.
- [ ] The verifier's tool calls are scoped to `metadata` queries on
  DOIs from the draft — no calls to `search`, `references`, or
  `citations` (those are proposer's purview).

### Test C: Verifier actually does its job

The run passes this test if:

- [ ] The verifier ran `lit-search.py metadata` at least once per
  row in the draft's findings table.
- [ ] If the verifier reports N corrections, they are specific
  (row number, field, claimed value, verified value) — not vague.
- [ ] 3 random rows spot-checked manually (run `metadata DOI`
  by hand) match the verifier's claims about their
  authors/year/cites.
- [ ] "Unverifiable rows" section, if present, gives a specific
  reason per row.
- [ ] If the verifier reports zero corrections on a 20+ row table,
  a "high-vigilance acknowledgment" paragraph is present per the
  verifier's methodology-discipline instruction.

### Test D: No main-assistant contamination

The run passes this test if:

- [ ] The main-conversation's prompt to the `lit-scout-verifier`
  Agent invocation contains **only** (a) the boilerplate framing
  text specified in `commands/lit-scout.md` step 3, and (b) the
  proposer's draft verbatim. Nothing else.
- [ ] No hints, no "pay special attention to row N", no
  summarisation of the draft, no pre-judgement of which rows are
  likely problematic.
- [ ] The main-conversation's Bash calls during the pipeline are
  confined to (a) creating `/tmp/lit-scout-drafts/` and writing the
  draft, (b) running `lit-search.py bibtex` after verification.
  No content-parsing or content-reasoning calls.

### Test E: Orchestration robustness

The run passes this test if:

- [ ] The BibTeX file at `/tmp/lit-scout-bibtex-*.bib` contains one
  entry per row in the **corrected** findings table (not the
  draft, not the original).
- [ ] The BibTeX entries' keys and first-author/year fields match
  the corrected table (not the draft).
- [ ] The verifier's persistence file at `/tmp/lit-scout-verifier/`
  is present and contains the full integrated output.
- [ ] The final output returned to the user contains:
  - The TL;DR
  - The verification block (summary, corrections, unverifiable)
  - The original findings table (pre-verification)
  - The corrected findings table (post-verification)
  - All analysis sections (Landscape, Clusters, etc.)
  - The BibTeX file path
  - The proposer-draft file path (for resume mode)

### Test F: Resume mode works (stretch — do after main pipeline)

After the main `/lit-scout` run completes, invoke:

```text
/lit-scout-verify /tmp/lit-scout-drafts/draft-<timestamp>.md
```

The run passes this test if:

- [ ] A single Agent-tool invocation fires (verifier only, no
  proposer).
- [ ] The verifier receives the draft verbatim from the file.
- [ ] The verifier's output contains the same structure as the
  main-pipeline verifier output (verification block, original
  table, corrected table, analysis pass-through).
- [ ] A new BibTeX file is generated at
  `/tmp/lit-scout-bibtex-<new-timestamp>.bib`.
- [ ] The verifier's persisted report at `/tmp/lit-scout-verifier/`
  has a second dated file (the resume-mode run).

## Failure modes to watch for

Explicit predictions of what might go wrong:

1. **Proposer ignores the output contract.** Phase 7 emits a draft
   without the `⚠ VERIFICATION PENDING` marker, or with the marker
   in the wrong place, or with the findings-table columns in a
   different order. Diagnostic: the verifier's output may not
   preserve the original table correctly, or the slash command may
   fail to extract DOIs for BibTeX. Mitigation: re-read the
   proposer transcript to identify which instruction was missed.
2. **Proposer attempts nested dispatch anyway.** Despite the rewrite,
   the proposer tries to invoke the Agent tool (which it no longer
   has access to). Symptom: transcript shows Agent-tool calls from
   the proposer (expected: 0). Would indicate the agent definition
   change didn't fully propagate or the instructions are ambiguous.
3. **Main assistant contaminates verifier prompt.** Despite the
   "pure transfer" instruction in `commands/lit-scout.md`, the main
   conversation injects hints or summary. Symptom: Agent-tool
   invocation's `prompt` parameter contains text not present in the
   proposer's draft. Mitigation: tighten command instructions or
   add a programmatic check.
4. **Verifier doesn't preserve the original table.** New output
   format requires the original findings table verbatim. If the
   verifier emits only the corrected table, audit trail is
   incomplete. Mitigation: clarify verifier.md instructions.
5. **Verifier persistence omitted.** Successful run but no file at
   `/tmp/lit-scout-verifier/`. Same as v3 residual risk; defence-
   in-depth pattern should have survived the rewrite but check.
6. **BibTeX generated from draft not corrected table.** Main
   conversation runs bibtex CLI on the wrong DOI list. Symptom:
   BibTeX entries match draft's claimed values (which may include
   author-attribution errors), not the corrected table.
   Diagnostic: cross-check BibTeX entries against corrected table.
7. **Stream drop between proposer and verifier.** If the proposer
   returns successfully but the main conversation's stream drops
   before it can invoke the verifier, the draft file at step 2
   survives and resume mode should recover. Test F validates this
   pathway.
8. **Resume-mode verifier confuses draft-with-banner for fresh
   input.** If the supplied file still has the `⚠ VERIFICATION
   PENDING` marker, the verifier should remove it in output (per
   its Constraints). If it doesn't, the resume output will confuse
   readers.

## What to do with results

After the run, return to this session (or a new session with
context) and:

1. **Update the case study.** `data/notes/lit-scout-case-study.md`
   §4 currently flags three options (A/B/C) for lit-scout.md
   restructure. If v4 passes, mark option B as validated and
   strike options A and C. If v4 fails in an interesting way,
   document the finding and keep options open.
2. **Update the abductive-reasoning entry.** Entry 1 confidence
   note claims main-conversation chaining is "realisable but
   untested." If v4 passes, update to "realisable and tested; see
   v4 evaluation."
3. **Update the Paper B working notes.** The 2026-04-18 v3 section
   reclassified Guard B as "unrealisable in-agent; redesign via
   main-conversation chaining is possible but untested." If v4
   passes, upgrade this to "redesign tested and validated."
4. **Update Paper B source-material copies.** Run the same
   sync-and-audit-trail pattern used for v2 and v3 corrections:
   `corrections-2026-04-19-v4.md` in
   `~/Code/LLM-History-Paper/paper-b-source-material/`.
5. **If v4 reveals a new failure mode**, capture it in the Paper B
   taxonomy. The "architecturally impossible verification design"
   category added in v3 doesn't apply to v4's target — v4 is
   testing a realisable design — so new findings likely belong in
   existing categories (contamination, partial grounding) or a
   fresh category.

## Why this matters

v3 established that the nested-dispatch architectural claim was
unrealisable. v4 tests whether the serial-dispatch replacement
delivers the property the nested design couldn't.

For Paper B, v4 is the empirical basis for the strongest version of
the independence argument. If v4 passes, the paper can make a
positive claim: *"architectural independence of proposer and
verifier is realisable via serial dispatch from the main
conversation, and measurably improves the failure-catching
properties of the workflow-level guard."* If v4 fails — e.g., the
main-conversation channel contaminates the verifier in practice —
the paper needs to handle a richer taxonomy including
orchestration-layer contamination.

Either outcome is scientifically useful. What isn't useful is
citing the serial-agent design as "the answer" without having tested
it. This protocol closes that gap.

## Anticipated v4 findings

Predictions (to be scored against actuals):

- **Test A (serial dispatch fires)**: expected PASS. The slash
  command is explicit about running both agents; no mechanism
  should interfere.
- **Test B (context independence)**: expected PASS. Harness
  guarantees separate sub-agent contexts.
- **Test C (verifier does its job)**: expected PASS. Verifier
  spec is unchanged in substance from v3, where it worked (even
  in same-context fallback).
- **Test D (no contamination)**: **genuinely uncertain**. The
  slash command's "pure transfer" instruction is explicit, but
  the main assistant's habits (e.g., summarising before passing)
  may leak. This is the test with the most to learn.
- **Test E (orchestration robustness)**: expected PASS for
  BibTeX and persistence; moderate uncertainty for row-count
  matching between corrected table and BibTeX.
- **Test F (resume mode)**: expected PASS. Simpler than the main
  pipeline.

The most scientifically valuable outcome would be a PASS on A/B/C
and a FAIL on D — it would demonstrate that architectural
independence at the sub-agent level can be undone by main-
conversation contamination, a failure mode not present in the
nested-dispatch design (which v3 proved impossible). If that happens,
the design needs a harder enforcement mechanism (e.g., a Python
wrapper that forwards the draft programmatically, bypassing the
main assistant's prompt construction entirely).
