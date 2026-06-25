"""Behavioural tests for the lit-scout Zotero importer's field sourcing.

These tests pin the "authoritative source" contract for two fields that
``build_zotero_item`` writes into a staged Zotero item:

  * **Title** — registry-first (FIX 1(a), 2026-06-26). The registry
    record's ``title`` carries the full, untruncated title; the proposer's
    claims ``title`` is only a fallback when the registry has none. This
    prevents a proposer-truncated title (scored merely PARTIAL by the
    verifier, and therefore never corrected back into ``claims.jsonl``)
    from silently landing in Zotero. In the 2026-06-25 run, 8 of 24 titles
    were truncated and only a manual patch avoided corruption.
  * **Authors** — registry-first (the pre-existing contract; covered here
    as a regression guard so the FIX 1(a) title change did not perturb it).

The registry record (a CrossRef-``message``-style dict) and the claims
dict are stubbed inline; no network calls are made.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Load the importer module by path. It lives under ``scripts/`` with a
# hyphenated filename (not an importable package name), so we load it via
# an explicit spec rather than a plain ``import``.
# ---------------------------------------------------------------------------
_IMPORTER_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "lit-scout-zotero-import.py"
)
_spec = importlib.util.spec_from_file_location(
    "lit_scout_zotero_import", _IMPORTER_PATH
)
assert _spec is not None and _spec.loader is not None
_importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_importer)

build_zotero_item = _importer.build_zotero_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _claims(
    *,
    title: Any = "claims title",
    include_title: bool = True,
    authors: Any = "Proposer, A. (2022)",
    include_authors: bool = True,
) -> dict[str, dict]:
    """Build a minimal ``claims_for_doi`` mapping.

    Each claim category maps to a dict carrying a ``value`` key, matching the
    shape ``group_claims_by_doi`` produces. ``include_*`` toggles let a test
    omit a category entirely (distinct from supplying ``value=None``).
    """
    claims: dict[str, dict] = {"year": {"value": 2022}}
    if include_title:
        claims["title"] = {"value": title}
    if include_authors:
        claims["authors"] = {"value": authors}
    return claims


def _crossref(
    *,
    title: Any = "Registry Title",
    author: list[dict] | None = None,
) -> dict:
    """Build a minimal CrossRef-``message``-style registry record.

    ``title`` is wrapped in a list to match CrossRef's array shape; pass an
    empty list or ``None`` to model a record with no title.
    """
    msg: dict[str, Any] = {"type": "journal-article"}
    if title is None:
        # Model "key present but empty list" — the importer's
        # ``(crossref_msg.get("title") or [""])[0]`` should yield "".
        msg["title"] = []
    else:
        msg["title"] = [title]
    if author is not None:
        msg["author"] = author
    return msg


def _build(claims: dict[str, dict], crossref: dict) -> dict:
    """Invoke ``build_zotero_item`` with inert defaults for the rest."""
    return build_zotero_item(
        doi="10.1000/test",
        claims_for_doi=claims,
        crossref_msg=crossref,
        table_row={},
        corrections_for_doi={},
        run_timestamp="20260626-000000",
        subcollection_key="ABCD1234",
    )


# ---------------------------------------------------------------------------
# FIX 1(a): title is registry-first
# ---------------------------------------------------------------------------
def test_registry_title_wins_over_truncated_claims_title() -> None:
    """A present registry title overrides a truncated claims title."""
    claims = _claims(title="A truncated proposer titl")  # noqa: deliberate
    crossref = _crossref(
        title="A Truncated Proposer Title That Goes The Full Distance"
    )
    item = _build(claims, crossref)
    assert item["title"] == (
        "A Truncated Proposer Title That Goes The Full Distance"
    )


def test_claims_title_used_when_registry_title_empty_list() -> None:
    """An empty registry title list falls back to the claims title."""
    claims = _claims(title="Sole Surviving Claims Title")
    crossref = _crossref(title=None)  # -> "title": []
    item = _build(claims, crossref)
    assert item["title"] == "Sole Surviving Claims Title"


def test_claims_title_used_when_registry_title_absent() -> None:
    """A registry record with no ``title`` key falls back to the claim."""
    claims = _claims(title="Fallback Claims Title")
    crossref = {"type": "journal-article"}  # no "title" key at all
    item = _build(claims, crossref)
    assert item["title"] == "Fallback Claims Title"


def test_empty_registry_title_does_not_clobber_usable_claims_title() -> None:
    """An empty-string registry title must not win over a usable claim.

    Models a registry record whose title array contains a single empty
    string (rather than being absent), which is falsy and so must defer to
    the claims title rather than writing a blank title into Zotero.
    """
    claims = _claims(title="Real Title From Claims")
    crossref = _crossref(title="")  # -> "title": [""]
    item = _build(claims, crossref)
    assert item["title"] == "Real Title From Claims"


def test_absent_claims_title_yields_empty_when_registry_also_empty() -> None:
    """No registry title and no claims title key → empty title, not error."""
    claims = _claims(include_title=False)
    crossref = _crossref(title=None)  # -> "title": []
    item = _build(claims, crossref)
    assert item["title"] == ""


def test_empty_claims_correction_preserved_when_registry_empty() -> None:
    """An explicit empty claims correction is preserved over a blank registry.

    Mirrors the importer's documented care with empty corrections: when the
    registry title is empty and the claims ``value`` is the empty string
    (a deliberate correction, not an absent value), the empty string is
    kept rather than coerced to anything else.
    """
    claims = _claims(title="")  # explicit empty correction
    crossref = _crossref(title=None)  # -> "title": []
    item = _build(claims, crossref)
    assert item["title"] == ""


# ---------------------------------------------------------------------------
# Regression: authors remain registry-first
# ---------------------------------------------------------------------------
def test_authors_remain_registry_first() -> None:
    """The structured registry author list wins over the claims string.

    Guards the pre-existing authors contract against regression from the
    FIX 1(a) title change: the registry's ordered ``author`` list must be
    written as creators, not the proposer's short display rendering.
    """
    claims = _claims(authors="Wrongname, X. (2022)")
    crossref = _crossref(
        author=[
            {"family": "Orengo", "given": "H. A."},
            {"family": "Garcia-Molsosa", "given": "A."},
        ],
    )
    item = _build(claims, crossref)
    creators = item["creators"]
    assert [c["lastName"] for c in creators] == ["Orengo", "Garcia-Molsosa"]
    assert all(c["creatorType"] == "author" for c in creators)


def test_authors_fall_back_to_claims_when_registry_has_none() -> None:
    """With no registry author list, the claims string is parsed instead.

    Uses the canonical semicolon-delimited "Family, Given" form, which is
    the shape ``parse_author_string`` maps onto ``lastName``/``firstName``
    creators. (The proposer's comma-only display form is intentionally
    lossy on this fallback path — see ``parse_author_string`` — so the
    point being guarded here is simply that the fallback fires at all.)
    """
    claims = _claims(authors="Solo, Sam; Doe, Jane")
    crossref = _crossref(author=None)  # no "author" key
    item = _build(claims, crossref)
    creators = item["creators"]
    assert creators, "expected the claims string to yield at least one creator"
    assert creators[0]["lastName"] == "Solo"
    assert creators[0]["firstName"] == "Sam"


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
