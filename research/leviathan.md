# Volcanic Leviathan (user still + brief, 2026-09-28)

Inputs: `runs/inputs/leviathan.png` + `leviathan_prompt.md` (hover-battleship over lava; pulsing anti-gravity
emitters are the centrepiece; intermittent lightning; "do not place a flash at either loop boundary").

## Run `leviathan` (default route, 832x480): failed -- no usable take

Director v17 kept the essentials (pulsing white-amber emitters with lava reflections, lavafalls, eruption smoke,
"bright white forks of atmospheric discharge flash intermittently", embers at depths; the user's "avoid neon" stays
excluded). Contract quirks: "lava waterfalls" read as water_motion; no checklist line for the pulsing emitters.
Settle ran (transient early 4.28 / late 2.91) and the take started from the calm settled frame.

| take seed | worst cell drift (boundary) | pulse | camera px |
|---|---|---|---|
| 306 | 28.4 (c01 sky) | 27.5 | 0.07 |
| 307 | 7.63 (c02) | 13.6 (c00) | 0.01 |
| 308 | 13.9 | | |

Cause (seed 306, sky cell c01, per-second grey): the model FRONT-LOADS the storm -- ~9 s of frequent flashes (per-second
p20 74-90, i.e. sustained, not brief impulses) then calm (64) with one late flash. A per-second median would not
rescue it (medians 79-102 early vs 64 late): it is a regime change, not flicker. "Flash intermittently" is rendered as
a burst.

## Next: scheduled lightning (Prompt Relay)

WanGP LTX Prompt Relay: text before the first `[range]` is global; `[5.2s:5.7s] text` is attended only near that time
(`shared/prompt_relay.py`). Probe `runs/drum/lev_relay` (full 481 f take, seed 306, same settled keyframe): lightning
removed from the global prompt, five half-second flashes at 5.2 / 8.9 / 11.6 / 15.3 / 18.1 s (clear of the loop start
at 3.7 s and the take end). Pipeline catch if adopted: steady_light appends text AFTER the motion prompt, so relay
ranges must be appended last; a closure window would need its own schedule (ranges are relative to each window).

**Result: no flashes at all** (sky 65 grey every second; no frame > 4 grey over its 2 s median). The take is otherwise
perfectly stationary (take_qc drift 1.07, pulse 1.97, camera 0.01 px: passes). Either half-second windows are too
short for the relay mask, or the global "lighting stays exactly constant" clause wins. Not pursued further.

## The emitters never pulse (all takes)

Emitter glow (mean of the big left emitter box) varies +-1 grey over 20 s in every take (detrended std 0.6-0.8): the
brief's centrepiece is absent. Cause (hypothesis): the steady-light clause "the overall lighting, exposure and colour
stay exactly constant". Generic fix: `motion_style.PULSING_LIGHT` -- a sentence where a light source pulses / flashes /
throbs / strobes counts as moving light -> exposure-only clause + 5 s QC means (as for beams). Matches only the
leviathan and crawler_720 prompts among past runs. `leviathan` resumed with it after the harvester 4K.

**Resumed run (exposure-only clause, 5 s QC means):** settle skipped; take seed 306 passes easily (drift 1.4, pulse
2.3, camera 0.03 px) but the emitters STILL do not pulse (glow std 0.6) and there is no lightning (sky 64-68): the
clause was not the (only) cause. All 3 long-return closures fail loop_qc on foreground motion: bottom cells (lavafall
/ steam) drop to 0.47x of the take's rolling motion right where the return starts (frame ~401), plus sky drift 10.7-13.5
in c01; joins themselves clean (closing ratio 0.97-1.0). Run ends `unresolved`; failure review in
`runs/leviathan/stages/review/f8c5747bdfb53517/`. Not sent (the centrepiece is missing anyway).
QC tool: `experiments/drum/pulseqc.py` (source pulse std + period, spill correlation, sky flash frames, camera).
Baselines: current take pulse 0.59 / no period / 8 flash frames; storm take 0.75 / 2.6 s / 102.

## Emitter probes (121 f, seed 306, `runs/drum/lev_p1..4`, exposure-only clause)

| probe | pulse std (grey) | spill std | spill corr | camera px |
|---|---|---|---|---|
| P1 director wording "pulse rhythmically with bright white-amber light" | 0.65 | 1.56 | 0.18 | 0.04 |
| **P2 concrete: "throb with power: about once every second their white-hot cores flare much brighter, flooding the lava and the smoke below with light, then dim back down, each slightly out of step"** | **9.4** | 6.1 | **0.94** | 0.07 |
| P3 = P2 + depth guide 0.5 | 13.3 | 7.8 | 0.94 | 0.20 |
| P4 = P2 + single stage | 6.4 (one slow swell) | 2.5 | 0.91 | 0.08 |

P2 series: 139 (keyframe) -> 207 in 1.3 s, down to ~170, back to 209 ~3 s later: a visible swell / dim with the lava lit
in step (frames checked). **Wording is the lever, not the steady clause alone.** -> director v18 rule (hypothesis:
one scene). `leviathan_pulse` = full loop with P2's wording (`--raw-prompt`, runs/inputs/leviathan_motion_pulse.txt).

## `leviathan_pulse` (delivered 2026-09-28, review sent; verdict pending)

- Settle take pulses 11.4 (period 1.3 s, spill corr 0.98); take[0] pulses 12.2 (~4 s), 78 lightning flash frames.
- take_qc v3 rejected take[0] (c10 boundary 9.95 = pulse PHASE: floor 79-81 all take, last 3 s between pulses) ->
  **take_qc v4**: moving light judged on the window floor (p10): 3.23 passes; start transient / regime change still fail.
- loop_qc rejected every closure: c10-c12 "low" at the emitters' natural 4 s lull (frames 338-349) running from the take
  into the return (gap 352) -> **loop_qc v7**: with a declared moving light the low limits are min(fixed, 0.85 x the
  take's own minimum). v6 (low only in modified frames) was reverted: replay passed harvester old-route drum stalls.
  Replay `experiments/gate_replay/loop_qc_replay.py leviathan_pulse:moving leviathan:moving harvester harvester_1s`.
- Delivered closure 306: closing 0.80, churn worst 1.09, camera 0.14 px, pulse 10.8 (4 s), spill corr 0.95, 90 flash
  frames. **Open: the wrap** lands on a fading flare with a one-frame 9-grey dip (141 -> 132; neighbours ~2/frame):
  step 4.33x (natural pulse onsets reach 5.4x, so closing_over_rest passes). Review metrics that read pulse phase as
  drift (loop drift 37) are false alarms for this scene.
- **Review verdict: looks good; wanted more smoke motion, more floating embers in the foreground, and a slightly
  steadier emitter pulse.**

## v2 wording probes (121 f, seed 306, base = leviathan_pulse take; `experiments/drum/lifeqc.py`)

| probe | smoke flow | embers_fg | pulse std / interval cv |
|---|---|---|---|
| b0 (approved wording) | 0.105 | 197 | 21.3 / 0.25 |
| both (concrete smoke + foreground embers) | 0.122 | 211 | 9.2 / 0.11 |
| all (+ "steady, even rhythm ... every two seconds, never pauses") | 0.117 | 220 | 13.5 / 0.57 |

5 s is too short for pulse regularity (3 peaks). The ember counter includes lava flicker; the max-minus-median TRAIL
image (runs/drum/lev_trails.jpg) is decisive: "all" draws large defocused embers across the whole foreground, b0 none.
Smoke gain is small (+12-16 %). -> `leviathan_v2` full loop with the "all" wording (runs/inputs/leviathan_motion_v2.txt).
