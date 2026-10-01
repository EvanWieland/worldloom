# 0004 — Long-form via a keyframe-anchored clip pool joined by cross-dissolves (not generated loop closure or chaining)
Status: **ping-pong assembly rejected for directional motion (2026-09-22); the keyframe-anchored clip pool remains the generation model until a forward-only continuation method is measured.** History: cross-dissolve rejected by human review (visible morph); ping-pong accepted provisionally on a calm, near-static sample (passed review); then rejected on the first real pipeline output with gentle motion — in review the transitions were jarring, the back-and-forth approach itself felt wrong, the scenes were probably too short, and clouds do not slide back and forth over the sky like that. Measured: the reversal jolt is 3.9–6.9× normal at gentle motion vs 1.1–2.1× at calm; easing the turnaround removes the jolt but not the visible reversal itself. Two conclusions: (1) any assembly that reverses time only works for motion slow enough to have no visible direction; (2) 5 s clips put a seam every few seconds, which no join hides. Next candidate: forward-only continuation (SVI / sliding windows) with the calm+NAG recipe — its earlier failure predates that recipe. See `research/local-video-baseline.md`.
Date: 2026-09-21
Refines 0003 (generative video stays the backbone; this changes how clips become a long, seamless video).

## Problem
ADR 0003 assumed chained I2V segments (SVI) plus a generated closure back to frame 0. Local experiments (`research/local-video-baseline.md`) tested that.

## Considered approaches
1. **First = last frame conditioning** on Wan 2.2 14B I2V. Measured: seam 28× the normal frame change, motion collapsed (sky temporal std 0.8 vs 3.0), last frame ≠ keyframe. Rejected.
2. **SVI 2 Pro chaining + end anchor** (2 windows, 158 f). Measured: camera push-in (~190 px shift), architecture morph, luma +30 %, sparkle artifacts, seam 40×. Not adequate as tested (single seed, defaults; other settings untried).
3. **Keyframe-anchored clip pool + cross-dissolve.** Every clip is an independent 5 s I2V from the *same* keyframe (different seed/motion prompt). Clips are joined by 0.75–1.5 s dissolves; luma is normalised to the keyframe. Measured on 2 clips (seeds 42, 7): worst-tile transition ratio **1.7–2.2×** normal change (self-loop and A→B), no ghosting in the contact sheet, brightness dip removed by normalisation.
4. Boomerang (forward+reverse) and VACE bridge: untested; boomerang expected to show reversed motion, VACE needs ≈ 6+ GB more weights and WanGP marks its 2.2 support partial.

## Evidence
`research/local-video-baseline.md` (Videos B, C, D and dissolve section), `experiments/dissolve_test.py`, `experiments/clip_metrics.py`. Caveats: one scene, two seeds; metrics are pixel-difference based (mean luma over 4×4 tiles), not perceptual; nobody has watched the output; seed 7 drifted more (14.5 px, ~15 px shift) than seed 42 (9.6 px, ~0 px), so per-clip QA gates are required.

## Decision (provisional)
Adopt approach 3 as the working design:
- **generate** stage produces a *pool* of N independent clips from one keyframe; each clip is its own fingerprinted artifact, so one bad clip is regenerated alone and adding clips never invalidates others.
- **validate** rejects clips that drift/shift too far from the keyframe (camera shift, luma trend, identity diff) — per-clip gate.
- **assemble** (revised after human review): each accepted clip becomes a **leg** = clip forward then reversed, luma-normalised, encoded once as a closed-GOP file; legs are scheduled pseudo-randomly and concatenated by stream copy. Every leg starts and ends on the keyframe-state frame, so any leg can follow any other with no blending. (Original text was 'cross-dissolves at the joins' — rejected by human review.)
- Final tier = enhance each *accepted* clip (interpolate 16→24/30 fps, upscale, deflicker), then assemble. Dissolves are done after enhancement.

## Human verdict (2026-09-21, on `SAMPLE_dissolve_pool_848x480.mp4`)
Mostly good, but the stitch shows where one clip fades into the next: the castle morphs oddly, and the fades between clips look bad.

**Diagnosis (measured):** the sample alternated seeds 42 and 7. Seed 7's castle drifts structurally within its own 5 s (start-vs-end castle-body edge mismatch 0.92 vs 0.25 for seed 42; the zoomed comparison shows shifted/zoomed castle, changed spire and balcony). Every B→A join dissolved seed 7's drifted castle into a fresh one, which reads as morphing. My acceptance metric (pixel change per tile) could not see this; it only looked at the mild A→B join and at a contact sheet too small to show it. **Lessons:** (1) the metric for any blend must be structural (edge-map mismatch on the castle body), not pixel difference; (2) a dissolve is only safe when both blended states are structurally near-identical, i.e. the *outgoing clip must not have drifted*; (3) clip quality is very seed-dependent (1 of 2 usable), so generation yield and a per-clip structural gate are first-class.

**Second human verdict** (same day, on `SAMPLE_hub_pingpong_A_848x480.mp4`, one good clip played fwd/rev ×3, no blending): **looks good.** Interpreted as accepting the ping-pong mechanism itself (no dissolve, reversed motion at turnarounds). Provisional: single clip, one viewing, small-screen display.

**Assembly mechanics verified:** legs (fwd+rev, one closed-GOP file per accepted clip, luma normalised) concatenate by pure stream copy: 5 legs, 524 packets, 32.75 s exact, 0 irregular timestamps, clean decode (`research/long-form-assembly.md`). Long-form output is zero-re-encode again.

**Yield problem (measured on 6 seeds, corrected):** the reliable signal for "is this clip usable" turned out to be **camera drift by end-of-clip**, not the early structural-gate trip that first flagged seeds — the gate fired at frame ~9–12 while measured camera shift was still <1 px at that point; the real drift (2–8 px) only appears by the end of the clip. By that measure: **2 of 6 seeds (42, 104) hold a locked camera for the full 5 s; 4 of 6 (7, 101, 102, 103) drift 4.7–8.3 px.** Cost per usable clip ≈ 3×. The structural gate as first coded is not yet trustworthy alone; a camera-shift check must be added before it is used for real accept/reject decisions (R7). See `research/local-video-baseline.md` for the full table.

## Tradeoffs
- Assembly is no longer a pure stream copy: dissolve regions must be re-encoded (bodies can still be stream-copied only if encoder parameters/GOPs match — untested; otherwise re-encode everything, ≈ realtime on CPU at 4K10).
- Clips restart from the keyframe state every ~5 s: slow global changes (moonlight shifting, weather) cannot emerge from the generation itself and would have to be applied at assemble time (grade/light modulation).
- Every clip repeats the same *structure*; only motion varies. Suits calm ambient scenes (the target) but limits scenes needing evolving state.
- Pool size vs perceptual repetition is unmeasured.

## Consequences
`ARCHITECTURE.md` stages: `generate` = clip pool, `assemble` = scheduler + dissolver. Invalidation is naturally per clip. The "generated closure" and "SVI chain" work items are demoted to optional experiments.

## Revisit when
A human watching 10+ minutes of several distinct legs sees repetition, reversed-motion artifacts, or turnaround pops as objectionable; or the corrected per-clip gate (R7) shows yield too low to be practical; or a closure/chaining method appears that measures clean.
