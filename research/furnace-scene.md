# The Last Furnace: a user still + brief through the pipeline (2026-09-26)

Scene: the user's 1672x941 still (industrial ruins under a red giant) + a 5.8k-char structured brief. Run
`dir_furnace`; inputs `runs/inputs/last_furnace*.{png,md,txt}`.

## Baseline (director v13, no flare)

Three input bugs fixed first (odd image height, a brief passed verbatim, multi-line prompt → 29 WanGP requests; see
STATE "Unattended pipeline"). Then: take 2.23 grey first try; extensions 4.26 / 5.47 → 17.7 s loop on the old code,
30 s on the new extension-best-effort rule (4.26); all closures accepted, closing 1.03–1.18; pumping 0.72 grey/s
global, 0.68 in the sun region. Composition matches the still frame-for-frame; the settle step brightened the gear's
interior fire and put a hotspot where the sun meets the horizon.

**Reviewer:** 17.7 s: very slight scene jump, acceptable; the giant gear's spin slightly shaky or jerky; 30 s preferred.
Then requested: more effect from the sun, light, reflections and floating embers (the light does little in these
scenes); more movement and brilliance.

## Gear lurch

Gear region (left 36 % of the frame) changes 0.80 grey/frame vs 0.38 elsewhere; lurches at loop frames 249 and 499
(> 2x median); mean flow 0.09 px/frame. Difference maps put the change on the thin rim over glowing fire, i.e. the
rim itself creeps and jumps, although the prompt fixes the gears. Hypothesis: depth control is ambiguous for a thin
rim against bright fire; canny-edge control ("EVG") should pin it. T0 `experiments/gear_canny/run.py` (145 f, seed
306, same keyframe/prompt), gear region (left 36 %):

| control | step median / p95 / max (grey) | rest median | flow px/f median | net flow |
|---|---|---|---|---|
| depth (pipeline) | 0.71 / 0.88 / 1.26 | 0.32 | 0.051 | 0.22 |
| canny | 0.65 / 1.20 / 1.42 | 0.33 | 0.048 | 0.19 |
| none | 2.21 / 2.57 / 2.74 | 1.38 | 0.364 | 2.12 |

**Rejected:** canny ≈ depth on the rim; the control map is not the lever (no control at all is 3–7x worse, so the
lock itself is essential). The 30 s loop's lurches (frames 249, 499) did not reproduce in 145 f clips (max 1.26).

**Solved 2026-09-26 (dir_furnace_bright, reviewer: a fairly severe shudder at ~30 s):** the lurches at frames 249/499
were **x264 keyframe pops**, not generation. The lossless master's worst step is 1.51x; the crf-17/20 4:2:0 files
step 2.1–2.8x at frames 250, 500, 750 … = x264's default `keyint=250`, whole frame, in every run (the "gear" jump was
just the region with the most grain). They vanished in 145 f clips because those files have no second I-frame.
Fix: `keyint=infinite:scenecut=0` in `loopkit.write_video` (deliver v3, review v2); the review stage now measures the
encoded file's own worst step, not only the master's. Re-encoded review: mid-file worst 1.79x (frame 5, natural).

**Spokes (review, same loop):** the wheel spun smoothly, but the spokes blurred and did not spin at the same rate —
thin repeating structure smearing under the rim's motion (the depth map has no spokes to lock). Measured on
the s307 take: the wheel region (left 40 %, rows 5–75 %) has **no rotation period** (autocorrelation decays
monotonically, 0.36 at lag 24 and falling); the inner lattice re-synthesises frame to frame instead of turning
rigidly. Sharpness is constant (Laplacian var ≈ 1260 everywhere). Open; in the improvement brief
`docs/handoffs/2026-09-26-pipeline-improvement-research-brief.md` §4.3.

