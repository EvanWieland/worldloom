# 0006 — Loop closure: 16 fps Wan Fun VACE with context both sides + in-overlap splice ramp
Status: accepted (review verdict on Review D, 2026-09-24: no transition perceptible at all, scene passed)
Date: 2026-09-24

## Problem
Every closure before this left a visible transition: flf2v bridges freeze, circular generation loses motion, LTX frame injection / inpainting leave hard jumps, and the 24 fps VACE gap ran ~16 % fast with a one-frame "kick" at each splice. Invariant 10 requires closure to be *generated*, not blended.

## Considered approaches
flf2v bridge + retime (freeze), circular ring generation (motion loss), LTX KFI self-close / inpainting IC-LoRA (hard mask-edge jumps), LTX soft temporal RePaint of the whole loop (reviewer: scene bleed), bigger models (don't address the join between two generators). Evidence for all of these is in `research/loop-direction.md`, `research/model-options.md` and `research/loop-transition.md`.

## Evidence
`research/loop-transition.md` § Results. Waterfall loop, LTX-2.5 clip:
- 16 fps context cut the gap speed error from +16 % to ~+4 %.
- Writer fixes: 4:4:4 intermediates, `mbtree=0`.
- 10-frame ramp inside the context overlap: review-file joins 2.5 / 3.1× → 1.2 / 1.8× median step.
- Reviewer: A (16 fps VACE) almost imperceptible; D (A + fixes + ramp) no transition perceptible at all.

## Decision
The closure recipe for a clip C (any source model):
1. RIFE ×2 the clip, then sample **exact 16 fps** context: 33 end frames + 33-frame grey gap + 31 start frames = 97 f (Wan's 4k+1).
2. Wan 2.2 Fun VACE (`video_prompt_type "VA"`, the clip's prompt, Lightning 4-step, NAG 9), then RIFE ×3 and every 2nd frame back to 24 fps.
3. `best_splice` (cut where the re-render matches the real frame best), then `match_gap --stabilise` (tone/sharpness/smoothed drift).
4. `splice_ramp`, N = 10: at each splice, ramp from the real frame to VACE's re-render **of the same instant**, only inside the context overlap, with a sharpness restore per mixed frame.
5. Every intermediate encode is 4:4:4 with `mbtree=0`; the delivery/review encode is 4:2:0 with `mbtree=0`.

**Invariant 10, clarified:** the closure (the new frames in the gap) must still be generated. Step 4 does not replace any content with a mix of *different* moments; it hides the render-to-render difference of one moment across a few frames. Cross-dissolving different content stays rejected (ADR 0004).

## Tradeoffs
- Two models in one loop (clip model + Wan VACE). The gap keeps VACE's texture (slightly more painterly water), which the eye accepted here.
- RIFE-interpolated frames make up ⅔ of the gap. Fast fine particles (rain) may show it; untested.
- One scene (waterfall) so far.

## Consequences
- Phase C `bridge` stage implements this recipe, not flf2v. The engine's video writer must use 4:4:4 + `mbtree=0` for intermediates.
- `loop_qc.py` join ratios: D passes at 1.2 / 1.8×; the ≤ 2× join target stands for the 4:2:0 review encode.

## Revisit when
A second scene (rain cabin, then the benchmark set) fails with this recipe, or the clip model changes its native fps.
