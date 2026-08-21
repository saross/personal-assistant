# Scholarly API politeness — audit and design, 2026-08-21

**Trigger.** During a Fieldmark session an OpenAlex lookup returned
nothing, was read as "the record does not exist", and produced a wrong
factual claim in a working document. The response had been **HTTP 429**.
Shawn asked for the rate limits to be discovered and politeness built
into the tooling.

**Headline: the politeness layer already exists and mostly works.** What
is missing is the last step — **every careful retry ends in
`return None`, and `None` means "not found".**

This is not new. The 2026-05-02 audit found it and filed it as **D-X4**
(`data/reports/audit-2026-05-02/cluster-D-integrations.md:233-236`).
Batch 1 fixed the logging; the semantic fix was deferred.
`scripts/lit-search.py:435` still carries `# job of a later batch
(D-X4)`. **111 days.**

---

## 1. Why this is worse than a missing lookup

The failure inverts the instrument built to prevent confabulation.

1. `scripts/lit-search.py:419-430` — 429 survives four attempts,
   `return None`. The comment is candid: *"the caller still cannot
   distinguish this from a 404 — the same contract as before."*
2. `scripts/lit-search.py:805-806` — all three sources `None`, so stdout
   gets `{"error": "No metadata found for DOI: ..."}`.
3. `agents/lit-scout-verifier.md:125-126` — an API failure marks the row
   **UNVERIFIABLE**, conflating "throttled" with "does not resolve".
4. `agents/lit-scout-verifier.md:252-257` — an all-unverifiable row is a
   **structural FAIL**, and *"the iterate loop will route the row for
   removal."*
5. `commands/lit-scout-iterate.md:5` — the loop removes rows whose DOIs
   do not resolve, up to five iterations, **with no bypass**.

**A rate-limited verification run deletes genuine citations from a
bibliography and reports them as confabulations.** That is the exact
opposite of what `/lit-scout`'s verifier exists to do.

**Three further false-absence sites**, each with a confidently worded
log: `lit-search.py:1085` and `:1109` (`"Could not resolve DOI…"`,
`"returned no results"`, then `return []`), and `:511-515`, where a 429
mid-pagination **breaks the loop and returns a partial list
indistinguishable from a complete one** — so forward citation chains
silently truncate.

### A status check alone will not be enough

`lit-search.py:877-886` records a real incident on 2026-06-12 where
Semantic Scholar returned **HTTP 200 with `references: null`** under
load. The fix coerced null to `[]`, so it now reports *"found 0
references"*. The code comment says this happens on *"rate-limited (HTTP
429) or partial S2 response"*.

**A 200 can be a rate-limit signal.** The layer needs a payload
plausibility check, not only a status check.

## 2. Live state at time of audit

```text
GET /works/doi:10.1038/nature12373  → 200,  x-ratelimit-cost-usd: 0
GET /works?filter=doi:...           → 429,  retry-after: 58281
GET /works?search=archaeology       → 429,  retry-after: 58281
x-ratelimit-remaining-usd: 0        x-ratelimit-limit-usd: 0.1
```

The OpenAlex daily budget was **exhausted**, resetting in about 16
hours. Singleton DOI lookups still worked (they cost nothing); search,
citation pagination and reference batch-resolve were dead.

**And the retry logic makes it expensive.** `_parse_retry_after` reads
58281 seconds, then `min(MAX_BACKOFF=60, …)` clamps it to 60
(`lit-search.py:355-357`). Each doomed call sleeps **three times sixty
seconds** before returning a wrong "0 results".

**A 429 is not one thing.** A per-second throttle is retryable in
seconds; a daily budget exhaustion is retryable in sixteen hours, and
retrying it is both futile and rude.

## 3. Rate limits, verified 2026-08-21

