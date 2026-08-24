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
    ZOTERO_API_KEY_ALL        The Tier-1 broad key: personal-library
                              write + all-groups read (see
                              global-claude-md/zotero-reference.md)
    ZOTERO_STAGING_COLLECTION Top-level collection key under which dated
                              subcollections are created

HTTP tuning knobs (optional; shared with lit-search.py)
-------------------------------------------------------
    LIT_SEARCH_MAX_RETRIES            Total attempts per fetch (default 4)
    LIT_SEARCH_BASE_BACKOFF           Base backoff seconds (default 2.0)
    LIT_SEARCH_MAX_BACKOFF            Cap on a single sleep (default 60.0)
    LIT_SEARCH_BACKOFF_JITTER         +/- jitter fraction (default 0.5)
    LIT_SEARCH_CROSSREF_MIN_INTERVAL  CrossRef pacing seconds (default 0.2)
    LIT_SEARCH_DATACITE_MIN_INTERVAL  DataCite pacing seconds (default 0.2)
    LIT_SEARCH_OPENALEX_MIN_INTERVAL  OpenAlex pacing seconds (default 0.1)
    LIT_SEARCH_S2_MIN_INTERVAL        Semantic Scholar pacing (default 1.1)
    LIT_SEARCH_DEFAULT_MIN_INTERVAL   Fallback host pacing (default 0.2)

These deliberately reuse lit-search.py's `LIT_SEARCH_*` names so one setting
tunes both tools; the logic is ported (not imported) to keep this script
self-contained.

