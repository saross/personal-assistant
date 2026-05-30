#!/usr/bin/env python3
"""
Vector 2 — session-start digest selector (pure module).

Implements the Stage 1 selector from ``wiki/planning/vector-2-design.md``
§6a: a small, byte-capped "what changed since last session" digest that
replaces the ~16 KB recall dump emitted by
``hooks/session-start-retrieval.py``. The recall dump's four bucket
dumps (Recent, Constraints, Gotchas & Patterns, Key Decisions) move
behind ``/recall`` and the tier-2 autonomous-retrieval protocol; only a
mechanical "what changed" counter plus a bounded list of *verified-true*
recent entries is surfaced eagerly.

Design tenets honoured here (design §4):
  - Eager bytes are a budget, not a default — a HARD byte cap, enforced
    by trimming the lowest-rank entries first (no spill, no overflow).
  - Anchors over confidence — surfacing rank is driven by ``verified``
    state and tag overlap, never by the self-reported ``confidence``
    field.
  - Fail soft, never silent — a record whose status cannot be resolved
    is omitted rather than surfaced with a fallback label.

This module is **pure**: no file I/O, no clock reads, no dependency on
the session-start hook module. The caller (``scripts/digest-preview.py``
for the dry-run harness, and in a later pass the live hook itself)
performs the I/O — loading memories, deriving the project, collecting
the project tag profile, and passing a ``now`` — then calls
:func:`build_digest`. Keeping it pure makes the selector unit-testable
in isolation, which is the design's explicit §6c requirement.

The small parsing/tag/overlap helpers are re-implemented here rather
than imported from the hook on purpose: the hook's versions carry
side-effects (e.g. ``_record_bad_timestamp`` mutates module-level
diagnostics) that a pure function must not inherit. The logic is
trivial and stable, so the duplication is deliberate, not accidental.

Marker semantics (verified empirically against the live corpus
2026-05-30, ``data/memories/memories.jsonl``):
  - ``verified`` is stored as the STRING ``"true"`` / ``"false"`` (not a
    JSON boolean). We compare case-insensitively and also tolerate a
    real bool, so the selector is robust to either encoding.
  - ``is_active: false`` marks a memory forgotten via ``/forget``
    (the record also gains a ``revisions`` entry with
    ``action: "forget"``). Forgotten records are NEVER surfaced
    eagerly.
  - A non-empty ``revisions`` list whose newest entry is *not* a forget
    marks a memory updated/corrected via ``/update``.
  - Tags live in ``research_tags`` (string or list).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# ============================================================================
# Configuration (design §5a, §7b)
# ============================================================================

# Hard ceiling on the rendered digest, in bytes (design §5a / §7b).
# Start at 1,500 B; the design flags this for review after a fortnight
# of operation. The cap governs the WHOLE rendered digest (scaffolding +
# entries), not just the entry list.
DEFAULT_BYTE_BUDGET = 1500

# "What changed since" window, in days (design §6a item 1, §7a). Stage 1
# uses a simple wall-clock window; per-project last-engagement is a
# Stage 2 consideration.
DEFAULT_WINDOW_DAYS = 7

# Promoted-recent fallback (design §6a item 3): if the verified-true
# bucket fills less than this fraction of the byte budget, top up with
# the most-recent anchored memories so the digest is not near-empty
# during the verification-backfill window. Temporary; removed in
# Stage 2 once the corpus is verified-dense.
FALLBACK_MIN_FILL = 0.5

# Fallback to ``content`` when ``summary`` is absent; truncate to keep a
# single rogue long memory from blowing the per-entry budget (mirrors
# the hook's CONTENT_FALLBACK behaviour, smaller because the digest is
# tighter).
CONTENT_FALLBACK_MAX_CHARS = 200

# Cap on how many categories the what-changed line itemises. A noisy
# auto-extracted corpus can produce 25+ categories in a 7-day window;
# itemising all of them turns the "small, mechanical" counter (design
# §5c) into a histogram that crowds out the verified entries. The
# busiest few plus a "+N more" tail carries the signal at a fraction of
# the bytes.
MAX_CATEGORY_BREAKDOWN = 6


# ============================================================================
# Result type
# ============================================================================


@dataclass
class DigestResult:
    """Output of :func:`build_digest`.

    ``text`` is the final rendered digest. Its size is ``<= byte_budget``
    whenever the budget is at least the fixed scaffolding floor (~550 B —
    the title, what-changed line, anti-confabulation reminder, and depth
    footer, which are load-bearing and never trimmed). Below that floor
    the minimal scaffolding is returned intact, which may exceed the
    budget — the entries are the only variable the cap can squeeze, and
    the live hook always runs well above the floor (default 1,500 B).
    ``entries`` is the list of memory records actually surfaced, in
    render order. ``counter`` is the mechanical what-changed tally. The
    remaining fields are observability hooks for the §8 empirical-testing
    plan (digest.log).
    """

    text: str
    rendered_bytes: int
    entries: list[dict]
    counter: dict
    used_fallback: bool
    verified_available: int
    window_days: int
    byte_budget: int


# ============================================================================
# Pure helpers (no I/O, no side effects)
# ============================================================================


def parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp to a tz-aware UTC datetime.

    Accepts both the ``Z`` suffix and ``+00:00`` offset forms; assumes
    UTC for a tz-naive string. Returns ``None`` on a missing or
    unparseable value (the caller treats that as "not in window").
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def tags_of(mem: dict) -> set[str]:
    """Return a memory's tags as a lowercased set.

    Tolerates the ``research_tags`` field being a single string, a list,
    or absent.
    """
    raw = mem.get("research_tags") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(t).lower() for t in raw}


def overlap_score(mem: dict, project_tags: set[str]) -> int:
    """Count a memory's tags that overlap the project tag profile.

    Returns 0 when ``project_tags`` is empty — the caller then falls
    back to pure recency ranking (the personal-assistant hub case, where
    the hook deliberately collects no single-project profile).
    """
    if not project_tags:
        return 0
    return len(tags_of(mem) & project_tags)


def is_verified_true(mem: dict) -> bool:
    """True iff ``verified`` resolves to true.

    The live corpus stores ``verified`` as the string ``"true"``; older
    code paths or tests may use a real bool. Both are accepted; anything
    else (``"false"``, ``"pending"``, ``None``, absent) is false.
    """
    v = mem.get("verified")
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() == "true"


def is_active(mem: dict) -> bool:
    """False only when explicitly forgotten (``is_active: false``).

    A memory with no ``is_active`` field is active (legacy default).
    Forgotten memories must never be surfaced eagerly.
    """
    return mem.get("is_active", True) is not False


def has_anchors(mem: dict) -> bool:
    """True iff the memory carries a non-empty ``anchors`` list.

    Used by the promoted-recent fallback: an anchored memory has been
    through verification (even if the result is not yet ``true``), so it
    is a safer top-up than an un-verified one.
    """
    return bool(mem.get("anchors"))


def newest_revision(mem: dict) -> dict | None:
    """Return the most recent revision entry, or ``None``.

    ``revisions`` is a list of ``{revised_at, action, reason}`` dicts.
    "Most recent" is by ``revised_at``; entries with an unparseable
    timestamp sort to the bottom.
    """
    revs = mem.get("revisions") or []
    if not isinstance(revs, list) or not revs:
        return None
    return max(
        revs,
        key=lambda r: parse_iso(r.get("revised_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )


# ============================================================================
# What-changed counter (design §6a item 1)
# ============================================================================


def count_changes(
    memories: list[dict],
    *,
    now: datetime,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict:
    """Tally new / updated / forgotten activity inside the window.

    Mechanical; no LLM in the path. Definitions:
      - **new**: ``created_at`` falls in the window and the memory is
        still active.
      - **updated**: the newest ``revisions`` entry is in the window and
        its ``action`` is not a forget.
      - **forgotten**: the newest ``revisions`` entry is in the window
        and its ``action`` is ``"forget"`` (equivalently
        ``is_active is False`` with an in-window forget revision).

    Also returns a ``categories`` breakdown of the *new* memories
    (e.g. ``{"decision": 4, "progress": 3}``) for the digest's
    one-line "what changed" summary.
    """
    cutoff = now.timestamp() - window_days * 86400
    new = updated = forgotten = 0
    categories: dict[str, int] = {}

    for mem in memories:
        created = parse_iso(mem.get("created_at"))
        created_in_window = created is not None and created.timestamp() >= cutoff
        if created_in_window and is_active(mem):
            new += 1
            cat = mem.get("category", "unknown")
            categories[cat] = categories.get(cat, 0) + 1

        # updated/forgotten count only *pre-existing* memories that changed
        # in the window. A memory both created and revised in-window is
        # already captured by ``new`` (or, if forgotten same-window, is
        # net churn) — counting its revision too would double-count it in
        # the "what changed" line.
        if not created_in_window:
            rev = newest_revision(mem)
            if rev is not None:
                revised = parse_iso(rev.get("revised_at"))
                if revised is not None and revised.timestamp() >= cutoff:
                    if str(rev.get("action", "")).strip().lower() == "forget":
                        forgotten += 1
                    else:
                        updated += 1

    return {
        "new": new,
        "updated": updated,
        "forgotten": forgotten,
        "categories": categories,
    }


# ============================================================================
# Candidate ranking (design §6a items 2 + 3)
# ============================================================================


def _in_window(mem: dict, *, now: datetime, window_days: int) -> bool:
    created = parse_iso(mem.get("created_at"))
    if created is None:
        return False
    return created.timestamp() >= now.timestamp() - window_days * 86400


def _rank_key(mem: dict, project_tags: set[str]):
    """Sort key: tag overlap (desc), then recency (desc)."""
    created = parse_iso(mem.get("created_at")) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    return (overlap_score(mem, project_tags), created)


def rank_verified(
    memories: list[dict],
    *,
    now: datetime,
    project_tags: set[str],
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Verified-true, active, in-window memories ranked best-first.

    Ranking is tag overlap with the project profile (descending), then
    recency (descending). When ``project_tags`` is empty, overlap is 0
    for all and ranking collapses to pure recency.
    """
    pool = [
        m
        for m in memories
        if is_verified_true(m)
        and is_active(m)
        and _in_window(m, now=now, window_days=window_days)
    ]
    pool.sort(key=lambda m: _rank_key(m, project_tags), reverse=True)
    return pool


