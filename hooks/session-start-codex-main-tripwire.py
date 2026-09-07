#!/usr/bin/env python3
"""SessionStart hook: flag Codex-authored commits that landed directly on PA main.

Why this exists (ruled 2026-09-07, plan §Credentials): the Codex-side agent
holds a GitHub token that is Shawn's own identity and reaches
``personal-assistant``, which has no branch protection. GitHub therefore
cannot tell a Codex push from Shawn's. Inside the sandbox, Claude-owned PA
paths stay read-only, but between an admitted PA clone and PA ``main`` the
only barrier is the norm that Codex changes to PA arrive by branch + PR.
This hook is the detection layer behind that norm.

Rule: a commit is flagged when all of these hold —

- it is on the first-parent chain of ``main`` (it landed directly, rather
  than arriving as the second parent of a merge commit);
- it is not itself a merge commit;
- it was not committed by GitHub's web flow (``noreply@github.com``), which
  is how a "Squash and merge" by Shawn would look;
- it is dated on or after the ruling; and
- it carries a ``Co-Authored-By`` trailer naming Codex, or its author
  identity names Codex.

Subject lines mentioning Codex are deliberately not a signal: Claude's own
documentation commits mention Codex constantly.

Silent when clean, so it can run every session at no attention cost. When
something is flagged, the block below is elevated into context for Shawn to
read; a reviewed commit can be acknowledged with ``--ack <sha>`` so it stops
being reported. Fail-open: any error exits 0 with no output. This is a
tripwire, not a security control — commit dates and trailers are forgeable.

Usage:
    session-start-codex-main-tripwire.py            # hook mode
    session-start-codex-main-tripwire.py --ack SHA  # stop reporting SHA
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path.home() / "personal-assistant"
REFS = ("origin/main", "main")        # first that resolves wins
SINCE = "2026-09-07"                  # date of the ruling; nothing earlier matters
ACK_FILE = Path.home() / ".cache" / "pa-codex-main-tripwire.ack"
WEB_FLOW_EMAIL = "noreply@github.com"
CODEX_MARKERS = ("codex",)            # matched case-insensitively
FETCH_TIMEOUT = 5                     # seconds; best-effort, never blocks a session
MAX_COMMITS = 500

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


def git(repo: Path, *args: str, timeout: int = 15) -> str:
    """Run git in ``repo`` and return stdout; raise on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return result.stdout


def resolve_ref(repo: Path, candidates: tuple[str, ...] = REFS) -> str | None:
    """Return the first candidate ref that exists in ``repo``."""
    for ref in candidates:
        try:
            git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
            return ref
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
            continue
    return None


def names_codex(text: str) -> bool:
    """True when the text names Codex (case-insensitive marker match)."""
    lowered = text.lower()
    return any(marker in lowered for marker in CODEX_MARKERS)


def flagged_commits(
    repo: Path, ref: str, since: str = SINCE, acked: frozenset[str] = frozenset()
) -> list[dict[str, str]]:
    """Return direct-to-main commits attributable to Codex, oldest first.

    Pure with respect to everything but the repository: no fetch, no files.
    """
    fmt = FIELD_SEP.join((
        "%H", "%an", "%ae", "%ce", "%cs", "%s",
        "%(trailers:key=Co-Authored-By,valueonly,separator=%x2c)",
    )) + RECORD_SEP
    out = git(
        repo, "log", "--first-parent", "--no-merges", f"--since={since}",
        f"--max-count={MAX_COMMITS}", "--reverse", f"--format={fmt}", ref,
    )
    flagged: list[dict[str, str]] = []
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record.strip():
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) != 7:
            continue
        sha, author, author_email, committer_email, date, subject, trailers = parts
        if sha in acked or committer_email.strip().lower() == WEB_FLOW_EMAIL:
            continue
        if names_codex(trailers) or names_codex(author) or names_codex(author_email):
            flagged.append({"sha": sha, "date": date, "subject": subject, "author": author})
    return flagged


def read_acks(path: Path = ACK_FILE) -> frozenset[str]:
    try:
        return frozenset(
            line.split()[0] for line in path.read_text().splitlines() if line.strip()
        )
    except OSError:
        return frozenset()


def acknowledge(sha: str, repo: Path = REPO, path: Path = ACK_FILE) -> int:
    """Record a reviewed commit so the hook stops reporting it."""
    try:
        full = git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        print(f"not a commit in {repo}: {sha}", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{full} acknowledged\n")
    print(f"acknowledged {full[:7]}")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--ack":
        return acknowledge(sys.argv[2])

    repo = Path(os.environ.get("PA_TRIPWIRE_REPO", str(REPO)))
    if not (repo / ".git").exists():
        return 0
    fetched = True
    try:
        git(repo, "fetch", "--quiet", "origin", "main", timeout=FETCH_TIMEOUT)
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        fetched = False
    ref = resolve_ref(repo)
    if ref is None:
        return 0
    hits = flagged_commits(repo, ref, acked=read_acks())
    if not hits:
        return 0

    print("# ⚠ Codex-on-main tripwire — RELAY THIS TO SHAWN")
    print(
        f"Commits on personal-assistant {ref} since {SINCE} that carry a Codex "
        "co-author trailer or author and did NOT arrive through a merge commit, "
        "i.e. a direct push outside the branch + PR norm"
        + ("" if fetched else " (fetch failed; local refs only)") + ":"
    )
    for hit in hits:
        print(f"- {hit['sha'][:7]} {hit['date']} {hit['subject']} [{hit['author']}]")
    print(
        "After review, silence one with: python3 "
        "~/personal-assistant/hooks/session-start-codex-main-tripwire.py --ack <sha>"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail open: a tripwire must never block a session
