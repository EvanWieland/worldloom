# E1 — local video baseline on the dev laptop (2026-09-21)

**Evidence level: measured.** RTX 3060 Laptop 6 GB, 64 GB RAM, driver 596.08, WanGP commit `59e5560` (torch 2.10+cu130, sage2 attention, `--profile 4`). Scripts: `experiments/e1_baseline.py`, `experiments/clip_metrics.py`, settings in `experiments/e1/`. Outputs (not in git): `<tools>/e1_out/`. One seed each; treat as a first look, not statistics.

## Results

| Job | Model | Output | Generation time (excl. download) | Peak VRAM | Peak RAM |
|---|---|---|---|---|---|
| Keyframe still | Z-Image Turbo 6B, 8 steps | 1280×720 | ≈ 10 s of denoising (≈ 1 s/step); total 414 s incl. first download | 1.4 GB | 26 GB |
| Video A | Wan 2.2 **5B FastWan**, 3 steps | 832×480, 121 f @ 24 fps (5.0 s) | ≈ 155 s (25 s denoise + ≈ 120 s VAE decode) | 2.8 GB | 29 GB |
| Video B | Wan 2.2 **14B I2V Enhanced-Lightning v2** (FP8), 4 steps | 848×480, 81 f @ 16 fps (5.06 s) | ≈ 415 s (≈ 20 s load, 8 s text, ≈ 330 s denoise, ≈ 52 s decode) | 3.8 GB | **55 GB** |

Downloads consumed ≈ 45 GB of disk in total (Z-Image, 5B, 14B high/low FP8 experts, text encoder).

Model-load and denoise costs are dominated by offloading (`--profile 4` streams weights from RAM); the 14B fits because 64 GB RAM holds the experts. **On a machine with less RAM this would not run**; RAM headroom (55 of 64 GB) is a constraint to respect (no other big processes during generation).

## Quality (same keyframe, same prompt, locked-camera wording)

Metrics from `clip_metrics.py` (pixel units 0–255 luma; frames after the first second for the std figures):

| | 5B FastWan | 14B Lightning |
|---|---|---|
| Diff to keyframe: frame 1 / 4 / 24 / end | 6.2 / 12.5 / 13.9 / 14.9 | 2.3 / 4.4 / 7.0 / 9.6 |
| Adjacent-frame change (mean) | 0.68 (near-frozen after frame ~4) | 1.75 (visible motion, smooth) |
| Mean luma, first → last | 49 → 40 (**−18 %**, darkening) | 49 → 55 (+11 %, slow brightening) |
| Camera shift (phase corr.) | ≈ 1 px | ≈ 0.1 px |
| Temporal std castle region / sky | 4.3 / 2.0 | 6.7 / 3.0 |

Visual (contact sheets): **5B breaks from the keyframe within ~4 frames** — the castle is redrawn with different architecture and a darker grade, then barely moves. **14B keeps identity** (same towers, windows, trees), with drifting clouds, moving valley fog and moon glow; drift is gradual, not a cut.

## Conclusions

1. **The 14B Lightning path is viable locally; the distilled 5B is not** (identity break, darkening, near-static). Use the 14B family as the dev model. Cost ≈ 7 min per 5 s clip → a 60 s chain ≈ 12 windows ≈ 85 min, 3 min ≈ 4.5 h — fine as an unattended, resumable-per-segment job.
2. **A single 5 s clip already drifts** (9.6 px mean diff, +11 % luma). Over minutes this must be controlled (SVI anchor image, colour matching between windows, closure back to frame 0). This is the central risk and is now measurable.
3. **"Temporal std" is a poor shimmer metric** — it lumps real motion, brightness drift and flicker together (castle 6.7 > sky 3.0 despite the castle being the thing that should be still). Need: detrend luma, mask by measured motion, and look at high-frequency residual. Tracked in `PLAN.md` (R7).
4. WanGP's Python API worked first time headless (`init` → `submit_task` → events); the events carried enough (phase, step, %, previews, stdout) to feed our `events.jsonl` design. Observed API quirks: requested 832×480 came out 848×480 for the 14B (rounding to model multiples), 832×480 for the 5B — always read actual size from the output.
5. Practical: VAE decode of the 5B took ≈ 2 min for 121 frames — decode is a hidden cost; the 14B's 52 s for 81 frames is smaller. GPU peaked at 69–71 °C, ≈ 65–70 W (well within limits, no throttling seen).

## Loop closure attempt 1: first = last frame on the plain 14B I2V (Video C)

Same settings as Video B plus `image_prompt_type: "SE"`, `image_end` = the keyframe. 420 s, 4.0 GB VRAM. WanGP does inject the end image into the conditioning for this model (`models/wan/any2video.py`), so this is a model result, not a plumbing bug.

**Result: failed.** The last frame does not return to the keyframe (mean diff to frame 0 at the end 7.4 px, same as mid-clip), the seam ratio is 28× (median tile 13.7×), and motion **collapsed**: sky temporal std 0.8 (vs 3.0 without the end frame), clouds nearly frozen, faint vertical banding in the sky, +12 % brightness jump in the first 12 frames. This is the "static collapse" the loop literature describes. Wan 2.2 I2V-A14B was not trained for end-frame conditioning; Lightning distillation doesn't change that. **Do not use first=last on the plain I2V model.**

## Chaining + end anchor attempt: SVI 2 Pro Enhanced-Lightning, 2 windows (Video D)

`i2v_2_2_Enhanced_Lightning_v2_svi2pro`, 8 steps, windows of 81 f with 4 f overlap (158 frames, 9.9 s @ 16 fps), keyframe as start reference and `image_end`. 1494 s (≈ 12.5 min/window), 3.7 GB VRAM, 58 GB RAM. One seed, defaults otherwise.

**Result: not adequate as tested.**
- Window 1 (frames 0–80) resembles Video B. Window 2 drifts hard: **camera push-in** (phase-correlation shift ≈ −190 px between frame 24 and the end), castle architecture morphs (towers/rooflines change, a lake appears in the valley), mean luma 46 → 60 (**+30 %**), diff to keyframe at the end 20 px (vs 6–9 px for a single window).
- Sparkle artifacts (white specks like snow/stars) appear in the sky from window 1 on.
- **End anchor not honoured**: last frame ≠ keyframe, seam ratio 40× (worse than plain I2V). A single `image_end` may apply to only one window (docs: one anchor per window), but even so the outcome is unusable.
- So SVI's "no drift" claim did **not** hold for this setup (480p, FP8 Lightning, 4-step-distilled experts, locked-camera ambient prompt). Not tried: multiple anchors (one per window), non-Lightning experts, lower LoRA strength, 720p. Revisit only if the alternative below fails.

## Keyframe-anchored clip pool + cross-dissolve (Video E = Video B with seed 7)

Idea: every clip starts from the **same keyframe** (identical, drift-free start state); different seeds give different cloud/fog motion; joining clip *i*'s end to clip *j*'s start with a short dissolve resets drift at every join. Seed-7 clip: 419 s (same cost as seed 42), 3.8 GB VRAM, 55.6 GB RAM.

Per-clip drift differs by seed: seed 42 ends 9.6 px from frame 0, ≈ 0 px camera shift; seed 7 ends 14.5 px away, ≈ 15 px shift. **Per-clip QA gates are required.**

Dissolve test (`experiments/dissolve_test.py`, smoothstep alpha; ratio = worst 4×4-tile frame change inside the transition ÷ median tile change elsewhere; 1.0 = indistinguishable from normal motion):

