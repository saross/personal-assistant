# /focus — Manage Focus Slots

View and manage the 1–3 items in active focus. Enforces the focus limit.

**Slot names must be actionable tasks**, not project names. Use concrete
deliverables (e.g., "LLM-History-Paper results write-up") rather than
abstract buckets (e.g., "LLM-History-Paper"). Projects are tracked via the
`Project` grouping tag field, not the slot name.

## Usage

```text
/focus
/focus add [item]
/focus remove [item]
/focus swap [current] -> [new]
```

## Arguments

- *(no arguments)* — Show current FOCUS.md status
- `add [item]` — Add an item to an empty focus slot
- `remove [item]` — Remove an item from focus (must classify as done/paused/abandoned)
- `swap [current] -> [new]` — Replace one focus item with another in a single operation

## Behaviour

### Show Status (bare `/focus`)

1. **Read** `~/personal-assistant/tasks/FOCUS.md`
2. **Display** the current state: slots filled, items, days in focus, deadline status
3. **No commentary** unless something is obviously wrong (e.g., both slots empty)

### Add (`/focus add [item]`)

1. **Read** `~/personal-assistant/tasks/FOCUS.md`
2. **Count** filled slots (look for slot headers that are NOT `[Empty]`)
3. **Read** `~/personal-assistant/tasks/SYSTEM.md` to get `focus_limit` (currently 3).
   **If all slots filled**, refuse:

```text
Focus is full (N of N slots):
  Slot 1: [current item 1]
  Slot 2: [current item 2]
  Slot 3: [current item 3]

To add [new item], you must remove or pause one of these first.
Use: /focus remove [item] or /focus swap [item] -> [new item]
```

4. **If a slot is available**, ask the user for the required fields:
   - **Item name:** An actionable task, not a project name (e.g., "Flinders onboarding presentation" not "EFN")
   - **Project:** Grouping tag (e.g., `research/llm-history-paper`, `business/fieldmark`)
   - **Deadline:** (date or "none")
   - **Why this matters:** (one sentence connecting to real stakes)
   - **Next action:** (the specific next thing to do)

5. **Write** the item into the first empty slot in FOCUS.md using the format contract:

```markdown
## Slot N: [Item Name]

- **Project:** [path]
- **Started:** YYYY-MM-DD
- **Deadline:** YYYY-MM-DD or None
- **Why this matters:** [text]
- **Next action:** [text]
- **Blocked by:** Nothing
```

6. **Update** the focus check header: `**Focus check:** N of 3 slots filled`
7. **Update** the last-updated date

### Remove (`/focus remove [item]`)

1. **Read** `~/personal-assistant/tasks/FOCUS.md`
2. **Find** the matching slot (fuzzy match on item name). If no slot matches, list the current focus items and ask the user to clarify which one they mean. If both slots are empty, say "Both focus slots are already empty. Nothing to remove."
3. **Ask** the user to classify:

```text
Removing [item] from focus. What's the status?
  (a) Done — moving to archive (/done will handle this)
  (b) Paused — will return to it (add to Paused table)
  (c) Abandoned — not doing this
```

4. **If paused**, move to the Paused table at the bottom of FOCUS.md:

```markdown
| [Item] | [Project] | YYYY-MM-DD | [Why paused] |
```

Ask the user why it's being paused.

5. **If abandoned**, note it in the archive (tasks/done/YYYY-MM.md) with status "Abandoned"
6. **If done**, tell the user to use `/done` instead (it handles archiving properly)
7. **Clear** the slot by setting its header to `## Slot N: [Empty]` and removing the detail fields (replace with just the header and divider)
8. **Update** the focus check header and last-updated date

### Swap (`/focus swap [current] -> [new]`)

1. **Remove** the current item (following the remove flow — ask for classification)
2. **Add** the new item (following the add flow — ask for required fields)
3. This is a convenience shortcut for remove + add in one operation

## Format Contract

FOCUS.md must always follow this structure (Python hooks parse it).
**Slot names are actionable tasks** — the `Project` field is a grouping tag.

```markdown
# Current Focus

**Last updated:** YYYY-MM-DD
**Focus check:** N of 3 slots filled

---

## Slot 1: [Actionable Task Name or [Empty]]

- **Project:** [grouping tag, e.g. research/llm-history-paper]
- **Started:** YYYY-MM-DD
- **Deadline:** YYYY-MM-DD or None
- **Why this matters:** [text]
- **Next action:** [text]
- **Blocked by:** [text or Nothing]

---

## Slot 2: [Item Name or [Empty]]

[same fields, or just header if empty]

---

## Slot 3: [Item Name or [Empty]]

[same fields, or just header if empty]

---

## Paused (Must Finish Focus Before Resuming)

| Item | Project | Paused Since | Why Paused |
|------|---------|--------------|------------|

---

## Rules

[unchanged]
```

An empty slot looks like:

```markdown
## Slot N: [Empty]

---
```

A filled slot has all the detail fields between the header and the divider.

## Integrity Check

If the user has swapped focus items 3+ times in a week, note the pattern:

```text
You've changed focus [N] times this week. Each swap costs momentum.
Are you rotating through items instead of finishing them?
```

## Notes

- The 3-item limit is non-negotiable. Not "just this one small thing."
- Started date is always today when adding — it measures time in focus, not project age
- The Paused table is visible in FOCUS.md as a reminder, not a to-do list
- If both slots are empty after a remove, prompt: "Both focus slots are empty. What's most important right now?"
