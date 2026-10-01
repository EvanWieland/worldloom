# Model bake-off on the spice desert still (2026-09-29, handoff §11.2 screen)

**Question:** is there a video model that beats the pipeline's LTX-2.5 distilled on this machine, on a scene rated
flawless in review? **Status:** screen (1 seed) done for 5 of 6 arms; Kandinsky 5 Pro running; finalists not run.

## Setup

`experiments/models/bakeoff.py spice_desert` — the user's still center-cropped to 16:9 at full res
(`runs/inputs/spice_desert_16x9.png`), the director's motion prompt for the scene (`runs/inputs/spice_desert_motion.txt`)
+ the steady-light clause, the director's negative, seed 306, 5 s, each arm at its documented recipe and native size.
LTX arms carry the pipeline's depth lock (camera); the other families have no camera guide (their own recipe).
Outputs `runs/models/spice_desert/` (clips, `measures.json`, `sbs_s306.mp4`).

## Results (seed 306)

| arm | size / fps | minutes | camera px | region drift | flecks kept (last s / first s) | eye |
|---|---|---|---|---|---|---|
| ltx_480 (pipeline default) | 832x448 / 24 | 4.6 | 0.46 | 4.11 | 1.84* | holds the scene |
| ltx_720 (distilled 8 step) | 1280x704 / 24 | 5.0 | 0.01 | 1.62 | 0.94 | steadiest; spice and dust alive; figure barely moves |
| ltx_dev_720 (40 step, CFG 3) | 1280x704 / 24 | 14.9 | 0.12 | 2.76 | 1.06 | ~ distilled 720; RAM peak 63.4 / 64 GiB |
| hy15_720 (50 step) | 1280x720 / 24 | 234.3 | 0.13 | 4.20 | 0.71 | traveler actually walks, cloak moves; spice sparkle fades to plain haze |
| wan22_lightning (4 step) | 848x480 / 16 | 7.3 | 37.3 | 6.91 | 2.03* | FAIL: zooms, rewrites dunes, spice field vanishes |
| k5_pro (50 step) | 1280x720 / 24 | running | | | | |

\* fleck count (`experiments/models/clipmetrics.py`: white top-hat > 40 at 1280x720, connected components) also counts
sharp ground texture: a rise means the scene changed, not more spice. Diagnostic only.

## Reading (provisional until the user watches `sbs_s306.mp4`)

- LTX 720 distilled is the best quality per minute by far: steadier than 480 and ~the same time (confirms the
  2026-09-27 lighthouse bake-off). Dev adds 3x time for no visible gain here.
- Hunyuan 1.5 is the only arm with a convincingly walking figure, but it loses the still's brilliance (user taste:
  brilliance matters) and costs 47x LTX 720 -- a 30 s loop would be a day+ locally: offsite-only if the user prefers
  its motion.
- Wan 2.2 Lightning without a camera guide is out.
- Not run: Wan 2.2 A14B full (native 720p 14B infeasible locally, L1c), hy15 30-step variant.

## Review verdicts (2026-09-29 walkthrough)

- **Review 1, screen (sbs_s306):** every arm except wan22_lightning looks good; wan22_lightning has excessive,
  unmotivated animation and wrong-looking physics. Hunyuan's cloth animation on the figure is liked, but a figure
  walking away cannot loop; cloth motion without the walk is wanted. -> Hunyuan's walk (which I had counted in its
  favour) is a loop defect: a subject's net locomotion cannot close. What the user wants is Hunyuan-grade cloth
  motion on a figure that holds position.
- **Review 2, Hunyuan H100 x3 + LTX 720 (sbs_hunyuan_h100):** cloak / robe motion, Hunyuan vs LTX: **Hunyuan clearly
  better**.
