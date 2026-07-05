---
description: Session-close ritual. Invoke on /handoff, "let's wrap up", "before we close out", "wrap session", or any end-of-session / session-close signal in a single project. Updates continuity, captures observations, flags wiki candidates, drafts user-observation candidates, and commits-and-pushes batched by logical area.
---

# /handoff — Session-Close Ritual

End-of-session ritual that updates continuity, captures fresh observations,
and lands a clean working tree before context is lost. Distinct from `/recap`
(daily, multi-project, accountability) — `/handoff` is per session-close in a
single project and serves continuity for the next session.

## Usage

```text
/handoff
```

No arguments. Adapts to session weight (light / heavy / verification-only).

## Behaviour

1. **Read** `~/personal-assistant/global-claude-md/handoff-protocol.md` and
   execute the six steps it defines. The protocol is authoritative — do not
   improvise from this skill; read it fresh each invocation.

2. **Honour the adaptation rules** in the protocol:
   - Light session → skip steps 2–4; update continuity only if needed.
   - Heavy design session → all six steps; budget ~10 minutes.
   - Verification-only → often no continuity update at all.
   - **Step 6 (resume prompt) always runs**, whatever the session weight.

3. **Key refinements** (do not omit, even when the protocol summary is
   skimmed):
   - **Step 4 (observations — two registers, split by *who observed
     whom*):**
     - *4a user-observations (gated):* draft 2–4 candidate observations of
       things **Shawn observed about Claude** (what I did that helped /
       didn't), then surface them for accept / edit / discard / replace.
       Don't ask a blank-page question — candidates jog memory and are
       useful even when wrong. One exception lands here: an in-the-moment
       Shawn reaction I relay ("wow, that helped").
     - *4b claude-observations (default-keep):* write 1–4 observations of
       things **I observed about Shawn** (working style, decisions) plus my
       own collaboration self-critiques, *directly* into the project's
       `claude-observations.md` — not gated. Be liberal. Symmetric dedup
       guard with `/reflect`: **either ritual may run first**; if today's
       claude-obs already exist, augment rather than duplicate. **Then
       display the obs full-text in the close-out message alongside the 4a
       candidates** (protocol Visibility rule, 2026-07-05) — Shawn reads
       both registers together to make mid-course corrections; written ≠
       seen.
   - **Step 5 (commit and push):** *default is commit-and-push everything*
     before handoff closes, batched by logical area (design-doc, protocol-doc,
     continuity, notes — one commit per area). Bundle into a single commit
     only if all changes belong to one logical area. Surface push failures
     rather than working around them.
   - **Step 6 (resume prompt):** *end the handoff with a brief, copy-paste-ready
     prompt* for the next session — orientation to the continuity / planning
     doc(s) plus any carry-forward context the docs don't capture. Display it
     last, in a fenced block, after the commit/push. Runs every time.

4. **Apply the anti-confabulation rule** when drafting the continuity diff:
   re-read any cited filenames, line numbers, commit hashes, or config values
   at the source before including them. Sessions are long; specifics drift.

## Notes

- The protocol doc is the source of truth. This skill is a thin invoker.
- `/handoff` does not curate wiki pages (that is `/weekly-review`), does not
  modify `FOCUS.md`, and does not surface memories for review.
- If the session was load-bearing and you are tempted to skip the continuity
  update — stop. That is the highest-cost failure mode.
