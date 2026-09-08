#!/usr/bin/env python3
"""Archive agent mail into the private data submodule, with a JSONL index.

Why (Shawn, 2026-09-08): nothing ever deletes agent mail, so ``~/agent-mail``
is already the complete record of how the two agents work together — every
message, review, correction, retraction, and receipt. But it lives on one
disk, in no repository, with no backup. This script makes it durable and
indexable: an append-only copy under ``data/agent-mail/`` (the private
``pa-data`` submodule, so it is versioned and pushed by the daily sync) plus
``data/agent-mail/index.jsonl``, one record per message with the routing
headers, sizes, hashes, and the receipt that closed it. Private for now; a
curated public export is a later, separate step.

Rules:

- **Append-only.** Nothing is ever removed from the archive. A source file
  that goes missing stays archived; a source file whose bytes change (they
  should not — messages and receipts are write-once) is re-copied and the
  index records the new hash.
- **Copy, never move.** The live mailbox is untouched; both agents' subtrees
  are read only.
- **Both agents' mail is archived**, under the same relative layout as the
  mailbox: ``<agent>/outbox/<recipient>/<file>`` and
  ``<agent>/seen/<sender>/<file>``.
- **The index is regenerated** from the archive on every run, so it is
  always a function of the archived files (safe to diff, cheap to rebuild).

Usage:
    archive-agent-mail.py [--root ~/agent-mail] [--archive <data>/agent-mail]
                          [--commit] [--quiet]

``--commit`` stages and commits ``agent-mail/`` in the data submodule (an
explicit pathspec, so other pending data changes are left alone); the daily
sync pushes and bumps the parent pointer. Exit 0 always unless the archive
directory cannot be written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PA_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = Path(os.environ.get("AGENT_MAIL_ROOT", "~/agent-mail")).expanduser()
DEFAULT_ARCHIVE = PA_DIR / "data" / "agent-mail"
MAX_HEADER_BYTES = 4_096
MAX_MESSAGE_BYTES = 65_536   # same cap as the hooks; larger files are not mail
HEADER_NAMES = ("From", "To", "Project", "Lane", "Workstream", "Date", "Re")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_headers(path: Path) -> dict[str, str]:
    """Bounded header block, known names only; ends at the first blank line."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            prefix = handle.read(MAX_HEADER_BYTES)          # bounded: never the whole file
    except OSError:
        return {}
    headers: dict[str, str] = {}
    for line in prefix.splitlines():
        if not line.strip():
            break
        name, separator, value = line.partition(":")
        if separator and name in HEADER_NAMES:
            headers[name] = value.strip()
    return headers


def mail_files(root: Path) -> list[Path]:
    """Every regular ``.md`` under ``<agent>/outbox/*/`` and ``<agent>/seen/*/``."""
    found: list[Path] = []
    if not root.is_dir():
        return found
    for agent_dir in sorted(root.iterdir()):
        if agent_dir.is_symlink() or not agent_dir.is_dir():
            continue
        for kind in ("outbox", "seen"):
            kind_dir = agent_dir / kind
            if kind_dir.is_symlink() or not kind_dir.is_dir():
                continue                    # a symlinked outbox could point anywhere
            for peer_dir in sorted(kind_dir.glob("*")):
                if peer_dir.is_symlink() or not peer_dir.is_dir():
                    continue
                for path in sorted(peer_dir.iterdir()):
                    if path.suffix != ".md" or path.is_symlink() or not path.is_file():
                        continue
                    if not path.name.isprintable():
                        continue
                    try:
                        if path.stat().st_size > MAX_MESSAGE_BYTES:
                            continue        # not mail by the protocol; never into the repo
                    except OSError:
                        continue
                    found.append(path)
    return found


def copy_new(root: Path, archive: Path) -> tuple[int, int]:
    """Copy new or changed mail files into the archive. Returns (added, changed)."""
    added = changed = 0
    for source in mail_files(root):
        relative = source.relative_to(root)
        target = archive / relative
        if target.exists():
            if sha256(target) == sha256(source):
                continue
            changed += 1
        else:
            added += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return added, changed


