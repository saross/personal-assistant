---
priority: 3
scope: conditional
title: "Abductive Reasoning Investigation"
audience: "researchers and future instances"
conditions: "Update when the session produced a surprising finding,
  a belief revision, or a hypothesis that was tested and either
  confirmed or disconfirmed."
---

# Abductive Reasoning — personal-assistant

Surprising-fact → probe → belief-revision sequences observed during
sessions in the `personal-assistant` project. Part of an ongoing
cross-project research investigation into AI reasoning patterns.

Only updated when a session produced a genuinely surprising finding
or a non-trivial revision of prior beliefs. The conditional trigger
keeps entries sharp — if you find yourself writing a forced entry to
satisfy the template, the session didn't warrant one.

Entries are numbered sequentially and dated.


## Entry 1 — 2026-04-17: Partial grounding collapse at the synthesis boundary

**Session anchor (retro-matched 2026-07-22):** `2026-04-16T05-06_comprehensive-agent-workflow-training-and` — session `6e7ef1fd-541d-4ddd-a949-e82443cb34e1`, confidence: transcript-confirmed.

### Surprising fact

The v1 lit-scout agent produced output that *looked* rigorous:
37 papers in a findings table, chain-provenance annotations,
convergence scores, thematic clusters, venue-match analysis, Zotero
dedup flags. The DOIs were correct. The titles were correct. The
citation counts were mostly reasonable.

A four-row spot-check found that **three of four author attributions
were wrong** — and wrong in a specific way: the DOI resolved to a real
paper, but the agent had attached *different authors' names* to that
paper in its report text. "Messeri & Crockett (2024)" at a PNAS DOI
whose real authors were Binz, Alaniz, Roskies (2025). "Jalilian et al.
(2025)" at a JDV DOI whose real authors were Keplinger, Frashure,
Duran. "Walters (2023)" at a Cureus DOI whose real authors were
Alkaissi & McFarlane.

The agent's system prompt contained an explicit constraint:
*"Never fabricate citations — every DOI, title, author, and year must
come from an API response, MCP tool result, or Zotero record."*
The constraint was in effect. The constraint failed.

### Probe

Why would an explicit anti-fabrication instruction work for some
fields and fail for others? The obvious hypothesis — "the agent
ignored its instructions" — does not fit, because DOIs and titles
were correctly grounded. Something more specific is going on.

The difference between the field-types: DOIs and titles in the
findings table came from a dedicated retrieval step (`metadata DOI`
via the helper script). Authors came from *the same metadata response*
— the API returned authors alongside DOI and title — but the agent's
report-construction step did not consult the retrieved data for the
"Authors (Year)" column. It synthesised that column from training-
data memory of who writes papers at that venue on that topic.

The retrieval boundary was clean. The synthesis boundary was porous.

### Belief revision

The failure mode is not "the agent fabricated citations." It is more
specific: **when a workflow combines grounded retrieval with LLM
synthesis of a report, confabulation leaks in at the synthesis step
even when the retrieval was correct, and even when an explicit
anti-fabrication constraint is in force.** Retrieval grounding does
not propagate to narrative columns automatically. Every field in the
output needs to be individually traceable to a retrieval, or it is at
risk of synthesis-boundary confabulation.

The architectural consequence: a same-context self-check cannot catch
this. The same agent that did the porous synthesis is the one asked to
review its own output; it re-reads its own narrative columns and finds
them self-consistent (which they are — the confabulation is
internally coherent). The guard has to be in a **fresh context
window** that cannot share the proposer's narrative memory. This is
not stylistic. It is the only kind of guard that has epistemic
independence from the source of the error.

The proposer-verifier pattern from map-reader-llm (paired evaluators
for independent judgement) turned out to be the right scaffolding
transferred. `lit-scout-verifier.md` now runs as the final phase of
lit-scout, in an independent sub-agent context, re-querying metadata
for every row and producing corrections that the proposer cannot
override.

### Generalisation

**Partial grounding collapse** (or: narrative-column confabulation):
a workflow with both grounded-retrieval and LLM-synthesis stages will
produce confabulated narrative columns even with explicit
anti-fabrication constraints and grounded input data. The retrieval
was honest; the synthesis was not. Every output field needs its own
verification path.

This is directly relevant to Paper B's contribution 1 (a failure
taxonomy for LLM scholarly information work). The taxonomy as
drafted includes "confabulation" as a category; the partial-grounding-
collapse pattern is a more specific variant where the confabulation
is *architecturally localised* at the synthesis boundary. The
implication for the paper's contribution 3 (researchers' workbench
design requirements) is that verification must occur at field
granularity in a context epistemically independent of the synthesis
context. A single "review your work" step in the same context will
not catch it.

### Consequence for the project

Two guards were added in response to the finding, at different
architectural levels:

- **Workflow-level (Guard A).** `agents/lit-scout.md` updated with a
  mandatory metadata-verification phase (Phase 6): the proposer must
  run `metadata DOI` on every candidate and populate narrative
  columns from the returned JSON verbatim.
