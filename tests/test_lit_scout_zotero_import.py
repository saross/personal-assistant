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



# ===========================================================================
# ET1 — run_import end to end
#
# Before this block the importer's entire write path was untested: the
# duplicate check, the --live gate, the collection assignment, the env-var
# precondition, the manifest idempotency, and the read-only SQLite open all
# survived deletion (lens B, tranche 5, finding 1). Every test below runs
# the real ``run_import`` against a synthetic workspace, a synthetic Zotero
# SQLite, and a fake pyzotero client that records every call.
#
# All identifiers, titles, names, and queries are invented.
# ===========================================================================

import argparse
import json
import os
import sqlite3
import sys
import types

from no_network_guard import refuse_socket_connections
from zotero_sqlite_fixture import build_zotero_sqlite


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every socket connection for the life of each test."""
    refuse_socket_connections(monkeypatch)


class FakeZoteroClient:
    """A pyzotero stand-in that records every call and creates nothing."""

    def __init__(self, library_id: str, library_type: str, api_key: str):
        """Record the credentials the importer constructed us with."""
        self.library_id = library_id
        self.library_type = library_type
        self.api_key = api_key
        self.calls: list[tuple[str, Any]] = []
        #: Pages returned by ``collections_sub``; index 0 is the first page.
        self.subcollection_pages: list[list[dict]] = [[]]
        self.created_items: list[list[dict]] = []

    def collections_sub(self, parent_key: str) -> list[dict]:
        """Return the FIRST page of children, as pyzotero itself does."""
        self.calls.append(("collections_sub", parent_key))
        return self.subcollection_pages[0]

    def everything(self, first_page: list[dict]) -> list[dict]:
        """Flatten every page — pyzotero's own pagination helper."""
        self.calls.append(("everything", len(first_page)))
        return [c for page in self.subcollection_pages for c in page]

    def create_collections(self, templates: list[dict]) -> dict:
        """Pretend to create one collection and return pyzotero's shape."""
        self.calls.append(("create_collections", templates))
        return {"successful": {"0": {"key": "NEWCOLL1"}}, "failed": {}}

    def create_items(self, items: list[dict]) -> dict:
        """Pretend to create every item and return pyzotero's shape."""
        self.calls.append(("create_items", items))
        self.created_items.append(items)
        return {
            "successful": {
                str(i): {"key": f"ITEMKEY{i}"} for i in range(len(items))
            },
            "failed": {},
        }


def _install_fake_pyzotero(monkeypatch: pytest.MonkeyPatch) -> list:
    """Put a fake ``pyzotero`` package in ``sys.modules``; return the clients.

    ``run_import`` imports pyzotero lazily inside the ``--live`` branch, so
    the substitution has to live in ``sys.modules`` rather than on the
    importer module.
    """
    clients: list[FakeZoteroClient] = []

    def _factory(library_id: str, library_type: str, api_key: str):
        client = FakeZoteroClient(library_id, library_type, api_key)
        clients.append(client)
        return client

    zotero_mod = types.ModuleType("pyzotero.zotero")
    zotero_mod.Zotero = _factory  # type: ignore[attr-defined]
    package = types.ModuleType("pyzotero")
    package.zotero = zotero_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyzotero", package)
    monkeypatch.setitem(sys.modules, "pyzotero.zotero", zotero_mod)
    return clients


def _write_workspace(root: Path, dois: list[str]) -> Path:
    """Create a one-iteration lit-scout workspace claiming ``dois``."""
    workspace = root / "lit-scout-iterate-20310204-101500"
    iteration = workspace / "iter-0"
    iteration.mkdir(parents=True)
    lines = []
    for index, doi in enumerate(dois):
        for category, value in (
            ("title", f"Synthetic Study {index}"),
            ("year", 2031),
            ("authors", "Petkova, N."),
        ):
            lines.append(
                json.dumps(
                    {
                        "claim_id": f"{doi}-{category}",
                        "doi": doi,
                        "value": value,
                        "status": "pass",
                    }
                )
            )
    (iteration / "claims.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    (iteration / "report.md").write_text(
        "## Findings table\n\n"
        "| # | Fit | Cites | Authors (Year) | Title | DOI | Chain | "
        "Chains | Cluster | Status |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        + "".join(
            f"| {i + 1} | HIGH | 3 | Petkova (2031) | Synthetic Study {i} "
            f"| {doi} | fwd | 1 | terraces | ok |\n"
            for i, doi in enumerate(dois)
        ),
        encoding="utf-8",
    )
    return workspace


def _crossref_record(doi: str) -> dict:
    """A minimal CrossRef ``message`` for ``doi``."""
    return {
        "type": "journal-article",
        "title": [f"Registry Title for {doi}"],
        "author": [{"given": "Nadia", "family": "Petkova"}],
        "issued": {"date-parts": [[2031, 4, 2]]},
        "container-title": ["Journal of Synthetic Landscapes"],
        "DOI": doi,
    }


