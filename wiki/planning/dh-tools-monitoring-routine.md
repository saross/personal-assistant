# DH Tools Monitoring Routine

## Context

The LLM-History-Paper research involved one-off Research-mode searches
for archaeology/DH software tools (~91 tools across Feb-Aug 2025). A
scheduled routine could do this continuously: build a more complete
picture over time than any single search, detect new tools as they
appear, and observe the *trajectory* of the ecosystem.

This would be a longitudinal companion to the LLM-History-Paper
case study. Candidate successor paper: "what does longitudinal
LLM-assisted monitoring of a research software ecosystem reveal
about tool evolution that traditional bibliometrics miss?"

## Approach: weekly scheduled routine + `tool-scout` agent

### Architecture

```text
Weekly cron routine (CronCreate, Sunday 8am)
  │
  ├─ Invokes a `tool-scout` agent (variant of prior-art-scout
  │    tuned for field survey rather than problem-solving)
  │
  ├─ Searches across:
  │    - GitHub (topics: archaeology, digital-humanities, GIS,
  │      photogrammetry, field-data-collection, etc.)
  │    - PyPI / CRAN / HuggingFace with relevant tags
  │    - arXiv / Zenodo / OSF for tool-mentioning papers
  │    - Software-citation mentions via CrossRef / OpenAlex
  │      (e.g., FAIMS, Fieldmark, PaleoHub etc.)
  │
  ├─ Reads existing tool catalogue (last run's state)
  │
  ├─ Produces:
  │    - Updated master catalogue (all tools seen ever)
  │    - New-this-week digest (diff against last run)
  │    - Maturity changes (tools going stale, tools reviving)
  │    - Trajectory notes (new approaches, consolidation patterns)
  │
  └─ Commits to a research repo (research/dh-tools-catalogue/)
     and emails digest
```

### Why not just prior-art-scout?

`prior-art-scout` is tuned for "solve this technical problem" —
high specificity, narrow relevance. Field survey needs the opposite:
breadth, inclusion, tracking experimental and mature tools alike.
The scoring criteria differ (field survey values *coverage*;
prior-art-scout values *fit*). The search strategies differ
(prior-art-scout narrows queries; field survey broadens).

New agent definition, borrowing structure but rewriting the
methodology, search strategies, and output format.

## Key design decisions

- **State management.** Where does the catalogue live? Options:
  (a) dedicated repo `research/dh-tools-catalogue/`; (b) part of
  LLM-History-Paper repo as an ongoing artefact; (c) new private
  repo. Recommendation: dedicated public repo — the catalogue
  itself is a research contribution worth making visible.
- **Schema.** One row per tool with: name, URL, tags, first-seen,
  last-updated, maturity indicators (stars, commits, licence),
  archaeological / DH domain, brief description. JSON or
  YAML front-matter per tool file.
- **Duplicate detection.** Tools re-discovered under different names
  / mirrors / forks — needs canonical identifier logic.
- **New-vs-changed.** Worth flagging both new tools AND significant
  changes to known tools (major release, deprecation, new
  maintainer).
- **Alert threshold.** Not every new tool warrants attention; tier
  by relevance (obvious fit / possible fit / edge case).

## Implementation sequence

1. **Design the catalogue schema** (1-2 hours, collaborative)
2. **Seed the catalogue manually** from the existing LLM-History-Paper
   research materials (~91 tools already documented)
3. **Write `tool-scout` agent definition** adapted from
   prior-art-scout
4. **Build state-tracking wrapper** — the routine needs to read last
   run's catalogue and diff against this run's findings
5. **Test manually** — invoke tool-scout on demand for 2-3 runs,
   verify catalogue updates cleanly
6. **Set up CronCreate routine** — weekly schedule, connectors for
   email digest
7. **Monitor for 4-6 weeks** — refine queries, fix false positives,
   improve trajectory detection
8. **Consider successor paper** — once 6+ months of longitudinal data
   accumulated

## Scoping estimate

- Schema + seed catalogue: 1 day (possibly collaborative with a co-author)
- `tool-scout` agent definition: 3-4 hours
- State-tracking wrapper: 2-3 hours
- Routine setup + first run: 1 hour
- Review overhead going forward: ~1 hour/week (reading digest,
  triaging new entries)

Total initial build: 2-3 days of focused work.

## Non-obvious considerations

- **Search query drift.** "Archaeology software tools" will surface
  different things in 2027 than in 2026 as the field vocabulary
  shifts. Expect to revise queries quarterly.
- **Coverage asymmetry.** GitHub/PyPI coverage is excellent;
  historical or legacy tools (Perl scripts, Fortran, Windows
  binaries) won't surface. Document coverage limits explicitly.
- **Archaeological vs DH scope.** These overlap but differ. Decide
  whether to split into two catalogues or keep unified with tags.
- **Value compounds non-linearly.** At 3 months: an annotated list.
  At 6 months: trajectory patterns visible. At 12 months: genuine
  empirical evidence for ecosystem-level claims.
- **Privacy / attribution.** Tool maintainers may notice being
  monitored; consider a public statement about the routine's
  methodology as courtesy.

## Trigger conditions

This task becomes active when:
- LLM-History-Paper is submitted (focus slot frees)
- Inscriptions SPA is past the initial scaffolding phase
- At least 1 day of focused time is available for the initial build
