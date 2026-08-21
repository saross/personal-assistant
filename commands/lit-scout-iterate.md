# /lit-scout-iterate — Closed-loop literature scout with verifier-driven iteration

Run `lit-scout` + `lit-scout-verifier` as a closed loop: the proposer
drafts; the verifier audits; if any claim fails, the proposer re-applies
the verifier's `true_value` to the affected rows and removes rows whose
DOIs the registry has authoritatively reported as not existing; repeat.
Cap N=5 iterations. Terminate on PASS, on PARTIAL (flag to user), on
UNVERIFIABLE (flag to user), on cap, or on no-progress (FAIL claim_id
set unchanged between iterations).

Always runs the verifier on every iteration. There is no bypass.

**A row is only ever removed on an authoritative negative.** A lookup
that did not complete — HTTP 429, a 5xx, a timeout, an exhausted API
budget — is `unverifiable`, and unverifiable rows are preserved and
flagged, never removed. Without this rule a throttled run deletes
genuine citations and reports them as confabulations, which is the
opposite of what the loop is for. See
`~/personal-assistant/wiki/planning/api-politeness-audit-2026-08-21.md`.

## Usage

```text
/lit-scout-iterate [query]
```

## Arguments

- `[query]` — free-text description of the literature to scout. Same
  shape as `/lit-scout`. Can include target venues, scope constraints,
  time periods, etc.

## Behaviour

The slash command is a thin orchestrator. It performs **no reasoning
about the content** of either agent's output. Its only substantive
actions are: invoke agents, extract the machine-readable
`claims.jsonl` and `corrections.jsonl` blocks from their markdown
output (sub-agents cannot reliably Write report files per the
2026-04-19 v4.x evaluation), pass file paths between iterations,
track iteration state, and decide when to terminate. All content
judgement lives inside the agents.

### Iteration policy (settled 2026-05-22)

- **Iteration cap:** `N=5`. Hard stop; do not silently extend.
- **Iterate on FAIL only.** PARTIAL verdicts surface to the user
  with full divergence details; the driver does not auto-iterate.
- **No-progress termination.** If iteration *k* produces the same
  set of FAIL `claim_id`s as iteration *k-1*, terminate.
- **Flag PARTIAL clearly.** When the loop terminates on PARTIAL,
  return the verifier's full integrated output with a banner
  flagging the partial divergences for user review.

### Pre-flight

Before iteration 0:

```bash
ITERATE_ROOT="/tmp/lit-scout-iterate-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$ITERATE_ROOT"
```

Each iteration writes to `${ITERATE_ROOT}/iter-{N}/` so the full
trajectory is preserved for inspection.

Initialise the no-progress tracker: `LAST_FAIL_SET=""`.

### Extraction helpers

Both agents embed their machine-readable structured data as fenced
`jsonl` blocks delimited by HTML comment markers. The orchestrator
extracts with:

