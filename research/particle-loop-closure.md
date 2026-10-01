# Loop closure for particle motion (rain cabin): regional QC, source transitions, clean-context LTX (2026-09-24)

Hand-off plan: `CLAUDE_CODE_SEAMLESS_LOOP_HANDOFF.md` (user, 2026-09-24). Harness: `experiments/loop_eval/` (QC, search,
crossovers, blind review) and `experiments/ltx_clean/` (clean-context LTX gap / continuation). Source clip unless noted:
`experiments/user_image/chain/chain.mp4` (LTX-2.5 distilled, seed 306, 832x448, 24 fps, 241 f; usable 8..240).
Findings in section 5, recommendation in section 6, exact commands in section 7.

## 1. Regional QC (`loop_eval/rqc.py`, `calibrate.py`, `scenes/*.json`)

Masks come from the SOURCE only (scene boxes AND source activity >= the box's 25th percentile; static = source
activity < frame p40 away from all boxes), so a frozen region can't drop out of its own evaluation.
Regions (rain cabin): `glass` (4 panes of the tilted sash), `side_glass`, `rail` (sash edge + drip line below it),
`exterior` (open window: foliage + falling rain), `static`.

Per region, energy `E[r,b,k,t] = sqrt(mean_r((B(I_t) - B(I_{t-k}))^2))`, bands raw / fine (DoG .7/2) / coarse (DoG 2/6),
lags 1, 2, 4, 8 frames at 24 fps (matched in seconds at other rates), `R = E / median over the source`.
Bead tracks: top-hat (7x7) peaks above the source's p99 inside bead regions, mutual-nearest linking (radius 4 px),
links kept only inside >= 3-frame tracks; per frame: count/area, contrast, moving fraction (> 0.75 px/frame),
speed, births/deaths away from the pane border. Static: max 32 px tile |Sobel - source median| and tile luma.

