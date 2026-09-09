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
import inspect
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

#: Read size for hashing. Corpus JSON runs to a few megabytes; a fixed buffer
#: keeps the memory cost flat regardless.
_HASH_CHUNK_BYTES = 1 << 20

#: The repository root, derived from this file (``<root>/scripts/
#: style-analyser/``) rather than from ``~`` or the working directory, so a
#: worktree or a differently named checkout resolves correctly.
PA_ROOT = Path(__file__).resolve().parents[2]

#: THE phase 1 results file. Several scripts each had their own idea of where
#: it lives, and one of them (``validate_announce_colon.py``) defaulted to a
#: path that has never existed — ``<corpus-dir>/analysis/phase1-results.json``
#: — so it silently reported every rate as unavailable. One constant, so a
#: relocation is one edit.
PHASE1_RESULTS_DEFAULT = (
    PA_ROOT / "data" / "style-corpus" / "phase1-results-clean.json"
)

#: The version of the METRIC DEFINITIONS phase 1 emits. Bumped whenever a
#: metric changes meaning under a name that stays the same — which is exactly
#: what happened in the 2026-09 audit: hapax_ratio moved from tokens to types,
#: passive_ratio from per-verb to presence-per-sentence, the nominalisation
#: rate onto the alphabetic token count, and mattr_100 to None below its
#: window. A results file written before that change looks identical to one
#: written after it, so a consumer measuring an input with the new code and
#: comparing it against an old corpus file gets numbers that cannot be
#: compared — silently. Version 1 is anything unstamped.
METRIC_SCHEMA_VERSION = 2

#: What version 2 means, recorded in the file itself so a reader of an
#: archived result does not have to find this constant.
METRIC_SCHEMA_DEFINITIONS = (
    "hapax_ratio over word TYPES; passive_ratio as the fraction of sentences "
    "carrying a passive; nominalisation_per_1000w over alphabetic tokens; "
    "mattr_100 null below its 100-word window; NFC-normalised input"
)


#: The efficacy experiment's root. Every path below is derived from it at
#: CALL time, not frozen at import, so a test (or an operator with a second
#: experiment) repoints one base and both the writer and the reader follow.
#: They did not, once: the builder moved the unblinding key under `private/`
#: and the scorer's default stayed a directory up, so a run at the defaults
#: could not find a key that was exactly where it belonged.
EXPERIMENT_DEFAULT = (
    PA_ROOT / "data" / "experiments" / "style-efficacy-2026-05-31"
)


def experiment_root(root: Path | str | None = None) -> Path:
    """Return the experiment root, defaulting to ``EXPERIMENT_DEFAULT``."""
    return Path(root) if root is not None else EXPERIMENT_DEFAULT


def judge_dir(root: Path | str | None = None) -> Path:
    """The directory handed to the judges. Nothing else may live here."""
    return experiment_root(root) / "judge-tasks"


def private_dir(root: Path | str | None = None) -> Path:
    """The directory no judge is ever pointed at."""
    return experiment_root(root) / "private"


def passages_dir(root: Path | str | None = None) -> Path:
    """The generated passages the judge tasks are built from."""
    return experiment_root(root) / "passages"


def judge_key_dir(root: Path | str | None = None) -> Path:
    """Where the unblinding key is written, and where it is read from."""
    return private_dir(root) / "judge-key"


def load_checked_payloads(
        paths: Sequence[Path | str]) -> tuple[list[dict] | None, str | None]:
    """Load every phase file, refusing BEFORE returning any of them.

    Returns ``(payloads, None)`` when every path exists, parses, and carries
    the current metric-definition stamp, and ``(None, message)`` otherwise —
    never a partial list. A caller that holds payloads therefore holds
    checked ones, by construction.

    This exists because the check's position was previously enforced only by
    reading the source: an assertion that the stamp loop appears before the
    first consuming call passes just as happily when the loop is hoisted into
    a nested function called afterwards, wrapped in an environment-variable
    condition, or given an empty iterable. None of those could be caught by
    running the code either, because both consumers import numpy at module
    scope and neither executes in this repository's virtual environment. The
    sequence is a single stdlib-only call instead, so it is testable here on
    its own terms, and a consumer cannot reach a payload around it.
    """
    payloads: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            return None, f"Input not found: {path}"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return None, f"{path}: could not be read as JSON ({exc})"
        if not isinstance(payload, dict):
            return None, (f"{path}: expected a JSON object, found "
                          f"{type(payload).__name__}")
        stale = metric_schema_error(payload, path)
        if stale:
            return None, stale
        payloads.append(payload)
    return payloads, None


