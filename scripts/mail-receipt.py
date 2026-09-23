#!/usr/bin/env python3
"""Write an agent-mail read receipt into Claude's own ``seen/`` subtree.

Receipting a peer message means placing a file of the same name under
``~/agent-mail/claude/seen/<sender>/``. Doing that with a bare ``cp`` needs a
broad shell permission, and a broad permission is the wrong trade for a
one-line operation: it would also authorise every other copy this session
might make. This script exists so the capability can be allow-listed exactly.

It refuses to write anywhere except Claude's own ``seen/`` subtree, which is
the only mail location Claude owns under
``global-agent-guidance/ownership.toml`` (rule ``agent-mail-claude``).

Usage:
    python3 scripts/mail-receipt.py <path-to-peer-message> [...]

Exit status is 0 only when every requested receipt exists afterwards.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import sys


MAIL_ROOT = Path.home() / "agent-mail"
SELF = "claude"
# Messages are named as a timestamp slug; anything else is refused rather than
# copied, matching the watcher's own refusal of non-slug filenames.
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")


def receipt_target(message: Path) -> Path:
    """Resolve the receipt path for a peer message, or raise ValueError.

    The message must sit at ``~/agent-mail/<sender>/outbox/claude/<name>.md``
    with ``<sender>`` not being Claude itself. Everything is resolved before
    comparison so a symlink or ``..`` segment cannot escape the mail root.
    """
    resolved = message.resolve()
    try:
        relative = resolved.relative_to(MAIL_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"not inside {MAIL_ROOT}: {message}") from error

    parts = relative.parts
    if len(parts) != 4 or parts[1] != "outbox" or parts[2] != SELF:
        raise ValueError(f"not a message addressed to {SELF}: {message}")

    sender = parts[0]
    if sender == SELF:
        raise ValueError("refusing to receipt Claude's own message")
    if not NAME_PATTERN.match(parts[3]):
        raise ValueError(f"refusing a non-slug filename: {parts[3]}")
    if not resolved.is_file():
        raise ValueError(f"not a regular file: {message}")

    return MAIL_ROOT / SELF / "seen" / sender / parts[3]


def write_receipt(message: Path) -> tuple[bool, str]:
    """Copy one message into the receipt subtree; report what happened."""
    try:
        target = receipt_target(message)
    except ValueError as error:
        return False, f"REFUSED  {error}"

    if target.exists():
        return True, f"ALREADY  {target}"

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(message.resolve(), target)
    return True, f"WROTE    {target}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("messages", nargs="+", type=Path,
                        help="peer message paths under ~/agent-mail/<sender>/outbox/claude/")
    arguments = parser.parse_args()

    failures = 0
    for message in arguments.messages:
        ok, line = write_receipt(message)
        print(line)
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