Outputs
-------
    - <workspace>/zotero-import-manifest.json — durable record of the run
    - Markdown report of imported/skipped/failed items written to stdout
      (consumed by the /lit-scout-iterate driver and appended to the
      final report's "## Zotero import" section).
"""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable
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
OPENALEX_BASE = "https://api.openalex.org"
DATACITE_BASE = "https://api.datacite.org"
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

# DataCite `types.resourceTypeGeneral` → CrossRef-style type string. DataCite is
# the registry of record for datasets, software, and many DataCite-only DOIs
# (arXiv, Zenodo, institutional repositories). We translate its controlled
# vocabulary into the CrossRef type strings that `CROSSREF_TO_ZOTERO_TYPE`
# already understands, so `fetch_datacite` can hand `build_zotero_item` the
# exact same internal record shape as CrossRef/OpenAlex and reuse one mapping
# table. Values not listed here fall through to `journal-article` (the same
# conservative default the CrossRef and OpenAlex paths use).
#
# `Text` is deliberately mapped to `journal-article` rather than the Zotero
# `document` catch-all: DataCite tags scholarly articles, reports, and book
# chapters all as `Text`, and the overwhelming majority of `Text` DOIs that
# reach this fallback (i.e. ones CrossRef did NOT index) are journal articles
# in regional/diamond-OA venues. A bare `document` would lose the container
# title; `journal-article` preserves it. The CrossRef path still owns the
# common, well-indexed cases, so this only affects DataCite-only `Text` DOIs.
DATACITE_GENERAL_TO_CROSSREF_TYPE = {
    "dataset": "dataset",
    "software": "software",
    "text": "journal-article",
    "preprint": "posted-content",
    "report": "report",
    "conferencepaper": "proceedings-article",
    "conferenceproceeding": "proceedings-article",
    "book": "book",
    "bookchapter": "book-chapter",
    "dissertation": "dissertation",
    "journalarticle": "journal-article",
}

# CrossRef-style type string → Zotero itemType, extended beyond
# `CROSSREF_TO_ZOTERO_TYPE` with the few DataCite-introduced types that have no
# CrossRef equivalent (notably `software` → `computerProgram`). Looked up after
# `CROSSREF_TO_ZOTERO_TYPE` misses, so it never overrides an existing mapping.
EXTRA_TYPE_TO_ZOTERO_TYPE = {
    "software": "computerProgram",
}


# ----------------------------------------------------------------------------
# HTTP tuning knobs (shared config with lit-search.py)
# ----------------------------------------------------------------------------
# These knobs deliberately reuse the `LIT_SEARCH_*` environment-variable names
# that lit-search.py reads, so that setting e.g. `LIT_SEARCH_MAX_RETRIES=6`
# once tunes BOTH tools identically. The defaults are copied verbatim from
# lit-search.py (MAX_RETRIES=4, BASE_BACKOFF=2.0s, MAX_BACKOFF=60s,
# BACKOFF_JITTER=±50%, per-host minimum intervals) so the two share behaviour
# without importing from lit-search.py (whose hyphenated filename is not a
# valid Python module name). A future shared `http_retry` module would let us
# drop this duplication, but that refactor is intentionally out of scope here.


def _env_float(name: str, default: float) -> float:
    """
    Read a float tuning knob from the environment, falling back to a
    conservative default.

    A missing/empty value uses the default silently; a malformed (non-float)
    value emits a one-line warning to stderr and uses the default, so a typo
    degrades gracefully rather than crashing the import.

    Args:
        name: Environment-variable name (e.g. ``LIT_SEARCH_BASE_BACKOFF``).
        default: Value to use when the variable is unset, empty, or malformed.

    Returns:
        The parsed float, or ``default`` on absence/parse failure.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        sys.stderr.write(
            f"WARNING: {name}={raw!r} is not a float; using default "
            f"{default}.\n"
        )
        return default


def _env_int(name: str, default: int) -> int:
    """
    Read an int tuning knob from the environment (see :func:`_env_float`).

    Args:
        name: Environment-variable name (e.g. ``LIT_SEARCH_MAX_RETRIES``).
        default: Value to use when the variable is unset, empty, or malformed.

    Returns:
        The parsed int, or ``default`` on absence/parse failure.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        sys.stderr.write(
            f"WARNING: {name}={raw!r} is not an int; using default "
            f"{default}.\n"
        )
        return default


# Per-host minimum inter-request interval (seconds). Keyed by HOST so the floor
# is honoured across an entire batch import (every DOI hits the same few hosts)
# regardless of which fetch helper issued the request. DataCite is added on top
# of lit-search.py's set; Semantic Scholar is included for config parity even
# though this importer does not currently call S2.
S2_HOST = "api.semanticscholar.org"
CROSSREF_HOST = "api.crossref.org"
OPENALEX_HOST = "api.openalex.org"
DATACITE_HOST = "api.datacite.org"

HOST_MIN_INTERVAL: dict[str, float] = {
    S2_HOST: _env_float("LIT_SEARCH_S2_MIN_INTERVAL", 1.1),
    CROSSREF_HOST: _env_float("LIT_SEARCH_CROSSREF_MIN_INTERVAL", 0.2),
    OPENALEX_HOST: _env_float("LIT_SEARCH_OPENALEX_MIN_INTERVAL", 0.1),
    DATACITE_HOST: _env_float("LIT_SEARCH_DATACITE_MIN_INTERVAL", 0.2),
}
# Floor applied to any host not listed above.
DEFAULT_MIN_INTERVAL = _env_float("LIT_SEARCH_DEFAULT_MIN_INTERVAL", 0.2)

# Retry / exponential-backoff knobs. Transient failures (HTTP 429, HTTP 5xx,
# connection/timeout errors) are retried with exponential backoff plus jitter.
# After exhausting attempts the caller's existing graceful-degradation path
# runs (returns None → the next source in the fetch chain), so a persistently
# rate-limited source still degrades to the remaining sources.
MAX_RETRIES = _env_int("LIT_SEARCH_MAX_RETRIES", 4)  # total attempts per call
BASE_BACKOFF = _env_float("LIT_SEARCH_BASE_BACKOFF", 2.0)  # seconds (attempt 0)
MAX_BACKOFF = _env_float("LIT_SEARCH_MAX_BACKOFF", 60.0)  # cap on a single sleep
BACKOFF_JITTER = _env_float("LIT_SEARCH_BACKOFF_JITTER", 0.5)  # +/- fraction

# Track last request time per host for pacing. The lock makes the limiter safe
# under future concurrency; the import currently runs single-threaded.
_last_request: dict[str, float] = {}
_pace_lock = threading.Lock()


# ----------------------------------------------------------------------------
# Per-host pacing + retry helpers (ported from lit-search.py to keep this
# importer self-contained; see the knob block above for why we duplicate)
# ----------------------------------------------------------------------------


def _host_of(url: str) -> str:
    """Extract the hostname from a URL for per-host pacing."""
    return urllib.parse.urlsplit(url).hostname or ""


def _pace_host(host: str) -> None:
    """
    Enforce the minimum inter-request interval for ``host``.

    Sleeps just long enough that consecutive requests to the same host are
    spaced by at least ``HOST_MIN_INTERVAL[host]`` (or ``DEFAULT_MIN_INTERVAL``
    for hosts not listed). Because the timestamp is keyed by host and stored at
    module scope, the floor applies across the whole import run, not just within
    one call.

    Args:
        host: Hostname to pace (e.g. ``api.crossref.org``).
    """
    min_interval = HOST_MIN_INTERVAL.get(host, DEFAULT_MIN_INTERVAL)
    with _pace_lock:
        now = time.monotonic()
        last = _last_request.get(host, 0.0)
        elapsed = now - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_request[host] = time.monotonic()


def _parse_retry_after(value: str) -> float | None:
    """
    Parse a ``Retry-After`` header value into a delay in seconds.

    The header may be either an integer number of seconds or an HTTP-date
    (RFC 7231).

    Args:
        value: Raw ``Retry-After`` header value (possibly empty).

    Returns:
        The delay in seconds (>= 0.0), or ``None`` if it cannot be parsed.
        A past HTTP-date yields 0.0 (retry immediately, subject to the
        backoff floor applied by the caller). A malformed/garbage value
        yields ``None`` so the caller falls back to exponential backoff.
    """
    value = (value or "").strip()
    if not value:
        return None
    # Numeric seconds form.
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    # HTTP-date form. `parsedate_to_datetime` raises (TypeError/ValueError) on
    # unparseable input rather than returning None, so guard it and treat an
    # unparseable header as "no usable hint" → fall back to backoff.
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    delay = parsed.timestamp() - time.time()
    return max(0.0, delay)


def _backoff_delay(attempt: int) -> float:
    """
    Exponential backoff with jitter for retry ``attempt`` (0-indexed).

    ``delay = BASE_BACKOFF * 2**attempt``, multiplied by a random jitter factor
    in ``[1 - BACKOFF_JITTER, 1 + BACKOFF_JITTER]``, then capped at
    ``MAX_BACKOFF``. The jitter spreads out retries so repeated callers do not
    stampede the API in lockstep ("thundering herd").

    Args:
        attempt: Zero-indexed retry attempt number.

    Returns:
        Sleep duration in seconds, in ``[0.0, MAX_BACKOFF]``.
    """
    raw = BASE_BACKOFF * (2 ** attempt)
    jitter = 1.0 + random.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)
    return min(MAX_BACKOFF, max(0.0, raw * jitter))


def _is_retryable_status(status_code: int) -> bool:
    """True for HTTP 429 and any 5xx (transient server-side failures)."""
    return status_code == 429 or 500 <= status_code < 600


def _request_with_retry(
    do_request: Callable[[], httpx.Response],
    host: str,
    source: str,
) -> httpx.Response:
    """
    Execute a single HTTP request with pacing + exponential-backoff retry.

    ``do_request`` is a zero-argument callable that performs exactly one GET and
    returns the ``httpx.Response`` (it must NOT do its own pacing/retry — this
    helper owns both). The helper:

      * paces the host before every attempt (so retries also respect the
        per-host floor);
      * retries on HTTP 429, HTTP 5xx, and connection/timeout errors;
      * on 429 honours ``Retry-After`` (seconds or HTTP-date) when present,
        otherwise uses exponential backoff with jitter;
      * caps the number of attempts at ``MAX_RETRIES`` and any single sleep at
        ``MAX_BACKOFF``, so a call can never hang indefinitely;
      * after exhausting retries, returns the last response (so the caller's
        existing non-200 handling runs) or re-raises the last connection error
        (so the caller's existing ``except httpx.HTTPError`` runs).

    Net effect: success and terminal-4xx (e.g. 404) paths are unchanged; only
    transient failures gain extra, backed-off attempts before the SAME graceful
    degradation the caller already implemented.

    Args:
        do_request: Zero-argument callable performing one GET.
        host: Hostname used for pacing.
        source: Human-readable source label for log messages.

    Returns:
        The final ``httpx.Response`` (success, terminal 4xx, or
        retry-exhausted transient status).

    Raises:
        httpx.HTTPError: If every attempt failed with a connection-level error.
    """
    last_exc: httpx.HTTPError | None = None
    last_resp: httpx.Response | None = None

    for attempt in range(MAX_RETRIES):
        _pace_host(host)
        try:
            resp = do_request()
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            # Connection-level failure: retryable.
            last_exc = exc
            last_resp = None
            if attempt < MAX_RETRIES - 1:
                delay = _backoff_delay(attempt)
                sys.stderr.write(
                    f"WARNING: {source}: connection error "
                    f"({type(exc).__name__}); retry {attempt + 1}/"
                    f"{MAX_RETRIES - 1} in {delay:.1f}s.\n"
                )
                time.sleep(delay)
                continue
            # Exhausted: re-raise so the caller's except-clause degrades it.
            raise

        last_resp = resp
        if not _is_retryable_status(resp.status_code):
            # Success or a terminal status (e.g. 404): return immediately.
            return resp

        # Transient HTTP status (429 or 5xx).
        if attempt >= MAX_RETRIES - 1:
            # Out of attempts: hand the response back so the caller's existing
            # non-200 branch runs and returns None.
            return resp

        if resp.status_code == 429:
            retry_after = _parse_retry_after(
                resp.headers.get("Retry-After", "")
            )
            if retry_after is not None:
                # Respect the server's hint, but never below the backoff floor
                # for this attempt and never above the global cap.
                delay = min(
                    MAX_BACKOFF, max(retry_after, _backoff_delay(attempt))
                )
                hint = f"Retry-After={retry_after:.1f}s"
            else:
                delay = _backoff_delay(attempt)
                hint = "no Retry-After"
            sys.stderr.write(
                f"WARNING: {source}: rate limited (429, {hint}); retry "
                f"{attempt + 1}/{MAX_RETRIES - 1} in {delay:.1f}s.\n"
            )
        else:
            delay = _backoff_delay(attempt)
            sys.stderr.write(
                f"WARNING: {source}: server error (HTTP "
                f"{resp.status_code}); retry {attempt + 1}/"
                f"{MAX_RETRIES - 1} in {delay:.1f}s.\n"
            )
        time.sleep(delay)

    # Loop fell through (unreachable given the returns/raises above, but kept
    # for total-function safety).
    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry loop exited without a response")


# ----------------------------------------------------------------------------
# .env loading (no python-dotenv dependency; simple key=value parser)
# ----------------------------------------------------------------------------


def load_env(path: Path = ENV_PATH) -> None:
    """Source key=value pairs from .env into os.environ if not already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
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
    for line in path.read_text(encoding="utf-8").splitlines():
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
        # Prefer the explicit, lossless `doi` field (claim contract from
        # 2026-06-06 onward). Fall back to decoding the claim_id slug only
        # for legacy workspaces that predate the field. The slug encodes
        # `/`->`-`, which is NOT reversible for DOIs containing hyphens or
        # multiple slashes (e.g. ACL anthology `10.18653/v1/2023.emnlp-main.557`
        # or JAMIA `10.1093/jamia/ocae014`): `replace("-", "/", 1)` only
        # recovers the first slash and corrupts the rest.
        doi = (c.get("doi") or "").strip() or doi_slug.replace("-", "/", 1)
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
            "cluster": (
                cells[doi_col + 3]
                if doi_col is not None and len(cells) > doi_col + 3
                else ""
            ),
            "status": (
                cells[doi_col + 4]
                if doi_col is not None and len(cells) > doi_col + 4
                else ""
            ),
        }
    return rows


# ----------------------------------------------------------------------------
# Metadata fetch chain: CrossRef → DataCite → OpenAlex
# ----------------------------------------------------------------------------
# All three helpers return the SAME internal record shape (the CrossRef
# `message` shape `build_zotero_item` consumes) and degrade to None on a miss,
# so the chain is just "first non-None wins". We carry richer container fields
# (journal/volume/issue/pages/ISSN) than lit-search.py's `_normalise_crossref`
# because the Zotero item needs them. Every fetch is routed through
# `_request_with_retry` for 429/5xx/connection resilience with per-host pacing.
# ----------------------------------------------------------------------------


def fetch_crossref(doi: str, client: httpx.Client) -> dict | None:
    """Return the raw `message` block of a CrossRef works/<doi> record.

    Routed through :func:`_request_with_retry`, so transient HTTP 429 / 5xx /
    connection errors are retried with backoff before degrading. The
    degradation path is unchanged: a non-200 (including a retry-exhausted 429)
    or a connection error returns ``None``, and the caller falls back to the
    next source in the CrossRef → DataCite → OpenAlex chain.
    """
    # CrossRef wants the DOI as a path segment with `/` URL-encoded.
    url = f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi, safe='')}"
    try:
        r = _request_with_retry(
            lambda: client.get(
                url, params={"mailto": MAILTO}, timeout=HTTP_TIMEOUT
            ),
            host=_host_of(url),
            source="crossref",
        )
        if r.status_code != 200:
            return None
        return r.json().get("message")
    except httpx.HTTPError:
        return None


