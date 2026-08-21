"""
Tests for scripts/_openai_key.py — per-machine OpenAI key resolution.

Paid keys are issued per machine, so the ``.env`` variable carries a host
suffix (``OPENAI_API_KEY_PA_ZBOOK`` / ``..._AMDT``). Two scripts used to read
the amd-tower spelling unconditionally and so could not run on zbook at all,
despite zbook holding a usable credential. These tests pin the resolution
order, the hostname mapping, and — the part that made the original bug hard to
read — that the error names the credential the environment actually holds.

Every environment here is a plain dict passed in explicitly, so no test can
touch a real key or depend on which machine it runs on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from _openai_key import (  # noqa: E402
    UnknownHostError,
    host_suffix,
    resolve_openai_key,
)


class TestHostSuffix:
    """Hostname to suffix mapping."""

    @pytest.mark.parametrize(
        "hostname,expected",
        [
            ("zbook-ubuntu", "ZBOOK"),
            ("AMD-tower-ubuntu", "AMDT"),  # Real hostname is mixed case.
            ("amd-tower-ubuntu", "AMDT"),  # The docs write it lowercase.
            ("ZBOOK-UBUNTU", "ZBOOK"),
            ("zbook-ubuntu.local", "ZBOOK"),  # FQDN form.
            ("amd-tower", "AMDT"),  # SSH alias form.
        ],
    )
    def test_known_hosts_resolve(self, hostname, expected):
        assert host_suffix(hostname) == expected

    @pytest.mark.parametrize("hostname", ["sapphire", "rpi-server", "runner-01", ""])
    def test_unknown_hosts_return_none(self, hostname):
        assert host_suffix(hostname) is None


class TestResolutionOrder:
    """Which variable wins, and when."""

    def test_suffixed_key_resolves_from_hostname(self):
        env = {"OPENAI_API_KEY_PA_ZBOOK": "zbook-secret"}
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "zbook-secret"

    def test_same_env_different_host_picks_different_key(self):
        """The regression this module exists to prevent."""
        env = {
            "OPENAI_API_KEY_PA_ZBOOK": "zbook-secret",
            "OPENAI_API_KEY_PA_AMDT": "amdt-secret",
        }
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "zbook-secret"
        assert resolve_openai_key("PA", env=env, hostname="AMD-tower-ubuntu") == "amdt-secret"

    def test_unsuffixed_override_wins(self):
        env = {
            "OPENAI_API_KEY_PA": "override",
            "OPENAI_API_KEY_PA_ZBOOK": "zbook-secret",
        }
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "override"

    def test_override_works_on_an_unknown_host(self):
        """The escape hatch must not need the hostname to be known."""
        env = {"OPENAI_API_KEY_PA": "override"}
        assert resolve_openai_key("PA", env=env, hostname="some-ci-runner") == "override"

    def test_explicit_suffix_beats_hostname(self):
        env = {"OPENAI_KEY_SUFFIX": "amdt", "OPENAI_API_KEY_PA_AMDT": "amdt-secret"}
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "amdt-secret"

    def test_explicit_suffix_rescues_an_unknown_host(self):
        env = {"OPENAI_KEY_SUFFIX": "ZBOOK", "OPENAI_API_KEY_PA_ZBOOK": "zbook-secret"}
        assert resolve_openai_key("PA", env=env, hostname="brand-new-box") == "zbook-secret"

    def test_role_is_honoured(self):
        env = {
            "OPENAI_API_KEY_PA_ZBOOK": "pa-secret",
            "OPENAI_API_KEY_MR_ZBOOK": "mr-secret",
        }
        assert resolve_openai_key("MR", env=env, hostname="zbook-ubuntu") == "mr-secret"

    def test_role_is_case_insensitive(self):
        env = {"OPENAI_API_KEY_PA_ZBOOK": "pa-secret"}
        assert resolve_openai_key("pa", env=env, hostname="zbook-ubuntu") == "pa-secret"

    def test_value_is_stripped(self):
        env = {"OPENAI_API_KEY_PA_ZBOOK": "  padded  "}
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "padded"

    def test_whitespace_only_counts_as_absent(self):
        env = {"OPENAI_API_KEY_PA_ZBOOK": "   "}
        with pytest.raises(RuntimeError):
            resolve_openai_key("PA", env=env, hostname="zbook-ubuntu")

    def test_empty_override_falls_through_to_suffixed(self):
        env = {"OPENAI_API_KEY_PA": "", "OPENAI_API_KEY_PA_ZBOOK": "zbook-secret"}
        assert resolve_openai_key("PA", env=env, hostname="zbook-ubuntu") == "zbook-secret"


class TestErrors:
    """The messages have to be actionable, and must never leak a key."""

    def test_unknown_host_raises_unknown_host_error(self):
        with pytest.raises(UnknownHostError) as exc:
            resolve_openai_key("PA", env={}, hostname="sapphire")
        assert "OPENAI_KEY_SUFFIX" in str(exc.value)
        assert "_HOST_SUFFIXES" in str(exc.value)

    def test_missing_key_names_what_is_present(self):
        """The original bug: 'not set' whilst a usable key sat right there."""
        env = {"OPENAI_API_KEY_PA_AMDT": "amdt-secret"}
        with pytest.raises(RuntimeError) as exc:
            resolve_openai_key("PA", env=env, hostname="zbook-ubuntu")
        message = str(exc.value)
        assert "OPENAI_API_KEY_PA_ZBOOK not set" in message
        assert "AMDT" in message  # Names the credential that does exist.

    def test_missing_key_says_so_plainly_when_nothing_is_set(self):
        with pytest.raises(RuntimeError) as exc:
            resolve_openai_key("PA", env={}, hostname="zbook-ubuntu")
        assert "no OPENAI_API_KEY_PA_* key is set at all" in str(exc.value)

    def test_error_never_contains_a_key_value(self):
        env = {
            "OPENAI_API_KEY_PA_AMDT": "sk-secret-value-do-not-leak",
            "OPENAI_API_KEY_MR_AMDT": "sk-another-secret",
        }
        with pytest.raises(RuntimeError) as exc:
            resolve_openai_key("PA", env=env, hostname="zbook-ubuntu")
        message = str(exc.value)
        assert "sk-secret-value-do-not-leak" not in message
        assert "sk-another-secret" not in message

    def test_error_does_not_advertise_another_roles_key(self):
        """A missing PA key must not point the reader at an MR credential."""
        env = {"OPENAI_API_KEY_MR_ZBOOK": "mr-secret"}
        with pytest.raises(RuntimeError) as exc:
            resolve_openai_key("PA", env=env, hostname="zbook-ubuntu")
        assert "no OPENAI_API_KEY_PA_* key is set at all" in str(exc.value)
