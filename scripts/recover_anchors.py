#!/usr/bin/env python3
"""
Item 21b-act — correct recoverable anchor refs + strip junk anchors, then
re-verify the affected memories (no-API corpus cleanup).

Why
---
The item-20/21 triage showed ``verified=false`` is dominated not by wrong
memories but by two *write-side* defects this script repairs in the canonical
``memories.jsonl``:

  * **Prefix-mismatch** — a ``file`` anchor whose ref dropped its directory
    prefix (``continuity.md`` for ``wiki/continuity.md``). The file is real;
    the ref is cosmetically wrong, so the memory is stuck ``verified=false``
    and de-weighted in recall. We rewrite the ref to the unique tracked path
    (``anchor_verify.unique_suffix_match`` — recovered **only on a unique
    suffix hit**, collision-guarded so we never bind to the wrong file).
  * **Junk anchors** — prose, slash-command names, or bare object ids
    mis-typed as ``file`` anchors (caught by the item-21a write gate going
    forward, but already in the corpus). We strip the ones that fail
    :func:`anchor_verify.wellformed_anchor`.

Crucially, rewriting a ref does **not** by itself flip ``verified`` — nothing
re-runs verification on existing records (``verify_memory`` is only called in
the extraction hook). So after editing anchors we **re-verify** each modified
record with the *exact* production code path (``anchor_verify.verify_memory``
over ``project_id.repo_set()`` — the same repo set the hook uses, since
``repo_set_for`` only reorders it) and re-bind ``confidence`` via
``anchor_verify.bind_confidence``. The corpus's ``verified`` field therefore
keeps meaning exactly what the live system means.

Safety
------
* **Dry-run is the default.** ``--apply`` is required to mutate anything, and
  even then the change is gated by :mod:`_bulk_rewrite_guard`
  (``ensure_safe_to_rewrite``: origin==local on the ``data`` submodule, clean
  protected files, daily-sync flock) and wrapped in ``lock_jsonl_for_rewrite``
  so concurrent extraction-hook appends drain and are blocked for the rewrite
  window. The commit carries the ``Rewrite-Class: bulk`` trailer.
* **Minimal diff.** Unmodified records are written back **verbatim** (original
  line bytes); only modified records are re-serialised (``json.dumps`` with the
  same default flags the extraction hook uses).
* **Audit trail.** Each modified record gains a ``revisions`` entry
  (``{"revised_at", "action", "reason"}`` — matching the existing ``/forget``
  shape) recording what changed.
* **Postgres.** The mirror uses ``INSERT ... ON CONFLICT DO NOTHING``, so a
  normal sync will NOT propagate edits to existing rows. ``--apply`` therefore
  issues a surgical ``UPDATE`` of just ``verified``/``confidence``/``anchors``
  for the changed ids (no embedding — the embedded text is unchanged).

Usage
-----
::

    venv/bin/python3 scripts/recover_anchors.py                 # dry-run (default)
    venv/bin/python3 scripts/recover_anchors.py --report out.md # dry-run + save report
    venv/bin/python3 scripts/recover_anchors.py --apply         # mutate (guarded)
    venv/bin/python3 scripts/recover_anchors.py --apply --no-postgres  # JSONL only

Run ``--apply`` from the **main working tree** (not a git worktree): the bulk
guard operates on ``<repo>/data``, which is only the real submodule there.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anchor_verify as av  # noqa: E402
import project_id  # noqa: E402
from triage_anchors import build_basename_index  # noqa: E402


# Mirror of hooks/extraction-hook.py:706 (GUIDANCE_CATEGORIES). Kept as a local
# constant because the hook module is hyphenated and runs hook logic; these six
# category names are stable. If the hook's set changes, update this too.
GUIDANCE_CATEGORIES = frozenset(
    {"feedback", "decision", "gotcha", "methodology", "pattern", "error_mode"}
)

CORPUS = Path.home() / "personal-assistant" / "data" / "memories" / "memories.jsonl"


# ============================================================================
# Planning (pure-ish — injectable resolvers, no I/O, fully testable)
# ============================================================================


def _is_relative_file_ref(anchor: dict) -> bool:
    """True for a ``file`` anchor whose ref is repo-relative (not ~/absolute)."""
    if anchor.get("type") != "file":
        return False
    ref = str(anchor.get("ref", "")).strip()
    return bool(ref) and not ref.startswith(("~", "/"))


def plan_record(record, resolve, recover, reverify):
    """Compute the modification plan for one record, or ``None`` if unchanged.

    Injected callables keep this pure and testable:
      * ``resolve(type, ref) -> "true"|"false"|"pending"`` — anchor resolution.
      * ``recover(ref) -> str | None`` — unique suffix match (collision-guarded).
      * ``reverify(modified_record) -> "true"|"false"|"pending"|None`` — the
        production ``verify_memory`` over the modified anchors.

    Modifications: strip any anchor failing ``wellformed_anchor``; rewrite a
    relative ``file`` anchor that resolves nowhere but has a unique recovery.
    Returns a plan dict (with the fully-modified record under ``"record"``) or
    ``None`` when neither a strip nor a rewrite applies.
    """
    anchors = record.get("anchors")
    if not anchors:
        return None

    new_anchors = []
    ref_rewrites = []   # (old_ref, new_ref)
    stripped = []       # anchors removed
    for a in anchors:
        if not isinstance(a, dict):
            stripped.append(a)
            continue
        if not av.wellformed_anchor(a)[0]:
            stripped.append(a)
            continue
        if _is_relative_file_ref(a):
            ref = str(a["ref"]).strip()
            if resolve("file", ref) == "false":
                new_ref = recover(ref)
                if new_ref and new_ref != ref:
                    a2 = dict(a)
                    a2["ref"] = new_ref
                    new_anchors.append(a2)
                    ref_rewrites.append((ref, new_ref))
                    continue
        new_anchors.append(a)

    if not ref_rewrites and not stripped:
        return None

    modified = copy.deepcopy(record)
    modified["anchors"] = new_anchors

    old_verified = record.get("verified")
    new_verified = reverify(modified)
    # For a *correction* we always reflect the recomputed status, including
    # None (all anchors stripped → genuinely unanchored), which honestly
    # clears a now-meaningless "false". (The hook keeps None to avoid
    # overwriting a fresh record; here we are repairing an existing one.)
    modified["verified"] = new_verified
    modified["confidence"] = av.bind_confidence(
        new_verified,
        has_why=bool(record.get("why")),
        has_how_to_apply=bool(record.get("how_to_apply")),
        is_guidance_category=(record.get("category") in GUIDANCE_CATEGORIES),
    )

    return {
        "id": record.get("id"),
        "ref_rewrites": ref_rewrites,
        "stripped": stripped,
        "old_verified": old_verified,
        "new_verified": new_verified,
        "old_confidence": record.get("confidence"),
        "new_confidence": modified["confidence"],
        "record": modified,
    }


def add_revision(record: dict, *, when: str, ref_rewrites, stripped) -> None:
    """Append an audit-trail revision entry (matches the ``/forget`` shape)."""
    bits = []
    if ref_rewrites:
        bits.append(
            "rewrote " + "; ".join(f"{o} -> {n}" for o, n in ref_rewrites)
        )
    if stripped:
        refs = [str(a.get("ref")) if isinstance(a, dict) else str(a) for a in stripped]
        bits.append(f"stripped {len(stripped)} junk anchor(s): " + "; ".join(refs))
    record.setdefault("revisions", []).append({
        "revised_at": when,
        "action": "anchor-recover (item 21b)",
        "reason": "; ".join(bits),
    })


# ============================================================================
# Build plans over the corpus (I/O: reads corpus, builds resolvers)
# ============================================================================


def build_plans(corpus: Path, repos):
    """Return a list of per-record plans for every verified=false anchored
    record that has a recoverable ref and/or a strippable junk anchor."""
    bn_index = build_basename_index(repos)

    resolve_memo: dict[tuple, str] = {}

    def resolve(a_type, ref):
        key = (a_type, ref)
        if key in resolve_memo:
            return resolve_memo[key]
        if a_type == "commit":
            res = av.verify_commit(ref, repos)
        elif a_type == "file":
            res = av.verify_file(ref, repos)
        else:
            res = "pending"
        resolve_memo[key] = res
        return res

    recover_memo: dict[str, str | None] = {}

    def recover(ref):
        if ref not in recover_memo:
            recover_memo[ref] = av.unique_suffix_match(ref, _flat(bn_index, ref))
        return recover_memo[ref]

    def reverify(rec):
        return av.verify_memory(rec, repos)

    plans = []
    with corpus.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if not (str(r.get("verified")).lower() == "false" and r.get("anchors")):
                continue
            plan = plan_record(r, resolve, recover, reverify)
            if plan is not None:
                plans.append(plan)
    return plans


def _flat(bn_index, ref):
    """Candidate tracked paths sharing *ref*'s basename (narrows the matcher)."""
    import os
    return bn_index.get(os.path.basename(ref.rstrip("/")), [])


