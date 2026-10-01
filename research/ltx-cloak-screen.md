# LTX cloak motion: first screen of the 2026-09-29 research report

**Question:** can LTX-2.5 reshape the traveler's cloak (spice desert still) the way Hunyuan 1.5 does, without masks?
Report: `docs/handoffs/2026-09-29-ltx-cloak-motion-research-report.md` (§9 first screen, §10 gates). Brief:
`docs/handoffs/2026-09-29-ltx-cloak-motion-research-brief.md`. Plan + ledger: `docs/superpowers/plans/2026-09-29-ltx-cloak-screen.md`.

**Answer (probe + one full loop, user verdict pending): yes, with a moving depth guide and a single-stage pass.** The
held-still depth guide replaced by a Hunyuan render of the same still (converted to depth by WanGP), generated in one
full-size pass, makes LTX's cloak billow along Hunyuan's trajectory as solid fabric. Every one-parameter change on
its own (source strength, single stage) and the moving guide in the default two-stage pass fall short. A full 27 s
loop whose take AND return are guided (a Hunyuan continuation for the return) passes loop_qc with the cloak moving
throughout (below); a return with the held still freezes it.

## Setup

`experiments/models/bakeoff.py spice_desert_cloth` (launch: `runs/logs/cloak_screen.ps1`, `cloak_arm4.ps1`): distilled
8 steps, 1280x704, 121 f, 24 fps, seed 306, cloth-first prompt, held-still depth guide (DVG 1.0) unless stated; each
arm changes ONE setting against the recorded baseline (dry run: settings differ only by the delta). Measure:
`experiments/models/cloak.py` (dark silhouette in the lower-left box; area min / max / excursion in points; 1 - IoU 4
frames apart; camera = take_qc's ORB transform). Donor: `runs/models/spice_desert_calm/hy15_720_s306/clip.mp4`
(Hunyuan 1.5 720p, 50 steps, calm-cloak prompt, H100). Arm 0 checks: baseline resolved `input_video_strength` 1.0,
2 phases, fps 24; donor frame 0 vs the still at 1280x704 = 0.06 px / 0.002 % zoom (WanGP resizes guide and still
identically), donor camera 0.09 px, feet planted.

| arm (one change) | change | area min-max | excursion | camera | eye |
|---|---|---|---|---|---|
| baseline (distilled, held still) | 0.176 | 5.4-8.7 % | 3.3 pts | 0.19 px | one silhouette, edge shimmer |
| `input_video_strength` 0.7 | 0.113 | 6.8-10.9 % | 4.1 pts | 0.04 px | ~ baseline |
| single stage (`guidance_phases` 1) | 0.223 | 2.8-7.8 % | 5.0 pts | 0.04 px | haze thickens over the traveler; no flare |
| moving depth guide (donor), two-stage | 0.167 | 6.8-11.6 % | 4.8 pts | 0.15 px | shape follows the donor; new area tattered, translucent, glowing patches |
| **single stage + moving guide** | 0.234 | 3.3-15.3 % | **12.0 pts** | 0.11 px | **solid fabric billowing along the donor's path, 5 s wide flare**; denser haze |
| dev 40 steps CFG 5 (earlier) | 0.123 | 6.4-12.1 % | 5.7 pts | 0.13 px | flares a little |
| Hunyuan calm (the donor) | 0.064 | 8.0-17.7 % | 9.6 pts | 0.23 px | reference |

Minutes / RAM peak (laptop): 6.7 / 61.1 GiB, 6.1 / 62.7, 6.4, 7.2 / 56.6 GiB. Review: `runs/models/spice_desert_cloth/
review_cloak_screen.mp4` (traveler crops, 3x loop), `screen_sheet.jpg` (guides + crops over 5 s), `arm4_zoom.jpg`.

Reading the numbers: with single stage the dust haze over the traveler thickens, so the dark-pixel silhouette thins
(low minimum) and its edge flickers (high change): for these arms the metric's minimum and change measure haze, the
maximum and the crops measure the cloak.

## Findings

- **What pins the cloak is information, not strength:** softer source conditioning (0.7) and a weaker held guide
  (earlier: 0.5 / 0.25) change little; a guide that MOVES changes the silhouette at once. WanGP's DA-V2 depth of the
  donor carries the hem clearly, including the flare (`guide_processed.mp4` in each arm dir, `--save-masks`).
- **Two-stage under-resolves it** (report §2/§5 confirmed with real tensors, `model.tokens` events): the union
  control is injected in BOTH stages -- 5x10 latent cells in stage 1 (the traveler ~1.3 cells tall) and 11x20 in stage
  2; the two-stage output follows the guide's outline with a smoky, see-through fill. Single stage (control 11x20 from
  the first step) renders the swept area as cloth.
