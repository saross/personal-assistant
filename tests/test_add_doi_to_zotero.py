"""
Tests for scripts/add-doi-to-zotero.py — the single-DOI Zotero adder.

The script's header makes two safety claims — "Idempotent: refuses to
create if the DOI is already in ANY local Zotero library" and "Dry-run by
default" — and until audit round 4d nothing tested either (lens B, tranche
5, ET18). The first claim was in fact false for the commonest stored
shape: the duplicate guard it borrows from the importer did not normalise
URL-wrapped DOIs, so a DOI saved by Zotero's browser connector was
invisible and a duplicate was created.

Every test here runs the real ``main()`` with the registry lookups and
pyzotero replaced by recorders, against a synthetic on-disk library. All
identifiers, names, and titles are invented.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from no_network_guard import refuse_socket_connections
from zotero_sqlite_fixture import build_zotero_sqlite

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "add-doi-to-zotero.py"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every socket connection for the life of each test."""
    refuse_socket_connections(monkeypatch)


def _load_script() -> Any:
    """Load the hyphen-named script by path and return the module."""
    spec = importlib.util.spec_from_file_location("add_doi_to_zotero", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingZotero:
    """A pyzotero stand-in that records calls and creates nothing."""

    instances: list["RecordingZotero"] = []

    def __init__(self, library_id: str, library_type: str, api_key: str):
        """Record the credentials the script constructed us with."""
        self.library_id = library_id
        self.api_key = api_key
        self.calls: list[tuple[str, Any]] = []
        RecordingZotero.instances.append(self)

    def collections_sub(self, parent_key: str) -> list[dict]:
        """Return an empty first page of child collections."""
        self.calls.append(("collections_sub", parent_key))
        return []

    def everything(self, first_page: list[dict]) -> list[dict]:
        """Flatten pages — here, the single empty page."""
        return list(first_page)

    def create_collections(self, templates: list[dict]) -> dict:
        """Pretend to create the dated subcollection."""
        self.calls.append(("create_collections", templates))
        return {"successful": {"0": {"key": "SUBCOLL1"}}, "failed": {}}

    def create_items(self, items: list[dict]) -> dict:
        """Pretend to create the item."""
        self.calls.append(("create_items", items))
        return {"successful": {"0": {"key": "MADEITEM"}}, "failed": {}}


@pytest.fixture
def script_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """Point the script at a synthetic library and a fake registry."""
    RecordingZotero.instances = []
    module = _load_script()
    importer = module.load_importer()

    data_dir = tmp_path / "ZoteroSynthetic"
    data_dir.mkdir()
    db_path = data_dir / "zotero.sqlite"
    build_zotero_sqlite(
        db_path,
        [
            {
                "key": "ONFILE01",
                "collection_id": 1,
                "fields": {
                    "title": "Already Filed Study",
                    "DOI": "https://doi.org/10.4321/ALREADY-here",
                },
            }
        ],
    )

    def _load_importer_stubbed():
        """Return the shared importer module with its paths redirected."""
        importer.ZOTERO_SQLITE = db_path
        importer.ENV_PATH = tmp_path / "absent.env"
        importer.fetch_crossref = lambda doi, client: {
            "type": "journal-article",
            "title": [f"Registry Title for {doi}"],
            "author": [{"given": "Marek", "family": "Dvorak"}],
            "issued": {"date-parts": [[2031, 5, 6]]},
            "container-title": ["Journal of Synthetic Landscapes"],
            "URL": f"https://doi.org/{doi}",
        }
        importer.fetch_datacite = lambda doi, client: None
        importer.fetch_openalex = lambda doi, client: None
        return importer

    monkeypatch.setattr(module, "load_importer", _load_importer_stubbed)

    zotero_mod = types.ModuleType("pyzotero.zotero")
    zotero_mod.Zotero = RecordingZotero  # type: ignore[attr-defined]
    package = types.ModuleType("pyzotero")
    package.zotero = zotero_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyzotero", package)
    monkeypatch.setitem(sys.modules, "pyzotero.zotero", zotero_mod)

    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "9990001")
    monkeypatch.setenv("ZOTERO_API_KEY_ALL", "synthetic-broad-key")
    monkeypatch.delenv("ZOTERO_API_KEY_PERSONAL", raising=False)
    monkeypatch.setenv("ZOTERO_STAGING_COLLECTION", "STAGINGK")
    return {"module": module, "db": db_path}


def _run(
    module: Any, monkeypatch: pytest.MonkeyPatch, *argv: str
) -> int:
    """Run the real ``main()`` with ``argv``."""
    monkeypatch.setattr(sys, "argv", ["add-doi-to-zotero.py", *argv])
    return module.main()


class TestRefusesDuplicates:
    """The header's idempotency claim, made true and pinned."""

    def test_a_url_wrapped_duplicate_is_refused(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bare DOI matching a stored URL-wrapped one creates nothing."""
        code = _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.4321/already-here",
            "--collection",
            "2031-05-06-terraces",
            "--live",
        )

        assert code == 0
        assert RecordingZotero.instances == [], (
            "a duplicate DOI reached the Zotero API"
        )

    def test_an_absent_doi_is_created_under_live(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The positive half of the pair: a new DOI is created once."""
        code = _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.7777/brand-new",
            "--collection",
            "2031-05-06-terraces",
            "--tag",
            "synthetic-tag",
            "--live",
        )

        assert code == 0
        assert len(RecordingZotero.instances) == 1
        client = RecordingZotero.instances[0]
        created = [c for c in client.calls if c[0] == "create_items"]
        assert len(created) == 1
        item = created[0][1][0]
        assert item["DOI"] == "10.7777/brand-new"
        assert item["collections"] == ["SUBCOLL1"]
        assert [t["tag"] for t in item["tags"]] == ["synthetic-tag"]


class TestDryRunWritesNothing:
    """"Dry-run by default" — pinned as a consequence, not a message."""

    def test_the_default_run_creates_nothing(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --live no pyzotero client is even constructed."""
        code = _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.7777/brand-new",
            "--collection",
            "2031-05-06-terraces",
        )

        assert code == 0
        assert RecordingZotero.instances == []


class TestCredentialPrecedence:
    """E6 — the broad key is preferred, the retiring key still works."""

    def test_the_broad_key_is_used_when_present(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ZOTERO_API_KEY_ALL is what reaches pyzotero."""
        monkeypatch.setenv("ZOTERO_API_KEY_PERSONAL", "synthetic-old-key")

        _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.7777/brand-new",
            "--collection",
            "2031-05-06-terraces",
            "--live",
        )

        assert RecordingZotero.instances[0].api_key == "synthetic-broad-key"

    def test_the_retiring_key_still_works_alone(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With only the old key set, the script still runs."""
        monkeypatch.delenv("ZOTERO_API_KEY_ALL")
        monkeypatch.setenv("ZOTERO_API_KEY_PERSONAL", "synthetic-old-key")

        code = _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.7777/brand-new",
            "--collection",
            "2031-05-06-terraces",
            "--live",
        )

        assert code == 0
        assert RecordingZotero.instances[0].api_key == "synthetic-old-key"

    def test_no_key_at_all_refuses_before_any_request(
        self, script_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Neither key set means an immediate non-zero exit."""
        monkeypatch.delenv("ZOTERO_API_KEY_ALL")

        code = _run(
            script_env["module"],
            monkeypatch,
            "--doi",
            "10.7777/brand-new",
            "--collection",
            "2031-05-06-terraces",
            "--live",
        )

        assert code == 3
        assert RecordingZotero.instances == []


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
