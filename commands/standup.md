# /standup — Daily Accountability Check

The centrepiece of the task system. Forces confrontation with reality.

## Usage

```text
/standup
```

No arguments. Reads everything, generates the standup, saves it, displays it.

## Behaviour

### 1. Load State

Read these files:

- `~/personal-assistant/tasks/FOCUS.md` — Current focus items
- `~/personal-assistant/tasks/SYSTEM.md` — Escalation parameters
- `~/personal-assistant/tasks/inbox.md` — Unprocessed captures
- `~/personal-assistant/tasks/waiting-for.md` — Blocked items
- `~/personal-assistant/memories/memories.jsonl` — Recent memories for pattern detection and prompt coaching
- `~/personal-assistant/notes/llm-craft.md` — Prompt craft notebook (for coaching section fallback)

### 2. Calculate Metrics

If both focus slots are empty, skip the Focus Check, At Risk, Patterns, and escalation sections. Instead, output:

```text
## Focus Check

Both focus slots are empty. Nothing is being tracked.

Use /focus add [item] to set your priorities.
If you're avoiding committing to something, that's worth examining.
```

Then proceed to Inbox, Waiting For, and Today sections as normal.

For each focus slot that is filled (not `[Empty]`):

- **Days in focus:** Today minus the `Started` date
- **Deadline status:** If a deadline exists, calculate days until/past deadline
  - Future: "in N days"
  - Today: "TODAY"
  - Past: "OVERDUE by N days"
- **Inbox count:** Number of `- [ ]` lines in inbox.md
- **Waiting-for count:** Number of data rows in the waiting-for table (exclude header and separator rows)

### 3. Determine Escalation Level

Read SYSTEM.md for escalation parameters. For each focus item, based on days in focus:

- **Days 1-2** (below `escalation_question_day`): Neutral status
- **Days 3-6** (at or above `escalation_question_day`, below `escalation_confront_day`): Curious questions
- **Days 7-13** (at or above `escalation_confront_day`, below `escalation_abandon_day`): Direct confrontation
- **Day 14+** (at or above `escalation_abandon_day`): Abandon discussion

**Progress exception:** If there is evidence of meaningful progress in the last 7 days (progress/completion memories, updated next actions, user-reported work), cap escalation at the **confrontational** level regardless of days in focus. The abandon discussion exists for items that are truly stalled, not for long-running tasks with active forward movement. Long duration alone is not a problem — long duration with no progress is. When applying this exception, note it explicitly (e.g., "Day 22 in focus — confrontational, not abandon, because progress is evident").

### 4. Detect Patterns (from memories)

Search `memories.jsonl` for memories from the last 14 days in these categories:
`slip`, `commitment`, `progress`, `completion`, `blocker_real`, `blocker_excuse`, `system_friction`

Look for:

- Repeated slips on the same items
- Avoidance patterns (comfortable work progressing while hard work stalls)
- Stated commitments versus actual progress
- Successfully completed items and what enabled them

If no relevant memories exist, omit the Patterns section entirely.

### 5. Select Prompt Coaching Content

Search for coaching material for the Prompt Craft section:

1. **Check recent memories** (last 7 days) for `prompt_effectiveness`,
   `error_mode`, or `self_reflection` categories. If found, use the most
   recent one.
2. **Fall back to craft notebook** — read `notes/llm-craft.md` and select
   an entry. Avoid repeating entries from the last 3 standups (check recent
   standup files).
3. **If neither has material**, skip the Prompt Craft section.

Distil whatever source material you find into a concrete, actionable lesson.

### 6. Generate Standup

Use this template. The tone must match the `standup_tone` parameter from SYSTEM.md (default: confrontational). Follow the tone guidelines from CLAUDE.md exactly.