- **Architectural (Guard B).** `agents/lit-scout-verifier.md` created
  as a fresh-context adversarial sub-agent, spawned at Phase 8 to
  re-verify every row after the proposer drafts. Adversarial framing
  ("assume the proposer made mistakes").

Plus:

- Observation written up in `data/notes/paper-b-working-notes.md`
  as candidate taxonomy material for Paper B.
- Extended case study at `data/notes/lit-scout-case-study.md` —
  now with a correction (added 2026-04-19) distinguishing which
  guard was empirically tested.

### Confidence note (revised 2026-04-19 after transcript
re-inspection)

**Session anchor (retro-matched 2026-07-22):** `2026-04-16T05-06_comprehensive-agent-workflow-training-and` — session `6e7ef1fd-541d-4ddd-a949-e82443cb34e1`, confidence: transcript-confirmed. (Revision authored near session close: Edit at 2026-04-18T06:39Z, commit `9f3d909`. Archive completed 2026-07-22: the earlier snapshot ended 2026-04-18T00:03Z mid-session; the full transcript to 2026-04-18T07:10Z was re-archived from zbook.)

The 75% spot-check rate (3/4 rows) is a small-sample estimate, not a
population rate. The direction of the finding is robust (multiple
independent mis-attributions on distinct papers in a single run); the
magnitude would need a larger audit to pin down.

**Which guard was empirically validated matters and I got this
wrong on first pass.** The v2 run's transcript
(`/tmp/.../a863ecaade9efa6b4.output`, 90 lines, 35 tool calls) shows
no Agent tool calls at all. The stream died during Phase 7
(draft-building) before Phase 8 (verifier sub-agent) was spawned. The
correct author attributions observed in the v2 partial output (and
in the BibTeX file that made it to disk) were produced by Guard A
alone — the mandatory Phase 6 metadata-re-query step inside the
proposer's own workflow.

So:

- **Guard A (workflow-level):** *validated.* The procedure-level fix
  (mandatory per-field retrieval) prevented the confabulation. The
  original prompt-level "never fabricate" constraint failed; its
  procedural replacement succeeded. This is the empirical finding.
- **Guard B (architectural sub-agent):** *present but untested.* It
  exists in the codebase and is wired into lit-scout's Phase 8, but
  has not run against a real confabulation. Its value remains
  theoretical and should not be claimed as validated in the paper.

The belief-revision in this entry (partial grounding collapse at the
synthesis boundary; same-context self-checks cannot catch this;
independent-context guards are the structural backstop) is supported
by the v1 failure but the *architectural* part of the fix has not
yet been tested against that failure mode. The v1→v2 arc
demonstrates that a procedural fix within the same context was
sufficient this time; the claim that only an architectural fix
*could* work remains conjectural until the architectural guard fires
against a real confabulation.

### Further update (2026-04-18, after v3 scrutinised test)

**Session anchor (retro-matched 2026-07-22):** `2026-04-18T07-11_executed-lit-scout-v3-test-protocol-and` — session `6f5ba855-ca71-491e-8f53-3e67ab87da8a`, confidence: transcript-confirmed.

The v3 test (fresh query: Bayesian archaeological dating uncertainty,
25 rows) established two things that refine the confidence picture:

**1. Guard B as designed cannot fire from inside lit-scout.**
Claude Code's harness explicitly forbids sub-agents from spawning
sub-agents (docs/sub-agents.md line 469). lit-scout runs as a
sub-agent, so Phase 8's nested-sub-agent dispatch is not a
contingent failure mode — it is an architectural impossibility. A
corpus-wide audit of 1,363 sub-agent transcripts found zero nested
Agent calls from any user-authored sub-agent. The v3 proposer
inspected its runtime tool registry, found Agent absent, and fell
back to same-context verification with explicit self-disclosure.

This means the claim "independent-context guards are the structural
backstop" is not weakened empirically — it is **not yet evaluable
in this harness at all** via the sub-agent dispatch mechanism. A
main-conversation chained architecture (main assistant invokes
lit-scout, then separately invokes lit-scout-verifier with the
draft) is realisable and would allow the claim to be tested. Not
yet attempted.

**2. Same-context adversarial framing catches at least some
errors that same-context drafting misses.** v3 Row 16 is a real
Level-1 author-attribution error: CrossRef encoded Philippe Lanos
& Anne Philippe with family/given ambiguity; the drafter wrote
"Philippe & Philippe" at 07:21:11; the verification pass at 07:26:01
re-queried the same DOI, received the same response, and correctly
parsed it as "Lanos & Philippe." Same model, same context, same
tool, same data. Different framing (drafting vs adversarial
verification). Different outcome.

This is a **weaker** claim than context-independent verification,
but an empirically defended one. It slightly revises the
"same-context self-checks cannot catch this" part of the original
belief revision: at least in the specific case of surface-pattern
confabulation, *a differently-framed same-context pass* can catch
errors that a drafting pass misses. The mechanism is likely
attentional: verification framing invites domain-knowledge
cross-checks (Row 16 required recognising that CrossRef's `family`
field is wrong for this record, which requires domain knowledge
about the ChronoModel authorship).

