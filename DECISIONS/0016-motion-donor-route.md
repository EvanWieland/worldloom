# 0016 — Motion donor: another model renders the motion, LTX renders the picture and the closure
Status: accepted 2026-09-30 (proposed the same day and approved for building; the second scene passed: sample_1b,
hands-off from the user's own still + prompt, Review 5: joins and scene passed)
Date: 2026-09-30

## Problem

LTX-2.5 keeps large deformable shapes (cloth) in the still's pose; prompts, guidance, source strength, a weaker
held depth guide and attention kernels do not reshape it (`research/model-bakeoff-2026-09.md`,
`research/ltx-cloak-screen.md`). Hunyuan 1.5 moves cloth well but cannot close a loop in WanGP (no end-frame input;
5 s windows chained on ONE frame jump every 5 s; its look drifts) — its pictures are not loop material (reviewer on the
480p cross-model loop: looks like dated CGI). The user wants LTX's picture and loops with that cloth
motion, run hands-off by the pipeline on any scene.

## Considered approaches

1. More LTX levers (dev + CFG, STG, keyframes, a trained cloth LoRA): tested ones fail or are partial (dev CFG 5:
   5.7 pts vs Hunyuan 9.6); a LoRA is a rented research project (report §4).
2. Hunyuan pictures + an LTX closure (cross-model loop): seam clean, but drift 30 grey, window pops, style shift —
   rejected by the user.
3. **Motion donor (chosen):** Hunyuan renders the scene's motion from the still; its video, converted to depth by
   WanGP, is the moving full-frame guide of an LTX single-stage take, and a Hunyuan continuation from the loop's
   end guides the LTX return. LTX renders every pixel and closes the loop from its own latents.

## Evidence

`research/ltx-cloak-screen.md`: moving guide + single stage = 12.0 pts cloak excursion as solid cloth (probe; two
stages: smoky fill; held still: 3.3); a 20 s guided take keeps the cloak moving throughout (10.2 pts; the donor's
drift and window pops do not transfer); with a held-still return the cloak freezes (loop_qc c20.low on 3 seeds);
with a continuation-guided return the 27 s loop passes loop_qc with no flags. Review verdict: joins
invisible, the cloak slightly too fast, otherwise the scene passed -> `--donor-speed`.
**Second scene (sample_1b, the user's still + prompt, no hand steps; `research/ltx-cloak-screen.md`):** 30 s loop,
loop_qc PASS with no flags (closing 0.98, joins 1.23x vs the loop's own worst 1.26x), cloak billowing through body
and return; reviewer: joins and scene passed (then asked for the whole scene slower: donor speed 0.3 chosen
from native test renders; a RIFE retime of the finished loop was rejected for distortion and patterns).
Limits seen on the way: a still's thin rod at the hip became a sword-like stick in every take (the still was the
cause, not the donor: smoothing the guide's depth and a prompt sentence changed nothing; the user replaced the
still), and the take's light can ramp per seed (the guide amplifies LTX's own drift where the donor darkens).

## Decision

`looper loop ... --motion-donor [--donor-speed S]` (S in (0, 1], default 1; the spice cloak wanted 0.6):
- `donor[take]`: Hunyuan 1.5 480p step-distilled (local, `adapters/hunyuan.py`) renders the still, long enough
  for a take at speed S; `fit_guide` retimes it (guide frame k = donor frame S*k, motion-interpolated), frames it
  exactly like the fitted keyframe and trims it to the take; the take renders single-stage (implied) from it.
- the long-return cut as today (`loopkit.calmest_segment`); then `donor_start` (the donor frame at the loop's
  last body frame, round((e - 1) * S)), `donor[return]` (Hunyuan continuation from it), `fit_guide[return]`;
- `return_guide`: take guide [e-E:e] + continuation [1:G+1] + take guide [s:s+S]; G is chosen among the target
  gap and up to 64 frames less (loop up to 2.7 s under the target) by a whole-frame match of the continuation
  against the loop's first 8 frames: mean |difference| of tone-normalised grey, weighted by where the take itself
  moves (derived automatically, no regions; replayed on the spice donor it picks the cut the user passed, where an
  unweighted match scored every gap 0.92-0.93);
- every close seed renders with that guide; splice / loop_qc / deliver / review / 4K gate unchanged; `grow` is
  skipped (an unguided interior bridge would freeze the motion again).
`--take-guide VIDEO` supplies the donor video instead of rendering one (bring your own donor).

Checklist (prompt.txt): 1 quality — the first LTX loop with moving cloth the user loved; 2 iteration — donor
renders are cached stages, a speed change reruns only guides onward; 3 rerun — every step is a fingerprinted
stage; 4 persisted — donor videos, fitted guides, the return guide and its match scores; 5 replaceable — the donor
is one adapter + any video via `--take-guide`; 6 observable — stages emit events, the review shows the donor
speed and wrap score; 7 diagnose — processed guides kept, `trace` / review as usual; 8 laptop — 480p donor ~10 min
per 5 s, the route adds ~45-60 min per run; 9 scale — the same stages run on a rented GPU; 10 demonstrated —
built on a loop the user approved, not on a hypothesis.

## Tradeoffs

- Transfers SHAPE motion only (cloth, hair, flags, maybe waves): depth carries no light (embers, glints, beams).
- Single stage is required (two stages under-resolve the guide) and thickens haze on this scene.
- Hunyuan is a second model dependency (non-commercial licence: acceptable, CLAUDE.md invariant 13); a subject
  that walks in the donor walks in the take.
- The wrap match is a heuristic; the loop length flexes (target - 64 .. target frames).

## Consequences

New stages `donor`, `donor_hold`, `donor_start`, `return_guide` (`looper/stages/donor.py`), adapters
`looper/adapters/hunyuan.py` and `looper/adapters/pose.py`; every donor (take and return) is checked for a
subject that travels (torso keypoints, net > 1 % of the width) and re-rolled up to 3 seeds (2026-10-01: sample_2
seed 306 stepped, the spice brief's traveler walked);
`keyframe.fit_video` gains speed + frame count; `close` takes an optional guide (`ltx.control`); CLI
`--motion-donor`, `--donor-speed`. Existing runs keep their fingerprints (all new keys only when the route is on).

## Revisit when

A second scene fails with the route; a native LTX cloth fix appears (LoRA, low-pass guidance); a donor model
gains end-frame conditioning (its own closure); or the wrap match picks a visibly wrong cut.
