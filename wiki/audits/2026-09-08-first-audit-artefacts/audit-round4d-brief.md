# Audit round 4d — external services and machine glue — fix brief

Read the shared brief first: `audit-round2-brief.md` in this directory (all of
its safety constraints, code standards, commit rules, and the synthetic-fixture
rule apply unchanged). Differences for this round:

- Worktree: `~/worktrees/personal-assistant/claude-audit-round4d`, branch
  `claude/audit-round4d`, at main (the commit your worktree shows). Suite at
  the branch point: about 2,453 passed. Sibling agents run in other
  worktrees: round 4a-2 owns `tests/conftest.py` and
  `tests/test_hermeticity_fixture.py` (it is adding a socket-level network
  guard and widening the canonical-store guard — do NOT edit those two
  files; if you need a guard, report the gap); round 4c owns the archive
  pipeline AND `tests/test_glue_scripts.py` (do NOT edit that file — put every
  new shell-glue test in a NEW file `tests/test_machine_glue.py`, and every
  new Zotero/literature test in the existing per-script test files or new
  ones); others own daily-sync, the memory-store writers, and the retrieval
  scripts.
- Lens reports: `lensA-5.md` (correctness, findings 1-24 → cite as E1-E24)
  and `lensB-5.md` (test adequacy, findings 1-19 → ET1-ET19) in this
  directory. Line numbers were taken at 0d5fc39; verify before editing.
- The durable record is `wiki/audits/2026-09-08-first-audit.md`; do NOT edit it.
- Scope: `scripts/zotero.py`, `scripts/add-doi-to-zotero.py`,
  `scripts/lit-scout-zotero-import.py`, `scripts/lit-search.py`,
  `scripts/review-paper-prepass.py`, `scripts/_http_retry.py`,
  `scripts/_openai_key.py`, `scripts/llm-use-inventory.py`,
  `scripts/publish-dashboard.py`, `scripts/ollama-endpoint.sh`,
  `scripts/syncthing-health.sh`, `scripts/syncthing-bind-heal.sh`,
  `scripts/env-fingerprint.sh`, `scripts/sync-symlinks.sh`,
  `scripts/compose-global-claude-md.sh`, their tests, and
  `global-claude-md/zotero-reference.md` where a claim changes.

## Absolute safety rules for this tranche

NEVER open, cat, grep, source, or copy `~/personal-assistant/.env` or any real
`.env` (a deny rule exists; do not route around it — synthetic `.env` files
with fake values in tmp dirs only); never print an environment value. No
network: stub `httpx`/`urllib`/pyzotero at the boundary and, in every test
file you touch, add an autouse fixture that makes `socket.socket.connect`
raise (until the conftest guard lands). Never talk to Zotero, Ollama,
Syncthing, docker, systemctl, ssh, rsync, Slack, or pip. Never run
`sync-symlinks.sh`, `compose-global-claude-md.sh`, `syncthing-*.sh`,
`env-fingerprint.sh`, or `ollama-endpoint.sh` outside a sandbox with stub
binaries (`git`, `pip`, `docker`, `ssh`, `curl`, `python3` where needed)
first on PATH and HOME pinned. Never write under `~/.claude`, `~/.cache`,
`~/.codex`, `~/agent-mail`, `~/gpt-hub`, `~/personal-assistant`, or its
`data/`.

## Must fix (Critical and Medium from both lenses)

Order: E1, ET5, ET1, ET2, ET3 first (one commit each), then by file.

E1 (critical) — ONE DOI normaliser. `lit-scout-zotero-import.py:894`
`find_existing_by_doi` must normalise both sides the way
`zotero.py:328-372` `find_by_doi` does (strip `https://doi.org/`,
`http://dx.doi.org/`, `doi:`, case-fold) — import and reuse `zotero.py`'s
normaliser rather than a second copy; make the SQL `REPLACE` chain and the
Python prefix strip agree (the cross-file note: SQL strips `doi:` anywhere,
Python only a prefix — pick the prefix rule and apply it in both). Tests
(ET12): a stored `https://doi.org/10.1234/ABC-def` is found by a bare
lower-case lookup in BOTH functions; a stored bare DOI is found by a
URL-wrapped lookup; absent → none.

ET5 (critical) — `sync-symlinks.sh:61-75` `prune_stale_symlinks`: tests in
`tests/test_machine_glue.py` that run the function (extract it by name, or
run the script in a sandbox with stub `git`/`pip`) and prove: a real
directory is left alone; a real file is left alone; a symlink pointing
outside the source dir is left alone; only a dangling symlink into the
source dir is removed, with `rm` (never `-r`). ET11: the "real file, not a
symlink → skip" branch (:120) pinned. E9 and E10: `pip install --upgrade -r
requirements.txt` must not run unattended — install only the missing
package(s) without `--upgrade`, or print the command and skip when not
interactive (`[ -t 0 ]`); `git submodule update --init --recursive` must run
ONLY when the submodule is uninitialised (empty `data/`), never on an
initialised one (which detaches `data/` from its branch and can orphan a
concurrent session's commits) — tests with a stub `git` that records argv.
Add `--dry-run` (E5 answer) that prints every action and executes none;
test it.

ET1 (critical) — `lit-scout-zotero-import.py` `run_import` end to end with
a fake pyzotero client (records every call) and a synthetic Zotero SQLite:
dry run creates nothing; `--live` creates exactly the non-duplicate items in
the dated subcollection; a duplicate (bare or URL-wrapped) is withheld; a
manifest hit is withheld; missing env vars refuse before any request; the
SQLite open is `immutable=1` (assert the URI). E2: `load_env` strips one
layer of matching quotes and accepts `export ` (mirror
`env-fingerprint.sh:88-92`; test both shapes). E4: `date-parts: [[None]]`
→ empty date, never the string "None". E5: the title is HTML-stripped like
the abstract (`_strip_html`). E8: `ensure_subcollection` paginates
(`zot.everything(zot.collections_sub(...))`) — test with a fake returning
two pages. E6: `add-doi-to-zotero.py:139` prefers `ZOTERO_API_KEY_ALL`
then `_PERSONAL`, matching the importer; update `zotero-reference.md:175`.
ET18: `tests/test_add_doi_to_zotero.py` — refuses to create when the DOI is
in any local library; dry-run writes nothing.

ET2 (critical) — `publish-dashboard.py` `main()` end to end with `urlopen`
stubbed: no POST without `--publish`; refuses without token or
`--canvas-id`; `ok:false` raises; `TaskFilesMissing` refuses; the request
goes to `SLACK_API` with a bearer header. E7: the authenticated request
must not follow redirects (an opener whose redirect handler raises); test
that a 302 is not followed and the token is not re-sent.

ET3 (critical) — `zotero.py:70`: a test that runs the REAL `_connect`
against a synthetic Zotero SQLite in a tmp dir (set `ZOTERO_DATA_DIR`) and
asserts the connection is immutable (an `INSERT` fails) and the URI is
well-formed with the path URL-encoded (E24: `#` and `?` in the dir).
E12: `format_citation` renders "n.d." when the date is empty.