**Residual shudder at ~31 s after the keyframe fix (reviewer: still there, maybe milder):** the wheel region moves
a sustained **1.12–1.16x faster through the whole 32-frame closure gap** (max 1.23x) on all three closure seeds
(306/307/308), against 1.01x elsewhere: the closure catches the wheel up to frame 0's state. Whole-frame steps stay
≤ 1.4x, so no gate sees it; the eye tracks rotation speed. Seed choice cannot fix it. **48 f gap tried (2026-09-26,
`experiments/gear_canny/gap48.py`, seed 308): wheel gap mean 1.14x, max 1.22x (rest 1.00x)** — identical to the 32 f
gap. The catch-up does not spread over a longer gap; the closure re-synthesises the wheel at whatever speed lands on
the target latents. Not gap-addressable. A generic warning was tried and dropped the same day: the per-region
closure-gap activity ratio (`regional_qc.gap_motion`, mean lag-1 change through the gap / the rest of the loop) is
1.25–1.31 on the furnace wheel cells but 1.19–1.26 on the rain loop that passed review (nothing noticed), so it cannot
warn without crying wolf (`experiments/qc_tools/gapmotion.py`; kept in qc.json as a diagnostic). The eye tracks
rotation *speed*, which needs a rotation-specific measure (flow phase on the rim) or a guide (plan §4.3). Parked.

## Flare A/B (`dir_furnace_flare`, `--raw-prompt`)

Same settled keyframe, the director's prompt with "The light is soft, even and perfectly steady" replaced by "a steady
cinematic anamorphic lens flare streaks from the red giant, constant in brightness and position; long diffuse
volumetric rays ... perfectly steady", negative without the flare terms.

| | baseline | flare prompt |
|---|---|---|
| takes (3 seeds) | 2.23 (accepted first try) | 4.73 / 5.74 / … — none accepted; best effort 4.73; one seed luma −5 % |
| extension | 4.26 (best effort) | 5.91 (best effort) |
| sun-region pumping (grey/s) | 0.78 | 1.17 |
| visible flare / rays | none | **none** — frames near-identical (`runs/dir_furnace_flare/review/ab_dir_furnace.jpg`) |

**Conclusion:** the motion prompt cannot add a flare the still does not have (depth-locked I2V keeps the keyframe's
look); asking for one only destabilised the light. The director's flare ban stays for the motion prompt. Brilliance
must go into the **keyframe** (the still carries the look): for prompt-only runs that is the keyframe prompt; for user
stills it is the still itself (or a settle pass that adds it). Not sent for review (nothing to see).

## Brilliance T0 (`experiments/brilliance/run.py`)

