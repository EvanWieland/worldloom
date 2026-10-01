# 0013 — Scene contract and content gates, separate from loop continuity
Status: **accepted** (2026-09-27; implementation handoff `LOOPER_IMPLEMENTATION_HANDOFF_2026-09-27.md`, supplied by the user)
Date: 2026-09-27

## Problem
lighthouse_lr_s02 passed every continuity check (in review neither join was visible) and failed as a scene: waves
very poor, the lighthouse light missing entirely. Nothing in the pipeline recorded what the scene had to contain,
so nothing could say a required element was gone, and the only review came after ~55 min of closure work.

## Decision
1. **Scene contract** (`looper/contract.py`, stage `contract`, runs on every path incl. `--raw-prompt`): requirements
   come only from the user's words (word rules per motion family: emission, flow, atmosphere, periodic illumination,
   rigid periodic). The director proposes the plan; the contract checks it. An omitted emission / flow / atmosphere
   element is put back as one plain clause; a negative that names a required element is removed; an element still
   missing makes the outcome `best_effort`.
   **Amended same day (requested: no rule against beams; the scenes should be striking and as realistic as
   possible):** there is no beam gap. A beam, turning machinery or breaking sea the DIRECTOR selects becomes a
   `director_selected` requirement of that design, with effect fields (initial state, motion, expected relationships,
   forbidden substitutions such as a static glow for a sweep); its route is `unverified` until a human passes it.
   Prompt-only runs append framing clauses so defining effects have room in the still (never a user's image).
2. **Content gates** (`looper/acceptance.py`): `loop --audition` pauses after take_qc with an audition packet
   (native-res take at real speed, automatic detail crops, original vs effective prompt, contract checklist, recipe,
   timing); `looper accept RUN take|loop [--reject|--best-effort]` records a decision bound to the stage fingerprint,
   the output's hash and the contract hash. A rejection stops the run; any change of recipe, output or contract
   re-opens the gate. `--4k` (about 2.6 h) only runs on a loop accepted this way.
3. **Outcome states**: `needs_review` (default after a run), `accepted` / `best_effort` / `rejected` only from a
   recorded human decision; `best_effort` also whenever the contract has a gap.

## Compatibility
Without `--audition` the loop path runs end to end as before (compatibility mode while the gates are calibrated).
The contract stage changes no take fingerprint unless it repairs the plan. `--4k` now pauses for `looper accept RUN
loop` -- a deliberate change: finishing is ~74 % of loop+4K time.

## Limits
Word rules catch omission and a named negative; they cannot prove the effective prompt means what the user meant --
the audition shows both prompts side by side for that. Requirements from the image alone (a lantern the prompt never
names) are not captured. Automated checks stay diagnostics; the human decides.
