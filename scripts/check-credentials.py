#!/usr/bin/env python3
"""Read-only health check for the credentials in ~/personal-assistant/.env.

Three passes, cheapest first:

1. **Name hygiene.** Every variable name must match ``[A-Z_][A-Z0-9_]*``. Hyphenated
   or lowercase names are not valid shell identifiers, so ``set -a && . .env``
   parses the line as a *command* and bash echoes the whole word — including
   the secret — to stderr. ``~/.claude/settings.json`` sources this file in
   session hooks, so a malformed line re-leaks on every hook run. This
   happened twice: 2026-05-22 (at a prompt, key rotated) and 2026-07-27
   (in .env, caught before any hook fired).

   Note the audit trap: listing names with a *name-shaped* pattern such as
   ``^[A-Za-z_0-9]+=`` silently skips the malformed lines you are looking
   for. Anchor on the ``=`` instead — ``^[^=]+=`` — as this script does.

   Whitespace is checked on **both** sides of the ``=``, because the two
   sides fail differently. ``NAME =value`` makes bash echo the variable
   *name*; ``NAME= value`` and ``NAME=a b`` make bash run part of the
   *value* as a command, so the secret itself reaches stderr. The latter
   forms are the worse leak, and they were invisible to this script until
   2026-09-08.

   Pass 1 also reports four ways a line can parse differently in bash than
   in the Codex launcher's literal parser, each verified against bash 5.2:
   an opening quote that does not close the value; a ``$`` outside single
   quotes (bash expands it, to nothing for an unset name, so the process
   gets no credential while the file looks populated); a trailing backslash
   (bash treats it as a line continuation and swallows the next line,
   leaving that variable unset); and a line ending bash reads differently
   from this parser — CRLF keeps the carriage return as the last character
   of the value, while a lone CR is not a line break to bash at all, so it
   reads the whole file as one line and leaves every name after the first
   unset.

   Pass 1 finally reports the shell metacharacters, because a credential
   file is sourced by every session hook: an unquoted ``&``, ``;`` or ``|``
   ends the assignment and runs the rest as a command (``A=https://x?a=1&b=2``
   leaves A UNSET), and a backtick or ``$(`` outside single quotes EXECUTES
   when the file is sourced — double quotes do not stop that one.

2. **Shell-source test.** Sources the file in a subshell; any output at all
   is a finding.

3. **Live reads.** Reports each Zotero key's true scope from
   ``/keys/current``, checks the library and group IDs resolve, checks every
   ``*_COLLECTION`` key against the personal library and all accessible
   groups, confirms the OSF token authenticates, and confirms every GitHub
   token (``GH_TOKEN``, ``GITHUB_TOKEN``, ``*_GH_TOKEN``) authenticates —
   reporting the account, token kind, expiry, and whether it can push to
   ``saross/gpt-hub``, the first repository a Codex-side token must reach.

4. **Grant cross-check.** Every grant in
   ``global-agent-guidance/credential-grants.toml`` must name a variable
   that exists in .env, so the Codex launcher never injects an empty value,
   and its recorded ``expires_on`` must match the live token: ``"none"`` for
   a token rotated by hand, otherwise the date GitHub reports. A grant whose
   token expires within 14 days is a finding.

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
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request

VALID_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# One line plus its terminator. Group 2 is "" only for a final line with no
# terminator at all, so the three endings stay distinguishable (audit L1).
_LINE_SPLIT = re.compile(r"([^\r\n]*)(\r\n|\r|\n|$)")
ZOTERO_API = "https://api.zotero.org"
OSF_API = "https://api.osf.io/v2"
GITHUB_API = "https://api.github.com"
# The first repository any Codex-side GitHub token must be able to push to.
GITHUB_PROBE_REPO = "saross/gpt-hub"
GRANTS_FILE = pathlib.Path(__file__).resolve().parent.parent / (
    "global-agent-guidance/credential-grants.toml")
EXPIRY_WARNING_DAYS = 14
TIMEOUT = 45

findings: list[str] = []


def note(msg: str) -> None:
    """Record a finding and print it inline."""
    findings.append(msg)
    print(f"  FINDING: {msg}")


def parse_env(path: pathlib.Path) -> dict[str, str]:
    """Parse KEY=VALUE lines, anchoring on '=' so malformed names are visible."""
    out: dict[str, str] = {}
    # Read as BYTES and decode by hand: text mode translates ``\r\n`` to
    # ``\n``, and ``splitlines()`` would then strip what is left, which is why
    # the CRLF divergence went unreported (audit round two M4). Splitting on
    # ``\r\n|\r|\n`` rather than ``\n`` alone keeps a legacy CR-only file
    # parsing line by line — splitting on ``\n`` collapsed it into one "line"
    # and reported the wrong names (audit round two L1) — while ``term`` still
    # says which ending each line actually had.
    data = path.read_bytes()
    text = data.decode("utf-8")
    for lineno, match in enumerate(_LINE_SPLIT.finditer(text), start=1):
        raw, term = match.group(1), match.group(2)
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([^=]+)=(.*)$", line)
        if not m:
            continue
        raw_name, raw_value_field = m.group(1), m.group(2)
        raw_value = raw_value_field.strip()
        name = raw_name.strip()
        # "Quoted" must mean the quote CLOSES the value, not merely that the
        # value opens with one (audit round two, 2026-09-08). For
        # ``TOKEN='abc' # trailing comment`` bash assigns ``abc`` while this
        # parser keeps ``abc' # trailing comment`` — a genuine divergence, and
        # the old ``raw_value[:1] in ('"', "'")`` test suppressed the very
        # finding that would have surfaced it. A quote that does close the
        # value (``TOKEN="abc # inside"``) still exempts the '#' test, because
        # there both sides agree on ``abc # inside``. Verified against bash 5.
        quote_char = raw_value[:1] if raw_value[:1] in ('"', "'") else ""
        quoted = (
            bool(quote_char)
            and len(raw_value) >= 2
            and raw_value.endswith(quote_char)
        )
        value = raw_value[1:-1] if quoted else raw_value.strip('"').strip("'")
        out[name] = value
        if raw_name != name:
            # bash treats "NAME =value" as a command named NAME — the leak class
            # pass 1 exists to catch — so whitespace around the name is a finding.
            note(
                f"line {lineno}: whitespace around the name {name!r} — bash would run "
                "it as a command and echo the rest. Remove the spaces."
            )
        if value and raw_value_field[:1].isspace():
            # The worse half of the same defect, and invisible until
            # 2026-09-08 because the value was stripped before any test ran.
            # "NAME =value" makes bash echo the variable NAME; "NAME= value"
            # makes bash assign NAME the empty string for one command and then
            # RUN THE VALUE as that command, so the secret itself lands in
            # stderr ("<secret>: command not found"). Verified against bash 5.2.
            # ``line`` has already been stripped, so a value field that is only
            # whitespace cannot reach here: the ``value and`` conjunct is
            # UNREACHABLE through parse_env and is kept only as
            # defence-in-depth against a future refactor that drops that
            # strip. No test pins it, because no input can (audit round two).
            note(
                f"line {lineno}: whitespace after the '=' on {name!r} — bash sets "
                f"{name} empty and runs the value as a command, echoing the secret "
                "itself to stderr. Remove the space."
            )
        if not quoted:
            # Whitespace INSIDE an unquoted value is the same leak class:
            # verified against bash 5.2, ``A=a b`` assigns nothing to A, runs
            # ``b`` as a command, and echoes "b: command not found". A trailing
            # comment is a different problem, reported separately below, so a
            # second word beginning with '#' is excluded here.
            words = raw_value.split()
            if len(words) > 1 and not words[1].startswith("#"):
                note(
                    f"line {lineno}: {name}'s value contains whitespace and is not "
                    "quoted — bash assigns only the first word and runs the rest as "
                    "a command, echoing it to stderr. Quote the whole value."
                )
        if quote_char and not quoted:
            # An opening quote that does not close the value means bash and
            # this parser disagree about where the value ends: verified against
            # bash 5.2, ``TOKEN='abc' # c`` assigns ``abc`` in bash while the
            # parser keeps everything after the closing quote, and ``TOKEN='abc``
            # is an unterminated string the shell rejects outright.
            note(
                f"line {lineno}: the opening {quote_char} does not close {name}'s "
                "value — bash ends the value at the closing quote while the Codex "
                "launcher keeps everything after it. Quote the whole value or none."
            )
        # Command substitution runs BEFORE the assignment and double quotes do
        # NOT stop it. Verified against bash 5.2.37: ``A=`id` `` and
        # ``A=$(id)`` both EXECUTE id and assign its output, and so does
        # ``A="`id`"``; only single quotes make them literal. A credential
        # file is not a place for anything that executes.
        # ``literal`` means the WHOLE value is inside single quotes, which is
        # the only form bash leaves alone. Guarding on the opening quote alone
        # was a false negative (audit round three M1): ``A='abc'$(id)`` opens
        # with a single quote and still EXECUTES, because the quoted run ends
        # before the substitution begins. Verified against bash 5.2.37.
        literal = quoted and quote_char == "'"
        substitution = "`" in value or "$(" in value
        if not literal and substitution:
            note(
                f"line {lineno}: {name}'s value contains a command substitution "
                "(backtick or '$(') outside single quotes — bash EXECUTES it when "
                "the file is sourced and assigns the output. Single-quote the "
                "value, or remove it."
            )
        if not quoted:
            # Control operators terminate the assignment. Either quote form
            # protects them. Verified against bash 5.2.37:
            # ``A=https://x/y?z=1&w=2`` leaves A UNSET because '&' backgrounds
            # the assignment; ``A=a;b`` assigns 'a' and runs 'b'; ``A=a|b``
            # leaves A unset and runs 'b'. The URL is the form most likely to
            # appear in a real credential file.
            operators = sorted({char for char in "&;|" if char in raw_value})
            if operators:
                note(
                    f"line {lineno}: {name}'s value contains {', '.join(operators)} "
                    "and is not quoted — bash ends the assignment there and runs the "
                    f"rest as a command, often leaving {name} unset entirely. Quote "
                    "the whole value."
                )
        if not literal and "$" in value and not substitution:
            # bash expands ``$`` unless the value is single-quoted; this parser
            # and the Codex launcher keep it literal. Verified against bash 5.2:
            # ``A=$B`` and ``A="$B"`` both assign the EMPTY string for an unset
            # B, so the process gets no credential at all while the file looks
            # populated. ``A='$B'`` agrees on both sides and is not flagged,
            # but ``A='abc'$B`` expands to ``abc`` in bash and is (M1).
            note(
                f"line {lineno}: {name}'s value contains '$' outside single quotes "
                "— bash expands it (to nothing, for an unset name) while the Codex "
                "launcher keeps it literally. Single-quote the value."
            )
        if raw_value.endswith("\\"):
            # Verified against bash 5.2: ``A=x\`` followed by ``NEXT=y`` assigns
            # A the value "xNEXT=y" and leaves NEXT unset — a wrong secret AND a
            # silently missing variable, from one trailing character.
            note(
                f"line {lineno}: {name}'s value ends with a backslash — bash treats "
                "it as a line continuation and swallows the NEXT line into this "
                "value, leaving that variable unset. Remove or escape it."
            )
        if term == "\r\n":
            # Verified against bash 5.2: sourcing a CRLF file assigns "x\r" for
            # ``A=x``. Python's text-mode read hides this twice over, which is
            # why it went unreported until audit round two M4.
            note(
                f"line {lineno}: CRLF line ending — bash keeps the carriage return "
                f"as the last character of {name}'s value while this parser drops "
                "it. Convert the file to LF line endings."
            )
        elif term == "\r":
            # A lone CR is not a line ending to bash at all. Verified against
            # bash 5.2: a whole CR-only file is ONE line, so `A=1\rB=2\rC=3`
            # assigns A the entire rest of the file and leaves B and C unset.
            # This parser reads it line by line, so the two disagree about how
            # many variables the file even defines.
            note(
                f"line {lineno}: lone CR line ending — bash does not treat it as a "
                "line break, so it reads the whole file as ONE line: only the first "
                f"name is assigned (the rest of the file becomes its value) and "
                f"{name} may never be set at all. Convert the file to LF endings."
            )
        if not quoted and (" #" in value or value.startswith("#")):
            # bash sourcing drops an unquoted trailing comment; the Codex launcher
            # and this parser keep it as part of the value. One of them would
            # hand a process the wrong secret, so the line must be unambiguous.
            note(
                f"line {lineno}: {name} has a '#' in its value — a trailing comment "
                "is dropped by shell sourcing but kept by the Codex launcher. Remove it."
            )
        if not VALID_NAME.match(name):
            # "export NAME=…" sources fine in bash but the Codex launcher's
            # literal parser rejects it; either way the line is not plain.
            note(
                f"line {lineno}: variable name {name!r} is not a plain shell "
                f"identifier — bash may echo this line, secret and all, when the "
                f"file is sourced, and the Codex launcher rejects it. Use "
                f"NAME=value with [A-Z_][A-Z0-9_]* only."
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


def http_get(url: str, headers: dict[str, str]) -> tuple[int, object, dict[str, str]]:
    """Like http_json, but also return the response headers (lower-cased keys).

    GitHub reports a fine-grained token's expiry only in a response header,
    so the body alone is not enough for the GitHub check.
    """
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.load(resp), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()[:200].decode("utf-8", "replace"), {}
    except Exception as exc:  # network, timeout, malformed JSON
        return 0, str(exc), {}


def zotero_headers(key: str) -> dict[str, str]:
    return {"Zotero-API-Key": key, "Zotero-API-Version": "3"}


def check_shell_source(path: pathlib.Path) -> None:
    """Source the file in a subshell; any output is a parse failure."""
    print("\n== Shell-source test ==")
    result = subprocess.run(
        ["bash", "-c", 'set -a; . "$1"; set +a', "check-credentials", str(path)],
        capture_output=True, text=True,
    )
    combined = (result.stdout + result.stderr).strip()
    if combined:
        # Never echo the captured text: on a malformed line it contains the secret.
        note(
            f"sourcing {path.name} produced {len(combined.splitlines())} line(s) of "
            "output (suppressed — it would contain the secret). A well-formed file "
            "sources silently. If pass 1 reported nothing, the cause is something "
            "pass 1 cannot see line by line — an unterminated quote, a here-document, "
            "or a command substitution."
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
        personal = ("read+write" if user_access.get("write")
                    else "read only" if user_access else "no access")
        print(f"      personal: {personal}")
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


def github_token_vars(env: dict[str, str]) -> list[str]:
    """Names of every GitHub token variable, by naming convention."""
    return sorted(
        n for n in env
        if n in {"GH_TOKEN", "GITHUB_TOKEN"} or n.endswith("_GH_TOKEN"))


def check_github(env: dict[str, str]) -> dict[str, dt.date | str | None]:
    """Authenticate each GitHub token and report account, kind, expiry, push access.

    Returns a map of variable name to live expiry for the grant cross-check:
    a date, the string "none" for a token created without an expiry, or None
    when authentication failed.
    """
    print("\n== GitHub tokens ==")
    expiries: dict[str, dt.date | str | None] = {}
    names = github_token_vars(env)
    if not names:
        print("  none present")
        return expiries

    for name in names:
        token = env[name]
        # Token kind is visible from the prefix alone and never from the value.
        kind = ("fine-grained PAT" if token.startswith("github_pat_")
                else "classic PAT" if token.startswith("ghp_")
                else "OAuth/app token" if token.startswith(("gho_", "ghs_", "ghu_"))
                else "unrecognised prefix")
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        status, body, resp_headers = http_get(f"{GITHUB_API}/user", headers)
        if status != 200 or not isinstance(body, dict):
            note(f"{name}: authentication failed ({status})")
            expiries[name] = None
            continue

        expiry_raw = resp_headers.get("github-authentication-token-expiration", "")
        expiry: dt.date | None = None
        if expiry_raw:
            # Header form is "2026-12-06 03:14:07 UTC"; keep the date only.
            try:
                expiry = dt.date.fromisoformat(expiry_raw.split(" ")[0])
            except ValueError:
                pass
        # A missing header means the token was created with no expiry. That is
        # a choice, not a fault: the grant record must declare it, and the
        # grant cross-check below reports any disagreement.
        expiries[name] = expiry if expiry else "none" if not expiry_raw else None
        expires = (expiry.isoformat() if expiry
                   else f"unparseable header {expiry_raw!r}" if expiry_raw
                   else "none (rotated by hand)")
        print(f"  {name}: OK — account {body.get('login')!r}, {kind}, expires {expires}")
        if expiry_raw and expiry is None:
            # Otherwise the grant cross-check below would skip this token silently.
            note(f"{name}: expiry header {expiry_raw!r} did not parse — the grant "
                 "cross-check cannot compare it; report this format")

        # Fine-grained tokens carry no scope header; probe the repository instead.
        st, repo, _ = http_get(f"{GITHUB_API}/repos/{GITHUB_PROBE_REPO}", headers)
        if st == 200 and isinstance(repo, dict):
            perms = repo.get("permissions", {})
            access = ("push" if perms.get("push") else
                      "pull only" if perms.get("pull") else "none")
            print(f"      {GITHUB_PROBE_REPO}: {access}")
            if not perms.get("push"):
                note(f"{name}: cannot push to {GITHUB_PROBE_REPO} — the Codex launcher "
                     "grant is pointless without Contents: read and write there")
        elif st == 404:
            note(f"{name}: {GITHUB_PROBE_REPO} not visible — the token's repository "
                 "list does not include it")
        else:
            note(f"{name}: repository probe failed ({st})")
    return expiries


def check_grants(env: dict[str, str], expiries: dict[str, dt.date | str | None]) -> None:
    """Every launcher grant must name a variable that exists, and its record must
    agree with the live token about expiry."""
    print(f"\n== Launcher grants ({GRANTS_FILE.name}) ==")
    if not GRANTS_FILE.is_file():
        print(f"  {GRANTS_FILE} absent — skipped")
        return
    try:
        grants = tomllib.loads(GRANTS_FILE.read_text()).get("grants", [])
    except tomllib.TOMLDecodeError as exc:
        note(f"{GRANTS_FILE.name} does not parse: {exc}")
        return
    if not grants:
        print("  no grants declared")
        return

    today = dt.date.today()
    for grant in grants:
        source = grant.get("source_name", "")
        target = grant.get("inject_as", source)
        label = f"{grant.get('id', '?')} ({source} -> {target})"
        if not env.get(source):
            note(f"grant {label}: {source} is absent or empty in .env — the launcher would "
                 "inject nothing")
            continue
        if not VALID_NAME.match(target):
            note(f"grant {label}: inject_as {target!r} is not a valid shell identifier")
        expiry = expiries.get(source)
        recorded = str(grant.get("expires_on", "")).strip()
        if expiry is None:
            # Not a GitHub token, or its authentication already failed above.
            print(f"  {label}: present ({len(env[source])} chars)")
            continue
        if expiry == "none":
            if recorded == "none":
                print(f"  {label}: present, no expiry — rotated by hand, as recorded")
            else:
                note(f"grant {label}: live token has no expiry but the record says "
                     f"expires_on = {recorded!r} — fix the record or rotate the token")
            continue
        if recorded != expiry.isoformat():
            note(f"grant {label}: record says expires_on = {recorded!r}, live token "
                 f"expires {expiry.isoformat()} — update the record")
        days_left = (expiry - today).days
        if days_left < 0:
            note(f"grant {label}: token expired on {expiry.isoformat()}")
        elif days_left <= EXPIRY_WARNING_DAYS:
            note(f"grant {label}: token expires in {days_left} day(s) "
                 f"({expiry.isoformat()}) — rotate it and update the grant record")
        else:
            print(f"  {label}: present, expires {expiry.isoformat()} ({days_left} days)")


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
    expiries = check_github(env)
    check_grants(env, expiries)

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