@pytest.fixture
def import_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Wire the importer to a synthetic library, workspace, and registry."""
    data_dir = tmp_path / "ZoteroSynthetic"
    data_dir.mkdir()
    db_path = data_dir / "zotero.sqlite"
    build_zotero_sqlite(
        db_path,
        [
            {
                "key": "ALREADY1",
                "fields": {
                    "title": "Already Filed Study",
                    "DOI": "https://doi.org/10.4321/ALREADY-here",
                },
            }
        ],
    )
    monkeypatch.setattr(_importer, "ZOTERO_SQLITE", db_path)
    monkeypatch.setattr(_importer, "ENV_PATH", tmp_path / "absent.env")
    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "9990001")
    monkeypatch.setenv("ZOTERO_API_KEY_ALL", "synthetic-key-not-a-secret")
    monkeypatch.setenv("ZOTERO_STAGING_COLLECTION", "STAGINGK")
    monkeypatch.setattr(
        _importer, "fetch_crossref", lambda doi, client: _crossref_record(doi)
    )
    monkeypatch.setattr(_importer, "fetch_datacite", lambda doi, client: None)
    monkeypatch.setattr(_importer, "fetch_openalex", lambda doi, client: None)

    opened: list[str] = []
    real_connect = sqlite3.connect

    def _recording_connect(target, *args, **kwargs):
        """Record every SQLite URI the importer opens."""
        opened.append(str(target))
        return real_connect(target, *args, **kwargs)

    monkeypatch.setattr(_importer.sqlite3, "connect", _recording_connect)
    return {"tmp": tmp_path, "opened": opened, "db": db_path}


def _args(workspace: Path, **overrides: Any) -> argparse.Namespace:
    """Build the argparse namespace ``run_import`` expects."""
    values = {
        "workspace": str(workspace),
        "query": "terrace survey methods",
        "live": False,
        "limit": 0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestRunImportDryRun:
    """The default path must plan everything and create nothing."""

    def test_dry_run_creates_nothing(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """No pyzotero client is even constructed on a dry run."""
        clients = _install_fake_pyzotero(monkeypatch)
        workspace = _write_workspace(import_env["tmp"], ["10.1111/new-one"])

        assert _importer.run_import(_args(workspace)) == 0

        assert clients == [], "a dry run constructed a Zotero client"
        assert not (workspace / "zotero-import-manifest.json").exists()
        assert "DRY RUN" in capsys.readouterr().out

    def test_sqlite_is_opened_immutable(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dedup read must never be able to write the live library."""
        _install_fake_pyzotero(monkeypatch)
        workspace = _write_workspace(import_env["tmp"], ["10.1111/new-one"])

        _importer.run_import(_args(workspace))

        uris = [u for u in import_env["opened"] if "zotero.sqlite" in u]
        assert uris, "the importer never opened the Zotero database"
        assert all("immutable=1" in u for u in uris), uris
        assert all(u.startswith("file://") for u in uris), uris
        # And the promise holds in practice, not only in the URI.
        conn = sqlite3.connect(uris[0], uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO itemDataValues VALUES (9999, 'x')"
                )
        finally:
            conn.close()


