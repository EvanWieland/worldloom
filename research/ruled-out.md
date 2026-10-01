# Ruled-out registry (evidence, scope, reopening condition)

Handoff 2026-09-27 §16: a failure is scoped to the method, model and scene it was measured on. Do not rerun anything
here because this list exists; reopen an entry only when its reopening condition holds (a changed causal assumption or
an untested capability a current requirement needs). Confidence: high = repeated / user-judged, medium = one scene or
metrics only.

| method | scope (model, scene, settings) | failure | evidence | conf. | reopen when |
|---|---|---|---|---|---|
| flf2v bridges (first+last frame) | Wan 2.2 flf2v 720p, castle, 33-81 f | eases into the target and freezes; blocky sky off-native; 81 f infeasible locally | local-video-baseline.md | high | a flf2v model with native 480p support or offsite 720p budget |
| circular generation | Wan T2V spikes, castle | seam 9-15x, motion 1/3-1/10 of chain | loop-direction.md | medium | an I2V circular method at > 5 s is released |
| LTX frame injection (pixel frames as conditioning) | LTX-2.5 distilled | loses fine motion vs true latents | loop-transition.md, particle-loop-closure.md | high | never on this model; re-test on a new model family |
| inpainting IC-LoRA closure | LTX-2.5, rain cabin | seam / masked region re-synthesises | loop-transition.md | medium | a closure need the true-latent route cannot meet |
| whole-loop RePaint | LTX-2.5 | drift of the whole loop | loop-transition.md | medium | as above |
| VACE closure for particle scenes | Wan Fun VACE 16 fps, rain cabin | drip stall + snap (Review E) | loop-transition.md, particle-loop-closure.md | high (particles only) | a non-particle scene where LTX closure fails; waterfall passed with VACE |
| retiming a snap | ADR 0006 recipe | snap stays visible | particle-loop-closure.md | medium | — |
| returning into the first ~2 s of a take | LTX takes | closes into the I2V settling (frame 9) -> snap | particle-loop-closure.md | high | a model without an I2V settling transient |
| cross-seed cycles, chained continuations, longer extension context | LTX-2.5 extensions | drift compounds per hop | particle-loop-closure.md | high | a model with a longer native window |
| crossovers (blending two renders) | LTX, rain | not generated closure (invariant 10); user preferred generated in blind review | particle-loop-closure.md, ADR 0007 | high | only inside ADR 0006/0009 same-instant overlaps |
| negative prompts against flare | LTX-2.5 distilled | the distilled recipe ignores negatives | furnace-scene.md | high (distilled) | the Dev / CFG model becomes the recipe |
| flare / light wording in the motion prompt | LTX-2.5, furnace | light drifts 4.7-5.7 grey, no visible flare | furnace-scene.md | medium | a lighting-capable recipe is under test (brilliance) |
| canny vs depth for the gear | LTX union IC-LoRA, furnace wheel | no better rotation | furnace-scene.md | medium | a periodic reference-guidance experiment (handoff §13) |
| 48 f wheel gap | LTX closure, furnace | not rerun; gap-motion warning dropped | plan-2026-09-26.md | low | — |
| Qwen Image Edit; Kontext edits of the user's still | image editors, furnace still | broken / unnatural; shaft added | furnace-scene.md | medium | never silently recompose a user's still (handoff §4) |
| seekable GOPs (periodic keyframes) | x264 delivery | 2.1-2.8x step every I-frame | long-form-assembly.md | high | a concrete delivery requirement (handoff §15) |
| track-guided embers on a still without embers | LTX motion-track IC-LoRA | tracks move existing content only | scene-perfection-round2.md | high | a still that already contains embers |
| local-VLM subject veto | qwen3.6 vision | invented a fire, missed a missing waterfall | scene-perfection-round2.md | medium | a VLM that passes a calibration set (advisory only, handoff §10) |
| motion-aware pair ranking | endpoint pairs, furnace | no better than luma | scene-perfection-round2.md | medium | not to be retried (handoff §10) |
| masked ocean depth guide | LTX union depth, lighthouse | stopped by the user before any render (masking ruled out) | scene-perfection-round2.md §9 | user decision | never for synthesis; crops for MEASUREMENT stay allowed |
| NAD diffusion decoder | LTX-2.5 distilled 832x480, lighthouse, seed 306 | darker, half the sharpness | video-models-2026-09.md, bake-off | medium (one recipe) | a recipe the NAD decoder is documented for |