| API | Limits | What identification buys |
| --- | --- | --- |
| **CrossRef** | 5/s anonymous (`x-api-pool: public-single`) | **UA with `mailto:` → 10/s, `polite-single`.** The `?mailto=` param does the same; either suffices |
| **OpenAlex** | **Credit model.** Anonymous **$0.10/day**. Singleton GET **$0**, list-filter $0.0001, search $0.001. Resets midnight UTC | **Free registered key = $1/day — a 10× uplift at no cost.** `mailto` now buys **nothing**; the polite pool is gone |
| **DataCite** | No rate headers, no published figure | UA good practice; no measurable tier |
| **Semantic Scholar** | 1000 RPS **shared among all unauthenticated users**, plus peak throttling | A key gives a *dedicated* **1 RPS** — for bursty single-DOI work the shared pool may be better |
| **Zotero v3** | No req/s figure; **max 4 concurrent** | Key only for private libraries |
| **arXiv** | **1 request / 3 seconds**, single connection, counted across all machines | Nothing — arXiv asks for no UA or contact |
| **Unpaywall** | 100,000/day | `email=` is **mandatory**; 422 without |

**Two distinctive headers worth building around.** Zotero sends
`Backoff: <seconds>` on **any** response including 2xx — a proactive
"slow down" that must be read off healthy responses. pyzotero already
honours it. OpenAlex exposes `X-RateLimit-Remaining-USD`, `-Cost-USD`,
`-Credits-Required` and `-Reset` on every response; **nothing in the
codebase reads any of them**, which makes "warn before the budget hits
zero" trivial to add.

**Where docs contradict observation, trust the headers.** Secondary
sources say OpenAlex singleton = 1 credit, list = 10. Live headers say
singleton = 0, list = 1, search = 10.

## 4. The design

One module, `scripts/_polite_http.py`, owning identification, pacing,
retry, budget telemetry, and — the part that matters — **the return
type**.

```python
class Outcome(enum.Enum):
    FOUND   = "found"     # 2xx, payload present and plausible
    ABSENT  = "absent"    # authoritative negative: 404, or a well-formed
                          # empty result set
    UNKNOWN = "unknown"   # could not determine: 429, 5xx, timeout,
                          # budget exhausted, 200-with-null-payload
```

`Result` carries `outcome`, `data`, `status`, `reason`, `retry_at`, and
`partial` for truncated pagination.

**`Result.__bool__` should raise `TypeError`.** Every defect in this
audit is a truthiness test — `if not crossref_msg`, `if not results`.
Making the object refuse `if result:` converts the whole bug class into
a loud failure at every call site, rather than something each caller
must remember to check. That single decision does more than the rest of
the module.

Behaviour: identify always; branch on status **before** parsing; honour
`Retry-After` and Zotero's `Backoff` (including on 2xx, as a
forward-looking pause rather than a retry); **give up rather than retry
long waits** — above roughly 120 seconds return
`UNKNOWN(reason="budget_exhausted", retry_at=…)` immediately instead of
clamping; parse budget telemetry and warn below 20%; run a `plausible`
hook so a 200 with a null payload is `UNKNOWN`, not `ABSENT`; and never
return a truncated page set without `partial=True`.

**The agent side already has the vocabulary.**
`agents/prior-art-scout-verifier.md:269` distinguishes "unverifiable
because rate-limited" correctly. `lit-scout-verifier.md:252-257` needs
its policy inverted: an UNDETERMINED row must **halt the iterate loop
and surface**, never route for removal.

## 5. Priority

**Tier 1 — prevents wrong answers.**

1. [x] **Invert the verifier's unverifiable-to-FAIL collapse**
   (`lit-scout-verifier.md:252-257`, `lit-scout-iterate.md:5`).
   Prose-only, no code, no tests. **Largest error, cheapest fix, do it
   first.** — **Done 2026-08-21.** See "Tier 1 item 1 as built" below.
2. Three-state return in `_safe_get` and the three `fetch_*` functions.
3. Fix the positive-absence messages at `lit-search.py:1085`, `:1109`,
   and `add-doi-to-zotero.py:176`.