class TestRunImportLive:
    """``--live`` must create exactly the non-duplicate items."""

    def test_creates_only_new_items_in_the_dated_subcollection(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A duplicate is withheld; the new item lands in the subcollection."""
        clients = _install_fake_pyzotero(monkeypatch)
        workspace = _write_workspace(
            import_env["tmp"],
            ["10.1111/new-one", "10.4321/already-here"],
        )

        assert _importer.run_import(_args(workspace, live=True)) == 0

        assert len(clients) == 1
        client = clients[0]
        assert client.api_key == "synthetic-key-not-a-secret"
        created = [c for c in client.calls if c[0] == "create_items"]
        assert len(created) == 1
        items = created[0][1]
        assert [i["DOI"] for i in items] == ["10.1111/new-one"], (
            "the URL-wrapped duplicate was not withheld"
        )
        assert items[0]["collections"] == ["NEWCOLL1"]
        assert "<PLACEHOLDER>" not in items[0]["collections"]

    def test_subcollection_is_named_for_the_run_date_and_query(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dated subcollection name comes from the workspace stamp."""
        clients = _install_fake_pyzotero(monkeypatch)
        workspace = _write_workspace(import_env["tmp"], ["10.1111/new-one"])

        _importer.run_import(_args(workspace, live=True))

        templates = [
            c[1] for c in clients[0].calls if c[0] == "create_collections"
        ]
        assert templates, "no subcollection was created"
        assert templates[0][0]["name"] == (
            "2031-02-04-terrace-survey-methods"
        )
        assert templates[0][0]["parentCollection"] == "STAGINGK"

    def test_a_manifest_hit_is_withheld(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A DOI recorded by a prior run is not created a second time."""
        clients = _install_fake_pyzotero(monkeypatch)
        workspace = _write_workspace(import_env["tmp"], ["10.1111/new-one"])
        (workspace / "zotero-import-manifest.json").write_text(
            json.dumps(
                {
                    "imported_at": "2031-02-04T10:15:00+00:00",
                    "items_created": [
                        {"doi": "10.1111/NEW-ONE", "key": "PRIORKEY"}
                    ],
                }
            ),
            encoding="utf-8",
        )

        assert _importer.run_import(_args(workspace, live=True)) == 0

        created = [c for c in clients[0].calls if c[0] == "create_items"]
        assert created == [] or created[0][1] == [], (
            "a DOI in the prior manifest was imported again"
        )

    def test_missing_credentials_refuse_before_any_request(
        self,
        import_env: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No staging key means an immediate non-zero exit, no client."""
        clients = _install_fake_pyzotero(monkeypatch)
        monkeypatch.delenv("ZOTERO_STAGING_COLLECTION")
        workspace = _write_workspace(import_env["tmp"], ["10.1111/new-one"])

        assert _importer.run_import(_args(workspace, live=True)) == 3
        assert clients == []
        assert import_env["opened"] == [], (
            "the library was opened before the credential check"
        )


# ===========================================================================
# E2 / E4 / E5 / E8 — the four medium defects on the importer's write path
# ===========================================================================


class TestLoadEnv:
    """E2 — the loader must read what env-fingerprint.sh certifies."""

    def test_quotes_are_stripped(self, tmp_path, monkeypatch) -> None:
        """A quoted value loads without its quotes."""
        env = tmp_path / "synthetic.env"
        env.write_text(
            '# a synthetic env file\n'
            'ZOTERO_LIBRARY_ID="9990001"\n'
            "ZOTERO_STAGING_COLLECTION='STAGINGK'\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("ZOTERO_LIBRARY_ID", raising=False)
        monkeypatch.delenv("ZOTERO_STAGING_COLLECTION", raising=False)

        _importer.load_env(env)

        assert os.environ["ZOTERO_LIBRARY_ID"] == "9990001"
        assert os.environ["ZOTERO_STAGING_COLLECTION"] == "STAGINGK"

    def test_export_prefix_is_accepted(self, tmp_path, monkeypatch) -> None:
        """``export KEY=value`` defines KEY, not a variable called "export KEY"."""
        env = tmp_path / "synthetic.env"
        env.write_text(
            "export ZOTERO_API_KEY_ALL=synthetic-key-not-a-secret\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("ZOTERO_API_KEY_ALL", raising=False)

        _importer.load_env(env)

        assert os.environ["ZOTERO_API_KEY_ALL"] == (
            "synthetic-key-not-a-secret"
        )
        assert not any(k.startswith("export") for k in os.environ)

    def test_an_existing_value_is_not_overwritten(
        self, tmp_path, monkeypatch
    ) -> None:
        """The ambient environment still wins over the file."""
        env = tmp_path / "synthetic.env"
        env.write_text('ZOTERO_LIBRARY_ID="from-file"\n', encoding="utf-8")
        monkeypatch.setenv("ZOTERO_LIBRARY_ID", "from-environment")

        _importer.load_env(env)

        assert os.environ["ZOTERO_LIBRARY_ID"] == "from-environment"


class TestRegistryDateAndTitle:
    """E4 and E5 — what actually reaches the Zotero item."""

    def test_null_date_parts_yield_an_empty_date(self) -> None:
        """``[[None]]`` must not become the literal string "None"."""
        crossref = _crossref()
        crossref["issued"] = {"date-parts": [[None]]}
        item = _build(_claims(), crossref)
        assert item["date"] != "None"
        assert item["date"] == "2022", (
            "with no usable registry date the claims year should stand"
        )

    def test_a_null_tail_is_truncated(self) -> None:
        """``[[2031, None]]`` yields the year alone, not "2031-None"."""
        crossref = _crossref()
        crossref["issued"] = {"date-parts": [[2031, None]]}
        item = _build(_claims(), crossref)
        assert item["date"] == "2031"

    def test_html_in_the_registry_title_is_stripped(self) -> None:
        """Markup and entities must not land in Zotero's title field."""
        item = _build(
            _claims(),
            _crossref(title="Terraces <i>in situ</i> &amp; abandoned"),
        )
        assert item["title"] == "Terraces in situ & abandoned"


class TestEnsureSubcollectionPaginates:
    """E8 — an existing subcollection past page one must still be found."""

    def test_a_second_page_match_is_reused_not_duplicated(self) -> None:
        """No create call is made when the name exists on page two."""
        client = FakeZoteroClient("9990001", "user", "key")
        client.subcollection_pages = [
            [{"key": "PAGE1AAA", "data": {"name": "2031-02-04-other"}}],
            [{"key": "PAGE2BBB", "data": {"name": "2031-02-04-wanted"}}],
        ]

        key = _importer.ensure_subcollection(
            client, "STAGINGK", "2031-02-04-wanted"
        )

        assert key == "PAGE2BBB"
        assert not [c for c in client.calls if c[0] == "create_collections"]

    def test_an_absent_name_is_still_created(self) -> None:
        """The create path is unchanged when nothing matches."""
        client = FakeZoteroClient("9990001", "user", "key")
        client.subcollection_pages = [[], []]

        key = _importer.ensure_subcollection(
            client, "STAGINGK", "2031-02-04-new"
        )

        assert key == "NEWCOLL1"
        assert [c[0] for c in client.calls if c[0] == "create_collections"]


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
