#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""
lit-scout-zotero-import.py
==========================

Import a /lit-scout-iterate workspace into a Zotero staging subcollection.

Reads the final iteration's claims.jsonl, the verifier's corrections.jsonl
(for warning tags on unverified rows), and the corrected report.md (for
Fit and cluster signals from the Findings table). Dedups against every
local Zotero library via sqlite. Imports new items to a dated subcollection
under the configured staging collection in the user's personal library.

Defaults to --dry-run. Pass --live to actually write to Zotero.

Workspace layout expected
-------------------------
    <workspace>/
      iter-0/draft.md, claims.jsonl, report.md, corrections.jsonl
      iter-N/draft.md, claims.jsonl, report.md, corrections.jsonl   ← final
      post-run-note.md (optional)

The "final iteration" is the highest-numbered iter-N directory containing
a non-empty claims.jsonl. Per the iterate-mode contract, this carries the
corrected values (true_value substituted into FAIL claims).

Environment variables (sourced from ~/personal-assistant/.env)
--------------------------------------------------------------
    ZOTERO_LIBRARY_ID         User ID for the personal library
    ZOTERO_API_KEY_PERSONAL   Key with personal-library write +
                              all-groups read
    ZOTERO_STAGING_COLLECTION Top-level collection key under which dated
                              subcollections are created