- No frozen-frame bug: the start image is clean context for exactly one latent frame at strength 1.0 (880 tokens at
  full size) and none at 0.7.
- Loop consequence (report §5): a 5 s donor covers 5 s. A take needs a donor as long as the take (next: a 20 s
  Hunyuan take as the guide, `looper loop --take-guide`, experimental); the return keeps the held-still guide.

## Full loop, 2026-09-29/30 (report §10 gate) -- the take works, the return does not (yet)

**Donor:** Hunyuan 1.5 **480p step-distilled** (`bakeoff.py` arm `hy15_480_sd`, local: 9.7 min / 5 s, 35.7 min / 20 s,
RAM 35 GiB), stand-still prompt (probe: 5.1 pts vs 4.0 for the calm prompt; the 720p 50-step whip was 15.6), 481 f =
four 121 f windows chained by WanGP with ONE overlapping frame (`runs/models/spice_desert_hy480_20s/`).

**Guided take** (`looper loop --take-guide <donor> --single-stage`, 832x480 -> 832x448, `runs/spice_guided`; the guide is
fitted to the keyframe's exact framing: 0.04 px): 13.7-15 min per take; take_qc 6.21 / 4.05 / 5.86 grey (seeds
306-308; strict gate 4.0) -> best effort seed 307. **Its cloak follows the donor for the whole 20 s as solid cloth:**
excursion 10.2 pts (the accepted spice_desert LTX take: 3.1), every 5 s window flares (9.7-14.1 / 10.7-14.0 /
11.3-14.0 %); LTX's own look kept (golden haze, particles); camera 0.42 px. The donor's slow darkening does NOT
transfer (calmest stretch drift 3.47 grey vs the donor's 18.9), nor do its window-join pops (LTX steps there
1.33 / 1.28 / 1.01x vs 1.6x elsewhere).

**Return (held-still guide, the pipeline's long return, 368 f):** all three seeds fail loop_qc on the traveler cell
only -- `c20.low` + `c20.low_texture` -- while every seam gate passes (closing 1.04x, churn worst 1.11-1.13, loop
drift 3.8-4.6 grey). The cloak nearly freezes in a mid-flare pose for the return's first ~5 s (0.3-0.6 pts per
2.5 s vs 2.5-4.5 in the body), then settles slowly back to the start pose: 15 s of billowing, 15 s of a still cloak.
The run ends `unresolved` with the least-bad closure's review (`runs/spice_guided/stages/review/4e150465640a60f4/`).
This is report Path B, now measured: a moving guide must cover the return too.

