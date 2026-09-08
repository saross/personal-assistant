"""
Tests for scripts/check-credentials.py — the read-only credential health check.

The script had no tests at all until the 2026-09-08 audit (finding "Lens B,
tranche 0: check-credentials.py has no tests"), so every one of its guards —
name hygiene, the trailing-comment divergence, GitHub token classification and
expiry parsing, and the launcher-grant cross-check — could be deleted with the
suite green.

Constraints honoured here, because this file is about credentials:

- **No real credential file is ever read.** Every test writes its own ``.env``
  into a pytest ``tmp_path`` with obviously fake values; the script's default
  path (``~/personal-assistant/.env``) is never the argument, and a deny rule
  blocks reading it anyway.
- **No network.** ``http_get`` and ``http_json`` are substituted in every test
  that reaches the live-read passes, and the substitutes assert on the URLs
  they are handed.
- **No secret may reach stdout.** The fake values below are distinctive
  strings, and several tests assert they appear nowhere in captured output —
  the property the whole script exists to protect.

``findings`` is module-level global state, so the autouse fixture clears it
around every test.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-credentials.py"
_spec = importlib.util.spec_from_file_location("check_credentials", SCRIPT)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

# A value distinctive enough that "did this leak?" is a substring search.
FAKE_SECRET = "FAKE-SECRET-DO-NOT-PRINT-9f3a2b"


@pytest.fixture(autouse=True)
def _clear_findings():
    """Reset the module-level ``findings`` list around every test."""
    cc.findings.clear()
    yield
    cc.findings.clear()


def _env_file(tmp_path: Path, text: str, name: str = ".env") -> Path:
    """Write a throwaway env file with fake values and return its path."""
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ============================================================================
# parse_env — pass 1, name hygiene
# ============================================================================


class TestParseEnvNames:
    """Case 1 and 3 of the audit case list."""

    @pytest.mark.parametrize(
        "line",
        ["api_key=v", "BAD-NAME=v", "1FOO=v", "A.B=v", "export FOO=v"],
    )
    def test_invalid_names_are_flagged(self, tmp_path, line, capsys):
        """Kills ``if not VALID_NAME.match(name):`` → ``if False:``.

        ``export FOO=v`` sources cleanly in bash but the Codex launcher's
        literal parser rejects it, so it is deliberately a finding; the
        parametrisation pins that intent alongside the genuinely broken
        names.
        """
        cc.parse_env(_env_file(tmp_path, line + "\n"))
        assert len(cc.findings) >= 1
        assert any("not a plain shell identifier" in f for f in cc.findings)

    @pytest.mark.parametrize("name", ["_FOO", "FOO1", "A_B_C"])
    def test_valid_names_are_not_flagged(self, tmp_path, name):
        """Kills widening VALID_NAME to something that rejects legal names."""
        cc.parse_env(_env_file(tmp_path, f"{name}=v\n"))
        assert cc.findings == []

    def test_whitespace_before_the_equals_is_flagged(self, tmp_path):
        """Kills ``if raw_name != name:`` → ``if False:``.

        ``NAME =value``: bash runs ``NAME`` as a command and echoes
        ``NAME: command not found``. Verified against bash 5 on 2026-09-08.
        """
        cc.parse_env(_env_file(tmp_path, f"SPACED_NAME ={FAKE_SECRET}\n"))
        assert len(cc.findings) == 1
        assert "whitespace around the name" in cc.findings[0]
        assert cc.findings[0].startswith("line 1:")

    def test_whitespace_after_the_equals_is_flagged(self, tmp_path):
        """Kills the new ``if value and raw_value_field[:1].isspace():`` guard.

        This is the defect fixed on 2026-09-08. ``NAME= value`` was missed
        entirely because the value was stripped before any test ran, and it
        is the WORSE form: bash assigns ``NAME`` the empty string for one
        command and then runs the value as that command, so the secret
        itself is echoed to stderr rather than just the variable name.
        Verified against bash 5.
        """
        cc.parse_env(_env_file(tmp_path, f"SPACED_VALUE= {FAKE_SECRET}\n"))
        assert len(cc.findings) == 1
        assert "whitespace after the '='" in cc.findings[0]
        assert cc.findings[0].startswith("line 1:")
        assert FAKE_SECRET not in cc.findings[0]


class TestParseEnvValues:
    """Cases 4 and 5 of the audit case list — the value side."""

    def test_unquoted_trailing_comment_is_flagged(self, tmp_path):
        """Kills ``if not quoted and (" #" in value …)`` → ``if False:``.

        Shell sourcing drops the comment; this parser and the Codex
        launcher keep it, so the two would hand a process different
        secrets.
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN=abcfake # trailing comment\n"))
        assert len(cc.findings) == 1
        assert "has a '#' in its value" in cc.findings[0]

    def test_a_value_beginning_with_hash_is_flagged(self, tmp_path):
        """Kills dropping ``or value.startswith("#")`` from the same test."""
        cc.parse_env(_env_file(tmp_path, "TOKEN=#abcfake\n"))
        assert len(cc.findings) == 1
        assert "has a '#' in its value" in cc.findings[0]

    def test_a_hash_inside_a_closed_quote_is_not_flagged(self, tmp_path):
        """Kills dropping the ``quoted`` exemption altogether.

        ``TOKEN="abc # inside"`` assigns ``abc # inside`` in bash and here;
        both sides agree, so there is nothing to report. Verified against
        bash 5 on 2026-09-08.
        """
        env = cc.parse_env(_env_file(tmp_path, 'TOKEN="abcfake # inside"\n'))
        assert cc.findings == []
        assert env["TOKEN"] == "abcfake # inside"

    def test_a_quote_that_closes_early_is_flagged_twice(self, tmp_path):
        """Kills reverting ``quoted`` to ``raw_value[:1] in ('"', "'")``.

        This is the second defect fixed on 2026-09-08. For
        ``TOKEN='abc' # trailing comment`` bash assigns ``abc`` while this
        parser assigns ``abc' # trailing comment`` — a real divergence that
        the "starts with a quote" guard suppressed, so no finding was
        raised at all. Verified against bash 5.2.

        Two findings now, not one (audit round two, Lows): the trailing
        comment AND the quote that closes before the end of the value.
        """
        env = cc.parse_env(
            _env_file(tmp_path, "TOKEN='abcfake' # trailing comment\n")
        )
        assert len(cc.findings) == 2
        assert any("has a '#' in its value" in f for f in cc.findings)
        assert any("does not close" in f for f in cc.findings)
        # And the divergence itself: bash would have assigned "abcfake".
        assert env["TOKEN"] != "abcfake"

    def test_an_unterminated_quote_is_flagged_on_its_own(self, tmp_path):
        """Kills dropping the ``if quote_char and not quoted:`` finding.

        Audit round two, Lows: the test above passed only because of the
        '#' finding, so an unterminated quote with no '#' produced NOTHING
        at line level. bash rejects the whole file as an unterminated
        string, which pass 2 reports without saying which line.
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN='abcfake\n"))
        assert len(cc.findings) == 1
        assert "does not close" in cc.findings[0]
        assert cc.findings[0].startswith("line 1:")

    def test_a_closed_quote_is_stripped_exactly_once(self, tmp_path):
        """Kills ``raw_value[1:-1]`` → ``.strip('"').strip("'")``.

        Repeated stripping eats a nested quote that bash keeps.
        """
        env = cc.parse_env(_env_file(tmp_path, "TOKEN=\"'abcfake'\"\n"))
        assert env["TOKEN"] == "'abcfake'"

    def test_only_the_first_equals_splits_the_line(self, tmp_path):
        """Kills ``^([^=]+)=(.*)$`` → a greedy or split-on-every-'=' parse."""
        env = cc.parse_env(_env_file(tmp_path, "MULTI=a=b=c\n"))
        assert env["MULTI"] == "a=b=c"
        assert cc.findings == []

    def test_an_empty_value_parses_to_the_empty_string(self, tmp_path):
        """Kills treating a valueless assignment as a skipped line."""
        env = cc.parse_env(_env_file(tmp_path, "EMPTY=\n"))
        assert env == {"EMPTY": ""}

    def test_comments_and_blank_lines_are_skipped(self, tmp_path):
        """Kills dropping ``if not line or line.startswith("#"): continue``.

        Without it a comment line containing an '=' is parsed as an
        assignment with a malformed name and raises a spurious finding.
        """
        env = cc.parse_env(
            _env_file(tmp_path, "# a comment with an = sign\n\nGOOD=v\n")
        )
        assert env == {"GOOD": "v"}
        assert cc.findings == []

    def test_line_numbers_are_one_based_and_count_skipped_lines(self, tmp_path):
        """Kills ``enumerate(..., start=1)`` → ``start=0`` and any use of a
        post-filter counter: the number in a finding must point at the line
        in the file the operator has to edit."""
        cc.parse_env(
            _env_file(tmp_path, "# comment\n\nGOOD=v\nbad-name=v\n")
        )
        assert len(cc.findings) == 1
        assert cc.findings[0].startswith("line 4:")

    def test_no_value_is_ever_printed(self, tmp_path, capsys):
        """Kills any finding message that interpolates the value.

        Every malformed form in one file; the fake secret must appear in no
        finding and nowhere in stdout.
        """
        text = (
            f"bad-name={FAKE_SECRET}\n"
            f"SPACED ={FAKE_SECRET}\n"
            f"SPACED2= {FAKE_SECRET}\n"
            f"COMMENTED={FAKE_SECRET} # trailing\n"
            f"QUOTED='{FAKE_SECRET}' # trailing\n"
        )
        cc.parse_env(_env_file(tmp_path, text))
        assert cc.findings, "the fixture must produce findings to be meaningful"
        out = capsys.readouterr().out
        assert FAKE_SECRET not in out
        assert not any(FAKE_SECRET in f for f in cc.findings)


# ============================================================================
# check_shell_source — pass 2
# ============================================================================


class TestParseEnvShellDivergence:
    """Audit round two M4: four ways bash and the launcher disagree.

    Each is verified against bash 5.2 with a throwaway env file, and each
    was silent before 2026-09-08.
    """

    def test_an_unquoted_dollar_is_flagged(self, tmp_path):
        """Kills dropping the ``"$" in value`` finding.

        Verified: ``A=$B`` with B unset assigns bash the EMPTY string while
        the parser keeps ``$B``. The process gets no credential at all and
        the file looks populated — the quietest failure in the set.
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN=$OTHER_VAR\n"))
        assert len(cc.findings) == 1
        assert "'$' outside single quotes" in cc.findings[0]
        assert cc.findings[0].startswith("line 1:")

    def test_a_dollar_inside_double_quotes_is_still_flagged(self, tmp_path):
        """Kills narrowing the guard to unquoted values only.

        Double quotes do not stop expansion: ``A="$B"`` assigns the empty
        string in bash, exactly as the unquoted form does.
        """
        cc.parse_env(_env_file(tmp_path, 'TOKEN="$OTHER_VAR"\n'))
        assert len(cc.findings) == 1
        assert "'$' outside single quotes" in cc.findings[0]

    def test_a_dollar_inside_single_quotes_is_not_flagged(self, tmp_path):
        """Kills widening the guard to every ``$``.

        ``A='$B'`` assigns the literal ``$B`` in bash, which is what the
        parser and the launcher do — both sides agree, so there is nothing
        to report, and the message tells the operator to do precisely this.
        """
        env = cc.parse_env(_env_file(tmp_path, "TOKEN='$OTHER_VAR'\n"))
        assert cc.findings == []
        assert env["TOKEN"] == "$OTHER_VAR"

    def test_a_trailing_backslash_is_flagged(self, tmp_path):
        r"""Kills dropping the ``raw_value.endswith("\\")`` finding.

        Verified: a value ending in a backslash, followed by ``NEXT=y``,
        assigns A the value ``xNEXT=y`` and leaves NEXT unset — one wrong
        secret and one variable that silently does not exist.
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN=abcfake\\\nNEXT_VAR=other\n"))
        assert any("ends with a backslash" in f for f in cc.findings)
        assert any(f.startswith("line 1:") for f in cc.findings)

    def test_a_crlf_line_ending_is_flagged(self, tmp_path):
        """Kills reverting to ``read_text().splitlines()``.

        Verified: sourcing a CRLF file assigns ``x\r`` for ``A=x``. Python
        hides the carriage return twice over — text-mode reads translate
        ``\r\n`` to ``\n``, and ``splitlines()`` strips what is left — so the
        parser cannot even see the character bash keeps.
        """
        path = tmp_path / "crlf.env"
        path.write_bytes(b"TOKEN=abcfake\r\nOTHER=second\r\n")
        env = cc.parse_env(path)
        assert env == {"TOKEN": "abcfake", "OTHER": "second"}
        assert len(cc.findings) == 2
        assert all("CRLF line ending" in f for f in cc.findings)
        assert cc.findings[0].startswith("line 1:")
        assert cc.findings[1].startswith("line 2:")

    def test_lf_line_endings_are_not_flagged(self, tmp_path):
        """Kills flagging every line regardless of its ending."""
        path = tmp_path / "lf.env"
        path.write_bytes(b"TOKEN=abcfake\nOTHER=second\n")
        env = cc.parse_env(path)
        assert env == {"TOKEN": "abcfake", "OTHER": "second"}
        assert cc.findings == []

    def test_a_cr_only_file_still_parses_line_by_line(self, tmp_path):
        """Kills splitting on ``\n`` alone (audit round two L1).

        That split collapsed a legacy CR-only file into ONE "line", so the
        parser returned ``{'TOKEN': 'abcfake\rOTHER=second\rTHIRD=third'}``
        and reported findings against names that are not what is wrong. The
        operator must still see every name in the file.
        """
        path = tmp_path / "cr.env"
        path.write_bytes(b"TOKEN=abcfake\rOTHER=second\rTHIRD=third\r")
        env = cc.parse_env(path)
        assert env == {
            "TOKEN": "abcfake", "OTHER": "second", "THIRD": "third",
        }
        assert len(cc.findings) == 3
        assert all("lone CR line ending" in f for f in cc.findings)

    def test_a_cr_only_ending_is_reported_as_its_own_problem(self, tmp_path):
        """Kills folding the lone-CR case into the CRLF message.

        They fail differently, verified against bash 5.2.37. CRLF keeps the
        carriage return IN the value; a lone CR is not a line break to bash
        at all, so it reads the whole file as one line — ``A=1\rB=2\rC=3``
        assigns A the rest of the file and leaves B and C unset. Telling the
        operator "the value has a stray character" would be the wrong
        diagnosis.
        """
        path = tmp_path / "cr.env"
        path.write_bytes(b"TOKEN=abcfake\r")
        cc.parse_env(path)
        assert len(cc.findings) == 1
        assert "lone CR line ending" in cc.findings[0]
        assert "reads the whole file as ONE line" in cc.findings[0]
        assert "CRLF" not in cc.findings[0]

    def test_mixed_line_endings_are_reported_per_line(self, tmp_path):
        """Kills classifying the file rather than each line.

        A file part-converted by an editor carries both endings, and the
        operator needs the line numbers, not a verdict on the file.
        """
        path = tmp_path / "mixed.env"
        path.write_bytes(b"TOKEN=abcfake\r\nOTHER=second\nTHIRD=third\r")
        env = cc.parse_env(path)
        assert env == {
            "TOKEN": "abcfake", "OTHER": "second", "THIRD": "third",
        }
        assert len(cc.findings) == 2
        assert cc.findings[0].startswith("line 1:") and "CRLF" in cc.findings[0]
        assert cc.findings[1].startswith("line 3:") and "lone CR" in cc.findings[1]

    @pytest.mark.parametrize(
        "line,char",
        [
            ("TOKEN=https://example.test/y?z=1&w=2", "&"),
            ("TOKEN=abcfake;whoami", ";"),
            ("TOKEN=abcfake|whoami", "|"),
        ],
    )
    def test_an_unquoted_control_operator_is_flagged(self, tmp_path, line, char):
        """Kills dropping the ``for char in "&;|"`` finding.

        Verified against bash 5.2.37: ``A=https://x/y?z=1&w=2`` leaves A
        UNSET because '&' backgrounds the assignment; ``A=a;b`` assigns 'a'
        and runs 'b'; ``A=a|b`` leaves A unset and runs 'b'. The URL is the
        form most likely to appear in a real credential file, and it fails
        silently — the variable simply is not there.
        """
        cc.parse_env(_env_file(tmp_path, line + "\n"))
        assert len(cc.findings) == 1
        assert f"contains {char} and is not quoted" in cc.findings[0]

    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_a_quoted_control_operator_is_not_flagged(self, tmp_path, quote):
        """Kills applying the operator check to quoted values.

        Either quote form protects '&', ';' and '|', verified against bash
        5.2.37, and a query-string URL in quotes is a perfectly ordinary
        credential-file entry.
        """
        url = "https://example.test/y?z=1&w=2"
        env = cc.parse_env(
            _env_file(tmp_path, f"TOKEN={quote}{url}{quote}\n")
        )
        assert cc.findings == []
        assert env["TOKEN"] == url

    @pytest.mark.parametrize("value", ["`whoami`", "$(whoami)"])
    def test_a_command_substitution_is_flagged(self, tmp_path, value):
        """Kills dropping the ``"`" in value or "$(" in value`` finding.

        Verified against bash 5.2.37: both forms EXECUTE the command when
        the file is sourced and assign its output. A credential file is
        sourced by every session hook, so this is arbitrary execution on a
        schedule, not a formatting problem.
        """
        cc.parse_env(_env_file(tmp_path, f"TOKEN={value}\n"))
        assert len(cc.findings) == 1
        assert "command substitution" in cc.findings[0]
        assert "EXECUTES" in cc.findings[0]

    def test_a_double_quoted_command_substitution_is_still_flagged(self, tmp_path):
        """Kills reusing the ``not quoted`` guard for command substitution.

        Double quotes stop '&', ';' and '|' but NOT substitution: verified
        against bash 5.2.37, ``A="`id`"`` still executes. The two classes
        need different guards, and treating them alike lets the dangerous
        one through.
        """
        cc.parse_env(_env_file(tmp_path, 'TOKEN="`whoami`"\n'))
        assert len(cc.findings) == 1
        assert "command substitution" in cc.findings[0]

    def test_a_single_quoted_command_substitution_is_not_flagged(self, tmp_path):
        """Kills flagging every backtick regardless of quoting.

        Single quotes make it literal on both sides, so there is nothing to
        report — and the finding's own advice is to single-quote the value.
        """
        env = cc.parse_env(_env_file(tmp_path, "TOKEN='`whoami`'\n"))
        assert cc.findings == []
        assert env["TOKEN"] == "`whoami`"

    def test_a_command_substitution_is_reported_once_not_twice(self, tmp_path):
        """Kills dropping the ``and not substitution`` guard on the '$' check.

        ``$(`` matches the plain expansion rule too; two findings for one
        character would bury the sharper message (it EXECUTES) under the
        milder one (it expands).
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN=$(whoami)\n"))
        assert len(cc.findings) == 1
        assert "command substitution" in cc.findings[0]

    def test_whitespace_inside_an_unquoted_value_is_flagged(self, tmp_path):
        """Kills dropping the ``len(words) > 1`` finding.

        Verified: ``A=a b`` assigns NOTHING to A, runs ``b`` as a command,
        and echoes "b: command not found" — the same leak class as
        ``NAME= value``, and the parser meanwhile keeps ``a b``.
        """
        cc.parse_env(_env_file(tmp_path, f"TOKEN=abcfake {FAKE_SECRET}\n"))
        assert len(cc.findings) == 1
        assert "contains whitespace and is not quoted" in cc.findings[0]
        assert FAKE_SECRET not in cc.findings[0]

    def test_whitespace_inside_a_quoted_value_is_not_flagged(self, tmp_path):
        """Kills applying the whitespace check to quoted values.

        ``A="a b"`` assigns ``a b`` on both sides; a passphrase with spaces
        is legitimate as long as it is quoted.
        """
        env = cc.parse_env(_env_file(tmp_path, 'TOKEN="two words"\n'))
        assert cc.findings == []
        assert env["TOKEN"] == "two words"

    def test_a_trailing_comment_is_not_reported_as_a_command(self, tmp_path):
        """Kills dropping ``not words[1].startswith("#")`` from the guard.

        ``A=abc # c`` has whitespace in an unquoted value but bash runs no
        command — the rest is a comment. Reporting it as an executed
        command would be a false statement about what bash does, and the
        line already has its own (correct) finding.
        """
        cc.parse_env(_env_file(tmp_path, "TOKEN=abcfake # a comment\n"))
        assert len(cc.findings) == 1
        assert "has a '#' in its value" in cc.findings[0]

    def test_the_shell_source_message_does_not_promise_findings_above(
        self, tmp_path, capsys
    ):
        """Kills restoring "Fix the names above" to the pass-2 message.

        Audit round two M4: pass 2 fires on causes pass 1 cannot see line
        by line, so pointing the operator at findings that may not exist
        sends them looking for something that is not there.
        """
        cc.check_shell_source(_env_file(tmp_path, "TOKEN='unterminated\n"))
        assert len(cc.findings) == 1
        assert "Fix the names above" not in cc.findings[0]
        assert "sources silently" in cc.findings[0]


class TestCheckShellSource:
    """Cases 7 and 8 of the audit case list."""

    def test_a_clean_file_is_silent_and_raises_nothing(self, tmp_path, capsys):
        """Kills ``if combined:`` → ``if True:`` (every file reported broken)."""
        cc.check_shell_source(_env_file(tmp_path, "GOOD=abcfake\n"))
        assert cc.findings == []
        assert "silent — all names parse as assignments" in capsys.readouterr().out

    def test_a_malformed_file_is_reported_without_the_value(
        self, tmp_path, capsys
    ):
        """Kills ``if combined:`` → ``if False:``, and any change that echoes
        the captured text: on a malformed line bash's own error message
        contains the secret."""
        cc.check_shell_source(_env_file(tmp_path, f"BAD NAME= {FAKE_SECRET}\n"))
        assert len(cc.findings) == 1
        assert "line(s) of" in cc.findings[0]
        assert FAKE_SECRET not in cc.findings[0]
        assert FAKE_SECRET not in capsys.readouterr().out

    def test_a_path_containing_a_space_is_sourced_correctly(
        self, tmp_path, capsys
    ):
        """Kills unquoting the path back into the ``bash -c`` string.

        With the path interpolated unquoted, bash sources two nonexistent
        files and every clean env file in a directory with a space in its
        name reports as broken.
        """
        path = _env_file(tmp_path, "GOOD=abcfake\n", name="with space.env")
        cc.check_shell_source(path)
        assert cc.findings == []
        assert "silent" in capsys.readouterr().out


# ============================================================================
# github_token_vars — naming convention
# ============================================================================


class TestGithubTokenVars:
    """Case 9 of the audit case list."""

    def test_selects_exactly_the_github_token_names(self):
        """Kills widening the membership test to ``"GH_TOKEN" in n``.

        ``GH_TOKEN_OLD`` and ``GITHUB_TOKEN_2`` are deliberately outside the
        convention: a retired or duplicated token must not be authenticated
        against GitHub on every run.
        """
        env = {
            "GH_TOKEN": "x",
            "GITHUB_TOKEN": "x",
            "CODEX_GH_TOKEN": "x",
            "GH_TOKEN_OLD": "x",
            "GITHUB_TOKEN_2": "x",
            "gh_token": "x",
            "OSF_API_KEY": "x",
        }
        assert cc.github_token_vars(env) == [
            "CODEX_GH_TOKEN",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        ]


# ============================================================================
# check_github — pass 3, with http_get substituted (no network)
# ============================================================================


def _stub_http_get(monkeypatch, *, user, repo):
    """Replace ``cc.http_get`` with a URL-dispatching stub. No network.

    ``user`` and ``repo`` are ``(status, body, headers)`` triples. The stub
    records its calls and refuses any URL the test did not anticipate, so a
    real request cannot slip through unnoticed.
    """
    calls: list[str] = []

    def _get(url: str, headers: dict[str, str]):
        calls.append(url)
        if url.endswith("/user"):
            return user
        if "/repos/" in url:
            return repo
        raise AssertionError(f"unexpected URL requested: {url}")

    monkeypatch.setattr(cc, "http_get", _get)
    return calls


_OK_USER = (200, {"login": "saross"}, {})
_OK_REPO = (200, {"permissions": {"push": True, "pull": True}}, {})


class TestCheckGithub:
    """Cases 10–14 of the audit case list."""

    @pytest.mark.parametrize(
        "token,kind",
        [
            ("github_pat_abcfake", "fine-grained PAT"),
            ("ghp_abcfake", "classic PAT"),
            ("gho_abcfake", "OAuth/app token"),
            ("ghs_abcfake", "OAuth/app token"),
            ("ghu_abcfake", "OAuth/app token"),
            ("nonsense_abcfake", "unrecognised prefix"),
        ],
    )
    def test_token_kind_comes_from_the_prefix(
        self, monkeypatch, capsys, token, kind
    ):
        """Kills collapsing the prefix ladder to a single branch.

        The kind is the only thing said about a token's nature, and it must
        come from the prefix rather than the value.
        """
        _stub_http_get(monkeypatch, user=_OK_USER, repo=_OK_REPO)
        cc.check_github({"GH_TOKEN": token})
        out = capsys.readouterr().out
        assert kind in out
        assert token not in out

    def test_a_parseable_expiry_header_becomes_a_date(self, monkeypatch, capsys):
        """Kills ``expiry_raw.split(" ")[0]`` → the whole header string.

        The grant cross-check compares ``expiry.isoformat()`` with the
        recorded date, so a mis-parsed header makes every grant disagree.
        """
        user = (
            200,
            {"login": "saross"},
            {"github-authentication-token-expiration": "2026-12-06 03:14:07 UTC"},
        )
        _stub_http_get(monkeypatch, user=user, repo=_OK_REPO)
        expiries = cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert expiries["GH_TOKEN"] == dt.date(2026, 12, 6)
        assert cc.findings == []
        assert "expires 2026-12-06" in capsys.readouterr().out

    def test_a_missing_expiry_header_means_none(self, monkeypatch, capsys):
        """Kills collapsing the three-way expiry result to two values.

        No header means the token was created without an expiry — a choice
        the grant record must declare, not a fault.
        """
        _stub_http_get(monkeypatch, user=_OK_USER, repo=_OK_REPO)
        expiries = cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert expiries["GH_TOKEN"] == "none"
        assert cc.findings == []
        assert "none (rotated by hand)" in capsys.readouterr().out

    def test_an_unparseable_expiry_header_is_a_finding(self, monkeypatch, capsys):
        """Kills ``if expiry_raw and expiry is None:`` → ``if False:``.

        Without the finding the value stays ``None``, which makes
        ``check_grants`` skip the cross-check *silently* — the token's real
        expiry then goes unchecked forever with no signal.
        """
        user = (
            200,
            {"login": "saross"},
            {"github-authentication-token-expiration": "next Tuesday"},
        )
        _stub_http_get(monkeypatch, user=user, repo=_OK_REPO)
        expiries = cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert expiries["GH_TOKEN"] is None
        assert len(cc.findings) == 1
        assert "did not parse" in cc.findings[0]
        assert "unparseable header" in capsys.readouterr().out

    def test_a_401_is_a_finding_and_the_loop_continues(self, monkeypatch, capsys):
        """Kills ``continue`` → ``return`` after a failed authentication.

        With ``return`` the first dead token hides every later one.
        """

        def _get(url: str, headers: dict[str, str]):
            if headers["Authorization"].endswith("deadfake"):
                return (401, "Bad credentials", {})
            if url.endswith("/user"):
                return _OK_USER
            return _OK_REPO

        monkeypatch.setattr(cc, "http_get", _get)
        expiries = cc.check_github(
            {"GH_TOKEN": "ghp_deadfake", "GITHUB_TOKEN": "ghp_livefake"}
        )
        assert expiries["GH_TOKEN"] is None
        assert expiries["GITHUB_TOKEN"] == "none"
        assert any("authentication failed (401)" in f for f in cc.findings)
        assert "GITHUB_TOKEN: OK" in capsys.readouterr().out

    def test_push_access_raises_nothing(self, monkeypatch, capsys):
        """Kills ``if not perms.get("push"):`` → ``if True:``."""
        _stub_http_get(monkeypatch, user=_OK_USER, repo=_OK_REPO)
        cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert cc.findings == []
        # The literal, not the constant against itself (audit round two,
        # Lows): gpt-hub is the repository the Codex launcher must reach, so
        # repointing GITHUB_PROBE_REPO elsewhere is the defect, not a rename.
        assert cc.GITHUB_PROBE_REPO == "saross/gpt-hub"
        assert "saross/gpt-hub: push" in capsys.readouterr().out

    def test_pull_only_access_is_a_finding(self, monkeypatch, capsys):
        """Kills ``if not perms.get("push"):`` → ``if False:``.

        A read-only token satisfies the ``/user`` check and is useless to
        the Codex launcher, which exists to push.
        """
        repo = (200, {"permissions": {"push": False, "pull": True}}, {})
        _stub_http_get(monkeypatch, user=_OK_USER, repo=repo)
        cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert len(cc.findings) == 1
        assert "cannot push" in cc.findings[0]
        assert "pull only" in capsys.readouterr().out

    def test_a_404_repository_probe_is_its_own_finding(self, monkeypatch):
        """Kills folding the 404 branch into the generic probe failure.

        404 means the token's repository list excludes gpt-hub — a
        different fix from a transient probe failure.
        """
        _stub_http_get(monkeypatch, user=_OK_USER, repo=(404, "Not Found", {}))
        cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert len(cc.findings) == 1
        assert "not visible" in cc.findings[0]

    def test_any_other_probe_status_is_reported(self, monkeypatch):
        """Kills dropping the ``else`` arm of the repository probe."""
        _stub_http_get(monkeypatch, user=_OK_USER, repo=(500, "boom", {}))
        cc.check_github({"GH_TOKEN": "github_pat_abcfake"})
        assert len(cc.findings) == 1
        assert "repository probe failed (500)" in cc.findings[0]

    def test_no_token_value_reaches_stdout(self, monkeypatch, capsys):
        """Kills interpolating the token into any printed line."""
        _stub_http_get(monkeypatch, user=_OK_USER, repo=_OK_REPO)
        cc.check_github({"GH_TOKEN": f"github_pat_{FAKE_SECRET}"})
        out = capsys.readouterr().out
        assert FAKE_SECRET not in out
        assert not any(FAKE_SECRET in f for f in cc.findings)

    def test_no_tokens_present_does_no_requests(self, monkeypatch, capsys):
        """Kills ``if not names: return expiries`` → falling through."""
        calls = _stub_http_get(monkeypatch, user=_OK_USER, repo=_OK_REPO)
        assert cc.check_github({"OSF_API_KEY": "x"}) == {}
        assert calls == []
        assert "none present" in capsys.readouterr().out


# ============================================================================
# check_grants — pass 4, with GRANTS_FILE repointed at a fixture
# ============================================================================


def _grants_file(tmp_path: Path, body: str, monkeypatch) -> Path:
    """Write a throwaway credential-grants.toml and point the script at it."""
    path = tmp_path / "credential-grants.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cc, "GRANTS_FILE", path)
    return path


_GRANT = """schema_version = 2

[[grants]]
id = "github-pat-gpt"
source_name = "GPT_GH_TOKEN"
inject_as = "GH_TOKEN"
expires_on = "{expires_on}"
"""


class TestCheckGrants:
    """Cases 15–20 of the audit case list."""

    def test_a_missing_grants_file_is_skipped_without_a_finding(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ``if not GRANTS_FILE.is_file(): return`` → falling through.

        The checker runs on machines that have no launcher grants; absence
        is not a fault.
        """
        monkeypatch.setattr(cc, "GRANTS_FILE", tmp_path / "absent.toml")
        cc.check_grants({}, {})
        assert cc.findings == []
        assert "absent — skipped" in capsys.readouterr().out

    def test_malformed_toml_is_one_finding_not_a_traceback(
        self, tmp_path, monkeypatch
    ):
        """Kills removing the ``except tomllib.TOMLDecodeError`` arm.

        The checker is run by hand after editing credentials; a traceback
        there loses every other pass's output.
        """
        _grants_file(tmp_path, "this is not = [ valid toml\n", monkeypatch)
        cc.check_grants({}, {})
        assert len(cc.findings) == 1
        assert "does not parse" in cc.findings[0]

    def test_an_absent_source_variable_is_a_finding(self, tmp_path, monkeypatch):
        """Kills ``if not env.get(source):`` → ``if False:``.

        A grant naming a variable that does not exist makes the launcher
        inject nothing, and the sandbox then fails with an empty credential
        rather than a missing one.
        """
        _grants_file(tmp_path, _GRANT.format(expires_on="none"), monkeypatch)
        cc.check_grants({}, {})
        assert len(cc.findings) == 1
        assert "absent or empty in .env" in cc.findings[0]

    def test_an_empty_source_variable_is_also_a_finding(self, tmp_path, monkeypatch):
        """Kills ``env.get(source)`` → ``source in env`` (empty passes)."""
        _grants_file(tmp_path, _GRANT.format(expires_on="none"), monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": ""}, {})
        assert len(cc.findings) == 1
        assert "absent or empty in .env" in cc.findings[0]

    def test_an_invalid_inject_as_is_a_finding_and_the_grant_still_reports(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ``if not VALID_NAME.match(target):`` → ``if False:``.

        The launcher exports ``inject_as`` literally, so a non-identifier
        there is the same leak class as a malformed .env name — and the
        grant must still be reported, not skipped.
        """
        body = _GRANT.format(expires_on="none").replace(
            'inject_as = "GH_TOKEN"', 'inject_as = "gh-token"'
        )
        _grants_file(tmp_path, body, monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": "none"})
        assert len(cc.findings) == 1
        assert "not a valid shell identifier" in cc.findings[0]
        assert "rotated by hand, as recorded" in capsys.readouterr().out

    def test_no_expiry_known_reports_length_only(self, tmp_path, monkeypatch, capsys):
        """Kills ``if expiry is None: … continue`` → falling through.

        A non-GitHub credential has no live expiry to compare; the script
        must say so without inventing a comparison, and must print only the
        length.
        """
        _grants_file(tmp_path, _GRANT.format(expires_on="none"), monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": FAKE_SECRET}, {})
        assert cc.findings == []
        out = capsys.readouterr().out
        assert f"present ({len(FAKE_SECRET)} chars)" in out
        assert FAKE_SECRET not in out

    def test_no_live_expiry_matching_the_record_is_clean(
        self, tmp_path, monkeypatch
    ):
        """Kills ``if recorded == "none":`` → ``if False:``."""
        _grants_file(tmp_path, _GRANT.format(expires_on="none"), monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": "none"})
        assert cc.findings == []

    def test_no_live_expiry_against_a_recorded_date_is_a_finding(
        self, tmp_path, monkeypatch
    ):
        """Kills ``if recorded == "none":`` → ``if True:``.

        The record and the token disagree about whether the token expires
        at all; one of them is wrong and Shawn has to decide which.
        """
        _grants_file(tmp_path, _GRANT.format(expires_on="2026-12-06"), monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": "none"})
        assert len(cc.findings) == 1
        assert "live token has no expiry" in cc.findings[0]

    def test_a_recorded_date_that_differs_from_the_live_one_is_a_finding(
        self, tmp_path, monkeypatch
    ):
        """Kills ``if recorded != expiry.isoformat():`` → ``if False:``."""
        live = dt.date.today() + dt.timedelta(days=90)
        _grants_file(tmp_path, _GRANT.format(expires_on="2020-01-01"), monkeypatch)
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": live})
        assert len(cc.findings) == 1
        assert "update the record" in cc.findings[0]

    def test_a_matching_date_well_in_the_future_is_clean(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ``if recorded != expiry.isoformat():`` → ``if True:``."""
        live = dt.date.today() + dt.timedelta(days=90)
        _grants_file(
            tmp_path, _GRANT.format(expires_on=live.isoformat()), monkeypatch
        )
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": live})
        assert cc.findings == []
        assert "(90 days)" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "days_left,expect_finding,marker",
        [
            (15, False, "(15 days)"),
            (14, True, "expires in 14 day(s)"),
            (0, True, "expires in 0 day(s)"),
            (-1, True, "token expired on"),
        ],
    )
    def test_the_expiry_warning_boundary(
        self, tmp_path, monkeypatch, capsys, days_left, expect_finding, marker
    ):
        """Kills ``elif days_left <= EXPIRY_WARNING_DAYS:`` → ``< …``, and
        ``if days_left < 0:`` → ``<= 0``.

        Fifteen days out is quiet, fourteen warns, and an already-expired
        token gets its own distinct wording rather than "expires in -1
        day(s)".
        """
        live = dt.date.today() + dt.timedelta(days=days_left)
        _grants_file(
            tmp_path, _GRANT.format(expires_on=live.isoformat()), monkeypatch
        )
        cc.check_grants({"GPT_GH_TOKEN": "abcfake"}, {"GPT_GH_TOKEN": live})
        assert bool(cc.findings) is expect_finding
        combined = capsys.readouterr().out + " ".join(cc.findings)
        assert marker in combined

    def test_an_empty_grants_table_is_reported_not_flagged(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ``if not grants: return`` → falling through to the loop."""
        _grants_file(tmp_path, "schema_version = 2\n", monkeypatch)
        cc.check_grants({}, {})
        assert cc.findings == []
        assert "no grants declared" in capsys.readouterr().out


# ============================================================================
# main — exit codes and the --env path
# ============================================================================


def _run_main(monkeypatch, argv: list[str]) -> int:
    """Invoke ``cc.main()`` with *argv* (excluding argv[0])."""
    monkeypatch.setattr(sys, "argv", ["check-credentials.py", *argv])
    return cc.main()


class TestMain:
    """Case 21 of the audit case list."""

    def test_a_missing_env_file_exits_one(self, tmp_path, monkeypatch, capsys):
        """Kills ``if not args.env.is_file(): return 1`` → ``return 0``.

        A checker that reports success when it read nothing is worse than
        no checker.
        """
        code = _run_main(monkeypatch, ["--env", str(tmp_path / "absent.env")])
        assert code == 1
        assert "No .env at" in capsys.readouterr().err

    def test_a_clean_file_exits_zero(self, tmp_path, monkeypatch, capsys):
        """Kills ``if findings: … return 1`` → ``return 1`` unconditionally.

        Every live read is stubbed; the OSF pass is the only one with a
        variable present, so a clean run must reach exit 0.
        """
        env = _env_file(tmp_path, "OSF_API_KEY=abcfake\n")
        monkeypatch.setattr(cc, "GRANTS_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(
            cc,
            "http_json",
            lambda url, headers: (
                200,
                {"data": {"attributes": {"full_name": "Fake User"}, "id": "aa11"}},
            ),
        )
        monkeypatch.setattr(
            cc, "http_get", lambda url, headers: pytest.fail(f"requested {url}")
        )
        code = _run_main(monkeypatch, ["--env", str(env)])
        out = capsys.readouterr().out
        assert code == 0, out
        assert "No findings" in out

    def test_any_finding_exits_one(self, tmp_path, monkeypatch, capsys):
        """Kills ``if findings:`` → ``if False:`` in the summary block."""
        env = _env_file(tmp_path, f"bad-name={FAKE_SECRET}\nOSF_API_KEY=abcfake\n")
        monkeypatch.setattr(cc, "GRANTS_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(
            cc,
            "http_json",
            lambda url, headers: (
                200,
                {"data": {"attributes": {"full_name": "Fake User"}, "id": "aa11"}},
            ),
        )
        monkeypatch.setattr(
            cc, "http_get", lambda url, headers: pytest.fail(f"requested {url}")
        )
        code = _run_main(monkeypatch, ["--env", str(env)])
        out = capsys.readouterr().out
        assert code == 1
        assert "finding(s):" in out
        assert FAKE_SECRET not in out

    def test_the_env_argument_is_the_file_that_is_read(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ignoring ``--env`` and falling back to the default path.

        The default is ``~/personal-assistant/.env``; this suite must never
        touch it, and the argument is the only thing standing between the
        two.
        """
        env = _env_file(tmp_path, "GOOD=abcfake\n")
        seen: list[Path] = []
        real_parse = cc.parse_env
        monkeypatch.setattr(
            cc, "parse_env", lambda path: (seen.append(path), real_parse(path))[1]
        )
        monkeypatch.setattr(cc, "GRANTS_FILE", tmp_path / "absent.toml")
        monkeypatch.setattr(
            cc, "http_json", lambda url, headers: (0, "stubbed; no network")
        )
        monkeypatch.setattr(
            cc, "http_get", lambda url, headers: pytest.fail(f"requested {url}")
        )
        _run_main(monkeypatch, ["--env", str(env)])
        assert seen == [env]
        assert str(env) in capsys.readouterr().out


# ============================================================================
# check_zotero and check_osf — pass 3, with http_json substituted (no network)
# ============================================================================


def _stub_http_json(monkeypatch, handler):
    """Replace ``cc.http_json`` with *handler*, recording the URLs it sees.

    *handler* takes a URL and returns ``(status, body)``. Any URL it does
    not recognise must raise, so a real request cannot slip through.
    """
    calls: list[str] = []

    def _json(url: str, headers: dict[str, str]):
        calls.append(url)
        return handler(url)

    monkeypatch.setattr(cc, "http_json", _json)
    return calls


def _zotero_key_body(user_id: int = 4242, groups: dict | None = None) -> dict:
    """A ``/keys/current`` body in the shape the Zotero API returns."""
    return {
        "userID": user_id,
        "access": {
            "user": {"library": True, "write": True},
            "groups": groups if groups is not None else {"9001": {"write": False}},
        },
    }


class TestCheckOsf:
    """Audit round two M5: check_osf had no tests at all."""

    def test_an_absent_key_is_a_finding(self, monkeypatch, capsys):
        """Kills ``if not token: note(...); return`` -> a silent return.

        Two scripts depend on the OSF token; a missing one must not read as
        a clean bill of health.
        """
        _stub_http_json(
            monkeypatch, lambda url: pytest.fail(f"requested {url} with no token")
        )
        cc.check_osf({})
        assert len(cc.findings) == 1
        assert "OSF_API_KEY absent" in cc.findings[0]

    def test_a_successful_authentication_reports_the_account(
        self, monkeypatch, capsys
    ):
        """Kills ``if status == 200 …`` -> ``if False:`` (every run a finding).

        Also pins that the account, not the token, is what gets printed.
        """
        body = {"data": {"attributes": {"full_name": "Fake User"}, "id": "aa11"}}
        _stub_http_json(monkeypatch, lambda url: (200, body))
        cc.check_osf({"OSF_API_KEY": FAKE_SECRET})
        out = capsys.readouterr().out
        assert cc.findings == []
        assert "'Fake User'" in out
        assert "aa11" in out
        assert FAKE_SECRET not in out

    def test_an_authentication_failure_is_a_finding(self, monkeypatch, capsys):
        """Kills ``if status == 200 …`` -> ``if True:``.

        A revoked or expired token would otherwise be reported as OK, and
        the failure would surface only when a publish run died.
        """
        _stub_http_json(monkeypatch, lambda url: (401, "Unauthorized"))
        cc.check_osf({"OSF_API_KEY": FAKE_SECRET})
        assert len(cc.findings) == 1
        assert "OSF_API_KEY: authentication failed (401)" in cc.findings[0]
        assert FAKE_SECRET not in capsys.readouterr().out

    def test_the_bearer_header_carries_the_token(self, monkeypatch):
        """Kills sending the token in the wrong header (or not at all).

        The check would then fail for every token and the finding would be
        about the checker, not the credential.
        """
        seen: list[dict] = []

        def _json(url: str, headers: dict[str, str]):
            seen.append(headers)
            return 200, {"data": {"attributes": {"full_name": "F"}, "id": "i"}}

        monkeypatch.setattr(cc, "http_json", _json)
        cc.check_osf({"OSF_API_KEY": "abcfake"})
        assert seen[0]["Authorization"] == "Bearer abcfake"


class TestCheckZotero:
    """Audit round two M5: check_zotero had no tests at all."""

    def test_no_keys_present_is_not_a_finding(self, monkeypatch, capsys):
        """Kills ``if not key_vars: … return`` -> falling through.

        A machine with no Zotero keys is a normal state, not a fault, and
        falling through would issue requests with no key at all.
        """
        calls = _stub_http_json(monkeypatch, lambda url: (200, {}))
        cc.check_zotero({"OSF_API_KEY": "x"})
        assert cc.findings == []
        assert calls == []
        assert "none present" in capsys.readouterr().out

    def test_an_authentication_failure_is_a_finding(self, monkeypatch):
        """Kills ``if status != 200 …`` -> ``if False:``.

        A dead Zotero key must be named; the /cite and /read commands fail
        opaquely without it.
        """
        _stub_http_json(monkeypatch, lambda url: (403, "Forbidden"))
        cc.check_zotero({"ZOTERO_API_KEY_READ": FAKE_SECRET})
        assert len(cc.findings) == 1
        assert "ZOTERO_API_KEY_READ: authentication failed (403)" in cc.findings[0]

    def test_the_key_scope_is_reported_without_the_key(self, monkeypatch, capsys):
        """Kills printing the key alongside its scope.

        The scope report is the reason this pass exists — it is also the
        place a key value would most naturally be interpolated.
        """
        _stub_http_json(
            monkeypatch,
            lambda url: (200, _zotero_key_body())
            if url.endswith("/keys/current")
            else (200, []),
        )
        cc.check_zotero({"ZOTERO_API_KEY_READ": FAKE_SECRET})
        out = capsys.readouterr().out
        assert "ZOTERO_API_KEY_READ: OK (user 4242)" in out
        assert "personal: read+write" in out
        assert FAKE_SECRET not in out

    def test_write_access_to_all_groups_is_a_finding(self, monkeypatch):
        """Kills ``if "all" in writable:`` -> ``if False:``.

        A key named for one group that can write to every group is the
        over-scoping this pass exists to surface.
        """
        body = _zotero_key_body(groups={"all": {"write": True}})
        _stub_http_json(
            monkeypatch,
            lambda url: (200, body) if url.endswith("/keys/current") else (200, []),
        )
        cc.check_zotero({"ZOTERO_API_KEY_GROUP": "abcfake"})
        assert len(cc.findings) == 1
        assert "write access to ALL groups" in cc.findings[0]

    def test_a_library_id_mismatch_is_a_finding(self, monkeypatch):
        """Kills the ``str(body.get("userID")) != library_id`` comparison.

        A key belonging to a different Zotero account reads every request
        against the wrong library, silently.
        """

        def _handler(url: str):
            if url.endswith("/keys/current"):
                return 200, _zotero_key_body(user_id=4242)
            if "/items?limit=1" in url:
                return 200, []
            return 200, []

        _stub_http_json(monkeypatch, _handler)
        cc.check_zotero(
            {"ZOTERO_API_KEY_READ": "abcfake", "ZOTERO_LIBRARY_ID": "9999"}
        )
        assert any("userID 4242 != ZOTERO_LIBRARY_ID 9999" in f for f in cc.findings)

    def test_an_unresolvable_collection_key_is_a_finding(self, monkeypatch):
        """Kills ``if where is None: note(...)`` -> a silent skip.

        A stale collection key sends every filed reference into nothing;
        the failure is otherwise invisible until a citation goes missing.
        """

        def _handler(url: str):
            if url.endswith("/keys/current"):
                return 200, _zotero_key_body()
            if "/items?limit=1" in url:
                return 200, []
            if "/groups?limit=100" in url:
                return 200, []
            if "/collections/" in url:
                return 404, "Not Found"
            raise AssertionError(f"unexpected URL: {url}")

        _stub_http_json(monkeypatch, _handler)
        cc.check_zotero(
            {
                "ZOTERO_API_KEY_READ": "abcfake",
                "ZOTERO_LIBRARY_ID": "4242",
                "PAPER_COLLECTION": "ABCD1234",
            }
        )
        assert any(
            "PAPER_COLLECTION=ABCD1234: not found" in f for f in cc.findings
        )

    def test_a_collection_key_found_in_a_group_is_reported(
        self, monkeypatch, capsys
    ):
        """Kills the group-search fallback in the collection loop.

        Most collection keys live in shared groups rather than the personal
        library; without the fallback every one of them is a false finding.
        """
        collection = {
            "data": {"name": "Fake Collection"},
            "meta": {"numItems": 7},
        }

        def _handler(url: str):
            if url.endswith("/keys/current"):
                return 200, _zotero_key_body()
            if "/items?limit=1" in url:
                return 200, []
            if "/groups?limit=100" in url:
                return 200, [{"id": 5150, "data": {"name": "Fake Group"}}]
            if "/users/4242/collections/" in url:
                return 404, "Not Found"
            if "/groups/5150/collections/" in url:
                return 200, collection
            raise AssertionError(f"unexpected URL: {url}")

        _stub_http_json(monkeypatch, _handler)
        cc.check_zotero(
            {
                "ZOTERO_API_KEY_READ": "abcfake",
                "ZOTERO_LIBRARY_ID": "4242",
                "PAPER_COLLECTION": "ABCD1234",
            }
        )
        out = capsys.readouterr().out
        assert cc.findings == []
        assert "'Fake Collection'" in out
        assert "7 items" in out
        assert "group 5150 (Fake Group)" in out


class TestMainWiring:
    """Audit round two M5: whole passes were deletable from main().

    Nothing asserted that ``main()`` calls ``check_shell_source``,
    ``check_zotero``, ``check_osf``, ``check_github``, or ``check_grants``,
    so any one of them could be removed and the checker would report a
    clean bill of health for the credential it no longer examined.
    """

    #: One distinctive marker per pass, chosen so no other pass can produce
    #: it. If a call is deleted from main(), its marker disappears.
    MARKERS = {
        "parse_env": "not a plain shell identifier",
        "check_shell_source": "line(s) of output",
        "check_zotero": "ZOTERO_API_KEY_READ: authentication failed",
        "check_osf": "OSF_API_KEY: authentication failed",
        "check_github": "GH_TOKEN: authentication failed",
        "check_grants": "absent or empty in .env",
    }

    @staticmethod
    def _stage(tmp_path, monkeypatch):
        """Build an env, grants file, and stubs that make every pass speak."""
        env = _env_file(
            tmp_path,
            "bad-name=abcfake\n"
            "ZOTERO_API_KEY_READ=abcfake\n"
            "OSF_API_KEY=abcfake\n"
            "GH_TOKEN=ghp_abcfake\n",
        )
        grants = tmp_path / "credential-grants.toml"
        grants.write_text(
            'schema_version = 2\n\n'
            '[[grants]]\n'
            'id = "g1"\n'
            'source_name = "ABSENT_VAR"\n'
            'inject_as = "GH_TOKEN"\n'
            'expires_on = "none"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(cc, "GRANTS_FILE", grants)

        def _json(url: str, headers: dict[str, str]):
            if "api.zotero.org" in url:
                return 401, "Unauthorized"
            if "api.osf.io" in url:
                return 401, "Unauthorized"
            raise AssertionError(f"unexpected URL: {url}")

        def _get(url: str, headers: dict[str, str]):
            if "api.github.com" in url:
                return 401, "Bad credentials", {}
            raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr(cc, "http_json", _json)
        monkeypatch.setattr(cc, "http_get", _get)
        return env

    def test_every_pass_is_wired_into_main(self, tmp_path, monkeypatch, capsys):
        """Kills deleting any one of the five pass calls from main().

        Each pass is given exactly one thing to complain about, and each
        complaint is unique to it, so a missing call shows up as a missing
        marker rather than as a smaller total.
        """
        env = self._stage(tmp_path, monkeypatch)
        code = _run_main(monkeypatch, ["--env", str(env)])
        out = capsys.readouterr().out

        assert code == 1
        combined = out + "\n".join(cc.findings)
        missing = [
            pass_name
            for pass_name, marker in self.MARKERS.items()
            if marker not in combined
        ]
        assert not missing, f"these passes did not run: {missing}\n{out}"
        assert len(cc.findings) == len(self.MARKERS)

    def test_the_summary_lists_every_finding_and_counts_them(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills dropping the ``for f in findings: print(...)`` summary loop.

        The inline FINDING lines are interleaved with pass output; the
        summary is what the operator actually reads, and a count without
        the list is not actionable.
        """
        env = self._stage(tmp_path, monkeypatch)
        _run_main(monkeypatch, ["--env", str(env)])
        out = capsys.readouterr().out

        assert f"{len(cc.findings)} finding(s):" in out
        summary = out.split("finding(s):", 1)[1]
        for marker in self.MARKERS.values():
            assert marker in summary, f"{marker!r} missing from the summary"

    def test_the_github_expiries_reach_the_grant_cross_check(
        self, tmp_path, monkeypatch, capsys
    ):
        """Kills ``check_grants(env, expiries)`` -> ``check_grants(env, {})``.

        The cross-check's whole purpose is comparing the recorded expiry
        with the live one; handed an empty map it silently degrades to
        "present (N chars)" for every grant and never disagrees with the
        record.
        """
        live = dt.date.today() + dt.timedelta(days=90)
        env = _env_file(tmp_path, "GPT_GH_TOKEN=github_pat_abcfake\n")
        grants = tmp_path / "credential-grants.toml"
        grants.write_text(
            'schema_version = 2\n\n'
            '[[grants]]\n'
            'id = "g1"\n'
            'source_name = "GPT_GH_TOKEN"\n'
            'inject_as = "GH_TOKEN"\n'
            'expires_on = "2020-01-01"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(cc, "GRANTS_FILE", grants)
        monkeypatch.setattr(
            cc, "http_json", lambda url, headers: pytest.fail(f"requested {url}")
        )

        def _get(url: str, headers: dict[str, str]):
            if url.endswith("/user"):
                return (
                    200,
                    {"login": "saross"},
                    {
                        "github-authentication-token-expiration":
                            f"{live.isoformat()} 03:14:07 UTC"
                    },
                )
            return 200, {"permissions": {"push": True, "pull": True}}, {}

        monkeypatch.setattr(cc, "http_get", _get)
        code = _run_main(monkeypatch, ["--env", str(env)])
        out = capsys.readouterr().out

        assert code == 1
        assert any("update the record" in f for f in cc.findings), out
        assert live.isoformat() in out


class TestParseEnvFinalLine:
    """Audit round three M2: a file whose last line has no terminator."""

    def test_a_single_line_without_a_trailing_newline_parses(self, tmp_path):
        """Kills dropping ``|$`` from ``_LINE_SPLIT``.

        Without that branch the regex matches nothing on a file with no
        final terminator, so ``ZOTERO_API_KEY=abc`` parses to ``{}`` with
        zero findings — the checker reports a clean bill of health for a
        file it did not read. Editors that omit the final newline are
        common enough that no test had ever written one.
        """
        path = tmp_path / "no-newline.env"
        path.write_bytes(b"ZOTERO_API_KEY=abcfake")
        env = cc.parse_env(path)
        assert env == {"ZOTERO_API_KEY": "abcfake"}
        assert cc.findings == []

    def test_a_two_line_file_without_a_trailing_newline_parses(self, tmp_path):
        """Kills a split that keeps only the terminated lines.

        The second line is the one that disappears, so a one-line fixture
        alone would not notice.
        """
        path = tmp_path / "no-newline.env"
        path.write_bytes(b"FIRST_VAR=one\nSECOND_VAR=two")
        env = cc.parse_env(path)
        assert env == {"FIRST_VAR": "one", "SECOND_VAR": "two"}
        assert cc.findings == []

    def test_a_malformed_final_line_without_a_newline_is_still_flagged(
        self, tmp_path
    ):
        """Kills the same mutation at the finding level, not just the dict.

        A file ending mid-line is exactly where a hand-edit goes wrong, so
        the last line is the one that most needs checking.
        """
        path = tmp_path / "no-newline.env"
        path.write_bytes(b"GOOD_VAR=one\nbad-name=two")
        cc.parse_env(path)
        assert len(cc.findings) == 1
        assert cc.findings[0].startswith("line 2:")
