# LLM Wiki — Bounded Pilot for Per-Paper Synthesis

**Status:** Backlog candidate
**Added:** 2026-04-14
**Source:** Karpathy gist — <https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f>
**Owner:** Shawn (exploration), CC (analysis)

---

## Idea in one sentence

Pilot a Karpathy-style "LLM Wiki" — a small, LLM-maintained collection of interlinked markdown pages that captures the *current synthesised state* of a research artefact — for a single project, to test whether it makes structural research work (theme identification, length control, contradiction detection) materially faster.

## The Karpathy pattern (summary)

A persistent, compounding artefact that sits between raw sources and your queries:

- **Raw sources** (immutable) → **Wiki** (LLM-owned interlinked markdown, continuously updated) → **Schema** (CLAUDE.md / AGENTS.md telling the LLM how to maintain it)
- Operations: **ingest** (LLM updates 10–15 wiki pages per new source), **query** (search wiki not raw, file good answers back as new pages), **lint** (find contradictions, orphans, stale claims)
- Two indexes: **index.md** (content catalogue) + **log.md** (chronological audit trail)
- Obsidian as the human-facing IDE; the LLM does all the writing

The key insight: **synthesis is baked in, not re-derived on every query.** Cross-references already exist; contradictions are already flagged; the synthesis already reflects everything ingested.

## How it relates to the existing memory system

| Dimension | Current memory system | LLM Wiki |
|---|---|---|
| Unit | Discrete atomic memory (≤150 char summary + content) | Interlinked markdown pages, structured by entity/concept |
| Synthesis | Computed on demand (`/synthesise`, `/recall`) | **Baked in and continuously updated** |
| Update model | Append-only with decay | Pages edited, superseded, lint-checked |
| Navigation | Tag/FTS/semantic search | Hypertext links + index.md |
| Maintenance | Hooks, vocabulary gardening | Active LLM editing per ingest |
| Best for | Cross-session patterns, slips/commitments, errors, prompt craft, decisions | Per-artefact synthesis: arguments, themes, hypotheses, evidence aggregation |

The two are **complementary**, not overlapping. The memory system is a learning log (good for ephemera, patterns, decisions, constraints). The wiki would be a knowledge base (good for the *current state* of a structured intellectual artefact).

## Where it would actually pay rent

### Strongest fit: per-paper "thesis wiki" for active manuscripts

**Specifically LLM-History-Paper, right now.** Reasons:

1. **Length control is exactly the wiki's use case.** Stages 2 and 3 of length control (identify 3–4 themes, then ruthlessly cut) are essentially "build a synthesis of the paper's current argument and use it to decide what's redundant." A paper-wiki *is* that synthesis.
2. **Consolidation work is already happening ad-hoc.** Today's memories include "formatting-as-authority claim consolidated", "5 manuscript edits integrated". A wiki would automate the bookkeeping that is currently being done by hand.
3. **Lint maps onto editorial work.** Karpathy's lint pass (find contradictions, orphan claims, stale assertions) is what a critical peer reviewer does. The "Critical peer reviewer pass" backlog item could be partially automated by a well-maintained wiki.

### Second fit: per-experiment wiki for map-reader-llm

Pages for each hypothesis (H10, H12, …), each experimental configuration, each metric pattern. A wiki page for H10 could include an explicit "transmission mechanism" section — "what must be in the API call for this hypothesis to be testable." **The H10/H12 confound caught today might have been caught earlier if such a page had existed.** This is the structural fix for the prompt_effectiveness lesson from the 2026-04-14 standup.

### Weak fit: everything else

The current memory system is genuinely better for cross-session patterns, slips/commitments, error modes, prompt craft, and the tag-relevance retrieval pipeline. Those are *learning logs*, not knowledge bases — wikis are the wrong shape for them. **Do not migrate the memory system to a wiki model.**

## Risks and costs

