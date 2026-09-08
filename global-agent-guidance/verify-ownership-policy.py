#!/usr/bin/env python3
"""Validate and exercise ownership denial cases declared in ownership.toml.

Also validates any ``[[admitted_clones]]`` entries (plan §3, "Codex Git
lanes", ruled 2026-09-07): an admission is the only thing that makes a lane's
Git metadata writable for an agent, so every field is checked against the
layout and semantics the policy declares before a renderer may act on it.
"""

from __future__ import annotations

import argparse
from datetime import date
import errno
import glob
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tomllib
from urllib.parse import unquote, urlsplit


DENIAL_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}
CASE_OPERATIONS = {"create": "write", "open-write": "write", "read": "read"}
ENFORCEMENT_LAYERS = {"os", "tool-layer"}
ADMISSION_AUTHORITY = "shawn"
REQUIRED_CLONE_FIELDS = (
    "id", "agent", "repository", "lane_path", "remote", "branch_namespace",
    "storage", "clone_mode", "admitted_on", "admitted_by",
)
LANE_PARENT = "~/worktrees"


def rule_denies(rule: dict, agent: str, operation: str) -> bool:
    if operation not in rule.get("operations", []):
        return False
    denied_agent = rule.get("denied_agent")
    if denied_agent is not None and denied_agent != agent:
        return False
    return rule.get("owner") != agent


def load_policy(path: Path) -> dict:
    with path.open("rb") as handle:
        policy = tomllib.load(handle)

    if policy.get("schema_version") != 2:
        raise ValueError("unsupported ownership policy schema")
    home_owned = policy.get("semantics", {}).get("home_repository_owned_globs", [])
    if "scripts/**" not in home_owned:
        raise ValueError("agent home repositories must own scripts/** by default")

    agents = policy.get("agents", [])
    agent_ids = [agent.get("id") for agent in agents]
    if None in agent_ids or len(agent_ids) != len(set(agent_ids)):
        raise ValueError("agent ids must be present and unique")
    for agent in agents:
        if not agent.get("name") or not agent.get("home_repository"):
            raise ValueError(f"agent {agent.get('id')} must declare name and home_repository")

    rules = policy.get("denials", [])
    cases = policy.get("verification_cases", [])
    rule_ids = [rule.get("id") for rule in rules]
    case_ids = [case.get("id") for case in cases]

    if None in rule_ids or len(rule_ids) != len(set(rule_ids)):
        raise ValueError("denial rule ids must be present and unique")
    if None in case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("verification case ids must be present and unique")

    known_agents = set(agent_ids)
    known_owners = known_agents | {"shawn"}
    rules_by_id = {rule["id"]: rule for rule in rules}
    for rule in rules:
        owner = rule.get("owner")
        if owner not in known_owners:
            raise ValueError(f"unknown owner for rule {rule['id']}: {owner}")
        narrowed = rule.get("denied_agent")
        if narrowed is not None and narrowed not in known_agents:
            raise ValueError(f"unknown denied_agent for rule {rule['id']}: {narrowed}")
        if narrowed == owner:
            raise ValueError(f"rule {rule['id']} cannot deny its owner")
        operations = set(rule.get("operations", []))
        if not operations or not operations <= {"read", "write"}:
            raise ValueError(f"unsupported operations for rule {rule['id']}")
        if not rule.get("path_globs") and not rule.get("repo_relative_globs"):
            raise ValueError(f"rule {rule['id']} declares no paths")

    tested_rules = set()
    for case in cases:
        rule_id = case.get("rule_id")
        if rule_id not in rules_by_id:
            raise ValueError(f"unknown rule for case {case.get('id')}")
        operation = case.get("operation")
        if operation not in CASE_OPERATIONS:
            raise ValueError(f"unsupported operation for case {case.get('id')}")
        if case.get("expected") != "deny":
            raise ValueError(f"case {case.get('id')} must expect deny")
        if case.get("enforcement") not in ENFORCEMENT_LAYERS:
            raise ValueError(f"unsupported enforcement layer for case {case.get('id')}")
        agent = case.get("agent")
        if agent not in known_agents:
            raise ValueError(f"unknown agent for case {case.get('id')}: {agent}")
        if not case.get("path"):
            raise ValueError(f"case {case.get('id')} must declare a path")
        if not rule_denies(rules_by_id[rule_id], agent, CASE_OPERATIONS[operation]):
            raise ValueError(f"case {case.get('id')} is not denied by rule {rule_id}")
        tested_rules.add(rule_id)

    missing = set(rules_by_id) - tested_rules
    if missing:
        raise ValueError(f"denial rules without verification cases: {sorted(missing)}")

    validate_admitted_clones(policy)
    return policy