def fetch_openalex(doi: str, client: httpx.Client) -> dict | None:
    """Broad backstop metadata fetch, normalised to the CrossRef `message` shape.

    Last link in the CrossRef → DataCite → OpenAlex chain: tried only when both
    CrossRef and DataCite return nothing. OpenAlex covers arXiv and most other
    registries, so it catches the long tail neither prior source indexed. Only
    the subset of fields `build_zotero_item` reads is mapped (type, title,
    container-title, volume, issue, page, ISSN, abstract, URL, issued); authors
    are sourced from the claims contract when present, falling back to the
    record's `author` list otherwise.
    """
    url = f"{OPENALEX_BASE}/works/https://doi.org/{urllib.parse.quote(doi, safe='')}"
    try:
        r = _request_with_retry(
            lambda: client.get(
                url, params={"mailto": MAILTO}, timeout=HTTP_TIMEOUT
            ),
            host=_host_of(url),
            source="openalex",
        )
        if r.status_code != 200:
            return None
        w = r.json()
    except (httpx.HTTPError, ValueError):
        return None

    oa_to_crossref_type = {
        "article": "journal-article",
        "preprint": "posted-content",
        "book": "book",
        "book-chapter": "book-chapter",
        "proceedings-article": "proceedings-article",
        "dataset": "dataset",
        "report": "report",
        "dissertation": "dissertation",
    }
    cr_type = oa_to_crossref_type.get((w.get("type") or "").lower(), "journal-article")

    authors = []
    for a in w.get("authorships", []):
        disp = ((a.get("author") or {}).get("display_name") or "").strip()
        if not disp:
            continue
        toks = disp.split()
        if len(toks) >= 2:
            authors.append({"given": " ".join(toks[:-1]), "family": toks[-1]})
        else:
            authors.append({"name": disp})

    src = (w.get("primary_location") or {}).get("source") or {}
    container = src.get("display_name") or ""
    issn = [i for i in (src.get("issn") or []) if i]

    biblio = w.get("biblio") or {}
    pages = ""
    if biblio.get("first_page"):
        pages = str(biblio["first_page"])
        if biblio.get("last_page"):
            pages += f"-{biblio['last_page']}"

    # Date: prefer the full publication_date (YYYY-MM-DD), else the year.
    date_parts: list[list[int]] = [[]]
    pubdate = w.get("publication_date")
    if pubdate:
        try:
            date_parts = [[int(x) for x in pubdate.split("-")]]
        except ValueError:
            date_parts = [[]]
    if date_parts == [[]] and w.get("publication_year"):
        date_parts = [[int(w["publication_year"])]]

    return {
        "type": cr_type,
        "title": [w.get("title") or ""],
        "author": authors,
        "container-title": [container] if container else [],
        "volume": biblio.get("volume") or "",
        "issue": biblio.get("issue") or "",
        "page": pages,
        "ISSN": issn,
        "abstract": "",  # OpenAlex stores an inverted index; skip reconstruction
        "URL": w.get("doi") or f"https://doi.org/{doi}",
        "issued": {"date-parts": date_parts},
    }


