# Lens B (test adequacy) — tranche 3c: retrieval and serving — HEAD 505ca8c
18 mutations, all 18 survived. Baseline 130 passed over six test files; nothing written outside caches.

## Critical
1. fetch-memories.py:241-301 — the entire PostgreSQL query body is unreachable: try_postgres returning a hard-coded list right after connect passes 130/130. TestTryPostgres (tests/test_fetch_memories.py:408-454) tests only the two ways to fail before the query.
2. fetch-memories.py:248 — `active_memories` -> `memories` invisible (is_active/decay live in the view, schema.sql:269-281); same at memory_mcp.py:491 (list_recent).
3. fetch-memories.py:281-283 — AND -> OR survives (base WHERE TRUE, so every filter becomes a no-op).
4. fetch-memories.py:710-803 — main() has no test: deleting the JSONL fallback (results = [] at :760) and neutering --limit validation (:184) pass. parse_args, _staleness_warning (61-118), _log_invocation (806-847) have zero references in tests/.
5. memory_mcp.py:390-392 — search_sessions returning a hard-coded list is green; only name-set membership (test_memory_mcp.py:75) and readOnlyHint tested; ImportError envelope (:393) and empty-result note (398-401) untested.
6. search-sessions.py — zero coverage in the FULL suite: dropping LIKE escaping (75-77), dropping the role filter (104-106), reversing ORDER BY rank (98) all pass.
7. memory_mcp.py:251-271 — the JSONL fallback test (test_memory_mcp.py:245-249) patches matches_filters to return True; dropping the project filter (:262), reversing the sort (264-266), dropping [:limit] (:268) all pass together.
8. fetch-memories.py:318-430 — try_semantic never called by any test: WHERE embedding IS NOT NULL -> WHERE TRUE plus cosine DESC (worst first) passes; every semantic_search test patches try_semantic out.

## Medium
9. fetch-memories.py:496 — tag any -> all survives (documented as OR; every tag test passes exactly one tag).
10. surfacing_stats.py:42 vs surfacing_log.py:94 — reader/writer defaults never compared (reader default -> surfacing.log passes; test_writer_output_parses_in_aggregator passes an explicit log_path).
11. surfacing_stats.py:138-204 — _render_human and main() untested (reverse ranking :164; main aggregating {} :200 pass).
12. log-recall.py:106-141 — main() untested: discarding --selectors/--results and writing source=fetch instead of source=recall passes (main is the only entry point recall.md invokes; source= is the discriminator tier-2-retrieval.md defines).
13. memory_mcp.py:437 — get_memory `== memory_id` -> startswith passes.
14. Schema-version guard unpinned at every read call site: neutering `except SchemaVersionError` at fetch-memories.py:237-239, :377-379, memory_mcp.py:111-115 passes.
15. project_id.py:59-81, 119-208 — decode_project_id, repo_set, repo_set_for untested (decode returning Path("/") for every input; repo_set_for dropping prioritisation pass). tests/test_project_id.py covers encode_project_id (5 parity cases) and the hook wrapper only.
16. resolve_session_id.py — zero coverage; prefix matching at resolve_via_catalogue:51 and resolve_via_filesystem:79 passes; nothing imports it; wiki/planning/memory-system-v2-implementation-plan.md:524 lists tests/test_resolve_session_id.py as a deliverable that does not exist.

## Low
17. digest-preview.py — zero coverage; writes PA_DIR/data/logs/digest.log by default (:39, 183-185).
18. memory_mcp.py:483-486 — list_recent's column list omits `verified` while search_memories returns it (fetch-memories.py:242-245). SUSPECTED drift.

## Wiring / fixtures / negatives / default path
- Only log-confab-flag.py has a real entry-point test (test_log_confab_flag.py:231). memory_mcp tools are invoked as coroutines but stub the layer below (try_postgres, try_semantic, _pg_connect, load_jsonl_memories). fetch-memories, log-recall, surfacing_stats, search-sessions, digest-preview, resolve_session_id: no main()/CLI test. No sqlite shim or SQL-parsing cursor anywhere; the strongest SQL assertion is `sql.count("%s") == len(params)`; fetch-memories' SQL is not compared at all.
- Fixtures: _make_memory (test_fetch_memories.py:29-54) and SAMPLE_RESULTS (test_memory_mcp.py:36-59) omit verified and anchors (matches most of production) but only one test sets verified ("true"); 'false'/'pending' never reach format_output; no fixture carries is_active (production has such records), so the fallback's documented "returns all memories regardless of is_active" is unpinned either way; list_recent's fake rows are 9-tuples matching its own column list (test and fixture mutate together).
- Negatives good inside matches_filters and search_archive; absent elsewhere: no test excludes an is_active=false row, a wrong-project row in the MCP fallback, or a wrong-role turn; test_similarity_boundary (test_memory_mcp.py:806) is the only mutation-resistant boundary in memory_mcp.
- Default path: no unmarked test connects today (PGHOST sabotaged, 130/130), but dbname="claude_memories" is hard-coded with no env override (fetch-memories.py:47, memory_mcp.py:72, search-sessions.py:40), nothing patches psycopg2.connect at session scope, no integration markers in the tranche. Write side: conftest.py:220-295 watches ~/.cache only; a throwaway test calling log_recall("probe"), log_confab_flag(...), and fetch_memories._log_invocation(...) with no log_path created logs/fetch-memories.log and logs/confab-flags.log in the checkout, suite green. log-recall.py:87 and log-confab-flag.py:169 bind DEFAULT_LOG_PATH (from __file__, through logs -> data/logs) as a default argument with no S22 pytest guard; surfaced.log was correctly NOT created. fetch-memories.main() cannot be tested at all because _log_invocation (:813) has no injection point.
