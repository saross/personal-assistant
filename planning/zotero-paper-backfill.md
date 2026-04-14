# Plan: Backfill Zotero Items + Memory Keys for Legacy source_insight Memories

**Status:** Deferred (not yet started)
**Created:** 2026-04-12
**Estimated effort:** 1–2 hours (mostly manual/interactive)
**Trigger to implement:** When you next have a `/read` session with one of
the affected papers, OR as a one-off cleanup pass when you have time

## Context

During the Zotero write-back sync implementation (2026-04-12), we discovered
that the 11 existing `source_insight` memories with a `zotero_key` field
contain **invalid keys**: author-year slugs, arXiv IDs, full titles, and
citation strings rather than the 8-character alphanumeric keys Zotero (and
the pyzotero API) actually use.

Worse, **the underlying papers are not in the Zotero library at all**.
Searches for each came up empty. The user read these papers and captured
insights but never added the items to Zotero — the captured `zotero_key`
was a placeholder.

The sync script handles this gracefully: it validates the key format and
silently skips legacy entries (counted as `skipped_legacy`). But these 8
unique memories will never be synced to Zotero notes unless their data is
fixed at the source.

## Affected Memories

8 unique memory IDs across 11 JSONL entries (some duplicated):

| Memory ID | Current zotero_key | Real paper |
|-----------|-------------------|------------|
| `2026-02-10-6abd95370f86` | `buchanan-hamilton-2021` | Buchanan & Hamilton (2021) — Paleoindian projectile point scaling laws |
| `2026-02-10-568f13094e44` | `ballsun-stanton-torrington-2025` | Ballsun-Stanton & Torrington (2025) — AI pedagogy four-pillar framework |
| `2026-02-10-2e44dad16dbe` | `martinelli-2025` | Martinelli (2025) — Ethnographic AI pedagogy study |
| `2026-03-15-7d86aad6679d` | `2511.21569` | arXiv 2511.21569 — Self-Transparency Failures in Expert-Persona LLMs |
| `2026-03-15-9a707c42c45a` | `2602.20478` | arXiv 2602.20478 — Codified Context (memory architecture) |
| `2026-03-29-c8ef636e7881` | (full title) | Sobotkova et al. 2023 — historical maps + novice volunteers |
| `2026-04-10-cca054c6fa96` | `sobotkova_2023` | Same paper as above |
| `2026-04-10-bd33a9a40253` | `Sobotkova et al. 2023` | Same paper as above |

So actually only **6 unique papers** for 8 memories (3 of them point to the
same Sobotkova 2023 paper).

## Goal

After backfill:

- All 6 papers exist in the Zotero library
- All 8 memories have the correct 8-character `zotero_key`
- The next `sync-to-zotero.py` run pushes the insights to the corresponding
  Zotero item notes
- Future `/read` sessions with these papers see the prior insights via
  the existing source_insight retrieval mechanism

## Implementation

### Step 1: Add the 6 papers to Zotero

For each paper, the user runs:

```text
/cite-new <DOI>
```

Which creates a BibTeX entry and adds it to Zotero via the existing
research command. DOIs to look up:

- Buchanan & Hamilton (2021), Paleoindian projectile points — find DOI
- Ballsun-Stanton & Torrington (2025) — paper-in-press, may not have a DOI
  yet; could be added manually with `pyzotero` or via Zotero UI
- Martinelli (2025), AI pedagogy ethnography — find DOI
- arXiv 2511.21569 — DOI typically `https://doi.org/10.48550/arXiv.2511.21569`
- arXiv 2602.20478 — same pattern
- Sobotkova et al. (2023), historical maps — find DOI

For papers without a DOI, fall back to manual Zotero entry via the desktop
app, then read out the `key` field.

### Step 2: Resolve the 8-char key for each new item

After adding, query Zotero locally:

