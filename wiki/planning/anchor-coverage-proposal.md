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

### Lever B — anchor-type expansion (item 19, no-API)

Add `url`, `pr`/`issue`, `dataset`, and `memory`-to-`memory` anchor types: extend
the prompt's type list, `wellformed_anchor`, and the verify functions. Captures
referents currently lost to type-narrowness. No-API forward change, offline-
testable. **But the demand is unquantified** (the malformed-type tail is tiny
because the prompt suppresses it), so size it before building — sample unanchored
research-side memories for unsupported referents.

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

## 6. Recommendation & sequencing

1. **Lever A (deterministic anchor inference) — the one to build.** No-API,
   reuses items 20/21, lifts both new writes and the back-corpus. **Build as its
   own deliberate effort** (it mutates the corpus — guarded write, quiet window,
   PG lockstep, like `recover_anchors.py`). Step 0 is no-API + read-only:
   run the inference over the back-corpus in **dry-run** to get the *net resolved*
   count (how many of the 1,041 actually resolve uniquely) — that decides whether
   to proceed and is the honest size of the lever.
2. **Lever B (type expansion)** — a secondary no-API increment; size the demand
   first.
3. **Lever C (prompt)** — only for what A can't reach, and only behind a cheap
   API spot-check (P3 discipline).
4. **Lever D (LLM retroactive)** — stays deferred; largely superseded by A.

This keeps item 6 an incremental, mostly-no-API effort rather than the heavy
API-gated pass it was first framed as — because the biggest lever turned out to
be deterministic.

---

## 7. Open calls for Shawn

1. **Lever A's dilution semantics (the main call):** accept that an inferred
   anchor means "a cited file exists" (weaker than "claim verified"), with the
   unique-resolution + required-category guards — or hold A until item 16 gives a
   value signal that makes anchor-as-value less load-bearing? Lean: **accept it**
   (guarded), since the contract is already "verify a cited specific" and the
   coverage gain is large.
2. **Build Lever A now (Step 0 dry-run first), or keep scoping?** Lean: do the
   no-API Step-0 dry-run next — it's read-only and gives the real net-reach number
   before any build commitment.
3. **Lever B (type expansion):** worth sizing, or skip until a concrete demand
   surfaces? Lean: size it opportunistically; not urgent.
4. **Prompt (Lever C):** ever worth the API spot-check, given P3? Lean: defer
   until A's net reach is known — if A lifts coverage materially, C may be
   unnecessary.