def _datacite_creator(creator: dict) -> dict[str, str] | None:
    """Convert one DataCite ``creators[]`` entry into a CrossRef-style author.

    DataCite supplies structured ``familyName``/``givenName`` for personal
    names and a flat ``name`` for organisations (and as a fallback). We prefer
    the structured fields (so "Cowey, James M.S." round-trips to
    family="Cowey", given="James M.S.") and fall back to the flat ``name``,
    splitting a "Family, Given" string on the first comma when present.

    Args:
        creator: One element of DataCite ``data.attributes.creators``.

    Returns:
        A ``{"family": ..., "given": ...}`` or ``{"name": ...}`` dict matching
        the CrossRef ``author`` shape, or ``None`` for an empty entry.
    """
    family = (creator.get("familyName") or "").strip()
    given = (creator.get("givenName") or "").strip()
    if family:
        return {"family": family, "given": given}
    name = (creator.get("name") or "").strip()
    if not name:
        return None
    name_type = (creator.get("nameType") or "").strip().lower()
    # A "Family, Given" personal name with no structured fields: split it so
    # downstream author parsing keeps the family/given distinction.
    if name_type != "organizational" and "," in name:
        fam, _, giv = name.partition(",")
        return {"family": fam.strip(), "given": giv.strip()}
    return {"name": name}