```bash
extract_block() {
  # Args: input_file marker output_file
  # Writes lines between <!-- BEGIN ${marker} --> and <!-- END ${marker} -->,
  # excluding fence lines, to output_file.
  awk "/<!-- BEGIN $2 -->/,/<!-- END $2 -->/" "$1" \
    | sed -n '/^```jsonl/,/^```$/{/^```/d; p}' \
    > "$3"
}
```

Use this twice per iteration: once on the proposer's draft (marker
`claims.jsonl`), once on the verifier's integrated report (marker
`corrections.jsonl`).

### Iteration loop

For `N` in 0..5:

#### Step A — Invoke the proposer

- **Iteration 0 (first-run mode):** invoke `lit-scout` via the
  `Agent` tool with the user's query as the prompt. Pass the query
  through as-received. Do not paraphrase or enrich. Typical
  runtime: 10–15 minutes.
- **Iterations 1..5 (iterate mode):** invoke with a prompt that
  includes the user's original query AND:

  ```text
  This is iterate-mode invocation N for the closed-loop driver.
  Read your iterate-mode section in
  ~/.claude/agents/lit-scout.md, then apply the verifier's
  corrections to the previous draft.

  previous_draft_path: ${ITERATE_ROOT}/iter-{N-1}/draft.md
  previous_corrections_path: ${ITERATE_ROOT}/iter-{N-1}/corrections.jsonl

  Original user query (do not re-run discovery; preserve PASS
  claims; substitute true_value for FAIL claims; remove rows
  whose doi_resolves is fail; preserve rows whose claims are
  unverifiable — an unverifiable claim means the check did not
  complete, not that the row is wrong):

  [original query verbatim]
  ```

Run in foreground (verification cannot start until the proposer
returns).

#### Step B — Persist the proposer's draft

```bash
DRAFT="${ITERATE_ROOT}/iter-${N}/draft.md"
mkdir -p "${ITERATE_ROOT}/iter-${N}"
# Use Write tool with the proposer's full return content
```

#### Step C — Extract the proposer's claims.jsonl

```bash
extract_block "${ITERATE_ROOT}/iter-${N}/draft.md" "claims.jsonl" \
              "${ITERATE_ROOT}/iter-${N}/claims.jsonl"
```

If `claims.jsonl` ends up empty or malformed: log a warning. The
verifier handles this case via its `_legacy` sentinel emission;
the driver does not iterate when the sentinel appears in
`corrections.jsonl`.

#### Step D — Invoke the verifier

Invoke `lit-scout-verifier` via the `Agent` tool with the prompt:

```text
Verify this lit-scout draft for confabulation per the
lit-scout-verifier specification. Treat the attached markdown as
your sole input; you have no access to the proposer's context.

[contents of ${ITERATE_ROOT}/iter-${N}/draft.md verbatim, with no
edits, summary, pre-amble, or commentary]
```

Pure transfer. Do not add hints. Do not flag specific rows as
suspicious. Run in foreground. Typical runtime: 3–8 minutes for a
20–40 row table.

#### Step E — Persist the verifier's integrated report

```bash
REPORT="${ITERATE_ROOT}/iter-${N}/report.md"
# Use Write tool with the verifier's full return content
```

#### Step F — Extract corrections.jsonl

```bash
extract_block "${ITERATE_ROOT}/iter-${N}/report.md" "corrections.jsonl" \
              "${ITERATE_ROOT}/iter-${N}/corrections.jsonl"
