# /lit-scout — Literature Scout (with verification)

Discover and verify academic literature on a topic. Orchestrates a
two-agent serial pipeline: `lit-scout` (proposer) runs discovery and
emits a draft; `lit-scout-verifier` (verifier) re-queries every DOI
and emits an integrated final report; the command then generates
BibTeX from the verified DOIs.

Always runs with the verifier. There is no bypass.

## Usage

```text
/lit-scout [query]
```

## Arguments

- `[query]` — free-text description of the literature to scout. Can
  include target venues, scope constraints, time periods, etc.

## Behaviour

The slash command is a thin orchestrator. It performs **no reasoning
about the content** of either agent's output. Its only substantive
actions are: invoke agents, forward the proposer's draft verbatim to
the verifier, and run the BibTeX CLI on verified DOIs. All content
judgement lives inside the agents.

### Step 1 — Invoke the proposer

Invoke the `lit-scout` sub-agent via the `Agent` tool with the user's
query as the prompt. Run in foreground (verification cannot start
until the proposer returns). Typical runtime: 10–15 minutes.

Pass the query through as-received. Do not paraphrase, enrich, or
inject advice about what to prioritise — the proposer's methodology
is documented in `~/.claude/agents/lit-scout.md`.

### Step 2 — Persist the draft

When the proposer returns, write its output verbatim to a dated file
for resume-mode recovery:

```bash
mkdir -p /tmp/lit-scout-drafts
cat > /tmp/lit-scout-drafts/draft-$(date +%Y%m%d-%H%M%S).md
```

Note the path — it is returned to the user on verifier failure so
they can resume with `/lit-scout-verify`.

### Step 3 — Invoke the verifier

Invoke the `lit-scout-verifier` sub-agent via the `Agent` tool. The
prompt is **only**:

```text
Verify this lit-scout draft for confabulation per the
lit-scout-verifier specification. Treat the attached markdown as
your sole input; you have no access to the proposer's context.

[proposer's draft output verbatim, with no edits, summary,
pre-amble, or commentary]
```

Do not add hints. Do not flag specific rows as suspicious. Do not
summarise the draft for the verifier. **Pure transfer.** Any
contamination at this boundary defeats the independence the serial
design exists to preserve.

Run in foreground. Typical runtime: 3–8 minutes for a 20–40 row
table.

### Step 4a — Handle verification success

The verifier returns an integrated report containing:
- TL;DR (pass-through from proposer)
- Verification block (summary, corrections applied, unverifiable)
- Original findings table (pass-through from proposer, verbatim)
- Corrected findings table (final)
- Analysis sections (pass-through from proposer)

Proceed to Step 5.

### Step 4b — Handle verification failure

If the verifier returns with an explicit failure marker, times out,
errors, or returns malformed output, emit a failure banner and
return the draft unverified:

```markdown
⚠ **VERIFICATION FAILED** — the proposer's draft is below,
unverified. To re-run verification on this draft, use:

    /lit-scout-verify /tmp/lit-scout-drafts/draft-YYYYMMDD-HHMMSS.md

Failure reason: [brief description from verifier's response or
error message]

---

[proposer's draft verbatim, including its `⚠ VERIFICATION PENDING`
marker]
```

Do not attempt to re-invoke the verifier automatically — that
decision is the user's. One invocation per slash-command run. Skip
Steps 5–6 on failure (do not persist a partial verifier output; do
not generate BibTeX from unverified DOIs).

### Step 5 — Persist the verifier's integrated report

Write the verifier's output verbatim to a durable file before
proceeding. Use the `Write` tool with path:

```text
/tmp/lit-scout-verifier/report-$(date +%Y%m%d-%H%M%S).md
```

No edits, no commentary added. The file is a faithful record of
what the verifier returned. Create the directory via `Bash mkdir -p
/tmp/lit-scout-verifier` first if it doesn't exist.

