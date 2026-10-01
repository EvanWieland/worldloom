# Scene perfection, research round 2 (2026-09-27)

Source: `docs/handoffs/2026-09-27-scene-perfection-research-report.md` (external report answering
`docs/handoffs/2026-09-27-scene-perfection-research-brief.md`). Requested: follow the report and try its suggestions.
Status per report item below; evidence paths under `runs/`. Every metric result is provisional until the user's eye.

## 1. Furnace closure churn (report §3)

### Motion-compensated gap churn separates the verdicts (C2 / Q1) — ADOPTED as a review DOUBT (loop_qc v4)

`loopkit.gap_churn`: Farneback flow at half resolution, residual |frame - warped previous| per 3x4 cell; closure-gap
mean / the same window's context frames (one decode, so no decode offset between gap and reference).

| loop | verdict | gap churn (mean over cells) |
|---|---|---|
| rain 160 f interior bridge | unnoticeable | 0.99 |
| cabin closure | (loop accepted) | 1.01 |
| rain 320 f interior bridge | unnoticed | 1.06 |
| rain closure (30 s loop) | nothing noticed | 1.21 |
| falls closure | very slight | 1.27 |
| pine7 17 s endpoint closure | completely unnoticeable | 1.28 |
| neon closure | very hard to tell | 1.29 |
| dir_furnace closure | very slight scene jump (mostly encoder pops) | 1.36 |
| pine7 30 s closure | noticeable (a passing shadow: interior drift) | 1.47 |
| furnace_mild closures, 5 seeds + grow closure | fairly noticeable (x2) | 1.54-1.62 |
| **furnace_mild 320 f return (new)** | pending | **1.04** |

