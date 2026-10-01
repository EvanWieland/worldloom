# Consistent wind direction in a seamless loop — desk research + local feasibility (2026-09-23)

**Evidence level:** literature + source reading + measurements on our own artifacts. No new generation runs.

## The problem, measured

Reviewer on the first passing 28.6 s loop (B7): the clouds switching direction mid-scene is unwanted. Horizontal sky flow per half second over the loop (`research/local-video-baseline.md`, 2026-09-23):

1. **Inside the chain the sky flips direction at every 5 s window boundary** (left 0–5 s, right 5–8 s, left 8.5–10 s, right 10–13 s …). Cause: plain Wan 2.2 i2v hands exactly one frame to the next window (`wan_handler.py` `test_oneframe_overlap` → overlap fixed at 1). One frame carries no velocity, so each window chooses a new drift direction. A WanVideoWrapper user reports the same for plain Wan 2.2: "even standard Wan generates similar reversal after ~10 seconds" ([issue #1373](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1373)).
2. **Every bridge sweeps the sky back** at 6–10× the chain's sky speed, because the loop must return to frame 0's cloud layout. Our motion-level gate averages the whole frame and missed this (fast sky over a calm foreground).

Cause 2 is structural: **a loop that returns to a fixed frame while its content drifts in one direction must undo that drift somewhere.** The only ways out are (a) content whose drift is periodic over the loop — which only *joint circular generation* produces, (b) content that does not drift (evolves in place), or (c) a slow reversal, which the user already rejected as ping-pong.

## What exists (Sept 2026)

| Method | What it does | Status / fit |
|---|---|---|
| **Loopy** ([arXiv 2608.23090](https://arxiv.org/abs/2608.23090), [code](https://github.com/WeChatCV/Loopy), [weights](https://huggingface.co/htdong/Loopy)) | Makes the DiT's temporal RoPE circular (layer-wise anchored shift `R̃_t = R_(t−δ_l) mod T`), plus a rank-4 LoRA to fix the VAE decoder's linear temporal bias. Loops keep "vivid motion" where FLF2V "degenerates to nearly static video" — exactly our freeze. | **T2V only** (Wan2.2-T2V-A14B high/low LoRA pairs + LightX2V 4-step). **53–81 frames (3–5 s)**. No I2V, no keyframe conditioning, no long loops. Cyclic smoothness 0.9925 vs Mobius 0.9892; shift without LoRA 0.9753. |
| **Mobius** ([arXiv 2502.20307](https://arxiv.org/abs/2502.20307), [code](https://github.com/YisuiTT/Mobius)) | Training-free latent roll by `shift_skip` frames each step so the loop point moves through the sequence; model always sees a linear window. | CogVideoX / VideoCrafter2 only. T2V. Implemented for Wan in the ComfyUI wrapper as `WanVideoLoopArgs`. |
| **ComfyUI-WanVideoWrapper** `WanVideoLoopArgs` (Mobius shift) + `context_schedule=uniform_looped` (AnimateDiff-style circular context windows) | Long circular sequences by co-denoising overlapping windows over a ring. | Source read (`nodes_sampler.py:1850,2513`): the latent shift rolls `latent_model_input` only; **I2V image conditioning is not rolled**, so with a start image the condition and the content diverge — effectively T2V-only. Open issues report **ping-pong at window transitions with Wan 2.2 I2V** ([#1373](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1373), [#1219](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1219)), contrast drift over loops ([#1541](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1541)), and an unresolved backward-window scheduling report ([#1172](https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1172)). No maintainer fixes. |
| **SVI 2.0 Pro** ([paper](https://arxiv.org/pdf/2510.09212), [page](https://wanx-troopers.github.io/svi.html)) | Long video via anchor latent + 5 motion latents from the previous clip ("error recycling"). Carries velocity across windows. | Our take-1 failure (hard cut at the seam) is explained by the anchor: WanGP puts the anchor image latent at slot 0 of every window (`any2video.py:719–748`), which pulls a drifting sky back to the keyframe layout each window. Good for characters, wrong for skies. |
| **Go-with-the-Flow** ([CVPR 2025](https://arxiv.org/abs/2501.08331), [kijai node](https://github.com/kijai/ComfyUI-VideoNoiseWarp)) | Warped noise gives a diffusion model a motion field to follow — could force the bridge to keep drifting left while morphing into frame 0. | CogVideoX/AnimateDiff only; no Wan port found. |
| **DreamLoop** ([arXiv 2601.02646](https://arxiv.org/abs/2601.02646)) | Cinemagraphs from one photo; loop closure via first=last conditioning + static tracks. Trained. | No code found; first=last is the family that collapses on our scene. |
| **Prompted direction** ("clouds drift slowly from right to left") | Give every window the same instruction, so windows agree. | Untested here. Cheap (one 241 f chain ≈ 20 min). Addresses cause 1 only. |
| **Non-drifting sky** ("clouds slowly thin, thicken and change shape in place; no overall drift") | Removes the drift, so the bridge has nothing to undo. | Untested. Cheap. Changes the look (still within the "living photograph" brief). Addresses causes 1 and 2. |

**Conclusion of the survey:** as of this search there is **no released method that produces a keyframe-conditioned, 30–60 s, seamlessly looping video with persistent unidirectional motion.** The one method that solves the motion-consistency problem properly (Loopy) is text-to-video and 3–5 s. Everything long-form either reverses (windows, bridges) or collapses to static (first=last).

## Local feasibility notes

- ComfyUI portable is installed (Python 3.13, torch 2.13+cu130, CUDA OK, git 2.55). `ComfyUI-WanVideoWrapper` cloned (`custom_nodes/`, commit 088128b, 2026-05-24); requirements not yet installed. Wan 2.2 i2v fp8 high/low + LightX2V 4-step LoRAs + umt5 are already in `ComfyUI/models`. Block swap (up to 40 blocks) is how 14B runs on 6 GB there; users on 6 GB report 10–15 min per 480p clip — comparable to WanGP.
- Wan 2.2's two experts are run as two sampler passes in the wrapper; context windows and loop args would have to be set on both.
- WanGP has no circular mode. Adding a Mobius roll to `any2video.py`'s denoise loop is ~10 lines, but I2V conditioning at slot 0 would have to roll with the latents — Wan i2v was never trained with the conditioned frame off index 0. Untested anywhere; a hypothesis, not a plan.
- Deleted earlier and needed for any T2V/VACE route: Wan 2.2 T2V 14B experts + VACE module (~31 GB, re-downloadable).

## Recommendations (cheapest first, each with a stop rule)

1. **Non-drifting sky (prompt), 1 GPU-hour.** Chain 241 f at 848×480 with the calm recipe but "clouds slowly thin, thicken and change shape in place; no wind, no drift across the sky", colour correction on, 121 f windows. Measure sky |dx| per window and the bridge's sky speed ratio. **Pass:** sky drift ≤ 0.3× today's and bridge sky speed ≤ 2× chain. If it passes, the current B7 pipeline delivers the loop with no reversal, and Phase C proceeds. This is also the honest fit for "living photograph": clouds that breathe rather than travel.
2. **Direction-locked prompt, same hour.** Same chain with "clouds drift very slowly from right to left throughout" to see whether cause 1 is prompt-addressable at all (useful for any future scene with wind). Stop rule: sign of sky dx constant across all windows.
3. **Loopy-style circular generation — spike, only if the user wants travelling clouds.** Not a config change: T2V-only weights and 3–5 s loops. The realistic version for us is a *hybrid*: generate a **5 s Loopy sky loop** (T2V, 81 f) for the sky region only — but that is compositing a sky layer over the plate, which invariant 12 forbids unless the user reopens it. Alternatively test **`uniform_looped` context windows without loop args on Wan 2.2 i2v** for a 241 f ring (keyframe at index 0, windows wrapping around it). Cost: ~half a day of setup + 1 h run. Risk: the wrapper's open ping-pong reports. Label: hypothesis.
4. **Gate change regardless of route:** add a **sky-region motion gate**: per-block sky |flow| ratio and sky direction (sign of dx) must stay within band across the whole loop including bridges. The whole-frame gate provably misses this.

**Recommendation:** run 1 and 2 next (2 GPU-hours total, both fit the existing WanGP pipeline). Decide on 3 only if 1 fails and the user wants travelling clouds more than a loop without reversals.

## A5 result (2026-09-23, 361 f, 121 f windows, colour correction, "clouds thin/thicken/change shape in place")

- 32 min on the local GPU. Sky horizontal flow stays rightward throughout (no per-window sign flips), but is not zero: 0.2–0.6 px/frame in the second half. Sky Laplacian ratio 2.6× at 10–12 s, 4.5× at 19 s (fails the provisional ≤1.4× gate by metric); luma −5 % after an early −18 % dip.
- **Human review: acceptable — the clouds dissipate and morph in place rather than flowing; a visual effect makes them look like they flow.** The metric gates (sky flow, sharpness) disagree with the eye's mild verdict; the eye wins for now, gate is provisional.
- Consequence: morph-in-place sky is acceptable, so a bridge back to frame 0 has no directional drift to undo. Still to test: does a bridge sweep on this chain read as morph too (needs a flf2v bridge, ~1 GPU-h).
- Evidence: `experiments/overnight/a5_sky_inplace/` (chain.mp4, job.log), numbers in `experiments/overnight/results.json`.
- **Follow-up verdict: cloud quality poor (the clouds look fake); transitions decent.** So the morph-in-place motion is acceptable, the cloud texture is not. This matches the sky-sharpness metric (2.6–4.5× vs frame 0) that the first verdict seemed to overrule: the Laplacian gate caught over-sharpened, painterly clouds. Keep the gate.

## A6 result (2026-09-23, same setup, "clouds drift very slowly from right to left at a constant speed throughout")

- 32 min. The direction was **not** followed: sky horizontal flow ≈ 0 (|dx| < 0.005 px/frame) the whole chain. Texture is the best of any chain: sky Laplacian ≤ 1.32× to 15 s, 1.6–1.7× after 16 s; luma −3.7 % flat.
- **Human review: good; some distortion in the sky near the end, decent quality overall.** The late distortion lines up with the Laplacian step at 16 s — the ≤1.4× sky gate agrees with the eye here.
- Consequence: the A6 prompt is the current best chain recipe for a static-ish sky; cut it at ≤ 15 s. Next: bridge from the A6 chain back to frame 0 (`experiments/overnight/a6_loop.py`).

## A5b (2026-09-23, "soft, hazy, wispy clouds slowly fade and reform in place" + anti-sharp negatives)

- 32 min. Sky dx ≈ 0; sky Laplacian 1.17/1.24/1.29/1.57× at 5/10/15/20 s — same texture class as A6.
- **Human review: looks good, but too still; some more atmospheric movement wanted (moderate, not strong).**
- The trade-off so far: prompts that stop the sky drifting also make it look static; A5's stronger morph read as fake. Next: A5c — visible in-place churn for clouds *and* valley mist, negatives against both sliding and frozen skies.

## A6 loop (2026-09-23): A6 chain cut at 236 + 33 f native flf2v bridge ("soft clouds stay where they are") + whole-loop retime

- Bridge 56 min, 4.7 GB VRAM, 40 GB RAM. Retimed loop 21.1 s @ 24 fps.
- **Sky sweep is gone:** bridge sky |dx| 0.004 px/frame (chain 0.002); B7's bridges swept at 6–10× chain speed. Bridge sky Laplacian 1.15–1.55×, no spike.
- Gates: direction pass, sharpness-continuity pass (1.07× retimed); **motion-level fails** (0.66–0.74× after retime), **spatial-noise fails**, joins 2.02× (chain→bridge) and 2.92× (wrap) vs ≤ 2× target. Caveat: with a near-static chain, the median adjacent change is tiny, which inflates every ratio — the absolute numbers need eye confirmation.
- **Human review: A6 looks good.** First loop with no cloud reversal to pass. The failing motion-level, spatial-noise and join gates did not match the eye — likely ratio inflation over a near-static chain; recalibrate those gates on absolute numbers before Phase C. Remaining complaint: the sky is too still (A5c in progress).

## A5c (2026-09-23, "slow, gentle but clearly visible motion"; clouds "churn, fade and reform in place"; mist "billows, swirls and rises"; negatives add "static sky, frozen clouds")

- 32 min. Sky Laplacian 1.19/1.24/1.28/1.54× at 5/10/15/20 s, luma −3.4 %: same clean texture as A5b/A6.
- Mean optical-flow magnitude over the first 15 s (px per 4 frames), sky ROI / lower third: A5 1.66 / 1.57, A6 0.017 / 2.35, A5b 0.017 / 2.01, **A5c 0.019 / 2.52**. The sky **stayed frozen** despite the wording; only the mist moved more (+7 % vs A6, +25 % vs A5b). Prompt wording does not unlock sky motion without the fake A5 look.
- Note: `results.json` is rewritten by each queue process, so only the last job's results are in it; per-job numbers are in each `*.log`.
- **Human review: excellent mist movement, a very high-quality scene; one defect, noise in the sky near the top right.** A5c is the best chain recipe so far. Movement comes from the valley mist, not the sky, and that answers the too-still complaint. Open defect: top-right sky noise (the sky Laplacian ROI is that exact region; the loop cut at ≤ 15 s avoids the worst of the late rise). Loop build started: `experiments/overnight/a5c_loop.py` (cut at frame 211).

## A5c loop (2026-09-23): cut at 211 + 33 f native bridge (no-drift sky + billowing mist prompt) + whole-loop retime

- Bridge 56 min. Retimed loop 19.9 s @ 24 fps (`experiments/overnight/REVIEW_A5c_loop_x2.mp4`).
- **All retimed bridge gates pass** (motion-level 0.81–1.06×, direction, spatial noise, sharpness continuity 1.10×) — first loop to pass every bridge gate. Mist flow in the bridge 0.66 vs chain 0.75 px/frame (the bridge keeps the mist moving).
- Joins: chain→bridge 1.69×, **wrap 2.96×** (> 2× target; the A6 loop had 2.92× and passed the eye).
- Sky Laplacian: chain ≤ 1.35×, bridge peak 1.53×.
- Verdict: pending.
- **Human review: fails at the ~22 s mark — it freezes and the mist shifts direction somewhat.** (22 s in the ×2 review = right around the wrap at 19.9 s.) Measured: mist speed in the retimed loop drops from a median 0.165 to 0.054–0.087 px/frame over the last ~1.5 s before the wrap — the bridge still eases into frame 0, now visible in the mist rather than the sky. The mist-direction change is the same structural problem the clouds had: the bridge has to return the mist to frame 0's shape.
- Tried (CPU): retiming on lower-third (mist) flow instead of whole-frame flow — end-of-loop mist speed only 0.054 → 0.065; does not fix it. Reverted.
- So the bridge gates passed a loop the eye failed: they need a per-region (mist) motion-level check over the last second, not whole-frame blocks.

## A4 circular-generation spike, T0 (2026-09-23): WanVideoWrapper `uniform_looped`, Wan 2.2 i2v A14B fp8 + lightx2v 4-step, 121 f ring, 832×480, keyframe at index 0

Setup (reusable): ComfyUI portable headless on :8188, workflow submitted as API JSON by `experiments/circular/run_looped.py`. Two fixes needed: (1) Windows **Smart App Control blocks scipy 1.18.1's `_odepack` DLL** in ComfyUI's embedded Python → install `scipy==1.17.1` (the version WanGP's venv uses); (2) the wrapper's LoRA merge into the fp8-scaled model **crashed the process (access violation)** → `merge_loras: False`. Context 81 f (21 latents), overlap 32 f (8 latents), NAG 9, euler, shift 5, 2+2 steps high/low. 25.8 min, block swap 40.

Result — **fails on every axis**:
- **Motion almost gone:** mist 0.02 px/frame (A5c chain 0.25–0.75), sky ~0.003. Overlapping windows with independent motion are averaged, and the averages cancel.
- **Ghosting:** double moon around 3.75 s (two windows disagree on the moon position; the fusion blends them).
- **Broken frames at the loop point:** frame 1 is a checkerboard; the wrap join is 9.5× median (123→0) and 32× (123→1). Consistent with Loopy's finding that the Wan VAE decoder has a temporal bias that breaks a circular latent without their LoRA.
- Contact sheet: `experiments/circular/t0_sheet.jpg`.

Why (hypotheses): with a 4-step distilled model the windows get only 4 fusion rounds to agree; the VAE is causal and not circular. A fix would need the non-distilled base model at 20–30 steps (~28 GB download, est. 5–8× the time) *and* a circular VAE decode — i.e. re-implementing Loopy for I2V. Not a config change.

## A4 circular spike, T1 series (2026-09-23): 480×272 (≈⅓ tokens) for speed, wrapper's looped decode patched out

Patch: `ComfyUI-WanVideoWrapper/nodes.py` WanVideoDecode `if is_looped:` → `if is_looped and False:` — the wrapper's wrap-decode re-decodes the i2v image latent as a 4-frame chunk and min-max normalises it separately, which produced T0's checkerboard frame 1. With it off, frame 1 is clean.

| run | steps | overlap | fuse | keyframe ref in every window | wall | wrap join (× median) | mist px/f (832 scale) |
|---|---|---|---|---|---|---|---|
| T0 832×480 | 4 | 32 | linear | no | 25.8 min | 9.5–32 (broken frame) | 0.02 |
| T1a | 4 | 32 | linear | no | 7.0 min | 14.6 | 0.031 |
| T1b | 8 | 48 | pyramid | no | 15.0 min | 12.7 | 0.081 |
| T1c | 8 | 48 | pyramid | yes | 15.0 min | 12.6 | 0.080 |
| T1d | 16 | 64 | pyramid | no | 51.3 min | 9.0 | 0.113 |

A5c chain for reference: mist 0.25–0.75 px/f; gate target for joins ≤ 2×.

- **Low res is a valid diagnostic here:** the same failure modes (motion loss, wrap jump) reproduce at 480×272 in ~¼ of the time.
- **Keyframe reference in every window does nothing** (T1c ≈ T1b) — the mid-window-keyframe hypothesis for the seam is not supported.
- **More denoising rounds help both problems, slowly:** 4→16 steps triples motion and shrinks the seam 14.6 → 9.0×. In T1d the content does converge toward frame 0 at the end (diff to frame 0: 11.7 at frame 110 → 7.0 at frame 120, where frames 0→8 differ by 6.3) — the seam is equivalent to skipping ~½ s of content, not a cut.
- Cost scales badly: 16 steps = 51 min for 7.5 s at ⅓ of 480p. A 30 s ring at 480p at that setting is a many-hour local job, and it would still fail both gates by extrapolation.
- **Human review of T1d ×4: the mist slows down and stops moving.** Circular T1d fails on motion by eye too. User requirement restated: the end must flow into the start with **no lag, crossover, fade or slowdown** — and asked for more research on how others solve it.

## Research round 2 (2026-09-23): how others close an *existing* clip without a stall

**Root cause of every stall so far, restated:** flf2v bridges (and the circular ring's wrap windows) are conditioned on *one* frame at each end. A single frame carries position but no velocity, so the model lands on frame 0 at rest (freeze) and picks its own direction on the way (mist reversal). Everything that works in the wild conditions on **several frames on each side**.

- **Community standard for "loop any clip": VACE temporal inpainting with context on both sides** — control video = last ~15 frames + ~51 blank frames + first ~15 frames, mask generate-only-the-gap, then drop the context frames and splice the gap between the originals ([OpenArt "Loop Anything with Wan2.1 VACE"](https://openart.ai/workflows/nomadoor/loop-anything-with-wan21-vace/qz02Zb3yrF11GKYi6vdu), [ComfyUI-Wan-VACE-Video-Joiner "Make Loop"](https://github.com/stuttlepress/ComfyUI-Wan-VACE-Video-Joiner), [Comfy template "Video to Seamless Loop"](https://comfy.org/workflows/template_sirolim_seamless_loop-31ea7d2d9224/)). The joiner now supports **Wan 2.2 Fun VACE**. Its documented caveats: brightness/saturation shift "baked into the model"; use *the same LoRAs/settings as the source clips*; context/replace counts scale with fps.
- **Our one VACE attempt (2026-09-22) is not a fair test of this:** it used WanGP's `vace_14B_lightning_3p_2_2` (the Wan 2.1 VACE module grafted onto 2.2 + a 3-phase Lightning recipe — not the chain's model/LoRA), 16 context frames, and we kept VACE's re-rendered context frames (which came out 11 luma darker) instead of the originals. **Wan 2.2 Fun VACE A14B** (trained natively for 2.2) is available in WanGP as `vace_fun_14B_2_2` (not downloaded).
- **Wan 2.2 FLF with the same image at both ends** ([Next Diffusion](https://www.nextdiffusion.ai/tutorials/wan-2-2-looping-animations-in-comfyui), [Wan2.2 #49](https://github.com/Wan-Video/Wan2.2/issues/49)) makes 5 s loops from one image; the issue thread reports restricted movement and colour differences; lowering end-frame strength trades motion for closure. It does not close an existing long clip. Matches our own first=last result.
- **Frame Guidance** ([arXiv 2506.07177](https://arxiv.org/html/2506.07177v2), [code](https://github.com/agwmon/frame-guidance)): training-free loop loss ‖first − last‖ during sampling; supports Wan-14B, CogVideoX, LTX (161 f), SVD. Needs backprop through the model → 2–4× slower and memory-heavy; T2V-first. Probably out of reach for 14B on 6 GB; LTX-2B variant might fit.
- **Loopy / Mobius**: circular RoPE / latent roll — T2V, 3–5 s (see above). Our I2V ring attempt reproduces their stated failure modes without their fixes.
- **Bidirectional / time-reversal inbetweening** (ViBiDSampler ICLR 2025, "Motion prior distillation in time reversal sampling" 2026): fuse a forward pass from A with a time-reversed pass from B so neither end is approached at rest. Built on SVD-class I2V; would need a custom sampler in WanGP. Hypothesis-level for us.

**Recommendation:** re-test the community method properly before anything exotic — Wan 2.2 Fun VACE, context 16 f each side from the A5c chain's end and start, 49 generated frames (3 s) at 832×480 with the chain's own Lightning/NAG settings, originals kept for the context frames, colour-matched gap. Gate on mist motion level across the gap (≥ 0.8× chain) and mist direction continuity, then eye.

## VACE Fun loop closure, v1/v2 (2026-09-23): Wan 2.2 Fun VACE, 16 ctx + 49 gap + 16 ctx, 832×480, Lightning T2V 4 steps, NAG 9, A5c chain cut at 211

- **v1 used `video_prompt_type: "VUA"` — WanGP ignores the mask whenever `U` is present** (`wgp.py:1400`, `any_mask = "A" in … and "U" not in …`), so the model reproduced the grey placeholder frames. Our 2026-09-22 VACE attempt used the same `VUA` flags, so that negative result is **invalid**. Correct flags for "control video + mask": **`VA`**.
- **v2 (`VA`), 7.7 min** (after a one-time ~30 GB download): the gap keeps the mist moving at **0.85–1.95× chain speed across the whole gap and the wrap — no slowdown**; gap luma −0.6 vs the context (no brightness shift); VACE's re-render of the context frames differs from the originals by only ~1.9 grey levels. Joins: chain→gap 2.48×, **gap→frame 0 4.63×** (target ≤ 2×).
- Review sample: `experiments/vace_loop/REVIEW_vace_v2_x2.mp4` (whole-loop retime, ¾ speed; gap 17.7–21.75 s per pass).
- **Human review: no perceptible transition in the loop; the best result so far.** First loop closure with visible atmospheric motion to pass. The 4.63× wrap join was invisible — the ≤2× join target is too strict for this content; recalibrate on this sample.

## Clouds c1 (2026-09-23): A5c recipe with "soft, hazy clouds drift slowly and steadily across the sky" + VACE closure

- Chain 32.5 min, VACE 7.7 min. Closure numbers match v2 (mist 0.46–2.1× through the gap, luma −1.35, joins 2.43/4.85).
- **The clouds did not drift.** Cloud-band flow (rows 30–130, full width) median 0.014 px/f vs 0.41 in A5 — same frozen sky as A5b/A5c. The "drift" wording is ignored once the A5b/A5c additions are present ("soft, hazy" + anti-sharp negatives). Candidate cause (hypothesis): the soft/hazy wording removes trackable cloud structure *and* the model reads it as stillness; NAG 9 with a long negative list may add to it. Only A5 (original "creep" wording, no anti-sharp negatives) moved, and it looked fake.
- Review sample: `experiments/vace_loop/REVIEW_clouds_c1_x2.mp4`.

## Cloud-motion screen (2026-09-23, 768×448, 241 f, 121 f windows, colour correction, A5c mist wording; ~19 min each)

Negatives trimmed to `CHAIN_NEG + painterly, illustration, static sky, frozen clouds` (no "soft/hazy", no anti-sharp list). Cloud band = rows 30–130 at 848×480 scale.

| variant | cloud speed px/f (median) | direction | sky Laplacian vs frame 0 |
|---|---|---|---|
| cb1 "thin clouds creep slowly across the sky", NAG 9 | 0.035, decays to ~0.01 | right, constant | ≤ 1.09× |
| **cb2 same, NAG 5** | **0.118, steady** | **left, constant** | **≤ 1.08×** |
| cb3 "wisps of thin cloud slowly pass in front of the moon and drift across the sky", NAG 9 | 0.249 (dips to 0.03 at the 7.5 s window boundary) | right, constant | 1.29–1.47× at 9–12 s |

- All three keep **one direction across windows** (sign consistency 1.0) — with 121 f windows + colour correction the per-window flips of the 81 f chains do not appear.
- **NAG scale is a motion lever:** NAG 9 → 5 raised cloud speed 3.4× with no texture cost. The A5b/A5c/c1 frozen skies were the "soft, hazy" wording + anti-sharp negatives under NAG 9.
- Verdicts pending (cb2, cb3 sent).
- **Human review, both at raw 16 fps playback:** fog better in the first [cb2] — the second [cb3] barely moves the fog; both have decent clouds; the cloud morphing is too quick (time-lapse look); the fog is a little fast too (as if driven by a gale); otherwise good scenes. → cb2 recipe preferred; everything is too fast at 1× playback. Cheapest lever is playback speed (the approved look was ¾ speed; user earlier accepted ½–¾).

## Gentle-motion prompt screen (2026-09-23, 81 f single window, 768×448, ~6.4 min each; `experiments/vace_loop/gentle.py`)

User asked for plants, mist and clouds all gentle but moving, tuned by prompt rather than playback speed. New prompt drops "pine trees completely still, no wind"; negatives target speed ("time-lapse, sped up, fast-moving fog, rushing mist, strong wind, gusts…"). Median flow px/f (848×480 scale): clouds rows 30–130, mist rows 180–300 left, plants rows 330+.

| | clouds | mist | plants |
|---|---|---|---|
| cb2 reference (reviewer: too fast) | 0.173 | 0.340 | 0.601 (prompted still) |
| g1 "everything moves slowly and gently…", NAG 5 | 0.195 | 0.163 | 0.725 |
| g2 same, NAG 7 | 0.092 | 0.119 | 0.728 |
| g3 "still, quiet night, faintest breeze … barely sway", NAG 5 | 0.020 | 0.066 | 0.768 |

- Wording halves mist speed; NAG 5→7 halves cloud speed; plant sway is insensitive to both wordings (~0.73–0.77). Verdicts pending.
- **Human review: clip 3 [g3] is the most realistic; the plants are slightly too active and lean against the way the mist and clouds blow; otherwise no issues; slightly more cloud movement near the foreground wanted.**

## Gentle-motion round 2 (2026-09-23, 81 f, 768×448; `experiments/vace_loop/gentle2.py`)

Review: g3's plants lean the wrong way: the keyframe's foreground grass plumes are **bent to the right** (wind implied left→right) while g3's clouds and mist drift left. First attempt (h1, "right to left") steered the clouds hard left (dx −0.31) — killed after h1 once the lean mismatch was understood. Re-run with a shared "breeze blowing from left to right" clause, plants "lean very slightly to the right … barely move", negatives against back-and-forth sway.

| | clouds speed / dx | low clouds speed / dx | mist speed / dx | plants speed / dx / sway std |
|---|---|---|---|---|
| g3 ref | 0.011 / −0.001 | 0.033 / −0.022 | 0.066 / −0.011 | 0.77 / −0.06 / 0.57 |
| h1r breeze L→R, NAG 5 | 0.020 / +0.013 | 0.030 / +0.007 | 0.098 / −0.008 | 0.80 / −0.10 / 0.49 |
| h2r + low wisps, NAG 5 | 0.059 / +0.035 | 0.063 / −0.025 | 0.117 / −0.080 | 0.91 / −0.27 / 0.65 |
| h3r + low wisps, NAG 6 | 0.040 / +0.014 | 0.044 / −0.010 | 0.122 / −0.076 | 0.89 / −0.17 / 0.64 |

- The direction clause steers the **sky**, not the mist or the plants. Plant activity is not reduced by "barely move" or the anti-sway negatives. Hypothesis: the windswept grass in the keyframe itself drives the plant motion → the real fix is a keyframe with calmer vegetation, with wind direction set at keyframe time (motion-prompting rule 5). Verdicts pending.
- **Human review: the first video [h1r] is best, but the wind does not go left to right as it should; failing that, the plants should lean left to follow the wind if the wind direction is not reversed.** The model's preferred drift here is right→left (g3, and h1 "right to left" steered clouds hard, dx −0.31), and a L→R instruction barely registers (+0.013). Next: **mirror the keyframe horizontally** so the grass leans left, then prompt the right→left breeze the model already follows.
- **m1 (mirrored keyframe → grass leans left; breeze "right to left", plants "lean very slightly to the left"; h1r wording otherwise, NAG 5):** clouds 0.39 px/f dx −0.37 (≈20× h1r), low clouds 0.094 leftward, mist 0.32, plants 0.69 with the lowest sway so far (0.46). All elements now agree with the grass lean; clouds/mist probably too fast. Verdict pending.
- **Reviewer on m1: the clouds are far too fast; asked whether a wind speed in mph can be set in the prompt.** Wind-speed wording screen on the mirrored keyframe (`experiments/vace_loop/wind.py`, 81 f, 768×448):

| | clouds | low clouds | mist | plants (speed / sway) |
|---|---|---|---|---|
| m1 (too fast) | 0.39 | 0.094 | 0.32 | 0.69 / 0.46 |
| w1 "very light breeze of about 2 mph" | 0.55 | 0.158 | 0.35 | 0.77 / 0.61 |
| w2 "light air, Beaufort force 1 … clouds creep so slowly you can barely see them move" | 0.65 | 0.177 | 0.35 | 1.07 / 0.88 |
| w3 m1 wording at NAG 7 | 0.43 | 0.089 | 0.30 | 0.68 / 0.48 |

- **Numeric/physical wind wording speeds motion up** (more wind words → more wind), and NAG 7 — which halved cloud speed on the original keyframe — does nothing on the mirrored one. On the mirrored keyframe the cloud speed is set by the image, not the text. **Conclusion (hypothesis, n=1 scene): text cannot set a target speed; the reliable speed control is measured retiming** (flow-measure the element, resample playback to hit a target px/f). Candidate rule 9 for `motion-prompting.md`.