Gates (each region on its own; the loop is evaluated cyclically):
| gate | rule | origin |
|---|---|---|
| low | 0.25 s rolling mean of raw R at lags >= 1/6 s < 0.5 | handoff candidate |
| low_texture | same at lag 1 (raw + fine) < 0.35 | split after the waterfall result below |
| spike | one-frame lag-1 R > max(3, the source's own max) | handoff candidate |
| beads | 0.5 s windows of moving fraction / speed / count / contrast / births / deaths outside [0.85 x min, 1.15 x max] of ordinary source windows; "insufficient" if the source has < 8 moving bead steps per window | calibrated |
| static | tile edge deviation > 1.5 x the source's own max; tile luma similarly (+1) | |

**Calibration (`reports/calib/calibration.json`)**, verdicts of the final gate set:
| case | verdict | what fails |
|---|---|---|
| source 8..235, no wrap | PASS | - |
| source looped with its own hard cut (235 -> 8) | FAIL | spikes (glass 1.35x, side glass 3.8x the limit), bead moving |
| freeze 0.5 s / 0.25 s | FAIL / FAIL | low, low_texture (0.0 / 0.15) |
| 0.5x slowdown for 2 s (blend / duplicate) | FAIL / FAIL | bead moving, births, deaths |
| contrast x 0.5 for 1 s | FAIL | low (0.47), bead count |
| jump (30 frames skipped) | FAIL | spikes, bead deaths |
| dissolve 12 f between different moments | FAIL | bead count (transparency), deaths |
| **Review E (failed human review)** | FAIL | glass low 0.43, low_texture 0.24, bead moving 0.021 (source min 0.055), rail low 0.36 |
| full-step VACE (`rain_v16full`) | FAIL | glass low_texture 0.30, bead moving 0.013 |
| LTX RePaint k5 / k6 (`ltx_gap/`) | FAIL / FAIL | bead moving/count, rail low, static luma |
| **waterfall Review D (passed human review)**, own scene `jungle_falls.json` | PASS | - (lag-1 0.40, lags >= 1/6 s 0.65) |
| seed 307 clip as held-out "ordinary" footage | FAIL | static tile luma 10.2 (a different room, see section 2), bead births/deaths above s306's range |
| seed 308 clip (drifts) | FAIL | everything |

Why `low` was split: with one lag-1 gate at 0.5 the human-passed waterfall FAILED (falls lag-1 0.40 in its RIFE'd gap)
while lag 8 stayed >= 0.75. Interpolated water loses per-frame texture change, not displacement, and the eye accepted
it. Review E drops at every lag (glass lag-8 about 0.55, lag-1 0.24). The thresholds rest on two human verdicts:
provisional. The old `loop_qc.py` passed Review E; its gates (brightness, sharpness, camera, global join) are blind to
regional motion. Limitation: no held-out clip of the SAME room exists yet, so the false-positive rate on ordinary
footage is untested beyond in-sample windows. The side-glass bead-moving statistic is the noisiest gate (few moving
tracks; it fails several otherwise clean crossovers).

Space-time slices (`*_slices.png`) show the Review E stall directly: diagonal bead streaks in the clip, horizontal
lines through the gap.

## 2. More source footage

- **481 frames in one LTX pass (seed 306, 12.8 min): unusable.** The room drifts from dark teal to amber lamplight
  and the sash geometry changes (`loop_eval/src481_sheet.jpg`). 241 f is the stable single-pass length here.
- 241 f seeds 307 / 308 (7.3 min each): **s308 drifts** the same way (rqc fails it everywhere). **s307 is stable but
  a different room:** median-frame difference vs s306 = 3.4 grey mean, with different bed wrinkles, lamp shade,
  outside cabin, sill cups and foliage layout (`loop_eval/s307_minus_s306.png`). **A cycle across seeds would
  re-dress the room at every transition** (the scene bleed already rejected in review), so multi-seed cycles are out.
  Longer source has to come from continuation of the same clip (section 4, extension).
- 361 f single passes (9.7 min each): **both drift** — seed 306 to amber by ~1.5 s (luma 25 -> 48), seed 307 slowly
  (20 -> 34 over 15 s). Every drift seen in this round is the room warming toward lamplight; suspected prompt-driven
  ("the bedside lamp glows with a warm ... light"). Steady-light prompt variant: see below.

## 3. Source-transition baseline (DIAGNOSTIC ALTERNATIVE, not generated closure)

`search.py`: all pairs (a, b), period >= 150 f (6.25 s), guard 3, crossover 12; cost = appearance (fine band) +
motion (frame-difference distance) + 2 x energy mismatch + 2 x quiet penalty + 0.5 x static, per region, each
normalised by its median over all pairs.
- **Best pairs are not closer than a random pair:** appearance 0.99-1.02x the median pair, motion 0.88-0.93x. A 10 s
  clip has no recurring drip configuration, so a direct cut always teleports beads. Cut-point search alone can't close
  a particle loop.
- Top pairs: P1 (44, 212), P2 (21, 213), P3 (54, 214); P0 (8, 228) = no search.

`xover.py`: two MOVING source streams, `C[k] = (1-a)V[b+k] + aV[a+k]`, loop = `V[a+L..b) + C`, 8-bit display-referred
BT.709 values mixed in float, no gain compensation, no stabilisation. Matrix (`loop_eval/xover/*_summary.json`):
| pair | L=0 | 3 | 4 | 6 | 8 | 9 | 12 |
|---|---|---|---|---|---|---|---|
| P1 (44,212) | FAIL spikes | FAIL side-glass spike | FAIL side-glass moving | **PASS** | FAIL bead count | FAIL count | FAIL count |
| P2 (21,213) | FAIL spikes, births | FAIL spike | **PASS** | **PASS** | FAIL count | FAIL count | FAIL count |
| P3 (54,214) | FAIL spikes | FAIL spike | **PASS** | FAIL side-glass moving | FAIL count | FAIL count | FAIL count |
| P0 (8,228) | FAIL spikes | FAIL spike | FAIL side-glass moving | FAIL side-glass moving | FAIL count | FAIL count | FAIL count |
The pattern is consistent: L <= 3 reads as a jump (one-frame spike, bead teleport), L >= 8 thins visible beads below
every ordinary source window (dissolve transparency), **L = 4-6 frames (0.17-0.25 s) passes every regional gate on the
searched pairs**; the unsearched pair P0 only misses on the noisy side-glass statistic. Automatic only; the eye decides
(blind set `loop_eval/blind3/`, manifest `loop_eval/blind3_MANIFEST.json`; blind1/2 superseded).

`pane_xover.py` (space-time switch): per-pane switch times (mullions as boundaries), 24 f overlap, each cell ramps over
Lc frames where its two streams disagree least, switch times >= 3 f apart. P2 Lc 6: PASS. P1 Lc 4/6: side-glass bead
gates fail.

## 4. Clean-context LTX (`ltx_clean/gen_job.py`)

**Checked in code (WanGP `models/ltx2`):** the RePaint patch (`ltx_gap/`) starts every token as noise (the noiser
scales by denoise_mask = 1) and re-pins context only after each step as `noise*s + (1-s)*source`; with the distilled
schedule 1.0, .994, .988, .981, .975, ... the gap sees < 3 % context signal for the first five steps. That confirms the
handoff's hypothesis that the layout forms before usable context is visible.

New driver: context goes through LTX's own conditioning path, `VideoConditionByLatentIndex(strength 1)` (as WanGP's
I2V first frame and video-continuation prefix): clean tokens in place, denoise_mask 0 -> per-token timestep 0, untouched
by the noiser, restored by `post_process_latent` after every step. Prefix = window frames 0..8(P-1) encoded as their
own clip (causal VAE, so clean); suffix = window frames from 8(I0-1)+1 encoded with the first frame duplicated in
front and that single-frame latent dropped, so latent groups align with the window. Both stages (416x224, 832x448).
Logged diagnostics (`clean_diag.json`), both stages: denoise mask 0 on every context latent and 1 on the gap; latent
start times 0, 0.042, 0.375, 0.708 ... s (24 fps, causal first frame); context tokens identical to the clean latents
after noising and **max |change| = 0.0 after denoising**; no attention mask (full attention: the gap sees both sides);
the depth IC-LoRA control is appended as its own tokens. Not verified: that the distilled checkpoint was trained on
mid-sequence clean-latent conditioning (no training config for the released weights checked).

**Natural-repair controls (window = chain frames 48..192, seed 306, 5-5.6 min each):**
| run | gap | glass energy gap/orig | rail | glass bead moving | notes |
|---|---|---|---|---|---|
| VAE only (context frames of every run) | - | 0.69 | 0.69-0.71 | 0.62-0.65 | bead count 0.80, exterior 0.53-0.57, luma -2.4, MAD 2.8 |
| nat_g16 | 16 f | 0.71 | 0.95 | 0.59 | exterior/side glass busier (1.6-1.8) |
| nat_g24 | 24 f | 0.57 | 0.66 | 0.42 | |
| nat_g48 | 48 f | 0.65 | 0.56 | 0.47 | |
- **The codec itself is the largest single loss:** encode -> decode of real frames keeps only ~0.69 of glass motion
  energy and 0.80 of visible beads. Anything that round-trips footage through the LTX VAE loses drips.
- Relative to that reconstruction the regenerated gaps move at 0.8-1.0x (glass) and ~0.7x (bead moving fraction):
  **no VACE-style stall** (VACE 0.1-0.25x), and the layout holds (RePaint without clean context made a new shot).
- Generated-gap luma matches the real clip (20.4-21.7 vs 20.5); the decoded context is darker (18.0).

**Closure (window = last 49 f of the loop segment | gap | first 48 f; `assemble.py`):**
- close_s306 / close_s307, 48 f gap: geometry holds, but **both drift into a lighting pulse** (luma 18 -> 28.8 / 24.4
  -> 17.5; exterior foliage brightens and yellows mid-gap), exterior/side-glass energy reaches 3-4x. FAIL (static luma,
  spikes, bead counts). Joins: hard 5.2 / 6.7x median step, with an 8-frame in-overlap ramp 1.6 / 1.5x. Per-channel
  histogram matching of the gap toward the real endpoints doesn't rescue it (joins 3.9 / 6.0x against the darker
  decoded context).
