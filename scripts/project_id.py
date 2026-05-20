#!/usr/bin/env python3
"""
Shared project-id encoding for hooks that need to compare a session's
working directory against the ``project`` field stored on memories.

Why
---
``hooks/session-start-retrieval.py`` derives a project id from
``cwd`` to filter memories to the current project. The extraction hook
uses ``Path(transcript_path).parent.name`` — a value Claude Code itself
encodes from cwd by replacing ``/`` with ``-``. The two encodings need
to match byte-for-byte; if they ever drift, ``is_same_project`` returns
``False`` for every memory of the active project and project-aware
retrieval silently breaks.

Until this batch the encoding lived inline in
``session-start-retrieval.py`` (``str(Path(cwd).resolve()).replace("/", "-")``).
The audit (IC3, C-C4, C-X3) flagged the duplication as a future-proofing
risk — Claude Code could change its encoding (URL-encode reserved
characters, for example), and any consumer of the ``project`` field
would silently disagree until someone noticed empty retrieval.

Both consumers now import ``encode_project_id`` from this module.

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — IC3.
* ``reports/audit-2026-05-02/cluster-C-hooks.md`` — C-C4 (retrieval),
  C-X3 (cross-file).
"""

from pathlib import Path


def encode_project_id(cwd: str) -> str | None:
    """Encode *cwd* as the canonical project id used by memory writers.

    Resolves *cwd* to an absolute path (matching the historical
    behaviour of ``session-start-retrieval.py``), then replaces every
    ``/`` with ``-`` — the same encoding Claude Code uses for the
    project directory under ``~/.claude/projects/<encoded-cwd>/``.

    Returns ``None`` for an empty *cwd* (callers treat ``None`` as
    "no current project known").

    Examples
    --------
    >>> encode_project_id("/home/shawn/personal-assistant")
    '-home-shawn-personal-assistant'
    >>> encode_project_id("")
    >>> encode_project_id("/")
    '-'
    """
    if not cwd:
        return None
    return str(Path(cwd).resolve()).replace("/", "-")


def decode_project_id(project_id: str) -> Path | None:
    """Inverse of ``encode_project_id``.

    Replaces every ``-`` with ``/`` to reconstruct the original cwd
    path. Returns ``None`` for empty or whitespace-only input.

    Caveat: encoding is lossy when path components themselves contain
    hyphens (e.g. ``~/Code/cc-session-toolkit``). The historical
    encoding does not distinguish path separator hyphens from intrinsic
    hyphens, so decode reconstructs a *candidate* path; callers that
    need a verified path should resolve against the filesystem and
    fall back gracefully if the candidate does not exist.

    Examples
    --------
    >>> decode_project_id("-home-shawn-personal-assistant")
    PosixPath('/home/shawn/personal-assistant')
    >>> decode_project_id("-home-shawn-Code-cc-session-toolkit")  # ambiguous
    PosixPath('/home/shawn/Code/cc/session/toolkit')
    """
    if not project_id or not project_id.strip():
        return None
    return Path(project_id.replace("-", "/"))


# ============================================================================
# Repo-set discovery (Memory System v2, Phase 2)
# ============================================================================
#
# anchor_verify.py needs to check whether a file or commit referenced by a
# memory exists somewhere — not just in the cwd repo where the memory was
# written, but across the user's active project tree. The discovery walks
# a fixed set of root paths and finds every ``.git`` directory within a
# bounded depth. The list of roots is intentionally a constant rather than
# a config file so behaviour is predictable across machines.
#
# Scope decision (Shawn, 2026-05-15): all active project directories,
# including ~/Code/teaching/* and ~/personal-assistant itself, plus the
# pa-data submodule.

# Discovery roots and their max walk depths. Tuples of (path, max_depth)
# where max_depth is the number of directory levels below the root to
# search for ``.git``. Depth 1 means "this directory only"; depth 2 means
# "this directory and its immediate children".
#
# Computed inside ``_repo_discovery_roots`` rather than at module import
# time so the lookup re-reads ``Path.home()`` on every call. If HOME
# changes mid-process — a test harness using ``monkeypatch.setenv``, or
# a privilege drop via sudo — a module-level tuple would otherwise pin
# the old paths for the lifetime of the process.
def _repo_discovery_roots() -> tuple[tuple[Path, int], ...]:
    """Return the discovery-root tuple, evaluated against the *current* HOME."""
    home = Path.home()
    return (
        (home / "Code", 2),
        (home / "personal-assistant", 1),
        (home / "personal-assistant" / "data", 1),
    )


def repo_set() -> list[Path]:
    """Discover all active git repos under the configured discovery roots.

    Walks each root returned by ``_repo_discovery_roots()`` to its depth
    and collects directories that contain a ``.git`` entry (directory
    *or* file — submodules use a ``.git`` file pointing at the parent's
    ``.git/modules/...``).

    Returns a deduplicated list of absolute paths. Empty list if no
    roots exist (e.g. fresh machine before clones).
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def _walk(root: Path, depth: int) -> None:
        if not root.exists():
            return
        # Depth 1: check the root itself for ``.git``.
        if (root / ".git").exists() and root not in seen:
            found.append(root)
            seen.add(root)
        # Depth >= 2: descend one level and recurse.
        if depth >= 2:
            try:
                children = list(root.iterdir())
            except (PermissionError, OSError):
                return
            for child in children:
                try:
                    if not child.is_dir():
                        continue
                except OSError:
                    # ``is_dir`` can raise on broken symlinks or other
                    # transient stat failures — skip the entry rather
                    # than aborting the whole walk.
                    continue
                try:
                    _walk(child, depth - 1)
                except OSError:
                    # Recursive descent can fail on symlink loops or
                    # other filesystem oddities; widen the catch beyond
                    # the inner ``iterdir`` so a single bad subtree
                    # doesn't take down the whole discovery pass.
                    continue

    for root, depth in _repo_discovery_roots():
        _walk(root, depth)

    return found


def repo_set_for(project_id: str | None) -> list[Path]:
    """Return the repo set with the decoded project path ordered first.

    When ``anchor_verify`` checks whether a file referenced by a memory
    exists, the most likely match is in the project where the memory
    was written. Returning that path first lets verification short-
    circuit on the common case.

    Falls back to ``repo_set()`` (unordered) when *project_id* is
    ``None``, empty, or decodes to a path not in the discovered set.
    """
    discovered = repo_set()
    if not project_id:
        return discovered

    candidate = decode_project_id(project_id)
    if candidate is None:
        return discovered

    # Match by resolved-path equality. The decoded path may not match a
    # discovered repo exactly when path components contain hyphens (see
    # ``decode_project_id`` caveat) — in that case fall back to discovery
    # order without prioritisation.
    try:
        candidate_resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return discovered

    primary: list[Path] = []
    rest: list[Path] = []
    for repo in discovered:
        try:
            if repo.resolve() == candidate_resolved:
                primary.append(repo)
                continue
        except (OSError, RuntimeError):
            pass
        rest.append(repo)
    return primary + rest
