# /lit-scout-verify — Run verifier on an existing draft

Resume mode for the `/lit-scout` pipeline. Runs the
`lit-scout-verifier` serial agent against an existing draft file
without re-running the proposer. Use when the main `/lit-scout`
pipeline's verification step failed and you want to retry, or when
you have a draft from any other source that needs verifying.

## Usage

```text
/lit-scout-verify [path-to-draft]
```

## Arguments

- `[path-to-draft]` — absolute path to a markdown file containing a
  lit-scout-format draft. Must contain a `## Findings table` section
  in the expected column format (see `~/.claude/agents/lit-scout.md`
  output contract).

If no path is provided, ask the user which draft to verify — list
recent files under `/tmp/lit-scout-drafts/` if any are present.

## Behaviour

### Step 1 — Load the draft

Read the file at the supplied path. Verify it contains:
- A `## Findings table` heading
- A table with the expected columns (#, Fit, Cites, Authors (Year),
  Title, DOI, Chain, Chains, Cluster, Status)

If the file is missing or malformed, return an error with the reason
and do not invoke the verifier.

### Step 2 — Invoke the verifier

Invoke `lit-scout-verifier` via the `Agent` tool with the draft as
input. The prompt is identical to the main `/lit-scout` step 3:

```text
Verify this lit-scout draft for confabulation per the
lit-scout-verifier specification. Treat the attached markdown as
your sole input; you have no access to the proposer's context.

[draft verbatim]
```

**Pure transfer.** No hints, no commentary, no pre-summary.

### Step 3 — Handle the verifier response

Same as `/lit-scout` steps 4a/4b:

- **Success**: receive integrated report; proceed to Step 4.
- **Failure**: emit failure banner with the draft path echoed back so
  the user can retry later. Skip Steps 4–5.

### Step 4 — Persist the verifier's integrated report

Same as `/lit-scout` step 5 — use the `Write` tool to save the
verifier's output verbatim to:

```text
/tmp/lit-scout-verifier/report-$(date +%Y%m%d-%H%M%S).md
```

Persistence is the orchestrator's responsibility, not the
sub-agent's (see context note in `commands/lit-scout.md` step 5).

### Step 5 — Generate BibTeX

Same as `/lit-scout` step 6 — run `lit-search.py bibtex` on the
verified DOIs from the corrected table, save to
`/tmp/lit-scout-bibtex-$(date +%Y%m%d-%H%M%S).bib`.

### Step 6 — Return

Return the verifier's integrated output with persisted-report and
BibTeX paths appended. Also echo the source draft path so the user
has a complete audit trail of which draft was verified:

```markdown
[verifier output verbatim]

---

**Verifier report (persisted):** /tmp/lit-scout-verifier/report-YYYYMMDD-HHMMSS.md

**BibTeX file:** /tmp/lit-scout-bibtex-YYYYMMDD-HHMMSS.bib

**Verified draft:** [original path supplied by user]
```

## Examples

```text
/lit-scout-verify /tmp/lit-scout-drafts/draft-20260418-212400.md

/lit-scout-verify /home/shawn/Downloads/my-lit-scout-draft.md
```

## Use cases

- The main `/lit-scout` pipeline completed Step 1 but failed at Step
  3 (verifier error or timeout). The draft was saved at Step 2 —
  resume with this command.
- You have a lit-scout-format draft from any other source (an
  earlier session, a manual draft, a peer's output) and want to
  run attribution verification on it.
- You want to re-verify a previously-verified draft (e.g., after
  the CrossRef citation counts have updated) — point at the draft
  or at a prior verifier output (either should work if the table is
  well-formed).

## Notes

- This command does not run discovery. No new papers are found, no
  chaining is done. It operates only on what is already in the
  supplied draft.
- If the supplied file is itself a prior verifier output (contains a
  "Corrected findings table"), the verifier will re-verify the
  corrected table, not the original. This is fine and arguably
  desirable (drift-check).
- Persistence to `/tmp/lit-scout-verifier/` still occurs, so
  successive re-verifications leave a trail of dated reports.