Vivid fast-light clauses (swirling bright embers, licking flames, glinting reflections, heat shimmer, "level of the
light stays exactly constant") vs the director's prompt, same keyframe/seed, 145 f:

| | director prompt | brilliance prompt |
|---|---|---|
| region drift (gate 4) | 1.57 | **9.35** (luma −3.7 %) |
| per-frame activity | 0.48 grey | 1.09 grey |
| near-white pixels (glints/embers) | 0.11 % | 0.11 % |
| by eye (`runs/brilliance/ab.jpg`) | steady | the gear's fire slowly brightens; no new sparkle or embers |

**Conclusion (with the flare A/B): on a depth-locked still, light wording in the motion prompt cannot add
brilliance; it only makes the existing light change slowly (drift).** The still decides the look. Next: put
brilliance into the keyframe (Z-Image keyframe prompt clause) and let LTX animate what it sees — keyframe T0 below.

## Keyframe brilliance T0 (`experiments/brilliance/kf.py`)

Same scene sentence ± a brilliance clause, Z-Image, 2 seeds each (`runs/brilliance/kf_sheet.jpg`). The clause works
on the still: crisp rays from the giant, a glittering river of reflections, rim light, glowing air; plain stills stay
subdued. **Reviewer: yes, but the scene looks like bad CGI; the original image's style is preferred.**
→ Brilliance = keyframe-side, confirmed; but for a user still the look must stay theirs: an image *edit* (add rays /
glints / embers, keep everything else), not a regeneration. Untested: whether a still this bright animates without
drift (`experiments/brilliance/take.py`, not run — the Z-Image route is rejected for this scene).

## Image-edit route (`experiments/brilliance/edit.py`, Qwen Image Edit Plus 2509 20B int8 in WanGP)

Goal: add rays / flare / glints / embers to the user's still and keep its style. Weights: one-time ~20 GB download
(no nunchaku kernels in the venv, so no INT4/4-step build). Attempt 1 (output at the input size 1672x941 via the
inferred "KI" flag, 20 steps, guidance 4): **pure noise** with the composition faintly visible; ~15 min per image on
the 6 GB card (offload). Attempt 2 (input pre-fitted to 1280x720, 30 steps): **noise again**, but the prompt's
content is there (rays, a flare), so the transformer responds and the corruption is elsewhere. Attempt 3: the
pipeline session uses `--attention sage2` (fine for LTX / Z-Image) while this model's definition asks for `sdpa`
below compute 8.9 (RTX 3060 = 8.6) → session rebuilt with sdpa: output **byte-identical** to attempt 2, so
attention was never the variable; the corruption is deterministic and systematic (weights / VAE / int8 path).
Attempt 4 = discriminator: WanGP's own default settings ("add a hat", 1024x1024, nothing overridden)
(`edit_default.py`): **noise too** (`runs/brilliance/edit_default.png`). → Qwen Image Edit Plus is broken on this
install (quantised weights / int8 path / VAE — the adapter silences WanGP's console, so the reason is unknown);
~10–15 min per attempt on the 6 GB card, 4 attempts, none usable. Do not retry without a fix in WanGP.
Fallback **Flux Kontext dev** (12B int8, 11.2 GB, `edit_kontext.py`, ~10 min/edit): **works.** Edit A
(`runs/brilliance/kontext_a.png`) keeps the painterly style and composition and adds a volumetric shaft between the
towers, embers in the air, a stronger giant and horizon glow. **Approved for the full loop** → `dir_furnace_bright`
(30 s, `--no-settle`, from the edit): take s306 rejected (sun cell creeping +3.8 grey, shaft fading −3.9: a bright
still CAN creep), s307 accepted at 1.9; extension 3.31; all closures accepted; 55 min, no warnings.
**Reviewer: a good attempt that missed the goal: keep the existing scene and make what is already there brilliant
(e.g. the sun).** → edit C (`edit_kontext.py c`): intensify the sun, the
furnace fire and the reflections that are already there; add nothing. Kontext did that but re-exposed the whole frame
(warmer, brighter everywhere) and re-synthesised fine detail at 1280x720. **Reviewer: looks visually off and unnatural
(maybe too low resolution).** Editors regenerate every pixel; two of two edits changed more than asked.

## Bloom (no model, `experiments/brilliance/bloom.py`)

Highlight bloom on the user's own still: mask = brightest channel above a threshold (the red giant is dark in luma
but saturated, so a luma mask misses it), Gaussian glow screened back, a hotter core where the mask is strongest.
Every other pixel is untouched; deterministic, seconds of CPU. `mild` (thresh 0.80, gain 1.2) keeps the sun's surface
texture under a corona and lifts the furnace fire and reflections; `strong` (0.74, 2.0) blows the sun out to a pale
disc. Sheet `runs/brilliance/bloom_sheet.jpg` sent 2026-09-26. **Reviewer: mild and strong both look very good;
mild chosen.** → `dir_furnace_mild` (30 s, `--no-settle`, from `bloom_mild.png`, 2026-09-26/27).

**The bloomed still costs stationarity, like the Kontext edit did:** takes s306 / s307 / s308 crept **5.78 / 4.56 /
5.15** grey (worst cells c10 = the wheel's fire, c11 = the furnace glow; camera ≤ 0.3 px), against 2.23 first try on
the unbloomed still and 4.56 / 1.9 on the Kontext edit. Best effort took s307 (4.56, "very slight" band) and the loop
went on. Hypothesis: the larger, hotter highlight areas give LTX more light to keep brightening; the creep is in the
lit cells, not global exposure. Consequences: bloom is a pipeline stage but off by default (`--bloom mild|strong`,
`looper/stages/bloom.py`); expect best-effort takes with it; a lower `core` / `gain` might trade brilliance for
stationarity (untested). The loop's verdict decides whether the trade is worth it.

The loop itself (30 s, extension 3.68, closure accepted): the closure gap's mean normalised step is **1.47–1.58 on all
five seeds** (306–310; passed loops elsewhere 1.19–1.30, `loop_qc.CLOSING_MEAN_MAX` 1.4 = review DOUBT) — the whole
frame re-synthesises through the 1.3 s gap (fire, embers, sun glow all change per frame), the review encode steps 3x
there. Seed choice does not move it; it is this scene's closure cost. Sent for a verdict 2026-09-27.
