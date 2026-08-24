#!/usr/bin/env python3
"""Validate and exercise ownership denial cases declared in ownership.toml."""

from __future__ import annotations

import argparse
import errno
import glob
import json
import os
from pathlib import Path
import sys
import tomllib


DENIAL_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}
CASE_OPERATIONS = {"create": "write", "open-write": "write", "read": "read"}
ENFORCEMENT_LAYERS = {"os", "tool-layer"}


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

    return policy


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
