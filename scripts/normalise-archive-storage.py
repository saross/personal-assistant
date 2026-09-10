#!/usr/bin/env python3
"""normalise-archive-storage.py — one-off pass to a single transcript form.

Establishes the storage invariant decided 2026-08-22 (cc-archives health
brief, open question 1): **`session.jsonl.gz` is the canonical form for an
archived transcript.** Before this pass the archive held three coexisting
states — gz-only (729), raw-only (88, ~1.1 GB never compressed), and both
(34) — with no declared invariant, so every consumer had to guess the form
and consumers that guessed `*.jsonl` reported a nonexistent 12-week hole.

Per session directory (found via `session.meta.json`, walked recursively):

  raw-only   → compress to gz with a decompress round-trip sha256 verify,
               rewrite the meta's archive block to the gz form, delete the
               raw file ONLY after verification.
  both forms → compare content. Identical → delete raw, point meta at gz.
               One a strict prefix of the other (a mid-session snapshot
               beside a fuller capture) → keep the LONGER content as gz,
               delete the shorter. Divergent → touch nothing, report for
               manual reconciliation.
  gz-only    → untouched (already canonical).

⚠ Run this against EVERY store, not just one: the daily-sync passes are
append-only and never delete, so a raw file removed locally but left on
canonical is pulled straight back by pass 4. Order: local mirror, then the
canonical mount, then zbook's mirror at its next opportunity. R2 keeps old
raw copies (additive by design); that is acceptable residue.

Dry-run by default; pass --apply to write.

Usage:
    venv/bin/python3 scripts/normalise-archive-storage.py                 # dry-run, ~/cc-archives
    venv/bin/python3 scripts/normalise-archive-storage.py --apply
    venv/bin/python3 scripts/normalise-archive-storage.py \
        --root ~/mnt/rpi-shares/cc-archives-consolidated --apply
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import stat as stat_module
import sys
import time
from pathlib import Path


def sha256_file(path: Path, *, decompress: bool = False) -> tuple[str, int]:
    """Return (hex digest, byte count) of a file's (optionally gunzipped) content."""
    h = hashlib.sha256()
    n = 0
    opener = gzip.open if decompress else open
    with opener(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def is_prefix(shorter: Path, longer: Path, *,
              shorter_gz: bool, longer_gz: bool) -> bool:
    """True when `shorter`'s content is a strict byte-prefix of `longer`'s."""
    op_s = gzip.open if shorter_gz else open
    op_l = gzip.open if longer_gz else open
    with op_s(shorter, "rb") as fs, op_l(longer, "rb") as fl:
        while True:
            cs = fs.read(65536)
            cl = fl.read(len(cs) or 65536)
            if not cs:
                return True
            if cs != cl[:len(cs)]:
                return False
            # longer stream ended first → not a prefix relationship
            if len(cl) < len(cs):
                return False


def write_gz_verified(src_raw: Path, dest_gz: Path) -> tuple[str, int]:
    """Compress raw→gz with round-trip verification. Returns (raw sha, raw bytes)."""
    src_hash = hashlib.sha256()
    n = 0
    with open(src_raw, "rb") as f_in, gzip.open(dest_gz, "wb") as f_out:
        for chunk in iter(lambda: f_in.read(65536), b""):
            src_hash.update(chunk)
            n += len(chunk)
            f_out.write(chunk)
    rt_hash, _ = sha256_file(dest_gz, decompress=True)
    if rt_hash != src_hash.hexdigest():
        dest_gz.unlink(missing_ok=True)
        raise RuntimeError(f"round-trip verify FAILED for {src_raw}")
    return src_hash.hexdigest(), n


def gz_meta_block(meta: dict, gz_path: Path) -> dict:
    """Build the canonical gz-form archive block, preserving archived_at."""
    old = meta.get("archive", {}) or {}
    comp_sha, comp_bytes = sha256_file(gz_path)
    unc_sha, unc_bytes = sha256_file(gz_path, decompress=True)
    block = dict(old)
    block.update({
        "jsonl_path": "session.jsonl.gz",
        "jsonl_sha256": comp_sha,
        "jsonl_bytes": unc_bytes,
        "jsonl_compression": "gzip",
        "jsonl_bytes_compressed": comp_bytes,
        "jsonl_bytes_uncompressed": unc_bytes,
        "jsonl_sha256_uncompressed": unc_sha,
    })
    return block


#: A staged write in this pipeline completes in milliseconds, so a ``.tmp``
#: older than this was abandoned by a killed process. Comparing against the
#: run's own start time is not enough: a CONCURRENT normalise pass that began
#: a second before this one would have its in-flight staging swept out from
#: under it. An age threshold cannot make that mistake.
STALE_TEMP_MIN_AGE_SECONDS = 3600


def sweep_stale_temporaries(root: Path, started_at: float, *, apply: bool
                            ) -> tuple[list[Path], int]:
    """Remove ``*.tmp`` files under *root* left by an earlier interrupted run.

    The staged writes this script and ``bulk-archive.py`` use (findings AR14,
    AR9, and round 4c-2 finding 9) leave a ``session.jsonl.gz.tmp`` behind
    when the process is killed between the write and the rename. Nothing
    cleaned them up, and they are not inert: ``push-archives-to-r2.sh``
    mirrors the archive root wholesale, so a partial temporary became a
    PERMANENT object in R2 — permanent because the push is ``--immutable``
    and never deletes, so the half-written file could not be replaced or
    removed once uploaded (audit round 4c-3, finding L-10).

    Only entries at least :data:`STALE_TEMP_MIN_AGE_SECONDS` old are swept,
    so a temporary belonging to a concurrent normalise pass — or to this one
    — is never removed, whichever run started first.

    Symlinks are treated as objects in their own right and never followed:
    ``lstat`` gives the LINK's age, and ``unlink`` removes the link. Judging
    one by its target's mtime would let a link to a fresh file protect a
    long-abandoned link, and a dangling one used to raise inside ``stat``
    and be skipped in silence, for ever (audit round 4c-5, finding L3).

    Returns ``(paths swept, error count)``; in dry-run the first element is
    what WOULD be removed. An entry that could not be removed is an error,
    not a sweep, and the caller makes the run exit non-zero for it (finding
    L2) — a summary of "errors=0" over a temporary that is still there is
    exactly the reassurance this sweep exists to stop giving.
    """
    cutoff = started_at - STALE_TEMP_MIN_AGE_SECONDS
    swept: list[Path] = []
    errors = 0
    for candidate in sorted(root.rglob("*.tmp")):
        # ``lstat``, not ``stat``: see the docstring. It also answers "is
        # this a symlink?" and "how old is it?" in one call, and never
        # raises on a dangling link.
        try:
            info = candidate.lstat()
        except OSError as exc:
            print(f"[ERROR] cannot stat {candidate}: {exc}", file=sys.stderr)
            errors += 1
            continue

        is_link = stat_module.S_ISLNK(info.st_mode)
        # ``rglob`` matches DIRECTORIES too, and a directory named
        # ``something.tmp`` is not an abandoned staged write — it is
        # somebody's working directory. Unlinking one raises
        # IsADirectoryError, which the handler below caught, but the path
        # had already been counted and printed as swept: the summary said
        # "stale-temp=1 errors=0" over a directory that is still there
        # (audit round 4c-4, finding 2). A SYMLINK to a directory does not
        # reach this branch at all: ``info`` comes from ``lstat``, so
        # S_ISDIR describes the LINK, which is never a directory. The
        # ``not is_link`` conjunct this test used to carry was therefore
        # dead (audit round 4c-6, finding L-a).
        if stat_module.S_ISDIR(info.st_mode):
            print(f"[stale-temp — SKIPPED, is a directory] "
                  f"{candidate.relative_to(root)}", file=sys.stderr)
            continue

        if info.st_mtime > cutoff:
            continue              # too recent to be abandoned

        label = "stale-temp"
        if is_link:
            # Reported distinctly: a link in the archive is odd enough that
            # an operator should see it go, and a DANGLING one used to be
            # invisible entirely.
            label = (
                "stale-temp — dangling symlink" if not candidate.exists()
                else "stale-temp — symlink"
            )

        if apply:
            try:
                candidate.unlink()
            except OSError as exc:
                # Counted only once it is really gone.
                print(f"[ERROR] cannot remove {candidate}: {exc}",
                      file=sys.stderr)
                errors += 1
                continue
        swept.append(candidate)
        print(f"[{label}{'' if apply else ' — would remove'}] "
              f"{candidate.relative_to(root)}")
    return swept, errors


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(Path.home() / "cc-archives"),
                        help="Archive root to normalise (default: ~/cc-archives).")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default: dry-run report only).")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    if not root.is_dir():
        parser.error(f"root not found: {root}")

    # Recorded before any work, so the sweep below can tell an abandoned
    # temporary from one this run is about to create.
    started_at = time.time()
    swept_temps, n_temp_err = sweep_stale_temporaries(
        root, started_at, apply=args.apply
    )
    n_stale_temp = len(swept_temps)

    n_raw_only = n_dual_same = n_dual_prefix = n_divergent = n_ok = 0
    # Seeded with the sweep's failures, so a temporary that could not be
    # removed reaches the summary AND the exit status (finding L2).
    n_err = n_temp_err
    n_stale_meta = 0
    for meta_path in sorted(root.rglob("session.meta.json")):
        d = meta_path.parent
        raw, gz = d / "session.jsonl", d / "session.jsonl.gz"
        try:
            if raw.exists() and gz.exists():
                raw_sha, raw_n = sha256_file(raw)
                gz_sha, gz_n = sha256_file(gz, decompress=True)
                if raw_sha == gz_sha:
                    n_dual_same += 1
                    print(f"[dual-identical] {d.relative_to(root)}")
                    if args.apply:
                        # Repoint BEFORE unlinking: see _repoint's docstring.
                        _repoint(meta_path, gz)
                        raw.unlink()
                elif raw_n > gz_n and is_prefix(gz, raw, shorter_gz=True, longer_gz=False):
                    n_dual_prefix += 1
                    print(f"[dual-raw-longer] {d.relative_to(root)} "
                          f"(gz is a {gz_n}-byte prefix of {raw_n}-byte raw — recompressing raw)")
                    if args.apply:
                        tmp = d / "session.jsonl.gz.tmp"
                        write_gz_verified(raw, tmp)
                        tmp.replace(gz)
                        _repoint(meta_path, gz)
                        raw.unlink()
                elif gz_n > raw_n and is_prefix(raw, gz, shorter_gz=False, longer_gz=True):
                    n_dual_prefix += 1
                    print(f"[dual-gz-longer] {d.relative_to(root)} "
                          f"(raw is a {raw_n}-byte prefix of {gz_n}-byte gz — deleting raw)")
                    if args.apply:
                        _repoint(meta_path, gz)
                        raw.unlink()
                else:
                    n_divergent += 1
                    print(f"[DIVERGENT — untouched] {d.relative_to(root)} "
                          f"raw={raw_n}B gz={gz_n}B")
            elif raw.exists():
                n_raw_only += 1
                print(f"[raw-only] {d.relative_to(root)}")
                if args.apply:
                    # Stage the compression, exactly as the dual-raw-longer
                    # branch above does. Writing straight to session.jsonl.gz
                    # meant a kill mid-write left a partial .gz beside the
                    # raw: every later run then read that entry as dual-form,
                    # found the truncated gz neither identical to nor a
                    # prefix relationship with the raw, called it DIVERGENT,
                    # and exited 1 forever without ever converging (audit
                    # round 4c-2, finding 9).
                    tmp = d / "session.jsonl.gz.tmp"
                    write_gz_verified(raw, tmp)
                    tmp.replace(gz)
                    _repoint(meta_path, gz)
                    raw.unlink()
            elif gz.exists() and not _meta_points_at_gz(meta_path):
                # gz on disk, raw gone, metadata still naming session.jsonl:
                # the state a run interrupted between the unlink and the
                # repoint used to leave behind, which the old "already
                # canonical" branch then reported as fine forever. A re-run
                # now finishes the job (AR9).
                n_stale_meta += 1
                print(f"[stale-meta — repointing] {d.relative_to(root)}")
                if args.apply:
                    _repoint(meta_path, gz)
            else:
                n_ok += 1
        except Exception as exc:  # noqa: BLE001 — report, continue, non-zero exit
            n_err += 1
            print(f"[ERROR] {d.relative_to(root)}: {exc}", file=sys.stderr)

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n{mode}: raw-only={n_raw_only} dual-identical={n_dual_same} "
          f"dual-prefix={n_dual_prefix} divergent={n_divergent} "
          f"stale-meta={n_stale_meta} stale-temp={n_stale_temp} "
          f"already-canonical={n_ok} errors={n_err}")
    return 1 if (n_err or n_divergent) else 0


