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
# The salt is fixed so the same value fingerprints identically on two hosts,
# which is what makes cross-host comparison work at all. It is a comparison
# aid, not a security boundary: do not paste the output anywhere public, and
# note that a low-entropy value (a group ID, a boolean) is not protected by a
# hash. Override with ENV_FINGERPRINT_SALT when comparing a set of files where
# even that matters; both sides must then use the same override.
#
# Usage
# -----
#   scripts/env-fingerprint.sh [path-to-env-file]
#
# Defaults to ~/personal-assistant/.env. To compare two machines:
#
#   scripts/env-fingerprint.sh > /tmp/local.txt
#   ssh other-host 'bash -s' < scripts/env-fingerprint.sh > /tmp/remote.txt
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
# "KEY<TAB>hash<TAB>length" line per assignment sorted by key, then a summary
# and a duplicate-key warning. Duplicates matter because the last assignment
# wins at load time, so a duplicated key is a silent override.
#
# See wiki/docs/env-cross-machine-reference.md for what is expected to differ
# between machines and what is not.
# ---------------------------------------------------------------------------
set -uo pipefail

ENV_FILE="${1:-${HOME}/personal-assistant/.env}"
SALT="${ENV_FINGERPRINT_SALT:-efn-envcmp-2026-08-22}"

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

python3 - "${ENV_FILE}" "${SALT}" <<'PY'
"""Fingerprint each assignment in a .env file without emitting values."""
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

env_path, salt = Path(sys.argv[1]), sys.argv[2]

# Accept an optional leading `export`, then KEY=VALUE. Comments and blanks
# fall through unmatched.
ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

entries: list[tuple[str, str, int]] = []
seen: Counter[str] = Counter()

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
    entries.append((key, digest, len(value)))
    seen[key] += 1

for key, digest, length in sorted(entries):
    # Flag empty values explicitly: they compare equal to each other and are
    # usually a placeholder rather than a real credential.
    marker = "  <EMPTY>" if length == 0 else ""
    print(f"{key}\t{digest}\t{length}{marker}")

print("### ---")
print(f"### assignments: {len(entries)}  unique keys: {len(seen)}")

duplicates = [k for k, n in seen.items() if n > 1]
if duplicates:
    print(f"### DUPLICATE KEYS (last wins at load time): {', '.join(sorted(duplicates))}")
PY
