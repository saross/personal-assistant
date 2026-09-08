#!/usr/bin/env python3
"""
Mechanical anchor verification for memory records (Memory System v2,
Phase 2).

Why
---
The 2026-05-14 corpus audit showed only 1.2% active confabulation but
53% of memories carry no anchor that can be mechanically re-checked.
The structural fix is to require anchors on guidance/decision/progress
memories at write time and verify they resolve before recall trusts
the claim.

This module implements the *mechanical* verification path:
``verify_file`` (filesystem + git history), ``verify_commit`` (git
rev-parse), ``verify_zotero`` (best-effort, currently stubbed).
``verify_memory`` dispatches on each anchor type and aggregates.

The *tier-3* fallback (transcript-grep when mechanical anchors are
absent or fail) is deferred to Phase 0b: it depends on the canonical
session archive being operational. ``verify_memory`` returns ``None``
for memories with no anchors and ``"pending"`` for any anchor whose
verification can't complete — the caller (extraction-hook or drift
sweep) decides what to do.

Contract
--------
* All functions return string values from a small vocabulary:
  ``"true"``, ``"false"``, ``"pending"``. ``verify_memory`` may also
  return ``None`` when a record has no anchors at all (distinct from
  ``"false"`` which means "we tried and it didn't resolve").
* Fail-soft: any internal error returns ``"pending"`` rather than
  raising. The verification status is recorded; recall ranking
  respects it. Better an audit-trail flag than a silent crash in the
  extraction hook.
* No state. All inputs are arguments; no globals modified.

Timeouts
--------
Subprocess calls (git operations) carry short timeouts. A timed-out
check returns ``"pending"`` — the drift sweep will retry later. This
keeps the SessionEnd hook responsive even when a repo's index is
locked or a remote check is slow.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple


# Subprocess timeout in seconds. Tuned for warm git repos on local
# filesystems; cold cache or NFS-backed repos may need a higher value.
_GIT_TIMEOUT_S = 3

# Characters that make git read a pathspec as a PATTERN rather than a literal
# path. ``git log -- '*.md'`` matches every markdown file in history, so a junk
# anchor whose ref carries one of these would mint ``verified=true`` for a file
# that never existed (audit 2026-09-08, finding AN1). Every git invocation here
# passes ``--literal-pathspecs`` as well; this gate is the write-side half, so
# such a ref never reaches the resolver in the first place.
_PATHSPEC_MAGIC = ("*", "?", "[")

# The one git error text that means "checked, and absent" rather than "could
# not check". Any other non-zero exit from the history probe is treated as a
# failure to check and reported as "pending" (finding AN3).
_UNMATCHED_PATHSPEC = "did not match any file"

#: Repositories that cannot be consulted AT ALL — git is missing, the path is
#: not a repository, the volume is unmounted. Keyed by path, value is the
#: reason; the warning is printed once per process.
#:
#: A repository-level failure is a property of the repository, not of the ref
#: being checked, so it must not make every ref in the corpus "pending". One
#: unmounted checkout out of thirty-six did exactly that: every absent ref
#: read pending, the drift sweep's pending rate went to 100 %, and the 10 %
#: floor refused every sweep from then on (round 4f-3, finding M6). Such a
#: repository is EXCLUDED with a warning; only a ref-level failure — a
#: timeout, an unreadable object — still yields pending, and only for the
#: repositories that could hold the ref.
_UNUSABLE_REPOS: dict[str, str] = {}


def note_unusable_repo(repo: Path, reason: str) -> None:
    """Record *repo* as unusable, warning once per process."""
    key = str(repo)
    if key not in _UNUSABLE_REPOS:
        _UNUSABLE_REPOS[key] = reason
        print(f"[anchor_verify] WARN: excluding {key} from anchor resolution "
              f"({reason})", file=sys.stderr)


def repo_is_unusable(repo: Path) -> bool:
    """Has *repo* already been found unusable in this process?"""
    return str(repo) in _UNUSABLE_REPOS


def unusable_repos() -> dict[str, str]:
    """A copy of the exclusion registry, for reporting."""
    return dict(_UNUSABLE_REPOS)


def reset_unusable_repos() -> None:
    """Clear the registry. For tests and long-lived callers."""
    _UNUSABLE_REPOS.clear()

# Minimum hex characters we will treat as a commit reference. Git itself
# resolves a 4-character prefix in a small repository, which made
# ``verify_commit`` accept four hex characters of prose as a hash and find a
# collision in one of ~36 repositories (finding AN12). Seven is git's own
# ``core.abbrev`` floor and the length every tool in this repo records.
_MIN_COMMIT_HEX = 7

# Minimum hex characters before a separator-free, extension-free ref is read as
# a mis-typed object id rather than a short filename (``cafe`` stays a file).
_MIN_ID_HEX = 6


# ============================================================================
# verify_file — does this file exist anywhere we can see?
# ============================================================================


def _under_repo(repo: Path, relpath: str) -> Path | None:
    """Lexically join *relpath* onto *repo*, refusing anything that escapes it.

    Purely lexical (``normpath``; no ``resolve``) for the same reason as
    :func:`_relpath_in_repo` — the file may have been deleted since the memory
    was written, and stat-ing it would follow symlinks out of the repository.

    ``(repo / "../outside.txt").exists()`` was true for a file that lived in no
    repository at all, so a ref that walked out of every checkout verified
    ``true`` (audit 2026-09-08, finding AN11). Returns ``None`` when the
    joined path is not inside *repo*, and the caller then skips that
    repository entirely rather than probing outside it.
    """
    repo_str = os.path.normpath(str(repo))
    joined = os.path.normpath(os.path.join(repo_str, relpath))
    if joined == repo_str:
        return None
    return Path(joined) if joined.startswith(repo_str + os.sep) else None


def _resolves_inside(repo: Path, candidate: Path) -> bool:
    """Does *candidate*, followed through symlinks, still live inside *repo*?

    :func:`_under_repo` is lexical and must stay that way — it also guards the
    git probes, where the file may have been deleted and ``resolve`` would
    touch the filesystem. But a lexical check alone lets a SYMLINK inside the
    repository stand in for a path outside it: ``<repo>/link/secret.txt``
    passes the prefix test while the bytes live anywhere at all (round 4f-3,
    finding L1). This second check runs only where a file was actually found,
    so it costs a ``resolve`` on the hit path and nothing on the miss path.

    A resolve that raises (a broken symlink, a permission wall, a symlink
    loop) is treated as "not inside": we could not show that it is.
    """
    try:
        real = candidate.resolve()
        root = repo.resolve()
    except (OSError, RuntimeError):
        return False
    return real == root or str(real).startswith(str(root) + os.sep)


def _git_knows_path(repo: Path, relpath: str) -> str:
    """Does *relpath* exist at HEAD or anywhere in *repo*'s history?

    Two probes, cheapest first:
      1. ``git cat-file -e HEAD:<relpath>`` — present in the current tip.
      2. ``git log --all --max-count=1 -- <relpath>`` — ever recorded on
         *any* ref (covers files deleted-since, renamed, or only ever on a
         side branch). This is the "git history, not just HEAD" check: a
         memory whose file was deleted after the memory was written still
         resolves ``"true"`` here, because the path exists in history.

    Both probes run under ``--literal-pathspecs``. Without it git reads the
    second probe's argument as a *pattern*: ``*.md`` matched the whole
    markdown history of the repository and ``:(exclude)zzz`` matched
    everything else, so junk anchors minted ``verified=true`` and then
    ``confidence=high`` (audit 2026-09-08, finding AN1). A ref that walks out
    of the repository (``../outside``) is refused outright (finding AN11).

    Returns ``"true"`` / ``"false"`` / ``"pending"``. ``"false"`` is reserved
    for a *completed* check that found nothing: git ran, answered, and the path
    was absent from HEAD and from every ref's history. Anything that stopped us
    checking — a missing git binary, an unreadable or unmounted repository, a
    timeout, or an exit code we do not recognise — returns ``"pending"``, per
    the module contract above. Returning ``"false"`` there was finding AN3: the
    drift sweep wrote the fabricated failure to its append-only trend log, and
    ``recover_anchors`` treated the anchor as a recovery candidate and rewrote
    it.
    """
    if not relpath:
        return "false"
    if _under_repo(repo, relpath) is None:
        # Escapes the repository (or names the root itself): nothing for git
        # to resolve here, and probing it would ask about a path outside the
        # checkout entirely.
        return "false"
    if repo_is_unusable(repo):
        return "unusable"
    # 1. Present at the current tip? A non-zero exit here is inconclusive on
    #    its own (an empty repository has no HEAD), so fall through to the
    #    history probe rather than deciding.
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{relpath}"],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
        )
        if result.returncode == 0:
            return "true"
    except subprocess.TimeoutExpired:
        # Ref-level: this repository is alive, this probe was slow.
        return "pending"
    except (FileNotFoundError, OSError) as exc:
        # Repository-level: git is missing, or the checkout vanished. It will
        # fail identically for every other ref, so exclude it rather than
        # mark the whole corpus unchecked.
        note_unusable_repo(repo, f"{type(exc).__name__}: {exc}")
        return "unusable"
    # 2. Ever in history (any ref)? Covers deleted-since + renames.
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "--literal-pathspecs", "log", "--all",
             "--max-count=1", "--", relpath],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return "pending"
    except (FileNotFoundError, OSError) as exc:
        note_unusable_repo(repo, f"{type(exc).__name__}: {exc}")
        return "unusable"
    if result.returncode == 0:
        # git answered: output means the path is in history, no output means
        # it never was. This is the only path that may return "false".
        return "true" if (result.stdout or "").strip() else "false"
    if result.returncode == 1:
        return "false"
    if result.returncode == 128 and _UNMATCHED_PATHSPEC in (result.stderr or ""):
        # "did not match any file(s) known to git" — a completed check whose
        # answer is "absent", not a broken repository.
        return "false"
    if result.returncode == 128:
        # Any other 128 is the repository itself: not a git repository, a
        # corrupt object store, no commits at all. Same for every ref.
        note_unusable_repo(repo, (result.stderr or "git exit 128").strip()[:120])
        return "unusable"
    return "pending"


def _relpath_in_repo(abspath: str, repo: Path) -> str | None:
    """If *abspath* lies inside *repo*, return its repo-relative path; else None.

    Purely lexical (``normpath`` + prefix match) — deliberately avoids
    ``Path.resolve``/``relative_to`` so it works for files that have since
    been *deleted* (resolve would touch the filesystem and follow symlinks).
    The repo root itself maps to ``None`` (a directory, not a file anchor).
    """
    repo_str = os.path.normpath(str(repo))
    p = os.path.normpath(abspath)
    if p == repo_str:
        return None
    prefix = repo_str + os.sep
    return p[len(prefix):] if p.startswith(prefix) else None


def verify_file(path: str, repo_set: Iterable[Path]) -> str:
    """Return whether *path* resolves to a real file in any provided repo.

    A leading ``~`` / ``~user`` is expanded first (item 20), so anchors
    recorded as ``~/personal-assistant/notes/_inbox.md`` resolve instead of
    spuriously reading ``"false"``.

    Resolution order:
      * **Absolute** (incl. expanded-tilde) — ``stat`` it directly; on a
        miss, fall back to git history for any repo that *contains* the
        path. Previously absolute paths got no git fallback, so a
        deleted-since absolute file read ``"false"``; now it resolves via
        :func:`_git_knows_path` (HEAD + ``git log --all``).
      * **Repo-relative** — ``stat`` against each repo as a prefix, then the
        same HEAD + history probe per repo.

    Returns ``"true"`` on first hit, ``"false"`` only when every repository
    was actually consulted and none of them knew the path, and ``"pending"``
    whenever some check could not complete — a timeout, an unreadable or
    unmounted repository, a missing git binary, or (for a relative ref) an
    empty repo set, where nothing was checked at all (finding AN3/AN7).

    Note: a path-prefix *mismatch* (e.g. a bare ``continuity.md`` anchor for
    a file that lives at ``wiki/continuity.md``) is NOT rescued here — the
    fix for those is write-side anchor hygiene, not the resolver.
    """
    if not path:
        return "false"

    # Expand a leading ~ / ~user. A no-op for already-absolute or
    # genuinely-relative refs; rescues tilde-rooted anchors.
    expanded = os.path.expanduser(path)
    repos = list(repo_set)
    pending_seen = False
    checked_any = False

    if os.path.isabs(expanded):
        # Absolute (or expanded-tilde): stat directly first. A stat that
        # RAISES (an unmounted mount, a permission wall) told us nothing.
        try:
            if Path(expanded).exists():
                return "true"
            checked_any = True
        except OSError:
            pending_seen = True
        # Miss — the file may have been deleted since the memory was
        # written. Fall back to git history for any repo containing it.
        for repo in repos:
            rel = _relpath_in_repo(expanded, repo)
            if rel is None:
                continue
            status = _git_knows_path(repo, rel)
            if status == "true":
                return "true"
            if status == "unusable":
                # Excluded, not unchecked: this repository fails identically
                # for every ref, so it must not colour this verdict (M6).
                continue
            if status == "pending":
                pending_seen = True
            else:
                checked_any = True
        return "false" if checked_any and not pending_seen else "pending"

    # Repo-relative: working-tree stat against each repo as a prefix. The
    # candidate is normalised first, so ``../outside.txt`` cannot stat a file
    # that lives in no repository at all (finding AN11).
    for repo in repos:
        candidate = _under_repo(repo, expanded)
        if candidate is None:
            continue
        try:
            if candidate.exists() and _resolves_inside(repo, candidate):
                return "true"
        except OSError:
            # The stat itself failed: an unmounted volume, a permission wall.
            # We did not check, so we must not later say "absent".
            pending_seen = True

    # Filesystem miss — try HEAD + history in each repo.
    for repo in repos:
        if _under_repo(repo, expanded) is None:
            # The ref escapes this repository: not absent from it, just not
            # a question about it. An escaping ref that fits no repository
            # therefore ends up "false" via the empty-checked branch below.
            checked_any = True
            continue
        status = _git_knows_path(repo, expanded)
        if status == "true":
            return "true"
        if status == "unusable":
            continue      # excluded with a warning; see finding M6
        if status == "pending":
            pending_seen = True
        else:
            checked_any = True

    # "false" is committal, so it requires a completed check. An empty repo
    # set (a degraded machine, an unpopulated ~/Code) checks nothing and must
    # not condemn every anchor in the corpus.
    return "false" if checked_any and not pending_seen else "pending"


class TrackedPath(NamedTuple):
    """One tracked file, and the repository it belongs to.

    ``repo`` is the repository root as a string (empty when the caller has no
    attribution to offer). Recovery needs it because a bare basename recurs
    across repositories: pooling ~36 checkouts into one namespace let project
    A's dead ``src/util.py`` "recover" to project B's ``pkg/src/util.py``
    (audit 2026-09-08, finding AN2).
    """

    repo: str
    path: str


class SuffixMatch(NamedTuple):
    """A recovered path plus where it came from.

    ``scope`` is ``"same-project"`` when the match lies inside the memory's
    own project, and ``"cross-repo"`` when it was found only by searching the
    union of every repository. A caller that WRITES a recovered ref must
    refuse ``"cross-repo"`` unless the operator has asked for it: binding a
    memory to a same-named file in an unrelated repository is worse than
    leaving the anchor unresolved.
    """

    path: str
    scope: str


def _as_tracked(candidate: object) -> TrackedPath:
    """Normalise a candidate into a :class:`TrackedPath`.

    Accepts a :class:`TrackedPath`, a ``(repo, path)`` pair, or a bare
    repo-relative string (no attribution — such a candidate can never satisfy
    a project-scoped search).
    """
    if isinstance(candidate, TrackedPath):
        return candidate
    if isinstance(candidate, (tuple, list)) and len(candidate) == 2:
        return TrackedPath(str(candidate[0]), str(candidate[1]))
    return TrackedPath("", str(candidate))


def unique_suffix_match(
    ref: str,
    tracked_paths: Iterable[object],
    *,
    project_repos: Iterable[Path] | None = None,
) -> SuffixMatch | None:
    """Collision-guarded prefix recovery (item 21b core) — I/O-free.

    Item-20 triage found ~53 % of the still-false relative `file` anchors are
    *prefix-mismatches*: the file is real, but the anchor dropped a leading
    directory (`continuity.md` for `wiki/continuity.md`). This finds the
    intended file by path **suffix** — a tracked path *P* recovers *ref* when
    ``P == ref`` or ``P`` ends with ``"/" + ref`` — but returns the match
    **only when it is unique**. Zero matches → ``None`` (genuinely absent);
    more than one → ``None`` (ambiguous: recovering would risk binding the
    memory to the *wrong* file, which is worse than leaving it unresolved).

    Suffix (not bare-basename) matching keeps whatever directory context the
    ref carries: ``cc_session_toolkit/extraction.py`` recovers
    ``src/cc_session_toolkit/extraction.py`` without colliding with an
    unrelated ``hooks/extraction.py``.

    *tracked_paths* are repo-relative POSIX paths (e.g. from ``git ls-files``),
    each optionally carrying the repository it came from (see
    :class:`TrackedPath`). This is a measurement/recovery helper, deliberately
    **not** wired into :func:`verify_file`: loosening the live resolver to
    fuzzy matches would erode the very ``verified`` signal we are trying to
    make trustworthy.

    *project_repos* scopes the search (finding AN2). When it is given, ONLY
    candidates inside those repositories are considered, and a unique hit is
    returned as ``"same-project"``; a memory that names a project must not
    recover onto a same-named file in someone else's repository, so no union
    fallback happens. When it is ``None`` — the memory records no project, or
    none of the discovered repositories matches it — the union is searched and
    a unique hit is labelled ``"cross-repo"`` for the caller to accept or
    refuse.
    """
    ref_norm = ref.rstrip("/")
    if not ref_norm:
        return None
    suffix = "/" + ref_norm
    candidates = [_as_tracked(p) for p in tracked_paths]

    def _hits(pool: list[TrackedPath]) -> list[TrackedPath]:
        return [c for c in pool
                if c.path == ref_norm or c.path.endswith(suffix)]

    if project_repos is not None:
        wanted = {os.path.normpath(str(r)) for r in project_repos}
        scoped = _hits([c for c in candidates
                        if c.repo and os.path.normpath(c.repo) in wanted])
        if len(scoped) == 1:
            return SuffixMatch(scoped[0].path, "same-project")
        return None

    matches = _hits(candidates)
    return SuffixMatch(matches[0].path, "cross-repo") if len(matches) == 1 else None


# ============================================================================
# verify_commit — does this hash resolve to a real commit?
# ============================================================================


def verify_commit(hash_: str, repo_set: Iterable[Path]) -> str:
    """Return whether *hash_* resolves in any provided repo.

    Uses ``git rev-parse --verify <hash>^{commit}`` which only succeeds
    when the hash is a real commit object (not a tag, blob, or random
    hex string). Handles partial hashes (e.g. 7-char) when git is
    configured to disambiguate.

    Returns ``"true"`` on first hit, ``"false"`` when every repository was
    consulted and none recognised the hash, and ``"pending"`` when a check
    could not complete — a timeout, an unreadable repository, a missing git
    binary, an exit code other than "no such object", or an empty repo set
    (finding AN3). A ref that is not hash-shaped is ``"false"`` without any
    subprocess: that is a completed check of the ref's own shape.
    """
    if not hash_ or not _looks_like_hash(hash_):
        return "false"

    pending_seen = False
    checked_any = False
    for repo in repo_set:
        if repo_is_unusable(repo):
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "rev-parse",
                 "--verify", "--quiet", f"{hash_}^{{commit}}"],
                capture_output=True,
                timeout=_GIT_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            # Ref-level: the repository is alive, this probe was slow.
            pending_seen = True
            continue
        except (FileNotFoundError, OSError) as exc:
            # Repository-level: exclude it with a warning rather than let one
            # broken checkout make every commit ref in the corpus pending
            # (finding M6).
            note_unusable_repo(repo, f"{type(exc).__name__}: {exc}")
            continue
        if result.returncode == 0:
            return "true"
        if result.returncode == 1:
            # rev-parse --verify --quiet: the object is not in this repo.
            checked_any = True
        else:
            # 128 = not a repository, corrupt object store, and so on: a
            # property of the repository, so exclude it.
            note_unusable_repo(
                repo, (result.stderr or b"git exit 128").decode(
                    "utf-8", "replace").strip()[:120] or "git exit 128",
            )

    return "false" if checked_any and not pending_seen else "pending"


def _looks_like_hash(s: str, *, min_len: int = _MIN_COMMIT_HEX) -> bool:
    """Cheap sanity check before launching git. Avoids spawning a
    subprocess for obviously non-hash strings.

    *min_len* defaults to :data:`_MIN_COMMIT_HEX`, the floor for a ref we are
    willing to call a commit. Four hex characters is a legitimate git prefix
    but also an ordinary word (``face``, ``beef``, ``cafe``), and
    :func:`verify_commit` searches ~36 repositories — enough of them for a
    four-character prefix to collide with something (finding AN12).
    :func:`_looks_like_file_ref` passes the looser
    :data:`_MIN_ID_HEX` because it is answering a different question: is this
    token a mis-typed object id rather than a short filename?
    """
    if not s or len(s) < min_len or len(s) > 40:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


# Zotero item keys are 8 uppercase alphanumerics; accept a slightly wider
# 6–12 alphanumeric band to tolerate legacy/lowercase variants without
# admitting prose.
_ZOTERO_KEY = re.compile(r"[A-Za-z0-9]{6,12}")


# Object-id prefixes seen mis-typed as ``file`` anchors (Anthropic batch /
# message / request ids, run handles). A bare token starting with one of these
# is an id, not a path.
_ID_PREFIXES = ("msgbatch_", "msg_", "batch_", "req_", "run_")


def _looks_like_file_ref(ref: str) -> bool:
    """Cheap shape gate (item 21a): does *ref* plausibly denote a file path?

    I/O-free, like the rest of :func:`wellformed_anchor`. Tightens the original
    "any string without a newline/tab" rule, which let three empirically-observed
    junk classes through to ``verified=false`` (item-20 triage):

      * **prose** — ``"scoring table (7 sessions, 42 cells)"`` — whitespace but
        no path separator. (Real space-bearing paths, e.g. a Zotero PDF, always
        carry a ``/``, so keying on the separator — not on spaces — avoids
        rejecting them.)
      * **slash-command names** — ``/weekly-review``, ``/reflect`` — a leading
        ``/`` whose first token holds no further ``/``. Every real absolute path
        has ≥2 segments; trailing em-dash prose after the command is tolerated.
      * **bare object ids** — ``3825319a``, ``msgbatch_016RZj…`` — no separator,
        no extension, and either all-hex (≥6) or a known id prefix. A hash-shaped
        ref belongs in a ``commit`` anchor, not a ``file`` one.
      * **pathspec magic** — ``scripts/*.py``, ``docs/?eal.md``,
        ``scripts/[r]eal.py``, ``:(glob)**/x.py`` — a glob or a leading ``:``
        magic prefix, which git reads as a *pattern*. Such a ref names a set of
        files, not a file, so it can never be a legitimate anchor; before
        ``--literal-pathspecs`` it also verified ``true`` against whatever the
        pattern happened to match (finding AN1).

    Deliberately *not* rejected (shape-valid; the resolver decides whether they
    resolve): extensionless real files (``LICENSE``, ``Makefile``), bare
    basenames missing a dir prefix (``continuity.md`` — a resolver/recovery
    concern, item 21b), and directory refs (trailing ``/``).
    """
    if len(ref) > 256 or "\n" in ref or "\t" in ref:
        return False
    # Pathspec magic: a pattern, not a path (see the docstring, finding AN1).
    if ref.startswith(":") or any(c in ref for c in _PATHSPEC_MAGIC):
        return False
    # Single-segment absolute → slash-command shape (/weekly-review, /reflect).
    if ref.startswith("/"):
        first = ref.split()[0]            # tolerate "/cmd — trailing prose"
        if "/" not in first[1:]:
            return False
    has_sep = "/" in ref
    # Prose: whitespace but no path separator.
    if " " in ref and not has_sep:
        return False
    # Bare object id mis-typed as a file: no separator, no extension.
    if not has_sep and "." not in ref:
        if _looks_like_hash(ref, min_len=_MIN_ID_HEX) or any(
            ref.startswith(p) for p in _ID_PREFIXES
        ):
            return False
    return True


def wellformed_anchor(anchor: object) -> tuple[bool, str]:
    """Write-time structural gate on an anchor's *shape* — NO I/O (item 11).

    Distinct from the ``verify_*`` resolvers, which spawn git/FS lookups to
    decide whether an anchor *resolves*. This is the cheaper upstream check
    that the extraction hook applies before persisting: it rejects anchors
    that can never resolve because the ``ref`` is malformed for its ``type``
    — most importantly a ``commit`` whose ref is a descriptive slug
    (``rome-verification-script``) or a non-hex string (``bb5r1pr54``) rather
    than a hash. A malformed anchor is worse than no anchor: it forces the
    whole memory to ``verified=false`` even when the content is fine, so we
    drop it at write time.

    Returns ``(ok, reason)``; ``reason`` is a short tag for logging when
    ``ok`` is False. Validation is tight on ``commit`` (the observed failure
    mode, ~3 % of commit anchors) and, since item 21a, on ``file`` too —
    :func:`_looks_like_file_ref` rejects prose, slash-command names, and bare
    object ids mis-typed as paths, while still passing any genuine path
    (existence is the resolver's call, not ours). Unknown anchor types pass
    through (``ok=True``, ``reason='unknown-type'``) so a future type is never
    silently dropped — only known types are gated.
    """
    if not isinstance(anchor, dict):
        return False, "not-a-dict"
    a_type = anchor.get("type")
    a_ref = anchor.get("ref")
    if not isinstance(a_type, str) or not isinstance(a_ref, str):
        return False, "type-or-ref-not-str"
    ref = a_ref.strip()
    if not ref:
        return False, "empty-ref"
    if a_type == "commit":
        return (True, "ok") if _looks_like_hash(ref) else (False, "malformed-commit-ref")
    if a_type == "file":
        ok = _looks_like_file_ref(ref)
        return (ok, "ok") if ok else (False, "malformed-file-ref")
    if a_type == "zotero":
        ok = bool(_ZOTERO_KEY.fullmatch(ref))
        return (ok, "ok") if ok else (False, "malformed-zotero-key")
    if a_type == "url":
        ok = ref.startswith(("http://", "https://"))
        return (ok, "ok") if ok else (False, "malformed-url")
    return True, "unknown-type"


# ============================================================================
# verify_zotero — stubbed; real impl in Phase 5
# ============================================================================


def verify_zotero(key: str) -> str:
    """Stub: returns ``"pending"`` unconditionally.

    A real implementation would call ``scripts.zotero.search_items``
    or hit the Zotero API to confirm the 8-character key exists in
    the user's library. That requires authentication, rate limiting,
    and offline-graceful behaviour — out of scope for Phase 2.

    Returning ``"pending"`` (rather than ``"false"``) means recall
    won't de-weight a memory just because we didn't check; the drift
    sweep can retry once the real implementation lands.
    """
    return "pending"


# ============================================================================
# verify_memory — dispatcher
# ============================================================================


_VERIFIERS = {
    "file": verify_file,
    "commit": verify_commit,
    "zotero": lambda ref, _repo_set: verify_zotero(ref),
    # 'url' anchors deliberately unsupported in Phase 2 — URLs can
    # 200 today and 404 tomorrow, so they're a weak anchor type.
    # Treated as 'pending' until a content-hash strategy lands.
    "url": lambda _ref, _repo_set: "pending",
}


def verify_memory(record: dict[str, Any], repo_set: list[Path]) -> str | None:
    """Aggregate verification across all anchors on a memory.

    Decision matrix:
      * No ``anchors`` field, or empty list → returns ``None``. The
        caller distinguishes "we didn't try" from "we tried and
        failed" — typically pre-v2 memories land here.
      * All anchors return ``"true"`` → returns ``"true"``.
      * Any anchor returns ``"false"`` → returns ``"false"`` (strict).
      * Otherwise (mix of ``"true"`` and ``"pending"``, or all
        ``"pending"``) → returns ``"pending"``.

    The strict "any false ⇒ false" rule is deliberate: if Haiku
    extracted a memory citing five anchors and one is clearly invented,
    the memory is suspect regardless of the other four. The drift
    sweep can re-check ``"pending"`` later; ``"false"`` is committal.
    """
    anchors = record.get("anchors")
    if not anchors:
        return None

    any_pending = False
    saw_any_valid_anchor = False
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue  # malformed; skip silently
        a_type = anchor.get("type")
        ref = anchor.get("ref")
        if not a_type or not ref:
            continue

        verifier = _VERIFIERS.get(a_type)
        if verifier is None:
            continue  # unknown anchor type — ignore rather than fail

        # Reaching the verifier call means the anchor was structurally
        # valid and of a known type. Track this so an ``anchors`` list
        # that is entirely malformed / unknown-type does NOT collapse to
        # the "verified == true" branch below (zero valid anchors is
        # contractually equivalent to "no anchors" per the docstring).
        saw_any_valid_anchor = True
        try:
            result = verifier(ref, list(repo_set))
        except Exception:  # noqa: BLE001 — fail-soft per module contract
            result = "pending"

        if result == "false":
            return "false"
        if result == "pending":
            any_pending = True

    if not saw_any_valid_anchor:
        # Same semantics as an empty/missing ``anchors`` field per the
        # docstring: "None" means no verifiable anchors present. The
        # production hot path is protected by ``hooks/extraction-hook.py``
        # filtering anchors before write, so this branch is a latent
        # module-contract fix rather than a routine code path.
        return None
    return "pending" if any_pending else "true"


# ============================================================================
# Confidence binding rubric — F.1 from the v2 design
# ============================================================================


def bind_confidence(
    verified: str | None,
    *,
    has_why: bool = False,
    has_how_to_apply: bool = False,
    is_guidance_category: bool = False,
    current: str | None = None,
) -> str:
    """Map ``verified`` × structural completeness to a confidence level.

    Phase 2 takes over confidence assignment from the extractor's
    self-rating, per the audit finding that 93% of the pre-v2 corpus
    was ``confidence: high`` including every confabulation. The new
    rubric ties confidence to objective conditions.

    Mapping (in priority order):
      * ``verified == "true"`` and (not guidance category, or both
        ``why`` and ``how_to_apply`` populated) → ``"high"``
      * ``verified == "true"`` but guidance fields incomplete → ``"medium"``
      * ``verified in {"tier3", "pending"}`` → *current* when the record
        already carries ``"high"`` or ``"low"`` (case-folded), else
        ``"medium"``
      * ``verified == "false"`` → ``"low"``
      * ``verified is None`` (no anchors checked) → ``"low"``

    ``"tier3"`` is reserved for the Phase 0b transcript-grep fallback —
    not produced by this module yet, but the rubric handles it for
    forward compatibility.

    *current* is the confidence the record already carries, and it exists so
    that a re-verification pass cannot MOVE a record on the strength of a
    check that did not complete. ``"pending"`` means "we could not look", not
    "we looked and found nothing" (finding AN3): an unmounted repository
    during one sweep must not cost a verified-true memory its ``high``, and
    must not hand an unverified one a ``medium`` it did not earn (L2).
    A ``"false"`` verdict still demotes — that one is committal.
    """
    if verified == "true":
        if not is_guidance_category:
            return "high"
        if has_why and has_how_to_apply:
            return "high"
        return "medium"
    if verified in ("tier3", "pending"):
        # A check that did not complete is not evidence in EITHER direction:
        # it must not demote a "high" record, and it must not promote a "low"
        # one to "medium" on the strength of having failed to look (round
        # 4f-3, finding L2). Case-folded: the corpus carries "High".
        existing = str(current or "").strip().lower()
        if existing in ("high", "low"):
            return existing
        return "medium"
    # 'false' or None — both treated as untrusted.
    return "low"
