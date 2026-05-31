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
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_verify as av  # noqa: E402


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
            for a in r["anchors"]:
                ok, _ = av.wellformed_anchor(a)
                if not ok or resolve(a) != "false":
                    continue
                if a.get("type") == "file":
                    ref = str(a.get("ref", "")).strip()
                    if ref.startswith("~"):
                        fileform["tilde (~) — verify_file can't expand"] += 1
                    elif ref.startswith("/"):
                        fileform["absolute — verify_file checks HEAD:<relpath>"] += 1
                    else:
                        fileform["relative (mostly deleted-since; HEAD-only check)"] += 1
                elif a.get("type") == "commit":
                    commit_missing += 1

    total = sum(disp.values())
    print(f"\nverified=false anchored records: {total}")
    for k in ("clean-after-strip", "cross-repo", "unresolvable"):
        n = disp.get(k, 0)
        print(f"  {k:18s}: {n:4d} ({100 * n / max(total, 1):.0f}%)")
    print("\nunresolvable bucket — broad-false FILE anchor forms (verifier gap vs genuine):")
    for k, n in fileform.most_common():
        print(f"  {n:4d}  {k}")
    print(
        "\nwell-formed COMMIT refs resolving nowhere "
        f"(strongest genuine signal): {commit_missing}"
    )


if __name__ == "__main__":
    main()