def canonical_home_path(value: str) -> PurePosixPath:
    """Reject lexical aliases and traversal without consulting live paths.

    Canonical spellings keep duplicate and home-repository checks meaningful.
    Symlinks and actual Git identity still require renderer-time validation.
    """
    path = PurePosixPath(value)
    if (
        not value.startswith("~/") or value != path.as_posix()
        or ".." in path.parts or len(path.parts) < 2
        or not value.isascii() or not value.isprintable() or " " in value
    ):
        # ASCII-printable only: zero-width and bidirectional-override
        # characters would otherwise pass as canonical look-alikes.
        raise ValueError("admitted clone paths must be canonical and home-relative")
    return path


def validate_clone_remote(value: str) -> None:
    """Require a usable HTTPS repository URL with no embedded credentials."""
    try:
        remote = urlsplit(value)
        port = remote.port
        raw_segments = [part for part in remote.path.split("/") if part]
        decoded_segments = [part for part in unquote(remote.path).split("/") if part]
        valid = (
            remote.scheme == "https" and bool(remote.hostname)
            and bool(remote.path.strip("/"))
            and remote.username is None and remote.password is None
            and not remote.query and not remote.fragment
            and (port is None or port > 0)
            and value.isascii() and value.isprintable() and " " not in value
            # Percent-encoding may not add path separators or traversal:
            # %2F would name a different repository once decoded.
            and len(decoded_segments) == len(raw_segments)
            and ".." not in decoded_segments
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "admitted clone remote must be an HTTPS repository URL without credentials"
        )


def validate_admitted_clones(policy: dict) -> None:
    """Check every admitted-clone entry against the declared lane semantics.

    The renderer on the Codex side grants a lane's ``.git`` only from these
    entries, so a malformed entry must fail here, at policy-validation time,
    rather than surface as a wrong grant. Nothing on disk is consulted: the
    acceptance run in the plan covers the live checks (a real ``.git``
    directory, no external git-dir, no alternates).
    """
    semantics = policy.get("semantics", {})
    entries = policy.get("admitted_clones", [])
    if not isinstance(entries, list):
        raise ValueError("admitted_clones must be a list of tables")
    if not entries:
        return
    required = semantics.get("admitted_clone_required_fields")
    # The declared list may not shrink below what this validator reads, or a
    # trimmed policy would either skip checks or crash on a missing key.
    if required is not None and not set(REQUIRED_CLONE_FIELDS) <= set(required):
        raise ValueError("admitted_clone_required_fields omits fields the verifier needs")
    storage = semantics.get("admitted_clone_storage")
    clone_modes = set(semantics.get("admitted_clone_clone_modes", []))
    if not required or not storage or not clone_modes:
        raise ValueError("admitted clones declared without admitted_clone_* semantics")

    agents = {agent["id"]: agent for agent in policy.get("agents", [])}
    seen_ids: set[str] = set()
    seen_lanes: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("admitted clone entries must be tables")
        if any(not isinstance(entry.get(field), str) for field in required):
            raise ValueError("admitted clone fields must be non-empty strings")
        ident = entry.get("id")
        if not ident or ident in seen_ids:
            raise ValueError(f"admitted clone ids must be present and unique: {ident}")
        seen_ids.add(ident)
        absent = [field for field in required if not entry.get(field)]
        if absent:
            raise ValueError(f"admitted clone {ident} is missing {absent}")

        agent = agents.get(entry["agent"])
        if agent is None:
            raise ValueError(f"admitted clone {ident} names unknown agent {entry['agent']}")
        prefix = agent["name"].lower()

        repository = entry["repository"]
        lane = entry["lane_path"]
        if not repository.startswith("~/") or not lane.startswith(f"{LANE_PARENT}/"):
            raise ValueError(f"admitted clone {ident}: paths must be home-relative")
        repository_path = canonical_home_path(repository)
        lane_path = canonical_home_path(lane)
        repo_name = repository_path.name
        parts = lane_path.parts
        # Expected shape: ~ / worktrees / <repo> / <agent>-<workstream>
        if len(parts) != 4 or parts[2] != repo_name or not parts[3].startswith(f"{prefix}-"):
            raise ValueError(
                f"admitted clone {ident}: lane_path must be "
                f"{LANE_PARENT}/{repo_name}/{prefix}-<workstream>"
            )
        if len(parts[3]) <= len(prefix) + 1:
            raise ValueError(f"admitted clone {ident}: lane needs a workstream name")
        if lane in seen_lanes:
            raise ValueError(f"admitted clone {ident}: lane_path admitted twice")
        seen_lanes.add(lane)
        home = agent["home_repository"]
        if repository_path == canonical_home_path(home):
            raise ValueError(
                f"admitted clone {ident}: the agent's home repository needs no lane"
            )

        validate_clone_remote(entry["remote"])
        # Repository identity is judged downstream by directory basename (the
        # renderer's carve-out projection and the Codex hook's
        # ~/worktrees/<repo>/ rule). Tie that basename to the remote's
        # repository name so a clone of one repository cannot be admitted
        # under another repository's name and escape its carve-outs.
        # Decode and case-fold the remote name: GitHub resolves Personal-Assistant
        # and personal%2Dassistant to the same repository, and consumers key on
        # the canonical lowercase directory name (Codex-side review of #112).
        remote_name = (
            PurePosixPath(unquote(urlsplit(entry["remote"]).path))
            .name.casefold().removesuffix(".git")
        )
        if remote_name != repo_name.casefold():
            # Case-folded on both sides: consumers fold too, so a directory
            # spelt Map-Reader-LLM with a matching remote is admissible.
            raise ValueError(
                f"admitted clone {ident}: repository basename {repo_name!r} must equal "
                f"the remote's repository name {remote_name!r} (case-insensitive)"
            )
        try:
            admitted_date = date.fromisoformat(entry["admitted_on"])
        except ValueError:
            raise ValueError("admitted_on must be a calendar date") from None
        if admitted_date.isoformat() != entry["admitted_on"]:
            raise ValueError("admitted_on must use YYYY-MM-DD")
        if entry["branch_namespace"] != f"{prefix}/*":
            raise ValueError(f"admitted clone {ident}: branch_namespace must be {prefix}/*")
        if entry["storage"] != storage:
            raise ValueError(f"admitted clone {ident}: storage must be {storage}")
        if entry["clone_mode"] not in clone_modes:
            raise ValueError(
                f"admitted clone {ident}: clone_mode must be one of {sorted(clone_modes)}"
            )
        if entry["admitted_by"] != ADMISSION_AUTHORITY:
            raise ValueError(f"admitted clone {ident}: admitted_by must be {ADMISSION_AUTHORITY}")