```text
STANDUP — [Day of week], [Date]

---

## Focus Check

Slot 1: [Item Name]
  In focus: [N] days (since [date])
  Deadline: [date] — [STATUS]
  Next action: [from FOCUS.md]
  [Escalation-appropriate commentary — see below]

Slot 2: [Item Name or Empty]
  [Same format, or "Empty — one slot available"]

---

## At Risk

[List anything past deadline or approaching deadline with no recent progress.
If nothing is at risk, omit this section.]

---

## Patterns

[Based on memory system analysis from step 4.
Examples:
- "LLM-History-Paper has been in focus for 8 days. You've made progress on infrastructure work but not on the paper. Are you avoiding it?"
- "You committed to finishing the methods section by Wednesday. It's Friday."
- "Last time you completed something quickly, you were single-threading. You currently have 2 items."

If no relevant patterns found, omit this section.]

---

## Hard Question

[One direct question that needs an honest answer. Tailored to what the data shows.
Examples:
- "What specifically will you do on the paper today? Not 'work on it.' What concrete output?"
- "You have 20 days until the deadline. Is the current pace sufficient, or are you going to run out of time?"
- "What's actually blocking this? Not 'busy.' What specifically?"

Always ask exactly one hard question.]

---

## Inbox ([N] items)

[If empty, show "Empty — nothing to process." and move on.]

[If items exist, list them all with age in days. Then prompt action:]

Pick 2-3 to deal with now (process, delegate, or delete):
  [numbered list of inbox items]

Which of these can you process or delete right now?

[If any item is older than 7 days, flag it:]
⚠ [item] has been sitting here for [N] days. Process it or delete it — the inbox is not a parking lot.

[When the user promotes an inbox item to focus, apply the same **scoping
check** as `/focus add` — see that command for the full protocol. In
brief: push back if the item is too broad (entire project or multi-week
endeavour), too narrow (single action, better as a next-action), or has
ambiguous completion criteria. A well-scoped focus item completes in
roughly 3–10 working days.]

---

## Waiting For ([N] items)

[List items from waiting-for.md that need attention.
Flag any that are overdue for a follow-up.
If none, omit this section.]

---

## Prompt Craft

[One prompt coaching observation. Source material in priority order:

1. Search memories from the last 7 days for categories: `prompt_effectiveness`,
   `error_mode`, `self_reflection`. If any exist, surface the most recent one
   as a reminder and draw a concrete lesson from it.
2. If no recent memories, read `~/personal-assistant/notes/llm-craft.md` and
   pick an entry the user hasn't seen recently (use the standup history to
   avoid repeats).
3. If neither source has material, omit this section.

Format:
  **Lesson:** [One sentence — the actionable takeaway]
  **Source:** [Where this came from — memory ID, craft notebook entry, or observation]
  **Try today:** [One specific thing to do differently in today's prompting]

Keep it to 3-4 lines. This is a daily micro-lesson, not a lecture.]

---

## Today

Given the above, what are you *actually* going to do today?
Not what you hope. What you're committing to.

[If today is Friday, append:]

📋 **Weekly review:** Run /weekly-review before you finish today. No weekly
reviews have been completed yet — building this habit matters.
```

### 7. Escalation Commentary Examples

**Days 1-2 (Neutral):**
```text
LLM-History-Paper: Day 1 in focus. Next action: [X]
```

**Days 3-6 (Curious):**
```text
LLM-History-Paper: Day 5 in focus. What progress did you make yesterday?
Is the next action still "[X]" or has it changed?
```

**Days 7-13 (Confrontational):**
```text
LLM-History-Paper: Day 9 in focus. This paper has a hard deadline in [N] days.

You've spent [N] days on it with [assessment of visible progress].
What's actually happening here? Not "I'm working on it." What specifically
is blocking forward movement?
```

**Day 14+ (Abandon Discussion):**
```text
LLM-History-Paper: Day 16 in focus. We need a different conversation.

Options:
  1. Recommit with a concrete plan — what will be different?
  2. Pause deliberately — set a condition for return
  3. Abandon — be honest about why
  4. Escalate — who can help unblock you?

Carrying it forward unchanged is not an option. Which is it?
```

**Day 14+ with progress exception (Confrontational, capped):**
```text
LLM-History-Paper: Day 22 in focus (confrontational — progress evident, not abandon).
This paper has a hard deadline in [N] days.

[Assessment of recent progress and remaining work.]
What's the plan to close it out?
```

### 8. Save and Display

1. **Save** the standup output to `~/personal-assistant/standups/YYYY-MM-DD.md`
   - If a standup already exists for today, append a separator and the new standup
     (multiple standups per day are fine — they show engagement)
2. **Display** the full standup to the user
3. **After displaying**, ask: "What's the honest answer to the hard question?"
4. Then: "Given that, what's your one concrete commitment for today?"
5. **After receiving commitments**, append them to the standup file under a
   `### Commitments` heading (inside the `## Today` section). This is critical
   — the standup file must be a complete record of what was discussed and
   committed to, because the conversation session may end before `/recap` runs.
   Format:
   ```text
   ### Commitments

   1. [First commitment]
   2. [Second commitment]
   ```

## Notes

- The standup is NOT optional. The whole system depends on facing reality.
- The saved file is identical to the displayed output — no separate formatting
- Pattern detection is best-effort. If the memory system has no relevant data, skip that section
- Never soften the tone. "You haven't touched this in 6 days" not "progress may have slowed"
- Connect escalation to real stakes. "This blocks [consequence]" not just "this is overdue"
- The Hard Question must be specific to the current situation, not generic
- **Slot names are actionable tasks**, not project names. Reference them as-is (e.g., "LLM-History-Paper results write-up"), not by project umbrella. The `Project` field is a grouping tag.