def fetch_datacite(doi: str, client: httpx.Client) -> dict | None:
    """DataCite metadata fetch, normalised to the CrossRef `message` shape.

    DataCite is the registry of record for datasets, software, and a long tail
    of DataCite-only DOIs (Zenodo, arXiv, institutional repositories) that
    CrossRef does not index. It sits in the chain BETWEEN CrossRef and OpenAlex:
    CrossRef covers most journal/book DOIs; DataCite is authoritative for the
    dataset/software/registry DOIs CrossRef misses; OpenAlex is the broad
    backstop for anything neither indexes.

    The returned dict is the SAME internal record shape `build_zotero_item`
    already consumes from CrossRef/OpenAlex: ``type`` is a CrossRef-style type
    string (translated from DataCite ``types.resourceTypeGeneral`` via
    :data:`DATACITE_GENERAL_TO_CROSSREF_TYPE`), plus ``title``, ``author``,
    ``container-title``, ``page``, ``abstract``, ``URL``, ``issued``, and a
    ``publisher`` key (DataCite's ``publisher`` — e.g. "Zenodo" — which
    `build_zotero_item` routes into the right per-type Zotero field).

    Routed through :func:`_request_with_retry` for 429/5xx/connection
    resilience; degrades to ``None`` on a non-200 or connection error exactly
    like the CrossRef path, so the caller falls back to OpenAlex.

    Args:
        doi: The DOI to resolve (unencoded; e.g. ``10.5281/zenodo.3575154``).
        client: A shared ``httpx.Client``.

    Returns:
        A CrossRef-``message``-shaped dict, or ``None`` if DataCite has no
        record / the request failed after retries.
    """
    # DataCite wants the DOI as a single path segment with `/` URL-encoded.
    url = f"{DATACITE_BASE}/dois/{urllib.parse.quote(doi, safe='')}"
    try:
        r = _request_with_retry(
            lambda: client.get(
                url,
                headers={"Accept": "application/vnd.api+json"},
                timeout=HTTP_TIMEOUT,
            ),
            host=_host_of(url),
            source="datacite",
        )
        if r.status_code != 200:
            return None
        attrs = (r.json().get("data") or {}).get("attributes") or {}
    except (httpx.HTTPError, ValueError):
        return None

    # Type: DataCite controlled vocab → CrossRef-style string. Unknown values
    # fall through to `journal-article`, matching CrossRef/OpenAlex defaults.
    general = ((attrs.get("types") or {}).get("resourceTypeGeneral") or "")
    cr_type = DATACITE_GENERAL_TO_CROSSREF_TYPE.get(
        general.strip().lower(), "journal-article"
    )

    # Title: first non-empty `titles[].title`.
    title = ""
    for t in attrs.get("titles") or []:
        cand = (t.get("title") or "").strip()
        if cand:
            title = cand
            break

    # Authors: structured DataCite creators → CrossRef-style author list.
    authors = []
    for creator in attrs.get("creators") or []:
        mapped = _datacite_creator(creator)
        if mapped:
            authors.append(mapped)

    # Year: DataCite gives a single `publicationYear`; express it as the
    # CrossRef `issued.date-parts` shape so the date logic downstream is shared.
    date_parts: list[list[int]] = [[]]
    pub_year = attrs.get("publicationYear")
    if pub_year:
        try:
            date_parts = [[int(pub_year)]]
        except (TypeError, ValueError):
            date_parts = [[]]

    # Abstract: first `descriptions[].description` (DataCite tags these with a
    # `descriptionType`, but the first is the abstract in practice; HTML strip
    # happens later in `build_zotero_item`).
    abstract = ""
    for d in attrs.get("descriptions") or []:
        cand = (d.get("description") or "").strip()
        if cand:
            abstract = cand
            break

    # Container: DataCite `container.title` (e.g. a journal/series name) when
    # present, for the journal/book-section type paths.
    container = ((attrs.get("container") or {}).get("title") or "").strip()

    publisher = (attrs.get("publisher") or "").strip()
    doi_value = (attrs.get("doi") or doi).strip()

    return {
        "type": cr_type,
        "title": [title],
        "author": authors,
        "container-title": [container] if container else [],
        "volume": "",
        "issue": "",
        "page": "",
        "ISSN": [],
        "abstract": abstract,
        "publisher": publisher,
        "URL": attrs.get("url") or f"https://doi.org/{doi_value}",
        "issued": {"date-parts": date_parts},
    }


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


