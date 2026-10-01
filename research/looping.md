# Looping & non-repetition (R5) — 2026-09-21

**Evidence level: desk research + reasoning. No technique below has been tested by us yet.**

Three distinct problems (from the brief): **M** mathematically seamless (state at t=L equals state at t=0), **V** visually seamless (no visible artifact/velocity jump at the join), **P** perceptually non-repetitive (viewer can't spot the cycle).

## Techniques and which problem they address

| Technique | M | V | P | Notes |
|---|---|---|---|---|
| Integer-harmonic motion: every periodic term has frequency k/L | ✔ | ✔ | – | Works for sway, bobbing, flicker envelopes, light drift |
| Periodic noise: sample N-D noise along a circle (`noise(x, y, r·cos 2πt/L, r·sin 2πt/L)`) | ✔ | ✔ | – | Standard for clouds/fog/wind fields; radius controls "speed" |
| Flow-field advection with two phase-offset layers cross-faded (flow-map trick) | ✔ | ✔ | – | Water shimmer, cloud drift over a still; keeps warp distortion bounded |
| Tiling translation: scroll a horizontally tileable layer by an integer number of tiles per L | ✔ | ✔ | – | Cloud decks, fog banks |
| Wrapping particles: lifetimes and spawn times modulo L, pre-rolled | ✔ | ✔ | – | Dust, insects, spray, smoke sprites |
| Baked-sim cache blend (overlap last N frames onto first N) | ~ | ✔ | – | Blender smoke/cloth; hides rather than removes the seam |
| Crossfade of video ends | ✗ | ~ | – | Ghosting on structured motion; last resort |
| Generative circular time (Loopy RoPE shift; Mobius latent shift) | ~ | ✔ | – | Loop is learned, not guaranteed → must be validated; short (≈53 frames) |
| Generative bridge (VACE: last 15 + gap + first 15) | ~ | ✔ | – | Any clip → loop; bridge quality varies |
| First = last frame conditioning (FLF2V, DreamLoop) | ✔(frame) | ~ | – | Identical frame ≠ matching velocity; "static collapse" risk |
| **Coprime per-layer periods**, composited | ✔ | ✔ | ✔ | Layers with periods e.g. 37 s, 53 s, 71 s, 97 s → composite repeats only at the LCM (≈ 156 days). Each layer still loops exactly. |
| Loop families with identical boundary state, scheduled pseudo-randomly | ✔ | ✔ | ✔ | Needs boundary state (pose *and* velocity) shared; costs N× renders |
| Slow global modulation (grade, moon position, light level) with a very long period | ✔ | ✔ | ✔ | Cheap; applied at composite time; breaks exact-frame recurrence |
| Avoid salient one-off events ("outliers") inside a loop | – | – | ✔ | A single bird crossing every 20 s is what viewers notice. Put distinctive events on their own long-period layer or omit |

Prior art supports the last row: ambient-video patent literature notes ~30 s+ segments and absence of outlier events as what defeats repetition perception; Microsoft's "video looping with progressive dynamism" uses **per-pixel loop periods**, i.e. the same idea as per-layer periods.

## Measured results (2026-09-21, local-video-baseline.md)

| Technique | Measured seam ratio (1 = normal motion) | Verdict |
|---|---|---|
| First = last frame (Wan 2.2 14B I2V) | 28 | fails; motion collapse |
| SVI 2 Pro chain + end anchor | 40 | fails; drift, push-in |
| **Cross-dissolve of keyframe-anchored clips** (self-loop or join) | **1.7–2.2** | works on metrics; human test pending (ADR 0004) |

## Applicability after ADR 0003

The project uses generative video as backbone. Rows about procedural layers (harmonics, periodic noise, flow warps, particles, coprime layers) are **not the plan**; relevant rows are the generative ones (circular time, VACE bridge, first=last), loop families, and avoiding salient one-off events. Non-repetition comes from **long chained loops** (minutes) — see `video-route.md`.

## (layered-route only) The important consequence

Coprime layers make the *composite* non-periodic over hours, so the long-form video cannot be a stream-copied single loop. But in a layered pipeline the composite is cheap (2-D GPU compositing, near real-time), so **hours of unique composite frames are affordable as long as the expensive work is per-layer loops rendered once**. Cost moves to encoding + file size (see `long-form-assembly.md`). Both assembly strategies should exist:

- **S1 single master loop + stream copy** — zero cost, tiny effort; repetition period = L. Good for previews and for scenes where L can be long.
- **S2 live composite of coprime-period layer loops → encoder** — perceptually non-repeating; cost ≈ real-time encode of full duration.

This only works if layers are truly independent (a cloud layer's shadow on the ground couples two layers → they must share a period or the coupling must be applied at composite time). The plan stage must record couplings.

## Open questions → experiments

1. How short can per-layer periods be before repetition is noticed, per motion type? (clouds vs water shimmer vs flicker). Needs human viewing tests.
2. Does flow-map warping hold up at 4K on generated stills, or does it read as "jelly"?
3. Generative patches: is a learned loop (Loopy) good enough to pass our objective seam check, or do we always need VACE-style closure + validation?
4. Coupled layers (reflections of animated lights in animated water): composite-time coupling vs shared period.

## Sources

- Loopy https://www.alphaxiv.org/abs/2608.23090 · Mobius https://arxiv.org/pdf/2502.20307 · DreamLoop https://arxiv.org/abs/2601.02646
- VACE loop closure https://openart.ai/workflows/nomadoor/loop-anything-with-wan21-vace/qz02Zb3yrF11GKYi6vdu
- Progressive dynamism / per-pixel periods (patent) https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9547927
- Continuous-loop ambient display (patent) https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9633692
- Blender looping guide https://www.blendernation.com/2024/08/08/the-ultimate-guide-to-seamless-looping-animations-in-blender-4-2/
