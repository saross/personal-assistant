#!/usr/bin/env python3
"""
Deterministic validator for generated session metadata.

Checks machine-verifiable properties of session-metadata JSON — the kind of
defect that needs no model to catch, and that no model should be trusted to
catch reliably. Built 2026-07-28 after a four-arm bake-off in which **every**
arm produced at least one defect, and three of five distinct defect classes
turned out to be checkable by code alone:

- a wrong ``project`` tag (makes a session unfindable in its own project),
- an empty ``provenance_summary`` with provenance prose misfiled into
  ``process_summary`` (a field swap plus a dropped field),
- a missing project tag entirely.

The remaining two classes — a factual contradiction between arms, and
in-session work described as prior context — genuinely need a reader with the
transcript. Those belong to a later LLM-verifier stage. **This script is
deliberately the cheap half: it runs in milliseconds, costs nothing, and is
worth shipping before any verifier because it catches the defects that make
retrieval fail outright.**

Design stance: **report, never mutate.** The validator's output is evidence for
a human or a downstream stage; it does not rewrite metadata. Every finding
carries the concrete value that failed so it can be checked by hand.

Severity levels
---------------
``error``    Retrieval-breaking or schema-violating. A session with an error
             may be unfindable or malformed downstream.
``warning``  Quality problem that degrades retrieval without breaking it
             (weak tags, unverifiable identifiers).
``info``     Observations worth surfacing but not defects.

Usage
-----
    validate-session-metadata.py --responses-dir DIR [--manifest FILE]
                                 [--report OUT.json] [--fail-on error|warning]

``--responses-dir`` holds one subdirectory per arm (``luna/``, ``gemini/``, …),
each containing ``<session_id>.json``. Without ``--manifest`` the project-tag
and identifier checks that need per-session ground truth are skipped and
reported as such — the script never silently downgrades a check to a pass.

Exit status is 1 when findings at or above ``--fail-on`` exist (default:
``error``), so it can gate a pipeline.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Fields every metadata record must carry, with the nested three_ps block
#: flattened as ``three_ps.<name>``.
REQUIRED_FIELDS: tuple[str, ...] = (
    "title",
    "purpose",
    "tags",
    "three_ps.prompt_summary",
    "three_ps.process_summary",
    "three_ps.provenance_summary",
)

#: Tags that match almost any session and therefore carry no retrieval value.
#: Observed in the 2026-07-28 bake-off: "markdown", "git", "python", "pytest".
#: A tag here is a warning, not an error — it is dead weight, not a defect.
GENERIC_TAG_DENYLIST: frozenset[str] = frozenset({
    "markdown", "git", "python", "javascript", "typescript", "json", "yaml",
    "bash", "shell", "code", "coding", "development", "documentation", "docs",
    "file", "files", "text", "data", "analysis", "research", "work", "task",
    "pytest", "testing", "tests", "logging", "log-analysis", "refactor",
})

#: Sensible tag-count band. Too few and the session is hard to find; too many
#: and each tag's discriminating power falls.
TAG_COUNT_MIN, TAG_COUNT_MAX = 2, 6

#: A bare hex run of 7-40 chars, the shape of an abbreviated or full git SHA.
#: Deliberately loose: false positives are cheap (verification just fails to
#: resolve and downgrades to "unverifiable"), whereas a missed confabulated
#: hash is exactly the defect this exists to catch.
COMMIT_RE = re.compile(r"\b([0-9a-f]{7,40})\b")

#: Absolute or clearly-relative paths with a file extension. Requires a slash,
#: so prose words with full stops are not mistaken for filenames.
PATH_RE = re.compile(r"(?:^|[\s`'\"(])((?:~|\.{0,2})?/[\w.\-/]+\.\w{1,6})\b")

#: Hex strings that are almost certainly prose or identifiers, not commits.
#: "added", "decade", "façade" etc. tokenise as valid hex.
HEX_WORD_ALLOWLIST: frozenset[str] = frozenset({
    "added", "decade", "defaced", "effaced", "accede", "acceded", "beaded",
    "deface", "efface", "facade", "decafe", "cabbed", "dabbed",
})


@dataclass
class Finding:
    """One validation result against one session's metadata."""

    arm: str
    session_id: str
    check: str
    severity: str
    message: str
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the JSON report."""
        return {
            "arm": self.arm,
            "session_id": self.session_id,
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "value": self.value,
        }


@dataclass
class SessionTruth:
    """Ground truth about one session, from the manifest.

    Without this the project-tag check has nothing to compare against, so the
    validator reports the check as *skipped* rather than passing it.
    """

    session_id: str
    project: str | None = None
    repo_path: Path | None = None
    aliases: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------


def load_truth(manifest_path: Path | None) -> dict[str, SessionTruth]:
    """Build per-session ground truth from the bake-off manifest.

    Returns an empty mapping when no manifest is supplied; callers must treat
    a missing entry as "cannot check", never as "check passed".
    """
    if manifest_path is None or not manifest_path.exists():
        return {}
    manifest = json.loads(manifest_path.read_text())
    truth: dict[str, SessionTruth] = {}
    for entry in manifest.get("sessions", []):
        project = entry.get("project")
        # Candidate repo for commit-hash verification. Only a real git
        # directory is used; anything else leaves hashes unverifiable rather
        # than falsely failing them.
        repo = None
        for candidate in (
            Path.home() / "Code" / (project or ""),
            Path.home() / (project or ""),
        ):
            if (candidate / ".git").exists():
                repo = candidate
                break
        aliases = {project} if project else set()
        # The consolidation of map-reader-llm and vlm-burial-mound-detection
        # (2026-07-28) means older metadata may legitimately carry either name.
        if project == "map-reader-llm":
            aliases.add("vlm-burial-mound-detection")
        truth[entry["session_id"]] = SessionTruth(
            session_id=entry["session_id"],
            project=project,
            repo_path=repo,
            aliases={a for a in aliases if a},
        )
    return truth


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _get(record: dict[str, Any], dotted: str) -> Any:
    """Fetch a possibly-nested field by dotted path, or None."""
    node: Any = record
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def check_schema(arm: str, sid: str, record: dict[str, Any]) -> list[Finding]:
    """Every required field present, correctly typed, and non-empty.

    Catches the observed field-swap defect from the other side: when
    provenance prose was misfiled into ``process_summary``, the real
    ``provenance_summary`` was left as an empty string. An emptiness check
    finds that without needing to understand either field's content.
    """
    out: list[Finding] = []
    for dotted in REQUIRED_FIELDS:
        value = _get(record, dotted)
        if value is None:
            out.append(Finding(arm, sid, "schema", "error",
                               f"required field missing: {dotted}"))
        elif isinstance(value, str) and not value.strip():
            out.append(Finding(arm, sid, "schema", "error",
                               f"required field present but empty: {dotted}"))
        elif dotted == "tags" and not isinstance(value, list):
            out.append(Finding(arm, sid, "schema", "error",
                               "tags must be a list", type(value).__name__))
    return out


def check_field_swap(arm: str, sid: str, record: dict[str, Any]) -> list[Finding]:
    """Heuristic: prose that belongs in one field appearing in another.

    Deliberately conservative — it fires only when a *sibling field is empty*
    as well, which is the signature of a genuine swap rather than an
    incidental turn of phrase. A summary that merely mentions "this session
    continues…" is not flagged if provenance is also populated.
    """
    out: list[Finding] = []
    process = (_get(record, "three_ps.process_summary") or "").strip()
    provenance = (_get(record, "three_ps.provenance_summary") or "").strip()
    provenance_markers = ("continues the", "belongs to", "follows ", "part of the",
                          "resolves a known", "builds on")
    if not provenance and process:
        if any(marker in process.lower() for marker in provenance_markers):
            out.append(Finding(
                arm, sid, "field-swap", "error",
                "provenance_summary is empty while process_summary reads as "
                "provenance — fields appear swapped",
                process[:160],
            ))
    return out


def check_tags(
    arm: str, sid: str, record: dict[str, Any], truth: SessionTruth | None,
    known_projects: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Tag hygiene, plus the project-tag correctness check.

    Tags are the retrieval keys, so this is the highest-value check in the
    file: a session tagged with the wrong project is effectively invisible in
    the project it belongs to.
    """
    out: list[Finding] = []
    tags = _get(record, "tags")
    if not isinstance(tags, list):
        return out  # already reported by check_schema
    normalised = [str(t).strip().lower() for t in tags]

    if not TAG_COUNT_MIN <= len(normalised) <= TAG_COUNT_MAX:
        out.append(Finding(arm, sid, "tag-count", "warning",
                           f"tag count {len(normalised)} outside "
                           f"{TAG_COUNT_MIN}-{TAG_COUNT_MAX}", normalised))

    duplicates = [t for t, n in Counter(normalised).items() if n > 1]
    if duplicates:
        out.append(Finding(arm, sid, "tag-duplicate", "warning",
                           "duplicate tags", duplicates))

    generic = sorted(set(normalised) & GENERIC_TAG_DENYLIST)
    if generic:
        out.append(Finding(arm, sid, "tag-generic", "warning",
                           "tags match almost any session and add no "
                           "retrieval value", generic))

    mangled = [t for t in normalised if "/" in t or t.endswith(".md") or " " in t]
    if mangled:
        out.append(Finding(arm, sid, "tag-mangled", "warning",
                           "tags look path- or sentence-derived", mangled))

    # Project mis-tagging — the defect that motivated this script.
    #
    # NOTE the asymmetry, which was corrected 2026-07-28 after the first run:
    # a *missing* project tag is NOT a defect. Project is already a structured
    # field on the archive entry, so retrieval filters on that; spending one of
    # 2-6 tag slots restating it is waste, and the upgrade plan's C1 item
    # explicitly bans "project-name echoes". The real defect is a tag naming a
    # DIFFERENT project than the session's, which actively misfiles the session
    # into a project it does not belong to. An over-strict "must tag its own
    # project" rule reported 6 findings on the bake-off, 5 of which were
    # well-tagged sessions that simply (correctly) omitted the echo.
    if truth is None or not truth.project:
        out.append(Finding(arm, sid, "tag-project", "info",
                           "cross-project tag check skipped (no ground truth)"))
    else:
        own = {a.lower() for a in truth.aliases}
        foreign = sorted((set(normalised) & known_projects) - own)
        if foreign:
            out.append(Finding(
                arm, sid, "tag-project", "error",
                f"tags name a different project than the session's "
                f"({truth.project}) — misfiles the session",
                foreign,
            ))
    return out


