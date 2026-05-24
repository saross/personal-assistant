# /done — Mark Task Complete

Mark a focus-slot task as complete: rotate the slot, prompt for refocus.

**Closure record:** as of 2026-05-24, closures are recorded in the day's
`/recap` (in the "Committed vs Actual" table) and consolidated by
`/weekly-review` into the Completions section. `/done` no longer writes to
`tasks/done/YYYY-MM.md` — that file retired as a canonical source. `/done`
remains the trigger for **slot rotation + refocus prompting**, which is its
unique value-add (recap captures closure but does not change FOCUS.md).

## Usage

```text
/done [task description or slot reference]
```

## Arguments

- `[task description]` — Fuzzy match against current focus items or inbox items
- Can also reference by slot: `/done slot 1`, `/done slot 2`

## Behaviour

1. **Read** `~/personal-assistant/tasks/FOCUS.md`
2. **Match** the user's description to a focus slot item (fuzzy match on name)
3. **If no match in focus**, check `~/personal-assistant/tasks/inbox.md` for matching inbox items
4. **If still no match**, ask the user to clarify which item they mean
5. **If matched**, confirm with the user:

```text
Completing: [item name]
  Project: [project]
  In focus for: [N] days (since YYYY-MM-DD)

Correct? Any notes for the archive?
```

6. **Record the closure for the day's `/recap`** — surface the item name +
   project + days-in-focus + any notes the user supplied. If a recap is
   open in the session, append to its "Committed vs Actual" table. If not,
   simply state the closure clearly so the user knows it will need to be
   captured in tonight's recap (or, if the task closed outside today's
   commitments, in the next standup's "Yesterday" section).

   **Do not write to `tasks/done/YYYY-MM.md`** — that file is retired as a
   canonical source. The weekly review consolidates closures from recaps
   into its Completions section.

7. **Clear** the FOCUS.md slot — set header to `## Slot N: [Empty]` and remove all the detail fields (the bullet-point lines), leaving only the header line and the `---` divider below it. The result must match the empty slot format defined in `/focus`'s Format Contract:

```markdown
## Slot N: [Empty]

---
```

8. **Update** the focus check header: `**Focus check:** N of 2 slots filled`
9. **Update** the last-updated date
10. **Acknowledge** completion briefly:

```text
Done: [item name]
  In focus for [N] days. Surfaced for tonight's recap.
```

11. **If a focus slot is now empty**, prompt for refocus:

```text
Slot [N] is now open.

You have [M] items paused and an inbox with [K] items.
Options:
  (a) Pull something from Paused into focus
  (b) Stay single-threaded on [remaining focus item]
  (c) Add something new with /focus add

Given your pattern of finishing faster with single focus, consider (b).
```

If both slots are now empty:

```text
Both focus slots are empty. What's most important right now?
Use /focus add [item] to set your next priority.
```

## Completing Inbox Items

If the matched item is from `tasks/inbox.md` rather than FOCUS.md:

1. **Remove** the matching `- [ ]` row from `inbox.md`. Inbox is a working
   in-tray (not an audit log); dispositioned rows leave the file.
2. **Surface for the day's `/recap`** — append the closure to the open recap's
   "Committed vs Actual" table if one exists. If not, simply state the closure
   clearly so the user knows it will need to be captured in tonight's recap
   (or in the next standup's "Yesterday" section if the task closed outside
   today's commitments).
3. **Confirm** briefly.

There is no separate done file to archive to — the recap (consolidated by
the weekly review's Completions section) is the canonical record for
inbox-direct closures.

## Notes on inbox disposition (refactor of 2026-05-24)

`tasks/inbox.md` is now a working in-tray, not an audit log. Disposition
removes the row from inbox; the canonical record lives in the destination:

| Disposition | Where the inbox row goes | Where the canonical record lives |
|---|---|---|
| `Done` (small task done from inbox) | Removed from inbox | Today's `/recap` → weekly-review Completions |
| `Moved to backlog` | Removed from inbox | New row in `tasks/backlog.md` |
| `Promoted to focus` | Removed from inbox | Populated FOCUS.md slot |
| `Consolidated into existing backlog row` | Removed from inbox | Addendum on existing backlog row |
| `Killed` / `Superseded` / `Resolved without action` | Moved to `tasks/inbox-archive.md` | The archive file (no downstream destination exists) |

Pre-2026-05-24 historical inbox dispositions live in
`tasks/inbox-archive.md` (one-time bulk migration of 61 rows).

## Notes

- Days in focus is calculated from the Started date in FOCUS.md (slot tasks only).
- If the user says `/done` with no arguments, show current focus items and ask which one.
- Encourage single-threading when a slot opens — research shows Shawn completes faster with one focus item.
- Do NOT update GitHub Issues (that's for /sync-board in Phase 4).
