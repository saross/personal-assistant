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
    # Vector 2c observability (defaulted so existing construction sites and
    # the flag-OFF path are unaffected): whether focus-aware ranking was
    # active this build, and whether a hard project scope was applied.
    focus_active: bool = False
    scoped: bool = False


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


def matches_project(mem: dict, project_id: str | None) -> bool:
    """True iff the memory is in scope for a hard project filter (Vector 2c).

    Mirrors the hook's ``is_same_project`` so the two cannot drift:
      - ``project_id`` is ``None`` → no scoping; everything is in scope
        (the personal-assistant hub case, where the hook deliberately
        nulls the current project for cross-project visibility).
      - a memory with no ``project`` field → legacy, pre-project-tagging
        record → treated as in scope rather than penalised.
      - otherwise exact match on the encoded project id.
    """
    if project_id is None:
        return True
    mem_project = mem.get("project")
    if not mem_project:
        return True
    return mem_project == project_id


def focus_score(mem: dict, focus_keywords: set[str]) -> int:
    """Count how many focus keywords a memory matches (Vector 2c, coarse).

    A keyword matches when it is a substring of the memory's lowercased
    ``project`` id OR of any of its lowercased tags. This is *coarse by
    design* (the keyword is the last path segment of a FOCUS.md slot's
    ``**Project:**`` line, e.g. ``research/inscriptions`` → ``inscriptions``):
    it bridges the logical focus label to both the encoded cwd project
    (``-home-shawn-Code-inscriptions``) and differently-named sibling repos
    (``efn`` matches ``…-Groundsite-EFN-Planning``), at the cost of an
    occasional loose match. Returns 0 when ``focus_keywords`` is empty, so
    the ranking collapses to the prior tag-overlap-then-recency behaviour
    (the flag-OFF guarantee). Keywords shorter than three characters are
    ignored to avoid pathological substring hits.
    """
    if not focus_keywords:
        return 0
    proj = str(mem.get("project") or "").lower()
    tags = tags_of(mem)
    matched = 0
    for kw in focus_keywords:
        if len(kw) < 3:
            continue
        if kw in proj or any(kw in t for t in tags):
            matched += 1
    return matched


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


def _rank_key(
    mem: dict,
    project_tags: set[str],
    focus_keywords: set[str] = frozenset(),
):
    """Sort key for the verified pool. Two regimes, by focus mode.

    - **Focus mode (``focus_keywords`` non-empty, Vector 2c on):**
      ``(focus_score, recency)``. Focus match dominates; recency breaks
      ties. The tag-overlap term is deliberately dropped here: in the
      personal-assistant hub the hook collects *all* corpus tags as the
      profile, so ``overlap_score`` degenerates to "how many tags does
      this memory carry" and biases toward the most verbose project,
      crowding out the other focus slots. Recency gives balanced,
      intent-faithful ordering across slots.
    - **Flag-OFF (``focus_keywords`` empty):** ``(overlap_score, recency)``
      — byte-for-byte the pre-2c key, so the digest is unchanged.

    Both branches return same-shape tuples within any one sort call
    (``focus_keywords`` is fixed per call), so the keys are comparable.
    """
    created = parse_iso(mem.get("created_at")) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    if focus_keywords:
        return (focus_score(mem, focus_keywords), created)
    return (overlap_score(mem, project_tags), created)


def rank_verified(
    memories: list[dict],
    *,
    now: datetime,
    project_tags: set[str],
    window_days: int = DEFAULT_WINDOW_DAYS,
    project_id: str | None = None,
    focus_keywords: set[str] | None = None,
) -> list[dict]:
    """Verified-true, active, in-window memories ranked best-first.

    Ranking is focus match (descending), then tag overlap with the project
    profile (descending), then recency (descending). When ``focus_keywords``
    and ``project_tags`` are both empty, ranking collapses to pure recency.

    ``project_id`` (Vector 2c) applies a hard project scope via
    :func:`matches_project`: when set, only same-project (and legacy
    no-project) memories are eligible. ``None`` means no scoping — the
    personal-assistant hub case.
    """
    focus_keywords = focus_keywords or set()
    pool = [
        m
        for m in memories
        if is_verified_true(m)
        and is_active(m)
        and _in_window(m, now=now, window_days=window_days)
        and matches_project(m, project_id)
    ]
    pool.sort(key=lambda m: _rank_key(m, project_tags, focus_keywords), reverse=True)
    return pool


