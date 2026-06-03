# Tier-2 autonomous memory retrieval — protocol

**Status:** canonical. This doc is the full protocol for fetching memory
content mid-conversation. It was relocated here from the session-start
hook's inline footer as part of Vector 2 (session-start payload
reduction): the recall channel now ships a small digest plus a one-line
pointer to this doc, rather than repeating the whole protocol every
session. See `wiki/planning/vector-2-design.md` §5b and §7e.

## What the session-start digest is

Under Vector 2 (Stage 1), each session opens with a compact
**session-start digest** (≤1,500 bytes) instead of the former ~16 KB
recall dump. The digest carries only:

- A mechanical "what changed" counter (new/updated/forgotten memories in
  the window).
- A short, byte-capped list of `verified=true` entries from the last
  7 days, ranked by tag overlap with the current project.
- The load-bearing anti-confabulation reminder.
- A one-line pointer to this protocol.

Everything else — the bulk of the corpus — is **not** surfaced eagerly.
It is available on demand through the two mechanisms below.

## How to fetch full memory content

```bash
# By tag
python3 ~/personal-assistant/scripts/fetch-memories.py --tag <tag-name>

# By free-text query
python3 ~/personal-assistant/scripts/fetch-memories.py --query "search terms"

# Scoped to a category
python3 ~/personal-assistant/scripts/fetch-memories.py \
    --category decision --query "topic"
```

Each invocation is logged to `logs/fetch-memories.log` (Vector 2
instrumentation, design §7c) so tier-2 utilisation can be measured over
the observation window. Lines from this autonomous path carry no
`source=` field; manual `/recall` lines carry `source=recall`.

## Protocol — when and how

1. When the conversation touches a topic that plausibly matches stored
   memories, **announce** it: *"I have memories about [topic] — shall I
   retrieve the details?"*
2. **Wait for confirmation** before running the fetch command.
3. Run the script via Bash and incorporate the results into your
   response.

## When NOT to fetch

- Trivial or passing mentions of a topic.
- Topics where full content has already been retrieved this session.
- When the user is focused on an unrelated task and the match is
  tangential.
- When the user has not confirmed after your announcement.

## Manual alternative

The user can invoke `/recall [query]` directly at any time, without
waiting on an announcement. Note this runs a *separate* path — `/recall`
reads `memories.jsonl` directly rather than calling this script — so it
is instrumented independently: each `/recall` appends a `source=recall`
line to the same `logs/fetch-memories.log` (see `commands/recall.md`).

## Why lazy depth

Vector 2's premise is that surfacing a large, unverified, authoritatively
framed memory dump every session primes primacy-effect confabulation —
the model welds stale fragments (paths, identifiers, counts) into
plausible-but-wrong specifics. Pulling depth **on demand**, only when a
real topic match is detected, keeps the eager channel small and verified
while preserving full access to the corpus. The risk this trades against
is that depth is *never* fetched (lazy premise fails); that is exactly
what the `logs/fetch-memories.log` instrumentation measures during the
amd-tower observation window — across both the autonomous path above and
manual `/recall` (tagged `source=recall`). See design §8 risk R1.
