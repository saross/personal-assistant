# /memory-health — Memory-System Health Report

Produce the memory-system health report: corpus size and composition, growth
and churn, anchor health, sync and archive integrity, and the confabulation-
flag rate. An opt-in Tier-C pass adds the write-time fresh-anchor-fail rate.

This is the on-demand entry to the standing report (write-path plan item 18 /
P6). The same report is also folded into the `/weekly-review` ritual, so the
weekly review surfaces corpus-health trends; use `/memory-health` whenever you
want a snapshot between reviews.

The report is **read-only** — it mutates nothing (no locks, no PostgreSQL
writes, no cursor changes), so it is safe to run at any time, including while
extraction hooks are appending concurrently (it reads a point-in-time
snapshot).

## Usage

```text
/memory-health            # sections A–E (fast, ~1 s)
/memory-health --tier-c   # also run the write-time anchor-fail audit (~1.5 min)
```

## Arguments

- `--tier-c` (optional) — also run section [F], the Tier-C write-time
  fresh-anchor-fail rate. This does per-anchor git resolution over the broad
  repo set and takes ~1.5 minutes, so it is off by default. Pass it through
  to the script. `--tier-c-days N` changes the trailing window (default 30).

## Behaviour

1. **Run** the report via Bash, passing through any `--tier-c` / `--json`
   flags the user supplied:

```bash
venv/bin/python3 ~/personal-assistant/scripts/memory-health-report.py [flags]
```

2. **Relay** the report. The script prints a six-section text report (or JSON
   with `--json`); show it to the user as-is — the figures are already
   formatted and each is re-derivable at source.

3. **Surface the verdict.** The script exits `0` when all integrity checks are
   clean and `1` when an integrity check failed (a recall leak — an archived id
   still `is_active=TRUE`; a duplicate-id tripwire; or quarantined PG-drops).
   If it exits `1`, call that out prominently: it is a real corpus-integrity
   finding, not a cosmetic one. Exit `2` means the report could not run (the
   canonical JSONL is missing) — report that plainly.

4. **Interpret lightly, do not over-read.** The confab-flag rate is only
   meaningful once enough verifier rows have accrued (a 2/2 rate on n=2 is
   noise, not a signal). The Tier-C fail rate counts records with ≥1 anchor
   that resolves nowhere; the failing-file-ref split (recoverable / ambiguous /
   absent) classifies only the anchors that themselves fail, so "recoverable"
   is genuinely a fixable-by-prefix backlog, not an artefact.

## Notes

- No API calls, no cost. Pure local reads (JSONL, PostgreSQL, `data/logs/*`,
  git for Tier-C only).
- Reuses the building blocks rather than re-deriving them:
  `audit_archive_parity()` from `audit-postgres-sync.py` (P5),
  `anchor_verify.verify_memory` / `triage_anchors.recovery_status` (items
  9/20/21), and `confab-flags.log` (§8 measurement 3, Tier A + Tier B).
