"""
Shared HTTP retry helper for sync scripts.

Background
----------
The 2026-05-02 audit (inter-cluster issue IC7) catalogued three different
rate-limit / retry idioms across the integration scripts:

* ``scripts/lit-search.py`` — Batch 1 added explicit ``Retry-After`` honour
  for HTTP 429 in ``_safe_get`` (the reference shape).
* ``scripts/sync-to-zotero.py`` — flat 0.5 s sleep between API writes.
* ``scripts/embed.py`` — no retry, no backoff at all.

Different idioms in adjacent files mean every transient outage is handled
slightly differently. This module factors the retry policy down to one
canonical implementation so new callers (and refactors of the existing
ones) share the same shape.

Scope of this module
--------------------
The helper deliberately does **not** ship a one-size-fits-all client
wrapper. ``embed.py`` uses ``urllib`` from the standard library and we are
not introducing ``requests`` or ``httpx`` as a new dependency just for
retries. ``lit-search.py`` already has a working ``_safe_get`` whose
public test surface pins the exact backoff value (5.0 s), so we leave it
in place and route only the policy-decision parts through this module
for cross-script consistency.

What this module provides
-------------------------
1. :func:`parse_retry_after` — parse an HTTP ``Retry-After`` header value
   (seconds form only; HTTP-date form is not used by any of our upstream
   APIs) and return a clamped float in seconds.
2. :func:`compute_backoff` — exponential backoff with deterministic
   jitter, given an attempt index. Pure function; trivially testable.
3. :func:`is_transient_status` — predicate for "should we retry?"
4. :func:`urlopen_with_retry` — convenience wrapper around
   :func:`urllib.request.urlopen` that retries transient failures with
   exponential backoff and (optionally) honours ``Retry-After`` on 429.
   Used by ``embed.py``.

Design notes
------------
* Backoff uses ``base * 2**(attempt-1)`` then adds jitter in
  ``[0, base/2)``. With ``base=1.0`` and ``max_attempts=3`` the worst-case
  total wait between attempts is ``1 + 2 + jitter ≈ 3.5 s`` — long enough
  to ride out a brief Ollama hiccup, short enough not to stall a cron
  tick.
* Jitter source is ``random.random()``. Tests that need determinism
  ``patch("scripts._http_retry.random.random", return_value=0.0)`` to
  zero it out.
* On 429 with ``Retry-After`` present, we honour the server's hint
  instead of our own backoff (clamped to ``[1.0, 30.0]`` so a misbehaving
  header cannot stall a cron run indefinitely).
* Transient status codes default to ``(408, 429, 500, 502, 503, 504)``;
  callers can override.
* Exceptions raised on the *final* attempt propagate to the caller. The
  helper does not swallow errors — the existing call sites already log
  and return ``None`` on failure, and we want to preserve their logging
  shape rather than duplicate it here.
"""

from __future__ import annotations

import logging
import random
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("http-retry")

# Default transient HTTP status codes — RFC 9110 408 + 429 + the common
# 5xx outage codes upstream APIs (CrossRef, S2, OpenAlex, Ollama, Zotero)
# actually emit.
DEFAULT_TRANSIENT_STATUS: tuple[int, ...] = (408, 429, 500, 502, 503, 504)

