# Lens B (test adequacy) — tranche 5: external services and glue — HEAD 0d5fc39
Baseline 214 passed over seven files; no socket connect attempted (sitecustomize guard); nothing written outside caches. 26 mutations survived; 11 highest applied simultaneously → full suite 2453 passed.

## Critical
1. lit-scout-zotero-import.py — the entire write path untested: run_import (:1341) dedup (:1463), --live gate (:1542), collection assignment (:1557), env-var precondition (:1366), manifest idempotency (:1460), read-only SQLite open (:1446) — six mutations each green (8/8). tests only exercise build_zotero_item.
2. publish-dashboard.py:540 main() never invoked: --publish unconditional (:594), token/--canvas-id check deleted (:598), ok:false raise deleted (:482), TaskFilesMissing refusal replaced (:561), SLACK_API repointed (:72) — all green (27/27).
3. zotero.py:70 read-only SQLite promise untested: patch_connect fixture (test_zotero.py:190) replaces _connect in every test; a plain read-write sqlite3.connect stays green (67/67).
4. lit-search.py:262 per-host pacing deletable (76/76 green, run 2.11 s → 0.12 s); :395 ignoring Retry-After entirely also survives (and _http_retry's docstring calls this code "the reference shape").
5. sync-symlinks.sh:61 prune_stale_symlinks zero coverage — the only rm in the tranche: `[ -L ]` → `[ -e ]` and `rm` → `rm -rf` (:75) both green (132/132): would recursively delete real directories under ~/.claude/{commands,skills,agents,output-styles}.

## Medium
6. _http_retry.py:249 timeout=timeout droppable (56/56 incl. test_embed).
7. _http_retry.py:265 except tuple → BaseException survives.
8. compose-global-claude-md.sh:85 --dry-run can write the real file (`if $DRY_RUN` → `if false` green).
9. compose-global-claude-md.sh:78 layer order unpinned (common/overlay swap survives; tests assert only `marker in composed`).
10. compose-global-claude-md.sh:117 nothing stops writing a Sol-owned surface (adding cp to ~/.codex/AGENTS.md after the mv stays green despite the header :15-16).
11. sync-symlinks.sh:120 "real file, not a symlink → skip" branch untested (rm -f && ln -s survives; a hand-written settings.json would be deleted).
12. zotero.py:397,406 _normalise_doi and find_by_doi have no test anywhere (`return doi`, `return []` green); wiki/working-notes.md:577 records a prior silent-failure defect in this function's SQL.
13. lit-scout-zotero-import.py:1271 ensure_subcollection idempotency untested (never-match survives).
14. env-fingerprint.sh zero tests (no-disclosure invariant, quote stripping, duplicate-key warning unpinned; a value-leaking edit stayed green).
15. syncthing-bind-heal.sh:43-46 precondition untested; no test references the script.

## Low
16. ollama-endpoint.sh no direct test (test_embed.py:300 tests the consumer's fallback); exit 0 with an unreachable URL survives.
17. lit-search.py:322,324 flat backoff and unbounded backoff both survive.
18. add-doi-to-zotero.py (217), review-paper-prepass.py (632), llm-use-inventory.py (397) — no tests. Minimum: add-doi refuses when the DOI is in any local library (:157-163) and dry-run writes nothing (:197); prepass checks degrade to checks_skipped when a tool is absent, aux-label rule; inventory honesty rules ("(proposed — confirm)", token cost omitted, duration caveat). add-doi:139 reads only ZOTERO_API_KEY_PERSONAL (retirement candidate).
19. syncthing-health.sh referenced only as a path fixture (test_daily_sync_trigger.py:220,328).

## Surviving mutations (all CONFIRMED)
_http_retry.py:249 drop timeout; :265 BaseException. zotero.py:70 drop immutable/uri; :397 normalise off; :406 find_by_doi []. lit-search.py:262 pacing; :395 retry_after None; :322/:324 backoff. publish-dashboard.py:594 publish always; :598 missing check; :482 ok:false raise; :561 TaskFilesMissing; :72 SLACK_API. lit-scout-zotero-import.py:1463 existing []; :1542 live gate; :1557 wrong collection; :1366 env refusal; :1446 immutable; :1460 manifest skip; :1271 subcollection. sync-symlinks.sh:69/:75 -L→-e, rm→rm -rf; :120 clobber. compose-global-claude-md.sh:85 dry-run writes; :78 layer swap; :117 write ~/.codex/AGENTS.md; :48 $LOCAL precondition.
Killed: is_transient_status set changes; Retry-After clamps; _openai_key (all three); _strip_html; _get_item_collections; lit-search 429 retryability; ln -sfn→-sf (S11); non-atomic compose (S13); dropping cat "$COMMON".

## Wiring / fixtures / negatives / default path
- Wiring: only compose-global-claude-md.sh (test_glue_scripts.py:419,434, live script, HOME pinned) and zotero.py (in-memory SQLite with the real schema) run a real entry point with a stubbed boundary. lit-search never runs main()/CLI; cmd_* tests patch _safe_get above the transport (TestOpenAlexApiKey :697 the exception). Importer never runs run_import/main. publish-dashboard never runs main(). sync-symlinks.sh only sourced up to "# Step 1:" — the eight linking steps never execute. ollama-endpoint.sh, syncthing-bind-heal.sh, env-fingerprint.sh never executed by any test.
- Fixtures: lit-search's are good (CROSSREF_WORK, S2_PAPER, OPENALEX_WORK). Missing: CrossRef author with family but no given (lit-search.py:623 never taken); organisation author {"name"} (silently dropped at :619-624); HTML title; issued.date-parts [[None]]; OpenAlex authorships[].author null (AttributeError); _normalise_openalex({}) never called. No fixture anywhere carries Zotero item JSON (key/version/data); ensure_subcollection and create_collections shapes and find_existing_by_doi rows appear in no test. tests/fixtures/ is empty. Rate-limit HTML body is safe (429 check before .json(); JSONDecodeError covered).
- Negatives: only compose has a positive/negative pair (and lacks the --dry-run negative). publish-dashboard: nothing asserts no POST without --publish/token/--canvas-id or with unreadable task files. Importer: nothing asserts a create happens or is withheld (duplicate, manifest hit, dry run, no credentials). zotero.find_by_doi neither positive nor negative. sync-symlinks: the guards (leave a real file alone; prune leaves non-symlinks and outside-pointing links alone) untested.
- Default path: ~/.claude/CLAUDE.md safe (conftest.py:46 HOME repoint at import; probe confirmed). Two holes: (1) NO network guard of any kind — conftest.py:271 guards psycopg2.connect only; a probe test connected to a local TCP server, 4 passed, nothing complained; an escaped httpx/pyzotero/Slack call would reach the internet. Recommend a socket-level guard (socket.socket.connect, connect_ex, create_connection) in conftest. (2) The canonical-store guard watches only memories.jsonl, tag-vocabulary.txt, logs/ (conftest.py:300-305); a probe clobbered global-claude-md/claude.md, data/tasks/FOCUS.md, wiki/continuity.md in the checkout and the suite stayed green — global-claude-md/claude.md is the composer's source. Smaller: zotero.py:34 honours ambient ZOTERO_DATA_DIR which conftest does not pop; test_glue_scripts.py:193 _run_ensure_symlink does not pin HOME in its subprocess env (sibling at :311 does).