Outputs
-------
    - <workspace>/zotero-import-manifest.json — durable record of the run
    - Markdown report of imported/skipped/failed items written to stdout
      (consumed by the /lit-scout-iterate driver and appended to the
      final report's "## Zotero import" section).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Defer pyzotero import to live mode so dry-run works without the venv
# being activated.

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

CROSSREF_BASE = "https://api.crossref.org"
MAILTO = "shawn@faims.edu.au"
USER_AGENT = "lit-scout-zotero-import/1.0 (mailto:shawn@faims.edu.au)"
HTTP_TIMEOUT = 30.0

ZOTERO_SQLITE = Path.home() / "Zotero" / "zotero.sqlite"
ENV_PATH = Path.home() / "personal-assistant" / ".env"

# CrossRef type → Zotero itemType mapping. Add to this as we encounter
# new types in real runs.
CROSSREF_TO_ZOTERO_TYPE = {
    "journal-article": "journalArticle",
    "book": "book",
    "book-chapter": "bookSection",
    "edited-book": "book",
    "monograph": "book",
    "proceedings-article": "conferencePaper",
    "report": "report",
    "posted-content": "preprint",
    "dissertation": "thesis",
    "dataset": "dataset",
}


# ----------------------------------------------------------------------------
# .env loading (no python-dotenv dependency; simple key=value parser)
# ----------------------------------------------------------------------------


def load_env(path: Path = ENV_PATH) -> None:
    """Source key=value pairs from .env into os.environ if not already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


# ----------------------------------------------------------------------------
# Workspace parsing
# ----------------------------------------------------------------------------


def find_final_iteration(workspace: Path) -> Path:
    """Return the path to the highest-numbered iter-N/ with a claims.jsonl."""
    iters = sorted(
        (p for p in workspace.glob("iter-*") if p.is_dir()),
        key=lambda p: int(p.name.split("-")[1]),
    )
    for it in reversed(iters):
        cj = it / "claims.jsonl"
        if cj.exists() and cj.stat().st_size > 0:
            return it
    raise FileNotFoundError(f"No iter-N/claims.jsonl found under {workspace}")


def load_claims(path: Path) -> list[dict]:
    """Load a JSONL file of claim or correction records."""
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def group_claims_by_doi(claims: list[dict]) -> dict[str, dict[str, dict]]:
    """
    Return {doi: {category: claim}} for the 5-category claim contract.

    Drops the `_legacy` sentinel and any claim whose claim_id does not match
    the <doi-slug>-<category> pattern.
    """
    pattern = re.compile(r"^(10\..+)-(authors|year|title|citation_count|doi_resolves)$")
    by_doi: dict[str, dict[str, dict]] = {}
    for c in claims:
        cid = c.get("claim_id", "")
        m = pattern.match(cid)
        if not m:
            continue
        doi_slug, category = m.group(1), m.group(2)
        doi = doi_slug.replace("-", "/", 1)
        by_doi.setdefault(doi, {})[category] = c
    return by_doi


def parse_findings_table(report_md: Path) -> dict[str, dict[str, str]]:
    """
    Parse the report's Findings table — verifier's corrected table preferred,
    else the proposer's draft table. Returns {doi: {fit, cites, cluster}}.

    The table layout (both proposer and verifier emit the same column order):
        | # | Fit | Cites | Authors (Year) | Title | DOI | Chain | Chains | Cluster | Status |
    """
    text = report_md.read_text()
    # Prefer the corrected table if it exists (verifier output), else the
    # original. Search marker headings to bound the right table.
    markers = ["## Corrected findings table", "## Findings table"]
    table_text = None
    for marker in markers:
        idx = text.find(marker)
        if idx == -1:
            continue
        # Take everything from this marker up to the next top-level heading.
        sub = text[idx:]
        end = sub.find("\n## ", 1)
        table_text = sub if end == -1 else sub[:end]
        break
    if table_text is None:
        return {}

    rows: dict[str, dict[str, str]] = {}
    doi_pattern = re.compile(r"^10\.\S+")
    for line in table_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # Expect ~10 columns; reject header / separator lines.
        if len(cells) < 10 or cells[0] in ("#", "---") or "---" in cells[0]:
            continue
        # Scan cells for the first one that looks like a DOI (resilient to
        # column drift if the proposer ever rearranges the table).
        doi = None
        doi_col = None
        for col_idx, cell in enumerate(cells):
            m = doi_pattern.match(cell)
            if m:
                doi = m.group(0).strip(".,;")
                doi_col = col_idx
                break
        if not doi:
            continue
        rows[doi.lower()] = {
            "fit": cells[1] if len(cells) > 1 else "",
            "cites": cells[2] if len(cells) > 2 else "",
            "cluster": cells[doi_col + 3] if doi_col is not None and len(cells) > doi_col + 3 else "",
            "status": cells[doi_col + 4] if doi_col is not None and len(cells) > doi_col + 4 else "",
        }
    return rows


# ----------------------------------------------------------------------------
# CrossRef metadata fetch (richer than lit-search.py's _normalise_crossref —
# we need journal/volume/issue/pages/ISSN for the Zotero item)
# ----------------------------------------------------------------------------


def fetch_crossref(doi: str, client: httpx.Client) -> dict | None:
    """Return the raw `message` block of a CrossRef works/<doi> record."""
    url = f"{CROSSREF_BASE}/works/{httpx.URL(doi).path or doi}"
    # CrossRef wants the DOI as a path segment with `/` URL-encoded.
    import urllib.parse
    url = f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='')}"
    try:
        r = client.get(url, params={"mailto": MAILTO}, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        return r.json().get("message")
    except httpx.HTTPError:
        return None


# ----------------------------------------------------------------------------
# Local-sqlite dedup
# ----------------------------------------------------------------------------


def find_existing_by_doi(doi: str, conn: sqlite3.Connection) -> list[dict]:
    """
    Return all items across all local libraries whose DOI field matches.

    Matching is case-insensitive on the canonical DOI string. Returns one
    row per match with library + collection context.
    """
    rows = conn.execute(
        """
        SELECT i.itemID, i.key, l.libraryID, l.type,
               COALESCE(g.name, 'My Library') AS library_name,
               GROUP_CONCAT(c.collectionName, '; ') AS collections
        FROM items i
        JOIN itemData id ON i.itemID = id.itemID
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        JOIN libraries l ON i.libraryID = l.libraryID
        LEFT JOIN groups g ON l.libraryID = g.libraryID
        LEFT JOIN collectionItems ci ON i.itemID = ci.itemID
        LEFT JOIN collections c ON ci.collectionID = c.collectionID
        WHERE f.fieldName = 'DOI'
          AND LOWER(idv.value) = LOWER(?)
          AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
        GROUP BY i.itemID
        """,
        (doi,),
    ).fetchall()
    return [
        {
            "item_id": r[0],
            "key": r[1],
            "library_id": r[2],
            "library_type": r[3],
            "library_name": r[4],
            "collections": r[5] or "",
        }
        for r in rows
    ]


# ----------------------------------------------------------------------------
# Author-string parsing — round-trip from claims.jsonl flat string to
# Zotero creators list
# ----------------------------------------------------------------------------


def parse_author_string(s: str) -> list[dict[str, str]]:
    """
    Convert "Family, Given; Family, Given; ..." → Zotero creators format.

    The format originates in our claims.jsonl `value` field for the
    `authors` category. Falls back to a name-only creator for entries
    that don't split on a comma (corporate authors etc.).
    """
    creators = []
    for entry in s.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "," in entry:
            family, _, given = entry.partition(",")
            creators.append(
                {
                    "creatorType": "author",
                    "lastName": family.strip(),
                    "firstName": given.strip(),
                }
            )
        else:
            creators.append({"creatorType": "author", "name": entry})
    return creators


# ----------------------------------------------------------------------------
# Item construction
# ----------------------------------------------------------------------------


def build_zotero_item(
    doi: str,
    claims_for_doi: dict[str, dict],
    crossref_msg: dict,
    table_row: dict[str, str],
    corrections_for_doi: dict[str, dict],
    run_timestamp: str,
    subcollection_key: str,
) -> dict[str, Any]:
    """
    Build a Zotero item dict suitable for `zot.create_items([item])`.

    Authoritative source for each field:
      - title, year, citation_count, doi_resolves: from claims (corrected)
      - authors: from claims (corrected; may differ from CrossRef raw)
      - publicationTitle, volume, issue, pages, ISSN, abstract, url:
        from CrossRef raw (claims contract does not cover these)
      - itemType: derived from CrossRef `type` via mapping table
      - tags: synthesised from run_timestamp + table_row + corrections
    """
    cr_type = crossref_msg.get("type", "")
    item_type = CROSSREF_TO_ZOTERO_TYPE.get(cr_type, "journalArticle")

    # Title: prefer the claims value (corrected), else CrossRef.
    title = (claims_for_doi.get("title") or {}).get("value") \
        or (crossref_msg.get("title") or [""])[0]

    # Year/date: claims has integer year; CrossRef date is richer.
    year = (claims_for_doi.get("year") or {}).get("value")
    # Try to recover full date from CrossRef.
    date_str = ""
    for fld in ("published-print", "published-online", "issued"):
        dobj = crossref_msg.get(fld)
        if isinstance(dobj, dict):
            parts = dobj.get("date-parts", [[]])
            if parts and parts[0]:
                date_str = "-".join(f"{p:02d}" if i > 0 else str(p)
                                    for i, p in enumerate(parts[0]))
                break
    if not date_str and year:
        date_str = str(year)

    # Authors: corrected value from claims, parsed back to creators.
    authors_str = (claims_for_doi.get("authors") or {}).get("value", "")
    creators = parse_author_string(authors_str) if authors_str else []

    # Container fields from CrossRef.
    journal = (crossref_msg.get("container-title") or [""])[0]
    volume = crossref_msg.get("volume", "")
    issue = crossref_msg.get("issue", "")
    pages = crossref_msg.get("page", "")
    issn_list = crossref_msg.get("ISSN", [])
    issn = issn_list[0] if issn_list else ""
    abstract = crossref_msg.get("abstract", "")
    if abstract:
        abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    # Tags: base set per design + Fit + unverified-field tags from
    # corrections.
    tags = [
        "lit-scout-staging",
        f"lit-scout-run:{run_timestamp}",
    ]
    fit = table_row.get("fit", "").upper()
    if fit in ("HIGH", "MEDIUM", "LOW"):
        tags.append(f"lit-scout-fit:{fit.lower()}")
    cluster = table_row.get("cluster", "").strip()
    if cluster:
        cluster_slug = re.sub(r"[^a-z0-9]+", "-", cluster.lower()).strip("-")
        if cluster_slug:
            tags.append(f"lit-scout-cluster:{cluster_slug}")
    # Warning tags from corrections.jsonl
    for category, corr in corrections_for_doi.items():
        status = corr.get("status")
        if status in ("fail", "partial", "unverifiable"):
            tags.append(f"lit-scout-unverified:{category}")

    # Use Zotero's tag dict shape so tags survive create_items().
    tag_dicts = [{"tag": t} for t in tags]

    item: dict[str, Any] = {
        "itemType": item_type,
        "title": title,
        "creators": creators,
        "date": date_str,
        "DOI": doi,
        "url": crossref_msg.get("URL", f"https://doi.org/{doi}"),
        "abstractNote": abstract,
        "tags": tag_dicts,
        "collections": [subcollection_key],
    }
    # Type-specific fields
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
    elif item_type in ("conferencePaper",):
        item["proceedingsTitle"] = journal
        item["pages"] = pages

    # Stash fix-hint context in extra for unverified rows.
    extras = []
    for category, corr in corrections_for_doi.items():
        if corr.get("status") in ("fail", "partial", "unverifiable"):
            hint = corr.get("fix_hint") or ""
            if hint:
                extras.append(f"lit-scout: {category} {corr['status']}: {hint}")
    if extras:
        item["extra"] = "\n".join(extras)

    return item


# ----------------------------------------------------------------------------
# Zotero collection management (live mode)
# ----------------------------------------------------------------------------


def slugify_query(query: str, max_len: int = 50) -> str:
    """Lower-kebab-case truncated query slug for subcollection naming."""
    s = re.sub(r"[^a-zA-Z0-9]+", "-", query.lower()).strip("-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s or "untitled"


def ensure_subcollection(zot, parent_key: str, name: str) -> str:
    """
    Return the key of a subcollection named `name` under `parent_key`,
    creating it if absent. Idempotent.
    """
    # List children of the staging collection
    children = zot.collections_sub(parent_key)
    for c in children:
        if c["data"]["name"] == name:
            return c["key"]
    # Create
    template = {"name": name, "parentCollection": parent_key}
    result = zot.create_collections([template])
    # pyzotero returns {"successful": {"0": {...}}, "failed": {}, ...}
    successful = result.get("successful", {})
    if not successful:
        raise RuntimeError(f"Failed to create subcollection {name!r}: {result}")
    new_key = list(successful.values())[0]["key"]
    return new_key


# ----------------------------------------------------------------------------
# Main flow
# ----------------------------------------------------------------------------


def run_import(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    if not workspace.exists():
        print(f"ERROR: workspace {workspace} does not exist", file=sys.stderr)
        return 2

    load_env()

    # Required env vars
    library_id = os.environ.get("ZOTERO_LIBRARY_ID")
    api_key = os.environ.get("ZOTERO_API_KEY_PERSONAL")
    staging_key = os.environ.get("ZOTERO_STAGING_COLLECTION")
    missing = [
        n
        for n, v in [
            ("ZOTERO_LIBRARY_ID", library_id),
            ("ZOTERO_API_KEY_PERSONAL", api_key),
            ("ZOTERO_STAGING_COLLECTION", staging_key),
        ]
        if not v
    ]
    if missing:
        print(f"ERROR: missing env vars: {missing}", file=sys.stderr)
        return 3

    # Locate final iteration
    final_iter = find_final_iteration(workspace)
    print(f"# Workspace: {workspace}", file=sys.stderr)
    print(f"# Final iteration: {final_iter.name}", file=sys.stderr)

    claims = load_claims(final_iter / "claims.jsonl")
    corrections_path = final_iter / "corrections.jsonl"
    corrections = load_claims(corrections_path) if corrections_path.exists() else []
    by_doi_claims = group_claims_by_doi(claims)
    by_doi_corrections = group_claims_by_doi(corrections)

    # Parse the Findings table from the corrected (verifier) report
    table = parse_findings_table(final_iter / "report.md")

    # Derive run timestamp from the workspace name
    ws_name = workspace.name
    m = re.search(r"(\d{8}-\d{6})", ws_name)
    run_ts = m.group(1) if m else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_date = datetime.strptime(run_ts[:8], "%Y%m%d").strftime("%Y-%m-%d")

    # Subcollection name
    query = args.query or "untitled-query"
    subcoll_name = f"{run_date}-{slugify_query(query)}"

    # Open sqlite for dedup
    conn = sqlite3.connect(f"file://{ZOTERO_SQLITE}?immutable=1", uri=True)

    # Manifest-based idempotency: skip DOIs already imported by a prior
    # invocation against this workspace. Useful for the 1-item-smoke-test
    # → finish-the-rest workflow, where the Zotero desktop sync may not
    # have refreshed local sqlite between calls.
    manifest_path = workspace / "zotero-import-manifest.json"
    previous_manifest = None
    already_imported: set[str] = set()
    if manifest_path.exists():
        previous_manifest = json.loads(manifest_path.read_text())
        already_imported = {
            entry["doi"].lower()
            for entry in previous_manifest.get("items_created", [])
        }
        if already_imported:
            print(
                f"# Previous manifest at {manifest_path.name} — "
                f"skipping {len(already_imported)} already-imported DOIs",
                file=sys.stderr,
            )

    # CrossRef client
    cr_client = httpx.Client(headers={"User-Agent": USER_AGENT})

    # Plan
    plan_create: list[tuple[str, dict]] = []
    plan_skip: list[tuple[str, list[dict]]] = []
    plan_already_imported: list[str] = []
    plan_failed: list[tuple[str, str]] = []

    print(f"# Planning import of {len(by_doi_claims)} candidate DOIs ...",
          file=sys.stderr)
    for doi, cat_claims in by_doi_claims.items():
        if doi.lower() in already_imported:
            plan_already_imported.append(doi)
            continue
        existing = find_existing_by_doi(doi, conn)
        if existing:
            plan_skip.append((doi, existing))
            continue
        crossref_msg = fetch_crossref(doi, cr_client)
        if not crossref_msg:
            plan_failed.append((doi, "CrossRef returned no record"))
            continue
        table_row = table.get(doi.lower(), {})
        cat_corrections = by_doi_corrections.get(doi, {})
        item = build_zotero_item(
            doi=doi,
            claims_for_doi=cat_claims,
            crossref_msg=crossref_msg,
            table_row=table_row,
            corrections_for_doi=cat_corrections,
            run_timestamp=run_ts,
            subcollection_key="<PLACEHOLDER>",  # filled in live mode
        )
        plan_create.append((doi, item))
        time.sleep(0.05)  # gentle on CrossRef

    cr_client.close()

    # Apply --limit if set (after planning, before any writes)
    if args.limit and args.limit > 0 and len(plan_create) > args.limit:
        plan_create = plan_create[: args.limit]

    # Emit plan summary
    print(f"\n## Zotero import — {'DRY RUN' if not args.live else 'LIVE'}\n")
    print(f"**Subcollection (would be):** `staging` → `{subcoll_name}`")
    print(f"**Candidates:** {len(by_doi_claims)} unique DOIs from "
          f"`{final_iter.name}/claims.jsonl`")
    print(f"- To create: **{len(plan_create)}**"
          + (f" (limited from full plan via --limit {args.limit})"
             if args.limit and args.limit > 0 else ""))
    print(f"- Skipped (already in a library): **{len(plan_skip)}**")
    if plan_already_imported:
        print(f"- Skipped (in prior manifest): **{len(plan_already_imported)}**")
    print(f"- Failed metadata fetch: **{len(plan_failed)}**")

    if plan_skip:
        print("\n### Skipped (existing items)\n")
        print("| DOI | Library | Collections | Key |")
        print("|---|---|---|---|")
        for doi, hits in plan_skip:
            h = hits[0]
            print(f"| `{doi}` | {h['library_name']} ({h['library_type']}) "
                  f"| {h['collections'][:60]} | `{h['key']}` |")

    if plan_failed:
        print("\n### Failed metadata fetch\n")
        for doi, reason in plan_failed:
            print(f"- `{doi}`: {reason}")

    if plan_create:
        print("\n### To create (preview — first 5)\n")
        for doi, item in plan_create[:5]:
            tags = ", ".join(t["tag"] for t in item["tags"])
            print(f"- `{doi}` → **{item['title'][:70]}** "
                  f"({item['itemType']}, {len(item['creators'])} authors)")
            print(f"  tags: {tags}")

    if not args.live:
        print("\n_(dry run — no Zotero writes performed; re-run with --live to import)_")
        return 0

    # --- LIVE MODE ---
    from pyzotero import zotero
    zot = zotero.Zotero(library_id, "user", api_key)

    print(f"\n# Creating subcollection {subcoll_name!r} under "
          f"staging ({staging_key}) ...", file=sys.stderr)
    subcoll_key = ensure_subcollection(zot, staging_key, subcoll_name)
    print(f"# Subcollection key: {subcoll_key}", file=sys.stderr)

    # Fix placeholder collection key on items
    for _, item in plan_create:
        item["collections"] = [subcoll_key]

    # Batch create — pyzotero limit is 50 per call
    created = []
    failed_live = []
    BATCH = 50
    for i in range(0, len(plan_create), BATCH):
        batch = [item for _, item in plan_create[i : i + BATCH]]
        result = zot.create_items(batch)
        successful = result.get("successful", {})
        failed_result = result.get("failed", {})
        for idx, payload in successful.items():
            doi = plan_create[i + int(idx)][0]
            created.append({"doi": doi, "key": payload["key"]})
        for idx, payload in failed_result.items():
            doi = plan_create[i + int(idx)][0]
            failed_live.append({"doi": doi, "error": payload})
        print(f"# Batch {i // BATCH + 1}: {len(successful)} created, "
              f"{len(failed_result)} failed", file=sys.stderr)

    # Merge with previous manifest if present (idempotent re-runs)
    prior_created = (previous_manifest or {}).get("items_created", []) if previous_manifest else []
    prior_skipped = (previous_manifest or {}).get("items_skipped", []) if previous_manifest else []
    prior_failed = (previous_manifest or {}).get("items_failed", []) if previous_manifest else []

    manifest = {
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "final_iteration": final_iter.name,
        "library_id": library_id,
        "library_type": "user",
        "staging_collection_key": staging_key,
        "subcollection_key": subcoll_key,
        "subcollection_name": subcoll_name,
        "query": query,
        "items_created": prior_created + created,
        "items_skipped": prior_skipped + [
            {"doi": doi, "existing": hits} for doi, hits in plan_skip
        ],
        "items_failed": prior_failed + [
            {"doi": doi, "reason": reason} for doi, reason in plan_failed
        ] + failed_live,
        "previous_invocations": (previous_manifest or {}).get("previous_invocations", []) + (
            [{"imported_at": previous_manifest["imported_at"]}]
            if previous_manifest else []
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\n# Manifest: {manifest_path}", file=sys.stderr)

    # Append created-items table to stdout report
    print(f"\n### Created\n")
    print("| DOI | Zotero key | Title |")
    print("|---|---|---|")
    for entry in created:
        doi = entry["doi"]
        title = next(
            (it["title"] for d, it in plan_create if d == doi), ""
        )[:70]
        print(f"| `{doi}` | `{entry['key']}` | {title} |")
    if failed_live:
        print(f"\n### Failed during creation\n")
        for entry in failed_live:
            print(f"- `{entry['doi']}`: {entry['error']}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Import a lit-scout-iterate workspace into Zotero staging."
    )
    p.add_argument(
        "workspace",
        help="Path to the /lit-scout-iterate workspace "
             "(e.g. /tmp/lit-scout-iterate-YYYYMMDD-HHMMSS)",
    )
    p.add_argument(
        "--query",
        default="",
        help="Original user query (used for subcollection naming). "
             "If omitted, the subcollection is named "
             "YYYY-MM-DD-untitled-query.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Actually write to Zotero. Default is dry-run.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap the number of items created in this invocation (0 = no cap). "
             "Useful for smoke-testing one item before importing the rest.",
    )
    args = p.parse_args()
    return run_import(args)


if __name__ == "__main__":
    raise SystemExit(main())
