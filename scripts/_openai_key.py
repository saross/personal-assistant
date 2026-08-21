"""
Resolve the machine-appropriate OpenAI API key.

Background
----------
Paid-service credentials are deliberately issued per machine, so that either
workstation can be revoked without disturbing the other. For OpenAI this shows
up in ``.env`` as a suffixed name: ``OPENAI_API_KEY_PA_ZBOOK`` exists only on
zbook, ``OPENAI_API_KEY_PA_AMDT`` only on amd-tower. Each host holds its own
key and not the other's, which is the intended posture rather than a gap.

Two scripts used to read ``OPENAI_API_KEY_PA_AMDT`` unconditionally
(``bulk-archive.py`` and ``bake-off-metadata.py``). On amd-tower that worked;
on zbook it raised "not set" even though the machine held a perfectly good
credential under the ``_ZBOOK`` spelling. The failure was doubly unhelpful
because the error named the variable it wanted rather than the one that was
actually present, sending the reader looking for a missing key instead of a
mis-resolved name. Found during the 2026-08-22 cross-machine ``.env``
reconciliation; see ``wiki/docs/env-cross-machine-reference.md``.

What this module provides
-------------------------
1. :func:`host_suffix` — map a hostname to its ``.env`` suffix. Pure, so it is
   trivially testable against hostnames this machine does not have.
2. :func:`resolve_openai_key` — return the key for a given role on this host,
   or raise a :class:`RuntimeError` that says what was tried and what was
   found. Never includes a key value in its message.

Resolution order
----------------
1. ``OPENAI_API_KEY_<ROLE>`` — an unsuffixed override. Escape hatch for a
   container, a CI runner, or a new machine, and it wins over everything.
2. ``OPENAI_API_KEY_<ROLE>_<SUFFIX>``, where ``SUFFIX`` comes from
   ``OPENAI_KEY_SUFFIX`` if set, otherwise from the hostname.
3. Otherwise raise.

Adding a machine means adding one row to :data:`_HOST_SUFFIXES`. Until then
``OPENAI_KEY_SUFFIX=<SUFFIX>`` in the environment gets a new host working
without a code change.
"""

from __future__ import annotations

import os
import socket

__all__ = ["host_suffix", "resolve_openai_key", "KEY_PREFIX", "UnknownHostError"]

KEY_PREFIX = "OPENAI_API_KEY"

# Matched case-insensitively as substrings, so both a short hostname
# ("zbook-ubuntu") and an FQDN ("zbook-ubuntu.local") resolve, and amd-tower's
# mixed-case "AMD-tower-ubuntu" resolves the same as the doc's lowercase form.
# Order matters only if a hostname could match two entries; keep them distinct.
_HOST_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("zbook", "ZBOOK"),
    ("amd-tower", "AMDT"),
)


class UnknownHostError(RuntimeError):
    """Raised when a hostname maps to no known ``.env`` suffix."""


def host_suffix(hostname: str | None = None) -> str | None:
    """Return the ``.env`` key suffix for a hostname.

    Args:
        hostname: Hostname to map. Defaults to this machine's hostname.

    Returns:
        The suffix (for example ``"ZBOOK"``), or ``None`` if the hostname
        matches no known machine.
    """
    name = (hostname if hostname is not None else socket.gethostname()).lower()
    for fragment, suffix in _HOST_SUFFIXES:
        if fragment in name:
            return suffix
    return None


def _present_suffixes(role: str, env: dict[str, str]) -> list[str]:
    """List suffixes for which this environment actually holds a non-empty key.

    Used only to make the error message concrete: naming the credential the
    machine *does* hold is what turns "not set" from a dead end into a fix.
    """
    stem = f"{KEY_PREFIX}_{role}_"
    return sorted(
        name[len(stem):] for name, value in env.items()
        if name.startswith(stem) and value.strip()
    )


def resolve_openai_key(
    role: str = "PA",
    *,
    env: dict[str, str] | None = None,
    hostname: str | None = None,
) -> str:
    """Return the OpenAI API key for ``role`` on this machine.

    Args:
        role: Key role segment, uppercased. ``"PA"`` for personal-assistant
            work, ``"MR"`` for the other keyed role.
        env: Environment mapping to read. Defaults to ``os.environ``. Callers
            are expected to have hydrated it from ``.env`` already.
        hostname: Override the hostname used for suffix resolution. Intended
            for tests.

    Returns:
        The key, whitespace-stripped.

    Raises:
        UnknownHostError: The hostname maps to no known suffix and no override
            was given.
        RuntimeError: A suffix resolved but no key is set for it.
    """
    environ = os.environ if env is None else env
    role = role.upper()

    # 1. Unsuffixed override wins outright.
    override = environ.get(f"{KEY_PREFIX}_{role}", "").strip()
    if override:
        return override

    # 2. Explicit suffix, else hostname.
    suffix = environ.get("OPENAI_KEY_SUFFIX", "").strip().upper() or host_suffix(hostname)
    if not suffix:
        known = ", ".join(s for _, s in _HOST_SUFFIXES)
        raise UnknownHostError(
            f"Hostname {socket.gethostname()!r} maps to no known "
            f"{KEY_PREFIX}_{role}_* suffix (known: {known}). Set "
            f"OPENAI_KEY_SUFFIX to one of those, or set {KEY_PREFIX}_{role} "
            f"directly, or add the machine to _HOST_SUFFIXES in "
            f"scripts/_openai_key.py."
        )

    var = f"{KEY_PREFIX}_{role}_{suffix}"
    key = environ.get(var, "").strip()
    if key:
        return key

    # 3. Nothing usable. Say what is actually present, so a mis-resolved suffix
    #    is distinguishable from a genuinely absent credential.
    available = _present_suffixes(role, dict(environ))
    if available:
        detail = (
            f"but this environment does hold {KEY_PREFIX}_{role}_"
            f"{{{','.join(available)}}}. Paid keys are issued per machine, so "
            f"if you meant to run here, issue a key for {suffix} rather than "
            f"copying another machine's."
        )
    else:
        detail = f"and no {KEY_PREFIX}_{role}_* key is set at all."
    raise RuntimeError(
        f"{var} not set (expected in personal-assistant/.env) {detail}"
    )