Context: persistence was previously the verifier sub-agent's own
responsibility. The v4 test (2026-04-19) surfaced a harness policy
blocking sub-agents from writing report files via the `Write`
tool, so the responsibility moved to the orchestrator. The
orchestrator runs in a main-conversation context with unrestricted
file access and can persist reliably. The stream-drop risk window
between sub-agent return and orchestrator persistence is accepted
as small and recoverable via `/lit-scout-verify` against the saved
proposer draft from Step 2.

### Step 6 — Generate BibTeX from verified DOIs

Parse the DOIs from the **corrected findings table** (from Step 4a).

Run:

```bash
BIBTEX_PATH="/tmp/lit-scout-bibtex-$(date +%Y%m%d-%H%M%S).bib"
/home/shawn/personal-assistant/venv/bin/python3 \
  /home/shawn/personal-assistant/scripts/lit-search.py bibtex \
  "DOI1" "DOI2" ... > "$BIBTEX_PATH"
```

If the command fails, append a brief note to the output ("BibTeX
generation failed: [reason]") but still return the verified report.

### Step 7 — Return the integrated output

Return the verifier's full integrated output to the user, with file
paths appended at the end:

```markdown
[verifier output verbatim]

---

**Verifier report (persisted):** /tmp/lit-scout-verifier/report-YYYYMMDD-HHMMSS.md

**BibTeX file:** /tmp/lit-scout-bibtex-YYYYMMDD-HHMMSS.bib
(N entries; drag-drop into Zotero or File → Import)

**Proposer draft (for resume mode):** /tmp/lit-scout-drafts/draft-YYYYMMDD-HHMMSS.md
```

## Examples

```text
/lit-scout Bayesian methods for archaeological dating uncertainty

/lit-scout Munsell colour standardisation in soil science and
archaeology; target venue: Journal of Archaeological Science

/lit-scout LLM-assisted data extraction from historical documents;
scope: 2022-present; include preprints
```

## Failure modes and recovery

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Proposer errors | Agent returns error, no draft | Re-run `/lit-scout` with same query |
| Verifier errors | Step 3 returns error | Draft saved at step 2 — use `/lit-scout-verify <path>` |
| Verifier times out | No response after ~15 min | Same as above |
| Verifier returns malformed output | Missing corrected table, missing verification block | Same as above |
| Verifier persistence write errors | Step 5 Write fails | Log the error; return the integrated output without the persisted-path line. Do not block BibTeX or return steps. |
| BibTeX CLI errors | Step 6 stderr non-empty | Report noted in output; verified report still returned |

## Notes

- The proposer and verifier both run in foreground as separate
  sub-agent calls. Each gets a fresh context window. Neither can
  see the other's reasoning or tool-call history.
- The main conversation is the channel between them; by design it
  does no reasoning about the content, only mechanical forwarding.
- Persistence is exclusively the orchestrator's job (settled
  2026-04-19 after v4.3). The orchestrator writes the full
  integrated report to
  `/tmp/lit-scout-verifier/report-YYYYMMDD-HHMMSS.md` at Step 5.
  The sub-agent does not persist anything — attempts to write
  receipt or report files are blocked or unreliable. A full arc
  of four tests (v4 → v4.3) confirmed this; see
  `data/notes/lit-scout-v4.3-evaluation-2026-04-19.md` for the
  empirical record and rationale.
- Draft files persist at `/tmp/lit-scout-drafts/` until `/tmp` is
  cleaned. They enable `/lit-scout-verify` resume mode.
- BibTeX files at `/tmp/lit-scout-bibtex-*.bib` can be moved/renamed
  freely; the slash command writes them with dated names to avoid
  overwrites.
- Do NOT attempt to invoke the verifier from inside lit-scout's
  context. The Claude Code harness forbids nested sub-agent dispatch
  (docs/sub-agents.md line 469). Serial dispatch from the main
  conversation is the only realisable path.
