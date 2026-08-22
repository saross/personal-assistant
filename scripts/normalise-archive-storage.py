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
import shutil
import sys
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

    n_raw_only = n_dual_same = n_dual_prefix = n_divergent = n_ok = n_err = 0
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
                        raw.unlink()
                        _repoint(meta_path, gz)
                elif raw_n > gz_n and is_prefix(gz, raw, shorter_gz=True, longer_gz=False):
                    n_dual_prefix += 1
                    print(f"[dual-raw-longer] {d.relative_to(root)} "
                          f"(gz is a {gz_n}-byte prefix of {raw_n}-byte raw — recompressing raw)")
                    if args.apply:
                        tmp = d / "session.jsonl.gz.tmp"
                        write_gz_verified(raw, tmp)
                        shutil.move(tmp, gz)
                        raw.unlink()
                        _repoint(meta_path, gz)
                elif gz_n > raw_n and is_prefix(raw, gz, shorter_gz=False, longer_gz=True):
                    n_dual_prefix += 1
                    print(f"[dual-gz-longer] {d.relative_to(root)} "
                          f"(raw is a {raw_n}-byte prefix of {gz_n}-byte gz — deleting raw)")
                    if args.apply:
                        raw.unlink()
                        _repoint(meta_path, gz)
                else:
                    n_divergent += 1
                    print(f"[DIVERGENT — untouched] {d.relative_to(root)} "
                          f"raw={raw_n}B gz={gz_n}B")
            elif raw.exists():
                n_raw_only += 1
                print(f"[raw-only] {d.relative_to(root)}")
                if args.apply:
                    write_gz_verified(raw, gz)
                    raw.unlink()
                    _repoint(meta_path, gz)
            else:
                n_ok += 1
        except Exception as exc:  # noqa: BLE001 — report, continue, non-zero exit
            n_err += 1
            print(f"[ERROR] {d.relative_to(root)}: {exc}", file=sys.stderr)

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"\n{mode}: raw-only={n_raw_only} dual-identical={n_dual_same} "
          f"dual-prefix={n_dual_prefix} divergent={n_divergent} "
          f"already-canonical={n_ok} errors={n_err}")
    return 1 if (n_err or n_divergent) else 0


def _repoint(meta_path: Path, gz_path: Path) -> None:
    """Rewrite the meta's archive block to the canonical gz form."""
    meta = json.loads(meta_path.read_text())
    meta["archive"] = gz_meta_block(meta, gz_path)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
