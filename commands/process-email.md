# /process-email — Email Triage

Classify incoming email into actions, waiting-for items, and reference.
Routes actionable items into the task system.

## Usage

```text
/process-email
/process-email [pasted email text]
```

## Arguments

- *(no arguments)* — Fetch recent unread emails via Gmail MCP server (if configured)
- `[pasted text]` — Classify pasted email content manually (fallback mode)

## Prerequisites: Gmail MCP Server

This command works best with a Gmail MCP server configured in Claude Code.
Without it, the command falls back to manual paste mode.

### Setup (one-time)

**Step 1: Select and install a Gmail MCP server.**

Evaluate available options. Criteria:
- Read access to messages (list, read) — write access optional
- OAuth 2.0 authentication with Gmail
- Minimal auth complexity

**Step 2: Set up Google Cloud OAuth credentials.**

1. Create a Google Cloud project (or use existing)
2. Enable the Gmail API
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download the credentials JSON
5. Store credentials securely (not in the repo)

**Step 3: Configure in Claude Code.**

Add MCP server to `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "[path to server]",
      "args": ["--credentials", "[path to credentials]"]
    }
  }
}
```

**Step 4: Test.**

Verify Gmail MCP tools appear in Claude Code. Test listing and reading messages.

## Behaviour

### Mode Detection

1. **If Gmail MCP tools are available** (check for tools like `gmail_list_messages`,
   `gmail_read_message`, or similar): use MCP mode
2. **If text is pasted after the command**: use manual mode
3. **If neither**: prompt the user:

```text
Gmail MCP is not configured. Options:
  (a) Paste email text here for manual triage
  (b) Set up Gmail MCP — see commands/process-email.md for instructions
```

### MCP Mode

1. **Fetch** recent unread emails:
   - Default: last 24 hours, or since last triage (track in a state file)
   - Use Gmail MCP tools to list unread messages
   - Read the subject, sender, and body of each message
   - State file: `~/personal-assistant/.last-email-triage` (contains ISO timestamp)

2. **Classify** each email into categories (see Classification below)

3. **Present** the classification to the user (see Display below)

4. **Apply** after user approval

### Manual Mode

1. **Accept** pasted email text (subject, sender, body — whatever the user provides)
2. **Classify** the pasted content
3. **Present** and **apply** as in MCP mode

### Classification

For each email, classify into one of:

| Category | Criteria | Destination |
|----------|----------|-------------|
| **ACTION** | Requires a response, task, or decision from the user | `tasks/inbox.md` |
| **WAITING** | User is waiting for someone else to act; this email confirms it's in progress | `tasks/waiting-for.md` |
| **REFERENCE** | Useful information to remember but no action needed | Offer `/remember` |
| **SKIP** | Newsletters, notifications, spam, marketing — no value | Discard silently |
| **UNCLEAR** | Cannot confidently classify | Present to user for manual decision |

**Classification heuristics:**
- Direct questions or requests addressed to the user → ACTION
- Replies to something the user sent, saying "I'll get back to you" → WAITING
- Conference CFPs, funding announcements, relevant news → REFERENCE
- Automated notifications, marketing, newsletters → SKIP
- CC'd on a thread with no clear ask → REFERENCE or SKIP based on relevance

### Display

Present the classification for approval:

```text
Email triage ([N] messages):

  ACTION ([N]):
    - "[Subject]" from [Sender] → inbox: "[task description]"
    - "[Subject]" from [Sender] → inbox: "[task description]"

  WAITING ([N]):
    - "[Subject]" from [Sender] → waiting-for: "[description]" (waiting on: [who])

  REFERENCE ([N]):
    - "[Subject]" from [Sender] — worth remembering? [y/n]

  UNCLEAR ([N]):
    - "[Subject]" from [Sender] — how to classify? [action/waiting/reference/skip]

  SKIPPED ([N]):
    - [Brief list: "N newsletters, M notifications, K marketing"]

Approve? [y to apply, e to edit, n to cancel]
```

### Apply

On approval:

**ACTION items:** Append to `~/personal-assistant/tasks/inbox.md`:

```text
- [ ] YYYY-MM-DD HH:MM | [task description] (from email: [sender])
```

**WAITING items:** Append to `~/personal-assistant/tasks/waiting-for.md`.
If the file has a table format, add a row. If free-form, append a list item:

```text
| [Description] | [Who] | YYYY-MM-DD | [context] |
```

**REFERENCE items** (where user said yes): Route to `/remember` with
`category:context` and appropriate tags.

**UNCLEAR items:** Apply the user's manual classification.

**Update triage timestamp:** Write current ISO timestamp to
`~/personal-assistant/.last-email-triage`.

### Report

After applying:

```text
Email triage complete:
  [N] items added to inbox
  [N] items added to waiting-for
  [N] items remembered
  [N] items skipped
  Next triage will start from [timestamp]
```

## Notes

- The Gmail MCP setup is a separate infrastructure step — it's not part of this
  command's implementation. The command should work in manual mode without it.
- Task descriptions derived from emails should be actionable:
  "Respond to Sarah's Fieldmark feedback" not "Email from Sarah about Fieldmark."
- For WAITING items, always note WHO you're waiting on — it's essential for follow-up.
- Don't over-classify. When in doubt, mark as UNCLEAR and let the user decide.
- Respect email privacy — don't store full email bodies. Store only the derived
  task description and enough context to act on it.
- The `.last-email-triage` file should be gitignored (it's machine-specific state).
- If manual mode receives a forwarded email dump (multiple emails pasted), split
  them and classify each separately.
