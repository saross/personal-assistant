# `moderate-mark` — Copilot port

This is a port of the `moderate-mark` skill (built for Claude Code,
lives one directory up at `~/personal-assistant/skills/moderate-mark/`)
adapted for use with Microsoft Copilot Chat for Enterprise / GPT-5.x.

The Copilot port exists because student data is subject to
institutional privacy controls that approve enterprise Copilot but
not Anthropic Claude. The Claude version remains the canonical
reference and is used for skill development, refinement, and any
future deployment to environments that do approve Claude (e.g.,
Claude Enterprise). The Copilot port is the production marking tool
for HUMN8031 from the next assessment cycle onward.

## Privacy boundary

**The Claude-Code skill is for skill maintenance only. The Copilot
port is for student data only. Do not cross.**

Concretely:

- The bootstrap prompts and templates in this directory contain NO
  student data — they are pure instructions and can live in any
  repository.
- The per-paper input template, once filled with one paper's marker
  tier picks + A1 feedback + submission body text, DOES contain
  student data — paste it ONLY into Copilot.
- Copilot's outputs (the dossiers) contain student data — handle per
  your usual marking workflow (Canvas, encrypted local storage, etc.).
- Do NOT paste student data into Claude Code (Anthropic) at any point
  during marking. Skill development, rule refinement, and format-spec
  edits do not require student data and remain Claude-friendly.

## What's in this directory

```text
copilot-port/
├── README.md                            (this file)
├── per-paper-input-template.md          (shared between variants)
├── single-shot/
│   └── bootstrap.md                     (one paste; one dossier per paper)
└── multi-stage/
    ├── bootstrap.md                     (one paste; sets up multi-stage workflow)
    ├── stage-1-neutral-dossier.md       (paste per paper)
    ├── stage-2-upward-check.md          (paste per paper after Stage 1)
    ├── stage-3-downward-check.md        (paste per paper after Stage 2)
    └── stage-4-reconcile-and-append.md  (paste per paper after Stage 3)
```

## Two workflow options

### Option A — Single-shot (simpler; routine cases)

**One bootstrap paste per Copilot session, one per-paper paste per
dossier.** Copilot produces the full dossier in one response.

Use for: routine cases with no obvious borderline calls; cases where
the marker is confident in their tier picks; bulk processing where
per-paper interaction time is the binding constraint.

Flow:

1. Open a fresh Copilot session.
2. Paste `single-shot/bootstrap.md` into the chat. Copilot will
   acknowledge and may summarise the rules; that's normal.
3. For each paper:
   1. Fill `per-paper-input-template.md` with the paper's data.
   2. Paste it into the same Copilot session.
   3. Copilot produces the full dossier (sections 1–11).
   4. Copy the dossier into wherever you store dossiers.
4. End the session when done. The bootstrap and any pasted student
   data leave Copilot's context when the session closes.