4. Mark truncated pagination (`lit-search.py:511-515`).
5. Payload plausibility for the S2 null case (`:882`, `:961`).
6. **`sync-to-zotero.py:284-289`** — the only defect that *writes*: an
   empty set from a throttled call feeds the duplicate check and creates
   duplicate notes in Zotero.

**Tier 2 — prevents throttling, not wrong answers.**

7. **Register a free OpenAlex API key** — 10× the budget, no cost. Best
   value per effort, but note it only makes exhaustion rarer; without
   Tier 1, exhaustion still yields wrong answers.
   **2026-08-21: needs Shawn — see §8.**
8. Stop retrying long `Retry-After` values — reclaims about three
   minutes per throttled call.
9. Budget-remaining warnings from the OpenAlex headers.
10. Add UA and `mailto` to the raw curls in `commands/cite-new.md:34-35`
    and `agents/lit-scout.md:122`; switch arXiv to HTTPS and pace it at
    1-per-3-seconds rather than the 1.1 s used for Semantic Scholar.

## 6. Decisions needed

- **OpenAlex free API key** — registration, not an API spend, so the
  API-call gate does not strictly apply; but it registers Shawn's
  identity, so it was not done unilaterally.
- **Semantic Scholar key** — `lit-search.py:144-148` already reads
  `S2_API_KEY`, and it is not in `.env`. The trade-off is genuinely
  ambiguous: a contended share of 1000 RPS versus a dedicated 1 RPS.
- **Should `UNKNOWN` be fatal in a lit-scout run**, or carried through
  the report flagged and unverified?

## 7. Migration cost, and two incidental findings

`tests/test_lit_search.py` has 22 `@patch.object(lit_search,
"_safe_get")` sites, and `test_429_exhausts_retries_returns_none`
(L519-527) **asserts `result is None`** — the defective contract is
pinned as intended behaviour. Changing the return type means touching
that file.

**Incidental, and relevant to the anti-confabulation rule**:
`scripts/anchor_verify.py:367` does not verify that URLs resolve — the
whole test is `ref.startswith(("http://","https://"))` — and
`verify_zotero` is a stub returning `"pending"`. Anchors are the
re-verification mechanism the rule depends on.

**Also**: `httpx` is imported by three scripts but is not in
`requirements.txt`; it arrives transitively via pyzotero.

---

## 8. Tier 1 item 1 as built — 2026-08-21

Three specification files changed; no code, no tests, as promised.

**The deletion path was narrower than the audit described.**
`agents/lit-scout.md` already told the proposer to *preserve*
unverifiable rows. The damage was done one step earlier: the verifier
was instructed to **manufacture** a `doi_resolves` FAIL out of an
all-unverifiable row, and the proposer then correctly removed a row it
had been told was fabricated. Stopping the verifier synthesising that
FAIL is the whole fix.

**The status token `unverifiable` was kept, and its meaning fixed.**
The audit's three-state design implies renaming it to `undetermined`,
but `scripts/lit-scout-zotero-import.py:1190` and `:1247` membership-test
the literal tuple `("fail", "partial", "unverifiable")` to decide which
imported items get the `lit-scout-unverified:<field>` review tag in
Zotero. A rename would silently strip that tag from exactly the rows
that most need it. Redefining the token instead keeps the change
prose-only and leaves the Python contract intact.

The governing sentence now in the spec: **`unverifiable` describes the
check, not the candidate.** It means "I did not find out", never "this
paper does not exist".

What changed:

