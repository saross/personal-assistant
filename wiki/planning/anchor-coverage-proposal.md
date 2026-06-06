# Anchor coverage — scoping & design (item 6 / P9 (c))

**Created:** 2026-06-06 (Workstream B, out-of-hours). **Status:** SCOPING /
DESIGN ONLY — no code changed, no live change, no API. **Origin:** P9 named anchor
coverage "the bigger lever — does more than any confidence reform" (P9 (c)), and
the 2026-06-06 verify-checks confirmed the anchor-production rate is **flat at
~27 % of post-v2 writes across three weeks** — not self-improving. The
session-start digest surfaces *only* from the anchored/verified-true pool, so
everything downstream is gated on this number. This scopes how to raise it.

Plan reference: `wiki/planning/memory-write-path-plan.md` §5 item 6, §6a P9 (c).

---

## Step-0 dry-run result (2026-06-06) — net reach 13%, dilution confirmed; Lever A weaker than scoped

Ran Lever A's resolution over the back-corpus **read-only** (nothing written;
reused `triage_anchors.recovery_status` + `anchor_verify.verify_commit` over
`broad_repo_set()`). Of **2,550** unanchored required-category memories:

- **337 (13%) resolve UNIQUELY** — a clean anchor is inferable (290 via a
  unique file-suffix match, 47 via a valid commit).
- **76** ambiguous only (basename collision — unsafe to auto-anchor).
- **2,137** absent: a path-like token is present but resolves *nowhere*.

So the §2 "40% gross" (1,041 with a path-ish token) collapses to **13% net**. The
gap is the 2,137 absent — tokens that *look* like files but don't resolve:
**files named as future work to create** ("sketch `notes/index.md`", "create
`notes/_tags.md`"), renamed/moved paths, and cross-project relative paths.

**Quality is mixed (the dilution risk, confirmed).** Eyeballing the inferred
anchors: some are genuine ("wiki structure will split into `wiki/index.md`" →
correct), but a real fraction are **tangential or future-tense** mentions where
the file existing does *not* verify the memory's claim ("`_inbox.md` should
*move* from `notes/_inbox.md`…"). Naive token-selection also mis-picks (chose
`CLAUDE.md` over the more-relevant `scripts/schema.sql` the same memory cited).
A blanket "anchor any resolving token" would push weakly-verified memories into
the digest's high-confidence pool — exactly the §7 (1) call.

