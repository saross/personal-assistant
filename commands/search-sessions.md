# /search-sessions — Full-text search of past session *content*

Search the actual transcript content of archived Claude Code sessions — the
words that were said, not just the session summaries. This is the indexed,
crash-proof way to answer "where did we discuss X / decide Y / try Z" across
past sessions.

## Where this sits (escalation ladder)

| Reach for… | When you want… |
|---|---|
| `/recall [query]` | what was distilled to **memory**, plus **which sessions** match (metadata) |
| **`/search-sessions [query]`** | the **transcript content itself** — the conversation, verbatim |
| `--show` (below) | the **exact turn(s)**, pulled verbatim from the index |
| `scripts/search-archives-safe.sh` | a bounded ad-hoc grep when the index lacks something |

`/recall` and `/search-sessions` are complementary: `/recall` is Tier 0–1
(memories + session metadata), `/search-sessions` is Tier 2–3 (the raw content
underneath). Start with `/recall`; escalate here when you need what was actually
said.

## Safety

This searches a **pre-built PostgreSQL index** (`session_chunks`) and never
decompresses a transcript. **Do not hand-roll `zcat | grep` over
`~/cc-archives`** — an ad-hoc search of that kind hard-locked the machine on
2026-06-21 (see `inscriptions/planning/archive-search-crash-diagnosis-2026-06-21.md`).
If you must grep raw `.gz` (e.g. for something not indexed), use the bounded
wrapper `scripts/search-archives-safe.sh`, never raw `zcat`/`tr`/`grep`.

## Usage

```text
/search-sessions [query]
/search-sessions [query] --project <name>
/search-sessions [query] --role assistant
/search-sessions [query] --substring          # exact / identifier match
/search-sessions --show <archive_dir> --turn <n>   # retrieve verbatim
```

## Behaviour

1. Run the search script via Bash and present the ranked results:

   ```bash
   ~/personal-assistant/venv/bin/python3 \
     ~/personal-assistant/scripts/search-sessions.py "QUERY" [--project P] [--role R] [--limit N]
   ```

   - **Query syntax** is PostgreSQL `websearch`: bare words are AND-ed, `"quoted
     phrases"` match in order, `OR` and `-exclude` work. Both terms in
     `Rome suggest` must appear in the same turn (= same transcript record).
   - **`--substring`** switches to a trigram `ILIKE` match — use for code-like
     identifiers (`build_model_f1`) that full-text stemming would mangle.
   - **`--project`** scopes to one project; **`--role assistant`** restricts to
     what Claude said (cuts user-prompt / injected-content noise).

2. Each result shows date, project, role, rank, session title, a highlighted
   snippet (match in `«»`), and a retrieval handle. **Offer to retrieve** the
   full turn for any result the user wants to read in full:

   ```bash
   ~/personal-assistant/venv/bin/python3 \
     ~/personal-assistant/scripts/search-sessions.py \
     --show <archive_dir> --turn <turn_idx> --context 2
   ```

   This returns the focal turn (marked `▶`) and its neighbours, verbatim, from
   the index — no `.gz` access.

3. **Zero matches:** suggest `--substring` (for identifiers), a broader query,
   dropping `--project`, or `/recall` for the memory/metadata tiers. Do not
   return empty silently.

4. **Graceful fallback:** if PostgreSQL is unavailable, the script reports it.
   Suggest `scripts/search-archives-safe.sh "QUERY" ~/cc-archives/<project>` as
   the bounded ad-hoc alternative (slower, ungranked, but safe).

## Freshness

The index is populated by `scripts/index-session-content.py`, which is
**incremental** (skips unchanged files by mtime). The most recent session(s) are
indexed once archived (sessions archive at *close*), so a just-finished session
may not be searchable yet. To refresh before searching:

```bash
~/personal-assistant/venv/bin/python3 \
  ~/personal-assistant/scripts/index-session-content.py [--project <name>]
```

By default only main session transcripts are indexed (the human↔assistant
conversation); add `--include-subagents` to index subagent transcripts too.

## Examples

```text
/search-sessions mixture model deconvolution --project inscriptions
/search-sessions "write-like-me" --role assistant
/search-sessions build_model_f1_f3 --substring --project inscriptions
/search-sessions OSF amendment --limit 20
/search-sessions --show 2026-06-19T07-48_complete-final-preregistered --turn 174
```

## Notes

- Searches **clean prose only** — user text and assistant text blocks. Thinking
  traces, tool calls, and tool results are excluded by the indexer, so matches
  are conversation, not tool noise.
- Also available to subagents as the **`search_sessions` MCP tool** — the safe
  path for agents, so they need never improvise a raw-archive grep.
- The index is a derived query layer; it can be rebuilt at any time from the
  canonical archive with `index-session-content.py --force`.
