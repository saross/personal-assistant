#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# env-fingerprint.sh — describe a .env file without disclosing any value.
#
# Purpose
# -------
# `.env` files are gitignored by design, so copies on different machines drift
# silently and nothing detects it. Comparing them by eye means reading secrets;
# comparing them by `diff` means putting secrets on a terminal and possibly
# into a model's context. This prints, for each assignment, the key name, a
# salted SHA-256 prefix of the value, and the value's length — enough to answer
# "do these two files agree?" without ever revealing what they contain.
#
# The salt must be the same on both hosts — that is what makes cross-host
# comparison work at all — and it must NOT be public. Audit round 4d (E23):
# the salt used to be a constant hardcoded in this file, which is a PUBLIC
# repository, and the output carried each value's exact length. Together
# those turn the output into a value oracle: a 7-digit library ID is
# recoverable from its 12-hex fingerprint by sweeping ten million
# candidates, and low-entropy values (a boolean, a group ID) fall out
# instantly. So the salt is now REQUIRED from the environment
# (ENV_FINGERPRINT_SALT), never printed, and shared between machines out of
# band; and the length is reported as a coarse bucket rather than an exact
# count.
#
# Even so this remains a comparison aid, not a security boundary: do not
# paste the output anywhere public.
#
# Usage
# -----
#   read -rs ENV_FINGERPRINT_SALT; export ENV_FINGERPRINT_SALT
#   scripts/env-fingerprint.sh [path-to-env-file]
#
# Defaults to ~/personal-assistant/.env. To compare two machines, use the
# SAME salt on both. Never put it on a command line — local or remote:
# /proc/<pid>/cmdline is world-readable, so anyone with an account on the
# box can read it while the process lives, and a shell command line also
# lands in history. Send it down the remote shell's STDIN instead, ahead
# of the script itself:
#
#   read -rs ENV_FINGERPRINT_SALT; export ENV_FINGERPRINT_SALT
#   scripts/env-fingerprint.sh > /tmp/local.txt
#   {
#       printf 'export ENV_FINGERPRINT_SALT=%q\n' "$ENV_FINGERPRINT_SALT"
#       cat scripts/env-fingerprint.sh
#   } | ssh other-host 'bash -s' > /tmp/remote.txt
#
# then diff the three categories separately — keys only in A, keys only in B,
# and keys in both whose hashes differ. **The third is the one that matters**
# and the one a naive copy silently destroys: on 2026-08-22 it was three
# deliberately per-machine paid credentials that an `scp` would have clobbered.
#
# Comparing whole files with `diff` is a trap here, because ordering and
# comment differences swamp the signal. Sort by key name and compare fields.
#
# Output
# ------
# A metadata header (host, path, stat, line count), then one
# "KEY<TAB>hash<TAB>bucket" line per assignment sorted by key, then a summary
# and a duplicate-key warning. The bucket is empty / short / medium / long,
# not an exact length. Duplicates matter because the last assignment wins at
# load time, so a duplicated key is a silent override.
#
# See wiki/docs/env-cross-machine-reference.md for what is expected to differ
# between machines and what is not.
# ---------------------------------------------------------------------------
set -uo pipefail

ENV_FILE="${1:-${HOME}/personal-assistant/.env}"

# A required, private, shared salt — see the header. Refuse rather than fall
# back to a default: a public default silently makes every fingerprint below
# reversible, and a refusal is the only way the operator finds that out.
# The value itself is never echoed.
#
# Leading and trailing whitespace is stripped before use (round 4d-2, C2):
# a salt pasted with a trailing newline or space would otherwise fingerprint
# every value differently from the other machine's — reporting a
# whole-file mismatch that is not there — and a salt that was ONLY
# whitespace passed the emptiness test while protecting nothing.
SALT="${ENV_FINGERPRINT_SALT:-}"
SALT="${SALT#"${SALT%%[![:space:]]*}"}"
SALT="${SALT%"${SALT##*[![:space:]]}"}"
if [[ -z "$SALT" ]]; then
    echo "ERROR: ENV_FINGERPRINT_SALT is required (a private salt shared" >&2
    echo "  out of band with the machine you are comparing against)." >&2
    exit 2
fi
# Handed to the child through the ENVIRONMENT, never through argv
# (round 4d-2, C2): /proc/<pid>/cmdline is world-readable, so a salt on a
# command line is readable by every account on the machine for as long as
# the process lives, whereas /proc/<pid>/environ is owner-only.
export ENV_FINGERPRINT_SALT="$SALT"

echo "### host: $(hostname)"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "### MISSING: ${ENV_FILE} does not exist"
    exit 0
fi

# Size, mtime, and mode are useful context and disclose nothing. Mode is worth
# reading: a .env at 664 is readable by group and others, which has twice been
# found in the wild here (amd-tower and blue-mountains, both 2026-08-22).
echo "### file:  ${ENV_FILE}"
echo "### stat:  $(stat -c 'bytes=%s mode=%a owner=%U mtime=%y' "${ENV_FILE}")"
echo "### lines: $(wc -l < "${ENV_FILE}")"
echo "### ---"

python3 - "${ENV_FILE}" <<'PY'
"""Fingerprint each assignment in a .env file without emitting values."""
import hashlib
import os
import re
import sys
from collections import Counter
from pathlib import Path

# The salt arrives in the environment, not in argv: /proc/<pid>/cmdline is
# world-readable and /proc/<pid>/environ is not (round 4d-2, C2).
env_path = Path(sys.argv[1])
salt = os.environ["ENV_FINGERPRINT_SALT"]

# Accept an optional leading `export`, then KEY=VALUE. Comments and blanks
# fall through unmatched.
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

entries: list[tuple[str, str, str]] = []
seen: Counter[str] = Counter()


def length_bucket(length: int) -> str:
    """Coarsen a value length so the output cannot be used to guess it.

    An exact length narrows a brute-force sweep enormously; a bucket still
    catches the drift this tool exists to catch (a truncated paste, a
    placeholder swapped for a real credential) without naming a search
    space. Boundaries are deliberately wide.
    """
    if length == 0:
        return "empty"
    if length < 16:
        return "short"
    if length < 48:
        return "medium"
    return "long"

for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not raw.strip() or raw.lstrip().startswith("#"):
        continue
    match = ASSIGNMENT.match(raw)
    if not match:
        continue

    key, value = match.group(1), match.group(2).strip()

    # Strip one layer of matching quotes so 'abc', "abc", and abc agree.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]

    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()[:12]
    entries.append((key, digest, length_bucket(len(value))))
    seen[key] += 1

for key, digest, bucket in sorted(entries):
    # Flag empty values explicitly: they compare equal to each other and are
    # usually a placeholder rather than a real credential.
    marker = "  <EMPTY>" if bucket == "empty" else ""
    print(f"{key}\t{digest}\t{bucket}{marker}")

print("### ---")
print(f"### assignments: {len(entries)}  unique keys: {len(seen)}")

duplicates = [k for k, n in seen.items() if n > 1]
if duplicates:
    print(f"### DUPLICATE KEYS (last wins at load time): {', '.join(sorted(duplicates))}")
PY
