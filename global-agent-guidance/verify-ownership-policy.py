#!/usr/bin/env python3
"""Validate and exercise ownership denial cases declared in ownership.toml."""

from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import sys
import tomllib


DENIAL_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}


def load_policy(path: Path) -> dict:
    with path.open("rb") as handle:
        policy = tomllib.load(handle)

    if policy.get("schema_version") != 1:
        raise ValueError("unsupported ownership policy schema")

    rules = policy.get("denials", [])
    cases = policy.get("verification_cases", [])
    rule_ids = [rule.get("id") for rule in rules]
    case_ids = [case.get("id") for case in cases]

    if None in rule_ids or len(rule_ids) != len(set(rule_ids)):
        raise ValueError("denial rule ids must be present and unique")
    if None in case_ids or len(case_ids) != len(set(case_ids)):
        raise ValueError("verification case ids must be present and unique")

    known_rules = set(rule_ids)
    tested_rules = set()
    for case in cases:
        if case.get("rule_id") not in known_rules:
            raise ValueError(f"unknown rule for case {case.get('id')}")
        if case.get("operation") not in {"create", "open-write"}:
            raise ValueError(f"unsupported operation for case {case.get('id')}")
        if case.get("expected") != "deny":
            raise ValueError(f"case {case.get('id')} must expect deny")
        tested_rules.add(case["rule_id"])

    missing = known_rules - tested_rules
    if missing:
        raise ValueError(f"denial rules without verification cases: {sorted(missing)}")

    return policy


def cases_for(policy: dict, agent: str) -> list[dict]:
    return [case for case in policy["verification_cases"] if case["agent"] == agent]


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def attempt(case: dict) -> tuple[bool, str]:
    path = expand_path(case["path"])
    operation = case["operation"]

    if operation == "create":
        if path.exists() or path.is_symlink():
            return False, f"preflight failed: scratch path already exists: {path}"
        if not path.parent.is_dir():
            return False, f"preflight failed: parent directory is absent: {path.parent}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    else:
        if not path.is_file():
            return False, f"preflight failed: target file is absent: {path}"
        flags = os.O_WRONLY

    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        if error.errno in DENIAL_ERRNOS:
            return True, f"denied by OS ({error.strerror})"
        return False, f"unexpected OS error {error.errno}: {error.strerror}"

    os.close(descriptor)
    if operation == "create":
        path.unlink(missing_ok=True)
    return False, "write unexpectedly succeeded"


def main() -> int:
    default_policy = Path(__file__).with_name("ownership.toml")
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "list", "attempt"))
    parser.add_argument("--agent", choices=("claude", "codex"))
    parser.add_argument("--policy", type=Path, default=default_policy)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    policy = load_policy(args.policy)
    if args.command == "validate":
        print(
            f"valid schema={policy['schema_version']} "
            f"rules={len(policy['denials'])} "
            f"cases={len(policy['verification_cases'])}"
        )
        return 0

    if not args.agent:
        parser.error("--agent is required for list and attempt")

    cases = cases_for(policy, args.agent)
    if args.command == "list":
        if args.json:
            print(json.dumps(cases, indent=2))
        else:
            for case in cases:
                print(
                    "\t".join(
                        (
                            case["id"],
                            case["operation"],
                            str(expand_path(case["path"])),
                            case["expected"],
                        )
                    )
                )
        return 0

    failures = 0
    for case in cases:
        passed, detail = attempt(case)
        result = "PASS" if passed else "FAIL"
        print(f"{result}\t{case['id']}\t{expand_path(case['path'])}\t{detail}")
        failures += not passed
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
