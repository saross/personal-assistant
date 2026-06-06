# Extraction truncation data-loss — fix proposal (P10)

**Created:** 2026-06-06 (Workstream B, out-of-hours). **Status:** PROPOSAL —
no live change, no API call made. The fix touches the **live extraction hook**
(`hooks/extraction-hook.py`, fires on every session across machines), so per the
item-13 / P3 discipline it is *diagnosed + proposed*, not edited blind. **Origin:**
the 2026-06-06 verify-checks surfaced 84 post-v2 "Failed to parse extraction
JSON" errors; run to ground, they are not malformed output — they are
`max_tokens` truncation that silently drops the densest windows' memories.

Plan reference: `wiki/planning/memory-write-path-plan.md` §6a P10.

---

## 1. The bug (evidence re-derived at source)

`extract_memories()` calls Haiku with a fixed **`max_tokens=2000`**
(`hooks/extraction-hook.py:585`). A window is up to `MAX_EXCHANGES=30` exchanges
(`:55`), each up to `MAX_MESSAGE_CHARS=3000` (`:56`) — so a content-dense window
asks Haiku to emit a large JSON array of memories. When that array would exceed
2,000 output tokens, the response is **cut off mid-string**.

The downstream path (`:640–656`):

```python
try:
    extracted = json.loads(response_text)      # truncated → raises
    ...
except json.JSONDecodeError as e:
    logger.error("Failed to parse extraction JSON: %s", e)
    logger.debug("Raw response: %s", response_text[:500])
    return []                                   # ← drops the whole window
```

And `return []` **advances the cursor** — the C2 audit note is explicit
(`:541–548`): "previously any exception was logged and returned `[]`, causing
`main()` to advance the cursor past a window… The affected memories were then
silently lost forever." C2 (2026-05-19) fixed *transient API errors* (5xx/429
→ `return None`, cursor held) but **deliberately kept malformed JSON as
permanent** ("bounded behaviour for hopeless inputs (4xx, malformed JSON…)").

**The evidence that this is truncation, not "hopeless input":** of the 85 parse
failures in `data/logs/extraction.log`, **81 are truncation** — the JSON breaks
at **char 5,912–7,846** (2,000 output tokens ≈ 6,000–8,000 characters; the
cutoff lands exactly at the token cap), and the bracketing log lines show they
come from **dense** windows. The output is not malformed; it is *unfinished*.
The remaining **4** are genuine small-window malformation (char 54–1,310, from
2–5-message windows) — those are the real "hopeless input" C2 was right about,
and the fix below leaves them on the existing `return []` path. (Earlier notes
said "every one is an unterminated string"; the accurate figure is 81/85.)

**Scale:** the 81 truncated windows span **35 distinct sessions** and ~1,768
messages of content, over three weeks — spiky (31 on the dense 2026-06-05). Each
overflowed *because* it was dense (emitting ~15–25 objects before the cutoff at
~7k chars), so the lost count is well above the per-window median of ~3 —
order **~1,200–2,000 memories**, not "a few hundred". The cruel inverse of P3
(which worried about *over*-extraction): here the **richest** windows extract
**zero**.

---

## 2. The reframe

