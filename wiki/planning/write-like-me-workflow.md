# `/write-like-me` workflow — neutral draft → voice-align

**Codified 2026-06-03 (Shawn + CC) · Workstream G · roadmap item #2.**

The drafting workflow separates **content** from **voice**: get the content
right first, in plain prose; apply the voice last, as a conservative finish.

**Why this order** (from the efficacy experiment + the design discussion):

- **Voice masks content flaws.** On-voice prose reads as authoritative, and
  fluency/familiarity lower scrutiny — flawed arguments get waved through when
  they "sound like you". Plain prose puts the argument and evidence naked on
  the table, which is the easiest possible substrate to audit.
- **Each pass does one job better.** The model writes the argument more cleanly
  when it is not simultaneously fighting a dozen voice targets (sentence
  length, concession rate, first-plural, no citations, semicolon density…).
- **It plays to the proven division of labour.** The experiment showed voice is
  the reliable part and content the generic / confabulation-prone part. So nail
  the content naked; dress it last with the reliable transform.

## The five stages

1. **Outline** — jointly (Shawn + CC). Voice-relevant *structure* (signposting,
   argument sequence) is settled here; later stages work below the structural
   level.
2. **Neutral draft** — CC writes in plain, clear, content-focused prose. No
   effort to sound like Shawn yet. Goal: the best argument + evidence, legibly.
3. **Author-hat content edit** — Shawn revises for substance and correctness
   against the plain prose (easiest possible audit). **Note:** even editing
   "for content only", the draft naturally drifts toward Shawn's voice. This is
   a *feature*: it lightens stage 4, and means stage 4's input is
   Shawn-inflected, not fully neutral. (Optional instrumentation: run `phase5`
   on the stage-2 vs stage-3 drafts to quantify how far the edit already moved
   it toward his voice.)
4. **Voice-align (`/write-like-me`)** — apply the validated, citation-stripped
   guide + Appendix F exemplars as a **conservative, meaning-preserving,
   transparent finish**:
   - **diagnose first** (`phase5` per-feature |z|), adjust **only where the
     draft is still off-voice**, and **preserve the voice Shawn already got
     right** — do not homogenise his choices;
   - **meaning-preserving**: change voice/surface, not claims; **flag any
     substantive edit**;
   - **show what changed** (a diff Shawn can scan);
   - **no citations** (venue-determined, guide §3).
   Because stage 3 drifts the draft toward Shawn, stage 4 is closer to a voice
   *finish / lint* than a full neutral→Shawn translation, and scales with how
   far the draft already is.
5. **Editor-hat final pass** — Shawn polishes the voiced version: catches any
   meaning-drift introduced by stage 4 and tunes any overdone voice. **Editor,
   not author.**

**Two checkpoints, two hats:** content is audited on plain prose (stage 3,
author hat); voice *and* meaning-drift are audited on the voiced version
(stage 5, editor hat). This is what makes the neutral→translate order safe:
the artifact Shawn verified for content (stage 3) is different from what ships
(stage 4 output), so stage 5 re-verifies the shipped artifact against drift.

## Architecture

- `/write-like-me` = the **stage-4 skill** (the voice-align transform). It
  drives a fresh-context generation agent for isolation (clean context → clean
  voice, per the experiment), runs `phase5` inline as the diagnostic, and uses
  the per-feature deltas as feedback for a 1–2-pass iterate loop. Optional
  blind-judge agent as the heavier gate.
- Stages 1–3 are normal collaboration — no skill.

## Validate before trusting (gate on building the skill)

The efficacy experiment validated the **fused** path (content + voice in one
shot). The **neutral → voice-align** path is **untested**. Before relying on it
or building the skill:

- run a couple of real neutral drafts through stage 4;
- blind-pair the voice-aligned output against a *fused* in-voice draft of the
  same content; Shawn judges which is more *him*, and whether the meaning held;
- check `phase5` distance + a meaning-drift read.

**Try the workflow manually first** (CC drafts neutral in-conversation, Shawn
edits, CC voice-aligns by hand applying the guide); build the skill only once
stage 4 proves out. Happy to iterate / adjust the workflow as we go.

## Status

Codified 2026-06-03; workflow agreed. Next: use it on a real piece of writing,
validate the stage-4 transform, then build the skill (roadmap #2).
