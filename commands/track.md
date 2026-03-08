# /track — Time Tracking

Record hours spent on projects. Designed for lightweight daily logging,
not minute-level precision.

## Usage

```text
/track [project] [hours] [description]
/track summary [period]
```

## Arguments

### Recording

- `[project]` — Project name (required). Use short names matching `Project`
  field in FOCUS.md/backlog (e.g., `fieldmark`, `llm-history-paper`,
  `anu-digital-humanities`, `personal-assistant`)
- `[hours]` — Hours spent, as a decimal (required). E.g., `2`, `1.5`, `0.5`
- `[description]` — Brief note on what was done (optional but recommended)

### Reporting

- `summary` — Show totals for the current week (Monday–Sunday)
- `summary week` — Same as bare `summary`
- `summary month` — Show totals for the current calendar month
- `summary [YYYY-MM-DD]` — Show the week containing that date

## Behaviour

### Recording Time

1. **Parse** the input to extract project, hours, and description
2. **Normalise** the project name to lowercase with hyphens
3. **Validate** hours is a positive number ≤ 16 (sanity check)
4. **Append** a line to `~/personal-assistant/reports/time-log.csv`

If the file doesn't exist, create it with a header row:

```csv
date,project,hours,description
```

Append one line per entry:

```csv
2026-03-08,fieldmark,3.5,Control Centre screenshots and descriptions
```

5. **Confirm** the entry:

```text
Tracked: 3.5h on fieldmark — "Control Centre screenshots and descriptions"
Today's total: 5.5h (fieldmark: 3.5h, llm-history-paper: 2h)
```

6. **If description is missing**, record the entry but note:

```text
Tracked: 2h on llm-history-paper (no description)
Consider adding a brief note for future reference.
```

### Reporting (summary)

1. **Read** `~/personal-assistant/reports/time-log.csv`
2. **Filter** to the requested period
3. **Display** a summary:

```text
## Time Summary — Week of 2026-03-03

| Project | Mon | Tue | Wed | Thu | Fri | Sat | Sun | Total |
|---------|-----|-----|-----|-----|-----|-----|-----|-------|
| fieldmark | 2 | — | 3.5 | 1 | — | — | — | 6.5 |
| llm-history-paper | 4 | 6 | 2 | 5 | 3 | — | — | 20 |
| **Total** | **6** | **6** | **5.5** | **6** | **3** | **—** | **—** | **26.5** |
```

For monthly summaries, show weekly subtotals and a grand total.

### Integration with /recap

The `/recap` command (step 5b, work log) includes an optional Hours subsection.
If the user mentions hours during the recap, offer to record them via `/track`
as well:

```text
You mentioned spending ~4 hours on the paper today. Want me to /track that?
```

This keeps both records in sync without requiring double entry.

## Examples

```text
/track llm-history-paper 4 Section 4.5 editing and data verification
/track fieldmark 1.5 Steve's Slack requests
/track anu-digital-humanities 2 Week 3 Canvas content
/track personal-assistant 1 Memory system improvements
/track summary
/track summary month
```

## Notes

- CSV format chosen for portability — can be opened in any spreadsheet app,
  queried with standard command-line tools, or imported into time-tracking
  software later
- Multiple entries per day per project are fine — they accumulate
- Hours are approximate. This is for pattern recognition and invoicing
  estimates, not billable-hour precision
- Project names should be consistent. If an unrecognised project name is used,
  note it and suggest the closest match from existing entries
- The CSV lives in `reports/` (data submodule) — it syncs across machines
  via git