def cases_for(policy: dict, agent: str) -> list[dict]:
    known_agents = {entry["id"] for entry in policy["agents"]}
    if agent not in known_agents:
        raise ValueError(f"unknown agent: {agent}; choose from {sorted(known_agents)}")
    return [case for case in policy["verification_cases"] if case["agent"] == agent]


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def resolve_case_path(case: dict) -> Path:
    expanded = str(expand_path(case["path"]))
    if not glob.has_magic(expanded):
        return Path(expanded)
    matches = sorted(Path(match) for match in glob.glob(expanded))
    if not matches:
        return Path(expanded)
    return matches[-1]


def attempt(case: dict) -> tuple[bool, str, Path]:
    path = resolve_case_path(case)
    operation = case["operation"]

    if operation == "create":
        if path.exists() or path.is_symlink():
            return False, f"preflight failed: scratch path already exists: {path}", path
        if not path.parent.is_dir():
            return False, f"preflight failed: parent directory is absent: {path.parent}", path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    elif operation == "open-write":
        if not path.is_file():
            return False, f"preflight failed: target file is absent: {path}", path
        flags = os.O_WRONLY
    else:
        if not path.is_file():
            return False, f"preflight failed: target file is absent: {path}", path
        flags = os.O_RDONLY

    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        if error.errno in DENIAL_ERRNOS:
            return True, f"denied by OS ({error.strerror})", path
        return False, f"unexpected OS error {error.errno}: {error.strerror}", path

    os.close(descriptor)
    if operation == "create":
        path.unlink(missing_ok=True)
    return False, f"{CASE_OPERATIONS[operation]} unexpectedly succeeded", path


def main() -> int:
    default_policy = Path(__file__).with_name("ownership.toml")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "list", "attempt"))
    parser.add_argument("--agent")
    parser.add_argument("--policy", type=Path, default=default_policy)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        policy = load_policy(args.policy)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))

    if args.command == "validate":
        layers = {layer: 0 for layer in sorted(ENFORCEMENT_LAYERS)}
        for case in policy["verification_cases"]:
            layers[case["enforcement"]] += 1
        print(
            f"valid schema={policy['schema_version']} "
            f"rules={len(policy['denials'])} "
            f"cases={len(policy['verification_cases'])} "
            f"clones={len(policy.get('admitted_clones', []))} "
            + " ".join(f"{layer}={count}" for layer, count in layers.items())
        )
        return 0

    if not args.agent:
        parser.error("--agent is required for list and attempt")
    try:
        cases = cases_for(policy, args.agent)
    except ValueError as error:
        parser.error(str(error))

    if args.command == "list":
        if args.json:
            print(json.dumps(cases, indent=2))
        else:
            for case in cases:
                print(
                    "\t".join(
                        (
                            case["id"],
                            case["enforcement"],
                            case["operation"],
                            str(expand_path(case["path"])),
                            case["expected"],
                        )
                    )
                )
        return 0

    failures = 0
    for case in cases:
        if case["enforcement"] == "tool-layer":
            print(
                f"CHECKLIST\t{case['id']}\t{case['operation']}\t"
                f"{expand_path(case['path'])}\t"
                f"{case['agent']} must exercise its tool layer and record denial"
            )
            continue
        passed, detail, path = attempt(case)
        result = "PASS" if passed else "FAIL"
        print(f"{result}\t{case['id']}\t{path}\t{detail}")
        failures += not passed
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
