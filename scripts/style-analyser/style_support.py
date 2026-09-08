#!/usr/bin/env python3
"""
style_support.py — shared, standard-library-only helpers for the
``scripts/style-analyser/`` tranche.

Three jobs, all of them audit findings from the 2026-09-08 repository audit:

1. **Atomic output writing.** Every script in the tranche wrote its JSON and
   Markdown outputs with a plain ``Path.write_text``. An interrupted run
   (Ctrl-C, a full disk, an OOM kill) therefore left a truncated file that the
   NEXT stage happily parsed as if it were complete. ``atomic_write_text``
   writes to a temporary file in the destination directory and then
   ``os.replace``s it into position, so a reader sees either the previous
   version or the new one and never a half-written one.

2. **Dry runs.** Each writer now takes ``--dry-run``; passing ``dry_run=True``
   here makes the write a no-op that reports "nothing written" to its caller,
   so an operator can inspect what a script WOULD do against production paths
   without touching them.

3. **Provenance.** No output in the tranche recorded what produced it — no
   script name, no git commit, no input hashes, no seed, no spaCy model
   version — so a results file could not be tied back to the code and inputs
   that made it. ``provenance_block`` assembles that record.

   Deliberately **no timestamp**: a wall-clock field would make every re-run
   differ byte-for-byte, and byte-identical re-runs are the cheapest available
   determinism check (several tests in this tranche assert exactly that). Time
   of generation is recoverable from the file's own mtime and from the commit.

A fourth, smaller job: ``sanity_verdict`` holds the Phase 5 validation
report's pure decision rule. Phase 5 imports numpy, scipy and scikit-learn at
module scope, none of which are installed in this repository's virtual
environment, so nothing inside it can be tested here. Lifting the rule into
this standard-library-only module keeps the *decision* under test even where
the *distance computation* is not.

This module imports nothing outside the standard library and makes no network
call.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Read size for hashing. Corpus JSON runs to a few megabytes; a fixed buffer
#: keeps the memory cost flat regardless.
_HASH_CHUNK_BYTES = 1 << 20


def atomic_write_text(path: Path | str, text: str, *, dry_run: bool = False,
                      encoding: str = "utf-8") -> bool:
    """Write ``text`` to ``path`` atomically; return whether bytes were written.

    The write goes to a temporary file in the destination's own directory (so
    the final ``os.replace`` is a same-filesystem rename, which is atomic) and
    is flushed and fsync-ed before the rename. A caller that is interrupted
    part-way therefore leaves the previous version of ``path`` intact, and
    never a truncated file for the next stage to misread.

    With ``dry_run`` set, nothing is created — not the file, not its parent
    directories — and the return value is ``False``.
    """
    if dry_run:
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp",
    )
    try:
        with os.fdopen(handle_fd, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Includes KeyboardInterrupt: the whole point is that an interrupted
        # write leaves no debris and no half-written destination.
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return True


def atomic_write_json(path: Path | str, payload: Any, *, dry_run: bool = False,
                      indent: int = 2, ensure_ascii: bool = False) -> bool:
    """Serialise ``payload`` and write it through :func:`atomic_write_text`.

    A trailing newline is added so the file is a well-formed text file (and so
    ``git diff`` does not report "no newline at end of file").
    """
    text = json.dumps(payload, indent=indent, ensure_ascii=ensure_ascii) + "\n"
    return atomic_write_text(path, text, dry_run=dry_run)


def file_sha256(path: Path | str) -> str | None:
    """Return the hex SHA-256 of ``path``, or ``None`` if it cannot be read.

    ``None`` rather than an exception: provenance is a diagnostic, and a
    missing optional input must not abort a run that is otherwise valid.
    """
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def git_commit(repo_hint: Path | str | None = None) -> str | None:
    """Return the HEAD commit of the repository containing ``repo_hint``.

    ``repo_hint`` defaults to this file's own directory, so a script run from
    any working directory still records the commit of the code that ran.
    Returns ``None`` when git is unavailable, the directory is not a
    repository, or the call fails for any other reason — provenance is
    best-effort and must never break a run.
    """
    start = Path(repo_hint) if repo_hint is not None else Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    commit = proc.stdout.strip()
    return commit or None


def provenance_block(script: str,
                     inputs: Iterable[Path | str] = (),
                     *,
                     seed: int | None = None,
                     spacy_model: str | None = None,
                     extra: Mapping[str, Any] | None = None) -> dict:
    """Assemble the ``provenance`` block embedded in every output file.

    ``inputs`` are hashed in the order given, each recorded as its path (as
    the caller named it, so a relative invocation stays legible) and its
    SHA-256 — enough to prove which bytes a result was derived from.

    Contains no wall-clock field, on purpose: see the module docstring.
    """
    record: dict[str, Any] = {
        "script": script,
        "git_commit": git_commit(),
        "inputs": [
            {"path": str(item), "sha256": file_sha256(item)} for item in inputs
        ],
    }
    if seed is not None:
        record["seed"] = seed
    if spacy_model is not None:
        record["spacy_model"] = spacy_model
    if extra:
        record.update(dict(extra))
    return record


def sanity_verdict(distance: float, loo_max: float, loo_median: float,
                   is_corpus: bool) -> tuple[str, bool]:
    """Return ``(rendered_verdict, ok)`` for one Phase 5 sanity sample.

    Two kinds of sample are checked, in opposite directions:

    * a held-out **corpus** paper must land within the corpus's own
      leave-one-out (LOO) range, so ``distance <= loo_max`` passes;
    * an off-register **fixture** must land farther out than every corpus
      paper, so only ``distance > loo_max`` passes.

    The second rule is the audit fix (finding ST12). The report used to render
    a fixture at or below ``loo_max`` as "NOT farther ✗" while leaving the
    overall verdict True unless the fixture also fell below the LOO *median* —
    so the footer could say PASS over a table saying the metric had failed to
    separate foreign text from the corpus. The stricter ``loo_median`` case is
    still reported, but as a note; it can no longer be the only thing that
    turns the verdict False.
    """
    if is_corpus:
        if distance <= loo_max:
            return "within", True
        return "ABOVE (unexpected)", False
    if distance > loo_max:
        return "farther ✓", True
    if distance <= loo_median:
        return "NOT farther ✗ (inside the LOO median)", False
    return "NOT farther ✗", False


def hash_inputs(paths: Sequence[Path | str]) -> dict[str, str | None]:
    """Map each path (as given) to its SHA-256, for ad-hoc provenance use."""
    return {str(p): file_sha256(p) for p in paths}