```

If the corrections block is missing entirely from the verifier's
output: treat as a verifier-failure case (see Failure modes
below).

#### Step G — Read the verdict

Read the verifier's verdict from the integrated report — search
for the **Summary** block in the Verification section, or parse
the aggregate verdict from `corrections.jsonl` directly:

```bash
PASS_CT=$(grep -c '"status":"pass"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
PARTIAL_CT=$(grep -c '"status":"partial"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
FAIL_CT=$(grep -c '"status":"fail"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
UNVER_CT=$(grep '"status":"unverifiable"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" \
  | grep -vc '"claim_id":"_legacy"' || true)
LEGACY_CT=$(grep -c '"claim_id":"_legacy"' "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
TOTAL_CT=$(grep -c . "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" || true)
```

`UNVER_CT` excludes the `_legacy` sentinel, which also carries
`status: unverifiable` but means something else entirely (see G.5).

Five cases, evaluated in order:

##### G.1 — PASS (`FAIL_CT == 0 && PARTIAL_CT == 0 && UNVER_CT == 0 && LEGACY_CT == 0`)

Loop terminates successfully. Skip to "Final reporting".

##### G.2 — PARTIAL (`FAIL_CT == 0 && PARTIAL_CT > 0 && UNVER_CT == 0 && LEGACY_CT == 0`)

Loop terminates with the PARTIAL flag. The driver does not iterate.
Skip to "Final reporting".

##### G.3 — UNVERIFIABLE (`FAIL_CT == 0 && UNVER_CT > 0 && LEGACY_CT == 0`)

Some claims could not be checked. The driver does **not** iterate:
iterating cannot fix a claim whose problem is that the registry did
not answer, and re-running the verifier under the same throttle just
produces the same result more slowly.

Terminate with status `UNVERIFIABLE`. This is deliberately not
reported as PASS — the run established nothing about those rows, and
calling it PASS would assert a verification that did not happen.
Skip to "Final reporting".

##### G.4 — FAIL (`FAIL_CT > 0`) — continue to the throttle check

Any unverifiable claims in the same iteration ride through untouched.
Iterate on the `fail` claims only.

##### G.5 — Legacy / structural failure (`LEGACY_CT > 0`)

Proposer did not emit a `claims.jsonl` block. The closed loop cannot
operate. Skip to "Final reporting" with status `LEGACY_PROPOSER`.

#### Step H0 — Throttle check (FAIL only)

Before spending another iteration, check whether the registries were
actually answering:

```bash
# Terminate rather than iterate if a third or more of the claims
# could not be checked at all.
if [ "${TOTAL_CT}" -gt 0 ] && [ $(( UNVER_CT * 3 )) -ge "${TOTAL_CT}" ]; then
  STATUS=THROTTLED
fi
```

If `STATUS=THROTTLED`, terminate and skip to "Final reporting". A run
this heavily throttled has not tested the table, and each further
iteration costs several minutes of retry backoff to learn the same
nothing. The `fail` claims found so far remain valid — under the
verifier's rules a FAIL requires a status code it actually saw — so
report them, but do not act on the table until it can be re-verified.

#### Step H — No-progress check (FAIL only)

```bash
CURRENT_FAIL_SET=$(grep -E '"status":"fail"' \
  "${ITERATE_ROOT}/iter-${N}/corrections.jsonl" \
  | python3 -c "import sys,json; print(' '.join(sorted(json.loads(l)['claim_id'] for l in sys.stdin)))")
```

If `CURRENT_FAIL_SET == LAST_FAIL_SET` and `N > 0`, terminate with
status `NO_PROGRESS` — the proposer is unable to act on the
remaining fix_hints. Skip to "Final reporting".

Otherwise: `LAST_FAIL_SET = CURRENT_FAIL_SET`, increment `N`, loop.

#### Step I — Cap check

If `N == 5` and the verdict is still FAIL, terminate with status
`CAP_REACHED`. Skip to "Final reporting".

### Final reporting

Always return:

```markdown
# /lit-scout-iterate result: <query>

**Status:** <PASS | PARTIAL | UNVERIFIABLE | THROTTLED | FAIL | NO_PROGRESS | CAP_REACHED | LEGACY_PROPOSER>
**Iterations run:** <0..5>
**Workspace:** ${ITERATE_ROOT}

## Per-iteration trajectory

| Iter | Verdict | PASS | PARTIAL | FAIL | UNVERIFIABLE | Notes |
|------|---------|------|---------|------|---------------|-------|
| 0    | FAIL    | 25   | 1       | 4    | 0             | initial draft |
| 1    | FAIL    | 28   | 1       | 1    | 0             | 3 corrections applied |
| 2    | PASS    | 30   | 0       | 0    | 0             | final |

(Generate from each iter's corrections.jsonl counts.)

**Rows removed, if any, must be listed explicitly** with the status
code that justified each removal, carried up from the proposer's
"## Rows removed in iterate mode" section. A removal with no observed
status code behind it is a defect in the run, not a finding — report
it as such and restore the row.

## Outcome detail

(Status-specific block — see below.)

## Final integrated report

(Verbatim contents of the final iteration's report.md. This is the
verifier's integrated report from the iteration that terminated the
loop. Includes the corrected Findings table — what the user actually
wants.)

---

**Per-iteration trajectory:** ${ITERATE_ROOT}/iter-*/
**Final verifier report:** ${ITERATE_ROOT}/iter-{N}/report.md
**Final claims:** ${ITERATE_ROOT}/iter-{N}/claims.jsonl
**Final corrections:** ${ITERATE_ROOT}/iter-{N}/corrections.jsonl
**Zotero import manifest:** ${ITERATE_ROOT}/zotero-import-manifest.json
(M items created, K skipped as duplicates — see "## Zotero import" section in final report)
**BibTeX file:** /tmp/lit-scout-iterate-bibtex-YYYYMMDD-HHMMSS.bib
(N entries; backup deliverable — primary destination is the Zotero staging subcollection)
```

#### Outcome-detail blocks

- **PASS** — "Loop converged after N iterations. All claims pass
  verifier tolerance. Final corrected report below."

- **PARTIAL** — Header: "**⚠ PARTIAL VERDICT — DRIVER DID NOT
  ITERATE.** Tolerance exceeded but within the partial-tolerance
  band on K claims. The corrected Findings table below reflects
  the iter-{N-1} corrections applied; PARTIAL claims preserve the
  proposer's value. Review the divergences in
  `${ITERATE_ROOT}/iter-{N}/corrections.jsonl` and decide whether
  to (a) accept the report as-is, (b) re-invoke with a stricter
  tolerance, or (c) manually re-run on specific rows."

- **UNVERIFIABLE** — Header: "**⚠ VERIFICATION INCOMPLETE — DRIVER
  DID NOT ITERATE.** K claims across R rows could not be checked;
  the registries did not answer. No claim failed. **Those rows are
  preserved in the table below and flagged, not removed** — an
  unanswered lookup is not evidence against a citation. The
  observed cause for each row is in
  `${ITERATE_ROOT}/iter-{N}/corrections.jsonl` under
  `source_method`. If the cause is an exhausted OpenAlex budget it
  resets at midnight UTC; re-run `/lit-scout-verify` on the final
  report then, rather than editing the table now."

- **THROTTLED** — Header: "**⚠ RUN THROTTLED — LOOP STOPPED EARLY.**
  A third or more of the claims could not be checked, so the loop
  terminated rather than spending iterations on retry backoff. The
  K FAIL claims listed below were each confirmed against a status
  code and stand. The rest of the table is untested. Re-run once
  the rate limit resets."

- **FAIL** (only via CAP_REACHED) — Header: "**⚠ ITERATION CAP
  REACHED.** Five iterations did not produce a PASS or PARTIAL
  verdict. K FAIL claims remain. Manual investigation required."

- **NO_PROGRESS** — Header: "**⚠ LOOP STALLED.** Iteration {N}
  produced the same FAIL `claim_id` set as iteration {N-1}. The
  proposer's iterate-mode cannot act on the remaining fix_hints —
  the hints may be ambiguous, the metadata API may be returning
  inconsistent results, or there is a methodology mismatch.
  Review iter-{N}/draft.md for the proposer's self-check notes
  on what it tried."

- **LEGACY_PROPOSER** — Header: "**⚠ CLOSED LOOP NOT POSSIBLE.**
  The proposer's draft did not contain a machine-readable
  `claims.jsonl` block. Returning the single-round verifier
  output without iteration. To enable closed-loop verification,
  ensure the proposer agent definition includes the Iterate mode
  + Machine-readable claims block sections."

### Zotero staging import

Run after the final iteration completes on any terminal verdict
**except `LEGACY_PROPOSER`** (no structured claims means nothing to
import). The corrected Findings table is the deliverable users
actually act on; staging it directly into Zotero saves the manual
BibTeX-import step and propagates iterate-mode corrections (e.g.,
CrossRef family/given swaps) into the user's library — closing the
2026-05-22 BibTeX-coverage gap.

```bash
/home/shawn/personal-assistant/venv/bin/python3 \
  /home/shawn/personal-assistant/scripts/lit-scout-zotero-import.py \
  "${ITERATE_ROOT}" \
  --query "<the user's original query verbatim>" \
  --live
```

The script:

1. Reads `iter-N/claims.jsonl` (corrected values), `iter-N/corrections.jsonl`
   (warning-tag list), and `iter-N/report.md` (Fit/cluster from the
   verifier's corrected Findings table).
2. Dedups against every local Zotero library via sqlite (matches DOI
   case-insensitively across all 16 libraries). Skipped items are
   recorded with the library + existing collection context, **not**
   re-created.
3. Fetches fresh CrossRef metadata for each non-skipped DOI to fill
   journal-article fields (publicationTitle, volume, issue, pages,
   ISSN, abstract). Author field is overridden from `claims.jsonl`
   so iterate-mode corrections take precedence over raw CrossRef.
4. Creates a dated subcollection
   `YYYY-MM-DD-<query-slug>` under the staging collection (key from
   `$ZOTERO_STAGING_COLLECTION`). Idempotent — re-uses existing
   subcollection if name matches.
5. Batch-creates items (50 per pyzotero call) with tags:
   - `lit-scout-staging` (every import)
   - `lit-scout-run:YYYYMMDD-HHMMSS` (workspace timestamp)
   - `lit-scout-fit:high|medium|low` (preserves proposer's Fit)
   - `lit-scout-cluster:<slug>` (preserves proposer's cluster label)
   - `lit-scout-unverified:<field>` for any row where the verifier's
     final status was `fail`, `partial`, or `unverifiable` —
     surfaces in Zotero's tag filter for review
6. Writes `${ITERATE_ROOT}/zotero-import-manifest.json` with the
   full audit trail. Re-invocations against the same workspace
   merge with the prior manifest (idempotent — already-imported
   DOIs skip).

The script's stdout markdown is appended verbatim to the final
report as the "## Zotero import" section, slotted between the
verifier's "## Zotero actions" pass-through and the existing
BibTeX file pointer.

**Required env vars** (sourced from `~/personal-assistant/.env`):

- `ZOTERO_LIBRARY_ID` — user ID for personal library (e.g. `3097511`)
- `ZOTERO_API_KEY_PERSONAL` — key with personal-library write +
  all-groups read
- `ZOTERO_STAGING_COLLECTION` — top-level staging collection key
  (e.g. `IX8XR97K`)

**Smoke-test pattern for first-time setup or after Zotero schema
changes:** add `--limit 1` to import a single item first, eyeball
it in the Zotero client, then re-run without `--limit` to finish
the rest. The manifest dedups so the smoke-test item isn't
re-created.

**Dry-run is the script's default** (omit `--live`) — useful for
inspecting the plan without touching Zotero. Driver invocation
always passes `--live`.

### BibTeX generation

Run after the final iteration completes (regardless of status —
the corrected table is still useful):

```bash
BIBTEX_PATH="/tmp/lit-scout-iterate-bibtex-$(date +%Y%m%d-%H%M%S).bib"
# Parse DOIs from the final iteration's claims.jsonl
DOIS=$(python3 -c "
import json, re, sys
seen = set()
with open('${ITERATE_ROOT}/iter-${N}/claims.jsonl') as f:
    for line in f:
        cid = json.loads(line)['claim_id']
        m = re.match(r'(10\\.[^-]+(?:-[^-]+)*)-(?:authors|year|title|citation_count|doi_resolves)\$', cid)
        if m:
            doi_slug = m.group(1)
            doi = doi_slug.replace('-', '/', 1)
            seen.add(doi)
for d in sorted(seen): print(d)
")
/home/shawn/personal-assistant/venv/bin/python3 \
  /home/shawn/personal-assistant/scripts/lit-search.py bibtex \
  $DOIS > "$BIBTEX_PATH"
```

If the command fails, append a brief note to the output ("BibTeX
generation failed: [reason]") but still return the verified report.

## Examples

```text
/lit-scout-iterate Bayesian methods for archaeological dating uncertainty

/lit-scout-iterate LLM-assisted data extraction from historical documents;
scope: 2022-present; include preprints
```

## Failure modes and recovery

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Proposer errors at iter 0 | Agent returns error, no draft | Re-run `/lit-scout-iterate` with same query; nothing persisted that could conflict. |
| Proposer errors at iter N>0 | Iterate mode failure | The iter-{N-1}/ outputs remain. Manually re-invoke `lit-scout` with `previous_draft_path` + `previous_corrections_path` pointing there. |
| Verifier errors | Step D returns error or malformed output | iter-{N}/draft.md is preserved. Manually invoke `lit-scout-verifier` against it via `/lit-scout-verify`. |
| Corrections block missing | Step F extraction yields empty file | Treat as verifier-failure case. Surface the verifier's narrative output; do not iterate. |
| Cap reached | Status CAP_REACHED | Inspect the final FAIL claims and their fix_hints; the proposer may be unable to satisfy the verifier on those rows. |
| Stall | Status NO_PROGRESS | Same as cap-reached, but earlier. Often indicates an ambiguous fix_hint or a metadata API inconsistency. |
| BibTeX errors | Step BibTeX returns non-zero | Note in output; still return integrated report. |
| Zotero import errors | `lit-scout-zotero-import.py --live` returns non-zero | Note the failure in the Zotero-import section but still return the integrated report and BibTeX. Common causes: missing env vars (`ZOTERO_API_KEY_PERSONAL`, `ZOTERO_STAGING_COLLECTION`), revoked key, network drop mid-batch. The workspace and manifest remain intact for manual re-run via `scripts/lit-scout-zotero-import.py <workspace> --query "..." --live`. |
| Zotero import partial failure | Some items in `failed_live` block | The manifest records which DOIs succeeded; re-running picks up from there via the idempotent skip-list. |
| User abort | Loop interrupted | The partial trajectory in `${ITERATE_ROOT}/` is inspectable. Future runs should use a new ITERATE_ROOT. |

## Notes

- The proposer and verifier both run in foreground as separate
  sub-agent calls. Each gets a fresh context window. Neither can
  see the other's reasoning or tool-call history.
- The main conversation is the channel between them; by design it
  does no reasoning about the content, only mechanical forwarding
  of file paths and block extraction.
- **Inline-block transport rationale**: sub-agents are blocked from
  Write on `.md` files (settled 2026-04-19 after `lit-scout-verifier`
  v4.x tests) and behaviour on `.jsonl` is untested. Both proposer
  and verifier embed structured data as fenced `jsonl` blocks in
  their markdown output, with HTML-comment markers (`<!-- BEGIN
  ... -->` / `<!-- END ... -->`) the driver extracts. This avoids
  the harness-restriction risk entirely at the cost of one extra
  awk/sed pass per iteration.
- Iteration cap of 5 is rule-of-thumb; mirrors `/data-profile-iterate`.
  Tune in light of real iteration experience.
- PARTIAL band currently rule-of-thumb (per-field thresholds in
  `lit-scout-verifier.md` "Tolerance bands" section). Quantifying
  "how partial" more precisely is deferred pending experience with
  actual partial outcomes.
- Each iteration is one full proposer call + one full verifier
  call. Typical query: 15–25 minutes per iteration; iterate-mode
  passes are faster (3–8 min) because the proposer skips
  discovery.
- Do NOT attempt to invoke the verifier from inside the proposer's
  context or vice versa. The Claude Code harness forbids nested
  sub-agent dispatch. Serial dispatch from the main conversation
  is the only realisable path.
- For one-shot (non-iterating) lit-scout work, use `/lit-scout` —
  it does single proposer + verifier round and returns. Use
  `/lit-scout-iterate` when the cost of an unfixable confabulation
  is higher than the cost of an extra 1–3 iterations.
