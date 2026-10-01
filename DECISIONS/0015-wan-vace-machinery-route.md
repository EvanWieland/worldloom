# 0015 — Wan 2.2 VACE route for scenes with rotating machinery, with a motion-evidence structure lock
Status: rejected by the user 2026-09-28 (drop masking; the director should instead edit scenes around things that
move in circles, which LTX handles poorly) -- replaced by director v19: a rotating part
keeps turning slowly and is veiled by the dust / steam it churns up
Date: 2026-09-28

## Problem

LTX-2.5 distilled (the take / closure model since ADR 0007) does not turn rigid rotating parts: the harvester's front
drum re-synthesises in place (in review it streaks, smears and fades forward; after the 4K finish it still looks
smeared, the teeth drag instead of turning cleanly). Measured: 20-36 % of the drum's frame change is motion; resolution,
single-stage, prompt wording, depth-guide blur and the 4K finish do not fix it; local 720 freezes the drum over a full
take (research/harvester-drum.md items 1-10).

## Considered approaches

1. Keep LTX, accept the drum (no fix).
2. Offsite higher-resolution LTX (untested; 720 froze locally, so resolution alone is doubtful).
3. **Wan 2.2 Fun VACE A14B with the still's depth as camera lock + the still as landscape reference + concrete
   rotation wording + a structure lock** (pixels the run's own LTX take never changes are held as the still).
4. Text-grounded masks (SAM 3.1 on the director's fixed / moving phrases): failed on the still (0 % for "drum",
   "machine", "hull"), parked.

## Evidence (research/harvester-drum.md items 11-13)

| harvester, 81 f @ 16 fps | drum explained / flow | surroundings frame change | scene kept |
|---|---|---|---|
| LTX 480 loop (rejected) | 0.26 / 0.47 | 0.63 | yes |
| VACE depth only (s306) | 0.46 / 1.07 | — | NO (repainted) |
| VACE + ref (2 seeds) | 0.01-0.02 / 0.04 (frozen) | — | yes |
| VACE + ref + rotation wording (s308) | 0.39 / 0.99 | 1.57 (janky in review) | yes |
| **+ motion-evidence lock (s308)** | **0.42 / 0.95** | **held 0.62** | yes |

Reviewer on the last: looks good. Seed yield 1 of 3 on every VACE arm.

**Second scene (mining crawler, director prompt as-is) FAILED the rotation half:** the LTX evidence take never moved
the tracks (flow 0.012), so the lock held 80 % of the track box and all 3 Wan seeds froze them (flow 0.02); the rest
(slag, beams, camera 0.03-0.07 px, held change 0.40 vs free 0.62) was fine. Confirms the stated limitation: an LTX
evidence take cannot free what LTX does not move. Next: evidence from Wan's own unlocked render, and optical FLOW
(coherent motion) instead of raw change (harvester jank = high change, flow 0.05; drum flow ~1).

## Decision (proposed — the user decides)

For a run whose contract has a rotating-machinery requirement (`machine_rotation`) and no declared moving light:
render the take with Wan 2.2 VACE (depth + reference + lock from a short LTX evidence take), N seeds, pick by the drum
QC (`experiments/drum/drumqc.py` generalised: motion-explained fraction in the most active region); everything else
keeps the LTX route. The lock is automatic (no words, no drawing), per the standing rule that a mask is used only if it generalizes
and the pipeline still runs without Claude.

## Tradeoffs

- Two models per run for these scenes (LTX evidence take + Wan take): more time (~8 min per 5 s Wan window + an LTX
  take), more code paths.
- Wan renders 16 fps: RIFE x1.5 to 24 fps (proven E5); 81 f windows -> a 20-30 s take is chained windows (VACE
  continuation / context overlap, proven for closures in ADR 0006).
- The lock can only free what the LTX take moved: if LTX freezes the rotating part, the lock would freeze it too
  (crawler lock was patchy: 22 %). Mitigation to test: free the contract's moving subjects when found.
- Held pixels sit ~6 grey from the still (tone), steady; lighting changes on held structure are impossible (hence no
  declared moving light).
- Loop closure for Wan takes: ADR 0006's VACE closure, not ADR 0012's LTX long return.

## Consequences

New stages: `evidence` (short LTX take or reuse), `lock` (motion_lock), `wan_take` (VACE windows), take selection by a
generalised rotation QC; closure via ADR 0006 path; review adds the rotation QC line.

## Revisit when

The crawler (second scene) fails; a single model turns rigid parts cleanly without a lock; offsite LTX at higher
resolution turns the drum.
