"""
Repository-scope lint: no quiet grep on the far side of a pipe.

``grep -q`` exits at its first match. Under ``set -o pipefail`` the producer
upstream of it then dies of SIGPIPE, the pipeline reports 141, and a
*successful* match reads as a failure — but only once the producer has more
than a pipe buffer (~64 KB) still to write, so the defect is invisible at the
one-line scale every test fixture uses and appears at the scale production
runs at.

This class has now shipped twice in this repository:

* ``daily-sync.sh``'s push gate, fixed with a per-script lint in
  ``test_daily_sync_stash_helpers.py``;
* ``push-archives-to-r2.sh``'s ``--immutable`` classifier (audit round 4c-7,
  finding C-1), where a real corruption signal read as "safe to retry"
  whenever more than ~64 KB of ERROR-level output followed the refusal. The
  deployed log holds 4,658 ``ERROR :`` lines in 2.5 MB, so that was the
  ordinary regime, not an edge case.

A per-script lint could not catch the second, because it only ever looked at
the first script. This one looks at every script in the repository that sets
``pipefail``, and the tokeniser and matcher are IMPORTED from the original
lint rather than copied — a second copy would drift, and the evasion tests
that harden the pattern (``grep -Fqx``, ``grep --silent``, ``grep -E -q``,
``egrep``/``fgrep``/``zgrep``, multi-line pipelines, heredoc bodies) live
with the original.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))

# The tokeniser, the matcher, and every evasion the original lint was
# hardened against. Imported, never re-implemented.
from test_daily_sync_stash_helpers import (  # noqa: E402
    _quiet_grep_offenders,
    _script_statements,
)

#: Shell scripts that opt into `pipefail`, where the defect can occur at all.
#: A script without it reports the LAST command's status, so a SIGPIPE
#: upstream is invisible — different bug, not this one.
_PIPEFAIL = re.compile(r"set\s+-[A-Za-z]*o\s+pipefail|set\s+-[A-Za-z]*e[A-Za-z]*o\s+pipefail")

#: Sites allowed to run a quiet grep, keyed by ``(file, function)``, each
#: with the reason it is safe. Every one of these reads a here-STRING or a
#: file, so there is no producer process to kill. Keyed by function rather
#: than by file so a new quiet grep elsewhere in an allowed file is still
#: caught, and carrying a reason so an entry cannot be added silently.
_ALLOWED: dict[tuple[str, str], str] = {}


def _shell_scripts() -> list[Path]:
    """Every ``*.sh`` under ``scripts/`` and ``hooks/``."""
    found: list[Path] = []
    for directory in ("scripts", "hooks"):
        found.extend(sorted((REPO_ROOT / directory).rglob("*.sh")))
    return found


def _pipefail_scripts() -> list[Path]:
    """The shell scripts that set ``pipefail``."""
    return [
        script for script in _shell_scripts()
        if _PIPEFAIL.search(script.read_text(encoding="utf-8"))
    ]


def _unallowed_offenders(script: Path) -> list[str]:
    """Offending statements in *script*, minus the allow-listed sites."""
    relative = str(script.relative_to(REPO_ROOT))
    functions = {
        number: function
        for number, function, _statement in _script_statements(script)
    }
    offenders = []
    for offender in _quiet_grep_offenders(script):
        number = int(offender.split(":", 1)[0])
        if (relative, functions.get(number, "")) in _ALLOWED:
            continue
        offenders.append(f"{relative}:{offender}")
    return offenders


class TestNoQuietGrepAcrossAPipe:
    """The rule, applied to the whole repository rather than one script."""

    def test_at_least_the_known_pipefail_scripts_are_scanned(self) -> None:
        """A lint over an empty set passes vacuously.

        Both scripts this defect has shipped in must be in scope, so a
        refactor that moves or renames one is a failure here rather than a
        silent loss of coverage.
        """
        scanned = {
            str(script.relative_to(REPO_ROOT)) for script in _pipefail_scripts()
        }

        assert "scripts/daily-sync.sh" in scanned, scanned
        assert "scripts/push-archives-to-r2.sh" in scanned, scanned
        assert len(scanned) >= 5, (
            f"only {len(scanned)} pipefail scripts found; the scan is "
            f"probably not reaching the tree: {scanned}"
        )

    @pytest.mark.parametrize(
        "script", _pipefail_scripts(), ids=lambda p: p.name
    )
    def test_no_quiet_grep_on_the_far_side_of_a_pipe(
        self, script: Path
    ) -> None:
        offenders = _unallowed_offenders(script)

        assert not offenders, (
            "these pipe a producer into a quiet grep. `grep -q` exits at "
            "its first match, the producer dies of SIGPIPE, and under "
            "`pipefail` the pipeline returns 141 — so a MATCH reads as a "
            "failure once the producer has more than ~64 KB left to "
            "write.\nUse one grep with a here-string, or drop -q and "
            "compare the output.\n" + "\n".join(offenders)
        )

    def test_the_r2_classifier_is_covered_by_this_lint(self) -> None:
        """The specific site C-1 was found in, named.

        Parametrised coverage is easy to lose to a filename change; this
        pins the one that cost a round.
        """
        script = REPO_ROOT / "scripts" / "push-archives-to-r2.sh"

        assert script in _pipefail_scripts()
        assert _unallowed_offenders(script) == []


class TestTheLintCatchesWhatItClaims:
    """The lint itself, held to a planted defect in each scanned script."""

    @pytest.mark.parametrize(
        "spelling",
        [
            'printf "%s" "$x" | grep -q immutable',
            'printf "%s" "$x" | grep -Fqx immutable',
            'printf "%s" "$x" | grep --quiet immutable',
            'printf "%s" "$x" | grep --silent immutable',
            'printf "%s" "$x" | grep -E -q immutable',
            'printf "%s" "$x" | egrep -q immutable',
        ],
    )
    def test_a_planted_quiet_grep_is_caught(
        self, tmp_path: Path, spelling: str
    ) -> None:
        """Every spelling the original lint was hardened against."""
        planted = tmp_path / "planted.sh"
        planted.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "check() {\n"
            f"    {spelling}\n"
            "}\n",
            encoding="utf-8",
        )

        assert _quiet_grep_offenders(planted), (
            f"`{spelling}` walked past the lint"
        )

    def test_a_here_string_grep_is_not_an_offender(
        self, tmp_path: Path
    ) -> None:
        """The fix's own shape must not be flagged.

        A here-string has no upstream process, so there is nothing to kill
        — which is exactly why it is the remedy.
        """
        planted = tmp_path / "here-string.sh"
        planted.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "check() {\n"
            '    grep -qE "immutable file modified" <<< "$output"\n'
            "}\n",
            encoding="utf-8",
        )

        assert _quiet_grep_offenders(planted) == []

    def test_a_multi_line_pipeline_is_caught(self, tmp_path: Path) -> None:
        """The evasion that reopened the defect in daily-sync.sh.

        Writing the pipe as a trailing operator puts the two halves on
        different lines, which a line-at-a-time scan misses entirely.
        """
        planted = tmp_path / "multiline.sh"
        planted.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "check() {\n"
            '    printf "%s" "$x" \\\n'
            "        | grep -E 'ERROR' \\\n"
            "        | grep -qE 'immutable'\n"
            "}\n",
            encoding="utf-8",
        )

        assert _quiet_grep_offenders(planted), (
            "a pipeline split across lines walked past the lint"
        )

    def test_a_script_without_pipefail_is_out_of_scope(
        self, tmp_path: Path
    ) -> None:
        """Scope is a claim too, so it is asserted rather than assumed."""
        planted = tmp_path / "no-pipefail.sh"
        planted.write_text(
            "#!/usr/bin/env bash\nset -eu\n"
            'check() { printf "%s" "$x" | grep -q immutable; }\n',
            encoding="utf-8",
        )

        assert not _PIPEFAIL.search(planted.read_text(encoding="utf-8"))


class TestTheAllowList:
    """An allow-list is a place defects hide; hold it to its own rules."""

    def test_every_entry_names_a_real_file_and_carries_a_reason(
        self
    ) -> None:
        for (relative, function), reason in _ALLOWED.items():
            assert (REPO_ROOT / relative).is_file(), (
                f"allow-list names a file that does not exist: {relative}"
            )
            assert reason.strip(), (
                f"allow-list entry ({relative}, {function}) has no reason"
            )

    def test_no_entry_is_stale(self) -> None:
        """An entry that no longer suppresses anything should be deleted.

        Otherwise the list grows into a standing permission nobody reviews.
        """
        for relative, function in _ALLOWED:
            script = REPO_ROOT / relative
            functions = {
                number: name
                for number, name, _statement in _script_statements(script)
            }
            suppressed = [
                offender for offender in _quiet_grep_offenders(script)
                if functions.get(int(offender.split(":", 1)[0]), "") == function
            ]
            assert suppressed, (
                f"allow-list entry ({relative}, {function}) suppresses "
                "nothing any more — delete it"
            )
