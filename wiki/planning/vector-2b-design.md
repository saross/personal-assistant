# Vector 2b — Scratchpad load-path byte budget (DESIGN)

**Status:** Design — drafted 2026-05-30; implementation pending scope-fork
decision (see §7).
**Created:** 2026-05-30
**Author:** Claude (Opus 4.8) + Shawn
**Related:**

- `wiki/planning/vector-2-design.md` — the parent pass. §1a puts the
  scratchpad explicitly out of scope for Vector 2; §7f says Vector 2b
  should **share** the Vector 2 byte-budget primitive, not re-invent it.
- `hooks/session-start-retrieval.py` — `load_scratchpad()` (≈907),
  `load_project_scratchpad()` (≈933), `SCRATCHPAD_WARN_LINES` (88), the
  shared `scratchpad_sections` assembly (≈1086) injected in **both**
  hook modes, and `digest_mode_enabled()` (≈996) — the PASS 2 flag
  pattern this design mirrors.
- `scripts/digest.py` — `build_digest()` byte-cap discipline (the
  primitive to share); `DEFAULT_BYTE_BUDGET = 1500` (64).
- `data/scratchpad.md` — the global scratchpad (the payload to bound).

## 1. Motivation

Vector 2 PASS 2 (shipped + enabled on amd-tower 2026-05-30) digested the
recall dump from ~16 KB to ~1.5 KB. The honest aggregate from that work:
the **total** session-start payload only fell ~33 % (48 → 32 KB) because
the recall dump was not the only large term. After the cut, the
**scratchpad is the dominant remaining payload** — ~15.5 KB global (plus
a cwd-matched per-project file) versus the digest's 1.5 KB.

Vector 2b bounds the scratchpad's session-start footprint. It is the
"mechanism" half; the 2026-05-30 distillation (29,268 → 15,484 B, 47 %
cut, zero principle loss) was the "content" half. The clean 15.5 KB
baseline now exists to size a budget against.

## 2. Empirical baseline (2026-05-30, re-measured at source)

| Term | Bytes | Notes |
|---|---:|---|
| Global scratchpad (`data/scratchpad.md`) | 15,484 | 69 lines; 5 principle sections |
| Per-project (`scratchpads/inscriptions.md`) | 973 | cwd-gated |
| Per-project (`scratchpads/map-reader-llm.md`) | 5,134 | cwd-gated |
| Per-project (`scratchpads/voice-assistant.md`) | 1,946 | cwd-gated |
| Recall dump (now digested, amd-tower) | ~1,488 | for comparison |

Global scratchpad section structure (the unit boundaries any capper must
respect):

```text
# Scratchpad            (preamble, ~lines 1–13)
## Constraints          (line 14)
## Preferences          (line 30)
## What Works           (line 47)
## What Doesn't         (line 54)
## Patterns             (line 60)
```

Re-measure if the gap to current is >2 weeks or the scratchpad has been
edited; these are point-in-time counts.

## 3. The crux — a scratchpad is not a recall dump

Vector 2's selector **ranks-and-drops** noisy, auto-extracted memory
records using `verified`, decay, tags, and dates. None of those levers
exist on the scratchpad:

- **No `verified` field, no decay, no per-entry score.** Every line is a
  hand-curated principle.
- **Deliberately global.** The five sections are cross-project protocol
  guardrails. Relevance-filtering the *global* scratchpad by current-cwd
  tags would defeat its purpose — it is supposed to apply everywhere.
- **Already distilled to zero-loss.** Shawn's 2026-05-30 pass removed
  28 duplicate Pattern entries and kept everything load-bearing. There
  is no slack left for a mechanism to silently reclaim.
- **Per-project files are already relevance-gated** — by cwd match. That
  *is* the relevance filter for project-specific principles; it is why
  `map-reader-llm.md` (5.1 KB) never loads in an inscriptions session.

The consequence: the right primary lever for *content* reduction is
human distillation (`/retro` step 5b), not a load-time filter. Vector
2b's mechanism job is therefore narrower and safer than Vector 2's:

1. **A byte-warn that actually fires.** `SCRATCHPAD_WARN_LINES = 150` is
   line-based and never fired — the bloat that reached 29 KB lived in
   ~99 long lines. The warn must be **byte-based** so it nudges
   distillation *before* the payload regrows.
2. **A regrowth guard-rail.** A byte budget that, if the scratchpad ever
   regrows past it, trims **whole sections from the tail** under a hard
   cap — never splitting a section, never cutting mid-principle. This is
   insurance against silent regrowth, not an active filter on the
   curated 15.5 KB.