**Revised read.** Lever A's *effective* high-quality reach is well under 337 —
order ~150–200 after discounting tangential/future mentions — i.e. a ~12–16%
bump to the 1,214-strong verified-true pool, bought at the cost of some signal
dilution and a corpus mutation. **That is no longer a slam-dunk.** The dry-run
(like P3's spot-check) repriced the lever before any build. Updated
recommendation in §6.

---

## 1. What item 6 asks, and why it binds

The digest ranks `verified=true` in-window memories (`digest.py` →
`rank_verified`); verification requires an anchor that *resolves*. So the
proactive-surfacing pool is bounded by **anchor coverage**. Post-v2 (measured
2026-06-06, PostgreSQL): of **5,864** post-epoch memories, **1,613 (27 %)** carry
an anchor and **1,214 (21 %)** verify true. The digest draws from those ~1,214.
Raising coverage widens (and de-biases) that pool — P9's point that it beats any
`confidence` reform.

---

## 2. Evidence (measured at source, 2026-06-06)

**The prompt offers an escape hatch, and Haiku takes it wholesale.** Anchors are
"required" for six categories (`hooks/extraction-hook.py:193`,
`ANCHOR_REQUIRED_CATEGORIES`), but the instruction adds: "if you cannot find a
concrete anchor … *either lower the memory's confidence to 'low' or reword* to
drop the false precision" (`:194–196`). Since `bind_confidence` overrides Haiku's
rating anyway, "mark low" is the path of least resistance. Of the **2,542**
unanchored required-category memories, **2,505 are `low`** and only **35 high** —
the hatch is used almost universally.

**Anchor rate by category (post-v2)** — the requirement bites, but unevenly:

| | anchored / total | rate |
|---|---|---|
| **Anchor-required** (decision, progress, architecture, gotcha, provenance, completion) | 1,462 / 4,002 | **37 %** |
| All other categories | 197 / 2,012 | **10 %** |

Within required: completion 56 %, provenance 55 %, architecture 49 %, progress
41 %, **decision 32 %** (the biggest category, 1,640), gotcha 26 %. The "other"
categories are mostly inherently abstract — `self_reflection` 2 %,
`prompt_effectiveness` 3 %, `pattern` 6 %, `surprise` 5 %, `hypothesis` 14 % —
where a low rate is *correct* (no concrete referent to anchor to).

**Anchor types are narrow:** of all post-v2 anchors, `file` 1,676 + `commit`
1,103 dominate; `zotero` only 12; and a tail of *malformed* types Haiku reached
for but the schema doesn't support (`url`, `ref`, `dataset`-ish). The prompt
lists only `file`/`commit`/`zotero` (`:190`), so Haiku is steered away from other
referents — type-narrowness loss is real but hidden (those memories just go
unanchored rather than trying an unsupported type).

**The unanchored required-category memories are often concretely anchorable.** A
sample of recent unanchored `decision`s names specific files —
`lit-scout-zotero-import.py`, `CLAUDE.md`, `zotero_batch_add.py`,
`zotero_followup.py` — i.e. they cite the exact supported anchor type (`file`)
but were not anchored. **Quantified:** of the 2,542 unanchored required-category
memories, **1,041 (40 %)** contain a file-path-like or commit-hash-like token in
their `content`. (Gross upper bound — not every token will resolve — but it sizes
the headroom.)

---

## 3. The reframe — 27 % is a blend, not one ceiling

"Raise anchor coverage to 80 %" is the **wrong goal**. The 27 % decomposes into:

- **A genuine ceiling (~a third of the corpus): the abstract categories.**
  `self_reflection`, `pattern`, `prompt_effectiveness`, `surprise`, `hypothesis`,
  `openness`, `context`, `commitment`, `waiting_for`, and many `methodology`
  memories have *no concrete referent*. Forcing anchors here would manufacture
  confabulated ones — the opposite of the anti-confab intent. These should stay
  unanchored.
- **Real, capturable headroom: concrete-but-escape-hatched memories** — above all
  **decisions/architecture/gotchas that name a file or commit** but took the
  "mark low" hatch. ~1,041 unanchored required-category memories carry a
  resolvable-looking token.
- **Type-narrowness losses** (unquantified): referents that aren't file/commit/
  zotero (URL, PR/issue, dataset, another memory) — invisible because the prompt
  steers away from them.

So the target is narrow and specific: **capture the concrete-but-unanchored
headroom**, not chase the abstract ceiling.

---

## 4. Levers, ranked

### Lever A — deterministic anchor inference (write-time + retroactive, NO-API) — recommended

For an unanchored required-category memory, scan its `content` for file-path-like
and commit-hash-like tokens; for each that **resolves** (file exists in the
working tree / git history; commit exists), add it as a `file`/`commit` anchor.
**No LLM, no API** — it resolves tokens *already in the content*, reusing the
heavily-worked `anchor_verify.verify_file` / `verify_commit` /
`unique_suffix_match` machinery (items 20/21).

- **Reach:** ~1,041 forward candidates (40 % of the unanchored required set);
  net depends on resolution rate (the first build step quantifies it).
- **Both directions, free:** unlike the LLM retroactive pass, the *retroactive*
  deterministic sweep over the back-corpus costs **nothing** (it's resolution,
  not generation) — so it can lift the existing corpus, not just new writes,
  with the `recover_anchors.py`-style guarded write pattern.
- **The key risk — verified-signal dilution.** If a memory merely *mentions* a
  file in passing and we anchor it, `verified=true` then means "a cited file
  exists", not "the memory's core claim is checked" — weakly-verified memories
  enter the high-confidence/digest pool. Mitigations: (i) only required
  categories; (ii) only on a **unique** resolution (`unique_suffix_match`
  discipline — no fuzzy/ambiguous hits); (iii) accept the semantics — the anchor
  contract is "re-verifying any specific cited in content", and a cited file that
  exists *is* a verified specific. Document the weaker guarantee. The alternative
  (valuable decisions never surfacing) is worse. This tension is the main design
  call (§8).

### Lever B — anchor-type expansion (item 19) — ❌ SIZED 2026-06-06, NOT WORTH IT

Idea: add `url`, `pr`/`issue`, `dataset`, `memory`-to-`memory` anchor types.
**Sized read-only (2026-06-06) over the 4,402 unanchored post-v2 memories — the
demand is negligible:** URL 6 (0 %), DOI 17 (0 %), arXiv 2 (0 %), PR/issue 138
(3 %, and `#NNN` is noisy — mostly section/count numbers), Zotero-key-like 84
(1 %, and `zotero` is *already* a supported type), memory-id ref 2 (0 %). And the
few real candidates split badly on verifiability: URL/DOI/PR need **network** to
resolve (so they'd just produce `verified=false`/`pending`, not grow the
verified-true pool), while the locally-verifiable ones (Zotero — already
supported; memory-to-memory — 2 records) are vanishing. **Conclusion: there is no
hidden type-narrowness reservoir; Lever B is dropped.**

### Lever C — tighten the prompt escape hatch (P3-tempered, API-gated)

Reframe the required-category instruction so anchoring is the *first* move ("point
to the file/commit you are describing — it is almost always in the transcript"),
not an equal alternative to "mark low". This targets the biggest *theoretical*
headroom — but it is the **same kind of prompt lever P3 showed is empirically
weak (11.4 %)**, and validating it needs Haiku calls (API-gated). Lower priority:
Lever A captures much of the same file/commit headroom *deterministically*, so
the prompt should only be pursued for what A cannot reach, and validated via a
cheap spot-check (the P3 lesson).

### Lever D — LLM retroactive anchor-gen pass (API-gated, heavy) — largely superseded

The "re-run Haiku over the unanchored back-corpus" pass the plan flagged as
heavy/API-gated. For the **file/commit-naming subset, Lever A's no-API
retroactive sweep does this for free**, so D shrinks to "memories whose anchorable
referent is *not* a literal token in the content" — a much smaller, lower-value
remainder. Keep deferred; reassess only after A + B.

(*Resolution robustness — converting `verified=false` → `true` — is effectively
exhausted by items 20/21; the residual 18 % fail is dominated by genuinely-gone
files, not fixable resolver gaps. Not a coverage lever.*)

---

## 5. The strategic fork — item 6 vs item 16 (complementary, not competing)

Anchor coverage and earned utility (item 16) address **different halves**:

- **Item 6 (this doc)** widens the *anchored/verified* pool — best for the
  **concrete** memories (decisions/architecture naming files). It will never
  reach the abstract categories (§3 ceiling) — and *should not* try.
- **Item 16 (earned utility, Stage 1 shipped 2026-06-06)** adds a *value* signal
  orthogonal to anchoring — the path by which an **abstract-but-genuinely-useful**
  memory (a hard-won `pattern`, a `feedback` rule) could earn proactive surfacing
  *without* an anchor it can never have.

So they are complementary: **item 6 for the concrete headroom, item 16 for the
abstract-but-used remainder.** The implication: do **not** over-invest in anchor
coverage to chase memories item 16 will cover better. Lever A (cheap, no-API,
concrete) is worth doing; pushing anchoring into the abstract categories is not.

---

## 6. Recommendation & sequencing — REVISED after the Step-0 dry-run

The Step-0 dry-run repriced Lever A (13% net, ~150–200 high-quality, dilution
confirmed). The revised recommendation:

1. **Do NOT build Lever A as a blanket back-corpus mutation.** A modest,
   dilution-prone 13% does not justify rewriting the corpus and weakening the
   verified signal. The naive version is not worth it — the dry-run's job was to
   establish exactly that, cheaply.
2. **If anything, build only the FORWARD, high-precision slice — and only as an
   anchor *suggestion*, not an auto-write.** At write time, when a required-
   category memory cites a token that resolves *uniquely*, surface it (or anchor
   it under a tight subject-proximity guard) so *new* memories anchor better
   without a retroactive mutation. Lower stakes (no back-corpus rewrite, forward-
   only, reversible). Still optional — its quality ceiling is bounded by the same
   tangential-mention problem.
3. **Lean on item 16 (earned utility) for the surfacing goal instead.** The real
   objective is "get valuable memories surfaced". The dry-run shows anchoring
   reaches that only partially and dilutively; **earned utility surfaces what
   actually gets used regardless of anchorability** — strictly more general, and
   already instrumented (Stage 1 shipped). This is the higher-leverage path; §5's
   "complementary halves" tilts, post-dry-run, toward item 16 as the *primary*.
4. **Lever B (type expansion)**, **Lever C (prompt)**, **Lever D (LLM
   retroactive)** — all stay deferred/secondary as before; none is urgent.

**Net:** item 6's binding-constraint *diagnosis* stands (the digest is gated on a
flat ~27%), but the deterministic remedy is weaker than hoped, so the practical
move is **mature item 16 rather than chase anchor coverage**. Anchor coverage is
not abandoned — the forward high-precision slice (2) remains available — but it is
**deprioritised below item 16** on the strength of this dry-run.

---

## 7. Open calls for Shawn

1. ✅ **Step-0 dry-run — DONE 2026-06-06.** Net reach 13% (337/2,550), ~150–200
   high-quality, dilution confirmed. Repriced the lever (see the Step-0 section).
2. **The main call, post-dry-run:** given 13% net + confirmed dilution, **drop
   the blanket back-corpus mutation** (lean: yes, drop it), and either (a) build
   only the forward high-precision suggestion slice, or (b) skip anchor-inference
   entirely and **make item 16 (earned utility) the primary surfacing lever**.
   Lean: **(b)** — item 16 is more general and already instrumented; revisit the
   forward slice (a) only if a cheap precision guard emerges.
3. ✅ **Lever B (type expansion) — SIZED 2026-06-06: dropped.** Negligible demand
   (<3 % even with noisy regexes), and the few candidates need network to verify.
   No hidden reservoir; not worth building.
4. **Prompt (Lever C):** ever worth the API spot-check, given P3? Lean: defer
   until A's net reach is known — if A lifts coverage materially, C may be
   unnecessary.