Every short furnace closure raises churn in all 12 regions at once (the report's "several stable regions change
together"). Gate 1.4 = review DOUBT only; one scene of failures does not earn reject authority.
Tool: `experiments/furnace_controls/motion.py churn WINDOW... --ref TAKE --gap G`.

### Motion-aware (e, s) ranking (C2)

`motion.py rank RUN`: per-cell luma level and slope, flow magnitude and direction, wheel angular velocity (flow about a
hand-placed centre), and z_return = the luma return speed a G-frame gap needs beyond the scene's natural slope,
each normalised by its spread across 2 s windows of the take. On the furnace take, the failed pairs need a return
7.6-9.9 sd faster than natural; the best 17 s candidates need ~3.3. Across other scenes z_return does NOT separate
passes from fails (rain 30 s passed at 5.5, pine7 cut passed at 4.4, pine7 30 s failed at 4.7): a furnace signal,
not a gate. Wheel angular velocity barely varies across the take (z_omega < 0.2 everywhere); the wheel's spokes
re-synthesise, so no absolute angle/phase was attempted (report: "if the spokes morph, the angle is unreliable").
Rendered at 32 f, seed 307 (`runs/endpoint/dir_furnace_mild_{luma_e577_s201,motion_e609_s217}/`):

| pair | loop | gap churn | gap activity (loop_qc) | joins |
|---|---|---|---|---|
| luma-top (577, 201), boundary 1.59 | 17.0 s | 1.42 | 1.38 | 1.48 / 1.52 |
| motion-top (609, 217), boundary 1.90 | 17.7 s | 1.45 | 1.43 | 1.47 / 1.64 |
| pipeline pair (481 -> 89), 32 f, 6 closures | 17.7 / 30 s | 1.54-1.62 | 1.54-1.58 | |
| same pair, 320 f return | 29.7 s | 1.04 | 1.09 | 1.19 / 1.63 |

A closer pair cuts the churn a little but stays above the pass band (<= 1.29); the motion-aware pick is no better
than the luma pick. **C2 not adopted.** On this scene gap length, not pair choice, is the lever. Neither 17 s loop
was sent (both would be DOUBT, and the 320 f return is better on every measure).

### Long return (report §2 step 1)

One 320-frame bridge from the take's end (481) back to frame 89 as the whole second half: 29.7 s loop, closure
step 1.04x, gap activity 1.09 (short closures 1.4-1.58), churn 1.04, region drift over the full loop 1.29 grey,
camera 0.03 px. Luma: the take darkens 64.2 -> 62.4 over 16 s and the bridge climbs back over 13 s (a slow
symmetric ramp, not a step). Frame sheet: no invented content. Sent for review. **More time helps this pair**:
the 32 f failure is the gap length, not an impossible pair.

### Preserve an accepted loop, grow its interior (C3 / F1)

`bridge.py interior dir_pine7 --loop runs/endpoint/dir_pine7_e777_s401_g32/loop.mp4 --offset 401 --e 601 --gap 344`:
the 17 s pine loop rated flawless in review (its closure kept, now at 6.0 s) with 32 interior frames replaced by a 344-frame
two-sided bridge whose contexts lie in the extension window -> 30.0 s. Closure step 0.90x, gap activity 0.99,
churn 1.06, full-loop region drift 2.95 grey (the 17 s loop: 3.26; the old 30 s pine loop the user saw a passing
shadow in: 9.76), camera 0.02 px, no invented content. 14 min GPU. Sent for review (`runs/endpoint/dir_pine7_grow30_e601_g344/`).

**Pipeline stage validated end to end (ADR 0011):** `loop_pipeline._grow` on falls_loop's cached take-only 17.7 s loop
(fresh run dir `runs/grow_check_falls/`, driver deleted after): plan e = 281, G = 328 from frame numbers alone ->
close[grow] -> grow -> splice[grow] -> loop_qc[grow] accepted: 30.0 s, churn 0.96, closure step 0.98, region drift
over the loop 2.08, camera 0.0 px, per-region motion in the passage = the take's (no freeze; its luma is flatter
than the take's, +0.6 grey entering it). Joins 1.37 / 1.25 / old closure 1.42 vs the loop's own worst 1.46.
Sent for review. **Reviewer: the waterfall transition is visible only at the 7 s mark; all other transitions clean.**
7 s is the ORIGINAL 32 f closure the grow kept (seed 306: churn mean 1.29, worst region 1.61); both joins of the
328 f passage (worst region 1.10) were clean. The grow stage did its job; a kept short closure keeps its defect.

### Worst-region churn separates better than the mean

| closure / passage | verdict | mean | worst region |
|---|---|---|---|
| rain 160 f / 320 f passages | unnoticed | 0.99 / 1.06 | 1.10 / 1.27 |
| falls grown passage 328 f | clean | 0.96 | 1.10 |
| rain closure 32 f | nothing noticed | 1.21 | 1.31 |
| pine7 cut closure 32 f | unnoticeable | 1.28 | 1.41 |
| neon closure 32 f | very hard to tell | 1.29 | 1.48 |
| dir_furnace closure 32 f | very slight | 1.36 | 1.57 |
| falls_loop closure 32 f | visible | 1.29 | 1.61 |
| dir_falls closure 32 f | very slight | 1.27 | 1.72 |
| furnace_mild closures 32 f | fairly noticeable | 1.54-1.62 | 1.67-1.80 |
| pine7 30 s closure 32 f | noticeable (shadow) | 1.47 | 1.83 |

Review DOUBT now also fires on worst region > 1.5 (and, after a grow, on the kept closure's worst region).
**Pattern across four scenes: every long two-sided bridge is clean (worst region <= 1.27); the visible transitions
are all 32 f closures.** Next test: a loop with no short closure at all (take + one long return sized to 30 s), on
the waterfall (`runs/endpoint/falls_loop_longreturn_g328/`): take[89:481] + one 328 f return, 30.0 s, churn 1.02 /
worst region 1.11, region drift over the loop 1.92, camera 0.01 px, closure step 1.13; entry join step 1.65 vs the
loop's own worst 1.46 (the only flag). Sent for review, verdict pending. With the furnace 320 f return (pending) this
is the basis of the proposed ADR 0012.

### M2: two-sided vs one-sided, same passage, same seed (report §8) — `experiments/furnace_controls/m2_onesided.py`

falls_loop take, the 328-frame passage after frame 281: two-sided = the grow stage's window; one-sided = the same
layout and seed 306 with the end context only. Worst 4x4-cell per-second luma outside the take's own envelope:

| second | 1 | 3 | 5 | 7 | 9 | 11 | 13 |
|---|---|---|---|---|---|---|---|
| two-sided | 3.2 | 3.0 | 3.5 | 3.7 | 3.1 | 2.9 | 3.2 |
| one-sided | 3.8 | 4.1 | 6.0 | 7.8 | 8.2 | 11.1 | 13.5 |

Mean luma first -> last second: two-sided 86.6 -> 85.8, one-sided 86.8 -> 89.6 (the mist brightens/builds); texture
residual equal (~1.1). **The future context is what holds the medium's statistics** (the ~3 grey floor in both is the
window-vs-take decode offset, see C1). Supports ADR 0011 over open-ended extension; one scene, one seed.

### Controls (C1 reconstruction, C4 positive) — `experiments/furnace_controls/controls.py`, `runs/endpoint/controls/`

Window [e-49, e+32+64) at e = 281 of the furnace_mild take.

| | gap churn (window) | gap step mean (linear clip / take) | entry join step (linear / take) |
|---|---|---|---|
| C1 recon: every latent clean = the take's own | 0.94 | 1.12 / 0.96 | 1.51 / 1.23 |
| C4 positive: 32 f gap generated between neighbours | 1.13 | 1.26 / 0.96 | 1.46 / 1.23 |
| the failed returns (take end -> frame 89), 32 f | 1.54-1.62 | | |

- **C1:** the same latents decoded in the window differ from the take's decode by ~1.2 grey/frame mid-window,
  ~5 grey at its first frames (the single-frame latent 0 + causal start) and ~2.5 at its end. Ablation of the splice
  on the recon: with neither per-frame tone matching nor the global sharpness target the join equals the take
  (entry 1.25 / gap 0.959 vs 1.23 / 0.959); per-frame tone adds most of the excess, the global sharpness target the
  rest (the take-wide median 284 vs 263 locally). A same-instant calibration (one LUT per side from context frames
  vs the take's frames of the same instants, lerped) reproduced the take exactly on the recon, but on real closures
  it was no better (furnace seeds churn 1.69-1.77 vs 1.64-1.71; rain mixed) and on the 320 f return it let the
  bridge overshoot ~2 grey mid-way: the per-frame lerped tone target is what holds a long bridge on a steady
  brightness path. **Not adopted; prototype deleted.** Assembly adds a small, measurable excess; it is not the
  furnace failure.
- **C4:** the model fills 32 frames between neighbouring furnace states cleanly (1.13, inside the pass band). Only
  the return fails, so per the report the lever is the pair / the time given, not conditioning or decoding: the
  320 f return (1.04) confirms "more time helps" for this pair.

## 2. Speed (report §5 W1)

The adapter's model card (downloaded) confirms the report: speed is a motion clock (`motion_fps = 24 / speed`),
playback stays 24 fps, no speed words in the caption, a generic LoRA loader gives none of the control.
Wired: `ltx.hooks(motion_speed=...)` scales every video token's temporal position (targets, clean contexts, IC guide
tokens) once per state construction, both stages, before the timestep plan is built; `clock_log` records the
actual transformer-input time span. Unit test: speed 1 = identity, 0.5 halves time only. Audio stays on (WanGP
hardcodes it) and its clock is not scaled. Access granted; the official demo
(`runs/speed/upstream/distilled_speed_demo.py`) wraps the diffusion stage with `fps = fps / speed` for BOTH stages,
which for video is exactly our position scaling (it may also retime audio; ours does not).

**W1 run** (`experiments/speed/run.py dir_lighthouse2`, 121 f, seed 306, same still/caption/depth lock). Logged
transformer-input time span: base / 1.0 -> 0-5.375 s, 0.5 -> 0-2.69 s, 0.2 -> 0-1.075 s, identical in both stages.

| condition | mean flow (px/f) | sea row flow (4 cells) | texture residual |
|---|---|---|---|
| base (no adapter) | 0.334 | 0.16 / 0.95 / 1.43 / 1.24 | 0.653 |
| LoRA speed 1.0 | 0.283 | 0.29 / 0.68 / 1.01 / 1.16 | 0.614 |
| LoRA speed 0.5 | 0.247 | 0.28 / 0.56 / 1.03 / 0.92 | 0.536 |
| LoRA speed 0.2 | 0.134 | 0.24 / 0.30 / 0.47 / 0.46 | 0.419 |

The control responds in order; residual falls with pace (no extra churn = no smear); 0.5 is only -13 % vs 1.0 (the
report's pilot bar is -20 %), 0.2 halves it; stills show no structural change, the sea still moves at 0.2. The
control is global (everything slows). Real-time pace judged by the user: `runs/speed/dir_lighthouse2/sbs.mp4`, pending.

## 3. Sparse tracks (report §4 L1)

`experiments/tracks/render.py`: CPU port of LTXVDrawTracks (50-frame trail, radius 2-8 at a 1080-px short side,
age colours, bilinear downscale, newest wins). The node hands ComfyUI a BGR-ordered tensor labelled RGB; writing our
RGB render through OpenCV reproduces that file exactly. WanGP infers the half-size reference from `ref0.5` in the
filename (raw "VG" route), so the guide is rendered once at 832x448. The still maps to the output by a squash
(480 -> 448 rows), not a crop. Furnace guide: 22 ember tracks born at the furnace mouth rising 1.2-2 px/frame with
sway, 50 frames of pre-roll history, + 12 anchors on points the source take holds within 0.6 px (camera stand-in,
no depth control in the first test). `runs/tracks/furnace_embers_l1/` (121 f; base = depth lock seed 306):

| | camera shift | region drift | moving highlights / frame in the ember band | upward highlight flow |
|---|---|---|---|---|
| base (depth lock) | 1.67 px | 2.59 | 65 | -0.007 px/f |
| tracks, seed 306 | 0.06 px | 1.21 | 18 | 0.005 |
| tracks, seed 307 | 0.12 px | 2.92 | 4 | 0.005 |

**L1 rejected for embers:** a max-brightening trail map shows no rising streaks where the guide has 22; the fire
region got calmer, not livelier. No guide colours leaked, structure intact. The adapter moves content that exists
("motion of objects or regions"); this still has no visible embers for it to move, so it cannot create them.
**Side finding:** 12 stationary anchor tracks held the camera at 0.06-0.12 px with NO depth control (the depth-locked
base drifted 1.67 px in this 121 f sample): the track adapter is a possible camera lock in its own right.
Not sent for review (no visible gain to judge). L2 (steady inflow) is moot until tracks can make embers.

### R3 reframed: the wheel should not rotate

The user's Last Furnace brief says "All industrial structures and enormous gears remain stationary", and the
furnace_mild take's time-averaged flow shows no coherent wheel rotation (the steady motion is mist along the bottom
left; an affine rotation fit over the wheel explains nothing: eigenvalues real, ~1e-3). A rotating-spoke guide (R2 /
R3 as written) would override the user's prompt (invariant 11). The spokes' streaking is re-synthesis of a wheel that
is meant to stand still, so the track experiment for it is stationary anchors ON the rim and spokes.
**Superseded in review (2026-09-27): the gears should not be forced to stay stationary, only look realistic when
they move.** The stationary-anchor variant was cancelled before it ran. The right R3 is rigid
rotation where the wheel moves (one angular speed across radii); it needs the wheel's geometry from a take where it
does rotate (dir_furnace s307, where review saw the wheel spin smoothly), and waits for L1 to show tracks work at all.

**R3 probe (capability test, hand-marked rim = not generic):** `experiments/tracks/r3.py`, 30 material-point tracks on
3 radii of an ellipse fitted to 8 rim points, one revolution per 40 s (0.0065 rad/frame) + L1's anchors. Measured
angular velocity per radius band (flow mapped into disk coordinates): base ~0, tracks seed 306 ~0.00006, seed 307
~0.00001 rad/frame, i.e. <= 1 % of the command; crops at frames 8/60/120 show no turning. Seed 306 also slid the
camera 7 px (anchors did not hold it this time). **No trajectory control observed.**

**Integration probe — the route works:** dragging the sun disc 80 px down with 5 tracks (`experiments/tracks/probe_sun.py`,
`runs/tracks/probe_sun/`): sun centre y 81 -> 83 -> 98 -> 120 -> 145 at frames 0/30/60/90/120 (63 of 80 px, lagging
then catching up); base 81-82 throughout. So WanGP's raw "VG" route + ref0.5 adapter + our renderer do reach the
model. **Conclusion:** the track adapter drags large distinct objects; it does not create absent particles (L1) or
turn a thin, dark, partly occluded lattice rigidly (R3). Anchors as a camera lock: 3 of 4 clips 0.06-0.13 px, one
7 px — not reliable enough to replace depth. **Tracks parked**; nothing generic to build from them now (a generic
use would need automatic tracks from the take, and the capability for the things we care about is missing).

## 4. Subject fidelity (report §9)

P1 adopted: direct v14 renders the still from a one-line prompt verbatim (the blind stills already favoured the
user's words 2 of 3 and the rewrite lost the waterfall twice); the director's version stays in direction.json.
**P2 (local VLM veto) rejected.** `experiments/subject_check/p2.py`, qwen3.6:35b, 12 blind stills x 2-3 grounded
questions, each asked twice in swapped order (an answer counts only if both orders agree): 14 OK, 16 REVIEW
(orders disagree), 2 WRONG. The two hard failures it had to catch: the director's no-waterfall still -> "uncertain"
(not caught as missing); the director's cold fireplace -> "a fire burning: yes" (invented), plus "snow inside the
room: yes" on the same still. The report's condition ("a veto only if it catches these errors without inventing
missing objects") fails. Not wired. `runs/still_ab/p2.json`.

## 5. Audits without GPU

- **R4 generated keyframe slots:** the installed LTX-2.5 distilled checkpoint has `keyframes_abs_pos_embedding`
  (config flag true) and WanGP already carries `keyframes_mask` into the transformer; missing is only the
  conditioning item that appends marked slot tokens (upstream `keyframe_slots.py`, ~60 lines). Feasible without a
  host change. Not built: the report ranks it "later".
- **Installed WanGP is 59e5560**, newer than the report's 2345ae1; the patched functions (`noise_video_state`,
  `denoise_audio_video`, `build_timestep_compression_plan`) matched the report's description.

## Not attempted this round (with reason)

F2 time-varying depth, F3 relight, R2 dynamic wheel proxy, R3 wheel tracks (after L1 shows tracks work), M1-M3 mist,
L3 / W3 alternate models, Q2 speed estimator, P3 FLUX.2: lower in the report's §12 order; each needs its own budget.

## 6. Long return on more scenes (ADR 0012 evidence, 2026-09-27)

take[89:481] + one 328 f return, seed 306 (`runs/endpoint/<run>_longreturn_g328/`, self-QC `experiments/furnace_controls/lrqc.py`):

| scene | churn mean / worst | motion return/take | boundary drift | loop drift (worst region range) | entry join |
|---|---|---|---|---|---|
| waterfall (falls_loop) | 1.02 / 1.11 | 1.0 | 1.92 | 8.69 | 1.65 |
| pine7 (take drifts 8.5) | 0.81 / 0.89 | 1.13 | 2.03 | **9.57** | 1.70 |
| neon | 0.99 / 1.12 | 1.08 | 1.01 | 1.71 | 1.62 |
| cabin | 0.98 / 1.18 | 0.93 | 2.46 | **9.23** (+1.8 grey global step entering the return) | 1.66 |
| furnace (320 f) | 1.04 | ~1 | 1.29 | 4.64 | 1.19 |

The churn is clean everywhere; the open risk is **slow regional swing**: a take that drifts one way and a return
that drifts back is a symmetric swell (pine c21 9.6 grey, near the extension loop's 10.5, seen in review as a passing
shadow). The endpoint-based take gate cannot see it; the new loop_drift can. Pine sent (calibrates the gate); cabin held.

**Entry-join step 1.6-1.9 is in the raw window** (last clean-context frame -> first generated frame): positive control
1.52, long returns 1.58-1.94, reconstruction (nothing generated) 1.23. Not the splice. Soft-collar test queued
(report C4: last/first context latent at strength 0.5 / 0.8).

## 7. CPU pass: performance, efficiency, QC (requested: CPU-side improvements, then implementation)

Profiled all 519 stage records: GPU stages dominate (take 11.6 min median, extension 8.4, closure 4.0, 4K chunk 31);
CPU: loop_qc 36 s x 3 seeds, join 22 s, deliver 20 s, splice 7 s.
- **loop_qc reference cache** (implemented): the take's QC reference was rebuilt for every seed; now once per
  process, keyed by path + size + mtime. Second seed 29.8 -> 16.5 s; results identical to the cached v3 outputs.
- **Vectorising regional_qc.analyze** (reverted): the per-frame RMS loop is memory-bound; 25.6 s -> 26.7 s.
- **Early accept of closures** (implemented, `early_accept` default on): stop at the first seed that is accepted, has
  closing <= 1.2, no flags and worst-region churn <= 1.4. Saves 1-2 closures per clean run (~8 min; ~28 with
  --long-return). Seeds of one take score within noise (closing +-0.05).
- **Shorter settle** (rejected with evidence): settle takes never plateau; worst-cell change between frame 240 and
  480: cabin 1.3, furnace 1.6, neon 3.4, falls 5.9-6.7, pine4 8.1, pine 40, lighthouse 43-62 grey. Halving it would
  give a different keyframe. The "settle" is itself drift; whether it helps at all is an open question.
- **Whole-loop slow drift** (implemented, loop_qc v5, review DOUBT > 8): see the table above for its first readings.
- **QOL:** dashboard / runsum / prune / verdict already cover run inspection; review push needs an
  external service (not set up).
- **Splice sharpness target** (tested, kept as is): on 8 real closures (furnace, rain, falls, neon) the current global
  target (take-wide median) beats a local one (2 s either side) and no matching: e.g. neon gap activity 1.26 global /
  1.27 local / 1.42 none; furnace churn 1.63 / 1.65 / 1.69. The C1 recon excess is real but smaller than what the
  target removes on generated gaps.
- **--long-return calmest stretch** (implemented): `loopkit.calmest_segment` picks s, e (>= 332 take frames) with the
  least within-stretch swing; the return (up to 388 f) fills the rest. First end-to-end use: lighthouse run below.
- **Soft collar (report C4), rejected:** positive control e = 281, seed 307, the context latent next to the gap on each
  side at strength 0.5 / 0.8. Raw window onset step: hard 1.52, 0.5 -> 1.27 but a new 1.50 step inside the formerly
  clean context and exit 1.50 -> 1.63; 0.8 -> onset 1.58, churn 1.13 -> 1.19 (worst region 1.25 -> 1.35). The report's
  stop rule ("drop collar tuning if it merely spreads visible change into formerly clean context") applies. Code removed.
- **Closure window cap is 481 frames** (WanGP `sliding_window_size`), not 501: a 497 f closure crashed. Return gap cap
  368 f; `close` refuses larger windows before GPU time.
- **Furnace 320 f return, second seed (314):** churn 1.05 / worst 1.13 (seed 313: 1.04), drift 1.23 -> not seed luck.

## 8. First end-to-end run with --long-return + --motion-speed 0.2 (lighthouse_lr_s02)

`python -m looper loop --image <dir_lighthouse2 settled keyframe> --no-settle --raw-prompt --prompt-file
runs/inputs/lighthouse2_motion_prompt.txt --long-return --motion-speed 0.2 --close-seeds 306,307`.
Take accepted (drift 2.45); calmest stretch 65-401 (2.61 grey swing) + a 368 f return (first attempt at 384 f crashed:
the 481 f window cap, fixed). Seed 306 failed loop_qc (closing 1.28), 307 accepted: closing 1.17, churn 0.98 / 1.10,
loop drift 3.82, joins 1.79 / 1.96 vs the loop's own worst 1.76 -> DOUBT. Sea flow at speed 0.2 is ~half the speed-1
clip's in both the take and the return (one clock across stages). Sent for review.

## 9. Ocean research round (reviewer: waves very poor; the lighthouse light missing entirely; low quality overall)

Verdict on lighthouse_lr_s02 (long return + speed 0.2): **neither join visible** — the pipeline mechanics hold;
the scene content fails.

Online research (sources in the final report to the user): diffusion video has no fluid solver; open models'
water tends to move as one viscous mass. Leads found: (1) HunyuanVideo 1.5 is cited as the strongest open model on
fluids (secondary source) and is installed locally -> bounded model comparison running (`experiments/ocean/hy15.py`);
(2) the union IC-LoRA takes a depth VIDEO (motion transfer), so a time-periodic Tessendorf ocean (quantised
dispersion -> exact loop, verified: frame(T) == frame(0)) could be written into the depth guide of the sea region
(`experiments/ocean/tessendorf.py`, `depth_guide.py`); (3) the LTX water-simulation IC-LoRA only ADDS water to dry
scenes (not applicable).

**Lead (2) stopped by the user before any GPU test: masking ruled out, attempt halted.** Region masks (a
sea mask, SAM3 segmentation) are out; consistent with ADR 0003 (no mask-and-animate) and the generic-methods rule.
The prototype code stays in `experiments/ocean/` only as a record; nothing masked will be wired.
- **HunyuanVideo 1.5 vs LTX, lighthouse still, 121 f** (`runs/ocean/hy15/`, sbs.mp4 not yet judged): sea-row flow
  HY 306 0.40-0.55, HY 307 0.81-1.26 px/f vs LTX base 0.16-1.43, LTX speed-0.2 0.24-0.47; camera held without depth
  control (0.05-0.18 px); HY outputs 864x464. Not judged by eye; not sent. Stopped at the user's request.