ET4 — `lit-search.py`: tests at the transport level (patch `httpx.Client`
or `client.get`) that pin per-host pacing (`time.sleep` called with ≥ the
floor between two calls to the same host; not between different hosts),
`Retry-After` honoured on 429, exponential backoff with the cap (ET17),
and E3: `x-api-key` sent ONLY to `api.semanticscholar.org` (per-request
header or a host-keyed event hook), never to CrossRef, OpenAlex, or
DataCite; `follow_redirects` must not carry it cross-host. E19:
organisation authors (`{"name": …}`) and family-only authors kept.
E18: BibTeX key collisions de-duplicated with a suffix. Fixtures: add the
missing shapes (family-only, organisation, HTML title, `[[None]]`,
`authorships[].author: null`).

ET6, ET7 — `_http_retry.py`: tests that the timeout kwarg reaches
`urlopen` on every attempt and that a non-network exception is NOT retried;
E14: refuse to retry a `POST`/`PUT`/`PATCH`/`DELETE` unless the caller
passes `idempotent=True`, and say so in the docstring.

ET8, ET9, ET10 — `compose-global-claude-md.sh`: `tests/test_machine_glue.py`
pins that `--dry-run` writes nothing (and only that exact spelling — E13:
any other argument is a usage error, exit 2); layer order common → overlay
→ local (assert relative positions); the script never writes outside
`$HOME/.claude/CLAUDE.md` (run with a stub that lists every file created
under the pinned HOME). E11: refuse (exit 2 with a one-line message) when
`SCRIPT_DIR`'s repository root is not `$HOME/personal-assistant`, unless
`--target <path>` is explicit — so a worktree run cannot overwrite the live
global instructions; test both.

ET14 + E23 — `env-fingerprint.sh`: tests that no value ever appears in
output (synthetic `.env` with a distinctive fake value; grep the output),
that quotes and `export` are handled, and the duplicate-key warning fires.
For E23: the salt must not be a public constant — read it from
`ENV_FINGERPRINT_SALT` (required, refuse without it, never printed) so
both machines share a private salt out of band; drop the exact length and
report a length bucket (short / medium / long) instead. Update the header.

ET15 — `syncthing-bind-heal.sh`: sandbox test with a stub `docker` that
records argv: no compose file → no action; `cert.pem` absent → no action;
both present → `up -d --force-recreate` once. E15: `syncthing-health.sh`
`--simulate-need` with no value exits 0 with a message (the "always exits
0" invariant), pinned. E16: quote `$container`/`$config_dir` in `run_on`
and pass file paths to the embedded Python via `sys.argv`, not string
interpolation; test with a path containing a quote.

E20 / ET16 — `ollama-endpoint.sh`: keep the documented contract but make
the failure signal usable — print nothing and exit 1, and document the
`if url=$(...)` idiom; test both branches with a stub `curl`.

E17 — `review-paper-prepass.py:102`: contain `GUARD_ANCHOR` paths to the
repo (reject `..` and absolute); test. E21 — `llm-use-inventory.py:369`:
contain `--project` to the root; test. ET18 — minimum suites for
`review-paper-prepass.py` (each check degrades to `checks_skipped` when its
tool is absent; the aux-label rule) and `llm-use-inventory.py` (the honesty
rules: "(proposed — confirm)", token cost omitted, duration caveat).

## Lows — fix where cheap

E22 (stderr comment), E24 (URI slashes and encoding, with ET3), E12.

## Record, do not change

E4 answer (the dashboard publishes private `data/` content to a Slack canvas
by design), E6 answer (the only restart is local docker in bind-heal), the
`sync-to-zotero.py` note writer (outside this tranche), the three
`Retry-After` parsers (consolidating them is round-5 material — say so).

## Finish

Run the full suite from the worktree; report its last line AND exit code.
Deliverable as in the shared brief: disposition table (finding ID → fixed
with file:line and test name, or not fixed with reason), NEW findings, the
suite line, `git log --oneline main..HEAD`, and live-behaviour risks (for
example "SessionStart no longer runs `git submodule update` on an
initialised submodule", "`env-fingerprint.sh` now needs
`ENV_FINGERPRINT_SALT` on both machines", "the composer refuses from a
worktree").
