#!/usr/bin/env python3
"""
Item 12 — read-only triage of ``verified=false`` anchored memories.

Classifies *why* each false-verified anchored record is false, so the
genuinely-suspect set (a real prune candidate) is separated from records that
are false only because of verifier limitations. **Pure read path — never
mutates the corpus.**

Per-anchor tag (``classify_anchor``):
  - ``malformed``   — fails ``anchor_verify.wellformed_anchor`` (e.g. a commit
                      ref that is a descriptive slug, not a hash). Caught at
                      write time since item 11; pre-existing ones remain.
  - ``broad-true``  — resolves against the *broad* repo set.
  - ``broad-false`` — well-formed but resolves nowhere, even broadly.
  - ``pending``     — zotero/url (unverifiable locally).

Per-record disposition (``dispose``):
  - ``clean-after-strip`` — the only false-causers are malformed anchors;
                            stripping them lets the record re-verify (or become
                            honestly unanchored). The memory is fine.
  - ``cross-repo``        — no malformed, no broad-false: the record was false
                            only because the live verifier used a too-narrow
                            per-project repo set. Re-verifying broadly flips it.
  - ``unresolvable``      — a well-formed anchor resolves nowhere even broadly.
                            The only bucket worth human review; but note much of
                            it is itself a ``verify_file`` path-handling gap
                            (``~``/absolute paths, HEAD-only checks), not wrong
                            memories — see the report's anchor-form breakdown.

The broad repo set is whatever ``project_id.repo_set`` discovers — the same
pass the live extraction hook uses — plus this checkout when it is a git
worktree that HOME-based discovery cannot see. Resolution reuses
``anchor_verify``'s real ``verify_file`` / ``verify_commit`` (memoised per
``(type, ref)``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

#: This checkout, derived from ``__file__`` rather than ``HOME``. A copy run
#: from a git worktree must resolve anchors against ITS OWN repository, not
#: whatever happens to sit at ``~/personal-assistant`` (finding ANT5).
PA_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_verify as av  # noqa: E402
import project_id  # noqa: E402


def build_basename_index(
    repos: list[Path],
) -> dict[str, list[av.TrackedPath]]:
    """``basename`` → sorted unique tracked files, across all *repos*.

    Each entry is an :class:`anchor_verify.TrackedPath` carrying the
    repository it came from. The attribution is what lets recovery stay inside
    the memory's own project: without it, ~36 checkouts share one namespace
    and a dead ``src/util.py`` in project A recovers onto project B's
    ``pkg/src/util.py`` (audit 2026-09-08, finding AN2).

    Sourced from ``git ls-files`` (tracked files only). Feeds the item-21b
    prefix-recovery diagnostic. A repository whose ``git ls-files`` fails is
    skipped and logged — a silent skip is indistinguishable from a repository
    with no tracked files, and it narrows the recovery namespace invisibly
    (finding ANT-Md).
    """
    index: dict[str, set[av.TrackedPath]] = {}
    for repo in repos:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "ls-files"],
                capture_output=True, text=True, timeout=20,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            print(f"[triage] WARN: cannot list {repo}: {exc}", file=sys.stderr)
            continue
        if result.returncode != 0:
            print(f"[triage] WARN: git ls-files failed in {repo} "
                  f"(exit {result.returncode})", file=sys.stderr)
            continue
        for f in result.stdout.splitlines():
            f = f.strip()
            if f:
                index.setdefault(os.path.basename(f), set()).add(
                    av.TrackedPath(str(repo), f)
                )
    return {k: sorted(v) for k, v in index.items()}


def recovery_status(ref: str, basename_index: dict[str, list[str]]) -> tuple[str, str | None]:
    """Three-way prefix-recovery classification for one *ref* (item 21b).

    Union-scoped and REPORTING ONLY: unlike
    :func:`anchor_verify.unique_suffix_match`, which the write path calls with
    the memory's own project, this counts what could in principle be recovered
    anywhere. The two numbers differ, and the report says so.

    Returns ``("recoverable", path)`` when exactly one tracked file suffix-
    matches (safe to recover — mirrors :func:`anchor_verify.unique_suffix_match`),
    ``("ambiguous", None)`` when >1 match (basename collision — recovering risks
    the wrong file), or ``("absent", None)`` when nothing matches.
    """
    ref_norm = ref.rstrip("/")
    if not ref_norm:
        return "absent", None
    candidates = [av._as_tracked(c)
                  for c in basename_index.get(os.path.basename(ref_norm), [])]
    suffix = "/" + ref_norm
    matches = [c.path for c in candidates
               if c.path == ref_norm or c.path.endswith(suffix)]
    if len(matches) == 1:
        return "recoverable", matches[0]
    return ("ambiguous", None) if matches else ("absent", None)


def classify_anchor(anchor: dict, resolve) -> str:
    """Tag one anchor. ``resolve`` maps a well-formed anchor to a verify result
    string (``"true"``/``"false"``/``"pending"``) — injected so the pure logic
    is testable without git/FS."""
    ok, _ = av.wellformed_anchor(anchor)
    if not ok:
        return "malformed"
    result = resolve(anchor)
    return {"true": "broad-true", "false": "broad-false"}.get(result, "pending")


def dispose(tags: list[str]) -> str:
    """Reduce per-anchor tags to a per-record disposition (see module docstring)."""
    non_malformed = [t for t in tags if t != "malformed"]
    if "broad-false" in non_malformed:
        return "unresolvable"
    if "malformed" in tags:
        return "clean-after-strip"
    return "cross-repo"


class RepoSetUnavailable(RuntimeError):
    """Raised when repository discovery cannot produce a usable repo set.

    Every anchor resolves against this set, so an empty (or degraded) one
    turns the whole corpus ``verified=false`` — a fabricated drift spike the
    append-only trend log then keeps for ever (audit 2026-09-08, findings
    AN7 / ANT5). Callers must fail loudly rather than sweep against nothing.
    """


class RepoSetShrunk(RepoSetUnavailable):
    """Discovery succeeded but found fewer repositories than a caller's floor.

    Distinct from a total discovery failure: the caller can tell the operator
    which floor was applied and how to reset it, because a repository that was
    archived or removed on purpose is a legitimate reason for the set to
    shrink (audit round 4f-3, finding C1).
    """

    def __init__(self, discovered: int, floor: int, hint: str = "") -> None:
        self.discovered = discovered
        self.floor = floor
        super().__init__(
            f"discovered {discovered} repositories, fewer than the {floor} "
            f"the floor requires{('; ' + hint) if hint else ''}"
        )


def broad_repo_set_detail() -> tuple[list[Path], int]:
    """Return ``(repos, discovered_count)``.

    ``discovered_count`` counts ONLY what :func:`project_id.repo_set` found —
    it excludes the :data:`PA_DIR` augmentation below. The augmentation
    depends on where the running copy lives (a worktree contributes one extra
    repository, the main checkout none), so a count that included it would
    differ between checkouts of the same machine. Anything comparing counts
    ACROSS runs — the drift sweep's append-only floor — must use the
    discovery-only number, or one sweep from a second checkout ratchets the
    floor above what any other checkout can ever reach (finding C1).

    See :func:`broad_repo_set` for what the repository list itself contains.
    """
    discovered = list(project_id.repo_set())
    repos = list(discovered)
    known = {str(r) for r in repos}
    for candidate in (PA_DIR, PA_DIR / "data"):
        if (candidate / ".git").exists() and str(candidate) not in known:
            repos.append(candidate)
            known.add(str(candidate))
    if not repos:
        raise RepoSetUnavailable(
            "no git repositories discovered — anchor resolution would report "
            "every anchor as absent"
        )
    return repos, len(discovered)


def broad_repo_set() -> list[Path]:
    """Every discovered git repository, plus this checkout.

    Discovery is :func:`project_id.repo_set` — the SAME pass the live
    extraction hook resolves anchors against. Maintaining a second,
    independently-written discovery here meant the two could silently
    disagree the moment a root was added to one of them (finding ANT5); this
    function is now a thin wrapper, and ``project_id`` is the source of truth.

    On top of it, :data:`PA_DIR` (and its ``data`` submodule) is added when it
    is a git repository discovery missed. ``project_id`` walks from ``HOME``,
    so a copy running out of ``~/worktrees/...`` would otherwise resolve its
    own anchors against a different checkout of the same repository.

    Raises :class:`RepoSetUnavailable` when nothing is found: on a fresh
    machine, an unmounted home, or a container, ``[]`` would silently condemn
    every anchored memory instead of reporting that we could not look.

    A caller that needs the discovery-only count (rather than this augmented
    list) wants :func:`broad_repo_set_detail`.
    """
    return broad_repo_set_detail()[0]


def _make_resolver(repos: list[Path]):
    """Return a memoised ``resolve(anchor)`` over *repos*.

    The cache key is ``(type, ref)``, not the ref alone: a ``commit`` anchor
    and a ``file`` anchor can carry the same text and must not share an
    answer (finding ANT-L7).
    """
    memo: dict[tuple, str] = {}

    def resolve(anchor: dict) -> str:
        t = anchor.get("type")
        ref = str(anchor.get("ref", "")).strip()
        key = (t, ref)
        if key in memo:
            return memo[key]
        if t == "commit":
            res = av.verify_commit(ref, repos)
        elif t == "file":
            res = av.verify_file(ref, repos)
        else:
            res = "pending"
        memo[key] = res
        return res

    return resolve


def main() -> None:
    corpus = Path.home() / "personal-assistant" / "data" / "memories" / "memories.jsonl"
    repos = broad_repo_set()
    resolve = _make_resolver(repos)
    print(f"broad repo set: {len(repos)} repos")

    disp = Counter()
    fileform = Counter()
    rel_refs: Counter = Counter()  # unique relative broad-false file refs (item 21b)
    commit_missing = 0
    with corpus.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not (str(r.get("verified")).lower() == "false" and r.get("anchors")):
                continue
            tags = [classify_anchor(a, resolve) for a in r["anchors"]]
            d = dispose(tags)
            disp[d] += 1
            if d != "unresolvable":
                continue
            # Characterise the unresolvable bucket: verifier gap vs genuine.
            # Labels updated post item-20/21a: tilde IS expanded and absolute
            # DOES get a git fallback now, so the residual of each form is the
            # genuinely-unrecoverable remainder (globs, ephemeral, non-repo).
            for a in r["anchors"]:
                ok, _ = av.wellformed_anchor(a)
                if not ok or resolve(a) != "false":
                    continue
                if a.get("type") == "file":
                    ref = str(a.get("ref", "")).strip()
                    if ref.startswith("~"):
                        fileform["tilde (~) — glob/unmounted/gone (expansion shipped item 20)"] += 1
                    elif ref.startswith("/"):
                        fileform["absolute — ephemeral/unmounted/non-repo"] += 1
                    else:
                        fileform["relative — see item-21b recovery breakdown below"] += 1
                        rel_refs[ref] += 1
                elif a.get("type") == "commit":
                    commit_missing += 1

    total = sum(disp.values())
    print(f"\nverified=false anchored records: {total}")
    for k in ("clean-after-strip", "cross-repo", "unresolvable"):
        n = disp.get(k, 0)
        print(f"  {k:18s}: {n:4d} ({100 * n / max(total, 1):.0f}%)")
    print("\nunresolvable bucket — broad-false FILE anchor forms (occurrences):")
    for k, n in fileform.most_common():
        print(f"  {n:4d}  {k}")
    print(
        "\nwell-formed COMMIT refs resolving nowhere "
        f"(strongest genuine signal): {commit_missing}"
    )

    # item-21b prefix-recovery diagnostic (READ-ONLY — no resolver change, no
    # corpus mutation). Of the unique relative refs that resolve nowhere, how
    # many point at a real tracked file via a UNIQUE path-suffix match (safely
    # recoverable prefix-mismatch) vs ambiguous (basename collision) vs absent?
    bn_index = build_basename_index(repos)
    rec = Counter()
    examples: list[tuple[str, str]] = []
    for ref in rel_refs:
        status, hit = recovery_status(ref, bn_index)
        rec[status] += 1
        if status == "recoverable" and hit is not None and len(examples) < 8:
            examples.append((ref, hit))
    uniq_n = len(rel_refs)
    print(f"\nitem-21b prefix-recovery over {uniq_n} unique relative refs:")
    for k in ("recoverable", "ambiguous", "absent"):
        n = rec.get(k, 0)
        print(f"  {k:12s}: {n:4d} ({100 * n / max(uniq_n, 1):.0f}%)")
    if examples:
        print("  sample unique recoveries (ref -> tracked path):")
        for ref, hit in examples:
            print(f"    {ref}  ->  {hit}")


if __name__ == "__main__":
    main()