# ============================================================================
# Reporting
# ============================================================================


def render_report(plans) -> str:
    from collections import Counter
    trans = Counter()
    n_rewrites = sum(len(p["ref_rewrites"]) for p in plans)
    n_strips = sum(len(p["stripped"]) for p in plans)
    for p in plans:
        trans[f'{p["old_verified"]} -> {p["new_verified"]}'] += 1

    lines = []
    lines.append("# recover_anchors — dry-run proposal (item 21b-act)\n")
    lines.append(f"Records to modify: **{len(plans)}**")
    lines.append(f"- ref rewrites: **{n_rewrites}**   junk anchors stripped: **{n_strips}**\n")
    lines.append("## verified transitions")
    for k, n in trans.most_common():
        lines.append(f"- `{k}`: {n}")
    flips = sum(n for k, n in trans.items() if k.startswith("false -> true"))
    lines.append(f"\n**Records that flip false -> true: {flips}**\n")
    lines.append("## sample ref rewrites (first 20)")
    shown = 0
    for p in plans:
        for old, new in p["ref_rewrites"]:
            if shown >= 20:
                break
            lines.append(
                f"- `{old}`  ->  `{new}`  "
                f"(id {p['id']}, {p['old_verified']}->{p['new_verified']})"
            )
            shown += 1
        if shown >= 20:
            break
    lines.append("\n## sample strips (first 12)")
    shown = 0
    for p in plans:
        for a in p["stripped"]:
            if shown >= 12:
                break
            ref = a.get("ref") if isinstance(a, dict) else a
            lines.append(f"- id {p['id']}: stripped `{ref}`")
            shown += 1
        if shown >= 12:
            break
    return "\n".join(lines) + "\n"


