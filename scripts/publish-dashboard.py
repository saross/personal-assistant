#!/usr/bin/env python3
"""
Render the task-accountability dashboard for surfaces outside a Claude session.

Why this exists
---------------
``hooks/session-start-accountability.py`` has been a working dashboard
generator for months: it parses ``FOCUS.md``, ``inbox.md``, and
``waiting-for.md``, and renders the banner shown at session start. Its only
limitation is where that output lands — inside a Claude Code session, and
nowhere else.

The prior attempt at a second surface was ``/sync-board`` rendering to a GitHub
Projects board. Its documented trigger is *"Manual only — no automatic sync"*,
and by 2026-08-22 the board's Focus column still named work that had rotated out
weeks earlier, contradicting ``FOCUS.md``. **A derived view whose refresh
depends on someone remembering will drift, and a drifted view is worse than no
view** because it is confidently wrong. FOCUS.md records the same lesson at a
shorter timescale on 2026-08-20: *"A prescriptive file that is not updated on
the day of a rotation lies to every session that starts afterwards."*

So this script adds no new store and no new state. It re-renders, from the same
canonical markdown, every time it runs. There is nothing here that can fall out
of date independently of ``data/tasks/``.

Surfaces
--------
``--format canvas``
    Canvas-flavoured Markdown for a Slack canvas. The body is regenerated
    wholesale rather than patched, because every value is derived and none is
    user-entered, so there is nothing in the document worth preserving across a
    refresh. See :func:`build_edit_plan` for why that still costs several API
    calls: Slack splits a canvas into one section per markdown block, and
    ``canvases.edit`` accepts one operation per call.

``--format plain``
    The exact session-start banner text, for a Slack message or a terminal.

Publishing
----------
``--publish`` requires ``SLACK_BOT_TOKEN`` (scope ``canvases:write``) and a
canvas id. Without a token the script still renders, so the content is usable
and testable today and the network path is the only part waiting on setup.

Usage
-----
    scripts/publish-dashboard.py                      # canvas markdown to stdout
    scripts/publish-dashboard.py --format plain       # session banner text
    scripts/publish-dashboard.py --out /tmp/dash.md
    scripts/publish-dashboard.py --publish --canvas-id F123 --section-id abc
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path.home() / "personal-assistant"
sys.path.insert(0, str(PA_DIR / "hooks"))

# The hook's filename is hyphenated, so it cannot be imported normally.
accountability = importlib.import_module("session-start-accountability")

SLACK_API = "https://slack.com/api"
DATA_DIR = PA_DIR / "data"


# ============================================================================
# Provenance
# ============================================================================


def data_revision() -> str:
    """Describe the commit the dashboard's content was rendered from.

    The content derives entirely from ``data/tasks/*.md``, so the *data
    submodule's* HEAD is the honest anchor, not the parent repository's.

    A dirty working tree is reported explicitly. That matters more here than
    usual: this repository routinely has several Claude sessions running at
    once, and a dashboard rendered from uncommitted edits corresponds to no
    commit anyone can retrieve later. Saying so is cheaper than the confusion
    of an unreproducible snapshot.

    Returns:
        A short description such as ``"96140df"``, ``"96140df+dirty"``, or
        ``"unknown"`` when git cannot answer.
    """
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(DATA_DIR), *args],
                capture_output=True, text=True, timeout=10, check=False,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    sha = git("rev-parse", "--short", "HEAD")
    if not sha:
        return "unknown"
    dirty = git("status", "--porcelain", "--", "tasks")
    return f"{sha}+dirty" if dirty else sha


# ============================================================================
# Model
# ============================================================================


def collect() -> dict:
    """Gather dashboard state via the hook's parsers.

    Reuses ``parse_focus_slots``, the counters, and the formatting helpers
    rather than reimplementing them, so this surface cannot disagree with the
    session banner about what the same files say.

    Returns:
        A dict with ``slots``, ``inbox``, ``waiting``, ``focus_limit``, and
        ``anomalies``.

    Raises:
        accountability.TaskFilesMissing: none of the source files exist.
    """
    if accountability.all_task_files_missing():
        raise accountability.TaskFilesMissing(
            "FOCUS.md, inbox.md, and waiting-for.md not found under "
            f"{PA_DIR / 'data' / 'tasks'} (is the data/ submodule pulled?)"
        )

    slots = accountability.parse_focus_slots()
    anomalies: list[str] = []

    # Self-check: a slot number appearing twice means a retired section in
    # FOCUS.md was never given the `(record)` prefix that marks it historical.
    # That happened to Slot 1 for nine days after the ARDC application closed
    # on 2026-08-13, and every session banner in that window announced a closed
    # item as current work. Surface it rather than rendering both rows, so the
    # dashboard reports the defect instead of propagating it.
    seen: dict[int, int] = {}
    for slot in slots:
        seen[slot["slot_number"]] = seen.get(slot["slot_number"], 0) + 1
    for number, count in sorted(seen.items()):
        if count > 1:
            anomalies.append(
                f"Slot {number} appears {count} times in FOCUS.md — a retired "
                f"section is probably missing its `(record)` prefix."
            )

    anomalies.extend(unreadable_deadlines(slots))

    return {
        "slots": slots,
        "inbox": accountability.count_inbox_items(),
        "waiting": accountability.count_waiting_items(),
        "focus_limit": accountability.get_focus_limit(),
        "anomalies": anomalies,
    }


def unreadable_deadlines(slots: list[dict]) -> list[str]:
    """Flag slots that state a deadline in prose the parser cannot read.

    The banner escalates on deadlines ("deadline in 4 days", "OVERDUE by 3
    days"), but only from the machine-readable form ``**Deadline:**
    YYYY-MM-DD``. A slot whose deadline reads ``**Deadline:** ~26 Aug
    commitment to Steve and Penny`` parses to ``None``, and the escalation is
    then **silently inert** — indistinguishable, from the banner, from a slot
    that genuinely has no deadline.

    That is the failure this dashboard exists to prevent, so it is reported
    rather than tolerated. Deliberately narrow: it fires only where a deadline
    is *stated but unreadable*, never where none is set, because plenty of work
    legitimately has no date.

    Args:
        slots: Parsed slots from ``parse_focus_slots``.

    Returns:
        One message per affected slot. Empty when all deadlines are readable.
    """
    focus_file = accountability.FOCUS_FILE
    if not focus_file.exists():
        return []

    import re

    content = focus_file.read_text(encoding="utf-8", errors="replace")
    # Active slot sections only — `(record)` sections are history by convention.
    blocks = re.split(r"^## (?=Slot \d+:)", content, flags=re.MULTILINE)

    messages: list[str] = []
    stated = {s["slot_number"] for s in slots if s.get("deadline")}
    for block in blocks[1:]:
        header = re.match(r"Slot (\d+):", block)
        if not header:
            continue
        number = int(header.group(1))
        if number in stated:
            continue
        if re.search(r"\*\*Deadline:\*\*", block) and not re.search(
            r"\*\*Deadline:\*\*\s*\d{4}-\d{2}-\d{2}", block
        ):
            messages.append(
                f"Slot {number} states a deadline in prose, so no countdown or "
                f"overdue warning can fire for it. Add `**Deadline:** "
                f"YYYY-MM-DD` to enable escalation."
            )
    return messages


# ============================================================================
# Rendering
# ============================================================================


def render_canvas(state: dict, *, now: datetime, revision: str) -> str:
    """Render the dashboard as Canvas-flavoured Markdown.

    Canvas supports only ATX headings, forbids headings inside list items, and
    does not accept Block Kit. Tables and callouts are supported at top level,
    which is all this layout needs.

    Args:
        state: Output of :func:`collect`.
        now: Render time, passed in so output is deterministic under test.
        revision: Provenance string from :func:`data_revision`.

    Returns:
        Canvas markdown, without a title (the canvas carries its own).
    """
    out: list[str] = ["## Focus", ""]

    if not state["slots"]:
        out.append("No items in focus. Run `/standup` or `/focus add`.")
    else:
        out.append("| Slot | Work | Day | Deadline |")
        out.append("|---|---|---|---|")
        by_number = {s["slot_number"]: s for s in state["slots"]}
        for number in range(1, state["focus_limit"] + 1):
            slot = by_number.get(number)
            if slot is None:
                out.append(f"| {number} | _empty_ |  |  |")
                continue
            days = accountability.days_in_focus(slot["started"])
            day_cell = f"day {days}" if days is not None else ""
            deadline = accountability.format_deadline_status(slot["deadline"])
            # Escape pipes so a title containing one cannot break the table.
            work = slot["name"].replace("|", "\\|")
            out.append(f"| {number} | {work} | {day_cell} | {deadline} |")

    out += ["", "## Queues", "",
            f"- Inbox: **{state['inbox']}** items",
            f"- Waiting for: **{state['waiting']}** items"]

    if state["anomalies"]:
        out += ["", "::: {.callout}", "**FOCUS.md needs attention**", ""]
        out += [f"- {a}" for a in state["anomalies"]]
        out.append(":::")

    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    out += ["", "---", "",
            f"_Generated {stamp} from `data/tasks/` at `{revision}`. "
            f"Regenerated in full on every run — if this footer is old, the "
            f"publisher stopped running; the contents are never edited by hand._"]

    return "\n".join(out)


def render_plain(state: dict, *, now: datetime, revision: str) -> str:
    """Render the exact session-start banner, plus a provenance footer.

    Used for a Slack message rather than a canvas. Calls the hook's own
    ``build_banner`` so the text cannot drift from what a session shows.
    """
    lines = accountability.build_banner()
    if state["anomalies"]:
        lines += [""] + [f"WARN: {a}" for a in state["anomalies"]]
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")
    lines += ["", f"generated {stamp} from data/tasks/ at {revision}"]
    return "\n".join(lines)


# ============================================================================
# Publishing
# ============================================================================


def build_edit_plan(
    canvas_id: str, markdown: str, existing_section_ids: list[str],
) -> list[dict]:
    """Build the ordered ``canvases.edit`` payloads for a full-body refresh.

    **Why this is a plan rather than a single call.** The design intent was one
    ``replace`` against one body section. Testing against the live API on
    2026-08-22 falsified that: Slack **splits a canvas into one section per
    markdown block** on creation — a heading, a table, and a list each become
    their own section — so a canvas of this shape arrives already split into
    eight. There is no way to keep the body as a single addressable section,
    and ``canvases.edit`` accepts only one operation per call.

    So the refresh is: delete every section except the title, then append the
    freshly rendered body. That converges no matter how many sections the
    previous render produced, which matters because the count changes with the
    content — an added warning callout is an extra section.

    Cost is ``len(existing_section_ids)`` calls, against a Tier 3 limit of
    50/min. Ample for a dashboard refreshed hourly or daily; the wrong shape
    for anything live.

    Args:
        canvas_id: Target canvas.
        markdown: Freshly rendered body.
        existing_section_ids: Sections from ``slack_read_canvas``, **title
            first**. The title is preserved and everything after it replaced.

    Returns:
        Payloads to POST in order.
    """
    plan: list[dict] = []
    for section_id in existing_section_ids[1:]:
        plan.append({
            "canvas_id": canvas_id,
            "changes": [{"operation": "delete", "section_id": section_id}],
        })
    plan.append({
        "canvas_id": canvas_id,
        "changes": [{
            "operation": "insert_at_end",
            "document_content": {"type": "markdown", "markdown": markdown},
        }],
    })
    return plan


def _post(payload: dict, token: str) -> dict:
    """POST one ``canvases.edit`` payload. Raises on a Slack-level failure."""
    req = urllib.request.Request(
        f"{SLACK_API}/canvases.edit",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    if not body.get("ok"):
        error = body.get("error", "unknown")
        hint = {
            "canvas_editing_locked": " (another editor holds the lock)",
            "canvas_too_large": " (body exceeds the 1 MiB per-change limit)",
            "section_not_found": " (section ids go stale after every edit —"
                                 " re-read the canvas before planning)",
        }.get(error, "")
        raise RuntimeError(f"canvases.edit failed: {error}{hint}")
    return body


def publish(plan: list[dict], token: str, *, sleep=None) -> int:
    """Execute an edit plan in order, retrying the concurrency lock.

    ``canvas_editing_locked`` is transient by definition — it means a human has
    the document open — so it is retried rather than treated as failure. Every
    other error is raised immediately: a partial refresh is visibly broken,
    which is preferable to a silent one.

    Args:
        plan: From :func:`build_edit_plan`.
        token: Slack bot token with ``canvases:write``.
        sleep: Injectable sleep, for tests.

    Returns:
        Number of operations applied.
    """
    import time
    sleep = sleep or time.sleep

    applied = 0
    for payload in plan:
        for attempt in range(3):
            try:
                _post(payload, token)
                applied += 1
                break
            except RuntimeError as exc:
                if "canvas_editing_locked" in str(exc) and attempt < 2:
                    sleep(2 ** attempt)
                    continue
                raise
    return applied


# ============================================================================
# Entry point
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--format", choices=("canvas", "plain"),
                        default="canvas", help="output flavour (default: canvas)")
    parser.add_argument("--out", type=Path, help="write to this path instead of stdout")
    parser.add_argument("--publish", action="store_true",
                        help="POST to Slack (needs SLACK_BOT_TOKEN)")
    parser.add_argument("--canvas-id", default=os.environ.get("SLACK_DASHBOARD_CANVAS_ID"))
    parser.add_argument("--section-id", default=os.environ.get("SLACK_DASHBOARD_SECTION_ID"))
    args = parser.parse_args()

    try:
        state = collect()
    except accountability.TaskFilesMissing as exc:
        # Refuse to render rather than publish a confidently empty dashboard.
        # An empty board and an unreadable one look identical to a reader, and
        # only one of them means "nothing to do".
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    revision = data_revision()
    renderer = render_canvas if args.format == "canvas" else render_plain
    body = renderer(state, now=now, revision=revision)

    if args.out:
        args.out.write_text(body + "\n", encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(body)

    for anomaly in state["anomalies"]:
        print(f"WARN: {anomaly}", file=sys.stderr)

    if args.publish:
        token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
        missing = [n for n, v in (("SLACK_BOT_TOKEN", token),
                                  ("--canvas-id", args.canvas_id),
                                  ("--section-id", args.section_id)) if not v]
        if missing:
            print(f"ERROR: --publish needs {', '.join(missing)}", file=sys.stderr)
            return 2
        publish(args.canvas_id, args.section_id, body, token)
        print("published to Slack", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