def rank_fallback(
    memories: list[dict],
    *,
    now: datetime,
    exclude_ids: set,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[dict]:
    """Promoted-recent fallback pool (design §6a item 3).

    Active, in-window memories that carry non-empty ``anchors`` (i.e.
    went through verification even if not yet ``true``), excluding
    anything already chosen, ranked by recency. Temporary scaffolding
    removed in Stage 2.
    """
    pool = [
        m
        for m in memories
        if id(m) not in exclude_ids
        and is_active(m)
        and has_anchors(m)
        and not is_verified_true(m)
        and _in_window(m, now=now, window_days=window_days)
    ]
    pool.sort(
        key=lambda m: parse_iso(m.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return pool


# ============================================================================
# Rendering (byte-authoritative; enforces the hard cap)
# ============================================================================


def render_entry(mem: dict) -> str:
    """Render one memory as a compact digest line.

    Shape mirrors the hook's ``format_memory``:
    ``[category] summary | tag1, tag2 [YYYY-MM-DD]``. ``summary`` is
    emitted verbatim (already bounded by the extraction hook); a missing
    summary falls back to a truncated ``content``.
    """
    category = mem.get("category", "unknown")
    summary = mem.get("summary")
    # Only a non-empty *string* summary is emitted verbatim; a non-string
    # (or empty) value falls through to content rather than silently
    # rendering an empty body — "fail soft, never silent" (design §4).
    if isinstance(summary, str) and summary:
        body = summary
    else:
        raw = mem.get("content", "") or ""
        if len(raw) > CONTENT_FALLBACK_MAX_CHARS:
            body = raw[:CONTENT_FALLBACK_MAX_CHARS].rstrip() + "… [/recall for full]"
        else:
            body = raw
    line = f"[{category}] {body}"
    tags = sorted(tags_of(mem))
    if tags:
        line += f" | {', '.join(tags)}"
    created = (mem.get("created_at") or "")[:10]
    if created:
        line += f" [{created}]"
    return line


def _format_categories(categories: dict, max_items: int = MAX_CATEGORY_BREAKDOWN) -> str:
    """Render the new-memory category breakdown, busiest first.

    Capped at ``max_items`` categories with a ``+N more`` tail. The
    what-changed counter is meant to be "small, mechanical, no per-entry
    surface" (design §5c); on a noisy auto-extracted corpus the full
    breakdown can run to dozens of categories and crowd the verified
    entries out of the byte budget, so we surface only the busiest few.
    """
    if not categories:
        return ""
    parts = sorted(categories.items(), key=lambda kv: (-kv[1], kv[0]))
    head = parts[:max_items]
    rendered = ", ".join(f"{cat} {n}" for cat, n in head)
    remaining = len(parts) - len(head)
    if remaining > 0:
        rendered += f", +{remaining} more"
    return rendered


def _assemble(
    counter: dict,
    entries: list[dict],
    *,
    window_days: int,
    verified_available: int,
    since_label: str | None,
) -> str:
    """Assemble the full digest text for a given entry set.

    Pure string builder — called repeatedly by :func:`build_digest`
    during the greedy byte-cap walk, then once more for the final text.
    """
    since = f" since {since_label}" if since_label else f" in the last {window_days} days"
    cat_break = _format_categories(counter.get("categories", {}))
    changed = f"{counter['new']} new"
    if cat_break:
        changed += f" ({cat_break})"
    changed += f", {counter['updated']} updated, {counter['forgotten']} forgotten"

    lines = [
        "# Session-start digest",
        "",
        f"**What changed{since}:** {changed}.",
        "",
        (
            f"**Verified-true entries from the last {window_days} days "
            f"({len(entries)} shown of {verified_available} available):**"
        ),
    ]
    if entries:
        lines += [f"- {render_entry(m)}" for m in entries]
    else:
        lines.append("- (none yet — corpus still building verified coverage)")
    lines += [
        "",
        (
            "**Anti-confabulation:** unverified content from prior sessions "
            "is not surfaced here; it is a pointer, not an authority. "
            "Use `/recall <query>` to fetch it explicitly."
        ),
        "",
        (
            "**Depth on demand:** `/recall <query>` or "
            "`scripts/fetch-memories.py --tag <t>` / `--query \"…\"` "
            "(full protocol: `global-claude-md/tier-2-retrieval.md`)."
        ),
    ]
    return "\n".join(lines)


def build_digest(
    memories: list[dict],
    *,
    now: datetime,
    project_tags: set[str],
    byte_budget: int = DEFAULT_BYTE_BUDGET,
    window_days: int = DEFAULT_WINDOW_DAYS,
    fallback_min_fill: float = FALLBACK_MIN_FILL,
    since_label: str | None = None,
) -> DigestResult:
    """Build the byte-capped session-start digest (the Stage 1 entry point).

    Pure function. Steps:
      1. Tally what changed in the window (:func:`count_changes`).
      2. Rank verified-true in-window memories (:func:`rank_verified`).
      3. Add entries in rank order while the *whole rendered digest*
         stays ``<= byte_budget``, skipping any single entry too large to
         fit (design §6a item 4). Highest-rank entries that fit win; an
         oversized entry is skipped, not allowed to abandon the entries
         behind it.
      4. If the verified entries fill less than ``fallback_min_fill`` of
         the budget, top up from the promoted-recent fallback pool
         (design §6a item 3), under the same hard cap.

    The returned ``text`` is ``<= byte_budget`` UTF-8 bytes provided the
    budget is at least the fixed scaffolding floor (~550 B); below that
    floor the minimal scaffolding is returned intact (see
    :class:`DigestResult`). The live hook runs at 1,500 B, well above
    the floor.
    """
    counter = count_changes(memories, now=now, window_days=window_days)
    verified = rank_verified(
        memories, now=now, project_tags=project_tags, window_days=window_days
    )
    verified_available = len(verified)

    def fits(entries: list[dict]) -> tuple[bool, str]:
        text = _assemble(
            counter,
            entries,
            window_days=window_days,
            verified_available=verified_available,
            since_label=since_label,
        )
        return len(text.encode("utf-8")) <= byte_budget, text

    # Greedy add of verified entries under the hard cap, in rank order.
    # We ``continue`` rather than ``break`` on a non-fitting candidate:
    # byte size is NOT monotonic with rank, so a single oversized
    # high-rank entry must not abandon the smaller lower-rank entries
    # behind it (that produced an empty digest in testing). Result: the
    # highest-rank entries that *fit*, still in rank order. The in-window
    # pool is bounded (a few hundred at a 7-day window), so iterating it
    # in full is cheap.
    chosen: list[dict] = []
    for cand in verified:
        ok, _ = fits(chosen + [cand])
        if ok:
            chosen.append(cand)

    # Promoted-recent fallback: only if verified content under-fills the
    # budget. Measured against the rendered digest size, per design §6a.
    used_fallback = False
    _, current_text = fits(chosen)
    if len(current_text.encode("utf-8")) < fallback_min_fill * byte_budget:
        exclude = {id(m) for m in chosen}
        for cand in rank_fallback(
            memories, now=now, exclude_ids=exclude, window_days=window_days
        ):
            ok, _ = fits(chosen + [cand])
            if ok:
                chosen.append(cand)
                used_fallback = True

    text = _assemble(
        counter,
        chosen,
        window_days=window_days,
        verified_available=verified_available,
        since_label=since_label,
    )
    return DigestResult(
        text=text,
        rendered_bytes=len(text.encode("utf-8")),
        entries=chosen,
        counter=counter,
        used_fallback=used_fallback,
        verified_available=verified_available,
        window_days=window_days,
        byte_budget=byte_budget,
    )


# ============================================================================
# Instrumentation primitive (design §8 / §9 pre-step) — ready for the
# live hook to call in the PASS 2 cutover. Best-effort; never raises.
# ============================================================================


def digest_log_line(result: DigestResult, *, now: datetime) -> str:
    """Format a one-line ``digest.log`` record for a built digest.

    Tab-separated: timestamp, rendered_bytes, byte_budget, entries shown,
    verified available, new/updated/forgotten counts, fallback flag.
    The caller appends this to ``data/logs/digest.log``; keeping the
    formatting here (pure) means the live hook and the dry-run harness
    log identically.
    """
    c = result.counter
    return (
        f"{now.isoformat()}\t"
        f"bytes={result.rendered_bytes}\t"
        f"budget={result.byte_budget}\t"
        f"shown={len(result.entries)}\t"
        f"verified_available={result.verified_available}\t"
        f"new={c['new']}\tupdated={c['updated']}\tforgotten={c['forgotten']}\t"
        f"fallback={result.used_fallback}"
    )
