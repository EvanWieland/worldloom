# Loop transition: what can remove the last visible seam (desk research + WanGP source reading, 2026-09-24)

**Evidence level:** web sources + reading WanGP's LTX code on this machine. No new GPU runs. Prior measurements are in `model-options.md` / `loop-direction.md`.

## Diagnosis

Every remaining complaint on the LTX loops (the same visible transition, waterfall +10 % faster in the gap, rain/window change at the loop point) is **two different generators meeting**: an LTX-2.5 clip and a Wan 2.2 Fun VACE gap. Their sense of speed, rain texture, tones and sharpness differ; `match_gap.py` fixes tones and sharpness after the fact, but not motion statistics. So:

- **A bigger or better clip model does not fix this.** It changes the footage, not the join. The seam goes away only if **the model that writes the gap is the same model that wrote the clip, and it sees real context frames at every denoising step** (joint attention, not a reference image or IC-LoRA hint).
- Our earlier LTX attempts did not meet that condition: frame injection (`KFI`) does not reproduce the injected frames, and the inpainting IC-LoRA (`MVGA`) treats context as a reference and leaves hard jumps at its mask edges (7.8 / 14.8 vs 2.8).

## Finding 1: the planned "LTX low-denoise harmonisation" is not possible with stock WanGP flags

STATE.md planned `video_prompt_type: "VG"` + `denoising_strength` 0.35 / 0.5 as a low-denoise video-to-video pass. **In WanGP's LTX path `denoising_strength` is "Control Video Strength"** (`ltx2_handler.py:694`, `ltx2.py:1464` `control_strength = denoising_strength`): how strongly the IC-LoRA control video conditions the output. It does not start sampling from a noised copy of the source (SDEdit). That run would not have tested the idea.

## Finding 2: WanGP already has a RePaint-style lock that can do it, with a small patch

