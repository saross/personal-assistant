# /capture — Quick Inbox Capture

Add something to the inbox without processing. Zero friction.

## Usage

```text
/capture [text]
```

## Arguments

- `[text]` — The item to capture (required). Can be anything: a task, idea, note, reminder.

## Behaviour

1. **Read** `~/personal-assistant/tasks/inbox.md`
2. **Append** a new line at the end of the file in this format:

```text
- [ ] YYYY-MM-DD HH:MM | [text]
```

Use the current date and time (24-hour format). The text should be preserved exactly as the user typed it — do not rephrase, clarify, or process it.

3. **Confirm** the capture with a brief acknowledgement:

```text
Captured to inbox:
  "[text]"
```

4. **Return to work.** No further commentary, no questions, no suggestions. The whole point is zero friction.

## Examples

```text
/capture email from Sarah about new ethics template
/capture idea: could we use DuckDB for GPS analysis instead of pandas?
/capture schedule dentist appointment
/capture check if fieldmark-docs CI is passing
```

## Notes

- Do NOT ask clarifying questions — that happens during inbox processing (standup or manual)
- Do NOT suggest a project, category, or priority — that is processing, not capturing
- Do NOT offer to do the captured item right now
- The inbox is processed daily during `/standup` — items will not be forgotten
- If the user provides no text after `/capture`, ask them what they want to capture