C2 lumped three very different failures under "permanent → advance the cursor":
genuine 4xx (auth/bad-request — truly hopeless), programming bugs (hopeless),
and **truncation (recoverable — it's a sizing problem, not a content problem)**.
Truncation needs its own branch: detect it explicitly, and either give Haiku
room (fix a) or recover what it did emit (fix b) — never silently drop the
window.

---

## 3. Fix (a) — raise `max_tokens`

`max_tokens=2000` → **`8000`** (a named constant, e.g. `EXTRACTION_MAX_TOKENS`).
Haiku 4.5 supports far more than 8,000 output tokens, so this is headroom, not a
ceiling change that risks anything. 8,000 tokens ≈ 24,000–32,000 chars ≈ ~40–60
memory objects at the observed object size — comfortably above the per-window
need (the densest observed windows truncated at ~3–8k chars of *output*, i.e.
well under 8,000 tokens).

- **Effect:** eliminates ~all current truncations at a stroke (every observed
  failure cut off under 8k chars).
- **Cost:** you are billed for output tokens *generated*, so this only costs
  more on windows that previously truncated — and on those you were getting
  **zero** usable memories, so the marginal spend buys back lost data. No change
  to the common (small) window.
- **Risk:** essentially none. A higher cap cannot make a fitting response worse.

This is the primary fix. On its own it likely drives the truncation rate to near
zero. But "near zero" is not zero — a pathological window could still exceed even
8k tokens — so it is paired with (b) so that residual truncation is *non-lossy*.

---

## 4. Fix (b) — detect truncation, then salvage (NOT naive retry)

**First, the honest correction to my own earlier framing.** When P10 was logged
I wrote (b) as "check `stop_reason == 'max_tokens'` and treat truncation as
transient (preserve the window)". On reflection that is **wrong**, and for the
exact reason C2 exists: "preserve the window" means *don't advance the cursor*,
so the **same** oversized window is re-read on the next firing — and Haiku
truncates it **identically** (it is a sizing problem; retrying unchanged changes
nothing). That is an infinite **wedge** that blocks all subsequent extraction —
precisely the failure C2 guards against. Naive "retry truncation as transient"
must be rejected.

**The correct (b): detect truncation explicitly, then salvage the complete
prefix.**

1. **Detect.** The SDK exposes `response.stop_reason`; `"max_tokens"` means the
   model was cut off. Branch on it *before* `json.loads`, so truncation is
   handled distinctly from genuinely-malformed output.
2. **Salvage.** A truncated array is `[{obj1}, {obj2}, …, {objN}, {partial…` —
   i.e. **N complete memory objects** followed by one incomplete one. Recover
   the N complete objects (e.g. `json.JSONDecoder().raw_decode` in a loop over
   the array body, stopping at the first failure; or trim to the last balanced
   `}` before the cutoff). Return those N — they are real, fully-formed memories.
   Only the incomplete tail object is dropped, instead of the **entire window**.
3. **Advance the cursor** after salvaging (we extracted what was recoverable;
   re-reading the same window would only truncate again). **No wedge.**

This converts "truncate → lose everything" into "truncate → keep the N that
fit." With (a) making truncation rare and (b) making it non-lossy when it does
happen, the data-loss path is closed.

**Optional deeper recovery (future, not required for the fix):** to also recover
the *tail* that (b) drops, a **bounded** reduce-window retry — on truncation,
re-extract just the unprocessed tail with a smaller `MAX_EXCHANGES`. It is
bounded (the window monotonically shrinks each retry, so it cannot wedge), but it
adds API calls and complexity. (a)+(b) already close the loss; this is a
refinement to consider only if salvage proves to drop meaningful tails.

---

## 5. Why (a) + (b) together

- **(a) alone:** truncation becomes rare, but a pathological window still loses
  *everything*.
- **(b) alone:** every truncation is salvaged, but truncation stays common (the
  cap is still tight), so we lean on salvage constantly and still drop tails.
- **(a)+(b):** truncation is rare *and*, when it happens, non-lossy. Belt and
  braces — the cheap headroom fix plus the safety net. This is the recommended
  pair.

---

## 6. Risks, edge cases, cost

- **Wedge (the main risk):** avoided by design — (b) salvages and then *advances*
  the cursor; it never holds the window for an unchanged retry (§4).
- **Salvage correctness:** the prefix-recovery must only return objects that
  fully parse, and must not mis-join a partial object. Tested offline with
  synthetic truncated arrays (no API needed) — see §7.
- **Genuinely-malformed (non-truncation) JSON:** still hits the existing
  `JSONDecodeError → return []` branch (kept for the real "hopeless input"
  case). (b) only fires when `stop_reason == "max_tokens"`, so it does not
  change behaviour for true malformation.
- **Cost:** marginal and self-funding (§3). The only added output tokens are on
  windows that previously yielded nothing.
- **Cross-machine:** the hook runs on amd-tower, zbook, rpi-server; the change is
  a pure code edit shipped via the data-submodule/repo sync, no per-machine
  config. Behaviour-improving on all three.

---

## 7. Validation

- **Offline (no-API, ships with the change):** unit-test the salvage function
  against synthetic truncated arrays — N complete objects + a cut-off tail in
  several shapes (mid-string, mid-key, mid-number, trailing comma); assert it
  returns exactly the N complete objects and never a malformed one. Unit-test the
  `stop_reason == "max_tokens"` branch routing. This fully covers (b)'s logic.
- **API-gated (optional confidence, present cost first):** confirm (a) actually
  drops the truncation rate on real dense windows. Replay extraction over a
  sample of recent content-dense sessions at `max_tokens=8000` and check
  `stop_reason` / parse success. Rough envelope to approve before any run:
  model **Haiku 4.5** (`claude-haiku-4-5-20251001`), real-time, ~50–100 windows,
  ~4k input + up to 8k output tokens each ≈ **~$4–5** (same ballpark as the P3
  spot-check). This is *confidence*, not a blocker — (a) is self-evidently
  correct and (b) is offline-tested; the spot-check just quantifies the
  truncation-rate drop. **No run without explicit model/count/cost approval.**

---

## 8. Implementation sketch (no-API code change)

In `hooks/extraction-hook.py:extract_memories()`:

1. Add `EXTRACTION_MAX_TOKENS = 8000` near the other constants (`:54–57`);
   use it at `:585`.
2. After the API call, before `json.loads`, branch on truncation:

   ```python
   response_text = first_block.text.strip()
   ...  # (existing code-fence stripping)
   if response.stop_reason == "max_tokens":
       logger.warning(
           "Haiku response truncated at max_tokens (session %s); "
           "salvaging complete objects", session_id)
       return _salvage_truncated_array(response_text)   # advance cursor
   try:
       extracted = json.loads(response_text)
       ...
   except json.JSONDecodeError as e:   # now only TRUE malformation
       logger.error("Failed to parse extraction JSON: %s", e)
       return []
   ```

3. Add a pure helper `_salvage_truncated_array(text) -> list[dict]` that strips a
   leading `[` and `raw_decode`s objects until the first failure, returning the
   complete ones (testable without the API).

No change to the cursor-advance contract beyond routing truncation through
salvage. The C2 transient-error path (`return None`) is untouched.

---

## 9. Recovering the already-lost windows (back-fill) — feasible, qualified-worth-it

The loss is **not permanent**: the full session transcripts are archived (Phase 0,
2026-05-22 — `~/mnt/rpi-shares/cc-archives-consolidated/` + local mirrors), and
the truncated windows are **precisely identifiable**. Each parse-failure line in
`extraction.log` is bracketed by `Processing N new messages from session <id>`
and `No memories extracted from N messages (session <id>)`, so a read-only log
parse yields, for all **81** truncations, the `(session_id, message_count,
timestamp)` — **35 distinct sessions**. So a targeted back-fill is buildable.

**But "feasible" ≠ "worth doing now". The honest cost/benefit:**

- **The information is preserved**, just not in the *memory index*. Those windows'
  content is in the archived transcripts, searchable on demand (tier-3 / `/recall`
  over the archive). Back-filling restores **proactive surfacing** (digest /
  autonomous recall) for those windows — real value, but bounded.
- **The recovered set is mixed signal.** Dense windows are exactly where P3's
  ~4–7× over-extraction bites hardest, so re-extracting them re-imports both the
  genuine signal *and* the over-extraction noise the archival/retention work is
  managing. Recovering ~1,200–2,000 memories adds materially to corpus volume.
- **Dedup is the technical crux.** A whole-session reprocess (simplest — reuse the
  existing `reprocess-*` toolkit) re-produces the *non-truncated* windows'
  memories too, so it needs dedup against the existing corpus (item 15 — unbuilt,
  embedding-driven, API-gated). Targeted exact-window re-extraction avoids dedup
  but needs cursor-position reconstruction (fiddly).
- **API-gated.** Re-extraction is Haiku calls: ~$4 (targeted 81 windows) to ~$15–20
  (full reprocess of 35 sessions). Present model/count/cost before any run.

**Recommended sequence (so the back-fill is clean, not noise-amplifying):**

1. **Fix P10 first** (§3–§8) — re-extracting *before* the fix just truncates
   again. Non-negotiable ordering.
2. **Land the P3 prompt/selectivity fix too**, ideally — then the re-extraction
   uses the *better* prompt and recovers fewer, higher-value memories instead of
   re-importing the dense-window noise.
3. **Then** scope the back-fill as its own small API-gated project (log-parse →
   identify windows → reprocess → dedup → insert net-new). A read-only first step
   (the log parse + exact lost-window/-session list + a per-session memory-gap
   estimate) is no-API and could be done anytime to firm up the decision.

**Verdict: feasible and a qualified yes — but a deliberate, sequenced
second-order move, not a quick patch.** Highest-value action is the forward fix;
the back-fill is "nice to recover" given the transcripts are safe, and is best
done after P10 *and* P3 so it restores signal without re-amplifying noise.

## 10. Open calls for Shawn

1. **`max_tokens` target:** 8,000 (proposed — generous headroom) vs a different
   value. Lean: 8,000.
2. **Salvage vs salvage+tail-retry:** ship salvage-prefix only (recommended —
   closes the loss simply), or also add the bounded reduce-window tail-retry
   (recovers the dropped tail, more complexity). Lean: salvage-only first; add
   tail-retry only if salvage is shown to drop meaningful tails.
3. **API spot-check:** pay ~$4–5 to quantify the truncation-rate drop, or ship
   (a)+(b) on the strength of the diagnosis + offline tests and observe forward
   via the verify-check query. Lean: ship-and-observe (the diagnosis is
   conclusive and (b) is offline-tested), keep the spot-check in reserve.
4. **Implement now or hold:** this is a no-API code change to the live hook; on
   your go I implement (a)+(b) + offline tests in the main thread (the live-hook
   edit gets the careful treatment, full suite + a hook-import smoke).