- `agents/lit-scout-verifier.md` — new "When a check does not complete"
  section separating an authoritative negative (a status code actually
  seen, normally 404 → `fail`) from an incomplete check (429, 5xx,
  timeout, exhausted budget, implausibly empty 200 → `unverifiable`).
  The spec had been internally inconsistent here: the prose routed "DOI
  not resolvable" to UNVERIFIABLE whilst the worked JSONL example routed
  an HTTP 404 to `fail`. Because `lit-search.py metadata` renders both
  as "No metadata found", the verifier is now told to **re-check the DOI
  directly with `curl` and read the status code** before ever writing a
  `fail`. The aggregate-verdict rules gained an UNVERIFIABLE verdict;
  the confabulation-rate denominator excludes unverifiable rows; an
  `unverifiable` exemplar was added to the JSONL block; and the
  Adversarial posture section gained a counterweight, since an
  adversarial prompt is precisely what pushes a model to read silence
  from an API as a confession.
- `commands/lit-scout-iterate.md` — removal now requires an
  authoritative negative. New terminal statuses `UNVERIFIABLE` (nothing
  failed, but some rows were never checked, so the run is not PASS) and
  `THROTTLED` (a third or more of claims unchecked: stop rather than
  spend iterations on retry backoff). `UNVER_CT` now excludes the
  `_legacy` sentinel, which shares the status token but means something
  else. Both new outcome blocks state that rows were preserved.
- `agents/lit-scout.md` — defence in depth. Even if a removal
  instruction reaches the proposer, it **declines the removal** when the
  `source_method` shows a rate limit, a 5xx, a timeout, or no status at
  all, and says so in Proposer self-check.

**Open decision from §6 resolved by default, reversibly.** "Should
UNKNOWN be fatal in a lit-scout run?" — implemented as: not fatal, but
not PASS either. The run terminates, keeps every row, and reports which
rows are unconfirmed and why. Tighten to fatal if that proves too soft.

**`published/agents/` is now behind** the working copies by this change.
That directory is a deliberate frozen-copy layer with a sanitisation
gate (`published/README.md`, convention set 2026-06-15), so it was left
alone rather than synced.

## 9. OpenAlex key — verified 2026-08-21, and a prerequisite the audit missed

**`lit-search.py` cannot send an OpenAlex key.** It reads `S2_API_KEY`
(`:144-148`, sent as the `x-api-key` header at `:186-187`) but there is
no OpenAlex equivalent anywhere in the file — `OPENALEX_BASE` at `:46`
is used raw at nine call sites. **Registering a key changes nothing
until the client sends it**, so Tier 2 item 7 needs the wiring as well
as the registration.

Re-verified against OpenAlex's own help centre, 2026-08-21:

| | Anonymous | Free registered key |
|---|---|---|
| Daily budget | $0.10 (observed in `x-ratelimit-limit-usd`) | **$1 of usage per day**, no payment details required |
| Reset | midnight UTC | midnight UTC |

A free key is "10× the keyless budget", which matches the observed
$0.10 exactly. Sign-up is at **<https://openalex.org/settings/api>**.
The key travels either as an `api_key=` query parameter or as
`Authorization: Bearer <key>`; the help centre says both work
identically.

**Note the docs are inconsistent about this.** The GitHub mirror
(`ourresearch/openalex-docs`, `rate-limits-and-authentication.md`) still
describes the pre-2026 model — "You don't need an API key", 100,000
credits a day free, keys as a Premium perk. The live help centre and the
live response headers both describe usage-based pricing in dollars.
**Trust the headers and help.openalex.org; the GitHub mirror is stale.**

Paid tiers, for context, run $5,000/year (Member, $20/day) to
$20,000+/year (Partner). Nothing here needs them.

**Registration still needs Shawn.** It creates an account in his name
and requires a password and an email confirmation, so it was not done
unilaterally. Thirty seconds: sign in at the URL above, copy the key,
and add `OPENALEX_API_KEY=<key>` to `~/personal-assistant/.env`.

**A house exemplar already exists.**
`~/Code/llm-reproducibility/scripts/fetch-corpus.py:88` raises rather
than returning empty, and identifies itself properly. If the shared
module wants a model, it is already in the tree.
