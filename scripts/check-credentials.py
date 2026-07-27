#!/usr/bin/env python3
"""Read-only health check for the credentials in ~/personal-assistant/.env.

Three passes, cheapest first:

1. **Name hygiene.** Every variable name must match ``[A-Z0-9_]+``. Hyphenated
   or lowercase names are not valid shell identifiers, so ``set -a && . .env``
   parses the line as a *command* and bash echoes the whole word — including
   the secret — to stderr. ``~/.claude/settings.json`` sources this file in
   session hooks, so a malformed line re-leaks on every hook run. This
   happened twice: 2026-05-22 (at a prompt, key rotated) and 2026-07-27
   (in .env, caught before any hook fired).

   Note the audit trap: listing names with a *name-shaped* pattern such as
   ``^[A-Za-z_0-9]+=`` silently skips the malformed lines you are looking
   for. Anchor on the ``=`` instead — ``^[^=]+=`` — as this script does.

2. **Shell-source test.** Sources the file in a subshell; any output at all
   is a finding.

3. **Live reads.** Reports each Zotero key's true scope from
   ``/keys/current``, checks the library and group IDs resolve, checks every
   ``*_COLLECTION`` key against the personal library and all accessible
   groups, and confirms the OSF token authenticates.

Nothing is written, created, or deleted, and no secret value is ever printed
(only its length, where useful). Run it after editing .env, and on each
machine after syncing credentials.

Usage:
    python3 scripts/check-credentials.py
    python3 scripts/check-credentials.py --env /path/to/.env

Exit codes:
    0 — everything checked out
    1 — one or more findings (malformed name, failed auth, unresolvable id)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

VALID_NAME = re.compile(r"^[A-Z0-9_]+$")
ZOTERO_API = "https://api.zotero.org"
OSF_API = "https://api.osf.io/v2"
TIMEOUT = 45

findings: list[str] = []


def note(msg: str) -> None:
    """Record a finding and print it inline."""
    findings.append(msg)
    print(f"  FINDING: {msg}")


def parse_env(path: pathlib.Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, anchoring on '=' so malformed names are visible."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([^=]+)=(.*)$", line)
        if not m:
            continue
        name, value = m.group(1).strip(), m.group(2).strip().strip('"').strip("'")
        out[name] = value
        if not VALID_NAME.match(name):
            note(
                f"line {lineno}: variable name {name!r} is not a valid shell "
                f"identifier — bash will echo this line, secret and all, "
                f"every time the file is sourced. Rename to [A-Z0-9_] only."
            )
    return out


def http_json(url: str, headers: dict[str, str]) -> tuple[int, object]:
    """GET a URL and return (status, parsed body or error text)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200].decode("utf-8", "replace")
    except Exception as exc:  # network, timeout, malformed JSON
        return 0, str(exc)


def zotero_headers(key: str) -> dict[str, str]:
    return {"Zotero-API-Key": key, "Zotero-API-Version": "3"}


def check_shell_source(path: pathlib.Path) -> None:
    """Source the file in a subshell; any output is a parse failure."""
    print("\n== Shell-source test ==")
    result = subprocess.run(
        ["bash", "-c", f"set -a; . {path}; set +a"],
        capture_output=True, text=True,
    )
    combined = (result.stdout + result.stderr).strip()
    if combined:
        # Never echo the captured text: on a malformed line it contains the secret.
        note(
            f"sourcing {path.name} produced {len(combined.splitlines())} line(s) of "
            "output (suppressed — it would contain the secret). Fix the names above."
        )
    else:
        print("  silent — all names parse as assignments")