def rank_fallback(
    memories: list[dict],
    *,
    now: datetime,
    exclude_ids: set,
    window_days: int = DEFAULT_WINDOW_DAYS,
    project_id: str | None = None,
) -> list[dict]:
    """Promoted-recent fallback pool (design §6a item 3).

    Active, in-window memories that carry non-empty ``anchors`` (i.e.
    went through verification even if not yet ``true``), excluding
    anything already chosen, ranked by recency. ``project_id`` (Vector 2c)
    applies the same hard project scope as :func:`rank_verified`, so a
    scoped digest never tops up with off-project records. The 2026-05-30
    feasibility reframe (design §6b) establishes this fallback as the
    permanent handler for anchor-less records, not a migration stopgap.
    """
    pool = [
        m
        for m in memories
        if id(m) not in exclude_ids
        and is_active(m)
        and has_anchors(m)
        and not is_verified_true(m)
        and _in_window(m, now=now, window_days=window_days)
        and matches_project(m, project_id)
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
    focus_label: str | None = None,
) -> str:
    """Assemble the full digest text for a given entry set.

    Pure string builder — called repeatedly by :func:`build_digest`
    during the greedy byte-cap walk, then once more for the final text.

    ``focus_label`` (Vector 2c), when non-empty, adds one italic line
    naming what the verified entries were ranked for — the cheap
    legibility cue that makes the otherwise-invisible focus ranking
    explicit (Option 3). Absent/empty → no line → byte-identical to the
    pre-2c digest (the flag-OFF guarantee).
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
    ]
    if focus_label:
        lines += [f"_Verified entries ranked for current focus: {focus_label}._", ""]
    lines.append(
        f"**Verified-true entries from the last {window_days} days "
        f"({len(entries)} shown of {verified_available} available):**"
    )
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
    project_id: str | None = None,
    focus_keywords: set[str] | None = None,
    focus_label: str | None = None,
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

    Vector 2c parameters (all default to the pre-2c behaviour, so omitting
    them is byte-identical to the flag-OFF digest):
      - ``project_id`` applies a hard project scope to both the verified
        and fallback pools (:func:`matches_project`); ``None`` = no scope.
      - ``focus_keywords`` makes focus match the primary ranking term
        (:func:`focus_score`); empty = ranking unchanged.
      - ``focus_label`` adds the one-line legibility cue naming the focus;
        empty = no line.

    The returned ``text`` is ``<= byte_budget`` UTF-8 bytes provided the
    budget is at least the fixed scaffolding floor (~550 B); below that
    floor the minimal scaffolding is returned intact (see
    :class:`DigestResult`). The live hook runs at 1,500 B, well above
    the floor.
    """
    focus_keywords = focus_keywords or set()
    counter = count_changes(memories, now=now, window_days=window_days)
    verified = rank_verified(
        memories,
        now=now,
        project_tags=project_tags,
        window_days=window_days,
        project_id=project_id,
        focus_keywords=focus_keywords,
    )
    verified_available = len(verified)

    def fits(entries: list[dict]) -> tuple[bool, str]:
        text = _assemble(
            counter,
            entries,
            window_days=window_days,
            verified_available=verified_available,
            since_label=since_label,
            focus_label=focus_label,
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
            memories,
            now=now,
            exclude_ids=exclude,
            window_days=window_days,
            project_id=project_id,
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
        focus_label=focus_label,
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
        focus_active=bool(focus_keywords),
        scoped=project_id is not None,
    )


# ============================================================================
# Instrumentation primitive (design §8 / §9 pre-step) — ready for the
# live hook to call in the PASS 2 cutover. Best-effort; never raises.
# ============================================================================


def digest_log_line(result: DigestResult, *, now: datetime) -> str:
    """Format a one-line ``digest.log`` record for a built digest.

    Tab-separated: timestamp, rendered_bytes, byte_budget, entries shown,
    verified available, new/updated/forgotten counts, fallback flag, and
    the Vector 2c ``focus``/``scoped`` flags (appended last so existing
    positional parsers of the earlier fields are unaffected). The caller
    appends this to ``data/logs/digest.log``; keeping the formatting here
    (pure) means the live hook and the dry-run harness log identically.
    """
    c = result.counter
    return (
        f"{now.isoformat()}\t"
        f"bytes={result.rendered_bytes}\t"
        f"budget={result.byte_budget}\t"
        f"shown={len(result.entries)}\t"
        f"verified_available={result.verified_available}\t"
        f"new={c['new']}\tupdated={c['updated']}\tforgotten={c['forgotten']}\t"
        f"fallback={result.used_fallback}\t"
        f"focus={result.focus_active}\tscoped={result.scoped}"
    )


# ============================================================================
# Vector 2b — scratchpad section capper (shared byte-budget primitive)
# ============================================================================
#
# Vector 2 caps the *recall dump* by ranking-and-dropping noisy memory
# records (build_digest above). Vector 2b caps the *scratchpad* — a
# curated principle log with no ``verified`` field, no decay, and no
# per-entry score, so the ranker is the wrong shape (see
# ``wiki/planning/vector-2b-design.md`` §3). What the two SHOULD share,
# per the parent design §7f, is the byte-budget *discipline*: greedy-keep
# whole units in document order while the rendered whole stays under a
# hard UTF-8 byte cap. That discipline lived only inside ``build_digest``'s
# ``fits()`` closure; this function lifts it into a reusable primitive for
# markdown, so Vector 2b does not re-invent it.

