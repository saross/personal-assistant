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

    def test_a_whitespace_only_value_is_not_flagged(self, tmp_path):
        """Kills dropping the ``value and`` guard on the same check.

        ``NAME=   `` assigns the empty string in bash and runs nothing, so
        there is no leak and no finding to raise.
        """
        cc.parse_env(_env_file(tmp_path, "EMPTY_VALUE=   \n"))
        assert cc.findings == []


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

    def test_a_quote_that_does_not_close_the_value_is_flagged(self, tmp_path):
        """Kills reverting ``quoted`` to ``raw_value[:1] in ('"', "'")``.

        This is the second defect fixed on 2026-09-08. For
        ``TOKEN='abc' # trailing comment`` bash assigns ``abc`` while this
        parser assigns ``abc' # trailing comment`` — a real divergence that
        the "starts with a quote" guard suppressed, so no finding was
        raised at all. Verified against bash 5.
        """
        env = cc.parse_env(
            _env_file(tmp_path, "TOKEN='abcfake' # trailing comment\n")
        )
        assert len(cc.findings) == 1
        assert "has a '#' in its value" in cc.findings[0]
        # And the divergence itself: bash would have assigned "abcfake".
        assert env["TOKEN"] != "abcfake"

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
        assert f"{cc.GITHUB_PROBE_REPO}: push" in capsys.readouterr().out

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