`masking_strength` ("Unmasked Area Strength") runs `_apply_mask_injection` (`ltx_pipelines/utils/helpers.py:670–678`): for the first `ceil(steps × strength)` steps, every **unmasked** token is overwritten with the source latent noised to the current sigma; masked tokens evolve freely. That is RePaint: the model attends to the real context, noised to the right level, at every locked step. That is the "strong attention to surrounding frames" that LTX's commercial **Retake** feature advertises ([LTX Retake API](https://docs.ltx.video/api-documentation/api-reference/async-video-generation/submit-retake), [fal Retake](https://fal.ai/models/fal-ai/ltx-2.3/retake-video)). Retake itself is API-only, so we can't use it here (no API keys). The ComfyUI community rebuilds it with a latent noise mask ([RuneXX V2V ReTake](https://huggingface.co/RuneXX/LTX-2.3-Workflows/discussions/74)).

The stock implementation has two limits that explain hard edges:
- `helpers.py:623` binarises the mask in latent space (`mask_latents >= 0.5`), and the step count is global. So time runs locked → free with no ramp.
- It is disabled for the inpainting IC-LoRA (`ltx2.py:1460–1461`, and `ltx2_handler.py:957`), which is the one we tested.

**Proposed patch (monkeypatched in the experiment script, WanGP files untouched):** keep the mask fractional and lock each token for `round(steps × (1 − m))` steps. With LTX's 8 distilled steps, m = 0 means an exact copy of the source, m = 1 means fully regenerated, and values in between re-render only the finer detail. This is Differential Diffusion applied along time. A community node already does the soft-ramp version for video ([MaskVidExperiments](https://github.com/drozbay/MaskVidExperiments)). Result: **no hard temporal edge anywhere**, and the gap comes from the clip's own model.

Two uses:
- **(a) Harmonise the existing VACE gap:** source = `[32 real ctx | VACE gap | 32 real ctx]`. m ramps 0 → ~0.5 over ~16 frames on each side and holds ~0.5 across the gap. LTX keeps VACE's layout but rewrites speed and texture with its own statistics.
- **(b) LTX writes the gap itself:** source = the same layout with grey in the gap. m = 1 in the gap, ramping to 0 through the context. This replaces VACE. The risk is the ease-in/slowdown we saw with LTX inpainting (−35 % mid-gap); RePaint's per-step real context is the reason to expect better, but that is a hypothesis.

Things to check before running (not verified):
- The masking source is `input_frames`, the control video (`ltx2.py:1527`). With `DVG` depth lock that is probably the depth-processed video, not RGB, so the patch should supply the RGB source itself.
- `masking_strength` requires `G` in the prompt type (`ltx2.py:1457`), so the control-video conditioning is always on. Keep the depth lock (DVG) as that control, since we want it anyway for the camera.
- The latent mask should follow LTX's 1 + 8k frame grouping (`_mask_to_latents`).

## Finding 3: our VACE runs break two of the joiner's documented rules

From the [Wan VACE Video Joiner README](https://github.com/stuttlepress/ComfyUI-Wan-VACE-Video-Joiner/blob/main/README.md):
- "The Wan models are trained at 16 fps … downgrade input videos to 16 fps for processing, then re-interpolate." `experiments/vace_loop/run.py` feeds the **24 fps** LTX frames directly. *Hypothesis:* this is at least part of the waterfall's +10 % in the gap, because Wan's motion prior is per 16 fps frame.
- "Disabling lightx2v speed LoRAs can help" with the brightness/colour shift. We run Lightning 4-step + NAG 9.

Cheap A/B: 24→16 fps context (drop to 16 or use RIFE), gap at 16 fps, RIFE the gap back to 24, then `match_gap`. Separately, try without Lightning (Fun VACE at ~20 steps). Measure the waterfall band speed as before.

## Models surveyed (for the seam specifically)

| option | what it would change | verdict |
|---|---|---|
| LTX-2.5 (current clip model) | already has native multi-frame continuation (anchors on a 17-frame / 3-latent tail) ([datanorth](https://datanorth.ai/news/ltx-releases-ltx-2-5-open-weights-video-world-model)) | confirms the principle: multi-frame context carries velocity |
| Cosmos 3 Super I2V 65B | better clips; Video2World multi-frame conditioning | ~83 GB/GPU at 720p (≈55 GB fp8) ([Spheron](https://www.spheron.network/blog/deploy-nvidia-cosmos-3-gpu-cloud-physical-ai/)) — rented GPU only, and it would still be a *different* model at the seam |
| Wan 2.7 | FLF control, editing | open-weight status still conflicting ([localaimaster](https://localaimaster.com/blog/wan-2-7-open-source)); no loop feature |
| Loopy (circular RoPE) | the principled fix | Wan 2.2 **T2V only**, 53 f demo, 8-GPU example ([HF](https://huggingface.co/htdong/Loopy)) — no I2V, no long loops |
| Frame Guidance loop loss | training-free loop for LTX-2B / Wan-14B ([paper](https://arxiv.org/html/2506.07177v2)) | needs backprop through the model; 22B only on a rented GPU; hypothesis |
| SYSTMS FLW IC-LoRA (LTX-2.3) | shot-to-shot transitions, grey frames between clips ([HF](https://huggingface.co/systms/SYSTMS-FLW-IC-LORA-LTX-2.3)) | same grey-frame IC-LoRA mechanism as the inpainting LoRA that left hard mask edges; built for A→B morphs; low priority |
| LTXV Looping Sampler | temporal tiling for long videos, not closure ([doc](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/looping_sampler.md)) | not applicable |
| Blind deflicker (All-in-One Deflicker, BlazeBVD) | tone flicker only ([All-in-One](https://github.com/ChenyangLEI/All-In-One-Deflicker), [BlazeBVD](https://arxiv.org/pdf/2403.06243)) | last-mile polish at most; motion mismatch untouched |

## Results (2026-09-24, waterfall loop)

**Run 1: VACE fed 16 fps context** (`experiments/vace_loop/vace16.py`). The LTX clip goes through RIFE ×2 → exact 16 fps context (33 end + 31 start frames, 33-frame gap = 97 f). VACE with the baseline's settings otherwise, then RIFE ×3 and every 2nd frame back to 24 fps, then best_splice, match_gap --stabilise and loop_qc. 8.8 min.
- Waterfall band speed, gap vs clip, at 24 fps with the same Farneback settings: **+16 % (24 fps baseline) → +1 % measured**. RIFE reads real footage 2.3 % slow after the same 24→16→24 path, so the corrected figure is ≈ +4 %.
- The raw 16 fps flow reading is unusable: 0.56 px/f even on re-rendered *context* frames. At 1.5× the per-frame displacement, Farneback aliases on streaky water. Measure speed at 24 fps only.
- All QC gates pass, joins 2.4× / 2.7×, no RIFE ghosting in crops. The gap's water texture still looks more painterly than LTX's. **Adopt: always feed Wan VACE 16 fps.**

**Run 2: soft temporal RePaint** (monkeypatch of WanGP's `prepare_mask_injection` / `_apply_mask_injection` + driver + tone post; code deleted after the negative verdict, mechanism described in Finding 2). The whole 278-frame loop is re-rendered in one LTX-2.5 distilled pass (313-frame window, depth lock, ~10 min). The loop is rotated so the gap sits mid-window, and new loop = out[16:294], so no splice into original frames remains.
- Implementation gotchas, all fixed:
  - `load_video_conditioning` from a *path* with `frame_cap=None` crashes (`media_io.py:397`).
  - An untiled full-resolution 313-frame source encode OOMs at 6 GB. Fix: decode on the CPU, move tiles to the GPU, use temporal tiling.
  - WanGP swallows stdout from its worker thread, so the patch writes `spec.json.called.json` as proof that it ran.
- Pinned (d = 0) frames are **not** exact copies. LTX-2.5's encode→decode comes out ~2.8 grey levels darker with MAD ~5 vs the source. Generated frames keep the tone. Fixed after the fact by per-frame luma histogram match to the same frame of the pre-harmonise loop. Sharpness is corrected with a blur/unsharp amount scaled by each frame's share of d; a hard switch at the gap start created a 20–30 % sharpness step.
- The distilled sigma schedule leaves only a few distinct release levels: d ≤ 0.42, (0.42, 0.725], (0.725, 0.909], > 0.909. So 0.8 ≡ 0.9.

| after tone/sharpness match | run 1 (input) | p0.7 | p0.9 |
|---|---|---|---|
| step at old splice / old loop point (× median) | 2.44 / 2.69 | 0.96 / 1.19 | 1.24 / 1.11 |
| largest step anywhere (× median) | 2.69 | 1.71 (new mid-clip join) | 1.55 |
| waterfall band speed gap/clip | 0.99 | **0.87** (regions 0.82–0.92) | **1.00** (0.90–0.97) |
| background change clip→gap (clip's own over 80 f ≈ 12.9) | 14.1 | **13.4** | **18.0** (foliage/lip morph) |
| loop_qc | PASS | PASS | PASS |

Trade-off: p0.7 keeps the layout but the closing model eases again (slower water). p0.9 fixes the speed but re-invents background detail. Sent A (run 1) / B (p0.7) / C (p0.9) for an eye verdict.

**Review verdict: A was clearly best, an almost imperceptible transition (maybe a 1-frame shift). B and C showed scene bleed from one to the next, not clean.**
- **Soft temporal RePaint is ruled out for loop closure.** Re-rendering reads as the scene bleeding and morphing, even when every step metric sits at about 1× median. Frame-to-frame step metrics can't see slow content morphing; background drift clip→gap was the only number that pointed at it, and only for p0.9.
- **Current best closure = 16 fps VACE (run 1).** Remaining defect: one frame.

**The one-frame shift: three causes, all fixed on CPU (loop A → D).**
1. **Colour drift in our own writer:** every 4:2:0 `write_h264` → cv2 read cycle shifted luma −1.66 (BGR −2.25/−1.45/−1.85, worst on foliage). Real frames that had been through different numbers of cycles no longer matched at splices. BT.601/709 tags don't fix it; **4:4:4 round-trips at +0.17**. `run_queue.write_h264` now defaults to `yuv444p`.
2. **Codec seam at the loop point:** x264's MB-tree starves never-referenced frames, so a file's *last* frame encodes at error 3.3 vs 2.4 median and the loop wraps from a degraded frame onto a fresh I-frame. `mbtree=0` → 2.3. ipratio/pbratio/keyint/B-frame settings don't help. `write_h264` and the review encodes now use `mbtree=0`.
3. **Hard cut between two renders of one moment:** VACE's re-render differs from the real frame by MAD ~7–8 (median frame step ~3). Choosing cuts on real-VACE-frame positions or by join cost doesn't help (2.4/2.8×). **`splice_ramp.py`** ramps real → VACE over ≤10 frames *inside the context overlap*, where both renders of the same instant exist. Closure stays generated; this is not a dissolve between different content. Each mixed frame is unsharp-restored to its interpolated sharpness, because averaging two water textures dropped sharpness 783 → 670, a soft pulse.
- Result, 4:4:4 file: joins into gap / loop point **2.34 / 2.63× → 1.13 / 1.44×**; ordinary in-gap steps are 1.38–1.41×. Review file (4:2:0, mbtree=0, stream-copied ×3): **1.17 / 1.76×**, vs 2.53 / 3.07× without the ramp. No ghosting in waterfall crops of the ramp frames. Sent as Review D.

## Second scene: rain cabin (2026-09-24, `experiments/vace_loop/rain_v16/`)

Same recipe, unchanged, on the existing rain cabin LTX clip (`user_image/chain`, already the recipe's step 1). `vace16.py rain_v16 --band 100,460,250,370`, 8.7 min VACE; best_splice A = 13, B = 14 (gen[13] / gen[113]).
- `loop_qc` OVERALL PASS. Joins 3.7 / 4.5× → **1.3 / 2.2× after the ramp** (4:4:4); review file 1.16 / **2.76×** at the loop point, which is still below the loop's own biggest step (2.8×, inside the gap). Worse than the waterfall (1.17 / 1.76×).
- **Rain exposes the gap's cadence.** Raw 16 fps VACE has a 4-frame pulse (every 4th step 1.8–2.4× the others; Wan's temporal latent grouping). The waterfall has it too, but milder (1.3–1.5×). Rain can't be interpolated well, so after RIFE ×3 → 24 fps the gap alternates steps of about 0.9 / 0.5× and has one near-duplicate (loop frame 249: 2.3× then 0.2×). The waterfall's gap stays smooth at about 0.8×.
- The raw VACE output also has a 7.8× jump at gen16 frame 64 (luma −10 % in one frame, just before the start context). `match_gap --stabilise` removes the brightness part: window brightness through the gap stays inside the clip's range. What remains is a texture burst of 1.5–1.8× at loop frames 259–263.
- Gap rain-band activity drops to 0.6–0.7× of the clip in the middle of the gap (RIFE softening the streaks, or genuinely less rain).
- The waterfall-band speed check reads 0 on rain (the streaks are too sparse for the median flow): not usable for particle content.
- Crops of the ramp frames: no visible ghosting. **Sent as Review E → FAILED: the rain slows down, almost stops, then starts again.**
- **Diagnosis:** the visible rain is mostly drips on the upper window glass (y 0–260), not streaks in the open window (my speed band). Drip activity (pixels changing > 25 grey per frame, window region) in raw VACE falls to **0.08–0.16× of the real clip** across the gap, and to 0.00 in the final loop at frames 216–248. At raw frame 64 it bursts to 4.5×: the drips catch up to the start context. VACE did this, not RIFE (the RIFE-made frames carry the same energy as the real ones).
- **Causes:** (1) `vace16.py` hard-coded the waterfall's settings, so the gap ran on the waterfall prompt, whose negative includes "storm"; (2) **NAG 9**, which `research/motion-prompting.md` already showed makes motion decay toward zero. Even the old 24 fps rain run with the correct prompt (still NAG 9) sagged to 0.11–0.6×, so the prompt alone isn't enough.
- **Rain prompt + NAG 5 (`rain_v16n5`): barely helps.** Raw gap drips 0.11–0.29× (was 0.08–0.16×), snap 7.3× at raw frame 64, final loop still at 0 mid-gap. Not sent. Prompt and NAG are minor factors; Wan Fun VACE (Lightning, 4 steps) holds fine, position-specific motion still in a masked gap and snaps to the context at the end. (Metric note: the >25-grey drip count under-reads RIFE-made 24 fps frames; trust the raw 16 fps numbers.)
- **NAG off (`rain_v16n1`):** no change (raw gap 0.17–0.24×, snap 7.7×). NAG is not the lever.
- **Non-distilled VACE (`rain_v16full`: no Lightning, 20 steps, CFG 4/3, 135 min on the laptop, ~6 min/step):** **the snap is gone** (raw frame 64: 0.46× vs 7.7×) and relative drip motion roughly doubles (gap ≈ 0.6× of its own context re-render vs ≈ 0.25×). But its drips are faint streaks everywhere, even on the context frames; it doesn't reproduce LTX's bright drips on the window rail. **In the final loop the gap still reads ~0.03× (still).** Joins after the ramp 1.6 / 2.1×; QC PASS. Not sent.
- **RIFE 16→24 thins particle motion ~3×:** 2 of 3 gap frames are blends, so a drip that jumps between raw frames becomes a faint ghost and consecutive-frame change drops about 3×. (My earlier "RIFE frames carry the same energy" check measured static-residual detail, not frame-to-frame change, so it was the wrong test.) The 16 fps VACE trick (right for continuous water speed) works against discrete particles.
- **Conclusion (hypothesis, 1 scene):** ADR 0006 holds for flowing content (water) but not for fine particle motion (drips, rain). Both the model (VACE doesn't match LTX's drip rendering) and the retime (RIFE) lose it.
- **LTX writes the gap (Finding 2 variant b), `experiments/ltx_gap/`.** `gen_job.py` wraps `distilled.prepare_mask_injection`: the source is our RGB frames (49 real end + 50 gap + 46 real start = 145 f, 24 fps, same layout as vace16's gen24), binary mask, context pinned at every step in both stages (stage 1 416×224 × 8 steps, stage 2 832×448 × 3 steps; 7 of 19 latents free). 5.4 min.
  - **rp1 (gap free from step 0): a different shot.** Context reproduces the real frames (MAD ~2.8, the known VAE darkening), but the gap is a new composition: wider framing, different windows, a lit room (QC: 521 px "camera shift", 52 % zoom). The clip itself matches the keyframe. Cause: the distilled schedule sets the layout in step 0, and RePaint pins context only *after* each step, so step 0 sees pure noise in the gap, 49 frames from the only clean anchor; the depth IC-LoRA doesn't hold the layout on its own. (Its rain on the glass looked rich.)
  - Seeded with the full-step VACE gap, pinned for the first k stage-1 steps. Schedule (`constants.py`): 1.0, .994, .988, .981, .975, .909, .725, .42, 0. **k = 1 / 2: no effect** (≈1 % of the seed survives; new framing, and k = 2 added a lamp in the window). **k = 5 (released at σ 0.909): layout held, QC PASS**, joins 3.9 / 4.0× before any ramp.
  - **But k = 5 stalls the drips too:** raw 24 fps gap drip activity 0.01–0.23 vs 0.4–0.6 on the context re-render; final loop 0.05–0.22 mid-gap. k = 6 (released at σ 0.725): QC PASS, same stall (0.05–0.16 mid-gap). This is the clip's own model at native 24 fps with no RIFE. **Conclusion: the stall is inherent to generating a bridge constrained at both ends (flf2v, VACE, VACE full-step, LTX inpainting, LTX RePaint all ease position-specific motion), not to model quality, frame rate or GPU size.** Next direction (user, 2026-09-24): the end and start rain are statistically the same and the room is identical (8 vs 235: 0.21 px shift, luma 20.78 / 20.75, static-region MAD 1.5 vs moving 8.4), so test a closure that doesn't generate specific particles, e.g. a crossover at a motion-matched cut. That conflicts with invariant 10 and needs the user's call.
- **Gate lesson:** `loop_qc` passed a gap where the main motion had stopped. Its per-region speed ratio (0.47–0.71) hinted at it, but that check isn't gated. Needed: a motion-continuity gate on the scene's *visible* moving element (here, glass drips) across the whole gap, not a hand-picked band.

## Recommendation (cheapest first, each gated by `loop_qc.py` + the waterfall-band speed + an eye check)

1. **VACE at 16 fps** (one ~7 min VACE run + RIFE): tests the speed-mismatch hypothesis. Pass: gap waterfall speed within ±3 % of the clip.
2. **Soft temporal RePaint with LTX, variant (a): harmonise the VACE gap** (~5 min per LTX run; patch is ~10 lines in an experiment script). Rain cabin first, then the waterfall. Pass: no step at either splice above the clip's own p99, gap speed within ±3 %.
3. **Variant (b): LTX writes the gap** with the same patch. If it passes, VACE drops out and the loop is single-model.
4. Rented GPU only if 2 and 3 both fail: Frame Guidance loop loss on LTX, or a Cosmos 3 clip. Price it first.