def sent_from_name(name: str) -> str:
    """The send time from the filename prefix (``20260825T010343.855743Z-…``).

    Taken from the name, not the file's mtime, so the index is a pure
    function of names and contents and does not churn when another machine
    checks the archive out.
    """
    stamp = name.split("-", 1)[0]
    try:
        parsed = datetime.strptime(stamp[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def when_from_note(note: str) -> str:
    """The receipt time from its first line, else empty.

    Both agents' conventions are accepted: Claude writes ``read <ISO> by …``,
    the Codex side writes ``Read: <ISO>`` or ``Read: <date> <zone>``. The
    time is the first token after the keyword; a bare date is kept as is.
    """
    parts = note.split()
    if len(parts) >= 2 and parts[0].rstrip(":").casefold() == "read":
        stamp = parts[1]
        if stamp[:4].isdigit():             # a date, not "by" in "read by claude …"
            return stamp
    return ""


def build_index(archive: Path) -> list[dict]:
    """One record per archived message, joined to its receipt if present."""
    records: list[dict] = []
    for message in mail_files(archive):
        relative = message.relative_to(archive)
        parts = relative.parts  # <agent>/outbox/<recipient>/<file>
        if len(parts) != 4 or parts[1] != "outbox":
            continue
        sender, _, recipient, name = parts
        headers = read_headers(message)
        receipt_path = archive / recipient / "seen" / sender / name
        receipt = None
        if receipt_path.is_file():
            try:
                note = receipt_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                note = []
            first_line = (note[0] if note else "")[:500]
            receipt = {
                "path": receipt_path.relative_to(archive).as_posix(),
                "when": when_from_note(first_line),
                "note": first_line,
            }
        records.append({
            "path": relative.as_posix(),
            "from": sender,
            "to": recipient,
            "project": (headers.get("Project") or "any").casefold(),
            "lane": (headers.get("Lane") or "any").casefold(),
            "workstream": headers.get("Workstream") or "",
            "date": headers.get("Date") or "",
            "subject": "".join(ch for ch in headers.get("Re", "") if ch.isprintable())[:200],
            "bytes": message.stat().st_size,
            "sha256": sha256(message),
            "sent": sent_from_name(name),
            "receipt": receipt,
        })
    records.sort(key=lambda r: (r["date"] or r["sent"], r["path"]))
    return records


def write_index(archive: Path, records: list[dict]) -> bool:
    """Write ``index.jsonl``; return True when its content changed."""
    path = archive / "index.jsonl"
    text = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def commit(archive: Path, summary: str) -> bool:
    """Commit the archive directory in its repository with an explicit pathspec."""
    repo = archive.parent
    relative = archive.relative_to(repo).as_posix()
    subprocess.run(["git", "-C", str(repo), "add", "--", relative], check=True)
    staged = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--quiet", "--", relative])
    if staged.returncode == 0:
        return False
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", f"chore(agent-mail): {summary}",
         "--", relative], check=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        args.archive.mkdir(parents=True, exist_ok=True)
        added, changed = copy_new(args.root, args.archive)
        records = build_index(args.archive)
        index_changed = write_index(args.archive, records)
    except OSError as error:
        print(f"agent-mail archive failed: {error}", file=sys.stderr)
        return 1
    receipted = sum(1 for r in records if r["receipt"])
    summary = f"{added} added, {changed} changed; {len(records)} messages, {receipted} receipted"
    committed = False
    # Always try when asked: a commit that failed on an earlier run leaves
    # files staged, and commit() itself is a no-op when nothing is staged.
    if args.commit:
        try:
            committed = commit(args.archive, summary)
        except subprocess.CalledProcessError as error:
            print(f"agent-mail archive commit failed: {error}", file=sys.stderr)
    if not args.quiet:
        print(f"agent-mail archive: {summary}" + (" (committed)" if committed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
