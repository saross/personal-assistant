# /done — Mark Task Complete

Mark a focus item or task as complete. Archive it. Celebrate briefly. Refocus.

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

6. **Archive** to `~/personal-assistant/tasks/done/YYYY-MM.md`

If the file does not exist, create it with the header:

```markdown
# Completed — [Month] [Year]

| Completed | Item | Project | Days in Focus | Notes |
|-----------|------|---------|---------------|-------|
```

Append a row:

```markdown
| YYYY-MM-DD | [Item] | [Project] | [N] | [notes or —] |
```

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
  In focus for [N] days. Archived to tasks/done/YYYY-MM.md.
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

If the matched item is from inbox.md rather than FOCUS.md:

1. **Remove** the matching line from inbox.md (the `- [ ] ...` line)
2. **Archive** to done/YYYY-MM.md with "Days in Focus" as "—" (was not a focus item)
3. **Confirm** briefly

## Notes

- The archive is append-only — completed items are never deleted
- Days in focus is calculated from the Started date in FOCUS.md
- If the user says `/done` with no arguments, show current focus items and ask which one
- Encourage single-threading when a slot opens — research shows Shawn completes faster with one focus item
- Do NOT update GitHub Issues (that's for /sync-board in Phase 4)