# ============================================================================
# Apply (guarded mutation)
# ============================================================================


def apply_plans(plans, corpus: Path, *, do_postgres: bool) -> None:
    """Mutate memories.jsonl in place (guarded + locked), commit, update PG."""
    from _bulk_rewrite_guard import (
        ensure_safe_to_rewrite,
        lock_jsonl_for_rewrite,
        mark_bulk_rewrite_commit_msg,
        release_lock,
    )

    by_id = {p["id"]: p for p in plans if p["id"] is not None}
    when = datetime.now(timezone.utc).isoformat()
    for p in plans:
        add_revision(p["record"], when=when,
                     ref_rewrites=p["ref_rewrites"], stripped=p["stripped"])

    ensure_safe_to_rewrite(reason=f"recover_anchors: {len(plans)} records (item 21b)")
    try:
        with lock_jsonl_for_rewrite(corpus):
            tmp = corpus.with_suffix(".jsonl.tmp")
            n_written = 0
            with corpus.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as out:
                for line in src:
                    stripped_line = line.strip()
                    if not stripped_line:
                        out.write(line)
                        continue
                    rid = json.loads(stripped_line).get("id")
                    if rid in by_id:
                        out.write(json.dumps(by_id[rid]["record"]) + "\n")
                        n_written += 1
                    else:
                        out.write(line)  # verbatim — minimal diff
                # Flush + fsync the temp file to disk BEFORE the atomic rename,
                # so a crash/power-loss between the write and the replace cannot
                # leave a truncated corpus (parity with archive-memories.py).
                out.flush()
                os.fsync(out.fileno())
            tmp.replace(corpus)
            print(f"rewrote {n_written} records in {corpus}", file=sys.stderr)
    finally:
        release_lock()

    # NB: if _git_commit fails (e.g. a pre-commit hook rejects it, or a git lock
    # is contended), the corpus is rewritten on disk but uncommitted — a later
    # run will be blocked by ensure_safe_to_rewrite (dirty working tree). Recover
    # inside the data submodule with either:
    #   git commit -- memories/memories.jsonl   (keep the applied recovery), or
    #   git checkout -- memories/memories.jsonl  (discard; the pass is idempotent
    #                                             and can be re-run from clean).
    _git_commit(corpus, len(plans), mark_bulk_rewrite_commit_msg)
    if do_postgres:
        _update_postgres(plans)
    else:
        print("skipped postgres update (--no-postgres)", file=sys.stderr)


