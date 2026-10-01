# 0005 — Target is a 30–60 s seamless forward-motion loop, proven locally, final-rendered offsite
Status: accepted (user decision, 2026-09-22). Refines 0003; supersedes the "hours from a finite pool" framing in 0004.
Date: 2026-09-22

## Problem
The pipeline was scoped for "plays for hours and looks continuous" from a pool of 5 s clips. Every join method that reuses short clips has failed human review: cross-dissolve (morph), ping-pong (visible reversal at any directional motion; seams every 5 s, scenes too short). Forward continuation (sliding windows) has invisible seams but drifts after ~10–15 s, and generated loop closure had not passed until L1.

## Brief (intent, 2026-09-22)
1. A Hollywood-quality scene, proven locally, then sent to an offsite GPU for the full render.
2. A convincing scene that repeats, but not too quickly, does so seamlessly, and does not depend on reversing playback (no clouds changing direction).
3. Only a 30 s – 1 min clip is needed that lets the entire scene flow; the work is seamlessly stitching the beginning and end frames.

## Evidence
`research/local-video-baseline.md` — sliding-window chains (seams invisible, drift caps ~10–15 s at the calm recipe), and L1/L1b: `flf2v_720p` closes a chain back to its first frame at 1.6–1.7× appearance / ≈1× velocity vs normal motion (target ≤ 2×), artifact-free **at native 1280×720**. It fails at 848×480 (blocky sky), and a full 81-frame native-res bridge is impractical locally (110 min/step, killed). **But the 2 s native bridge failed review: it freezes completely for a few seconds.** Motion decays to about a third of the chain's level. The closure method is therefore still open. The decision below does not depend on which closure method wins.

## Decision
- The deliverable unit is **one 30–60 s forward-motion segment whose last frame flows seamlessly into its first**. Playback is plain looping of that file (stream-copy concat of N copies if a fixed duration is wanted). No pools, no reversal, no dissolves.
- Local work proves the recipe at T1/T2; the final segment at delivery quality is rendered on a rented GPU (0003 unchanged).
- Closure is generated (FLF2V-style first+last-frame conditioning), not blended. **Clarified in the planning session (user, 2026-09-22):** retiming the generated bridge to a constant motion level still counts as generated closure; any bridge is gated on motion level and direction across its whole length, not just the join frames.
- **Fallback allowed for testing (user, 2026-09-22):** re-anchored segments — N × (10–15 s chain from the keyframe + bridge back to it, different seeds) inside one 30–60 s loop. The keyframe state then recurs every 12–17 s; whether that reads as repetition is decided by eye, not assumed.

## Tradeoffs
- Repetition period is 30–60 s; the user has accepted that as not repeating too quickly. Not the earlier "hours, non-repetitive" ambition.
- Chain length 30–60 s exceeds the measured drift horizon (~10–15 s); drift control is now on the critical path.
- Native-res bridge generation is expensive locally; may only be proven short (2–3 s) locally and rendered long offsite.

## Consequences
- `enhance` (ping-pong) and `assemble` (legs) are wrong and must be rewritten: chain + bridge → RIFE/retime → stream-copy.
- The plan stage's "pool size" concept becomes "segment length + bridge length".
- Quality gates need a spatial-noise/blockiness check (the L1 artifact was invisible to every existing frame-difference metric).

## Revisit when
A human watches a full 30–60 s local loop and judges it; or offsite render cost/limits are known.
