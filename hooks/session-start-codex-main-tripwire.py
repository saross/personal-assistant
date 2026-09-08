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
  identity names Codex; and
- it does not carry a ``Claude-Session`` trailer, or its author identity
  names Codex regardless. A commit made from a Claude Code session carries
  that trailer and may credit the Codex agent as co-author for a reviewed
  patch; the Codex agent's own commits never carry it. The trailer is a
  one-line opt-out that Codex could add (the hook is readable to it), so
  this exemption is a guard against mistakes, not an adversary; the
  alternative is a per-machine ``--ack`` for every such commit. Shawn's
  ruling is pending (audit decision D4).

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
import unicodedata
from pathlib import Path

REPO = Path.home() / "personal-assistant"
REFS = ("origin/main", "main")        # first that resolves wins
SINCE = "2026-09-07T00:00:00+10:00"   # the ruling day from local midnight; zone pinned (AEST)
ACK_FILE = Path.home() / ".cache" / "pa-codex-main-tripwire.ack"
WEB_FLOW_EMAIL = "noreply@github.com"
CODEX_MARKERS = ("codex",)            # matched case-insensitively
FETCH_TIMEOUT = 5                     # seconds; best-effort, never blocks a session
MAX_COMMITS = 500

# NUL is the one byte git guarantees cannot appear in a commit message, so
# it is the field separator; it reaches git as the %x00 escape (argv cannot
# carry a NUL) and comes back as the byte. Records are fixed groups of FIELDS
# fields, so a hostile subject or trailer cannot shift or forge a record.
FIELD_SEP = "\x00"
FIELD_SEP_FMT = "%x00"
FIELDS = 8


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
    fmt = FIELD_SEP_FMT.join((
        "%H", "%an", "%ae", "%ce", "%cs", "%s",
        "%(trailers:key=Co-Authored-By,valueonly,separator=%x2c)",
        "%(trailers:key=Claude-Session,valueonly)",
    )) + FIELD_SEP_FMT
    # No --max-count: git applies it before --reverse, which would drop the
    # OLDEST commits in the window — the ones this hook most needs to see.
    out = git(
        repo, "log", "--first-parent", "--no-merges", f"--since={since}",
        "--reverse", f"--format={fmt}", ref,
    )
    # Output is: f1 NUL f2 NUL … f8 NUL "\n" per commit — the newline git adds
    # after each record is glued to the next record's SHA, so groups are
    # exactly FIELDS wide and the SHA is stripped of it.
    parts = out.split(FIELD_SEP)
    flagged: list[dict[str, str]] = []
    for start in range(0, len(parts) - FIELDS + 1, FIELDS):
        (sha, author, author_email, committer_email, date, subject, trailers,
         claude_session) = parts[start:start + FIELDS]
        sha = sha.strip()
        if not sha:
            continue
        if sha in acked or committer_email.strip().lower() == WEB_FLOW_EMAIL:
            continue
        by_identity = names_codex(author) or names_codex(author_email)
        if claude_session.strip() and not by_identity:
            continue          # made from a Claude session; a co-author credit is not a push
        if by_identity or names_codex(trailers):
            flagged.append({
                "sha": sha, "date": date, "subject": printable(subject),
                "author": author_name(author),
            })
    return flagged[:MAX_COMMITS]


def _bracket_like(ch: str) -> bool:
    """True for anything that could read as a square bracket.

    The two ASCII brackets; every Unicode open/close punctuation character
    except the ASCII parentheses (which conventional-commit subjects need:
    ``fix(scope): …`` is 89% of this repository's history); and every
    character whose name says BRACKET, which catches the ``Sm``-category
    bracket pieces (U+23A1 ⎡, U+23A4 ⎤, …) that the category test misses.
    Text is NFKC-normalised first so fullwidth and small-form brackets fold
    to ASCII before the test (re-audits, 2026-09-08).
    """
    if ch in "[]":
        return True
    if ch in "()":
        return False
    return (unicodedata.category(ch) in ("Ps", "Pe")
            or "BRACKET" in unicodedata.name(ch, ""))


def printable(text: str, limit: int = 120) -> str:
    """A subject fit to relay: printable, no bracket-like characters.

    A subject cannot forge extra output lines or close the ``[author]``
    group that follows it; parentheses survive so the subject stays the
    subject.
    """
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if ch.isprintable() and not _bracket_like(ch))[:limit]


def author_name(text: str, limit: int = 60) -> str:
    """An author fit to sit inside ``[…]``: an allowlist, not a denylist.

    Names are letters, digits, spaces, and ``.-'_@()``; nothing else can
    appear inside the group, so nothing can close it early.
    """
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if ch.isalnum() or ch in " .-'_@()")[:limit].strip()


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
    repo = Path(os.environ.get("PA_TRIPWIRE_REPO", str(REPO)))
    if len(sys.argv) >= 2 and sys.argv[1] == "--ack":
        if len(sys.argv) != 3:
            print("usage: --ack <sha>", file=sys.stderr)
            return 2
        # Resolved here, not as a default argument, so tests and PA_TRIPWIRE_REPO apply.
        return acknowledge(sys.argv[2], repo=repo, path=ACK_FILE)

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
    hits = flagged_commits(repo, ref, acked=read_acks(ACK_FILE))   # resolved at call time
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