- 16 / 24-frame gaps (re-encoded context): the pulse shrinks with the gap (24 f: 18.3 -> 21.8 -> 17; 16 f: spikes).
  close_g24_s306 is the best re-encoded closure. Assembly variants (`assemble.py`): an 8-frame in-overlap ramp halves
  the visible beads (count 28 -> 14: it mixes real beads with the VAE's weaker, displaced re-render, a mini dissolve);
  a hard splice spikes (5.2x); **3-frame ramp with each LTX frame histogram-matched to its real twin + tone-matched
  gap ("ramp3_tone2") passes every energy/spike gate**; left: glass bead-moving near the wrap, side-glass stats,
  diffuse grain in the dark wall (static edge gate). Sharpening is not the issue (the gap already matches).

**Continuation (extension) for a 30-60 s take (`run.py extend`, `concat_ext.py`, `build_long.py`):** prefix = last
49 real frames, 192 new frames per run (7 min), chained 3x -> 817 frames / 34 s, room and brightness hold (no amber
drift, unlike the 481 f single pass). The real -> generated splice needs the same tone-matched 3-frame ramp (then no
spike, static luma passes). **But the motion decays with each generation:**
| new footage vs source | glass E lag1 | rail | exterior lag4 | glass bead moving | bead births | static luma / src max |
|---|---|---|---|---|---|---|
| ext1 (context re-encoded) | 0.58 | 0.82 | 1.05 | 0.44 | 0.50 | 1.9 |
| ext2 | 0.44 | 0.69 | 1.04 | 0.35 | 0.43 | 3.0 |
| ext3 | 0.40 | 0.57 | 1.12 | 0.49 | 0.40 | 3.6 |
| **ext1_true** (context = the clip's own latents) | **1.01** | 1.62 | 1.25 | **0.99** | 1.40 | 2.1 |
| ext2_true (chained on ext1_true's latents) | 1.07 | 2.56 | 1.86 | 0.98 | 1.69 | 3.2 |
- **Cause of the decay, verified:** the context was the decoded clip re-encoded; re-encoded latents differ from the
  clip's own latents by 0.33 mean |d| at std ~1 (0.25 at half res), and the model continues at the intensity of the
  weakened context. Re-running the clip with identical settings reproduced it bit-exactly (MAD 0.0), so its own
  latents could be saved (`gen_job.py "_save_latents"`: stage-1 latent before the upsampler, final latent before
  the decode) and used as context: glass motion back to 1.0x.
- True-latent chaining overshoots and compounds the other way (rail 2.6x, bead count 2.1x, exterior 1.9x by the second
  step). Neither pure variant gives a stationary 30 s take yet. (Stage-1-only true latents: pending.)
- A crossover closure of the re-encoded 34 s take joins calm continuation footage to the busier original (search
  energy term 0.43-0.5, ~1.6x): rqc fails it (`loop_eval/reports/long/`).

**Generated closure on TRUE latents both sides (`run.py close2`, `assemble2.py`):** loop = base clip frames 9..240 +
24-frame LTX gap (prefix = the clip's last 49 frames as its own latents 25..30, suffix = frames 9.. as latents 2..);
start frame 9 so the suffix opens a latent group. Seed 306, 5.1 min.
- Motion: glass energy >= 0.80x everywhere, loop_qc speed ratios 0.95-1.24: **no stall, no snap.**
- The gap comes out 33 % sharper than the clip (Laplacian); matched with one global Gaussian blur (sigma 0.41).
- After that: rqc fails only glass bead-moving (burst near the loop point), side-glass spike/moving (noisiest region)
  and static edges, all at loop frames 249-252: a faint whole-frame structure twitch (1.3 vs ~0.75 median step) 7
  frames before the loop point. Old loop_qc: PASS.
- Seeds 307 / 308: **glass passes every gate on both** (energy, spikes, all bead statistics). Left on all three seeds:
  side-glass statistics, a one-frame exterior/side-glass spike and static edges. Frame-step profiles of the raw LTX
  windows put the largest steps in the LAST generated latent group before the start context (window frames 65-68 for
  s306/s307, 59-61 for s308; 2-4x median), i.e. the model catches up to the start frames: a small version of VACE's
  end snap (VACE 7-8x). Re-encoded-context closures show the same at the gap -> suffix boundary (window 70-74).

**Gap length (true latents, seed 306):**
| gap | largest raw step in the gap (x median) | rqc fails after assembly |
|---|---|---|
| 16 f | 2.34 (frame 57) | glass bead moving/births/deaths, side glass, exterior spike, static |
| 24 f | 2.19 (frame 66) | glass bead moving, side glass, static edge |
| **32 f** | **1.58** (frame 74) | **side-glass bead moving (noisiest stat), static edge (dark-wall grain) only** |
| 40 f | 4.14 (frame 82) | side glass, exterior spike, static |
32 frames is the sweet spot on this seed: long enough that the model doesn't have to catch up in the last latent
group, short enough not to wander. (Seed check below.)

**Stage-1-only true latents** (continuation, re-encoded latents in stage 2): in between (glass 0.77x, bead births
0.94x, rail still 1.5x). The rail overshoot comes from stage 1, the glass decay from stage-2 re-encoding. Not pursued.

**Blended context latents (alpha x true + (1-alpha) x re-encoded, alpha 0.5):** the most source-like single
continuation (glass 0.81x, rail 1.19x, bead moving 0.80x, births 1.00x, count 1.22x), but chaining still drifts
(step 2: glass 0.71x, rail 1.55x, moving 0.60x). No variant tried gives a stationary chained take.

**Closing a continued take with the 32 f true-latent gap** (`close2_a5_g32`: clip + one alpha-0.5 continuation = 18 s,
19 s loop): the take holds (glass 0.85-1.0x), but the closing gap bursts (side glass / exterior ~3x, static luma and
edges ~3x the source max): the continuation's room has drifted slightly (static edge 1.4x), and the gap must reconcile
two versions of the room. **Generated closure is clean only when both ends come from the same generation.**

**First-generation 26 s take** (`run.py prepend`, `build_fg.py`): a backward piece generated BEFORE the clip (suffix
context = the clip's first latents, frame 0 conditioned on the keyframe and its fade-in discarded) + the clip + a
forward piece, every generated frame conditioned directly on the clip's own latents, closed by a 24-frame true-latent
gap (`close2_fg_g24`, 26.3 s loop). The backward piece moves at source-like levels (glass 0.87x, rail 1.15x, bead
moving 0.85x) but re-dresses the bed's fabric folds slightly (static edge gate 2.5x the source max for its whole
length), so its splice would show a small morph. rqc FAIL; not sent.

## 5. Findings (observations vs hypotheses)

Observed (measured this session):
1. **Review E's failure is regional and every-lag**: glass energy 0.43x (lags >= 1/6 s) and 0.24x (lag 1), bead
   moving fraction 0.021 vs >= 0.055 in every ordinary source window, then a one-frame catch-up. Global checks
   (brightness, sharpness, camera, whole-frame change) cannot see it.
2. **The LTX VAE round trip is lossy for drips**: re-encoding decoded frames keeps ~0.69 of glass motion energy and
   0.80 of visible beads; re-encoded latents differ from the clip's own by 0.33 mean |d| (std ~1).
3. **RePaint-style context is invisible while the layout forms** (code: context re-pinned after each step at
   noise*s + (1-s)*source; s >= .975 for the first five of eight steps). Clean timestep-0 conditioning through LTX's
   `VideoConditionByLatentIndex` keeps the layout and the room.
4. **Conditioning on re-encoded context transfers the codec loss** (continuations at ~0.6x); **on the clip's own
   latents it doesn't** (1.0x) but overshoots rail/bead density over generations.
5. **Both-ends LTX closure length matters**: 32 frames minimises the catch-up step (1.6-2.1x over 3 seeds); 16/24 f
   catch up late (2-4x), 40-48 f wander (lighting pulse, 4x).
6. **Crossovers between moving streams of one take**: 4-6 frames pass every regional gate; <= 3 jump; >= 8 go
   transparent (bead count below every source window).
7. **Cut search inside one 10 s clip finds nothing better than random** for particles.
8. **Different seeds are different rooms; long single passes and some seeds drift to amber lamplight.**

Hypotheses (not verified):
- The rail/bead overshoot of true-latent continuation comes from stage 1 (stage-1-only true latents keep it) —
  mechanism unknown.
- The 2-4x catch-up step is the model reconciling bead positions with the fixed start latents; a longer gap spreads it
  until the model starts to wander (~40 f).
- Whether a 4-6 frame crossover or the 32 f generated gap is perceptible at normal speed: **human review pending**.
- rqc thresholds rest on two human verdicts (Review D pass, Review E fail) plus synthetic controls; the side-glass
  bead statistics are too noisy to gate on (they fail clean crossovers).

## 6. Recommendation

1. **Get the blind verdict first** (`experiments/loop_eval/blind3/`, sent 2026-09-25; manifest
   `blind3_MANIFEST.json`). It contains: crossover L6, direct cut L0, per-pane crossover, generated 32 f closure on two
   seeds, and Review E as a known-bad anchor.
2. If the 32 f true-latent LTX closure is imperceptible: it satisfies invariant 10 as written; adopt it as ADR 0006's
   LTX variant for particle scenes (ADR 0007 option 2). Requires saving latents at generation time.
3. If only the crossover is imperceptible: decide ADR 0007's narrow exception (same take only, <= 6 frames, rqc-gated).
4. For 30-60 s: neither chained continuation nor cross-seed cycles is stationary/consistent. Next experiments: longest
   stable single pass (361 f test below), per-piece intensity control (alpha), or a unit made of first-generation pieces
   with space-time (per-pane) joins. Treat a stationary same-room take as the open problem.

## 7. Reproduce (WanGP venv python, repo root; runtimes on the RTX 3060 6 GB)

```
PY=<WanGP>/.venv/Scripts/python.exe
# QC + calibration (CPU, ~1 min per loop; calibration ~15 min)
$PY experiments/loop_eval/rqc.py experiments/loop_eval/scenes/rain_cabin.json LOOP.mp4 --marks GAP_START --label X
$PY experiments/loop_eval/calibrate.py
# source-transition baseline (CPU)
$PY experiments/loop_eval/search.py experiments/user_image/chain/chain.mp4 8 240 --min-period 150 --L 12
$PY experiments/loop_eval/xover.py experiments/user_image/chain/chain.mp4 21 213 0,3,4,6,8,9,12 experiments/loop_eval/xover --tag P2
$PY experiments/loop_eval/pane_xover.py experiments/user_image/chain/chain.mp4 21 213 experiments/loop_eval/xover/P2_pane_Lc6.mp4 --Lc 6
# clean-context LTX (cd experiments/ltx_clean; ~5-7 min per GPU run, 4.3 GB VRAM, ~54 GB RAM)
$PY base_latents.py base306                                            # bit-exact rerun of the clip, saves latents (7.1 min)
$PY run.py nat_g24 natural --w0 48 --P 8 --I0 11 && $PY eval_natural.py nat_g24
$PY run.py close2_base_g32 close2 --chain base306 --end base306 --start 9 --P 7 --I0 11 --seed 306
$PY assemble2.py close2_base_g32 base306/chain.mp4 --match-sharp --label true_sharp
$PY run.py ext1_true extend --chain base306 --true base306 --frames 241 --seed 401 --save-latents
$PY cmp_ext.py ext1 ext1_true
# blind set
$PY experiments/loop_eval/blind.py experiments/loop_eval/blind3 23 LOOP1.mp4 LOOP2.mp4 ...
```
Inputs: keyframe `experiments/user_image/rain_cabin_832.png`; clip settings `experiments/user_image/chain/settings.json`
(LTX-2.5 22B distilled, 8 steps, 832x448, 24 fps, 241 f, depth IC-LoRA "DVG" with the still keyframe, seed 306). Every
run writes `run_meta.json`, `gen/settings.json`, `gen/clean_diag.json`, `gen/ltx.mp4.meta.json` (runtime, peak VRAM/RAM).
Colour domain for all mixing: 8-bit display-referred BT.709 as decoded by OpenCV, float intermediate, rounded once;
intermediates 4:4:4 crf <= 10 mbtree=0; review files 4:2:0 crf 17-18 mbtree=0.

## 8. Later additions (2026-09-25): a stationary 20 s take

- **The long-pass drift is prompt-driven.** Replacing "the bedside lamp glows with a warm, perfectly steady light"
  with "the small bedside lamp gives a dim, perfectly steady light; the overall lighting, exposure and colour of the
  room stay exactly constant ..." (+ negatives: brightening, exposure change, warm amber glow spreading, ...;
  `ltx_clean/long_src.py`) holds 361 f (luma 19.8-21.3) and **481 f = 20 s in one window** (`ltx_clean/steady481`,
  seed 306, 12.6 min, 3.8 GB VRAM, 56 GB RAM, latents saved): luma 20.6-21.1, glass bead count flat (slope
  -0.09/s), glass/rail/exterior energy 0.9-1.1x of its own median in every second, camera <= 0.21 px / zoom <= 0.03 %
  (`loop_eval/trend.py`). The 361 f steady pass accumulated beads (+1/s); the 481 f one did not.
- **721 f request = 481 f window + a WanGP continuation window**: stationary to 20 s, then an exposure step at frame
  ~482 (luma 20.6 -> 24.1) and calmer rain (rail 0.65x). WanGP's LTX default `sliding_window_size` is 481. Forcing a 721 f window fails:
  WanGP caps `sliding_window_size` at 501 frames (20.9 s) for this model. 30 s needs one continuation.
- Crossover on the steady take (pair 46 -> 470, 17.7 s): L 4/6 now FAIL on a burst of glass bead births / moving
  right after the crossover (1.3x this calmer take's own maximum). They passed on the first clip only because its
  natural variation was larger. The crossover's bead-identity burst is real and measurable; whether it is visible is
  for the blind review.
- **32 f true-latent closure on the 20 s take** (`st481_g32_s306/7/8`, loop 21.0 s, scene `rain_steady481.json`):
  a systematic catch-up step at window frame 74 on all 3 seeds (4.2 / 5.9 / 5.7x median), the 2nd frame of the LAST
  generated latent group before the start context. The same position is the maximum in every close2 run in this round
  (66 for 24 f, 74 for 32 f, 82 for 40 f, 57 for 16 f); on the base clip it was only 1.6-2.1x.
- **Retiming it** (`fix_snap.py`: frames p-1..p+2 replaced by DIS-flow interpolation between generated frames p-2 and
  p+3, i.e. a retime inside the bridge, invariant 10 permits it): step 5.9x -> 1.7x (20 s take), 1.6x -> 1.0x (base).
  rqc on the 21 s loop then passes every energy and spike gate in every region; left: glass bead count dips across the
  4 interpolated frames (they look softer for ~0.17 s in crops) and bead-moving right after the wrap, plus the usual
  side-glass / grain flags. Sent as blind set 4 (fixed vs unfixed, codes in `loop_eval/blind4_MANIFEST.json`).
- **30 s take + 31 s loop** (`ltx_clean/st_ext_a5`, `longST.mp4`, `st30_g32`): the 20 s stationary window extended by
  240 frames (alpha-0.5 context, steady prompt, 8.1 min) -> 721 frames; the continuation holds (luma 20.8 -> 21.5,
  glass 0.92-1.0x, rail 0.83-1.06x, bead count flat, slope -0.07/s). Closed with the 32 f true-latent gap (end context =
  the continuation's own latents, start = the 20 s window's latents 2..) + `fix_snap.py` (5.3x -> 1.8x): 31.0 s loop,
  every region ~1.0x for 30 s, the continuation splice at 19.7 s clean; energy/spike gates pass. Left: the last ~0.7 s
  before the loop point runs 1.5-2.5x busier (spread over ~16 frames, not a single snap), static edge 2.0x there, bead
  moving/deaths flags at the wrap. Sent to the user (not blind) as `loop_eval/review30/REVIEW_31s_x2.mp4`.
- Closure seeds on the 30 s take (306/307/308/309): all alike after the retime (closing 30-step window mean
  1.52-1.58x, max 2.4-2.8x); raw snap 5.3-8.1x at window frame 74 every time. Seed selection doesn't help.
- **Soft first start-context latent** (`run.py --suffix-soft 0.5 / 0.25`: that latent's denoise mask 0.5 / 0.75, its 8
  frames treated as bridge): the raw snap stays at frame 74 (6.9 / 8.2x), so it is NOT the model catching up next to
  the fixed start latent; it sits at the 2nd frame of the last fully generated latent group whatever follows.
  Hypothesis (untested): a decoder effect at the first latent group whose neighbours are all clean context. After the
  retime the closing window is calmer (mean 1.29 / 1.27x vs 1.52x) but rqc flags more bead statistics. Not sent.

## 9. Human verdict (2026-09-25, blind; `experiments/loop_eval/VERDICTS_blind.md`)
- **Generated true-latent 32 f closure on the 10 s clip: imperceptible on both seeds shown (306, 308).** First rain
  loop to pass a human, and it satisfies invariant 10 as written (ADR 0007, option 2 accepted).
- Crossovers: per-pane: nothing noticed; 6-frame: glass fine, possibly a slight disturbance in the bushes outside;
  direct cut: a visible jump. Review E anchor correctly judged slowed or stopped.
- **Long takes fail at the stitch:** 21 s (with and without the retime) and 31 s: a visible jump, and the window-rain
  distortion breaks up. rqc agreed in direction (the 10 s closures passed every energy/spike gate; the long ones needed the
  retime to pass them and still flagged bead count/births at the wrap), but the retime fooled the energy gates while
  the eye still saw the stitch. Lesson: the 4-8x raw catch-up on long takes is the real problem; hiding it with 4
  interpolated frames does not work. Next: find why the snap is 1.6-2x on the 10 s clip and 4-8x on the 20 s take.

## 10. Why the long-take stitch jumps (2026-09-25, after the verdict)
Largest raw step in the 32 f gap (window frame 74), absolute grey levels (ratio to the window's context median):
| run | end context | start context | prompt | step |
|---|---|---|---|---|
| close2_base_g32 s306/307/308 | 10 s clip end | clip frame 9 | original | 0.93-1.22 (1.7-2.2x) |
| st481_g32 s306/307/308 | 20 s take end | take frame 9 | steady | 2.24-3.13 (4.6-6.5x) |
| st481_g32_origprompt (s307) | 20 s take end | take frame 9 | **original** | 3.11 (6.5x) |
| base_g32_steadyprompt (s307) | 10 s clip end | clip frame 9 | **steady** | 1.35 (2.5x) |
| st_firsthalf (s307) | 20 s take frame 240 | take frame 9 | steady | 3.21 (6.3x) |
| **st_secondhalf (s307)** | 20 s take end | **take frame 241** | steady | **0.53 (1.1x), no snap** |
- Not normalisation (context steps 0.48-0.56 everywhere), not the prompt, not how far apart the end and start look
  (end-vs-start MAD / typical 1-4 s MAD: 1.27 clip vs 1.39 take).
- **It is the start context: returning to frame 9 = latents 2.. right after the I2V fade-in.** Those early latents are
  still settling out of the conditioning image; the gap has to snap into them. Returning to mid-take latents: no snap.
  The 10 s clip had the same weakness, milder (hypothesis: the long pass's early latents are further from its
  steady state). Fix under test: start the loop later (frames 49 / 97).
- **Fix confirmed:** returning to take frame 49 / 97 removes the frame-74 snap (1.1x). A 13 s alpha-0.5 continuation
  (361 f window) makes a 33 s take (`longST2.mp4`, bead slope -0.01/s); loop = frames 89..792 + 32 f true-latent gap,
  3 seeds, no retime needed: largest closing step 2.17-2.31x vs 2.28-2.29x elsewhere in the loop; every energy, spike
  and static gate passes (static edge 14.3 vs 19-27 on the frame-9 loops); glass bead-moving/deaths still flagged.
  **Seed 307 (30.7 s) in review: nothing noticed** at the loop point, the internal join or as repetition.
  **First imperceptible 30 s rain loop.** Rule: never return the loop into the first ~2-4 s of an LTX I2V pass.

## 11. Accept rule for the pipeline's loop_qc (automatic regions, calibrated on the 10 judged loops)
| loop | human | closing/rest | auto-region flags |
|---|---|---|---|
| AHT / NMQ (10 s, generated) | pass | 1.80 / 1.75 | static.edge_dev |
| CWP (pane crossover) | pass | 1.16 | - |
| OAD (6 f crossover) | pass (bushes slight) | 1.45 | - |
| 30 s v2 | pass | 0.98 | static.edge_dev |
| LEX (direct cut) | fail | 4.76 | spikes |
| GIO (Review E) | fail | 1.79 | low, low_texture, spike, static |
| PDY (21 s, raw snap) | fail | 2.78 | spikes, static |
| MEV (21 s, retimed) | fail | 1.18 | static only |
| 31 s (retimed) | fail | 1.10 | static only |
Rule: reject on any spike / low / low_texture flag or closing/rest > 2.0; static.edge_dev is not a reject (3/5 passes).
Separates every UN-retimed case correctly. **The two retimed fails are invisible to every metric** (interpolated
frames spread the snap into a soft moment the eye still sees): the pipeline never retimes (`fix_snap.py` not ported).

### 11b. Spike gate scoped to modified frames (2026-09-26, loop_qc v2)

The spike gate (one-frame lag-1 activity > max(3, the take's own max)) rejected three closures for spikes in
UNMODIFIED source frames: dir_lighthouse2 c20 (sea swell, frame 282 = 11.8 s of a 17.7 s loop, every seed) and
dir_cabin c10/c11 (fire, frames 294/318). The closure being judged did not put those frames there. Rule now: a spike
rejects only inside the frames the pipeline generated or ramped — closure gap ± ramp ± 12 f, the wrap, the extension
join ± 20 f (`loop_qc.in_modified`); elsewhere it is recorded as `natural_spikes`.

Scan of every persisted loop_qc (11 spike rejects across all runs): 6 released (the three scenes above), 5 kept — and
all 5 kept ones sit inside the closure gap (cabin 307/308 c10 at 16.2 s of 17.7; pine7 308 c21/c22 at 28.8 s of
30.0). No human-passed loop had ever been spike-rejected, so the calibration of §11 is untouched. Re-judged with v2,
lighthouse2's three closures accept (closing 1.03–1.25) and cabin 306 accepts (1.27).

## 12. The pipeline (`python -m looper loop`, 2026-09-25)
First end-to-end run `runs/rain_loop_e2e` (keyframe + steady prompt, --seconds 30): take 12.4 min (drift 2.4 %,
camera 0.06 px), extension 8.4 min (345 f window), 3 closures ~4 min each (warm in-process session), all 3 accepted
by loop_qc; 35 min total. Resume: an identical rerun restored 11 stages in 3.3 s.
- v1 (3-frame ramp, crf-10 4:4:4 master): reviewer saw something very slight around 30 s. Cause measured: the
  master file's own codec wrap (last P-frame -> first keyframe) raised the loop-point step 1.76x -> 2.19x; every
  4:2:0 setting tried (crf 12-17, ipratio/pbratio 1.0, keyint 24/48) left the file wrap 1.16-1.24x above the loop's
  natural max.
- v2: lossless loop master (x264 qp 0) + 8-frame in-overlap ramps (true-latent re-render within 1.3-1.8 grey of the
  real frames, so the longer ramp costs nothing): master wrap 1.58-1.67x (natural max 2.28x), ratio 0.73-0.79 on all 3
  seeds. Delivery encodes 4 periods continuously (internal loop points 1.53-1.56x) and stream-copies that 2-minute
  block, so the codec seam occurs once per 2 min. **Reviewer: nothing noticed.**

## 13. Generalisation: waterfall and neon alley through the pipeline (2026-09-25)
- **Waterfall** (`runs/falls_loop`, seed 306 take): pipeline accepted all 3 closures (closing/rest 0.92-0.96), but
  the **reviewer saw a shift in the scene at each phase**, clearly worse than the rain. Measured: the take is not
  regionally stationary — foliage / side-fall cells brighten 11-14 grey over the 20 s take (29 with the extension)
  while global luma moved only +3.7 %; the extension came out 12 % sharper than the take at the join. The closure
  then has to undo ~10 grey of regional change in 1.3 s. Flow/spray energy matched across both phases, so longer
  context (the user's question) would not address these causes.
- **Neon alley** (seed 306 take): also drifts — the steam plume migrates from the left toward the centre / upper
  right and the distant haze brightens (end-vs-start cell difference 9.7 grey, residual flicker only 1.9).
- Rain take for comparison: worst cell 1.7 grey (1.4 end-vs-start).
- Fixes: `take_qc` stage (per-region 3x4 grid luma range <= 4 grey, plus the old global/camera gates; separate CPU
  stage so gates change without regenerating) → drifting takes retry the next seed; `join` stage (CPU) with
  sharpness matching + the same gate on the extended take.
- Tried and dropped: searching loop start/end points for matching scene states (1 s-averaged low-res frames).
  Rain 1.78 → 1.0-1.7, but the waterfall only 14.5 → 9.6-11: a take that drifts one way has no matching pair.
- **Neon alley, 3 seeds (306/307/308): all rejected by take_qc** (worst region 16.2 / 34.4 / 8.8 grey; global drift
  2-4 %, camera 0.1-0.7 px). The pipeline stopped with "no stationary take in 3 seeds" instead of making a loop the
  gates predict will show a shift. (An earlier attempt OOMed because two runs were accidentally started at once;
  `wangp.generate` now frees the CUDA cache first and retries once on OOM.)
- Working hypothesis (1 pass, 2 fails): scenes made of many small, statistically steady elements (rain on glass) give
  stationary LTX takes; scenes with a few large, slowly evolving structures (steam plume, mist, haze) wander over 20 s.
  Next: prompt the drifting element to stay put ("steady, unchanging column"), as the steady-light wording did for
  the lamp; else loop a shorter stationary stretch.
- **Neon with "thin, steady column of steam ... never spreading or drifting" (+ negatives billowing/spreading steam,
  fog rolling in, haze thickening), `runs/neon_steady`: no change.** Worst region per seed 18.4 / 35.3 / 8.3 grey vs
  16.2 / 34.4 / 8.8 with the old wording: the drift follows the seed, not the words. Contact sheet (seed 307): the
  plume keeps billowing upward and accumulates in the top-middle behind the signs, which ends much brighter / hazier
  than it starts. Prompting fixed lamp brightness drift but not steam accumulation.
- Waterfall seeds 307 / 308 improved on 306 (worst region 7.7 / 6.7 vs 13.7) but still failed the 4-grey gate. Reviewer
  on the raw seed-308 take (not a loop): looks steady. The 4-grey gate is calibrated on only 1.7 (pass) vs 13.7
  (fail); a calibration loop from seed 308 with the gate at 8 is queued.
- **Take-drift calibration (review verdicts):** region drift 1.7 grey (rain) → loop: nothing noticed; 6.7 (waterfall
  s308, 17.7 s loop, no extension, loop_qc fully clean, brightness 79.5 ↔ 79.5 at the wrap) → **very slight**; 13.7
  (waterfall s306 30 s) → a shift at each phase. The 4-grey gate sits on the right side of very slight; keep it.
  The seed-308 extensions drifted 13.1 / 16.7 grey (extensions add drift), so 30 s failed there; <= 17.7 s loops need
  no extension. Neon steam take s307 (35 grey): the steam build-up is clearly visible in review.

## 14. Extension drift A/B (2026-09-25, `experiments/ext_ab/`, waterfall seed-308 take, seed 403, +296 frames)
| context | alpha | whole-take worst region drift (from frame 89) |
|---|---|---|
| 49 f (baseline) | 0.5 | 13.1 (seed 404: 16.7) |
| 97 f | 0.5 | 17.9 |
| 145 f | 0.5 | 16.6 |
| 49 f | 1.0 | 22.8 |
| 145 f | 1.0 | 17.8 |
- **Neither longer context (up to 6 s) nor pure own-latent context reduces extension drift.** The drift is always in
  the upper-left cells: the mist over the foliage keeps building / clearing. Within its own 12 s the waterfall
  extension drifts 9.6-16.8 grey vs 5.8 for the take's 16 s (rain extension: 0.7). Same class as the neon steam:
  an accumulating element, not missing context. Next: settled keyframes (accumulating elements already at their
  steady state).

## 15. Settled keyframes (2026-09-25, `experiments/settle/`, `runs/neon_settled`)
Keyframe = frame 480 of the most built-up neon take (steady-steam s307: steam already filling the alley), same scene
prompt as the original neon runs, 481 f takes:
| seed | original keyframe (region drift, grey) | settled keyframe |
|---|---|---|
| 306 | 16.2 (18.4 steady wording) | **6.7** |
| 307 | 34.4 (35.3) | **9.5** |
| 308 | 8.8 (8.3) | 10.0 |
- Mean ≈ 20 → ≈ 9 grey and no 35-grey takes: **starting from the steady state works where prompt wording did not**,
  but none reached the 4-grey gate. Next: a loop from settled s306 at gate 7 for a human verdict, and a second
  settling pass (keyframe = frame 480 of the settled s306 take) to see if drift keeps falling toward equilibrium.
- Rule recorded as `motion_style.settled_keyframe_prompt` (for generated keyframes); for seed images the equivalent is
  "settle" = keyframe from a late frame of a take.
- **Neon 17.7 s loop from the settled-keyframe s306 take (6.7 grey, gate raised to 7): very slight in review** — same
  verdict as the waterfall at 6.7. The drift metric predicts the perceived seam across scenes: 1.7 nothing,
  6.7 very slight (x2), 13.7 a shift, 35 a clearly visible build-up.
- **Automatic neon run with the new defaults** (`runs/neon_loop`, settle always, gate 4, best effort): settle take =
  the cached seed-306 take of the original keyframe; takes from its last frame drifted 4.73 (s306) / **3.93 (s307,
  accepted)** — s307 drifted 34.4 from the original keyframe. Both 30 s extensions drifted 7.3-7.5 → take-only
  17.7 s loop with a warning. 55 min. **Reviewer: very hard to see even when looking for it; the settled look is good.**
- **Automatic waterfall run**: settled takes 6.88 / ? / 13.58 → best effort s306 (6.88, warned "very slight seam
  expected"); extensions 13.1 / ? → 17.7 s take-only loop. 66 min. **Reviewer: very slight — the warning predicted it.**

## 16. take_qc v2: trend instead of range, plus a pulse cap (2026-09-26, requested: allow glow and pulsing light)
The cell gate measured the per-second luma *range*, so a light that breathes (fireplace glow, furnace throb) counted
the same as a light that creeps. Recomputed on all 40 take videos in `runs/` (worst cell each; trend = rise of a
fitted line over the take, pulse = detrended peak-to-peak):

| take | user verdict | range | trend | pulse |
|---|---|---|---|---|
| rain_loop_e2e | nothing noticed | 1.67 | 1.68 | 1.05 |
| dir_neon s306 | really hard to tell | 1.13 | 0.87 | 0.91 |
| dir_furnace s306 | very slight jump | 2.23 | 1.57 | 2.13 |
| dir_pine7 | noticeable, passing shadow | 10.71 | 10.52 | 4.94 |
| dir_cabin (fireplace) | — | 6.99 | **0.93** | 7.00 |
| dir_pine4 (sun flare fades in/out) | — | 60.02 | 4.29 | **58.85** |
| dir_furnace_bright s306 | — | 4.56 | 3.60 | 2.46 |

- Trend ≈ range on every judged take, so the 4 (pass) / 7.5 (best effort) calibration transfers unchanged.
- The cabin fireplace was rejected for breathing 7 grey with no trend: the case the user wants allowed. Trend passes it.
- A trend gate alone would pass pine4's one-off sun flare (trend 4.3, pulse 59), so a pulse cap of 12 grey was added.
  Hypothesis, not calibrated: fireplace 7, dappled pine 8-10, flares 15-59. Tune when a verdict lands on either side.
- Sub-second flicker (candle, embers, glints) is averaged out per second and never counted.
- The bright furnace take s306 (Kontext edit) is a true creep (sun cell +3.8 of its 4.6 range, monotonic; the light
  shaft fades -3.9): the same seed on the unedited still trended 1.6. Brilliance in the still costs stationarity.