- **Review 3, same seed laptop sage2 vs H100 exact (sbs_parity_s306):** **the right looks better: the left has odd
  clumps of sand/spice flying by; the right keeps them particle-sized.** -> sage2's quantized attention visibly
  degrades fine particles (clumps) on Hunyuan; the eye agrees with the fleck / drift numbers.
  Open: does the same hold for LTX (queued: ltx_720 sdpa seeds 306-308)? If yes, the pipeline's attention default is
  a quality lever (it is sage2 everywhere today).
- **Review 4, spice_desert 4K 1:1 crop:** approved, looks good (also recorded as a `verdict` event on the run).
- **Review 5, finals on the original prompt (same H100, sdpa):** Hunyuan 306 preferred because it also animates the
  background sand; otherwise little difference in quality; LTX has more chunky floating spice/sand, but acceptable.
  -> quality is close; LTX's chunky particles persist with exact attention, so the clumping is partly LTX itself,
  not only sage2.
- **Review 6, finals on the stand-still prompt:** no decision yet; the cloak may be too distracting in an ambient
  scene; how well it would loop is unknown (if poorly, LTX may be best); Hunyuan's sand-cloud movement further out
  in the scene is liked. -> undecided; the deciding question is Hunyuan loopability (unproven: every closure recipe
  we have is LTX-specific), plus a calmer cloak for an ambient scene.

## Like-for-like finals: both models on the same H100, exact attention (sdpa), 3 seeds each (2026-09-29)

Second pod (`hy15_still`, H100 SXM, $3.49/h, 111 min, ~$6.46): Hunyuan stand-still x3, then (`runpod.py more`)
LTX 720 x3 on the original prompt (`runs/models/spice_desert_sdpa/`) and x3 stand-still (`runs/models/spice_desert_still/`).
Stand-still = the director prompt with the traveler clause replaced by "stands in one place with feet planted,
leaning into the wind; the heavy cloak and robe whip and billow sideways in the gusts while the figure stays exactly
where it is" + "walking, walking away, footsteps" in the negative (a probe, not a pipeline change).

| clip (H100, sdpa) | minutes | flecks kept | camera px | drift | traveler |
|---|---|---|---|---|---|
| hy15 original s306 / s307 / s308 | 21.1 / 18.6 / 18.6 | 1.03 / 0.87 / 0.75 | 0.22 / 1.14 / 0.07 | 1.1 / 1.3 / 2.86 | walks off (all) |
| ltx original s306 / s307 / s308 | 3.7 / ~2 / ~2 | 1.25 / 1.02 / 2.06 | 0.09 / 0.16 / 0.06 | 6.85 / 2.25 / 7.24 | holds, cloak sways |
| hy15 stand-still s306 / s307 / s308 | 28.7 / ~20 / ~20 | 1.23 / 0.85 / 0.96 | 0.1 / 0.53 / 0.74 | 5.2 / 2.51 / 4.35 | holds, cloak whips wide |
| ltx stand-still s306 / s307 / s308 | ~3 / ~2 / ~2 | 1.23 / 1.06 / 1.82 | 0.09 / 0.07 / 0.07 | 7.42 / 1.36 / 7.31 | holds, cloak sways |

- The stand-still clause works on Hunyuan on every seed (position held, big cloth motion); LTX barely reacts to it.
- **LTX with sdpa builds haze** on 2 of 3 seeds (drift ~7 vs 1.62 with sage2 locally on s306): exact attention is
  not a free win for LTX the way it is for Hunyuan. Hypothesis until the user compares.
- Hunyuan's big foreground bokeh from the still disappears after ~1 s on every seed (midground spice stays).
- Pod lessons: apt ffmpeg 4.4 lacks `-fps_mode` (WanGP control-video decode) -> static ffmpeg 7 pinned in
  `Wan2GP/ffmpeg_bins/`; an ssh poll can fail transiently (follow treats it as no information).
