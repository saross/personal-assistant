# lit-scout / lit-search Improvements Backlog

Future work identified during real-world testing of the lit-scout agent
and its helper script `scripts/lit-search.py`. Not urgent — the tool
works. These are polish, resilience, and feature additions that would
earn their cost over repeated use.

## Today's observations (from Paper B v2 run, 2026-04-17)

### Resilience

- **Network-drop recovery.** The Paper B v2 run died mid-stream
  from a LAN disconnection after ~10 minutes of API work. The
  BibTeX file had been written to disk so it survived; the markdown
  report (TL;DR, clusters, venue analysis, reading tiers) did not —
  had to relaunch a synthesis agent to reconstruct. Fix options:
    - (a) Write the report incrementally as each section completes,
      not only at the end
    - (b) Dump a "checkpoint" JSON after each phase containing
      verified table rows + cluster labels + any other state, so a
      resumed run can skip completed phases
    - (c) Flush prose progress to a log file that can be tail'd
      and rescued
  Pick (a) as simplest: instruction "write the report to
  `/tmp/lit-scout-report-{date}.md` after each phase, not only at
  end. Each Phase completes → file is rewritten with new content
  appended."

### Output design

- **Highest-confidence subset near the TL;DR.** The TL;DR names
  top-3 must-reads, but the findings table is heavy (28+ rows). A
  "**Read today (5 papers)**" subset between TL;DR and table — with
  a one-line "this is why" per paper — would speed the
  decision-of-what-to-open-first.
- **Venue-match signal more prominent.** Target-venue coverage is
  currently deep in Venue Analysis section. Promote a one-line
  summary ("Target venue fit: 1 of 28 in JASIST — the gap is the
  opportunity, but reviewers may lack shared vocabulary") to just
  after the TL;DR.
- **Confidence indicator per row.** Cite-count column is a decent
  proxy but not explicit. Consider adding a visible "verification
  status" column indicating the row is verifier-cleared, so users
  have instant confidence.

### Methodology

- **Network-failure-resilience protocol.** Related to (a) above —
  agent instruction "if an API call has been unresponsive for
  >60 seconds, checkpoint progress to disk before retrying."
- **Convergence metric refinement.** Chain-appearance count is
  narrow. Today's run didn't have many 2+ chain hits because the
  field is young. Thematic-cluster membership already helps, but
  consider a "citation-context similarity" score — papers whose
  BibTeX abstract (when available) shares vocabulary with >3 other
  candidates in the pool are topically central even if not found
  via chaining.
- **Strengthen Murton-et-al. pattern catch.** The Paper B v2 run
  flagged Murton et al. 2025 (*Cochrane Evidence Synthesis*) as the
  closest peer on prompt engineering as method — a non-LIS venue
  for a LIS-methods paper. Worth a methodology note: when the
  closest peer is outside the target-venue discipline, flag it as
  "discipline-mismatch peer" and note the implication for argument
  positioning.

## Earlier deferred items (from v1 audit, 2026-04-16)

Carried forward from the audit of commits `777e859` / `965bbce`:

- **`semanticscholar` Python library**: replace raw httpx calls to
  S2 with the `semanticscholar` package. Gets typed responses,
  automatic pagination, documented rate-limit handling. Only
  worth doing when S2 rate limits become a recurring problem.
- **`habanero` Python library**: CrossRef client. Mostly we use
  content negotiation already (for BibTeX), but `habanero` has a
  cleaner polite-pool interface and good BibTeX helpers. Marginal
  gain; defer.
- **pyzotero write-back**: pyzotero 1.11.0 is installed but unused.
  Agent currently produces Zotero-action *recommendations* for
  manual execution. Could auto-apply: add items to collection,
  set tags, insert the suggested note. Requires Zotero API key
  configuration or local-HTTP-server mode. Worth doing once the
  discovery pipeline is solid.
- **GROBID for PDF reference extraction**: heavy dependency; only
  useful when CrossRef/S2/OpenAlex all fail. Skip unless the
  fallback chain fails frequently enough to justify.
- **Iterative retrieval-generation (OpenScholar pattern)**: draft
  synthesis → identify claim gaps → targeted retrieval → refine.
  Improves citation accuracy in generated text (not discovery).
  Relevant only if lit-scout gains a "draft prose" mode — currently
  it's discovery+report, not synthesis.
- **Semantic Scholar API key**: free tier (100 req/5 min) hasn't
  been a bottleneck in testing. Apply only when rate limits are
  felt at scale.
- **API response caching**: cache recent `metadata`/`references`/
  `citations` results across invocations. Useful if the same DOIs
  are re-queried across sessions. Implement as a simple JSON cache
  in `~/.cache/lit-search/` with 7-day TTL.
- **`litstudy` integration** (NLeSC) for bibliometric analysis —
  co-citation networks, topic modelling. Belongs to a future
  "analyse the field" feature rather than discovery.

## Priority order (if promoting to focus)

1. **Incremental report write-to-disk** — highest value/effort ratio.
   Prevents 10+ minute losses on network drops.
2. **Highest-confidence subset near TL;DR** — small output tweak, big
   user-experience gain for deciding what to read today.
3. **Venue-match headline one-liner** — trivial to add, noticeable
   payoff.
4. **pyzotero write-back** — the obvious next capability. Defer
   until at least 3-5 more lit-scout runs confirm discovery is solid.
5. Everything else: defer until evidence of need.

## Trigger conditions for promoting this to focus

- Lit-scout has been used ≥5 times in real work without being
  retired
- A specific run hits an issue that maps to one of these items
- Starting Paper B lit review (would benefit from incremental
  write + pyzotero write-back)