# Retry-After upper bound. A misbehaving server sending "Retry-After: 86400"
# would otherwise stall the caller for a day; we cap aggressively so cron
# ticks remain bounded.
RETRY_AFTER_MAX_S = 30.0
RETRY_AFTER_MIN_S = 1.0


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """
    Parse an HTTP ``Retry-After`` header value (seconds form).

    The header may be either a non-negative integer (seconds) or an
    HTTP-date. We support only the integer form because none of our
    upstream APIs (CrossRef, Semantic Scholar, OpenAlex, Ollama, Zotero)
    emit the HTTP-date form in practice.

    Parameters
    ----------
    value:
        Raw header value, or ``None`` if absent.

    Returns
    -------
    float or None
        Clamped seconds in ``[RETRY_AFTER_MIN_S, RETRY_AFTER_MAX_S]`` if
        parsing succeeded, otherwise ``None`` (caller should fall back to
        its own backoff).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        # HTTP-date form or junk — caller falls back to its own backoff.
        return None
    if seconds < 0:
        return None
    return min(RETRY_AFTER_MAX_S, max(RETRY_AFTER_MIN_S, seconds))


def compute_backoff(
    attempt: int,
    *,
    base_backoff: float = 1.0,
    jitter: bool = True,
) -> float:
    """
    Compute the wait time before the next retry attempt.

    Uses exponential backoff: ``base_backoff * 2**(attempt - 1)``. With
    ``jitter=True`` (default), adds ``random.random() * (base_backoff /
    2)`` so concurrent callers do not retry in lockstep.

    Parameters
    ----------
    attempt:
        1-based attempt index (1 = the wait between the *first* failure
        and the *second* attempt).
    base_backoff:
        Multiplier in seconds. Defaults to 1.0.
    jitter:
        If ``True``, add a small random offset. Tests can suppress this
        by patching ``random.random``.

    Returns
    -------
    float
        Seconds to wait. Always non-negative; never below 0.
    """
    if attempt < 1:
        attempt = 1
    delay = base_backoff * (2 ** (attempt - 1))
    if jitter:
        delay += random.random() * (base_backoff / 2.0)
    return max(0.0, delay)


def is_transient_status(
    status_code: int,
    transient_status: tuple[int, ...] = DEFAULT_TRANSIENT_STATUS,
) -> bool:
    """Return ``True`` if ``status_code`` is in the retryable set."""
    return status_code in transient_status


# ---------------------------------------------------------------------------
# urllib convenience wrapper (used by embed.py)
# ---------------------------------------------------------------------------


def urlopen_with_retry(
    request: urllib.request.Request,
    *,
    max_attempts: int = 3,
    base_backoff: float = 1.0,
    timeout: float = 30.0,
    honour_retry_after: bool = True,
    transient_status: tuple[int, ...] = DEFAULT_TRANSIENT_STATUS,
):
    """
    Open a URL with exponential backoff and ``Retry-After`` honour.

    A thin wrapper around :func:`urllib.request.urlopen` that retries on
    transient failures. The wrapper does not buffer or read the response
    body — the caller receives the raw response object inside a context
    manager-aware return value, exactly as :func:`urllib.request.urlopen`
    would.

    Behaviour
    ---------
    * Network errors (``urllib.error.URLError``, ``OSError``,
      ``TimeoutError``) — retried up to ``max_attempts`` times with
      exponential backoff plus jitter.
    * ``urllib.error.HTTPError`` with a transient status code — same
      retry policy. On 429, if ``honour_retry_after`` is ``True`` and the
      response carries a parseable ``Retry-After`` header, we sleep for
      the header value (clamped) instead of our own backoff.
    * ``urllib.error.HTTPError`` with a terminal status code (4xx other
      than 408/429) — propagates immediately without retry.
    * Final-attempt failures propagate to the caller, who is responsible
      for logging and returning a sentinel ("graceful degradation"). This
      is deliberate: the existing ``embed.py`` already has a careful
      ``except`` ladder that we do not want to duplicate here.

    Parameters
    ----------
    request:
        A pre-built :class:`urllib.request.Request`. The caller controls
        method, headers, body.
    max_attempts:
        Total attempts including the first. Default 3.
    base_backoff:
        Base seconds for exponential backoff. Default 1.0.
    timeout:
        Per-attempt timeout in seconds, passed through to
        :func:`urllib.request.urlopen`.
    honour_retry_after:
        If ``True`` (default), 429 responses with a ``Retry-After``
        header use the header value instead of computed backoff.
    transient_status:
        HTTP status codes considered retryable. Override if you need
        stricter or looser semantics.

    Returns
    -------
    The raw response object returned by :func:`urllib.request.urlopen`.
    Caller must use it as a context manager and read it before the
    context closes, exactly as with the unwrapped function.

    Raises
    ------
    urllib.error.HTTPError
        On the final attempt for HTTP errors.
    urllib.error.URLError
        On the final attempt for network errors.
    OSError, TimeoutError
        On the final attempt for lower-level failures.
    """
    if max_attempts < 1:
        max_attempts = 1

    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if not is_transient_status(exc.code, transient_status):
                # Terminal 4xx — do not retry.
                raise
            if attempt == max_attempts:
                raise
            wait = _wait_after_http_error(
                exc, attempt, base_backoff, honour_retry_after,
            )
            logger.debug(
                "HTTP %d on attempt %d/%d; waiting %.2fs before retry",
                exc.code, attempt, max_attempts, wait,
            )
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            wait = compute_backoff(attempt, base_backoff=base_backoff)
            logger.debug(
                "Network error on attempt %d/%d (%s); waiting %.2fs",
                attempt, max_attempts, type(exc).__name__, wait,
            )
            time.sleep(wait)

    # Defensive: should be unreachable because the loop either returns or
    # re-raises on the final attempt.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("urlopen_with_retry exhausted attempts without raising")


def _wait_after_http_error(
    exc: urllib.error.HTTPError,
    attempt: int,
    base_backoff: float,
    honour_retry_after: bool,
) -> float:
    """Decide how long to wait after a transient HTTP error."""
    if honour_retry_after and exc.code == 429:
        # ``HTTPError.headers`` is ``email.message.Message``-shaped.
        retry_after = None
        try:
            retry_after = exc.headers.get("Retry-After")
        except AttributeError:
            retry_after = None
        parsed = parse_retry_after(retry_after)
        if parsed is not None:
            return parsed
    return compute_backoff(attempt, base_backoff=base_backoff)
