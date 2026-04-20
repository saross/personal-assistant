# /sync-board — GitHub Projects Board Sync

Push task state from markdown to a GitHub Projects kanban board.
Markdown is canonical; the board provides visual overview and external visibility.

## Usage

```text
/sync-board
/sync-board --dry-run
/sync-board --setup
```

## Arguments

- *(no arguments)* — Preview the sync plan, then execute after approval
- `--dry-run` — Preview only, don't execute
- `--setup` — Run first-time setup (create project, labels, columns)

## Design

- **Repository:** `personal-assistant` (this repo — task state lives here)
- **Direction:** One-way: markdown → GitHub (markdown is canonical)
- **Trigger:** Manual only — no automatic sync
- **Matching:** Issues are matched to tasks by title (case-insensitive, trimmed)
- **Board:** GitHub Projects v2 with board view and Status field

### What goes on the board

The board shows **concrete tasks** (things to do), not projects or commitments.
FOCUS.md tracks which projects are active; the board tracks the actual work within
those projects.

| Source | What becomes a card |
|--------|-------------------|
| `tasks/FOCUS.md` "This week" bullets | Individual tasks within each focus project |
| `tasks/FOCUS.md` "Next action" field | The immediate next task (if not covered by "This week") |
| `tasks/FOCUS.md` Paused table | Paused tasks |
| `tasks/backlog.md` entries | Scoped future work |
| `tasks/inbox.md` unchecked items | Unprocessed captures |
| `tasks/waiting-for.md` items | Blocked items |
| `tasks/done/YYYY-MM.md` rows | Recently completed (for closing open Issues) |

Tasks are tagged with their **specific project**, not a broad category.

### Board Columns (Status field values)

| Column | Meaning |
|--------|---------|
| **Backlog** | Scoped work, waiting for trigger |
| **Inbox** | Captured, not yet processed |
| **Focus** | Actively working on |
| **Paused** | Deliberately set aside |
| **Waiting For** | Blocked on others |
| **Done** | Completed |

### Labels

Labels identify the specific project a task belongs to. Created on the fly as
new projects appear — no predefined set.

Examples of project labels:

| Label | Colour | Used for |
|-------|--------|----------|
| `llm-history-paper` | `#1D76DB` (blue) | Research paper with Brian |
| `fieldmark-docs-staging` | `#D93F0B` (red) | EFN user-facing documentation |
| `anu-teaching-prep` | `#5319E7` (purple) | ANU digital humanities teaching |
| `flinders-admin-onboarding` | `#0E8A16` (green) | Flinders admin onboarding materials |
| `efn-legal` | `#D93F0B` (red) | EFN legal/contracts work |
| `llm-map-reader` | `#1D76DB` (blue) | Map reader LLM research |
| `llm-reproducibility` | `#1D76DB` (blue) | LLM reproducibility research |

**Colour convention:** Blue for research, red for business/EFN, purple for teaching,
green for other. But these are guidelines, not rules — readability matters more.

**Label naming:** Derive from the project name in FOCUS.md or backlog.md. Use
lowercase with hyphens. If a task doesn't clearly belong to a project, omit the label.

Deadline labels: If a task has a specific deadline, add `deadline:YYYY-MM-DD`.

Status is conveyed by the board column, not by labels.

## Behaviour

### 0. First-Time Setup (`--setup`)

Run once to create the project and initial labels. Idempotent — safe to re-run.

**Create initial project labels** (from current FOCUS.md projects, if missing):

```bash
gh label create "llm-history-paper" --color "1D76DB" --description "LLM history paper research"
gh label create "fieldmark-docs-staging" --color "D93F0B" --description "EFN user-facing documentation"
gh label create "anu-teaching-prep" --color "5319E7" --description "ANU digital humanities teaching"
```

On subsequent syncs, create new labels automatically as new projects appear.

**Create GitHub Project:**

```bash
gh project create --owner "@me" --title "Task Board"
```

Note the project number returned (e.g., `1`).

**Find the Status field ID:**

```bash
gh project field-list [PROJECT_NUMBER] --owner "@me" --format json
```