def _git_commit(corpus, n, mark) -> None:
    import subprocess
    data_dir = corpus.parent.parent  # .../data
    rel = corpus.relative_to(data_dir)
    subject = mark(
        f"fix(memories): recover {n} anchor refs + strip junk (item 21b)",
        rewrite_class="bulk",
    )
    subprocess.run(["git", "-C", str(data_dir), "add", str(rel)], check=True)
    subprocess.run(["git", "-C", str(data_dir), "commit", "-m", subject], check=True)
    print(f"committed {rel} in data submodule", file=sys.stderr)


def _update_postgres(plans) -> None:
    """Surgical UPDATE of verified/confidence/anchors for changed ids."""
    try:
        import psycopg2
        from psycopg2.extras import Json
    except ImportError:
        print("psycopg2 unavailable — skipping postgres update", file=sys.stderr)
        return
    try:
        conn = psycopg2.connect(dbname="claude_memories")  # scripts/sync-to-postgres.py:53
    except Exception as exc:  # noqa: BLE001
        print(f"postgres unreachable ({exc}) — skipping", file=sys.stderr)
        return
    # Guard against schema drift before issuing any UPDATE (parity with
    # archive-memories.py). The corpus is already committed by this point, so on
    # a mismatch warn loudly and return rather than exit non-zero — the JSONL is
    # correct; only PG is left unreconciled (fix with a rebuild-postgres).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _schema_version import assert_schema_version, SchemaVersionError
    try:
        assert_schema_version(conn)
    except SchemaVersionError as exc:
        conn.close()
        print(f"WARNING: postgres schema mismatch ({exc}) after the corpus was "
              "rewritten — PG not reconciled. Run rebuild-postgres.py to sync.",
              file=sys.stderr)
        return
    n = 0
    with conn, conn.cursor() as cur:
        for p in plans:
            rec = p["record"]
            cur.execute(
                "UPDATE memories SET verified=%s, confidence=%s, anchors=%s "
                "WHERE id=%s",
                (rec.get("verified"), rec.get("confidence"),
                 Json(rec.get("anchors") or []), p["id"]),
            )
            n += cur.rowcount
    conn.close()
    print(f"postgres: updated {n} rows", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="Mutate the corpus (default: dry-run only).")
    ap.add_argument("--no-postgres", action="store_true",
                    help="With --apply, skip the postgres column update.")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write the dry-run proposal to this path as well.")
    args = ap.parse_args(argv)

    repos = project_id.repo_set()
    print(f"repo set: {len(repos)} repos; corpus: {CORPUS}", file=sys.stderr)
    plans = build_plans(CORPUS, repos)
    report = render_report(plans)
    print(report)
    if args.report:
        args.report.write_text(report, encoding="utf-8")
        print(f"report written to {args.report}", file=sys.stderr)

    if not args.apply:
        print("DRY-RUN only. Re-run with --apply to mutate (guarded).", file=sys.stderr)
        return 0

    if not plans:
        print("nothing to apply.", file=sys.stderr)
        return 0
    apply_plans(plans, CORPUS, do_postgres=not args.no_postgres)
    return 0


if __name__ == "__main__":
    sys.exit(main())