This reframing is the main design decision. Everything below follows
from it.

## 4. Design tenets (inherited from Vector 2, adapted)

- **Eager bytes are a budget, not a default.** (Vector 2 tenet) Same
  hard-ceiling discipline; the scratchpad channel costs context every
  session.
- **Fail soft, never silent.** If the capper trims, it must leave a
  visible marker (`[scratchpad trimmed to byte budget — /retro to
  distil]`) so a dropped section is never invisible.
- **Distillation over truncation.** The human, principle-preserving
  lever (`/retro` distillation) is primary; the byte cap is a mechanical
  backstop that should ideally never bite. Record the principle, not the
  mistake.
- **Whole units only.** The capper keeps or drops whole `##` sections in
  document order. It never emits a half-section.

## 5. Proposed design

### 5a. Shared primitive (design §7f)

No standalone byte-cap helper exists in `digest.py` today — the cap is
baked into `build_digest()`'s `fits()` closure + greedy walk. Vector 2b
**adds a sibling pure function in `digest.py`** so the two share the
module, the UTF-8 byte-counting convention (`len(text.encode("utf-8"))
<= budget`), and the `DEFAULT_*_BYTE_BUDGET` constant pattern:

```python
def cap_markdown_to_budget(text: str, byte_budget: int, *,
                           trim_marker: str = ...) -> tuple[str, bool]:
    """Keep whole `##` sections in document order while the rendered
    whole stays <= byte_budget. The `# ` preamble + first section are
    always kept (the scaffolding floor, mirroring build_digest). Returns
    (capped_text, was_trimmed). Never splits a section; appends
    trim_marker when it drops anything."""
```

This is the same *discipline* as `build_digest` (greedy-keep-units under
a hard rendered-byte cap), applied to markdown sections instead of
memory records. It is "share the primitive, not re-invent" per §7f.

### 5b. Byte-based warn

Replace `SCRATCHPAD_WARN_LINES = 150` (never fires) with
`SCRATCHPAD_WARN_BYTES`. Both `load_scratchpad()` and
`load_project_scratchpad()` warn to stderr when over threshold,
recommending `/retro` distillation. The two existing line-based warn
tests are rewritten for bytes.

### 5c. Flag-gating — its own flag, mirroring PASS 2

The scratchpad is injected in **both** hook modes today (digest-mode and
legacy-mode share `scratchpad_sections`). The Vector 2 §8 observation
window is **live on amd-tower with a review booked 2026-06-13**, and one
of its four measurements is the verifier confabulation-flag rate. Any
unconditional change to scratchpad injection would confound that
measurement.

Therefore Vector 2b gets its **own machine-local flag**, mirroring
`digest_mode_enabled()` exactly:

- env `PA_SCRATCHPAD_BUDGET` (truthy/falsy override) →
- sentinel `~/.pa-scratchpad-budget` →
- else **OFF**.

When OFF (the default everywhere, including amd-tower until explicitly
enabled), the output is **byte-identical to current behaviour** in both
modes — the §8 window is untouched. Vector 2b then earns its own
short observation window before any wider rollout, exactly as PASS 2
did. The flag does **not** live in the synced `data/` submodule, so
enabling on amd-tower does not leak to zbook / rpi-server.

### 5d. Global and per-project budgets are separate

The per-project scratchpads are already small (≤5.1 KB) and cwd-gated.
Coupling them to the global budget (a shared total) would let a large
project scratchpad steal bytes from the global guardrails — the wrong
trade. Keep two **independent** budgets:

- `SCRATCHPAD_BUDGET_BYTES` — global (the meaningful cap).
- `PROJECT_SCRATCHPAD_BUDGET_BYTES` — per-project (generous; these are
  already disciplined by cwd-gating).

Both pass through the same `cap_markdown_to_budget` primitive.

## 6. What this is NOT

- **Not distill-on-load.** Running an LLM to distil the scratchpad every
  session would be an un-gated API call per session start (review-gate
  violation, latency, cost). Rejected.
- **Not byte-truncation.** A raw `text[:N]` cut splits mid-principle and
  silently drops the tail sections (`## What Doesn't`, `## Patterns`) —
  exactly the load-bearing "here's the failure mode" content. Rejected
  in favour of whole-section keep.
- **Not relevance-filtering the global scratchpad.** It is deliberately
  global; per-project relevance is already handled by cwd-gating.

## 7. Scope fork (decision needed before implementation)

The mechanism (§5) is fixed. The open decision is the **budget value**,
which determines whether anything is dropped *today*:

- **Fork A — guard-rail (recommended).** Set the budget generously
  (e.g. global ~18 KB, per-project ~8 KB) so nothing is trimmed at the
  current 15.5 KB. The mechanism is regrowth insurance; the byte-warn
  does the nudging. Honest framing: distillation already did the real
  reduction; this ships the mechanism + fixes the warn bug without
  risking a curated principle. Lowest risk; §8-clean.
- **Fork B — active reduction.** Set a tighter budget (e.g. global
  ~8–10 KB) that drops the lowest-priority section(s) now. Bigger
  immediate payload win, but it drops principles Shawn deliberately
  kept, and it needs an explicit **section-priority order** decided up
  front (candidate first-drop: `## What Works`; then `## Patterns`).
  Higher risk; should earn its own observation window before trusting it.

**Recommendation:** Fork A now; revisit Fork B after Vector 2b's
observation window if the scratchpad is still the bottleneck and Shawn
wants active trimming with an explicit drop order. Rationale:
distillation is the correct lever for content and has already proven
zero-loss; the mechanism's value is stopping silent regrowth and making
the warn fire, not second-guessing a human's curation.

## 8. Open questions

- **8a. Budget values.** §7 fork. Fork A defaults proposed above are
  round numbers, not tuned — adjust once the mechanism is in and real
  density data exists.
- **8b. Warn threshold.** Independent of the cap budget — the warn
  should fire *below* the cap so distillation happens before trimming.
  Suggest warn at ~12 KB global (nudge while still under any Fork-A cap)
  / ~4 KB per-project. Tune after first observation.
- **8c. Per-project budget — needed at all?** The largest per-project
  file is 5.1 KB and cwd-gated. A per-project cap may be pure
  future-proofing. Cheap to add via the shared primitive; decide whether
  to wire it now or leave a TODO.
- **8d. Trim marker wording + placement.** Where the trim marker goes
  (inline at the cut, or as a footer) and its exact text. Minor;
  resolve at implementation.

## 9. Implementation sequencing

1. **Shared primitive.** Add `cap_markdown_to_budget()` to `digest.py`
   (pure; tested in isolation — section boundaries, never-split,
   preamble-always-kept, scaffolding floor, multibyte safety, trim
   marker, under-budget passthrough).
2. **Byte-warn.** Swap `SCRATCHPAD_WARN_LINES` → `SCRATCHPAD_WARN_BYTES`
   in `load_scratchpad()` + `load_project_scratchpad()`; rewrite the two
   warn tests for bytes.
3. **Flag.** Add `scratchpad_budget_enabled()` mirroring
   `digest_mode_enabled()` (env → sentinel → OFF), with constants
   `PA_SCRATCHPAD_BUDGET` / `~/.pa-scratchpad-budget`. Default OFF →
   byte-identical current output. Test flag precedence + parsing +
   fail-safe-to-OFF (mirroring the PASS 2 flag tests).
4. **Wire the cap.** In the `scratchpad_sections` assembly, when the
   flag is ON, pass the global and per-project content through
   `cap_markdown_to_budget` with their respective budgets. Autouse
   fixture pins the flag OFF so the rest of the suite is independent of
   operator machine state.
5. **Roll out to amd-tower only** (its own sentinel), short observation
   window, then go/no-go on zbook + rpi-server — exactly the PASS 2
   shape. **Do not enable until the Vector 2 §8 review (2026-06-13)** is
   done, or enable with awareness that it confounds §8 measurement (3);
   simplest is to ship dark now and enable after the §8 review.

## 10. Risks and mitigations

- **R1: A trim drops a load-bearing principle.** Mitigation: Fork A
  (budget above current size → no trim today); whole-section-only;
  visible trim marker; byte-warn fires first to trigger distillation.
- **R2: Perturbing the §8 window.** Mitigation: separate flag, default
  OFF, byte-identical when off; ship dark, enable after the 2026-06-13
  review.
- **R3: The mechanism is over-engineering for a 15.5 KB file.** Honest
  risk under Fork A — at today's size nothing is trimmed. Counter: the
  byte-warn *is* needed now (the line-warn is genuinely broken), and the
  cap is cheap insurance built on a shared primitive. If Shawn judges
  the cap not worth it, Vector 2b reduces to just the byte-warn fix.

---

*Do not enable the Vector 2b flag on amd-tower while the Vector 2 §8
observation window is open (review booked 2026-06-13) unless the
confound is explicitly accepted. Ship dark first.*