def _given_family_creator(name: str) -> dict[str, str] | None:
    """Parse a single "Given … Family" full name into a Zotero creator.

    Last whitespace-token is treated as the family name, the remainder as
    given names (handles "Eric P. Xing", "H.-Y. Liu", "Tim Miller"). A
    trailing parenthetical year (e.g. "Smith (2024)") is stripped. A
    single-token or empty name falls back to a name-only creator.
    """
    name = re.sub(r"\s*\(\d{4}[a-z]?\)\s*$", "", name).strip()
    # Drop a trailing "et al." and treat a bare "et al." as a non-author.
    name = re.sub(r"[,;]?\s*et\s+al\.?\s*$", "", name, flags=re.IGNORECASE).strip()
    if not name or re.fullmatch(r"et\s+al\.?", name, flags=re.IGNORECASE):
        return None
    toks = name.split()
    if len(toks) >= 2:
        return {"creatorType": "author", "lastName": toks[-1],
                "firstName": " ".join(toks[:-1])}
    return {"creatorType": "author", "name": name}


def _creators_from_record(authors: list[dict]) -> list[dict[str, str]]:
    """Convert a CrossRef-style ``author`` list into Zotero creators.

    This is the PRIMARY source of creators in `build_zotero_item`: the registry
    record (CrossRef/DataCite/OpenAlex) carries the full, correctly-ordered
    author list, whereas the claims-contract `authors` value is only a short
    display rendering (see the authors block in `build_zotero_item` for why the
    registry wins). The claims string is consulted only as a fallback, when the
    record has no authors. Each input entry is either ``{"family", "given"}``
    (personal name) or ``{"name"}`` (organisation / unparsed name), matching the
    shape `fetch_crossref`/`fetch_openalex`/`fetch_datacite` emit.

    Args:
        authors: CrossRef-``message``-style ``author`` list.

    Returns:
        Zotero creator dicts, dropping any empty entries.
    """
    creators: list[dict[str, str]] = []
    for a in authors:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family:
            creators.append(
                {"creatorType": "author", "lastName": family,
                 "firstName": given}
            )
            continue
        name = (a.get("name") or "").strip()
        if name:
            creators.append({"creatorType": "author", "name": name})
            continue
        # Mononym / malformed entry with a `given` but no `family` and no
        # `name` (rare in CrossRef, but this is now the PRIMARY creator path,
        # so keep it rather than silently drop the author): store the lone
        # given token as a name-only creator.
        if given:
            creators.append({"creatorType": "author", "name": given})
    return creators