# Visible marker appended when the capper drops one or more sections, so a
# trim is never silent (design §4 "fail soft, never silent"). The marker
# nudges the human, principle-preserving lever (``/retro`` distillation),
# which is primary; the byte cap is only a regrowth backstop.
SCRATCHPAD_TRIM_MARKER = (
    "_[scratchpad trimmed to byte budget — run `/retro` to distil; "
    "use `/recall` for anything dropped]_"
)


def _split_markdown_sections(text: str) -> tuple[str, list[str]]:
    """Partition ``text`` into (preamble, level-2 sections).

    The preamble is every line before the first ``## `` heading (the
    ``# `` title plus any intro). Each section runs from one ``## `` line
    up to (but not including) the next. The partition is exact and
    gap-free: ``"\\n".join([preamble, *sections])`` reconstructs the input
    verbatim whenever the preamble is non-empty, so dropping a section just
    omits its line range.

    Caveat — empty preamble: when ``text`` begins with ``## `` on its first
    line the preamble is ``""`` and the verbatim-join would prepend a
    spurious ``\\n``. The sole caller (:func:`cap_markdown_to_budget`)
    filters empty pieces before joining, so its output is unaffected; any
    other caller that needs verbatim reconstruction must drop the empty
    preamble itself (``[preamble, *sections] if preamble else sections``).

    Note: a ``## `` at the start of a line inside a fenced code block
    would be mis-read as a heading. The scratchpad is plain principle
    bullets with no such fences, so this is an accepted limitation rather
    than a handled case.
    """
    lines = text.split("\n")
    heading_idxs = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if not heading_idxs:
        return text, []
    preamble = "\n".join(lines[: heading_idxs[0]])
    sections: list[str] = []
    for j, start in enumerate(heading_idxs):
        end = heading_idxs[j + 1] if j + 1 < len(heading_idxs) else len(lines)
        sections.append("\n".join(lines[start:end]))
    return preamble, sections


def cap_markdown_to_budget(
    text: str,
    byte_budget: int,
    *,
    trim_marker: str = SCRATCHPAD_TRIM_MARKER,
) -> tuple[str, bool]:
    """Keep whole ``## `` sections in document order under a hard byte cap.

    Mirrors :func:`build_digest`'s byte discipline for markdown instead of
    memory records:

      1. If ``text`` is already ``<= byte_budget`` UTF-8 bytes, return it
         **unchanged** (fast path → byte-identical output when nothing is
         dropped; this is what keeps the flag-OFF / under-budget cases
         indistinguishable from today).
      2. Otherwise greedily keep whole sections, in document order, while
         the rendered whole (preamble + kept sections + trim marker) stays
         within budget. Byte size is not monotonic across sections, so a
         non-fitting section is **skipped, not break** — a later, smaller
         section may still fit (same rationale as the ``continue`` in
         ``build_digest``).
      3. The preamble (``# `` title + intro before the first ``## ``) is
         ALWAYS kept, even if it alone exceeds the budget — fail-soft, the
         header is never lost and a section is never split mid-principle.

    Scaffolding-floor contract (mirrors :class:`DigestResult`): the result
    is ``<= byte_budget`` *provided the budget is at least the floor* —
    here ``len(preamble) + len(trim_marker) + 2`` bytes, the smallest
    trimmed render (preamble + blank line + marker, with every section
    dropped). Below that floor the preamble-plus-marker is returned intact
    and MAY exceed the budget — the sections are the only variable the cap
    can squeeze, exactly as ``build_digest`` cannot shrink its own
    scaffolding. The live budgets (18 KB / 8 KB) sit far above any real
    scratchpad's floor (preamble ~hundreds of bytes, marker ~100 B), so the
    sub-floor branch is not reachable in production.

    Returns ``(capped_text, was_trimmed)``. ``was_trimmed`` is True iff at
    least one section was dropped (in which case ``trim_marker`` is
    present in the output — though, below the floor, the output may still
    exceed the budget per the contract above).
    """
    if len(text.encode("utf-8")) <= byte_budget:
        return text, False

    preamble, sections = _split_markdown_sections(text)
    if not sections:
        # Nothing splittable (the whole text is preamble). Keep it intact
        # — fail-soft per the contract; we have no whole unit to drop.
        return text, False

    def render(kept: list[str]) -> str:
        # We only reach here when the full text is over budget AND there is
        # at least one section, so at least one section will be dropped —
        # the marker is always part of the rendered size we test against.
        pieces = [p for p in ([preamble] + kept) if p != ""]
        body = "\n".join(pieces).rstrip()
        return f"{body}\n\n{trim_marker}" if body else trim_marker

    kept: list[str] = []
    for sec in sections:
        if len(render(kept + [sec]).encode("utf-8")) <= byte_budget:
            kept.append(sec)
    return render(kept), True