- Estimated spend for both pods: $3.96 + $6.46 (RunPod's bill is authoritative).
- Review grids: `runs/models/spice_desert_sdpa/review_original_prompt.mp4`,
  `runs/models/spice_desert_still/review_stand_still.mp4` (top row Hunyuan, bottom LTX, seeds 306-308).

## Finalists: LTX 720 vs Hunyuan 1.5 720p (user pick 2026-09-29)

Hunyuan seeds on a rented H100 80GB SXM (RunPod, ADR 0014; `experiments/cloud/`), WanGP 59e55609, torch 2.10 cu130,
same settings; attention **sdpa** (exact) instead of the laptop's sage2, memory profile 1.

**Parity (seed 306, same settings on both machines):** H100 21.1 min vs laptop 234.3 min. Same behaviour (traveler
walks right, dust builds), different details (cloak billow, stride): not pixel-identical, as expected across
attention kernels and GPUs. But the exact-attention run holds the scene better on this seed: flecks kept 1.03 vs
0.71, region drift 1.1 vs 4.2 (camera 0.22 vs 0.13 px). **Hypothesis:** sage2's quantized attention costs Hunyuan
some sparkle / stability; seeds 307 / 308 test it. Fairness follow-up queued: LTX 720 seeds 306-308 with sdpa on the
laptop (`runs/models/spice_desert_sdpa/`), so the final compares like with like.

**All three H100 seeds** (clips in `runs/models/spice_desert_sdpa/`, pod log `runs/cloud/hy15_final/results/`):

| clip | minutes | flecks kept | camera px | region drift |
|---|---|---|---|---|
| hy15 s306 (H100, sdpa) | 21.1 | 1.03 | 0.22 | 1.1 |
| hy15 s307 (H100, sdpa) | 18.6 | 0.87 | 1.14 | 1.3 |
| hy15 s308 (H100, sdpa) | 18.6 | 0.75 | 0.07 | 2.86 |
| hy15 s306 (laptop, sage2) | 234.3 | 0.71 | 0.13 | 4.2 |
| ltx_720 s306 (laptop, sage2) | 5.0 | 0.94 | 0.01 | 1.62 |

Exact-attention Hunyuan drifts less than the laptop's sage2 run on every seed (1.1-2.9 vs 4.2); fleck retention
varies by seed (0.75-1.03), so the sage2 sparkle loss is only partly the kernel. Every seed has a real walk.
H100 run: profile 1, 16.4 GB VRAM, RAM peak 124 GiB (host RAM, fine there), ~685 W.
**Cost:** 68 min of pod time (5.3 min boot, 1.8 min setup, 3 renders, idle until pulled), ~$3.96 at
$3.49/h (RunPod's bill is authoritative). Side-by-side: `runs/models/spice_desert_sdpa/sbs_hunyuan_h100.mp4`.

## Hunyuan loopability: cross-model seam test (2026-09-29, requested: a Hunyuan loop test)

`experiments/models/crossclose.py`: the pipeline's own closure (close-stage layout E 49 | G 32 | S 64, ltx.hooks
context, splice stage with 8-frame same-instant ramps) on a clip from any model; the contexts are the clip's frames
re-encoded by LTX's VAE (no true latents exist for a Hunyuan clip). Laptop, LTX 1280x704 sdpa, ~10-12 min each.
Loop = clip[49:121] + 32 LTX frames = 104 f (4.33 s): the LTX gap is 31 % of the loop (harsh vs ~4 % in a 30 s loop).

| loop | into LTX gap | wrap | clip's own worst step |
|---|---|---|---|
| Hunyuan stand-still s306 | 1.41 | 1.03 | 2.64 |
| Hunyuan stand-still s307 | 1.79 | 1.12 | 3.04 |
| Hunyuan stand-still s308 | 1.22 | 0.94 | 2.17 |
| LTX stand-still s306 (control) | 1.37 | 0.91 | 1.87 |

Both joins sit inside each clip's own motion on every seed, Hunyuan as clean as the LTX control by this measure; stills
at the joins show no shape/colour break. Not measurable here: a change of motion STYLE inside the 1.3 s LTX section
(cloak behaviour) -> the user's eye decides (`runs/models/spice_desert_still/review_loops.mp4`, joins at 3.0 / 4.33 s
and every 4.33 s after).

