#!/usr/bin/env python3
"""
Shared project-id encoding for hooks that need to compare a session's
working directory against the ``project`` field stored on memories.

Why
---
``hooks/session-start-retrieval.py`` derives a project id from
``cwd`` to filter memories to the current project. The extraction hook
uses ``Path(transcript_path).parent.name`` — a value Claude Code itself
encodes from cwd. The two encodings need to match byte-for-byte; if they
ever drift, ``is_same_project`` returns ``False`` for every memory of the
active project and project-aware retrieval silently breaks.

Until this batch the encoding lived inline in
``session-start-retrieval.py`` (``str(Path(cwd).resolve()).replace("/", "-")``).
The audit (IC3, C-C4, C-X3) flagged the duplication as a future-proofing
risk — Claude Code could change its encoding (URL-encode reserved
characters, for example), and any consumer of the ``project`` field
would silently disagree until someone noticed empty retrieval.

That risk was not hypothetical: the ``/``-only rule was already wrong for
any cwd containing a dot, and had been since before this module existed
(audit R4, 2026-09-08 — see ``encode_project_id`` for the live evidence
and the corrected rule).

Both consumers now import ``encode_project_id`` from this module.

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — IC3.
* ``reports/audit-2026-05-02/cluster-C-hooks.md`` — C-C4 (retrieval),
  C-X3 (cross-file).
"""

import re
from pathlib import Path

#: Every character Claude Code replaces with ``-`` when it names a project
#: directory. Written as "anything not alphanumeric" because that is the
#: conservative reading of the live evidence in ``encode_project_id``: a
#: narrower class (say ``[/.]``) would silently disagree with Claude Code
#: again the first time a cwd contained an underscore or a space, which is
#: precisely the drift this module exists to prevent.
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def encode_project_id(cwd: str) -> str | None:
    """Encode *cwd* as the canonical project id used by memory writers.

    Resolves *cwd* to an absolute path (matching the historical behaviour
    of ``session-start-retrieval.py``), then replaces every character
    outside ``[A-Za-z0-9]`` with ``-`` — the encoding Claude Code uses for
    the project directory under ``~/.claude/projects/<encoded-cwd>/``.

    Why not only ``/`` (audit R4, 2026-09-08)
    -----------------------------------------
    Until this fix the encoder replaced ``/`` alone. The live
    ``~/.claude/projects/`` directory disproved that: it holds
    ``-home-shawn-personal-assistant--claude-worktrees-workstream-g-efficacy``
    for the cwd
    ``/home/shawn/personal-assistant/.claude/worktrees/workstream-g-efficacy``
    — a DOUBLE dash, one for the separator and one for the dot. The old
    encoder produced ``…-.claude-worktrees-…`` instead, so any session whose
    cwd had a dotted component (every ``.claude/worktrees/`` worktree) saw
    zero same-project memories: project-scoped retrieval,
    ``collect_project_tags``, and Vector-2c scoping all silently emptied.

    Evidence base: all 20 names under ``~/.claude/projects/`` on amd-tower
    (2026-09-08). Fifteen of them name a cwd that still exists on disk, and
    this rule reproduces all fifteen byte-for-byte; the sixteenth is the
    dotted worktree above, whose directory has since been removed but whose
    cwd is known by construction. The remaining four name cwds that no
    longer exist. Only ``/`` and ``.`` are attested there — no live name
    contains an underscore or a space — so the wider character class is a
    deliberate inference from "``.`` is not special either", not a measured
    fact. If a cwd with an underscore or space ever appears, compare against
    the directory Claude Code actually creates and narrow the class if it
    disagrees.

    ``resolve()`` is kept: Claude Code derives the id from the process
    working directory, which the kernel reports in physical (symlink-free)
    form, so resolving matches. No symlinked project existed on this machine
    to confirm that empirically — it is a documented assumption, not a
    measurement.

    Returns ``None`` for an empty *cwd* (callers treat ``None`` as
    "no current project known").

    Examples
    --------
    >>> encode_project_id("/home/shawn/personal-assistant")
    '-home-shawn-personal-assistant'
    >>> encode_project_id("/personal-assistant/.claude/worktrees/wg")
    '-personal-assistant--claude-worktrees-wg'
    >>> encode_project_id("")
    >>> encode_project_id("/")
    '-'
    """
    if not cwd:
        return None
    return _NON_ALNUM.sub("-", str(Path(cwd).resolve()))


def decode_project_id(project_id: str) -> Path | None:
    """Best-effort inverse of ``encode_project_id``.

    Replaces every ``-`` with ``/`` to reconstruct a *candidate* cwd path.
    Returns ``None`` for empty or whitespace-only input.

    The encoding is many-to-one, so this is not a true inverse: it is exact
    only when no path component contains a character the encoder rewrites.
    The lossy cases, in full:

    * **Intrinsic hyphens.** ``~/Code/cc-session-toolkit`` encodes exactly
      as the (nonexistent) ``~/Code/cc/session/toolkit`` would.
    * **Dots.** ``.claude`` encodes to ``-claude``, so a dotted component is
      indistinguishable from one more level of nesting. This is what
      produces the attested double dash.
    * **Every other non-alphanumeric character** — underscore, space, ``+``,
      ``@`` — collapses to ``-`` as well, and cannot be recovered either.

    Callers needing a real path must treat the result as a candidate: check
    it against the filesystem and degrade gracefully when it does not exist.
    ``repo_set_for`` below does exactly that.

    Examples
    --------
    >>> decode_project_id("-tmp-foo-bar")
    PosixPath('/tmp/foo/bar')
    >>> decode_project_id("-home-shawn-personal-assistant")  # ambiguous
    PosixPath('/home/shawn/personal/assistant')
    >>> decode_project_id("-home-shawn-Code-cc-session-toolkit")  # ambiguous
    PosixPath('/home/shawn/Code/cc/session/toolkit')

    The middle example is the one to remember: the hub's own project id does
    NOT decode back to the hub, because "personal-assistant" contains a
    hyphen. The previous version of this docstring claimed it did.
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
