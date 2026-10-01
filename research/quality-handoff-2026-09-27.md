# Quality handoff 2026-09-27: audit, lighthouse attribution, speed x depth experiment

Source: `LOOPER_IMPLEMENTATION_HANDOFF_2026-09-27.md` (user-supplied). This file is the implementation note it asks
for (§2) plus the §8 attribution and the §9 experiment.

## 1. What the controls actually do (audit, code-verified)

- **`--motion-speed S`** is generation-side only: the Slow-Motion-Control LoRA is loaded and every video token's
  temporal RoPE coordinate is multiplied by S (`adapters/ltx.py` `scale_motion_clock`, applied in `hooks()` to take,
  extend and close alike). It is not conditioning text, not a playback retime, not interpolation: the mp4 is always
  24 fps and no stage of the loop path retimes. S = 1.0 is native: no LoRA, no scaling, key absent from the
  fingerprint. There is therefore no "before speed adjustment" artifact to compare against -- a speed change is a new
  generation.
- **Camera lock** = the union-control IC-LoRA (WanGP system LoRA `...ic-lora-union-control-ref0.5`, multiplier 1.0,
  auto-added for "DVG") fed a **static depth video: the keyframe held still for every frame** (`ltx.still_control`),
  control strength = WanGP `denoising_strength` = 1.0 (`models/ltx2/ltx2.py` `control_strength =
  denoising_strength`). Same guide in take, extend and close. Prior evidence: strength 0.5 on the furnace kept the
  camera (0.10 px) and the user saw no difference; off = the camera travels (110 px).
  Now exposed as `--guide-strength` (default 1.0, stays out of fingerprints at 1.0).
- **Resolution** was not a CLI option (default 832x480 -> LTX output 832x448); now `--resolution`.

## 2. Lighthouse (lighthouse_lr_s02): where the scene was lost

`python -m looper trace lighthouse_lr_s02` (runs/lighthouse_lr_s02/trace/):

| stage | motion energy | sharpness | lantern p99 first/min/mean |
|---|---|---|---|
| take[0] | 0.586 | 83.5 | 163 / 163 / 172.5 |
| close[307] window | 0.595 | 76.0 | 173 / 170 / 176.6 |
| splice[307] loop (generated 352-720) | 0.644 | 79.2 | 176 / 166 / 173.8 |
| deliver loop | 0.627 | 78.5 | 173 / 164 / 171.8 |

1. **Lantern:** never absent. It is in the effective prompt ("Warm interior lantern light emits a steady glow
   through glass panes"), lit in the keyframe, in every take frame and in the delivered loop (p99 never below 163
   grey; crops confirm). What the review verdict called the removed lighthouse light is the **beam**: the user's
   prompt was only "A lighthouse on a rocky cliff in a storm at dusk"; the director (v11 brief) replaced "rotating
   lighthouse beacon" with "constant steady lantern glow" as an adaptation, its `MOTION_ONLY` rule drops any sweeping
   beam clause and `BASE_NEGATIVE` carries "sweeping light beams". Removal happened at **planning**, by design.
   Under ADR 0013 a beam becomes a requirement only when the user's words ask for rotation; whether a lighthouse
   should imply its beam is the user's call (open question in STATE).
2. **Waves:** poor at native speed (dir_lighthouse2, speed 1: much too fast and fake in review) and at 0.2 (lr_s02:
   very poor in review). The defect is in the raw take at both clocks, not added later. The motion prompt (from an older
   director version) asked for a "steady horizontal swell across the frame" (sideways sliding, which director v12
   later forbade).
3. **Depth vs timing:** see §3 (experiment).
4. **Closure / finishing:** the closure did not freeze or darken the scene (motion energy 0.59 -> 0.63, lantern
   steady); closure windows are ~8 % softer (Laplacian 76 vs 83.5). No 4K on this run.

## 2b. Realism amendment audit (requested: no rule banning beams)