| Case | Transition | Luma normalised | Worst tile ratio | Median tile ratio |
|---|---|---|---|---|
| Self-loop of clip A (tail → own head) | 24 f (1.5 s) | no | 1.89 | 0.99 |
| Self-loop | 24 f | yes | 1.71 | 0.91 |
| Join A → B | 24 f | no | 2.21 | 1.06 |
| Join A → B | 24 f | yes | 2.04 | 0.97 |
| Join A → B | 12 f (0.75 s) | yes | 1.89 | 1.03 |
| *(for comparison)* first=last conditioning | – | – | 28 | 13.7 |
| *(for comparison)* SVI + end anchor | – | – | 40 | 18 |

Contact sheet of the join: castle, terrain and moon line up (same keyframe), only sky/fog dissolve, no ghosting. Without normalisation the mean luma dips 53.7 → 49.1 across the join; normalisation to the keyframe's mean removes it.

**Conclusion: this beats both generative closure methods by more than 10× on the seam metric and costs nothing extra.** It is the working design (ADR 0004, proposed). Not yet verified by a human watching real playback; metrics are pixel-based, not perceptual.

## Clip yield across 6 seeds, and a gate correction (2026-09-21)

Rendered 4 more seeds (101–104) at 848×480 to measure how often a clip stays usable for a full 5 s. Structural gate (`hub_pingpong.py`, edge-mismatch on the castle body vs frame 0, threshold 0.35) result: **only seed 42 (81/81 frames) and seed 104 (76/81) kept the full clip; seeds 7, 101, 102, 103 were cut to 9–12 frames.**

Investigating *why* the others cut off that early: a direct camera-shift measurement (phase correlation, frame 0 vs frame 11 vs last frame) showed **shift at frame 11 was <1 px for every seed, including the failing ones** — so the structural gate is not catching gross drift that early; it is reacting to something finer (likely shimmer/texture change in the castle detail, not yet characterized). The real, large signal shows up by the end of the clip:

| Seed | Shift @ frame 11 | Shift @ last frame | Structural gate kept |
|---|---|---|---|
| 42 | 0.02 px | 0.11 px | 81/81 |
| 104 | 0.08 px | 0.10 px | 76/81 |
| 7 | 0.60 px | 8.28 px | 9/81 |
| 101 | 0.54 px | 4.66 px | 12/81 |
| 102 | 0.90 px | 6.24 px | 9/81 |
| 103 | 0.92 px | 5.96 px | 9/81 |

**Corrected finding: the reliable, meaningful gate is camera drift by end-of-clip (ties directly to the "unintended camera motion" check in `QUALITY.md`), not the early structural-mismatch trip.** Yield by this measure: **2 of 6 seeds (33%) hold a locked camera for the full 5 s**; the other 4 drift 4.7–8.3 px by the end even though nothing looks obviously wrong in the first second. A seed-7 style gross identity break (spires/balconies changing, confirmed visually) is a separate, rarer failure mode layered on top of the drift.

**Consequence:** the structural gate as first implemented is not yet trustworthy as the sole accept/reject signal — it needs the camera-shift measurement alongside it (or in place of it) before being used for real per-clip QA. This is now `research/quality-metrics.md`'s job (R7), not settled here.

## Does a smaller frame speed up testing without ruining it? (same seed 42, same prompt/keyframe, 81 frames)

| Size | Wall | Denoise | Decode | Fixed (load + text) | Peak VRAM | Speed vs 848×480 |
|---|---|---|---|---|---|---|
| 848×480 | 415 s | 331 s | 52 s | ≈ 29 s | 3.8 GB | 1× |
| 640×352 | 231 s | 164 s | 30 s | ≈ 35 s | 2.8 GB | 0.55× |
| 448×256 | 134 s | 84 s | 15 s | ≈ 34 s | 2.8 GB | 0.32× |

Denoise time tracks pixel count almost linearly (0.50× and 0.25× for 0.55× and 0.28× the pixels); a ≈ 35 s fixed cost (model load + text encode) does not shrink, so returns diminish below ~448×256. RAM peak stays at 55 GB regardless of size (weights dominate).

**What survives at small sizes** (visual + metrics): keyframe identity (same towers/windows/trees), locked camera (shift ≤ 0.6 px), gentle cloud/fog motion, no early break. **What does not transfer:** the *specific outcome* — the same seed gives different cloud/fog motion at each size (mean abs diff to the 848 clip, downscaled: ≈ 2 at frame 0 but 8–12 mid/end), so approving a small preview does not approve the large clip. Per-clip drift was 9.6 / 16.2 / 10.3 px (848 / 640 / 448) with no trend and a luma change of +11 % / +24 % / +9 % — comparable to the seed-to-seed spread at one size (seed 7 @848: 14.5 px), i.e. single-clip drift is noisy at every size and gates must be calibrated on the real dev size with many seeds. Fine detail (window lights, tower edges) is visibly softer at 448×256; shimmer/artifact judgments and SR feasibility cannot be made there.

**Rule adopted:** small size is for *screening and plumbing*, never for gate calibration or final approval. T1 = 448×256, ≈ 2.2 min/clip (was ≈ 7 min); T2 = 848×480 (≈ 7 min) until E5 says otherwise. Pipeline-engine tests (fingerprints, resume, events, assembly) don't need real generation: use synthetic or tiny clips.

## E5 — enhancement path (2026-09-21): RIFE + FlashVSR on the good (seed 42) clip

Ran independently via WanGP's `submit_media_postprocessing` (`experiments/e5_enhance.py`), each on the original 848×480/16fps clip.

**FlashVSR ×4 spatial upscale: 3392×1920, 1190 s (≈ 20 min) for 81 frames.** Zoomed crop comparison (source vs upscaled) shows genuine detail recovery — window mullions, stone coursing, roof tile texture all resolve, not just smoothed. **Conclusion: 480p is a viable source resolution for the enhance stage**; this settles the open "is 480p→4K acceptable" question in favor of yes, at least for this content. 3392×1920 is short of true 4K UHD (3840×2160) — needs either `flashvsr*4` on a slightly larger source, a second small upscale pass, or padding/crop; not yet decided.

**RIFE ×2 temporal upscale (16→32 fps): 161 frames, 14 s.** Visual spot-check first *appeared* to show the interpolated frame warping the castle roofline — but this only showed up when the crop happened to include the specific dormer/roofline region, and reproduced consistently at 4 points in the clip (frames 0–2, 20–22, 60–62, 158–160), which first looked like a real RIFE defect. A whole-clip quantitative check (edge-map mismatch of every interpolated frame vs the average of its two real neighbors, vs. a real-frame-to-real-frame baseline over the same 2-frame gap) contradicted that: interpolated-frame mismatch averaged **0.054**, actually *below* the real-to-real baseline of **0.099** (ratio 0.55×), and **0 of 80** interpolated frames exceeded 2× baseline. **Conclusion: RIFE is not introducing an anomaly** — the visual effect is very likely the base model's own known fine-detail flicker (dormers/roofline) showing up in both real frames, which RIFE faithfully interpolates rather than hides. This is consistent with, not new evidence beyond, the already-flagged static-region shimmer risk. **Methodology lesson: a handful of visual spot-checks (even reproducible ones) can mislead; a whole-clip quantitative check is required before concluding a tool is defective** — recorded as a process note, not just a result.

## E8b — does a reinforced anti-drift prompt raise yield? (2026-09-21)

