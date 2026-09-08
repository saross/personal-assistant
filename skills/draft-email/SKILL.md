---
name: draft-email
description: >-
  Use when drafting or revising an email on Shawn's behalf — a reply,
  a request, a notification, a follow-up. Loads the canonical email
  register before writing, drafts concise by default with the call to
  action near the end, runs the register's exit checks, and leaves the
  text as a Gmail draft or inline. Never sends.
---

# Draft email — delivery discipline

**Announce at start:** "I'm using the draft-email skill; loading the
register before I draft."

This skill is a **delivery mechanism, not a style guide**. The register
lives in a notes file and is loaded at the gate below. The skill
supplies the gate, the drafting contract, the exit checks, and the
send guardrail. Architecture mirrors `academic-prose`.

## ⛔ Guardrail: Claude drafts, Shawn sends

Standing rule (global CLAUDE.md, set 2026-09-02). Use `create_draft`,
`update_draft`, or show the text inline. Never `send_message`, `reply`,
or `forward`. A task brief naming an email is an instruction to draft
it. Approval to send is a separate, explicit yes from Shawn about the
actual text, after he has read it.

## Gate: load the register (once per session, before the first draft)

Read in full:

`~/personal-assistant/data/notes/style-guides/email/reference_register-email.md`

A memory of the rules is a pointer, not the rule. Re-open the file,
including for a two-line reply late in a long session.

## The drafting contract

- **Shape:** warm at the edges, precise in the middle. Human greeting
  and close; a clean ask in between with nothing wrapped round it.
- **Concise by default** (Rule 4). No "be concise" prompt should be
  needed. State the fact and stop (Rule 5). No reminders of what the
  recipient already agreed (Rule 6). No sentences announcing structure
  (Rule 7). Decide rather than ask when the answer is Shawn's to give
  (Rule 8).
- **Hedges:** keep epistemic and cost-of-no hedges; cut status-lowering
  ones (Rule 2). Tier the recipient (Rule 3): favour-asking gets the
  cost-of-no exit, opted-in gets a clean question, transactional gets
  answer-confirm-stop.
- **Call to action near the end** (Rule 9) whenever something is
  needed: what, from whom, by when.
- **Warmth goes light** (Rule 10): warm greeting and close, people
  credited by name. No exclamation marks, no repeated thanks — Shawn
  adds those in ten seconds, modulated to the recipient; cutting costs
  him minutes.
- **Mechanics:** contractions, `--` not `—`, asks as questions, reasons
  inside clauses, bullets for multiple items, closes that hand over
  control, `Cheers, Shawn` by default.
- **Anchor every specific** — date, name, figure, promise — to the
  thread, the task files, or Shawn's words this session. Never invent
  a plausible detail; write `[confirm: …]` instead.

## Exit checks (all twelve in the register; the countable ones here)

```bash
# On the draft text saved to FILE
grep -c '—' FILE                       # must be 0
grep -n -iE 'as (promised|agreed|discussed)' FILE
grep -n -iE '\b(so|which|and it is) ' FILE   # candidate trailing justifications — read each
grep -n -iE 'apolog|sorry' FILE        # keep only if the delay cost the recipient
wc -w FILE
```

Then by eye: ask in the first three sentences of its paragraph; ask is
a question; CTA in the last substantive paragraph; contractions
present; recipient could act without re-reading; edges warm.

## Handover

Leave the text in Gmail Drafts (or inline if two lines), say it is
ready for review, and stop. **Record where the draft lives** — Gmail
draft id or file path, plus recipient and date — in the session's
continuity note, so the next calibration can pair it with the sent
version. Calibration reruns when five or more new pairs exist.

## Red flags — stop if you catch yourself thinking

- "I'll add why this matters." → The recipient can infer it. Cut.
- "Remind them they agreed." → They know. Cut.
- "Ask which option they prefer." → If Shawn can decide, decide.
- "Warm it up to soften the cuts." → No. Cut the justification, keep
  the edges, leave warmth to Shawn.
- "It's urgent, I'll send it." → Never. Draft, hand over, stop.