**Net effect on confidence:**

- Guard A validated (unchanged from 2026-04-19 update).
- Guard B "present but untested" → **"as designed, architecturally
  unrealisable; a redesign via main-conversation chaining is
  possible but untested."**
- Framing-based intra-context verification → **new category with
  one supporting data point.** Weaker than context-independent
  verification. Useful as a defence-in-depth layer even when
  context-independence is unavailable. Worth tracking across
  future runs to see whether the Row 16 result replicates or was
  idiosyncratic.

The "only an architectural fix could work" claim is now more
carefully bounded: architectural fixes *of a particular kind*
(nested sub-agent spawning) don't work because they can't exist.
Architectural fixes *of another kind* (main-conversation chaining)
remain possible but are not yet evidenced. And we now have a small
piece of evidence that procedural same-context verification *with
adversarial framing* may be a non-trivial partial substitute.

### Further update (2026-04-19, after the v4.x serial-agent arc)

**Session anchor (retro-matched 2026-07-22):** `2026-04-18T07-11_executed-lit-scout-v3-test-protocol-and` — session `6f5ba855-ca71-491e-8f53-3e67ab87da8a`, confidence: transcript-confirmed. (Same session as the 2026-04-18 update above; the v4.x arc ran 2026-04-19 within it, and the update was authored near session close: Edit at 2026-04-19T10:50Z, commit `8136074`. Archive completed 2026-07-22: the earlier snapshot was a 474-line mid-session capture; the full transcript to 2026-04-19T12:12Z was re-archived from zbook.)

Four additional lit-scout test runs on 2026-04-19 substantially
refine the confidence picture:

**1. Main-conversation chained architecture is now empirically
realised.** v4 (maps/VLMs), v4.1 (Latin inscriptions + SPA), v4.2
(ABM Mediterranean economies), v4.3 (magnetometer prospection) all
successfully ran the serial-dispatch pipeline with proposer and
verifier as separate sub-agent invocations. Test A (serial dispatch
fires), Test B (context independence), Test D (no main-assistant
contamination) passed on all four runs. The earlier
"main-conversation chaining is possible but untested" claim is now
"tested four times, works reliably."

**2. Two additional catching-power data points surfaced, but
they're weaker than v3's Row 16.**

- v4 (38 rows): 0 corrections.
- v4.1 (36 rows): 1 correction — Row 4 Crema (2024) → (2025),
  accept/print date ambiguity that the proposer's self-check had
  also flagged. Catching-power attributable mostly to the
  metadata-authoritative convention rather than to detecting
  narrative confabulation.
- v4.2 (31 rows): 0 corrections.
- v4.3 (45 rows): 0 corrections.

So across five runs (v3 + v4 series), n=2 verifier-caught errors
on 175 total rows (~1%). v3's Row 16 is the one clear
confabulation-catch; v4.1's Row 4 is a date-ambiguity. Catching
power remains "non-zero but small, and contingent on specific
proposer failure modes rather than routine in well-disciplined
drafts."

**3. Sub-agent persistence is unreliable across every spec variant
tried.** The v4.1 Bash-heredoc receipt-stub was an opportunistic
post-Write-block fallback, not a reproducible design. Subsequent
attempts to prescribe a sub-agent-written receipt failed: v4.2
(Option A+ prescription) ignored; v4.3 (Option C Step-1 positioning
+ prescription) ignored. The verifier in v4.3 explicitly cited a
harness-injected system reminder as authoritative over spec text.
This is a significant finding: there exists a higher-priority
instruction channel (harness system-reminders) that sub-agent
spec text cannot override for concrete tool-choice/persistence
decisions.

**4. "Domestication" principle holds but requires architectural
rather than textual mechanism.** Initial framing in
`data/notes/paper-b-working-notes.md` (morning of 2026-04-19)
claimed domestication worked via spec text. v4.2/v4.3 showed it
doesn't. The refined framing: domestication as a design principle
is achieved architecturally — move the responsibility to a layer
where the prior doesn't fire — not textually. Orchestrator-only
persistence (current pure-Option-A spec, committed after v4.3) is
the architectural instantiation.

**Net confidence update:**

- Main-conversation chained verification: *realisable and tested
  across 4 runs.* Strong confidence.
- Independent-context catching power: *non-zero but modest* (n=2
  across 5 runs). Confidence lower than the v3 Row-16 moment
  implied.
- Spec-text control over sub-agent behaviour: *not reliable* for
  concrete persistence/tool choices. Low confidence in textual
  coaxing as a design tool.
- Architectural domestication: *reliable in this case.* High
  confidence that moving responsibility up the layering removes
  prior-fighting from the design space.

Paper B should foreground the serial-dispatch design as
empirically validated; introduce the architectural-domestication
refinement as the 2026 worked example; treat catching power as a
cautious, small-n finding that motivates the independence argument
without overclaiming.