Regenerated 6 more seeds (201–206) at 848×480 with an explicit "structure never changes" clause added to the positive prompt and camera/morph terms added to the negative prompt (`experiments/e1/i2v_14b_seed_template.json`). Gated with `experiments/clip_gate.py` (camera-shift ≤ 1.5 px):

| Seed | Camera shift (px) | Accept |
|---|---|---|
| 201 | 7.06 | ✘ |
| 202 | 2.39 | ✘ |
| 203 | 0.04 | ✔ |
| 204 | 0.02 | ✔ |
| 205 | 4.25 | ✘ |
| 206 | 3.52 | ✘ |

2 of 6 — identical ratio to the original batch (42, 104 of 42/7/101/102/103/104). **Combined: 4 of 12 (33%) across two independently-prompted batches. Conclusion: this prompt reinforcement did not move yield; camera drift is not simply a prompting problem** at this step count/distillation level. Cost per usable clip stays ≈ 3× (≈ 21 min at 848×480). Untried: more steps, non-distilled experts, different LoRA strength, lower motion-intensity language.

## Multi-clip pool sample (2026-09-21)

With 4 accepted clips (42, 104, 203, 204) in hand, built an 8-leg pool (`experiments/hub_pingpong.py`, order A,B,C,A,D,B,C,D, no immediate repeats), 80 s at 848×480. All 4 clips gate cleanly (kept 81/81 frames each at the diagnostic structural threshold too). Sent to the user for a longer viewing (previous verdict was on a single repeated clip). **Verdict pending.**

## Motion speed: review finds the motion far too fast (2026-09-21)

Reviewer on the 80 s pool sample: everything moves too fast, as if sped up. On the untouched seed-42 WanGP clip: everything far too fast, with heavy light flicker, tree sway and racing clouds.