def check_zotero(env: dict[str, str]) -> None:
    print("\n== Zotero keys (scope from /keys/current) ==")
    key_vars = sorted(n for n in env if n.startswith("ZOTERO_API_KEY_"))
    if not key_vars:
        print("  none present")
        return

    library_id = env.get("ZOTERO_LIBRARY_ID")
    group_id = env.get("ZOTERO_GROUP_ID")
    reader = None

    for name in key_vars:
        status, body = http_json(f"{ZOTERO_API}/keys/current", zotero_headers(env[name]))
        if status != 200 or not isinstance(body, dict):
            note(f"{name}: authentication failed ({status})")
            continue
        reader = reader or env[name]
        access = body.get("access", {})
        user_access = access.get("user", {})
        groups = access.get("groups", {})
        writable = sorted(g for g, p in groups.items() if p.get("write"))
        print(f"  {name}: OK (user {body.get('userID')})")
        print(f"      personal: {'read+write' if user_access.get('write') else 'read only' if user_access else 'no access'}")
        print(f"      group write: {writable or 'none'}")
        if "all" in writable:
            note(
                f"{name} holds write access to ALL groups. If its name implies a "
                "single target, narrow the key to just that group."
            )
        if library_id and str(body.get("userID")) != library_id:
            note(f"{name}: userID {body.get('userID')} != ZOTERO_LIBRARY_ID {library_id}")

    if not reader:
        return

    print("\n== Library and group ids ==")
    for var, path in (("ZOTERO_LIBRARY_ID", "users"), ("ZOTERO_GROUP_ID", "groups")):
        ident = env.get(var)
        if not ident:
            continue
        status, body = http_json(
            f"{ZOTERO_API}/{path}/{ident}/items?limit=1", zotero_headers(reader))
        if status == 200:
            print(f"  {var}={ident}: readable")
        else:
            note(f"{var}={ident}: read failed ({status})")

    # Resolve every collection key, searching the personal library then all groups.
    print("\n== Collection keys ==")
    status, groups = http_json(
        f"{ZOTERO_API}/users/{library_id}/groups?limit=100", zotero_headers(reader))
    group_list = groups if status == 200 and isinstance(groups, list) else []
    for name in sorted(n for n in env if n.endswith("_COLLECTION")):
        ckey = env[name]
        where = None
        if library_id:
            st, body = http_json(
                f"{ZOTERO_API}/users/{library_id}/collections/{ckey}",
                zotero_headers(reader))
            if st == 200 and isinstance(body, dict):
                where = ("personal library", body)
        if where is None:
            for grp in group_list:
                st, body = http_json(
                    f"{ZOTERO_API}/groups/{grp['id']}/collections/{ckey}",
                    zotero_headers(reader))
                if st == 200 and isinstance(body, dict):
                    where = (f"group {grp['id']} ({grp['data']['name']})", body)
                    break
        if where is None:
            note(f"{name}={ckey}: not found in the personal library or any group")
        else:
            location, body = where
            print(f"  {name}={ckey}: {body['data']['name']!r} "
                  f"({body['meta'].get('numItems', '?')} items) in {location}")


def check_osf(env: dict[str, str]) -> None:
    print("\n== OSF ==")
    token = env.get("OSF_API_KEY")
    if not token:
        note("OSF_API_KEY absent — scripts/osf-manifest.py and wiki publishing will fail")
        return
    status, body = http_json(f"{OSF_API}/users/me/", {"Authorization": f"Bearer {token}"})
    if status == 200 and isinstance(body, dict):
        attrs = body["data"]["attributes"]
        print(f"  OSF_API_KEY: OK — {attrs.get('full_name')!r} (id {body['data']['id']})")
    else:
        note(f"OSF_API_KEY: authentication failed ({status})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env", type=pathlib.Path,
        default=pathlib.Path.home() / "personal-assistant/.env",
        help="path to the .env file (default: ~/personal-assistant/.env)")
    args = parser.parse_args()

    if not args.env.is_file():
        print(f"No .env at {args.env}", file=sys.stderr)
        return 1

    print(f"Checking {args.env}\n")
    print("== Name hygiene ==")
    env = parse_env(args.env)
    if not findings:
        print(f"  all {len(env)} names valid")

    check_shell_source(args.env)
    check_zotero(env)
    check_osf(env)

    print("\n" + "=" * 60)
    if findings:
        print(f"{len(findings)} finding(s):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("No findings — credentials are consistent and all reads succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