**Review 7: every scene freezes briefly** -- the LTX control too. Cause (measured): every 5 s I2V clip,
Hunyuan and LTX alike, decelerates over its last ~16-24 frames (whole-frame motion 0.54-0.79x of its median, cloak
region 0.57-0.83x); the test loops ran each clip to its last frame, so the slowdown sat right before the LTX gap, which
then moves again (gap motion 0.88-1.13x of the body). A test-design flaw, not a Hunyuan result: the pipeline never ends
a loop on a clip's last frames (long takes, endpoint cuts). Retest queued: the same closures with the body ending at
frame 97 (`--end 97`, `loops_end97/`): Hunyuan s306 / s308, the calmer cloak, the LTX control.

Tail-cut result (s306, `--end 97`): the body now moves evenly up to the gap (0.96-1.13x), and the remaining dip is
INSIDE the LTX gap (0.67-0.70x in its middle, 0.80x overall): the classic short-bridge ease, stronger here because the
contexts are re-encoded (the pipeline avoids it with true latents + long returns, neither available for a Hunyuan
clip -- a long LTX return would make seconds of the loop LTX footage). A frame-selection retime of the gap
(`experiments/models/retime_gap.py`; no blending; counts as generated closure, ADR 0005 A1) lifts the mid-gap dip to
0.79-0.86x (32 -> 27 frames): milder, not gone (its mean-|diff| motion proxy is dominated by dust flicker; an
optical-flow retime would be the proper version).

**Review 9 (tail-cut + retimed loops, all four incl. the LTX control): every transition is poor: motion runs well,
slows at the transition, the scene reverses slightly, then recovers; suspected cause: too few context frames for the
transition.** -> Diagnosis: the 5 s clips are
the limit, not the context size (E 49 + S 64 frames): after dropping the settling and the tail, the loop's end and
start are ~2 s apart, so the closure must bring the drifting dust / cloak back to a state 2 s earlier within ~1 s --
slowing and reversing is the only way (the old Phase A "bridge sweeps it back" failure). The pipeline's proven LTX
loops avoid it with a 20 s take and a ~13 s long return (ADR 0012). A fair Hunyuan loop test therefore needs a long
Hunyuan take (continuation windows, ~20-30 min per 5 s on an H100) plus a long cross-model return -- where much of
the loop would be LTX footage. Short-clip closures are not a valid loopability test for ANY model.

## Can LTX animate the cloak? (user 2026-09-29; laptop, sage2, stand-still prompt, seed 306)

Measure (`experiments/models/cloak.py`, blind to bright particles): the dark traveler + cloak silhouette in the lower-left box;
change = 1 - IoU of its mask 4 frames apart; area range = how far the cloak flares.

| clip | silhouette change | area | camera |
|---|---|---|---|
| LTX 720 (pipeline today) | 0.184 | 5.0-8.5 % | 0.22 px |
| LTX 720, depth guide 0.5 | 0.232 | 4.7-9.6 % | 0.22 px |
| LTX 720, depth guide 0.25 | 0.327 | 1.7-10.9 % | 0.72 px |
| LTX dev 720 (40 steps, CFG 3; 15.3 min, RAM peak 63.7 / 64 GiB) | 0.065 | 6.9-9.6 % | 0.22 px |
| Hunyuan stand-still (H100) | 0.106 | 8.5-24.1 % | 0.10 px |
| Kandinsky (H100, original prompt) | 0.101 | 7.4-10.8 % | 4.45 px |