**Estimated effort per paper:** 5–10 minutes (mostly filling the
input template; Copilot's response is fast).

**Quality caveat:** All four pipeline stages happen in one inference
pass. On borderline cases (papers where the marker is uncertain, or
where the descriptor evidence is mixed), the discipline rules can
get conflated. Use multi-stage for these.

### Option B — Multi-stage paste-along (higher quality; borderline cases)

**One bootstrap paste per Copilot session, then four sequential
prompts per paper.** Each stage gets a focused inference pass.

Use for: borderline papers (failing marks; HD candidates; override
candidates; papers where you have reservations); the first 2–3
papers in a marking cycle as a calibration round; papers where
audit logs need to show the moderation reasoning per stage.

Flow:

1. Open a fresh Copilot session.
2. Paste `multi-stage/bootstrap.md` into the chat.
3. For each paper:
   1. Fill `per-paper-input-template.md` with the paper's data.
   2. Paste `multi-stage/stage-1-neutral-dossier.md` followed by the
      filled input template. Copilot produces the neutral dossier
      (sections 1, 3, 4, 5).
   3. Paste `multi-stage/stage-2-upward-check.md`. Copilot appends
      Section 5a (Upward check).
   4. Paste `multi-stage/stage-3-downward-check.md`. Copilot appends
      Section 5b (Downward check).
   5. Paste `multi-stage/stage-4-reconcile-and-append.md`. Copilot
      writes Section 2 (Verdict) and Sections 6–11 (polished bullets,
      borderline paste-ables, final mark recommendation).
   6. The full dossier is now built in the chat thread; copy it to
      wherever you store dossiers.
4. End the session when done.

**Estimated effort per paper:** 15–25 minutes.

**Quality benefit:** Each stage gets focused inference. The
default-to-lower discipline (Rule 1), the marker-comment-as-
descriptor-evidence rule (Rule 2), and the cohort-relative discipline
(Rule 4) are more reliably applied because each stage knows what it's
checking for.

### Mixing options within one cycle

A reasonable workflow for an 18-paper cohort:

1. Use multi-stage on the first 2–3 papers as a calibration round.
2. Switch to single-shot for the bulk of routine cases.
3. Drop back to multi-stage for any borderline papers identified
   during the routine run, or any paper where the single-shot
   dossier reads thin.

## What's lost in translation from the Claude version

The Claude-Code skill has affordances Copilot doesn't:

| Claude has | Copilot port handles by |
|---|---|
| File globbing for marks/A1/submission | User pastes content into the per-paper template |
| `awk`-based deterministic body word count (Rule 8) | User computes word count in their editor and reports it in the input template |
| Subagent spawning for parallel batch | Sequential per-paper interaction (no batch mode) |
| `SKILL.md` auto-loading | User pastes the bootstrap manually at session start |
| In-place dossier editing across stages | User copies prior-stage output back into the chat (multi-stage) |
| Pre-flight bails on missing inputs | User checks they have all inputs before starting |
| Stage re-invocation on existing dossier | Re-paste the stage prompt with the prior dossier (multi-stage) |

The substantive intellectual content transfers cleanly: the 11
discipline rules, the 10-section format spec, the locked verdict
vocabulary, the polished bullet structure, the per-criterion
borderline paste-ables, the A1 → A2 trajectory framing.

## HUMN8031-specific vs portable

The bootstrap prompts include three HUMN8031-specific elements
clearly marked with `[HUMN8031-SPECIFIC]` headers so they can be
swapped for future university deployments:

- **Rule 4 cohort-relative norm.** ANU Masters: modal D (70–79),
  cohort mean low 70s, HD reserved for 1–2 papers. Replace with the
  target institution's norm.
- **Rule 9 A1 ↔ A2 commensurate criterion mapping.** Specific to
  the HUMN8031 A1 (proposal) and A2 (literature review) rubrics.
  Replace with the equivalent mapping for the target assessment
  pair.
- **Rubric-specific descriptor quotes** in the format spec section
  on per-criterion borderline comments. Replace with the target
  rubric's descriptor language.

Everything else (the discipline rules' substance, the format spec's
structure, the verdict vocabulary, the bullet templates, the
anti-patterns) is portable across rubric / institution / assessment
type.

## When to update this port

- After the next HUMN8031 assessment cycle (A3) reveals borderline
  cases the rules don't cover well — update Discipline Rules and
  re-export to the bootstrap.
- After any v0.1.x or v0.2 update to the canonical Claude skill —
  re-export the affected rules and format-spec sections here. Keep
  the two in sync; `planning/moderate-mark-skill-known-limitations.md`
  in the HUMN8031 project repo tracks the Claude side.
- When deploying to a new university — fork this port; replace the
  three HUMN8031-specific sections; keep the rest.

## Version

This port is derived from `moderate-mark` v0.1.1 (Claude-Code skill,
2026-05-14). Track-along versioning: when the Claude skill ships
v0.1.2, this port becomes v0.1.2 once the relevant changes are
re-exported.