def metric_schema_stamp() -> dict:
    """Return the stamp phase 1 writes into its results file."""
    return {
        "version": METRIC_SCHEMA_VERSION,
        "definitions": METRIC_SCHEMA_DEFINITIONS,
    }


def metric_schema_error(payload: dict, source: Path | str) -> str | None:
    """Return a refusal message when ``payload`` predates the current metrics.

    ``None`` means the file is safe to use. Every consumer of a phase 1
    results file calls this immediately after loading it: comparing an input
    measured with today's definitions against a corpus measured with
    yesterday's produces a number with no meaning, and nothing else in the
    pipeline can detect it.
    """
    stamp = payload.get("metric_schema")
    found = stamp.get("version") if isinstance(stamp, dict) else None
    if found == METRIC_SCHEMA_VERSION:
        return None
    described = "absent" if found is None else repr(found)
    return (
        f"{source}: metric_schema version is {described}, but this code "
        f"requires version {METRIC_SCHEMA_VERSION}. The file was measured "
        "with superseded metric definitions "
        f"({METRIC_SCHEMA_DEFINITIONS}), so its numbers are not comparable "
        "with anything measured now. Re-run phase1_pipeline.py over the "
        "corpus, then re-run the stages that depend on it."
    )


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


def _git(args: list[str], cwd: Path) -> str | None:
    """Run one read-only git command in ``cwd``; return stdout, or ``None``.

    ``None`` covers every failure — git absent, not a repository, a non-zero
    exit — because provenance is best-effort and must never break a run.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def git_state(path_hint: Path | str | None = None) -> dict[str, Any]:
    """Describe the repository that actually contains the running code.

    Returns ``{"commit": str | None, "dirty": bool | None, "root": str | None,
    "reason": str | None}``; ``reason`` says why there is no commit.

    The search is BOUNDED to the repository that tracks ``path_hint`` itself.
    ``git rev-parse HEAD`` walks upwards, so a copy of these scripts placed
    anywhere beneath another checkout used to report THAT checkout's HEAD —
    provenance then named a commit which does not contain, and says nothing
    about, the code that ran. The file must be tracked by the repository whose
    commit is recorded, or nothing is recorded.

    ``dirty`` reports uncommitted changes to TRACKED files (untracked files
    are ignored: they are not part of the recorded code). A dirty tree means
    the commit alone does not identify what ran, which is exactly what a
    reader of a provenance block needs to know.
    """
    target = Path(path_hint) if path_hint is not None else Path(__file__)
    target = target.resolve()
    directory = target if target.is_dir() else target.parent

    root = _git(["rev-parse", "--show-toplevel"], directory)
    if root is None:
        return {"commit": None, "dirty": None, "root": None,
                "reason": "not inside a git repository"}
    if not target.is_dir():
        tracked = _git(["ls-files", "--error-unmatch", str(target)], directory)
        if tracked is None:
            return {"commit": None, "dirty": None, "root": root,
                    "reason": f"{target.name} is not tracked by the repository "
                              f"at {root}; its HEAD describes other code"}
    commit = _git(["rev-parse", "HEAD"], directory)
    if not commit:
        return {"commit": None, "dirty": None, "root": root,
                "reason": "the repository has no commits"}
    status = _git(["status", "--porcelain", "--untracked-files=no"], directory)
    return {"commit": commit, "dirty": bool(status), "root": root,
            "reason": None}


def git_commit(path_hint: Path | str | None = None) -> str | None:
    """Return the HEAD commit of the repository that TRACKS ``path_hint``.

    Defaults to this file, so a script run from any working directory records
    the commit of the code that ran — and records nothing at all when the
    running copy is not tracked by the repository it happens to sit inside.
    """
    return git_state(path_hint)["commit"]


def _calling_script() -> Path | None:
    """Return the ``__file__`` of the caller's caller, if it has one.

    Used so ``provenance_block`` describes the repository state of the SCRIPT
    that is producing the output, rather than of ``style_support`` itself.
    Returns ``None`` for a caller with no file (an interactive session, or
    code exec'd from a string), which the caller treats as "no path hint".
    """
    frame = inspect.currentframe()
    try:
        # currentframe -> _calling_script's caller (provenance_block) -> the
        # script that called it.
        outer = frame.f_back.f_back if frame and frame.f_back else None
        path = outer.f_globals.get("__file__") if outer else None
        return Path(path) if path else None
    finally:
        del frame


def provenance_block(script: str,
                     inputs: Iterable[Path | str] = (),
                     *,
                     seed: int | None = None,
                     spacy_model: str | None = None,
                     script_path: Path | str | None = None,
                     extra: Mapping[str, Any] | None = None) -> dict:
    """Assemble the ``provenance`` block embedded in every output file.

    ``inputs`` are hashed in the order given, each recorded as its path (as
    the caller named it, so a relative invocation stays legible) and its
    SHA-256 — enough to prove which bytes a result was derived from.

    ``git_dirty`` says whether the recorded commit is the whole story: a
    result produced from a modified working tree is not reproducible from the
    commit alone.

    Contains no wall-clock field, on purpose: see the module docstring.

    ``script_path`` is the file whose repository state is recorded. It
    defaults to the CALLER's ``__file__``, because the commit that matters is
    the one containing the script that produced the output. This used to call
    ``git_state()`` with no argument, which always described *this* module —
    so the "the file must be tracked by the repository whose commit is
    recorded" branch was unreachable for every caller, and a brand-new,
    uncommitted script recorded a clean commit that does not contain it
    (round 4g-4, item L3).

    Raises ValueError if ``extra`` would overwrite a field the block itself
    owns — silently replacing ``inputs`` or ``git_commit`` with a caller's
    value would make provenance say something the writer did not mean.
    """
    hint = script_path if script_path is not None else _calling_script()
    if hint is None:
        # No ``__file__`` on the caller: exec'd source, ``python -c``, or an
        # interactive session. Falling through to git_state()'s own default
        # would describe THIS module and hand back a commit that says nothing
        # about the code that ran — the very bug item L3 fixed, re-entered by
        # the back door (round 4g-5, item L-c1).
        state = {"commit": None, "dirty": None, "root": None,
                 "reason": "the calling script has no __file__ (exec'd "
                           "source, python -c, or an interactive session), "
                           "so no repository state describes it"}
    else:
        state = git_state(hint)
    record: dict[str, Any] = {
        "script": script,
        "git_commit": state["commit"],
        "git_dirty": state["dirty"],
        "inputs": [
            {"path": str(item), "sha256": file_sha256(item)} for item in inputs
        ],
    }
    if state["reason"]:
        record["git_note"] = state["reason"]
    if seed is not None:
        record["seed"] = seed
    if spacy_model is not None:
        record["spacy_model"] = spacy_model
    if extra:
        clashes = sorted(set(extra) & set(record))
        if clashes:
            raise ValueError(
                f"provenance extra may not overwrite {clashes}: those fields "
                "describe the run itself, not the caller's metadata"
            )
        record.update(dict(extra))
    return record


def is_measured(value: Any) -> bool:
    """True when ``value`` is a real measurement, not ``None`` and not a bool.

    ``isinstance(True, int)`` is True in Python, so a bare numeric check lets
    a boolean through as 1.0 or 0.0 and silently fabricates a measurement.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def impute_missing_features(values: Sequence[Any], labels: Sequence[str],
                            fallbacks: Sequence[float]
                            ) -> tuple[list[float], list[str]]:
    """Replace unmeasurable features with a neutral value; say which.

    Phase 1 reports ``None`` for a metric it could not measure on a given
    input — ``mattr_100`` below its 100-word window, for instance. The Phase 5
    input vector had no guard for that (the corpus matrix did), so ANY input
    shorter than one MATTR window raised ``TypeError`` deep inside numpy,
    before the short-input warning that exists to explain exactly this case.

    Each missing value is replaced by its ``fallbacks`` entry — the corpus
    MEAN for that feature, which standardises to z = 0 and so contributes
    nothing to the Mahalanobis distance. That is the honest choice: it says
    "no evidence from this feature" rather than inventing a value that would
    push the input toward or away from the corpus. The returned label list
    names every feature imputed, for the caller to record in its output.

    Raises ValueError if the three sequences do not line up, since a
    mis-aligned fallback would impute one feature's mean into another.
    """
    if not (len(values) == len(labels) == len(fallbacks)):
        raise ValueError(
            f"impute_missing_features got {len(values)} values, "
            f"{len(labels)} labels and {len(fallbacks)} fallbacks; the three "
            "must be parallel or a fallback lands on the wrong feature"
        )
    vector: list[float] = []
    imputed: list[str] = []
    for value, label, fallback in zip(values, labels, fallbacks):
        if is_measured(value):
            vector.append(float(value))
        else:
            vector.append(float(fallback))
            imputed.append(label)
    return vector, imputed


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