def parse_author_string(s: str) -> list[dict[str, str]]:
    """
    Convert a claims.jsonl `authors` value into Zotero creators.

    Fallback path only: `build_zotero_item` now prefers the registry record's
    structured authors (`_creators_from_record`) and calls this string parser
    only when the record has no author list. The claims `authors` value is a
    short display rendering, so parsing it is inherently lossy --- retained for
    the rare record with no registry authors, not as the primary source.

    Handles two formats the contract has used:
      - canonical "Family, Given; Family, Given; ..." (semicolon-delimited);
      - the lit-scout proposer's "Given Family, Given Family, ..."
        (comma-delimited list of full names, no semicolons) — historically
        mis-parsed as a single author, the cause of "1 authors" imports.

    A lone "Family, Given" with no semicolon is ambiguous with two
    comma-separated single-name authors; the proposer never emits that
    shape (single authors arrive as "Given Family", no comma), so we treat
    a semicolon-free comma string as a list of "Given Family" names.
    """
    s = (s or "").strip()
    if not s:
        return []
    creators: list[dict[str, str]] = []
    if ";" in s:
        # Canonical "Family, Given; ..." form.
        for entry in s.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            if "," in entry:
                family, _, given = entry.partition(",")
                creators.append({
                    "creatorType": "author",
                    "lastName": family.strip(),
                    "firstName": given.strip(),
                })
            else:
                c = _given_family_creator(entry)
                if c:
                    creators.append(c)
    elif "," in s:
        # Comma-delimited list of "Given Family" full names.
        for entry in s.split(","):
            c = _given_family_creator(entry)
            if c:
                creators.append(c)
    else:
        c = _given_family_creator(s)
        if c:
            creators.append(c)
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
      - title: from the registry record's `title` (CrossRef/DataCite/
        OpenAlex), which carries the full, untruncated title; the claims
        `title` string is only a fallback when the record has none (see
        the title block below for why — symmetric with authors)
      - year, citation_count, doi_resolves: from claims (corrected)
      - authors: from the registry record's structured `author` field
        (CrossRef/DataCite/OpenAlex), which carries the full, correctly
        ordered list; the claims `authors` string is only a fallback when
        the record has none (see the authors block below for why)
      - publicationTitle, volume, issue, pages, ISSN, abstract, url:
        from CrossRef raw (claims contract does not cover these)
      - itemType: derived from CrossRef `type` via mapping table
      - tags: synthesised from run_timestamp + table_row + corrections
    """
    cr_type = crossref_msg.get("type", "")
    # Resolve the Zotero itemType: try the CrossRef map first, then the
    # DataCite-introduced extras (e.g. `software` → `computerProgram`), then
    # default to `journalArticle` (the historical fallback).
    item_type = CROSSREF_TO_ZOTERO_TYPE.get(cr_type) or (
        EXTRA_TYPE_TO_ZOTERO_TYPE.get(cr_type, "journalArticle")
    )

    # Title: registry-first, symmetric with the authors block below. The
    # registry record's `title` (CrossRef for journals/books, DataCite for
    # arXiv/Zenodo, OpenAlex as the backstop) carries the full, untruncated
    # title; the claims-contract `title` is the lit-scout proposer's
    # rendering, which has been observed to truncate or reword the title.
    # The verifier scores a title mismatch as PARTIAL (not FAIL), and
    # iterate-mode only propagates FAIL corrections back into claims.jsonl,
    # so a truncated proposer title is never corrected upstream and lands in
    # Zotero verbatim unless we prefer the registry here. In the 2026-06-25
    # run, 8 of 24 titles were truncated and only a manual patch avoided
    # corruption. Preferring the registry cannot discard a verifier
    # correction the same way the authors block cannot: the registry record
    # is exactly the authority the verifier checks titles against.
    #
    # Priority:
    #   1. Registry record has a non-empty `title` → that is canonical.
    #   2. Else fall back to the claims `title` value. An explicit empty
    #      correction (the claims `value` is the empty string) is preserved
    #      rather than coerced away, mirroring the old behaviour's care with
    #      empty corrections; only an absent/None claim yields "".
    # Note the asymmetry in the empty-string handling between the two
    # sources: an empty *registry* title must NOT clobber a usable claims
    # title (hence the truthiness test on `registry_title`), whereas an
    # empty *claims* title is a legitimate (if rare) correction and is kept.
    registry_title = (crossref_msg.get("title") or [""])[0]
    title_claim = (claims_for_doi.get("title") or {}).get("value")
    if registry_title:
        title = registry_title
    elif title_claim is not None:
        title = title_claim
    else:
        title = ""

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

    # Authors: the authoritative full list is the registry record's structured
    # `author` field (CrossRef for journals/books, DataCite for arXiv/Zenodo,
    # OpenAlex as the backstop), parsed by `_creators_from_record`. We prefer it
    # over the claims-contract `authors` value because that value is the
    # lit-scout proposer's short DISPLAY rendering --- e.g. "Lu, Zhang (2025)" or
    # "Vygotsky (1978/1980)" --- NOT a full, correctly-ordered author list.
    # Round-tripping that string through `parse_author_string` produced the
    # corruption seen in staged records: year-as-surname (the "(1978/1980)" tail
    # has a slash, so the year-strip regex misses it and the token becomes the
    # family name), flattened order, and blank given names. The verifier checks
    # the proposer's attribution STRING (first author, count, and named later
    # authors --- broadened 2026-06-26), not the structured creator field this
    # importer writes, so even a clean verification does not guarantee a clean
    # round-trip of the claims string. The registry record is exactly the
    # authority the verifier checks against, so preferring it cannot discard a
    # verifier correction; it
    # restores the full list the short claim string only gestured at.
    #
    # Priority, therefore:
    #   1. Registry record has a usable `author` list → that is canonical.
    #   2. Else the claims contract carries an `authors` value → fall back to
    #      parsing it (a record CrossRef/DataCite/OpenAlex indexed WITHOUT an
    #      author list, but the proposer supplied one --- better a parsed string
    #      than zero creators). An explicit empty correction stays empty.
    #   3. Else → no creators.
    record_creators = _creators_from_record(crossref_msg.get("author") or [])
    if record_creators:
        creators = record_creators
    elif "authors" in claims_for_doi:
        authors_claim = (claims_for_doi.get("authors") or {}).get("value")
        authors_str = "" if authors_claim is None else authors_claim
        creators = parse_author_string(authors_str) if authors_str else []
    else:
        creators = []

    # Container fields from the fetched record.
    journal = (crossref_msg.get("container-title") or [""])[0]
    volume = crossref_msg.get("volume", "")
    issue = crossref_msg.get("issue", "")
    pages = crossref_msg.get("page", "")
    issn_list = crossref_msg.get("ISSN", [])
    issn = issn_list[0] if issn_list else ""
    # Publisher: DataCite supplies this directly (e.g. "Zenodo"); CrossRef
    # records carry it under `publisher` too. Routed into the type-appropriate
    # Zotero field below (datasets/preprints → `repository`, software →
    # `company`, documents → `publisher`).
    publisher = (crossref_msg.get("publisher") or "").strip()
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
    # Type-specific fields. Each Zotero itemType names the "where published"
    # field differently (Zotero has no universal `publisher`), so the DataCite
    # `publisher` is routed into the per-type equivalent rather than a single
    # field. Empty values are omitted to avoid writing blank fields.
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
    elif item_type == "dataset":
        # Zotero `dataset` has no `publisher` field; its repository/registry
        # equivalent is `repository` (e.g. "Zenodo").
        if publisher:
            item["repository"] = publisher
    elif item_type == "preprint":
        # Zotero `preprint` uses `repository` for the hosting server (arXiv).
        if publisher:
            item["repository"] = publisher
    elif item_type == "computerProgram":
        # Zotero `computerProgram` uses `company` for the distributor.
        if publisher:
            item["company"] = publisher
    elif item_type == "document":
        if publisher:
            item["publisher"] = publisher

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
# Manifest merge helpers
# ----------------------------------------------------------------------------


def merge_manifest_entries_by_doi(
    prior: list[dict],
    current: list[dict],
) -> list[dict]:
    """
    Merge two manifest entry lists, deduping by case-insensitive DOI.

    Manifest entries (items_skipped, items_failed) carry a ``doi`` key
    plus payload fields (``existing``, ``reason``, ``error``) whose
    shape varies by source. The merge keeps insertion order — prior
    entries first, then current entries — and on collision keeps the
    *current* entry (the fresh run is canonical for whichever fields
    the source last produced). Entries missing a ``doi`` are kept
    verbatim and not deduped against each other.

    Why: pre-2026-05-23 the manifest was rewritten as ``prior + current``
    with no deduplication, so re-importing the same workspace inflated
    the counts (each group-library duplicate counted once per re-run).
    Zotero state was always correct — only the manifest count drifted.
    """
    seen: dict[str, int] = {}
    merged: list[dict] = []
    for entry in list(prior) + list(current):
        doi = entry.get("doi")
        # Treat None, non-string, empty, or whitespace-only DOIs as
        # "no key for deduplication" — keep verbatim, do not collide.
        if not isinstance(doi, str) or not doi.strip():
            merged.append(entry)
            continue
        key = doi.strip().lower()
        if key in seen:
            # Current entry overwrites prior at the same index.
            merged[seen[key]] = entry
        else:
            seen[key] = len(merged)
            merged.append(entry)
    return merged


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
    # ZOTERO_API_KEY_ALL is the Tier-1 broad key (2026-08-24); the
    # retired ZOTERO_API_KEY_PERSONAL remains a fallback until revoked.
    api_key = (os.environ.get("ZOTERO_API_KEY_ALL")
               or os.environ.get("ZOTERO_API_KEY_PERSONAL"))
    staging_key = os.environ.get("ZOTERO_STAGING_COLLECTION")
    missing = [
        n
        for n, v in [
            ("ZOTERO_LIBRARY_ID", library_id),
            ("ZOTERO_API_KEY_ALL", api_key),
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

    # Manifest-based idempotency: skip DOIs already imported by a prior
    # invocation against this workspace. Useful for the 1-item-smoke-test
    # → finish-the-rest workflow, where the Zotero desktop sync may not
    # have refreshed local sqlite between calls.
    manifest_path = workspace / "zotero-import-manifest.json"
    previous_manifest = None
    already_imported: set[str] = set()
    if manifest_path.exists():
        try:
            previous_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"WARNING: prior manifest at {manifest_path} could not "
                f"be parsed ({exc.__class__.__name__}: {exc}); treating "
                f"this run as a fresh import. The corrupt manifest will "
                f"be overwritten.",
                file=sys.stderr,
            )
            previous_manifest = None
        if previous_manifest:
            already_imported = {
                entry["doi"].lower()
                for entry in previous_manifest.get("items_created", [])
            }

    # Derive run timestamp from the workspace name. Prefer the prior
    # manifest's stable run_ts on re-runs (so re-imports stay grouped
    # under one `lit-scout-run:TS` tag) and only fall back to the
    # current time when the workspace name has no embedded timestamp
    # AND there is no prior manifest to anchor the run.
    ws_name = workspace.name
    m = re.search(r"(\d{8}-\d{6})", ws_name)
    if m:
        run_ts = m.group(1)
    elif previous_manifest:
        prior_imported_at = previous_manifest.get("imported_at", "")
        # imported_at is an ISO-8601 string like "2026-05-22T19:02:12+00:00".
        # Strip non-digits to recover a YYYYMMDDHHMMSS-style stem; fall back
        # to current time if the field is missing or malformed.
        digits = re.sub(r"\D", "", prior_imported_at)[:14]
        run_ts = (
            f"{digits[:8]}-{digits[8:14]}"
            if len(digits) == 14
            else datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        )
    else:
        run_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_date = datetime.strptime(run_ts[:8], "%Y%m%d").strftime("%Y-%m-%d")

    # Subcollection name
    query = args.query or "untitled-query"
    subcoll_name = f"{run_date}-{slugify_query(query)}"

    if already_imported:
        print(
            f"# Previous manifest at {manifest_path.name} — "
            f"skipping {len(already_imported)} already-imported DOIs",
            file=sys.stderr,
        )

    # Open sqlite for dedup
    conn = sqlite3.connect(f"file://{ZOTERO_SQLITE}?immutable=1", uri=True)

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
        # Metadata fetch chain: CrossRef → DataCite → OpenAlex.
        #   - CrossRef indexes most journal/book DOIs (richest container data).
        #   - DataCite is authoritative for datasets, software, and the
        #     DataCite-registered DOIs CrossRef does not index (Zenodo, arXiv,
        #     institutional repositories).
        #   - OpenAlex is the broad backstop for anything neither covers.
        # Each helper returns the same internal record shape, so the first
        # non-None result wins and feeds `build_zotero_item` unchanged.
        crossref_msg = fetch_crossref(doi, cr_client)
        if not crossref_msg:
            crossref_msg = fetch_datacite(doi, cr_client)
        if not crossref_msg:
            crossref_msg = fetch_openalex(doi, cr_client)
        if not crossref_msg:
            plan_failed.append(
                (doi, "no record in CrossRef, DataCite, or OpenAlex")
            )
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
        # No explicit sleep here: per-host pacing inside `_request_with_retry`
        # (`_pace_host`) now enforces a polite minimum interval for every host
        # the fetch chain touches, replacing the old flat 0.05 s CrossRef nap.

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
        "items_skipped": merge_manifest_entries_by_doi(
            prior_skipped,
            [{"doi": doi, "existing": hits} for doi, hits in plan_skip],
        ),
        "items_failed": merge_manifest_entries_by_doi(
            prior_failed,
            [
                {"doi": doi, "reason": reason}
                for doi, reason in plan_failed
            ]
            + failed_live,
        ),
        "previous_invocations": (previous_manifest or {}).get("previous_invocations", []) + (
            [{"imported_at": previous_manifest.get("imported_at", "")}]
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