**No, not with these levers:** every LTX variant keeps the cloak's shape from the still (crops at 0 / 1.7 / 3.3 / 5 s
show the same silhouette): distilled jitters at the edges, a weaker depth guide adds jitter and loosens the camera
(0.25: 0.72 px), dev is smoother but just as still. The held depth guide is NOT what pins the cloak. Only Hunyuan and
Kandinsky make large coherent cloth sweeps. Extends the hard-won rule (brilliance / drum veil / embers): LTX moves
particles and light within the still's shapes; it does not re-shape large cloth. Untried and ruled out by the user's
no-masking rule: motion-track guidance on the cloak. Review: `runs/models/spice_desert_cloak/review_cloak.mp4`.

**Follow-up (requested: any way to make LTX move the cloak):** a cloth-first prompt
(`runs/inputs/spice_desert_motion_cloth.txt`: the cloak's gust cycle described step by step, the director's stability
clauses removed) -> `runs/models/spice_desert_cloth/`:

| clip | silhouette change | area | camera |
|---|---|---|---|
| LTX 720 distilled, cloth prompt | 0.176 | 5.4-8.7 % | 0.19 px |
| LTX dev 720, CFG 5, cloth prompt (15.3 min, RAM peak 63.5 / 64 GiB) | 0.123 | 6.4-12.1 % | 0.13 px |

Distilled LTX ignores the cloth wording entirely (the stability wording was not the cause). Dev + CFG 5 + the cloth
prompt is the first LTX setting that moves the cloak: it flares and settles (area to 12.1 %, ~1/3 of Hunyuan's range),
camera still locked. Cost: dev is 3x distilled per clip and at the laptop's RAM limit at 720p, so a 20 s dev take
would need a rented GPU.

## Kandinsky 5 Pro (2026-09-29, pod `k5_calm`, H100, sdpa)

Seed 306, original prompt: **61.4 min** for 121 frames on an H100 (3-4x Hunyuan, 15-30x LTX); the local 6 GB run was
stopped after 8 h without a result (weights streamed from RAM, 34 W at "100 %"). Camera drifts 4.45 px (no depth lock),
the traveler takes a few steps, spice flecks fall to 0.66x (foreground sparkle gone by mid-clip), drift 2.72. Seeds
307 / 308 not rendered: each would have run past the pod's $7 cap. Pod: 87 min, ~$5.05.
Calmer-cloak Hunyuan (same pod, `runs/models/spice_desert_calm/`): the traveler holds; the cloak moves less than the
whipping version but still flares by the end; drift 3.91 vs 5.2. Screen with all six arms: `sbs_s306.mp4`
(the 5-arm version kept as `sbs_screen5_s306.mp4`).
**Review 8: the best standing-figure animation, but possibly not worth its very long runtime.** -> parked on cost,
not quality.

## Conclusion so far (2026-09-29)

- Quality on the same GPU and attention: close (little difference in review). Hunyuan: better cloth and distant
  sand-cloud motion. LTX: chunkier floating particles (acceptable in review). Wan 2.2 Lightning: out.
- Cost: LTX 720 ~2-4 min per 5 s clip on an H100 and 5 min on the laptop; Hunyuan 19-29 min on an H100 and 234 min
  on the laptop (rented GPU only in practice).
- **Loopability decides it, and only LTX is proven.** WanGP's Hunyuan 1.5 i2v allows start image / continuation
  only (`image_prompt_types_allowed = "SVL"`, no end frame; sliding windows overlap 1 frame), so it cannot generate
  its own closure. A Hunyuan loop would need a cross-model closure (LTX bridge on re-encoded Hunyuan frames):
  untested; the style change at the seam is the risk. Hunyuan's walk is a defect for loops; the stand-still clause
  fixes it, but in review the whipping cloak may be too distracting for an ambient scene.
- Kandinsky 5 Pro: still rendering locally (requested: let it finish); not yet judged.

## Next

User's call: stay with LTX (proven loop path), or test Hunyuan loopability first (cross-model closure seam test on an
existing Hunyuan stand-still clip, calmer cloak wording); Kandinsky joins the screen when it finishes.
