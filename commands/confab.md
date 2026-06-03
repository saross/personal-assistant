# /confab — Log a Confabulation

Record a confabulation — a moment where I welded stale fragments into a
plausible-but-wrong specific (a path, identifier, count, quote, citation,
commit, or date) — to the shared confab-flag log. Low friction.

This is the **manual (Tier B)** complement to the automatic verifier-agent
tracking (Tier A): the verifier agents catch confabulation in citations,
repos, and dataset numbers; `/confab` catches the prose path/identifier/
count welding they don't see. Both write `data/logs/confab-flags.log` and
feed the memory-health standing report (write-path plan item 18).

## Usage

```text
/confab [what was confabulated]
```

## Arguments

- `[what was confabulated]` — a short description of the wrong specific.
  Optional: if omitted, infer it from the confabulation in the recent
  conversation that the user is reacting to. If nothing is obvious, ask
  one short question rather than guess.

## Behaviour

1. **Identify** the confabulated specific — what was claimed, and (if
   known) what the correct value was.
2. **Classify** the `kind` as exactly one of:
   `path` (a filepath), `identifier` (a function / variable / config /
   flag name), `count` (a number / quantity), `quote` (quoted text),
   `citation` (a reference / DOI), `commit` (a git SHA), `date`, or
   `other`.
3. **Compose** a short factual `detail`, ideally `claimed X, actually Y`
   (≤ ~150 chars; the helper collapses whitespace and truncates at 200).
   If the correct value isn't known, just describe the wrong claim.
4. **Derive** a short context label: the current project (from the cwd /
   FOCUS.md) or `interactive-session`.
5. **Log** it via Bash (best-effort — never block on a logging failure):

```bash
python3 ~/personal-assistant/scripts/log-confab-flag.py \
  --source user-correction \
  --checked 0 --flagged 1 --confab 1 \
  --kinds <kind> \
  --deliverable "<context>" \
  --detail "<claimed X, actually Y>"
```

6. **Confirm** briefly, then return to work:

```text
Logged confabulation (kind=<kind>): "<detail>"
```

## Source: who caught it

- **Default `--source user-correction`** — the user invoked `/confab`,
  i.e. the user noticed.
- **`--source self-catch`** — when I proactively log a confabulation I
  caught myself (e.g. an anti-confabulation re-read flagged a specific I
  was about to state). Use this only for genuine catches, not routine
  hedging — over-logging near-misses pollutes the signal.

## Examples

```text
/confab you said the script was scripts/sync.py — it's scripts/sync-to-postgres.py
/confab claimed Rome count was 65,000, the real figure is 65,435
/confab cited commit a1b2c3d that doesn't exist
/confab the function is collect_project_tags, not gather_project_tags
```

## Notes

- **One confabulation per invocation.** Log the specific wrong fact, not
  a general "you were sloppy".
- **`checked=0` is deliberate.** A manual catch has no denominator (you
  only ever log the catches), so manual rows are absolute-count-only and
  must not enter the verifier rate (Σflagged / Σchecked) — see the helper
  docstring.
- **Proactive offer (not naggy):** when the user corrects a specific I
  got wrong in normal conversation, I may offer "Want me to `/confab`
  that?" — once, then drop it.
- **Local file.** `data/logs/confab-flags.log` is in the synced `data`
  submodule; the `detail` is my own confabulated specifics, not uploaded
  third-party content.
- Do NOT ask for a category or priority — that's not what this is. Just
  classify the kind and log.