Look for the `Status` field (single select type — it's created by default).

**Add column values to the Status field.** The default Status field has "Todo",
"In Progress", "Done". We need to replace these with our GTD columns:

Use the GitHub web UI or GraphQL to set the Status field options to:
`Backlog`, `Inbox`, `Focus`, `Paused`, `Waiting For`, `Done`.

If the web UI is easier, instruct the user:

```text
First-time setup:
  1. Project "Task Board" created (#N)
  2. Labels created
  3. ACTION NEEDED: Open the project at [URL] and edit the Status field:
     - Rename "Todo" → "Inbox"
     - Rename "In Progress" → "Focus"
     - Keep "Done"
     - Add: "Backlog", "Paused", "Waiting For"
     - Reorder: Backlog | Inbox | Focus | Paused | Waiting For | Done

Then run /sync-board again to populate the board.
```

**Store project number** in `~/personal-assistant/.sync-board-config`:

```text
project_number=N
```

This file is gitignored (machine-specific).

### 1. Read Current State

**From markdown — extract concrete tasks from all sources:**

**FOCUS.md — extract tasks, not project headings:**

For each filled slot in FOCUS.md:
- Read the "This week" numbered bullets — each becomes a separate task card
- If no "This week" section, use the "Next action" field as a single task
- Tag each task with the project name (derived from the slot's `Project:` field)
- Include deadlines where specified in the bullet or inherited from the slot

Example: Slot 1 "LLM-History-Paper" with bullets:
1. "Results section write-up" → card tagged `llm-history-paper`, deadline 13 Feb
2. "Consolidate discussion drafts" → card tagged `llm-history-paper`

**Other sources:**

| Source | Status | How to parse |
|--------|--------|-------------|
| `tasks/FOCUS.md` "This week" / "Next action" | Focus | As above — individual tasks |
| `tasks/FOCUS.md` Paused table | Paused | Table rows — each is a task |
| `tasks/backlog.md` | Backlog | `## [Item Name]` sections — each is a task |
| `tasks/inbox.md` | Inbox | Unchecked `- [ ]` lines |
| `tasks/waiting-for.md` | Waiting For | Table rows or list items |
| `tasks/done/YYYY-MM.md` | Done | Table rows (check current + previous month) |

For each task, extract:
- **Title** (concise, actionable — "Write results section" not "LLM-History-Paper")
- **Status** (which column it belongs in)
- **Project label** (from the parent project)
- **Deadline** (if present)
- **Body text** (enough context for the Issue body)

**From GitHub:**

```bash
gh issue list --state all --json number,title,state,labels --limit 200
```

Also read project items to get current board positions:

```bash
gh project item-list [PROJECT_NUMBER] --owner "@me" --format json
```

### 2. Calculate Diff

Compare markdown state to GitHub Issues:

| Condition | Action |
|-----------|--------|
| Markdown task with no matching Issue | **Create** Issue + add to board in correct column |
| Completed task with matching open Issue | **Close** Issue + move to Done column |
| Task's board column doesn't match markdown status | **Move** to correct column |
| Task's labels don't match | **Update** labels |
| Open Issue with no matching markdown task | **Flag** for user review |
| Closed Issue matching an active markdown task | **Reopen** + move to correct column |

**Matching rules:**
- Match by title (case-insensitive, trimmed)
- If ambiguous (multiple matches), flag for user review rather than guessing

**Critical: issue-number + repository collision.** The board can contain
project items from multiple repos — for example `saross/personal-assistant`
(active) and `saross/personal-assistant-archive` (archived single-repo
history). Issue numbers are scoped *per repo*, so two items can share the
same number (e.g. both repos have an issue #1).

When locating a project item by issue number, **always filter by
`.content.repository` as well**. Use a `(repo, number)` tuple, never
number alone:

```bash
# CORRECT — scoped to the active repo
jq -r --arg repo "saross/personal-assistant" --argjson n "$issue_num" \
  '.items[] | select(.content.repository == $repo and .content.number == $n) | .id' \
  /tmp/gh-project-items.json

# WRONG — will match archive-repo items first and silently operate on the
# wrong card
jq -r --argjson n "$issue_num" \
  '.items[] | select(.content.number == $n) | .id' \
  /tmp/gh-project-items.json
```

`gh issue close N` always scopes to the *current* repo, so the close
action itself is unambiguous. The risk is that a subsequent
`move_project_item` call (driven by a number-only lookup) silently targets
a different repo's card. Anchoring both calls to the same
`(repo, number)` tuple prevents divergence.

**New project labels:** If a task references a project that doesn't have a label yet,
create the label automatically before creating the Issue.

### 3. Preview Sync Plan

Display the plan before executing:

```text
## Sync Plan

Project: Task Board (#N)

New labels (N):
  "anu-teaching-prep" (#5319E7)

Create + add to board (N):
  "Write results section" → Focus [llm-history-paper, deadline:2026-02-13]
  "Consolidate discussion drafts" → Focus [llm-history-paper]
  "Review pipeline output" → Focus [fieldmark-docs-staging]
  "Check Canvas access" → Focus [anu-teaching-prep]
  "Populate 3 assessments" → Focus [anu-teaching-prep]
  "Flinders Admin Onboarding" → Backlog [fieldmark-docs-staging]

Close (N):
  #12 "Setup PostgreSQL" → Done (completed 2026-02-08)

Move (N):
  #8 "Some task" — Inbox → Focus

Update labels (N):
  #3 — +anu-teaching-prep

Reopen (N):
  #15 "Some task" → Focus

Unknown (N):
  #5 "Old task" — not in any markdown file. Close? [y/n per item]

Already synced (N):
  [Items with no changes needed]
```

If `--dry-run`, stop here.

### 4. Execute (after approval)

Ask: "Execute this sync plan? [y/n]"

If approved, for each action:

**Create new labels (if needed):**

```bash
gh label create "[project-name]" --color "[colour]" --description "[description]"
```

**Create Issue + add to board:**

```bash
# Create the Issue
gh issue create --title "[title]" --label "[project-label]" --body "[body]"

# Add to project board
gh project item-add [PROJECT_NUMBER] --owner "@me" --url [issue-url]

# Set the Status field to the correct column
gh project item-edit --project-id [PROJECT_ID] --id [ITEM_ID] --field-id [STATUS_FIELD_ID] --single-select-option-id [COLUMN_OPTION_ID]
```

**Issue body templates:**

Focus tasks:

```text
**Project:** [project name]
**Deadline:** [date or None]
**Context:** [from FOCUS.md — why this matters or what it's part of]

---
Synced from FOCUS.md by /sync-board on [date].
```

Backlog tasks:

```text
**Project:** [project name]
**Effort:** [estimate]
**Trigger:** [what activates this]

---
Synced from backlog.md by /sync-board on [date].
```

Inbox items:

```text
Captured: [date from inbox entry]

---
Synced from inbox.md by /sync-board on [date].
```

Waiting-for items:

```text
**Waiting on:** [who]
**Since:** [date]

---
Synced from waiting-for.md by /sync-board on [date].
```

**Close:**

```bash
gh issue close [number] --comment "Completed [date]. Archived to tasks/done/."
```

**Move (change board column):**

Resolve `[ITEM_ID]` using the `(repo, number)` tuple (see matching rules
above). Never look up project items by issue number alone.

```bash
gh project item-edit --project-id [PROJECT_ID] --id [ITEM_ID] --field-id [STATUS_FIELD_ID] --single-select-option-id [COLUMN_OPTION_ID]
```

**Update labels:**

```bash
gh issue edit [number] --add-label "[labels]" --remove-label "[labels]"
```

**Reopen:**

```bash
gh issue reopen [number] --comment "Returned to active tracking on [date]."
```

**Unknown items:** Ask the user per item. If close:

```bash
gh issue close [number] --comment "No longer tracked. Closed by /sync-board."
```

### 5. Report

After execution, display a summary:

```text
Sync complete:
  Labels created: N
  Issues created: N (added to board)
  Issues closed: N (moved to Done)
  Issues moved: N (column updated)
  Labels updated: N
  Issues reopened: N
  Skipped: N (user declined)

Board: [project URL]
```

### 6. Caching IDs

The `gh project item-edit` command requires project ID, field ID, and option IDs
(not human-readable names). On each run:

1. Fetch project metadata: `gh project field-list [NUMBER] --owner "@me" --format json`
2. Parse out the Status field ID and each option's ID (Backlog, Inbox, Focus, etc.)
3. Cache in memory for the duration of the sync — no need to persist between runs

If the project or field is missing, tell the user to run `--setup` first.

## Notes

- Markdown is always canonical. If there's a conflict, markdown wins.
- The board is a view into the system, not a separate source of truth.
- Board shows concrete tasks, not project headings. "Write results section" not
  "LLM-History-Paper."
- Project labels are created on the fly — no need to predefine them all.
- Don't create Issues for already-completed items — only sync current state.
- The `--dry-run` flag is useful for seeing what would change without committing.
- If `gh` CLI is not authenticated, tell the user to run `gh auth login` first.
- The `.sync-board-config` file should be gitignored (machine-specific state).
- This command does NOT read from GitHub back into markdown. One-way only.
- Status field column renaming may need to be done via the web UI on first setup —
  the `gh` CLI's project field editing is limited for single-select option management.
- Rate limiting: `gh` CLI handles rate limits internally. Avoid creating more than
  20 Issues in a single sync (unlikely but guard against it).