def _iter_text(record: dict[str, Any]) -> list[str]:
    """All free-text fields, for identifier extraction."""
    texts = [str(record.get("title") or ""), str(record.get("purpose") or "")]
    three_ps = record.get("three_ps")
    if isinstance(three_ps, dict):
        texts.extend(str(v) for v in three_ps.values() if isinstance(v, str))
    return texts


def check_commits(
    arm: str, sid: str, record: dict[str, Any], truth: SessionTruth | None
) -> list[Finding]:
    """Verify any commit-shaped hex string resolves in the session's repo.

    A cited commit hash is a genuinely valuable anchor — and a genuinely
    dangerous one if invented, because it reads as precision. Resolution is by
    ``git cat-file -e``, which is exact and cheap.

    A hash that cannot be *checked* (no repo on this machine) is reported as
    ``warning``, not ``error`` — absence of a repo is not evidence of
    confabulation, and conflating the two would train readers to ignore the
    check.
    """
    out: list[Finding] = []
    candidates: set[str] = set()
    for text in _iter_text(record):
        for match in COMMIT_RE.findall(text):
            if match not in HEX_WORD_ALLOWLIST and not match.isdigit():
                candidates.add(match)
    if not candidates:
        return out
    if truth is None or truth.repo_path is None:
        out.append(Finding(arm, sid, "commit", "warning",
                           "commit-shaped strings present but no local repo to "
                           "verify against", sorted(candidates)))
        return out
    for sha in sorted(candidates):
        result = subprocess.run(
            ["git", "-C", str(truth.repo_path), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
        )
        if result.returncode != 0:
            out.append(Finding(
                arm, sid, "commit", "error",
                f"cited commit does not resolve in {truth.repo_path.name}",
                sha,
            ))
    return out


def check_paths(arm: str, sid: str, record: dict[str, Any]) -> list[Finding]:
    """Verify cited file paths exist.

    Reported as ``warning``: a path can be legitimately absent because the file
    was since renamed, deleted, or lives on another machine. The signal is
    still worth having — a cluster of non-existent paths in one record is a
    strong confabulation indicator even when any single miss is innocent.
    """
    out: list[Finding] = []
    missing: list[str] = []
    for text in _iter_text(record):
        for raw in PATH_RE.findall(text):
            path = Path(raw).expanduser()
            if not path.is_absolute():
                continue  # relative paths have no unambiguous base — skip
            if not path.exists():
                missing.append(raw)
    if missing:
        out.append(Finding(arm, sid, "path", "warning",
                           "cited absolute paths do not exist on this machine",
                           sorted(set(missing))))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_record(
    arm: str, sid: str, record: dict[str, Any], truth: SessionTruth | None,
    known_projects: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Run every check against one metadata record."""
    if "error" in record:
        return [Finding(arm, sid, "generation", "info",
                        "arm produced no output for this session",
                        str(record["error"])[:120])]
    findings: list[Finding] = []
    findings += check_schema(arm, sid, record)
    findings += check_field_swap(arm, sid, record)
    findings += check_tags(arm, sid, record, truth, known_projects)
    findings += check_commits(arm, sid, record, truth)
    findings += check_paths(arm, sid, record)
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic validator for generated session metadata."
    )
    parser.add_argument("--responses-dir", required=True, type=Path,
                        help="Directory containing one subdirectory per arm.")
    parser.add_argument("--manifest", type=Path,
                        help="Sample manifest supplying per-session ground truth. "
                             "Without it, project-tag and commit checks are "
                             "reported as skipped rather than passed.")
    parser.add_argument("--report", type=Path,
                        help="Write the full findings list as JSON.")
    parser.add_argument("--fail-on", choices=("error", "warning"), default="error",
                        help="Exit non-zero when findings at or above this "
                             "severity exist (default: error).")
    args = parser.parse_args()

    truth = load_truth(args.manifest)
    # Every project name the corpus knows about — the vocabulary against which
    # a "foreign project" tag is recognised. Drawn from the archive so it
    # covers projects absent from this particular manifest.
    archive_root = Path.home() / "cc-archives"
    known_projects = frozenset(
        {t.project.lower() for t in truth.values() if t.project}
        | ({p.name.lower() for p in archive_root.iterdir()
            if p.is_dir() and not p.name.startswith("_")}
           if archive_root.exists() else set())
    )
    if not truth:
        print("NOTE: no manifest supplied — project-tag and commit checks "
              "will be reported as skipped, not passed.\n")

    findings: list[Finding] = []
    per_arm: dict[str, int] = defaultdict(int)
    for arm_dir in sorted(p for p in args.responses_dir.iterdir() if p.is_dir()):
        arm = arm_dir.name
        for path in sorted(arm_dir.glob("*.json")):
            if path.name.startswith("_") or path.name.startswith("dry-run"):
                continue
            sid = path.stem
            try:
                record = json.loads(path.read_text())
            except ValueError as exc:
                findings.append(Finding(arm, sid, "parse", "error",
                                        f"file is not valid JSON: {exc}"))
                continue
            per_arm[arm] += 1
            findings.extend(
                validate_record(arm, sid, record, truth.get(sid), known_projects)
            )

    # --- report -----------------------------------------------------------
    by_sev = Counter(f.severity for f in findings)
    print(f"Validated {sum(per_arm.values())} records across {len(per_arm)} arms")
    print(f"Findings: {by_sev['error']} error, {by_sev['warning']} warning, "
          f"{by_sev['info']} info\n")

    grid: dict[str, Counter] = defaultdict(Counter)
    for f in findings:
        grid[f.arm][f.severity] += 1
    print(f"{'arm':<12}{'records':>8}{'error':>8}{'warning':>9}{'info':>7}")
    for arm in sorted(per_arm):
        g = grid[arm]
        print(f"{arm:<12}{per_arm[arm]:>8}{g['error']:>8}{g['warning']:>9}"
              f"{g['info']:>7}")

    errors = [f for f in findings if f.severity == "error"]
    if errors:
        print("\n--- ERRORS ---")
        for f in errors:
            val = f" | {f.value}" if f.value is not None else ""
            print(f"  [{f.arm}] {f.session_id[:8]} {f.check}: {f.message}{val}")

    warnings = [f for f in findings if f.severity == "warning"]
    if warnings:
        print(f"\n--- WARNINGS ({len(warnings)}) ---")
        for f in warnings[:20]:
            val = f" | {f.value}" if f.value is not None else ""
            print(f"  [{f.arm}] {f.session_id[:8]} {f.check}: {f.message}{val}")
        if len(warnings) > 20:
            print(f"  … {len(warnings) - 20} more (see --report)")

    if args.report:
        args.report.write_text(json.dumps(
            {"summary": dict(by_sev), "per_arm": {a: dict(g) for a, g in grid.items()},
             "findings": [f.as_dict() for f in findings]}, indent=1) + "\n")
        print(f"\nFull report: {args.report}")

    threshold = {"error": ("error",), "warning": ("error", "warning")}[args.fail_on]
    return 1 if any(f.severity in threshold for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