```python
from zotero import search_items
for paper in ["Buchanan Hamilton", "Martinelli", "Sobotkova", ...]:
    items = search_items(paper, limit=3)
    for item in items:
        print(f"  {item['key']}  ({item['date']})  {item['title'][:60]}")
```

Pick the right key for each paper. Build a mapping from old key to new
key, e.g.:

```python
RESOLUTIONS = {
    "buchanan-hamilton-2021": "MPZHXY3P",
    "ballsun-stanton-torrington-2025": "K8N3RTQS",
    # ... etc
}
```

### Step 3: Apply the backfill

Build a one-off Python script that:

1. Reads `memories/memories.jsonl`
2. For each line that is a `source_insight` memory with one of the legacy
   `zotero_key` values, replace it with the resolved 8-char key
3. Writes to `memories.jsonl.tmp`
4. Atomic rename to `memories.jsonl`
5. Triggers `sync-to-postgres.py --rebuild` to update the database

This is structurally similar to the `tag-gardening.py merge` operation —
in fact, the same atomic-rename pattern can be reused.

Pseudo-code:

```python
RESOLUTIONS = {
    "buchanan-hamilton-2021": "MPZHXY3P",
    # ... etc
}

with open(jsonl) as fh:
    lines = []
    for line in fh:
        if not line.strip():
            lines.append(line)
            continue
        mem = json.loads(line)
        if (
            mem.get("category") == "source_insight"
            and mem.get("zotero_key") in RESOLUTIONS
        ):
            mem["zotero_key"] = RESOLUTIONS[mem["zotero_key"]]
            lines.append(json.dumps(mem, ensure_ascii=False) + "\n")
        else:
            # Preserve original line — no reformatting noise
            lines.append(line)

# Atomic rename
tmp = jsonl.with_suffix(".jsonl.tmp")
tmp.write_text("".join(lines), encoding="utf-8")
os.rename(tmp, jsonl)
```

### Step 4: Sync to PostgreSQL

The 5-min sync cron only handles new appends, not in-place modifications.
Trigger a full rebuild:

```bash
venv/bin/python3 scripts/rebuild-postgres.py
```

### Step 5: Run the Zotero sync

```bash
venv/bin/python3 scripts/sync-to-zotero.py --dry-run --limit 3
# verify
venv/bin/python3 scripts/sync-to-zotero.py
```

The 8 memories should now be syncable. Each writes a note to its Zotero
item with the footer marker. Check the Zotero UI for the notes.

### Step 6: Verify

- Open Zotero
- Find each of the 6 papers
- Verify each has a child note containing the memory content + footer
- Re-run `sync-to-zotero.py` and verify it skips all 8 (idempotent)

## Verification

1. **Pre-flight**: `tag-gardening.py stats`-style check that the 8 memory
   IDs exist and have the expected legacy keys
2. **Resolution check**: every old key maps to a real Zotero item (not a
   404 from the API)
3. **Atomic rewrite**: backup the JSONL before running, diff after
4. **PostgreSQL sync**: confirm `SELECT zotero_key FROM memories WHERE id
   IN (...)` returns the new 8-char keys
5. **Live sync**: Zotero notes appear in the UI
6. **Idempotency**: re-run the sync, all 8 are skipped as duplicates

## Out of Scope

- Backfilling other source_insight memories that *don't* have a zotero_key
  field at all (854 of them). Most predate the Zotero integration; they
  reference papers conversationally without a stable identifier. Not worth
  retroactively linking.
- Updating Zotero notes that already exist for these papers (write-once
  policy from the sync plan)

## Why Defer

This is a one-off cleanup with low daily value:

- Only 8 memories, all from completed reading sessions
- The papers are already in the user's working memory
- The sync script is correctly skipping them (no errors, just idle)
- Adding 6 papers via `/cite-new` requires looking up 6 DOIs interactively
- Better to fold the backfill into a normal `/read` session: when the user
  next reads one of these papers, fix that one memory's key as part of the
  reading workflow

The mechanical backfill exists as a fallback if the "fold into next /read"
approach proves too slow.