| rule | location | scope | evidence it came from | action | regression |
|---|---|---|---|---|---|
| no sweeping / rotating beam; lantern-only adaptation | `direct._BRIEF` (v11), `MOTION_ONLY` beam regex | every directed run | dir_lighthouse 41-44 grey | **removed** (v15); brief now asks an operating lighthouse to sweep its beam | test_contract / test_direct lighthouse tests |
| no breaking / crashing / splashing waves | `MOTION_ONLY` | every directed run | dir_lighthouse | **removed**; WATER_PACE asks for waves breaking into foam | test_direct storm test |
| "sweeping light beams, changing light" negatives | `motion_style.BASE_NEGATIVE` | every run | ignored by distilled LTX anyway | **removed**; contract drops any negative naming a required element | test_base_negative_has_no_beam_ban |
| "each slow, steady and continuous" motion | `_BRIEF` | every directed run | loopability worry | **replaced** by per-phenomenon real speed / amplitude | brief text |
| "Calm and unhurried" pace | `motion_style.PACE` | every directed run | on every passed loop | **replaced** by "real time, not time-lapse, not slow motion" (passed loops keep their saved prompts) | — |
| "The water moves slowly and heavily" | `WATER_PACE` | sea scenes | much too fast and fake in review (dir_lighthouse2) | **replaced** by weight + travel + breaking (hypothesis) | test_direct water test |
| "The light is soft, even and perfectly steady" (daylight) | `SUN_HIDDEN` | daylight scenes | pine flare drift | **replaced** by "daylight established, exposure steady"; the still keeps its sun | test_direct daylight test |
| keep the sun out of frame | `_BRIEF` | daylight | pine5/6 grew a sun from motion words | **narrowed**: sun stays in the still; only a motion clause about the sun is dropped (MOTION_ONLY kept) | test_direct sun test |
| "lighting stays exactly constant" appended to every LTX stage | `motion_style.steady_light` | take / extend / close | lamplight drift 4/5 runs | **kept** for scenes without a moving light; exposure-only clause when `moving_light` (stage config key, so in the fingerprint) | test_steady_light_keeps_old_clause_unless_moving_light |
| per-frame whole-frame histogram target on the gap | `splice.splice`, `join.join` | every loop | ADR 0006/0007 drift fix | **kept** by default; `tone: none` for moving-light runs (beam loops used a raw gap and passed reviews 3-4) | defaults unchanged |
| drift / pulse on 1 s cell means | `take_qc.stationarity` | every take | calibrated gates | **kept**; 5 s means for moving-light runs (uncalibrated hypothesis) | defaults unchanged |
| no mist unless asked | `_BRIEF`, `direct.run` | every directed run | mist builds up (neon, pine) | **narrowed**: a beam clause may name its medium (light, established) | code |
| "fades" banned | `BANNED` | every directed run | change over time | **removed** (a turning beam fades as it points away) | — |
| settle every take | `loop_pipeline` (`settle` default) | every run | user decision 2026-09-25 | **unchanged** (user decision); `--no-settle` used for the lighthouse still, which is already settled | — |
| lighthouse = lantern only, beam only when the user says "rotating" | contract v1 | every run | handoff §6.1 | **superseded**: the director's selected beam becomes a `director_selected` requirement; a static glow in its place is repaired | test_director_selected_beam... |

Historical evidence (research files, old run prompts) is untouched.

## 2c. Review content diagnostics: what they can and cannot see (§10)

Loop vs its own take (review v3), and camera over the whole loop, on every delivered loop with a verdict:

| loop | verdict | motion ratio min / mean | light min / take | camera max px / zoom % |
|---|---|---|---|---|
| rain_loop_e2e | nothing noticed | 0.90 / 0.93 | 0.97 | 0.54 / 0.066 (full-frame fallback) |
| dir_pine7 | perfect | 0.93 / 0.98 | 0.99 | 1.33 / 0.17 |
| falls_loop | visible at 7 s (closure) | 0.99 / 1.02 | 0.98 | 0.36 / 0.015 |
| dir_neon | loop fine | 0.93 / 1.00 | 0.97 | 0.26 / 0.035 |
| dir_furnace_mild | pretty noticeable (closure) | -- | -- | 0.47 / 0.115 |
| lighthouse_lr_s02 | joins invisible; waves very poor | 0.94 / 1.05 | 0.95 | -- |

Gates (hypotheses): motion < 0.5, light < 0.7, camera > 1.5 px / 0.5 %. None fires on a passed loop. **No loop in
the pipeline era was ever rejected for freezing or losing its light**, so the gates are uncalibrated on the failing
side; and the content-rejected lighthouse scores like the passed loops: these diagnostics catch LOSS of motion or
light between take and loop, not bad-looking motion. Motion quality stays a human judgement (audition + review).

## 2d. First real run of the new path: crawler_720 (mining-crawler brief, stopped by the user after the take)

- **1280x704, 481 f LTX take fits the 6 GB card but not comfortably in RAM:** 42.5 min (loading 28 s, text 2.3 min,
  denoise 34.4 min, decode 5.2 min; the 3 full-res stage-2 steps ~10 min each vs ~25 s per half-res stage-1 step),
  VRAM 5.9 GB, CUDA peak alloc 6.7 GB, **system RAM peak 63.2 of 64 GiB** -- nothing else may run alongside; a
  longer window (extension, 368 f return) at 720p is unmeasured and may not fit (832x480 take: 12.5 min, 56-59 GB).
- Settle `auto` skipped (start transient 1.56 grey, late 3.99) -> take[0] reused the settle take (saved ~42 min).
- take_qc rejected seed 306: smoke cell drift 7.37 grey (gate 4, best effort 7.5), camera 0.06 px.
- Contract v3 on the brief: work lights, furnace, smoke/dust, director-selected rotating drums; neon excluded.
  Contract v2 had inverted "Avoid ... neon" and read "a stream of slag" as water (fixed before any render).
- Critic picked keyframe #0 (18/20; beams shooting up from nowhere); #1 matched the brief better (forward/down work
  lights, readable drum). None of the three reads as "several hundred metres" long.

## 3. Speed x depth experiment (§9) -- seed 306 only (stopped: the user dropped the lighthouse scene)

Lighthouse still, dir_lighthouse2 prompt/negative, 1280x704, 121 f. B/306 reused from the bake-off (settings
identical). Depth 0.5 instead of 0.6: the furnace already showed 0.5 holds the camera. Script deleted with the scene
(it was lighthouse-specific); clips in `runs/speed_depth/` (gitignored).

| arm | clock | depth | motion energy | sea-band flow px/f | camera px | drift grey |
|---|---|---|---|---|---|---|
| A | 0.2 | 1.0 | 0.261 | 0.181 | 0.01 | 0.66 |
| B | native | 1.0 | 0.565 | 0.259 | 0.05 | 1.02 |
| C | 0.2 | 0.5 | 0.265 | 0.157 | 0.03 | 0.83 |
| D | native | 0.5 | 0.605 | 0.239 | 0.02 | 1.93 |

Space-time slices of the near-shore row: at 0.2 the water is one slowly deforming mass sliding sideways (the
"viscous" look); at native clock the foam flashes in place about every 10 frames rather than travelling. Depth 0.5 vs
1.0 looks the same in both (B ≈ D, A ≈ C). **Conclusions (one seed, not judged by eye):** the motion clock is the
dominant lever and 0.2 is harmful for water -- keep native unless a scene is demonstrably too fast; the static depth
guide is not what freezes water, and 1.0 stays the default. A thin strip of sea (~35 px) cannot read as surf
whatever the settings: stills need the effect framed large (contract FRAMING clauses).