def _meta_points_at_gz(meta_path: Path) -> bool:
    """True when the metadata already names ``session.jsonl.gz``.

    An unreadable meta answers ``True``: this predicate only gates an extra
    repair pass, and a meta we cannot parse is not one to rewrite blind.
    """
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        return True
    archive = meta.get("archive") or {}
    return archive.get("jsonl_path") == "session.jsonl.gz"


def _repoint(meta_path: Path, gz_path: Path) -> None:
    """Rewrite the meta's archive block to the canonical gz form.

    **Called BEFORE the raw file is unlinked, and written atomically.** Two
    ordering defects lived here until 2026-09-08 (audit finding AR9):

    * ``raw.unlink()`` ran first, so a failure in this function left the raw
      transcript deleted, the gz written, and the metadata still naming
      ``session.jsonl``. The next run saw gz-only, called it already
      canonical, exited 0 — and the entry stayed broken forever.
    * the write was a bare ``write_text``, so a crash mid-write truncated the
      metadata. A session with no parseable meta is a session with no id,
      which drops it out of every archived-ids set and re-arms both drift
      gates on a session that is in fact archived.

    Repointing first inverts the failure: an interrupted run leaves the raw
    file in place beside the gz, which is the dual-form state this pass
    already knows how to finish. Nothing is ever deleted before the record
    that replaces it is safely on disk.
    """
    meta = json.loads(meta_path.read_text())
    meta["archive"] = gz_meta_block(meta, gz_path)
    tmp = meta_path.with_name(meta_path.name + ".tmp")
    tmp.write_text(json.dumps(meta, indent=2) + "\n")
    tmp.replace(meta_path)


if __name__ == "__main__":
    raise SystemExit(main())
