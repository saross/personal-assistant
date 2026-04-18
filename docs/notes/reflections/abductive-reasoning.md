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