**Path B, first attempt -- works (loop level, probe of one seed):** `experiments/models/guided_return.py`: a 20 s
Hunyuan continuation of the donor from the loop's last body frame (408; the frame saved at the still's own size so
Hunyuan renders 848x480 like the take), cut at G where its cloak silhouette best matches the loop's first frames;
return guide = donor[360:409] + continuation[1:G+1] + donor[57:121], fitted like the take guide; the pipeline's
close / splice / loop_qc / deliver / review on the same take with native latents (keys `[guided_return]`).
Result (`runs/spice_guided`, G 296 -> 27.0 s loop): **loop_qc accepts with no flags** -- closing 1.09x, gap
activity 1.07, churn worst 1.16, drift 4.2 grey, camera 0.66 px, every region keeps >= 0.97x the take's motion --
and **the cloak billows through the return** (2.0-3.3 pts per 2.5 s; held-still return 0.3-0.6), LTX look kept
(the continuation had drifted to Hunyuan's harsh late look; depth carries none of it). Weak point: the wrap -- the
continuation never returned to the loop-start pose (cloak IoU 0.53), so the return retracts the hem within the last
few frames (wrap step 1.65x vs the loop's worst 1.54x; review gate 1.8x). Review
`runs/spice_guided/stages/review/07a2ba6bba1ecb71/`; sheets `runs/spice_guided/guided_return/`. 4K rendered.

**What this is and is not:** a generic mechanism (any still; another model renders the motion, LTX renders the
pixels and the closure from its own latents) but not yet a pipeline route: it costs two donor renders (36 min each
at 480p locally), the loop length follows the wrap match (27 s here), and the wrap match is the weak point. Next
levers: longer continuations (more candidate cut points), matching on depth rather than dark pixels, several
continuation seeds; then a `--return-guide` stage + ADR if the user likes the look.

## Hunyuan end to end (requested: the whole scene in Hunyuan, through the 4K upscale)

`crossclose.py --size 832x448 --seconds 30 --finish --4k` on the Hunyuan donor take (`runs/models/hy480_loop`): the
pipeline's long-return layout on re-encoded contexts (no true latents for another model's take): Hunyuan frames
129-481 (14.7 s) + a 368-frame LTX return. The closure itself is clean (1.02x of the loop's own worst step), but
loop_qc rejects and review doubts: **slow drift 30.1 grey** (the donor's megastructure darkens 42 -> 25 grey over the
Hunyuan stretch; the return brightens it back to 46), texture churn 2.42 in the worst region (gate 1.5), and the
loop's worst step (2.04x at 9.7 s) is a Hunyuan window join (the take's joins: 2.45 / 2.73 / 3.11x the median).
Coherent to the eye (traveler holds, the return looks like the Hunyuan part); 4K rendered on request.
**Reading:** Hunyuan's cloak comes with Hunyuan's drift and window pops; used as a depth guide for LTX, only the
cloak's geometry transfers -- the guided LTX take is the better loop material.

## Review verdicts (2026-09-30)

- **Guided take + guided return, 27 s** (`runs/spice_guided`, review `07a2ba6bba1ecb71`): joins perfect; the cloak
  moves a little too fast; otherwise the scene is approved. -> the method passes the eye; the
  donor's cloak speed is the one complaint. Next (paused by the user): the donor guide at 0.75x speed
  (motion-interpolated, `runs/models/guides/hy480_take_slow075.mp4`), same recipe, 4K after approval.
- **Hunyuan end to end** (`runs/models/hy480_loop`): very poor quality, far below the earlier bake-off clips, a
  dated early-2000s CGI look. -- the run used Hunyuan 1.5 480p step-distilled
  (8 steps, no CFG, int8, local) instead of the 720p / 50-step H100 model judged in the bake-off; its look also drifts
  harsher over the take. As a motion donor it is fine (only depth transfers); as the picture it is not.

## Hands-off route (ADR 0016, 2026-09-30): the wrap match on real data

Replayed on the spice donor (take guide + the frame-408 continuation, fitted, gaps 296-368): a plain whole-frame
correlation of tone-normalised grey scores every gap 0.921-0.930 (the static megastructure decides; it picked 328);
the same distance weighted by the take's own per-pixel activity spreads 0.540-0.574 and picks **296 -- the cut the
cloak box picked and the user passed** (joins rated perfect in review), with no scene region. The pipeline uses the
weighted version (`donor.wrap_match`, return_guide v2). The cloak IoU itself was flat (0.48-0.53) for every gap:
the continuation never returns to the start pose, and the eye tolerated the hem's catch-up at the wrap.
`tests/test_donor_route.py` runs the whole route on the CPU with fake renders; it found that a 0.6x retime of a
donor of exactly the needed length lost 2 frames (479 of 481), which would have failed every slowed take
(fixed: `donor.SLOW_MARGIN`).

## 0.6x donor speed (user verdict 2026-09-30)

In review the 1.0x guided cloak was a little too fast; 0.6x was picked from a retimed preview. The 0.6x guide
(donor motion-interpolated, guide frame k = donor frame 0.6k) + a continuation from donor frame round((e-1)*0.6)
gave `runs/spice_guided_060`: loop_qc accept (closing 0.92, churn 1.09, drift 6.6), cloak shape change 0.104 vs 0.133
at 1.0x (body and return alike: no freeze), wrap cloak IoU 0.75 (1.0x: 0.53). **Reviewer: speed and hood acceptable.**
Known limitation, seen here: the depth guide transfers the donor's shape ERRORS too -- the continuation's hood grew a
bump and LTX drew a brim on it for ~5 s of the return. Remedy if it matters: another continuation seed.

## First hands-off run on a new scene: sample_1 (2026-09-30, `runs/sample1_donor`)

`looper loop --image sample_1.png --prompt-file <user's prompt> --motion-donor --donor-speed 0.6` (the user's still
and prompt, no hand steps). Director v20 kept "the cloak billows and rolls"; the contract added the light shafts
(the user asked for "subtle shifting shafts of light"), which switched on the exposure-only light clause.

**The route works on a second scene:** the cloak billows through the body AND the return (no freeze), the traveler
holds position, every closure is seam-clean (closing 0.98 / 0.98 / 0.94, joins 1.3-1.35x vs the loop's worst 1.52x),
camera 0.17 px, moving regions keep 0.96-1.01x the take's motion, the wrap lands on a matching cloak pose.

**Two defects, neither from the donor route's machinery:**

1. **A stick at the traveler's side** (Review 4: the stick is a defect): from ~10 s a thin rod with a small
   crossguard hangs to the ground, in all three take seeds. Not the donor: median-smoothing the guide's depth maps
   (feet and thin lines removed, verified through WanGP's own Depth Anything v2) left it in place and the cloak
   motion unchanged (traveler-box motion 3.37 vs 3.40); a prompt sentence ("the cloak hides the legs; the traveler
   carries nothing: no staff, no sword, no pole") changed nothing either (frames within ~2.7 grey). The still itself
   has a rod-like line at the traveler's hip (a sheathed sword or staff under the cloak); once the donor makes the
   cloak lift, LTX shows it. The user is editing the still. Both fixes were removed again (no effect = no code).
2. **The light drifts in the take** (seed 306 +7 grey brighter, 307 +3, 308 -32, as if the sun sets); the
   return then has to swing it back, so every closure fails loop_qc `static.luma_dev` (loop drift 12.9-15.5 grey).
   The full steady-light clause instead of the exposure-only one softened seed 308 (101 -> 81 instead of -> 68) but
   did not fix it. The take's own depth stays flat (<= 2 levels) while its light changes: a lighting ramp, not
   geometry. Seed 308 darkens where the donor darkens (the donor loses up to 25 grey); a no-guide control of the
   same seed decides whether the moving guide drives it.

### The new still (sample_1b) and the slower scene (2026-09-30)

The user replaced the still (new render: arch megastructure, two suns, smaller traveler, no hip rod). Hands-off run
`runs/sample1b_donor`: takes 10.75 / 7.55 / 27.88 grey (seed 307 missed the 7.5 best-effort limit by 0.05 ->
`--fallback-drift-max 8`, the strict gate untouched); the cloak flares, the traveler holds, **real legs instead of a
stick** when the cloak lifts. Loop: loop_qc PASS, no flags (closing 0.98, churn worst 1.21, slow drift 9.25, static
light deviation peak 1.1 < 1.5), joins 1.23x / 1.23x vs the loop's own worst 1.26x. **Reviewer: joins and scene
excellent; the whole scene should be slowed down considerably.**

- **RIFE retime of the finished loop (circular, `experiments/models/loop_retime.py`): rejected.** At 0.6x / 0.75x the
  steps pulse (1.1 / 0.4 / 1.2 / 0.3 / 1.1 of the median at 0.6x, even on blurred large-scale motion): on sand and
  sparkles RIFE snaps to the nearest real frame. 0.5x has an even cadence, but in review the cloak and
  surroundings showed odd distortion and patterns, very low quality. Interpolation is out for this content.
- **Native slow motion (121 f probes, seed 307):** the donor speed controls the cloak (0.3x: traveler flow 0.56x of
  0.6x); LTX's motion clock (0.5 / 0.3) barely changes LTX's own sand and dust in a guided single-stage take (flow
  0.92-1.10x). The reviewer picked cloak 0.3x, LTX 1.0 from the 2x2 comparison.
- **Dot pattern in the 4K (reviewer: the blowing sand began to form geometric patterns):** the still's lower cloak
  carried a glittery ornamental pattern (golden swirls, sparkle specks). LTX keeps such fine still texture as a
  speckle at 832x448 (more noticeable when the cloak moves slowly); the FlashVSR x4 upscale sharpens the speckle into
  a regular dot grid. The upscale cannot remove what the take carries: fine glitter / embroidery in a still is a
  4K risk. The user is replacing the still (plain cloak).

### Light drift on guided takes: the donor's tone is not the cause (2026-10-01)

Guided takes ramp their light per seed (sample_1 seeds 306 / 308: 10.2 / 49.5 grey; sample_1b at 0.3x: 9.9 / 15.8)
and the no-guide control of sample_1 seed 308 drifted 24 -- so the moving guide amplifies LTX's own drift. Hypothesis
tested: the Hunyuan donor darkens over its clip (up to 25 grey) and its depth maps shift with it. Holding every guide
frame's tone to frame 0 (Reinhard LAB, `experiments/models/tone_norm_guide.py`; guide luma 100.6 -> 86.4 became
100.7 -> 100.3) and re-rendering the same seeds with only the guide changed (`retake.py --guide`):

| take | original guide | tone-held guide |
|---|---|---|
| sample_1 seed 308 (moving-light floor metric) | 49.45 | 48.21 |
| sample_1 seed 306 (floor) | 10.21 | 10.04 |
| sample_1b 0.3x seed 308 (plain) | 15.78 | 18.36 |
| sample_1b 0.3x seed 306 (plain) | 9.93 | 10.10 |

**No effect: refuted** (the script was deleted after the test; it is in git history). The guide's structure /
motion, not its tone, is what amplifies the drift.

**Depth-anchor strength (sample_1 seed 308, same moving guide):** `guide_strength` 1.0 -> 49.45 grey floor drift,
0.8 -> 65.91 (luma 99 -> 59), 0.6 -> 69.24 (luma 96 -> 52, camera 1.01 px); the still's own depth held at 1.0 (the
no-guide control) -> 24. Monotonic: the looser the depth anchor, the further the picture slides. A moving guide is
a looser anchor than the held still, and weakening it is the wrong direction. Open: a stronger anchor that still
lets the cloth move (a hybrid of the held still and the donor's motion would be a region mask: ruled out).

### Spice hands-off take drift: the donor's traveler stepped (2026-10-01)

`spice_handsoff` (the user's original brief + still, director v24, donor 0.6x) failed: no take under the 8.0
best-effort limit (seeds 306 / 307 / 308: 9.69 / 10.23 / 14.36). Not light: the midground spice band thickens and
darkens over the take (c10 / c20 / c21 -10..-14 grey on seed 308). The delivered `spice_guided_060` passed (4.37 /
5.98 / 6.12) with a pixel-identical fitted still (0.2 px, 0.6 grey) but a hand-written prompt and a hand-picked donor.
Seed 308, one variable at a time (`experiments/models/retake.py`, plain region drift = the run's gate):

| take prompt | donor (moving guide) | drift |
|---|---|---|
| director v24 | spice_handsoff's (traveler steps 12.4 px) | 14.36 |
| v24 + "already fully developed ... never thickens or builds up" | same | 12.69 (s306: 9.69 -> 9.21) |
| v24 without "Dense clouds of" | same | 12.99 (s306: 9.69 -> 7.28) |
| the hand-written prompt | same | 9.82 |
| v24 + the donor's hold-position sentence (`motion_style.HOLD_POSITION`) | same | 12.14 |
| director v24 | spice_guided_060's (holds, 1.3 px) | **7.27** |
| the hand-written prompt | spice_guided_060's | 6.12 |

**The donor is the main cause; the wording a minor one** (every one-sentence change: -1.4..-2.2 grey; no prompt change adopted). The failed run's donor fails today's subject-hold check
(net 12.4 px, limit 8.3; the v23 donor before it 114.7 px), so the pipeline now re-rolls it before any take is spent
(`donor_hold`, committed the same day). Hold check on the other scenes' donors: sample_1b's four all hold
(0.2-1.4 px) while its takes still ramped 9.9 / 15.8 -- that light ramp is a different effect (above, unexplained);
sample_1's figure is not detected (1 frame of 25: the check passes it untested).

**End to end (the same run resumed, 2026-10-01):** `donor_hold` rejected the cached donor (12.4 px) and
re-rolled seed 307 (0.3 px); takes 7.19 / 9.20 / 6.87 (old donor 9.69 / 10.23 / 14.36), best effort seed 308; the
return donor held at 6.8 px (limit 8.3); closure 306 passed loop_qc first try (closing 1.047, no flags). Review DOUBT:
slow loop drift 10.99 (bottom-left), and the traveler sways +12 px at 20-21.7 s inside the return, back by the wrap
(torso x 126.6 -> 139.2 -> 128.6). Review 11 approved the 4K. 4K (`runs/spice_handsoff/stages/deliver4k/e88c8982290f76d3/`: loop_4k 29.3 s, final_4k
61 min; delivery wrap step 1.31, chunk joins 0.82-0.97 vs natural 2.29; no dot grid at 1:1): accepted as final.
**The user's original spice brief + still, hands-off, delivered in 4K.**

### sample_2: two hands-off runs, two good loops (2026-09-30 / 10-01)

The user's still + prompt (`runs/inputs/sample_2.png`, `sample_2_prompt.txt`), `--motion-donor --donor-speed 0.3`:
run 1 (donor seed 307 after seed 306's figure stepped) and the unaided reliability run `sample2_rel311` (seeds 311+)
both passed the strict take gate on their first take seed (3.84 / 1.28 grey), kept the figure planted (head x within
1-2 px) and closed seam-clean on every closure seed (closing 0.94-1.03). Every closure tripped loop_qc `c20.low`
(bottom-left: the robe flares less in the return than in the take) -- reviewer on run 1: the lull is not
visible; on run 2: as good as the first. Run 1 went to 4K and was accepted as final. The spice 0.6x 4K too.

### loop_qc v10: a lull is not a freeze (2026-10-01)

Every flagged `low` measured (`experiments/gate_replay/loop_qc_replay.py`, 0.25 s rolling R): the user's verdicts
separate by content, not by any single threshold -- the harvester drum stall the user saw (rated rough) scored
0.49 for 0.04-0.08 s, the lulls the user passed 0.39-0.49 for 0.17-2.08 s (sample_2 x2, sample_1b), the
held-still return's frozen cloak 0.17-0.24 for 8-14 s. Rule: scenes with rotating machinery (contract's
machine_rotation words) keep the strict gate; elsewhere a low fails only when deep (< 0.3) or long (> 4 s).
Replay: sample2_donor 2/2, sample2_rel311 3/3, sample1b_donor 3/3 now pass (lulls reported in the review);
spice_guided 3/3 and harvester 3/3 still fail; harvester_1s unchanged.