1. **Maintenance overhead.** Karpathy's "LLM does the bookkeeping" claim is true but the human still curates, reviews, and directs. Time is already tight; an experiment that doesn't pay off in the same week becomes another infrastructure tax.
2. **Duplication risk.** The memory system already accumulates project context. A wiki must claim a clearly distinct slice (per-artefact synthesis) or it becomes a parallel store to keep in sync.
3. **Tool-stack creep.** Karpathy assumes Obsidian + manual review. That's a different working pattern from "Claude Code session + memory hooks." Adding a third tool has friction.
4. **No wiki search at small scale is fine, but at scale needs tooling.** The gist mentions [qmd](https://github.com/tobi/qmd) for hybrid BM25/vector search over markdown. Pilot scale (one paper) doesn't need this; production scale would.

## Proposed pilot

**Scope:** One wiki, one paper, one week of length-control work.

**Subject:** LLM-History-Paper.

**Why this paper:** Length control naturally requires the artefact a wiki produces. If the wiki makes stages 2–3 demonstrably faster, the experiment has paid for itself in the same week. If it doesn't, the cost is sunk on one paper and the lesson is learned.

**What to build:**

1. A `wiki/` directory inside the LLM-History-Paper repo.
2. A schema file (`wiki/SCHEMA.md` or extended CLAUDE.md) describing page conventions: entity pages (key concepts, formatting-as-authority, etc.), theme pages (the 3–4 candidate themes), source pages (key references with claims and how the paper uses them), an `index.md`, and a `log.md`.
3. Initial population: have CC read the current manuscript and existing tagged memories (`research_tags` containing `llm-history-paper`) and seed the wiki.
4. Use the wiki to drive length-control stages 2 and 3.
5. At the end of the week, evaluate: did this make the work faster, slower, or about the same? Would I do it again for map-reader-llm?

**What NOT to build (yet):**

- A search tool. Index.md is enough at this scale.
- Obsidian integration. Markdown files in the repo are sufficient; CC reads them directly.
- Image handling, frontmatter querying, slide deck export. All optional; ignore.
- A separate wiki for any other project until the pilot is evaluated.

**Success criteria:**

- Stage 2 (theme identification) completes in materially less time than the alternative.
- Stage 3 (theme-driven cuts) has a clearer rationale (the wiki shows what is and isn't covered by the chosen themes).
- The lint pass surfaces at least one contradiction or orphan claim that wouldn't have been caught otherwise.

**Failure criteria:**

- Wiki maintenance consumes more time than it saves on the length-control work.
- The wiki ends up duplicating what's already in the memory system without adding new structure.
- CC needs constant prompting to keep the wiki current — i.e., maintenance isn't actually near-zero in practice.

## Decision

**Recommendation:** Add to backlog as a pilot, not as infrastructure. Do not action until *after* LLM-History-Paper ships — actually, scratch that. The strongest argument for the pilot is that it would *help* the paper ship by speeding up length control. So: consider whether to action it as part of the length-control work, or defer until the paper is done.

**The honest tension:** running a tooling experiment in the middle of the most time-pressured task on the slate is exactly the kind of distraction the standup keeps flagging. The safer call is to defer until after the paper, then pilot it on map-reader-llm length/structure work, where the time pressure is lower and the experimental hypothesis structure (H10, H12, …) is a more natural fit for entity pages.

**Default decision (unless reconsidered):** Defer to post-LLM-History-Paper. Pilot on map-reader-llm during the write-up phase.

## Open questions

- Where does the wiki live? Inside the paper repo, or a separate wiki repo? (Inside the paper repo is simpler and ensures it's versioned with the artefact.)
- How does the wiki interact with the memory system? Does CC also write memories about wiki edits, or is the wiki self-contained? (Probably self-contained — the wiki is the synthesis, the memory system is the learning log. Keep them separate.)
- What's the schema vocabulary? Karpathy leaves this to the user. Worth a short brainstorming session before the pilot starts.
- Can the existing `/synthesise` command be repurposed to bootstrap the initial wiki population?
