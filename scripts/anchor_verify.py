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
from pathlib import Path
from typing import Any, Iterable


# Subprocess timeout in seconds. Tuned for warm git repos on local
# filesystems; cold cache or NFS-backed repos may need a higher value.
_GIT_TIMEOUT_S = 3


# ============================================================================
# verify_file — does this file exist anywhere we can see?
# ============================================================================


def _git_knows_path(repo: Path, relpath: str) -> str:
    """Does *relpath* exist at HEAD or anywhere in *repo*'s history?

    Two probes, cheapest first:
      1. ``git cat-file -e HEAD:<relpath>`` — present in the current tip.
      2. ``git log --all --max-count=1 -- <relpath>`` — ever recorded on
         *any* ref (covers files deleted-since, renamed, or only ever on a
         side branch). This is the "git history, not just HEAD" check: a
         memory whose file was deleted after the memory was written still
         resolves ``"true"`` here, because the path exists in history.

    Returns ``"true"`` / ``"false"`` / ``"pending"`` (the last only on a
    subprocess timeout). A missing git binary or a vanished repo path
    yields ``"false"`` for *this* repo — the caller tries the next one.
    """
    if not relpath:
        return "false"
    # 1. Present at the current tip?
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{relpath}"],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
        )
        if result.returncode == 0:
            return "true"
    except subprocess.TimeoutExpired:
        return "pending"
    except (FileNotFoundError, OSError):
        # git not installed, or repo path vanished mid-check
        return "false"
    # 2. Ever in history (any ref)? Covers deleted-since + renames.
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "log", "--all",
             "--max-count=1", "--", relpath],
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return "true"
    except subprocess.TimeoutExpired:
        return "pending"
    except (FileNotFoundError, OSError):
        return "false"
    return "false"


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

    Returns ``"true"`` on first hit, ``"false"`` if no path resolves,
    ``"pending"`` on subprocess timeout.

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

    if os.path.isabs(expanded):
        # Absolute (or expanded-tilde): stat directly first.
        if Path(expanded).exists():
            return "true"
        # Miss — the file may have been deleted since the memory was
        # written. Fall back to git history for any repo containing it.
        for repo in repos:
            rel = _relpath_in_repo(expanded, repo)
            if rel is None:
                continue
            status = _git_knows_path(repo, rel)
            if status == "true":
                return "true"
            if status == "pending":
                pending_seen = True
        return "pending" if pending_seen else "false"

    # Repo-relative: working-tree stat against each repo as a prefix.
    for repo in repos:
        if (repo / expanded).exists():
            return "true"

    # Filesystem miss — try HEAD + history in each repo.
    for repo in repos:
        status = _git_knows_path(repo, expanded)
        if status == "true":
            return "true"
        if status == "pending":
            pending_seen = True

    return "pending" if pending_seen else "false"


# ============================================================================
# verify_commit — does this hash resolve to a real commit?
# ============================================================================


def verify_commit(hash_: str, repo_set: Iterable[Path]) -> str:
    """Return whether *hash_* resolves in any provided repo.

    Uses ``git rev-parse --verify <hash>^{commit}`` which only succeeds
    when the hash is a real commit object (not a tag, blob, or random
    hex string). Handles partial hashes (e.g. 7-char) when git is
    configured to disambiguate.

    Returns ``"true"`` on first hit, ``"false"`` if no repo recognises
    the hash, ``"pending"`` on subprocess timeout.
    """
    if not hash_ or not _looks_like_hash(hash_):
        return "false"

    pending_seen = False
    for repo in repo_set:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "rev-parse",
                 "--verify", "--quiet", f"{hash_}^{{commit}}"],
                capture_output=True,
                timeout=_GIT_TIMEOUT_S,
            )
            if result.returncode == 0:
                return "true"
        except subprocess.TimeoutExpired:
            pending_seen = True
            continue
        except (FileNotFoundError, OSError):
            continue

    return "pending" if pending_seen else "false"


def _looks_like_hash(s: str) -> bool:
    """Cheap sanity check before launching git. Avoids spawning a
    subprocess for obviously non-hash strings."""
    if not s or len(s) < 4 or len(s) > 40:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


# Zotero item keys are 8 uppercase alphanumerics; accept a slightly wider
# 6–12 alphanumeric band to tolerate legacy/lowercase variants without
# admitting prose.
_ZOTERO_KEY = re.compile(r"[A-Za-z0-9]{6,12}")


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
    ``ok`` is False. Validation is intentionally tight on ``commit`` (the
    observed failure mode, ~3 % of commit anchors) and light elsewhere:
    ``file`` refs are only shape-checked (a path that doesn't exist *here*
    may resolve in another repo — that's the resolver's call, not ours).
    Unknown anchor types pass through (``ok=True``, ``reason='unknown-type'``)
    so a future type is never silently dropped — only known types are gated.
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
        ok = len(ref) <= 256 and "\n" not in ref and "\t" not in ref
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
      * ``verified in {"tier3", "pending"}`` → ``"medium"``
      * ``verified == "false"`` → ``"low"``
      * ``verified is None`` (no anchors checked) → ``"low"``

    ``"tier3"`` is reserved for the Phase 0b transcript-grep fallback —
    not produced by this module yet, but the rubric handles it for
    forward compatibility.
    """
    if verified == "true":
        if not is_guidance_category:
            return "high"
        if has_why and has_how_to_apply:
            return "high"
        return "medium"
    if verified in ("tier3", "pending"):
        return "medium"
    # 'false' or None — both treated as untrusted.
    return "low"
