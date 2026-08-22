# Slack dashboard — a two-week trial

**Built 2026-08-22.** Publishes the task-accountability state to a Slack canvas,
because the GitHub Projects board that was supposed to do this job drifted into
contradicting reality and Shawn does not live in GitHub.

**Canvas:** <https://fedarch.slack.com/docs/T0X423C67/F0BRV9LUBRT> (id
`F0BRV9LUBRT`, workspace `T0X423C67`)

## The diagnosis this replaced

`commands/sync-board.md` renders `data/tasks/*.md` to a GitHub Projects board
and declares markdown canonical, one-way. Its documented trigger is **"Manual
only — no automatic sync."** By 2026-08-22 the board's Focus column named
*"Marketing / outreach strategy session"* and *"EFN — BolgiaTen arc"*, whilst
`FOCUS.md` and every session banner said **EFN website content, Move, RDA**. It
also showed 1 waiting-for item against the real 46.

**Two independent failures, and automation only fixes one.** The board was
*wrong* because its refresh was manual; it was *unvisited* because Shawn works
through `gh`, git, and Claude rather than project boards. Fixing the sync would
have produced a correct board he still would not open. Slack answers attention;
regeneration answers correctness. Both were needed, which is why "just automate
`/sync-board`" was rejected.

The same lesson is already in `FOCUS.md`, dated 2026-08-20, about a heading that
was stale for three days: *"A prescriptive file that is not updated on the day
of a rotation lies to every session that starts afterwards."*

## Shape

- **No new store.** `data/tasks/*.md` stays canonical. The canvas holds nothing
  that is not re-derived on every run, so it cannot drift independently.
- **One generator, two renderers.** `hooks/session-start-accountability.py`
  gained `build_banner()` and `all_task_files_missing()`;
  `scripts/publish-dashboard.py` reuses its parsers rather than reimplementing
  them, so the two surfaces cannot disagree about what the same files say.
- **Provenance in the artefact.** The footer carries render time and the `data`
  submodule commit, with `+dirty` when the working tree has uncommitted task
  edits — routine here, with several sessions running at once. **A stale canvas
  is detectable by reading it**, which is exactly what the GitHub board lacked.

## Self-checks — the reason it is not just a mirror

The canvas reports two defects the session banner structurally cannot show.

**Duplicate slot numbers.** Retired slot sections take a `## (record) Slot N:`
prefix. `## Slot 1: ✅ CLOSED — ARDC application SUBMITTED 2026-08-13` never got
one, so **for nine days every session banner announced a closed item as current
Slot 1**. Fixed in `FOCUS.md` on 2026-08-22; the check stops it recurring
silently.

**Deadlines stated in prose.** The banner escalates from `**Deadline:**
YYYY-MM-DD` only. **All three current slots write their deadline as prose**
(Slot 1: *"~26 Aug commitment to Steve and Penny; contracted mid-Sept"*), so the
countdown and overdue machinery has never fired for any of them. Not
auto-fixed — Slot 1 names two candidate dates and choosing between them is
Shawn's call, not a mechanical repair.

## To make it unattended — one setup step

Rendering needs no credentials and works today. **Publishing needs a Slack bot
token, which does not exist yet.** Create a Slack app with the `canvases:write`
scope, install it, then add to `.env` (both machines — Slack credentials are
shared, see `env-cross-machine-reference.md`):

```bash
SLACK_BOT_TOKEN=xoxb-…
SLACK_DASHBOARD_CANVAS_ID=F0BRV9LUBRT
```

Then wire `scripts/publish-dashboard.py --publish` into the once-per-day
`scripts/daily-sync-trigger.sh`, which is the established automation point here
— that wrapper deliberately replaced cron in order to inherit the interactive
SSH agent and avoid cron-environment auth problems.

Until the token exists, Claude can refresh the canvas in-session via the Slack
MCP tools. **That is a stopgap, not the design**: a refresh that depends on
someone remembering is the failure this replaced.

## Usage

```bash
scripts/publish-dashboard.py                  # canvas markdown to stdout
scripts/publish-dashboard.py --format plain   # the session banner, for a DM
scripts/publish-dashboard.py --out dash.md
```

`--format plain` exists for the other half of the original problem: carrying
handoff prompts between machines. A resume prompt is a moment-in-time
instruction, not a current-state view, so it belongs in a message (Slack renders
fenced code blocks with a copy button) rather than in this canvas. Keeping them
separate stops the dashboard growing into a log.

## Why canvas and not Slack Lists

Lists is the better-looking surface — real structured CRUD via twelve
`slackLists.*` methods, available on Pro. **But the official Slack MCP server
ships no Lists tools**, so Claude cannot maintain a List; it would need a
bespoke bot-token integration. Canvas is where the API and the agent tooling
actually meet.

## Cost, measured not assumed

The design intent was one `replace` call against one body section. **The live
API falsified that**: Slack splits a canvas into one section per markdown block,
so this dashboard arrives already split into eight, and `canvases.edit` accepts
one operation per call. The refresh is therefore *delete every section but the
title, then append the new body* — `n+1` calls, which converges regardless of
how many sections the previous render produced (a warning callout adds one).
Against a Tier 3 limit of 50/min that is ample daily and wrong for anything
live. `canvas_editing_locked` is retried; it means a human has the document
open.

## Kill criterion

**Two weeks from 2026-08-22.** If Shawn has not opened the canvas unprompted
during the second week, delete it and stop trying to solve this with surfaces.
Retire or archive the GitHub board once the canvas is established — leaving a
contradicting view in place is the one option with no upside.
