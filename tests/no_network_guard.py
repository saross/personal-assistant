"""
A socket-level network guard for test modules that touch external services.

The suite's shared fixtures guard the database driver but not, at the time
of writing, the socket layer, so an escaped Hypertext Transfer Protocol
(HTTP) call in a test of ``lit-search.py`` or the Zotero importer would
reach the internet and quietly pass. Test modules in this tranche install
the guard below as an autouse fixture:

    @pytest.fixture(autouse=True)
    def _no_network(monkeypatch):
        refuse_socket_connections(monkeypatch)

It is deliberately independent of the shared conftest: if a repository-wide
socket guard lands there later, this one becomes redundant rather than
wrong.
"""

from __future__ import annotations

import socket
from typing import Any, NoReturn


class NetworkAccessAttempted(AssertionError):
    """Raised when a hermetic test tries to open a network connection."""


def refuse_socket_connections(monkeypatch: Any) -> None:
    """
    Make every outbound socket connection raise ``NetworkAccessAttempted``.

    Patches the three entry points the standard library, ``httpx``, and
    ``urllib`` actually use: ``socket.socket.connect``,
    ``socket.socket.connect_ex``, and ``socket.create_connection``.

    Args:
        monkeypatch: The pytest ``monkeypatch`` fixture, so the patches are
            undone at the end of the test.
    """

    def _refuse(*args: Any, **kwargs: Any) -> NoReturn:
        raise NetworkAccessAttempted(
            "a test attempted a network connection; stub the transport "
            "boundary instead"
        )

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
