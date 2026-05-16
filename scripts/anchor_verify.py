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

import subprocess
from pathlib import Path
from typing import Any, Iterable


# Subprocess timeout in seconds. Tuned for warm git repos on local
# filesystems; cold cache or NFS-backed repos may need a higher value.
_GIT_TIMEOUT_S = 3


# ============================================================================
# verify_file — does this file exist anywhere we can see?
# ============================================================================


def verify_file(path: str, repo_set: Iterable[Path]) -> str:
    """Return whether *path* resolves to a real file in any provided repo.

    Resolution order:
      1. Direct filesystem ``stat`` against each repo as a prefix.
         Fastest path; covers the common "the file still exists" case.
      2. ``git cat-file -e HEAD:<path>`` against each repo. Catches
         files that were committed but deleted from the working tree.
      3. ``git log --all -- <path>`` to check whether the file ever
         existed in history (renamed/branched cases).

    Returns ``"true"`` on first hit, ``"false"`` if no path resolves,
    ``"pending"`` on subprocess timeout.

    The path is allowed to be absolute or repo-relative. Absolute paths
    are checked against the filesystem directly (the repo_set is
    ignored for the stat check).
    """
    if not path:
        return "false"

    # Absolute path: just stat it.
    if path.startswith("/"):
        return "true" if Path(path).exists() else "false"

    # Repo-relative: try each repo.
    for repo in repo_set:
        candidate = repo / path
        if candidate.exists():
            return "true"

    # Filesystem miss — try git history in each repo.
    pending_seen = False
    for repo in repo_set:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "cat-file", "-e", f"HEAD:{path}"],
                capture_output=True,
                timeout=_GIT_TIMEOUT_S,
            )
            if result.returncode == 0:
                return "true"
        except subprocess.TimeoutExpired:
            pending_seen = True
            continue
        except (FileNotFoundError, OSError):
            # git not installed, or repo path vanished mid-check
            continue
        # Try full history (covers renames + deleted-then-found cases).
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "log", "--all",
                 "--max-count=1", "--", path],
                capture_output=True,
                timeout=_GIT_TIMEOUT_S,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                return "true"
        except subprocess.TimeoutExpired:
            pending_seen = True
            continue
        except (FileNotFoundError, OSError):
            continue

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

        try:
            result = verifier(ref, list(repo_set))
        except Exception:  # noqa: BLE001 — fail-soft per module contract
            result = "pending"

        if result == "false":
            return "false"
        if result == "pending":
            any_pending = True

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
