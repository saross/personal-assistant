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

The broad repo set is the personal-assistant repo, its ``data`` submodule, and
every ``~/Code/*`` git repo. Resolution reuses ``anchor_verify``'s real
``verify_file`` / ``verify_commit`` (memoised per ``(type, ref)``).
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_verify as av  # noqa: E402


def build_basename_index(repos: list[Path]) -> dict[str, list[str]]:
    """``basename`` → sorted unique repo-relative paths, across all *repos*.

    Sourced from ``git ls-files`` (tracked files only). Feeds the item-21b
    prefix-recovery diagnostic. A repo whose ``git ls-files`` errors is skipped.
    """
    index: dict[str, set[str]] = {}
    for repo in repos:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo), "ls-files"],
                capture_output=True, text=True, timeout=20,
            ).stdout
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
        for f in out.splitlines():
            f = f.strip()
            if f:
                index.setdefault(os.path.basename(f), set()).add(f)
    return {k: sorted(v) for k, v in index.items()}


def recovery_status(ref: str, basename_index: dict[str, list[str]]) -> tuple[str, str | None]:
    """Three-way prefix-recovery classification for one *ref* (item 21b).

    Returns ``("recoverable", path)`` when exactly one tracked file suffix-
    matches (safe to recover — mirrors :func:`anchor_verify.unique_suffix_match`),
    ``("ambiguous", None)`` when >1 match (basename collision — recovering risks
    the wrong file), or ``("absent", None)`` when nothing matches.
    """
    ref_norm = ref.rstrip("/")
    if not ref_norm:
        return "absent", None
    candidates = basename_index.get(os.path.basename(ref_norm), [])
    suffix = "/" + ref_norm
    matches = [p for p in candidates if p == ref_norm or p.endswith(suffix)]
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


def broad_repo_set() -> list[Path]:
    """PA repo + its data submodule + every ``~/Code/*`` git repo."""
    home = Path.home()
    repos = [home / "personal-assistant", home / "personal-assistant" / "data"]
    repos += [Path(p).parent for p in glob.glob(str(home / "Code" / "*" / ".git"))]
    return [r for r in repos if r.exists()]


def _make_resolver(repos: list[Path]):
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
