"""
Shared helpers for the ``scripts/style-analyser/`` test files.

Not a test module (the name deliberately does not match ``test_*.py``, so
pytest does not collect it). It provides the three things every style-analyser
test file needs:

* :func:`load_style_module` — import one of the tranche's scripts by name,
  with the scripts directory on ``sys.path`` the way the scripts themselves
  arrange it when run directly.
* :func:`refuse_sockets` — the body of each test file's autouse
  network-refusal fixture. None of these scripts makes a network call and the
  audit's remit is to keep it that way, so a test that provokes one fails
  loudly instead of quietly reaching the internet.
* :class:`FakeNlp` — a scripted stand-in for a spaCy pipeline. spaCy is not
  installed in this repository's virtual environment, and the corpus text the
  real model would run over is private, so every spaCy-consuming function is
  exercised through an injected fake whose tags and dependencies are written
  out by hand in the test.
"""

from __future__ import annotations

import importlib
import socket
import sys
from pathlib import Path

#: The tranche under test. Resolved from ``__file__`` rather than ``~`` so the
#: suite's repointed HOME (see ``tests/conftest.py``) cannot send it astray.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "style-analyser"

#: Synthetic fixture data shared across the style-analyser test files.
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "style"


def load_style_module(name: str):
    """Import ``scripts/style-analyser/<name>.py`` and return the module.

    The scripts import each other as flat siblings (``import phase1_pipeline``),
    so the directory goes on ``sys.path`` exactly once, ahead of anything else.
    """
    path = str(SCRIPTS_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(name)


def refuse_sockets(monkeypatch) -> None:
    """Make any socket use in this test raise, rather than reach the network.

    Called from an autouse fixture in each style-analyser test file. The
    scripts under test are CPU-only by design — no LLM, no Ollama, no HTTP —
    and a future edit that quietly adds a call should fail the suite rather
    than succeed against a live service.
    """
    def refuse(*args, **kwargs):
        raise AssertionError(
            "this test tried to open a network connection; the style-analyser "
            "scripts are CPU-only and must make no network call"
        )

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeToken:
    """One token of a scripted document, in the shape spaCy's Token exposes."""

    def __init__(self, text: str, pos: str = "NOUN", dep: str = "dep",
                 lemma: str | None = None, is_space: bool = False) -> None:
        self.text = text
        self.pos_ = pos
        self.dep_ = dep
        self.lemma_ = lemma if lemma is not None else text.lower()
        self.is_space = is_space
        self.head = self          # rewritten by :meth:`FakeSent.link`
        self.children: list["FakeToken"] = []

    def __repr__(self) -> str:  # pragma: no cover — debugging aid only
        return f"FakeToken({self.text!r}, pos={self.pos_}, dep={self.dep_})"


class FakeSent:
    """One scripted sentence: a token list plus its dependency wiring."""

    def __init__(self, tokens: list[FakeToken]) -> None:
        self.tokens = tokens

    def __iter__(self):
        return iter(self.tokens)

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

    def link(self, child_index: int, head_index: int) -> "FakeSent":
        """Attach token ``child_index`` under token ``head_index``."""
        child = self.tokens[child_index]
        head = self.tokens[head_index]
        child.head = head
        head.children.append(child)
        return self


class FakeNlp:
    """A callable that returns a pre-scripted document, ignoring its input.

    Real spaCy is unavailable here and its corpus input is private, so the
    tests hand the pipeline the document they want it to see. ``max_length``
    and ``select_pipes`` exist only because the production callers set them.
    """

    def __init__(self, sents: list[FakeSent]) -> None:
        self._sents = sents
        self.max_length = 0
        self.meta = {"version": "3.8.0"}
        self.calls: list[str] = []

    def __call__(self, text: str) -> "FakeDoc":
        self.calls.append(text)
        return FakeDoc(self._sents)

    def select_pipes(self, disable=None):  # pragma: no cover — no-op shim
        """Accept the production call; there are no pipes to disable."""
        return None


class FakeDoc:
    """The document object ``FakeNlp`` returns: iterable, with ``.sents``."""

    def __init__(self, sents: list[FakeSent]) -> None:
        self.sents = sents

    def __iter__(self):
        for sent in self.sents:
            yield from sent
