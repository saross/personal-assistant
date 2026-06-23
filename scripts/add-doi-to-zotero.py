#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""
add-doi-to-zotero.py — add ONE source-of-truth Zotero item from a DOI into a
dated staging subcollection.

Purpose
-------
For the recurring "citation-without-AB+" case (Asch, Vygotsky, Collins,
Gonzalez): a reference cited directly in the paper that never went through the
``/lit-scout-iterate`` → Zotero staging flow, so it has no Zotero item even
though Zotero is the bibliography's source of truth.

Method (why this is safe to delegate)
-------------------------------------
Reuses the HARDENED registry-first helpers from
``lit-scout-zotero-import.py`` (the author path fixed in personal-assistant
``43b10bc``): creators come from the CrossRef record via
``_creators_from_record`` — exactly the authority the lit-scout verifier checks
against — never from a lossy display string. Idempotent: refuses to create if
the DOI is already in ANY local Zotero library. Dry-run by default; ``--live``
writes via the pyzotero API (never the local SQLite).

Requirements
------------
Run with the personal-assistant venv (has pyzotero + httpx). Credentials are
read from ``~/personal-assistant/.env`` by the importer's ``load_env``:
``ZOTERO_LIBRARY_ID``, ``ZOTERO_API_KEY_PERSONAL``, ``ZOTERO_STAGING_COLLECTION``.
The ``.env`` is per-machine (git-ignored) — each machine must have its own.

Usage
-----
    PY=~/personal-assistant/venv/bin/python3
    $PY ~/personal-assistant/scripts/add-doi-to-zotero.py \
        --doi 10.1037/h0093718 \
        --collection 2026-06-21-asch-1956-conformity \
        --tag paper-b [--live]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sqlite3
import sys
from pathlib import Path

# The hardened importer lives beside this script; resolve relative to __file__
# so the tool is portable across machines (amd-tower, zbook, ...).
IMPORTER = Path(__file__).resolve().parent / "lit-scout-zotero-import.py"