- **Not an encoding bug:** 16 fps with matching frame counts at every stage (WanGP output 81 f / 5.06 s; ping-pong raw and final 1280 f / 80.0 s).
- **It is the generation:** the raw model output already looks too fast. Likely causes: Wan's 16 fps / 5 s clip packs a lot of motion; the prompt asked for five motion types at once (clouds, fog, trees, flickering windows, moonlight), and the 4-step Lightning model shows all of them strongly. None of our gates measure motion *speed* (camera-lock gate only checks position) — a new, missing quality axis.
- **Lever 1, slow motion by interpolation:** RIFE ×2 / ×3 played back at 16 fps = ½ / ⅓ speed, every frame kept (161 f / 10.06 s and 241 f / 15.06 s). RIFE ×3 took 5.6 s. Side benefit: 3× more footage per generation, which offsets the 33 % yield. Samples sent to the user; verdict pending.
- **Lever 2, calmer prompt:** fewer motion types, "barely perceptible", negative prompt against time-lapse / fast clouds / flickering lights / swaying trees (`experiments/e1/calm_r448_s*.json`, 448×256). Measured on seed 42 vs the old prompt at the same size (`experiments/motion_speed.py`): overall flow 2.85 → 2.04 px/s (−28 %), sky 3.85 → 2.72 (−29 %), bright-pixel blink rate 0.0165 → 0.0125 (−24 %). **Reviewer: the second clip is calmer.** Adopt the calm prompt style. **But across 3 calm seeds (42 / 203 / 204) flow was 2.04 / 2.68 / 3.54 px/s and blink rate 0.0125 / 0.0042 / 0.0217** — seed 204 is faster and flickerier than the old-prompt seed-42 clip (2.85 / 0.0165). Seed-to-seed variation is larger than the prompt's effect, so the prompt alone can't guarantee calm; per-clip motion-speed gating (or slow motion) is needed. All three passed the camera-lock gate at 448×256 (0.06–0.09 px; gate calibrated at 848×480).
- Slow motion measured on the full-size seed-42 clip: flow 3.57 → 1.85 (½ speed) → 1.30 (⅓ speed); blink rate 0.0026 → 0.0002 → ≈ 0. Stronger lever than the prompt. Combined calm + ½ / ⅓ samples sent; speed verdict pending.
- **Speed verdict:** shown calm seed 42 at normal / ½ / ⅓ speed, **the user chose ½ speed**. Delivery arithmetic: 16 fps source × RIFE ×3 = 48 frames per source-second; played at 24 fps = ½ speed exactly. 30 fps would need 3.75× (RIFE only does 2/3/4), so 24 fps is the natural delivery rate.
- **Does slow motion cost quality?** (user asked) Sharpness (Laplacian variance, `experiments/interp_sharpness.py`) on the RIFE ×3 full-size seed-42 clip: real frames 182.3, invented frames 179.2 (−1.7 %); castle band −1.2 %; worst single invented frame −9 to −10 % vs its real neighbours. Negligible on average; the possible artefact is a faint sharpness pulse at 8 Hz (real frame every 3rd at 24 fps) — to be judged by eye on the full-size sample. Quality is dominated by the 848×480 generation + FlashVSR upscale, not by frame rate.
- **Fix it before generation instead?** (user asked why slow down at all). Input-side levers found in WanGP: (a) `motion_amplitude` — code only acts when > 1 (`models/wan/any2video.py` ~l.773), so it can add motion but never reduce it: useless here. (b) **NAG (Normalized Attention Guidance)** — the Lightning model runs at guidance_scale 1 (CFG off), which means **the negative prompt was very likely ignored in every run so far**; NAG restores negative-prompt effect for distilled models and is enabled for Wan i2v (`wan_handler.py`: NAG for t2v/i2v), default off (`NAG_scale` 0). Queued test: calm prompt + NAG_scale 5 and 9 on seeds 42 and 204 at 448×256 (`experiments/e1/nag*_r448_s*.json`), runs after the full-size batch. Other input-side options not yet tried: non-distilled Wan (real CFG, ~30 steps, far slower); LTX-2.x, which conditions on frame rate. Slow motion stays the fallback because it is proven and cheap.
- **Calm prompt at full size, 9 seeds (301–309, 848×480, NAG off):** camera lock **9 / 9** passed (shift 0.04–1.02 px) vs **4 / 12** with the old prompt. Removing the extra motion types and asking for a "completely static camera" fixed most of the camera drift, so yield is no longer the cost problem it was. Motion at normal speed 3.24–3.86 px/s for 8 clips (all over the provisional 2.4 limit, so all need ½ speed); seed 303 at 11.0 px/s is a clear reject (clouds race over and cover the moon, fog billows, an orange glow appears under the castle that the keyframe does not have) — the flow gate catches it unaided. Note: calm clips measure faster at 848 (≈3.4) than the calm seed 42 at 448 (2.04), another reason gates are calibrated at the dev size.
- **NAG test (448×256, calm prompt, seeds 42 / 204):** flow 2.04 → 1.47 (NAG 5 and 9 alike) and 3.54 → 2.24 / 2.15 — **both under the 2.4 limit at normal speed**. No extra time (~140 s per clip either way). Reduction comes from castle/fog/trees; sky flow unchanged or slightly up (3.7 → 4.2 on seed 204); blink rate mixed. Sent seed 204 off/on to the user. **Full-size NAG 5 (848×480, same seeds without / with):** 301 3.46 → 2.83 (−18 %), 302 3.35 → 2.09 (−38 %), 304 3.40 → 3.30 (−3 %), 306 3.24 → 2.19 (−32 %); avg ≈ −23 %. 2 of 4 pass the 2.4 limit at normal speed (0 of 4 without). Camera lock unaffected, +1–3 % time, blink slightly lower. **Conclusion: keep NAG on by default (free, always in the right direction) but it cannot guarantee calm alone at full size.** Candidate combination: NAG + ¾ speed (RIFE ×2 → 24 fps: 32 source frames per 24 output = 0.75 speed, only every other frame invented) instead of ½ speed (RIFE ×3). Seed 306 NAG + ¾ speed measured 1.65 px/s vs NAG-off + ½ speed 1.72. **Reviewer, on both versions of seed 306 and the 160 s sample: very good; the pine trees sway slightly too much in both.** → default becomes **calm prompt + NAG 5 + ¾ speed** (equal calm, fewer invented frames).
- **Pine sway** (foreground pines, box x 0–25 %, y 45–100 %; `motion_speed.py --box 0,0.45,0.25,1`): the busiest region, 2–3× overall motion; NAG reduced it only 15–23 % (302: 6.85 → 5.84; 306: 7.05 → 5.44). The calm prompt never mentioned trees and the "swaying trees" negative was inert before NAG. Tested explicit "pine trees stand completely still; there is no wind" + wind/branches negatives, NAG 5 and 9, seeds 302/306 at full size (`experiments/e1/still_nag*_s*.json`). The pine box also contains fog, so motion was split into dark pixels (tree silhouettes, ≤ 35th percentile of the box in frame 0) and bright pixels (fog behind): seed 306 trees 3.24 (NAG 5, old prompt) → 1.52 (tree prompt, NAG 5) → **1.15 (tree prompt, NAG 9; −65 %)**; seed 302 trees 4.57 → 5.85 → 5.13 (no improvement). NAG 9 beat NAG 5 on every measure (overall 302: 1.60, 306: 1.16 — both calm at normal speed). **Conclusion: the tree prompt works on some seeds and not others, like camera drift and overall speed → foreground sway needs its own per-clip gate on a "must stay still" region** (the plan stage must supply such regions per scene; B1's is the pine box). Default prompt/NAG: tree-still prompt, NAG 9. Both clips sent at ¾ speed. **Reviewer: both look good; 306 is excellent for a calmer scene, 302 for a scene where wind is expected.** → sway is not a defect to gate out; motion level is a per-scene, per-element creative parameter (recorded in `ARCHITECTURE.md` § Scene representation and `QUALITY.md`). Note the original B1 prompt asks for "trees moving gently in the wind", so the tree-still prompt is only right for scenes specified as calm.
- **8-clip calm half-speed pool (full size, NAG off):** seeds 301/302/304/305/306/307/308/309 slowed with RIFE ×3 → 24 fps (`experiments/slowmo_batch.py`), all pass the delivered-clip gate (shift 0.06–1.0 px, flow 1.45–2.22 px/s). 8 ping-pong legs, shuffled, 3840 frames / 160 s at 24 fps; sent for review (re-encoded at CRF 19). `hub_pingpong.py` rewritten to stream frames (one uint8 clip in memory) — the in-memory float version needed ~19 GB and would have starved the generation job.
- **Stars:** human noticed the old-prompt clip had stars and the calm one didn't. The keyframe has **no stars**, so the model invented them (same white specks as the "sparkle artifacts" in the SVI test and seed 7). They twinkle, so they add to the flicker. The calm negative prompt (flickering / blinking / strobing) suppressed them as a side effect. Stars are a creative choice the user didn't request, so the pipeline must not add them silently; if requested, they belong in the keyframe and must stay steady.

## Ping-pong seams on faster ("gentle") motion (2026-09-22, real pipeline output)

**Reviewer, on the 4-clip `gentle` pipeline output (`runs/b1_demo`, pool 4):** quality high, but the transitions are jarring; the clip joins are obvious. The calm half-speed sample had been approved (very good).

Measured (optical-flow velocity jump at the seam frame ÷ median frame-to-frame velocity jump, 448 px width):

| | gentle (jarring) | calm ½ speed (approved) | gentle, eased turnaround |
|---|---|---|---|
| typical motion | 0.31 px/frame | 0.084 px/frame | 0.27 px/frame |
| turnaround (clip reverses) | **3.9–6.9×** | 1.1–2.1× | **≈ 0** |
| junction (leg → next leg) | 1.8–1.9× | 0.9–1.1× | 0.5× |

**Conclusion:** the snap-reverse at the turnaround is the dominant visible seam, and it scales with motion speed. At calm speeds it is hidden; at gentle speeds it is not. This answers the open ADR 0004 question "is reversal noticeable on directional motion?": yes, once motion is ~4× the calm pace.

**Eased turnaround prototype** (`eased_legs.py`, scratch — not yet in `looper/`): RIFE ×4 for dense frames, then playback speed eases to zero over the last/first 24 output frames (1 s, cosine) at both ends of each forward half; fractional positions blended between neighbouring dense frames. Both seam types drop below normal motion. Legs go from 13.3 s to 15.3 s. Whether a stop-and-reverse "pendulum" reads as natural is a human question. **Verdict: no.** Reviewer on the eased version: the back-and-forth itself feels wrong and too obvious; the scenes are probably too short; clouds do not slide back and forth across the sky like that. So the eased turnaround fixes the jolt (measurable) but not the reversal (perceptual). Ping-pong is only viable for motion with no visible direction (the calm sample passed because clouds barely moved). Two requirements fall out: **forward-only motion** and **long continuous segments** (seams every 5 s are inherently too frequent). Next experiment: SVI 2 Pro forward chaining with the calm recipe (its earlier failure used the hyper-speed prompt, no NAG).

## Forward continuation, take 1: SVI 2 Pro with keyframe anchor + calm recipe (2026-09-22)

2 windows (81 f, overlap 4 → 158 f), `i2v_2_2_Enhanced_Lightning_v2_svi2pro`, 8 steps, calm prompt, NAG 9, keyframe as start/anchor, seed 306. 1454 s (≈ 12 min/window), 3.7 GB VRAM, 57 GB RAM.

- Camera lock across both windows: **0.17 px** (frame 0 → 157). Castle identity held (edge mismatch flat at 0.72–0.74 through the clip). So the calm recipe fixed the push-in/morph seen in the first SVI test.
- **But the window seam is a hard cut**: adjacent-frame difference at frame 80→81 is 25.8 vs a 2.29 median (**11×**); mean luma 49 → 59; the contact sheet shows heavy cloud over the moon at frame 80 and a clear moon at 81. SVI's anchoring restarts each window from the keyframe state — it reproduces the clip-pool cut inside one file. Velocity-jump at the seam was only 0.7× (that metric measures motion change, not appearance change — an appearance-cut check belongs in `validate.py`).
- Motion is still fast (7.7–8.3 px/s per window). Contributing cause found: the interpret stage copied "trees swaying gently in the wind" into the **keyframe (T2I) prompt**, so the still itself shows wind-blown foliage and the video model animates it. T2I prompts should describe appearance, not motion verbs — an interpret.py fix.
- Adapter bug found: WanGP lists per-window files then the combined clip last; `wangp._relocate` took `files[0]` (window 1 only). Fixed to take the last file.

## Forward continuation, take 2: plain sliding windows, no anchor — **works** (2026-09-22)

`i2v_2_2_Enhanced_Lightning_v2`, 2 windows of 81 f, overlap 1 (the model's maximum), 4 steps, calm prompt, NAG 9, seed 306 → 161 f. 822 s (≈ 6.9 min/window, same per-window cost as single clips), 3.9 GB VRAM, 55 GB RAM.

| | value |
|---|---|
| seam (frames 77–83) adjacent-frame change | 1.2–2.5 vs median 1.84 — **no cut**; the clip's largest change anywhere is 1.6× median (frame 0) |
| camera shift 0→80 / 80→160 / 0→160 | 0.18 / 0.15 / **0.21 px** |
| mean luma 0 / 80 / 160 | 67 / 70 / 72 (+7 % over 10 s) |
| castle edge mismatch vs frame 0 at 40 / 80 / 120 / 160 | 0.38 / 0.39 / 0.44 / 0.46 (slow rise — watch over longer chains) |
| flow, window 1 / 2 | 5.07 / 4.14 px/s (still above calm; keyframe shows wind-blown grass — interpret fix pending) |

Window 2 genuinely continues window 1: same moon, castle, fog. **This is the generation model to build on: forward chains, no reversal.** Seam stays invisible to a human? Sent for review.

### 6 windows / 30 s: seams stay invisible, the image drifts

Same settings, 481 f, 2372 s (6.6 min/window). Per window end:

| window | camera vs 0 | luma | castle mismatch | flow px/s |
|---|---|---|---|---|
| 1 | 0.18 | 70.4 | 0.39 | 5.07 |
| 2 | 0.21 | 71.9 | 0.47 | 4.14 |
| 3 | 0.23 | 73.2 | 0.55 | 4.20 |
| 4 | 0.26 | 75.5 | 0.65 | 4.06 |
| 5 | 0.23 | 80.8 | 0.73 | 3.77 |
| 6 | 0.23 | 86.0 | 0.77 | 3.30 |

All five seams ≤ 1.6× median frame change (invisible). Camera stays locked. But each window is conditioned on the previous window's *generated* last frame, so error compounds: luma +23 % by 30 s, castle mismatch doubles, and visually the sky degrades from real clouds (0–10 s) to smeared painterly texture (20 s) to colour blotches (30 s); fog flattens to white; motion slows. **Usable chain length at this recipe ≈ 2–3 windows (10–15 s).** Drift, not seams, is now the binding constraint on loop length — PLAN.md risk 4, confirmed.

Untested levers, cheapest first: WanGP's `sliding_window_color_correction_strength` (matches colour between windows at generation time); `sliding_window_overlap_noise`; lower-motion prompt (less to drift); non-distilled model with real CFG and 20–30 steps (~5× slower); periodic re-anchoring to the keyframe *with* a generated transition instead of SVI's cut.

## Loop closure by generated bridge (VACE) — negative as configured (2026-09-22)

`vace_14B_lightning_3p_2_2`, control video = chain's last 16 f + 49 grey + first 16 f, mask keep/generate/keep, `video_prompt_type` VUA, 832×480, seed 306. 1937 s incl. ~35 GB download; **VRAM peak 5.9 GB of 6.0** — at the ceiling. Measured on chain + gap looped twice:

- VACE re-rendered the *kept* frames ≈ 11 luma darker than the chain (mean abs diff 11–12; 4.8–5.3 after removing the offset).
- The generated gap has ~⅓ of the chain's motion (median adjacent change 0.55 vs 1.84).
- Inside the bridge, steps at both kept/generated boundaries: 15× and 28× the bridge's median.
- Loop joins: appearance 5.6× (chain→gap) and 9.9× (gap→chain); velocity 7× and 21×. Luma-matching the bridge and blending 16-frame overlaps did not help (still 9.7× / 20×) — the mismatch is structural.

**Conclusion:** this VACE setup (Lightning 3-phase, raw grey-gap control) does not respect its boundary frames well enough for closure. Untried: non-Lightning VACE with CFG (slower, ~same VRAM ceiling), longer overlaps (32 f), and the dedicated `flf2v_720p` (Wan 2.1 first-last-frame model, trained for exactly start+end conditioning — unlike the i2v end-image hack that collapsed) — ~30 GB more weights; disk now ≈ 48 GB free.

## Loop closure by dedicated first-last-frame model (flf2v_720p) — best generative result so far (2026-09-22)

`flf2v_720p` (Wan 2.1 FLF2V 14B, auto-quantized to the int8 checkpoint, 17 GB), real CFG (30 steps, guidance 5, not distilled), 848×480 (diagnostic tier — native at 720p would be ~3x slower), calm/NAG-9 recipe, seed 306. `image_start` = the forward-continuation chain's last frame, `image_end` = the chain's first frame, closing the loop directly (no separate "gap" video). 4046 s (≈ 67 min, incl. one-time 17 GB download); VRAM/RAM not sampled this run (add next time). `experiments/l1_flf2v_closure.py`, deleted after this writeup.

Measured (`experiments/l1_measure_closure.py`, deleted after this writeup) against the same chain used for the sliding-window test (`slide_2w_s306.mp4`, 161 f):

| Junction | Appearance ratio (vs median adjacent-frame diff) | Velocity ratio (vs median optical-flow jump) |
|---|---|---|
| chain-end → bridge-start (same source image, sanity check) | 1.32× | 0.20× |
| **bridge-end → chain-start (the actual closure)** | **2.77×** | **1.35×** |

For comparison, everything tried before on the same kind of metric: first=last I2V hack 28×; SVI+anchor 40×; VACE bridge 5.6–9.9× (appearance) / 7–21× (velocity); the *accepted* keyframe-pool dissolve join 1.89–2.21× (worst-tile metric, not directly comparable but same order of magnitude).

**This is the best generative closure result by a wide margin** — the closure join is within ~2-3x of normal motion instead of 6-40x, in the same neighborhood as the dissolve join we already accepted. Other observations: bridge's own motion slows toward the end (flow 0.276 px/frame at the start → 0.079 at the end, i.e. it appears to be genuinely easing toward the target end-image, not just cutting to it); luma drifts 68.0 → 61.8 (−9%) over the bridge, comparable to single-clip drift seen elsewhere, not a collapse. Sent a 30 s sample (chain + bridge, played 2×) to the user for a perceptual verdict — **metrics alone have been wrong before (E7)**, so this is not yet a pass. **Verdict pending.**

**Human verdict: fail — the frames lose quality toward the end.** Confirmed and quantified, not just subjective: extracted frames 0/20/40/55/65/70/75/78/80 show a blocky/checkerboard artifact building up in the sky (worst near the top-right, away from the moon) through the middle-to-late bridge, invisible at frame 0/20, clearly visible by 40, worst around 65–70, then it snaps clean again by 78–80 as the model locks onto the target end-image. Quantified with Laplacian variance (high-frequency energy) on a sky ROI (x 500–848, y 0–150, no moon/castle): 589 (frame 0) → 793 (20) → 905 (40) → **1155 (70, peak, ≈2×)** → 524 (80, back to baseline). None of the metrics used to call this a pass (appearance ratio, velocity ratio, mean luma) are sensitive to this kind of spatial noise — they're all frame-difference or brightness measures, not texture/frequency measures. **This is a real gap in the QA gate set (R7), not a one-off miss.**

Likely causes, untried: (a) the auto-picked **int8-quantized checkpoint** — quantization artifacts classically show up as blocky noise in smooth, low-detail regions like a plain sky; the non-quantized `wan2.1_FLF2V_720p_14B_mbf16` (no `_quanto_`) is available but ~2× the size, may not fit comfortably even with RAM offload. (b) **Off-native resolution** — this model's default/trained resolution is 1280×720; this test ran at 848×480 (diagnostic tier) for speed. Either is a plausible, cheap-ish next experiment; both cost roughly one more ~1–2.5 h GPU run. Not yet decided which to try, or whether to abandon this branch for L3 (attack drift on the sliding-window chain instead) — ask the user before spending more GPU time (see `STATE.md`).

### L1b — isolating the artifact: native resolution vs quantization (2026-09-22)

User asked to test both causes with shorter clips. Same inputs/seed/prompt/NAG 9, 33 frames (~2 s), native 1280×720 (`experiments/l1b_flf2v_run.py`, deleted after writeup). Sky-noise ratio = Laplacian variance of the top-right sky ROI ÷ the same bridge's frame 0 (relative, since absolute values change with resolution). Joins measured with the bridge area-downscaled to the chain's 848×480.

| Run | Wall | Peak VRAM / RAM | Sky noise peak (frame) | Closure appearance / velocity | Start-join appearance / velocity |
|---|---|---|---|---|---|
| Original: int8, 848×480, 81 f | 4046 s | not sampled | 1.95× (72), ≥1.33× from frame 8 | 2.77× / 1.35× | 1.32× / 0.20× |
| **A: int8, 1280×720, 33 f** | 3360 s (~109 s/step) | 4.7 GB / 43.7 GB | **1.23× (5)**, ~1.05× from frame 18 | **1.69× / 0.95×** | 1.15× / 0.86× |

**A: the blocky sky tiling is gone by eye** (frames 16, 28 checked; only a faint vertical streak texture top-right late in the clip). At matching absolute frame indices (8–32) the original was already 1.33–1.40× while A stayed at 1.02–1.21×, so the shorter clip alone doesn't explain it. **Most likely cause: running the 720p-trained model at 848×480.** Clip length is still partly confounded (a 2 s bridge has less time to degrade). Bridge motion eases 0.40 → 0.13 px/frame into the target (chain median 0.35), and luma goes 68.0 → 63.1 against a chain start of 64.6. Sample sent to the user (`e1_out/flf2v_closure/SAMPLE_loop_native720_int8_3x.mp4`, chain + bridge ×3). **Human verdict: fail — it freezes completely for a few seconds.** The easing measured above is the cause. Bridge flow decays 0.40 → 0.13 px/frame against a chain median of 0.35, so the scene visibly stalls into the target frame. The join metrics passed because they only compare adjacent frames at the seam. None of them measures motion *level* across the bridge. **Lesson: a closure must keep motion at the chain's level throughout the bridge, not just match at the seam frames.** A gate is needed: median bridge flow ÷ chain median flow ≥ ~0.8, plus no sustained low-flow run. FLF2V with a 2 s bridge shows a milder form of the same static-collapse tendency seen with first=last conditioning. **B, retried with `--profile 5` (streams instead of pinning) — succeeded.** 4458 s (≈74 min, slower per step: ~145 s vs int8's ~110 s), peak 5.5 GB VRAM, **56.7 GB RAM** (tight; free RAM dipped to 7–10 GB mid-run, close to the low-memory guard that killed the profile-4 attempt, but held). Same seed/prompt/inputs as A.

| Run | Sky noise peak (frame) | Closure appearance / velocity | Start-join appearance / velocity |
|---|---|---|---|
| A: int8, profile 4 | 1.23× (5) | 1.69× / 0.95× | 1.15× / 0.86× |
| **B: unquantized bf16, profile 5** | **1.16× (5)** | **1.57× / 1.19×** | 1.16× / 0.53× |

Visually clean (frames 16, 28 checked) — indistinguishable from A. **Conclusion: quantization was not a meaningful contributor to the blocky-sky artifact.** Native resolution was the fix; int8 is fine to use going forward (also the only variant that reliably fits this machine's RAM under normal pinning). The unquantized checkpoint (31 GB) can be deleted once this is settled — kept for now in case a future artifact needs re-isolating.

### L1c — does a full-length (5 s) native-res bridge still degrade? — **infeasible on this hardware as configured** (2026-09-22)

Both A and B were 2 s (33 f) diagnostics; the original 848×480 failure needed most of its 5 s (81 f) to show the artifact, so length itself was a confound. Attempted int8 @ 1280×720, 81 f, same inputs/seed (`experiments/l1b_flf2v_run.py flf2v_720p 1280x720 81 native720_int8_81f`, `--profile 4`).

**Killed after step 1/30 took 6639 s (≈110.6 min) — 60× A's ~110 s/step for only 2.45× more frames (33→81).** At that rate, 30 steps would take ≈55 h. Not simple linear/quadratic attention scaling (would predict ~5–8×, i.e. 550–900 s/step); this is disproportionate enough to indicate thrashing, most likely severe RAM↔VRAM shuttling once both the frame count and the native 720p tensor size are large together (profile 4 streams weights layer-by-layer from RAM; the combination may force much smaller, much more frequent transfers than either dimension alone). GPU showed 100% utilization throughout but only 34–37 W (vs the ~65 W seen in every successful run), consistent with a bandwidth-bound rather than compute-bound step. RAM/VRAM/disk-queue looked fine during the stall (no classic OS-level thrashing), so the bottleneck is internal to WanGP's offload scheduling at this combination, not system-wide memory pressure.

**Conclusion: on this 6 GB / 64 GB machine, `flf2v_720p` at native resolution only works at short clip lengths (~33 f / 2 s confirmed good); full 5 s (81 f) native-res generation is not practical with `--profile 4`.** Untried, cheapest first: `--profile 5` (streaming, worked for B despite being unquantized — may handle the frame/resolution combination better than 4's full pinning), an intermediate length (e.g. 49–65 f) to find where the cliff is, or accept 2–3 s bridges as the design point (a shorter bridge is not obviously bad for the pipeline — the chain itself already went 10–15 s before the bridge is needed). **L1/L1b are otherwise settled: native resolution fixes the artifact, quantization doesn't matter, but bridge length is capped by generation cost, not just quality, at native res.**

## Not yet measured

Combined RIFE+FlashVSR pipeline (tested independently only); exact 4K framing (3392×1920 from `flashvsr*4` is short of 3840×2160 — pad/crop or different source size undecided); deflicker for the fine-detail flicker found in E5; re-encode cost of a full assembled sequence at 4K; whether more inference steps or a non-distilled model raises yield.

## A0/A1 — motion-level gate quantifies the freeze; flow-constant retime fixes it numerically (2026-09-22)

**A0** (`experiments/a0_gates.py`, no GPU): built the four gates from `PLAN.md` Phase A0 — motion-level (median flow per 8-frame block vs the chain's own median, target 0.8–1.25×, no 2-block run below 0.8×), motion-direction (block angle vs chain's own spread), spatial-noise (sky-ROI Laplacian ÷ frame 0, ≤1.3×), sharpness-continuity (bridge ÷ chain Laplacian, 0.8–1.25×). Self-check: synthetic constant-motion bridge passes, synthetic near-frozen bridge fails (ratios 0.99–1.0× vs 0.002–0.005×).

Run on the existing chain (`slide_2w_s306.mp4`) against both native-res L1b bridges (bridge downscaled to the chain's 848×480 before comparing, matching how the pipeline actually joins them):

| | int8 | bf16 |
|---|---|---|
| motion-level ratio per block (4 blocks, 33 f) | 0.671, 0.592, 0.552, 0.518 | 0.453, 0.522, 0.450, 0.381 |
| motion-level gate | **fail** (below 0.8 from block 1, worsens monotonically) | **fail** |
| motion-direction gate | pass (chain's own direction spread is wide — locked camera, low motion) | pass |
| spatial-noise gate | pass (max 1.16×) — confirms native-res fix holds | pass (max 1.13×) |
| sharpness-continuity ratio | 0.627 (**fail**) | 0.595 (**fail**) |

**Confirms the human verdict quantitatively and adds a new finding**: the ease isn't a late-clip effect, it's present from the first 8-frame block onward. Metrics that only look at seam frames (all prior "passes") never saw this because they compare adjacent frames, not motion *level* over the whole bridge. **New, unflagged issue**: sharpness-continuity fails on both bridges (~0.6×) — the bridge's sky has measurably less high-frequency detail than the chain's, independent of the freeze. Hypothesis, untested: an artifact of downscaling a native-720p render to 848×480 for the join (area-interpolation smooths high frequencies) versus the chain's native-848×480 render — not yet isolated from "the model genuinely renders the bridge softer."

**A1** (`experiments/a1_retime.py`, no GPU): flow-constant retime — resample the bridge's own frames (nearest-neighbor frame selection along a warp built from cumulative optical flow, no new pixels invented, no blend across shots) so per-output-frame flow matches the chain's median. On the int8 bridge: 33 native frames → 20 output frames (the eased tail collapses, exactly as intended). Re-run through A0:

| | before retime | after retime (A1) |
|---|---|---|
| motion-level ratio per block (3 blocks, 20 f) | 0.671/0.592/0.552/0.518 | **0.978, 0.96, 1.058** |
| motion-level gate | fail | **pass** |
| motion-direction gate | pass | pass |
| spatial-noise gate | pass | pass |
| sharpness-continuity ratio | 0.627 | 0.548 (still fail — retime doesn't touch sharpness, as expected) |

**The motion-level and motion-direction gates — the ones that map directly to the freeze seen in review — now pass by construction on a pure CPU resample, zero new GPU generation.** Sharpness-continuity is a separate, still-open problem (Q3 resolution strategy). Assembled a chain+retimed-bridge loop (`R-A_loop_x2.mp4`, 22.6 s, chain played then bridge then repeated once) and sent for the R-A human verdict — **pending**. If R-A passes, the retime becomes `enhance`'s bridge resampler (Phase C) with no further GPU work needed for closure; A2/A3 (better cut point, anti-stillness prompt) become optional quality improvements, not blockers.

### Correction: sharpness-continuity "failure" was a measurement bug, not a real defect

`a0_gates.py`'s bridge downscale used `cv2.INTER_AREA`. Isolated test on a native 720p bridge frame (`native720_int8_33f/f_0.png`) downscaled to 848×480: AREA gives sky-ROI Laplacian variance 28.5 (0.70× the chain's 40.9 — reads as a real quality loss); LANCZOS4 gives 47.5 (1.16× — inside the gate's 0.8–1.25 band). **Area-averaging softens high-frequency detail on a large downscale (1280→848, 1.5×); lanczos doesn't.** Fixed both `a0_gates.py` and `a1_retime.py` to use `INTER_LANCZOS4` (matches the lanczos-upscale convention already planned for `bridge`'s endpoints — one resampling filter, not two). Re-ran: raw bridge sharpness-continuity 0.627 → **1.075** (pass); retimed bridge 0.548 → **0.88** (pass). Motion-level and direction results were unaffected (flow estimation is far less sensitive to this than a single-pixel Laplacian). **All four A0 gates now pass on the A1-retimed bridge.** A 7-frame visual contact sheet of the retimed bridge (`a1_v2_contactsheet.png`) confirms by eye: stable castle identity, no blockiness, no visible jump at the frame-skip points. The R-A sample sent to the user was generated before this fix, but the retime warp itself barely moved (chain baseline 0.2333→0.2389 px, same 33→20 frame collapse) — the sent video's *content* is effectively unchanged; only my own softness question in the caption was wrong, and the user should discount it.

**Lesson for `validate.py` (Phase C):** any gate that resamples a native-res artifact down to compare must use lanczos, not area — area quietly manufactures a "quality loss" that isn't in the actual output.

## B1 — per-second drift measurements on the sent 30s chain, precomputed for the verdict (2026-09-22)

`experiments/b1_drift_measure.py`, no GPU. Per-second luma (vs frame 0), sky-ROI Laplacian ratio (vs frame 0), castle edge-mismatch (Canny diff in the castle ROI vs frame 0), on `slide_6w_s306.mp4` (sent to the user for B1):

| t (s) | luma Δ% | sky Laplacian ×frame0 | castle edge mismatch |
|---|---|---|---|
| 0–5 | 0→+5.0 | 1.0→1.06 | 0→0.025 |
| 10 | +7.6 | 1.26 | 0.033 |
| 15 | +10.0 | 1.64 | 0.045 |
| **16** | **+15.7** | **2.28** | 0.054 |
| 20 | +14.0 | 2.64 | 0.059 |
| **21** | **+22.0** | **4.31** | 0.071 |
| 25 | +22.5 | 4.92 | 0.075 |
| **26** | **+30.5** | **6.92** | 0.088 |
| 30 | +31.0 | 7.31 | 0.092 |

Two step-changes, not a smooth curve: **t≈16s** (sky Laplacian nearly doubles between 15s and 16s: 1.64×→2.28×) and **t≈21s/26s** (further near-doublings). These land exactly on window boundaries (windows are ~5s at 16fps/81f; window 4 starts at t=20s per the per-window table above) — consistent with "error compounds per window" rather than a continuous decay. Castle edge-mismatch grows more smoothly (no matching step), so the sky/cloud texture is what breaks first and hardest. Waiting on the user's own timestamp to calibrate the drift gate threshold against this table.

## A3 — anti-stillness negative prompt does not stop the ease; 49 f native bridge exceeds 90 min (2026-09-22)

`experiments/a3_flf2v_run.py`: flf2v_720p int8, 33 f native, real CFG 5, 30 steps, seed 306, same endpoints as L1b bridge A, negative prompt + "slowing down, decelerating, coming to a stop, freeze frame, still image, frozen, settling". 3464 s (58 min), peak 4.7 GB VRAM / 42 GB RAM. **Median motion-level ratio 0.579× vs 0.563× for the L1b bridge without it** — within noise, still far below the 0.8× floor. With real CFG the negative prompt is live, so this is a real negative result: **the ease into the end frame is not prompt-addressable at this strength; flow-constant retime (A1) remains the closure fix.** (Confound: A3's positive prompt was a reconstruction, not the L1b wording — recovered later from mp4 metadata; the B7 bridges use the exact L1b wording.)

**Cost cliff:** the same job at 49 f (`--profile 4`) was still running at the 90 min watchdog cap and was killed. 33 f = 58 min; 49 f > 90 min (> 1.55× for 1.48× frames; the 81 f attempt was 110 min *per step*). Locally, native-res bridges stay at 33 f; longer bridges are an offsite question.

## 2026-09-22→23: first ~30 s forward-only loop (B7), colour drift solved (B2), native-720p chain infeasible locally (B3)

Queue: `experiments/overnight/run_queue.py` (log `queue.log`, `results.json`, fixed assembly `b7_fixed_results.json`).

**B7 re-anchored loop, 28.6 s** = chain1 (existing seed-306 chain, frames 0–212, A2 best cut: frame 212, 9.22 vs 9.72 mean diff to frame 0 for the last frame) + bridge1 (flf2v 33 f native, 56 min, retimed 33→18 f) + chain2 (new, seed 301, 241 f in 19.8 min, cut at 209) + bridge2 (56 min, retimed 33→16 f), every bridge landing on chain1's frame 0. Both retimed bridges pass all four A0 gates (motion 0.87–1.04×, sharpness 0.99–1.08×). Joins (appearance change ÷ median adjacent change): seg1→br1 0.74, **br1→seg2 2.14**, seg2→br2 0.71, br2→wrap 1.6. The 2.14 is chain2's frame 0 being WanGP's re-render of frame 0 (mean diff 2.1), not frame 0 itself. Contact sheet: clean, castle stable, bridge ends match the next segment's start almost exactly. Open perceptual question: each ~1 s bridge moves the sky from end-of-segment state to frame-0 state (cloud cover/moon glow differ visibly). **Sent for the R-B verdict.**

**Assembly bug caught by eye, not by metrics:** this WanGP build outputs `832x480` requests at 832×480 (it squashes the input; mean diff 2.1 vs 5.2 for a center-crop), while the older chain is 848×480. Piping mixed-size frames into ffmpeg as raw video sheared segment 2 into horizontal streaks. Every gate and join metric resizes frame by frame, so none of them noticed. Fix: normalize every frame to one size (lanczos) before assembly and assert it. **Phase C `assemble`/`enhance` must assert a single frame size, and resolution should be requested as 848x480 explicitly.**

**B2 colour correction (`sliding_window_color_correction_strength=1`, 481 f, 39 min): colour drift solved.** Luma vs frame 0 at 30 s: **+1.9 %** vs +31 % baseline (flat the whole way). Texture drift is only mildly reduced: sky Laplacian ×frame 0 at 20/25/30 s is 2.38/4.05/5.90 vs baseline 2.64/4.92/7.31. Castle edge mismatch 0.079 vs 0.092. **Adopt colour correction by default.** Texture still breaks at the ~16–20 s window boundaries, so segments stay ≤15 s (B7 structure) until a texture lever works.

**B3 native 1280×720 chain (481 f): killed at the 210 min cap** (the 848 chain takes 39 min). Not viable locally; it's an offsite (T3b) question.

**B4 longer windows (121 f, 4 conditioning hops per 30 s instead of 6; 42 min, same cost): the strongest texture lever so far.** At 30 s the sky Laplacian is ×1.89 of frame 0, versus ×7.31 for the baseline and ×5.90 with B2. Castle edge mismatch is 0.051 vs 0.092. Luma drifts the other way (−8 %), and B2's colour correction should cancel that. Visual check at 28 s (`experiments/overnight/drift_compare_0s_28s.png`): the baseline sky has broken into colour blotches; B2's colour is stable but its sky still shows leafy blotches and over-sharpened reeds; **B4's sky is still soft, plausible cloud and the castle is intact**, slightly darker and softer. Hypothesis: drift scales with the number of window handoffs, not with duration. Follow-up running (`morning_drift.py`): 121 f and 161 f windows, each with colour correction. If they hold for 30 s, one continuous chain + one bridge could replace B7's re-anchoring.

## Human verdicts 2026-09-23 + the window-boundary stall

- **R-B (B7 28.6 s re-anchored loop): judged good.** The first forward-only ~30 s loop to pass human review: two 13 s segments + two flow-retimed flf2v bridges, every bridge landing on frame 0.
- **R-A (10 s chain + retimed bridge): freezes at ~11 s.** **B1 (30 s chain, no bridge): freezes at ~11 s, then the video degrades.** Review 3 has no bridge, so the freeze is in the **chain**, not the closure.
- No duplicate or near-duplicate frames anywhere; whole-frame and per-region flow show no sustained stop. What is there: **a window-end ease + restart lurch at every sliding-window boundary.** In the last ~6 frames of each 81 f window the frame-change ratio drops to 0.4–0.7× (mid-window mean 1.05×); the next window's first frames jump to 1.3–1.7×. It is mild at 5 s (window 1→2) and clear at 10/15/20/25 s. It is the same slowing-toward-a-stop behaviour as the flf2v bridge, at every handoff. Overlap is already at the model's maximum (1 frame), so the new window gets no velocity information.
- **Drift gate, provisional from B1:** the user places degradation after ~11 s. On this chain at 11 s: luma +10 %, sky Laplacian ×1.42 of frame 0, castle edge mismatch 0.040. Provisional gate: sky ≤ ×1.4, |luma| ≤ 10 %.
- Candidate fixes for the boundary stall, cheapest first: (1) **flow-constant retime of the whole loop, not just the bridge**, on RIFE dense frames (Phase C `enhance` already runs RIFE; this generalises A1 from the bridge to everything); (2) WanGP `sliding_window_discard_last_frames` (drop each window's eased tail before the next window continues; GPU run); (3) longer windows (B4, 121 f) reduce the number of boundaries.

### Whole-loop flow-constant retime (2026-09-23): removes the window-boundary stall

`experiments/whole_retime.py`: RIFE ×4 on the whole one-pass loop, with frame 0 appended so the loop point is interpolated too. Per-source-frame flow is smoothed (Gaussian σ in source frames), then output frames are placed evenly in cumulative flow, at ¾ speed / 24 fps (the approved look). B7 loop: 457 source frames → 914 output frames, 38.1 s. Frame-change ratio vs median, per boundary (worst 6-frame mean / peak):

| boundary | uniform ¾ speed | σ=2 | σ=1 | **σ=0.5** |
|---|---|---|---|---|
| window 5 s | 0.74 / 1.72 | 0.92 / 1.97 | 0.92 / 2.07 | 0.84 / 1.32 |
| window 10 s | 0.65 / 1.82 | 1.02 / 2.78 | 1.07 / 2.77 | 1.07 / 2.10 |
| br1→seg2 | 0.86 / 2.23 | 0.89 / 2.86 | 0.97 / 2.93 | 0.95 / 2.08 |
| seg2 window | 0.37 / 1.52 | 0.65 / 1.86 | 0.76 / 1.86 | 0.77 / 1.78 |
| frames > 1.8× (of 914) | 40 | 56 | 48 | **25** |

Heavy smoothing fixes the slow-downs but sharpens the restart lurch (the eased tail gets compressed, so the jump lands harder). σ=0.5 fixes both. **Remaining:** the loop point (bridge2 end → frame 0) is 2.1× at source level; after RIFE at ¾ speed it lands in one output step (3.6×), because RIFE does not spread a small appearance offset. Contact sheet around the former stall (`retimed_13s_contact.png`): no ghosting, castle stable. Sent to the user as Review 4.

**Review 4 verdict (2026-09-23): the freeze is fixed.** The whole-loop flow-constant retime (σ=0.5, RIFE ×4, ¾ speed, 24 fps) removes the window-boundary stall perceptually, not just by measurement. It is now the proven design for `enhance` v2. **Still open (reviewer):** the clouds switching direction mid-scene is disliked. Measured: sky horizontal drift flips sign at every 5 s window boundary (the plain i2v model hands over only 1 frame, so there is no velocity carry-over, `wan_handler.py` `test_oneframe_overlap`), and each bridge sweeps the sky back at 6–10× chain speed to restore frame 0's cloud layout. Whole-frame motion gates can't see a fast sky over a calm foreground, so the motion gates need a per-region (sky) version.