def load_importer():
    """Load the hyphen-named importer module by path and return it."""
    spec = importlib.util.spec_from_file_location("lit_scout_zotero_import", IMPORTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_item(doi: str, msg: dict, m, collection_key: str, tags: list[str]) -> dict:
    """Build a Zotero item dict from a CrossRef-`message`-shaped record.

    Mirrors the field routing of ``build_zotero_item`` but without the
    lit-scout claims/corrections/tags coupling — creators are taken from the
    registry record (``_creators_from_record``), the same authoritative path.
    """
    cr_type = msg.get("type", "")
    item_type = m.CROSSREF_TO_ZOTERO_TYPE.get(cr_type) or m.EXTRA_TYPE_TO_ZOTERO_TYPE.get(
        cr_type, "journalArticle"
    )
    title = (msg.get("title") or [""])[0]
    creators = m._creators_from_record(msg.get("author") or [])

    date_str = ""
    for fld in ("published-print", "published-online", "issued"):
        dobj = msg.get(fld)
        if isinstance(dobj, dict):
            parts = dobj.get("date-parts", [[]])
            if parts and parts[0]:
                date_str = "-".join(
                    f"{p:02d}" if i > 0 else str(p) for i, p in enumerate(parts[0])
                )
                break

    journal = (msg.get("container-title") or [""])[0]
    volume = msg.get("volume", "")
    issue = msg.get("issue", "")
    pages = msg.get("page", "")
    issn_list = msg.get("ISSN", []) or []
    issn = issn_list[0] if issn_list else ""
    abstract = msg.get("abstract", "")
    if abstract:
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    item: dict = {
        "itemType": item_type,
        "title": title,
        "creators": creators,
        "date": date_str,
        "DOI": doi,
        "url": msg.get("URL", f"https://doi.org/{doi}"),
        "abstractNote": abstract,
        "tags": [{"tag": t} for t in tags],
        "collections": [collection_key],
    }
    if item_type == "journalArticle":
        item.update(
            {
                "publicationTitle": journal,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "ISSN": issn,
            }
        )
    elif item_type == "bookSection":
        item["bookTitle"] = journal
        item["pages"] = pages
    elif item_type == "conferencePaper":
        item["proceedingsTitle"] = journal
        item["pages"] = pages
    return item


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doi", required=True)
    ap.add_argument("--collection", required=True, help="staging subcollection name")
    ap.add_argument("--tag", action="append", default=[], help="tag(s); repeatable")
    ap.add_argument("--live", action="store_true", help="write to Zotero (default: dry-run)")
    args = ap.parse_args()

    m = load_importer()
    m.load_env()
    lib = os.environ.get("ZOTERO_LIBRARY_ID")
    key = os.environ.get("ZOTERO_API_KEY_PERSONAL")
    staging = os.environ.get("ZOTERO_STAGING_COLLECTION")
    missing = [
        n
        for n, v in [
            ("ZOTERO_LIBRARY_ID", lib),
            ("ZOTERO_API_KEY_PERSONAL", key),
            ("ZOTERO_STAGING_COLLECTION", staging),
        ]
        if not v
    ]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        return 3

    doi = args.doi.strip()

    # Idempotency: refuse to duplicate a DOI already in any local library.
    conn = sqlite3.connect(f"file://{m.ZOTERO_SQLITE}?immutable=1", uri=True)
    existing = m.find_existing_by_doi(doi, conn)
    conn.close()
    if existing:
        print(f"DOI {doi} is ALREADY in Zotero — refusing to create a duplicate:")
        for e in existing:
            print(f"  {e['library_name']} / {e['collections'] or '(unfiled)'} / key {e['key']}")
        return 0

    import httpx

    client = httpx.Client(headers={"User-Agent": m.USER_AGENT})
    msg = (
        m.fetch_crossref(doi, client)
        or m.fetch_datacite(doi, client)
        or m.fetch_openalex(doi, client)
    )
    client.close()
    if not msg:
        print(f"ERROR: no record in CrossRef/DataCite/OpenAlex for {doi}", file=sys.stderr)
        return 4

    item = build_item(doi, msg, m, "<PLACEHOLDER>", args.tag)

    print(f"\n## Zotero single-DOI add — {'LIVE' if args.live else 'DRY RUN'}\n")
    print(f"staging parent : {staging}")
    print(f"subcollection  : {args.collection}")
    print(f"itemType       : {item['itemType']}")
    print(f"title          : {item['title']}")
    print(f"creators       : {item['creators']}")
    print(f"date           : {item['date']}")
    print(
        f"publication    : {item.get('publicationTitle', '')}  "
        f"vol {item.get('volume', '')} iss {item.get('issue', '')} "
        f"pp {item.get('pages', '')}  ISSN {item.get('ISSN', '')}"
    )
    print(f"DOI / url      : {item['DOI']}  |  {item['url']}")
    print(f"tags           : {[t['tag'] for t in item['tags']]}")

    if not args.live:
        print("\n_(dry run — no Zotero writes. Re-run with --live to create.)_")
        return 0

    from pyzotero import zotero

    zot = zotero.Zotero(lib, "user", key)
    coll_key = m.ensure_subcollection(zot, staging, args.collection)
    print(f"\n# subcollection key: {coll_key}", file=sys.stderr)
    item["collections"] = [coll_key]
    result = zot.create_items([item])
    succ = result.get("successful", {})
    failed = result.get("failed", {})
    for _, payload in succ.items():
        print(f"CREATED item key {payload['key']} in collection {coll_key} ({args.collection})")
    for _, payload in failed.items():
        print(f"FAILED: {payload}", file=sys.stderr)
    return 0 if (succ and not failed) else 5


if __name__ == "__main__":
    raise SystemExit(main())
