# Harvester drum: resolution vs model (2026-09-27)

**Question:** in review the crawler's front drums streaked, smeared and faded forward instead of rotating. Resolution or
model? Same settled keyframe, same motion prompt + negative, seed 306, 5 s, `experiments/models/bakeoff.py
harvester_drum` (clips `runs/models/harvester_drum/`, comparison `drum_sbs.mp4`).

| arm | min | RAM peak GiB | camera px / zoom % | drift grey | drum flow px/f | change explained by motion |
|---|---|---|---|---|---|---|
| LTX 832x480 (pipeline default) | 4.1 | 53.1 | 0.38 / 0.05 | 2.64 | 0.11 | **3 %** |
| LTX 1280x704 | 4.9 | 57.5 | 0.38 / 0.00 | 0.87 | 0.28 | **35 %** |
| Wan 2.2 Lightning 864x464 (no depth lock) | 7.0 | 57.5 | 42 / 8.9 | 9.79 | — | — (push-in, invented meteor streaks) |

"Explained" = 1 - (drum-crop residual after Farneback-warping frame t onto t+1) / (raw frame difference), frames
16-120, crop left 40 % x rows 16-58 %. Near 0 = the drum's appearance changes without moving (re-synthesis: the
smear); rigid rotation would be near 100 %.

## Round 2 (2026-09-27): the drum QC and the two-stage cause

**QC tool** `experiments/drum/drumqc.py CLIP...` (832-wide units, box = the front drums x 3-36 %, rows 36-62 %):
motion-explained fraction, flow, 24-frame forward-backward track survival, per-48-frame windows, and y-t kymographs
(rotation = diagonal stripes, stall = flat bands) + a crop strip. Kymographs are the fastest eye check.

| clip | explained | flow px/f | track_ok | kymograph |
|---|---|---|---|---|
| delivered 480 loop (reviewer: streaks, smears, fades) | 0.26 | 0.47 | 0.80 | fine diagonals, teeth pass |
| 480 take (481 f) | 0.23 | 0.42 | 0.79 | same |
| **720 take (481 f, harvester_720)** | **0.01** | **0.03** | 0.09 | **flat: drum frozen for 20 s** |
| probe 480 two-stage (121 f) | 0.08 | 0.11 | 0.28 | nearly flat |
| probe 720 two-stage | 0.35 | 0.38 | 0.85 | diagonals |
| probe 480 **single stage** | 0.27 | 0.46 | 0.80 | teeth move as coherent blocks |
| probe 720 single stage | 0.21 | 0.14 | 0.76 | slow smooth diagonals |
| Wan 2.2 Lightning | 0.50 | 2.6 | 0.26 | (camera pushes in: out) |

Findings:
1. **WanGP's distilled LTX is two-stage**: stage 1 at HALF size (416x224 for "832x480"), spatial upsampler, 3-step
   refine at full size. Motion is decided in stage 1: the 480 drum was a ~13x7-token object. `guidance_phases: 1`
   skips stage 2 and decides motion at full size, at ~the same cost (121 f: 4.5 vs 4.1 min at 480; 7.4 min at 720).
   -> `--single-stage` (loop CLI), off by default until a full loop is judged.
2. **5 s probes do not predict a 20 s take**: 720 two-stage turned the drum in 121 f but froze it for all 481 f of
   harvester_720's take (same seed; confound: harvester_720's directed prompt adds "no movement ... in Colossal
   crawler chassis"). Judge the drum on take-length windows.
3. The metric's "smear" band is not yet calibrated against a rigid reference: the user-rejected loop turns (0.47 px/f)
   with 26 % of its change explained. Every LTX arm keeps concentric ripple artefacts on the drum's end face.

4. **Full 480 single-stage loop (`harvester_1s`, same keyframe/prompt/seed as the rejected loop):** take seed 306 drum
   0.33 / 0.68 (take_qc rejected: ground dust thickening, 5.49 grey), seed 307 0.27 / 0.46 (accepted); delivered loop
   (best effort: static.luma_dev = a slow 91->106->98 grey dust swell in the long return; joins clean) **0.27 / 0.46
   = the rejected loop's 0.26 / 0.47**. At 480 single-stage does not reliably turn the drum more over a full take.
5. **Detail, not motion, is the likely smear** (Laplacian variance of the drum box at 832 wide): user still 853, 720
   keyframe 748, 720 take 474, 480 keyframe 430, every 480 render 290-320. At 480 the video keeps ~1/3 of the
   drum's detail; teeth a few px wide cannot move rigidly, they streak. Next: 720 single-stage loop (`harvester_720_1s`).

6. **Cost of 720 single stage over a whole take:** 481 f at 1280x704 in one pass runs at the 6 GB VRAM ceiling
   (5.9 GB, 100 % util at 36 W = memory-bound): 652 s/step, then 1185 s/step (vs 121 f: 7.4 min total). ~2.5 h per
   take locally; 720 single-stage is an offsite (rented GPU) recipe, not a local one.
7. **720 single-stage take (`harvester_720_1s`, 481 f, 3.3 h): the drum nearly stops** (explained 0.07, flow 0.10;
   5 s probe had 0.21 / 0.14). Detail kept vs the 720 still: mean 0.48 (720 two-stage take 0.67, 480 0.40). Both
   720 long takes froze the drum -> at 720 the model keeps a large toothed object still over 20 s whatever the stage
   setup (one seed each; hypothesis). Run killed after the take (no loop).

8. **Upscalers on 5 s of the 480 single-stage loop** (`experiments/drum/upscale_probe.py`, frames 100-220):
   motion kept by both (explained 0.29 -> 0.37 LTX / 0.38 FlashVSR, flow unchanged, track_ok unchanged: no flicker).
   **LTX-2.5 Pixel Spatial Upscaler x2** (WanGP `ltx25*2`, 10.7 min / 5 s): sharper but RE-INVENTS geometry (a new
   spoked wheel on the drum hub) -> out for a loop (each window would invent differently). **FlashVSR x4** (the
   existing `--4k` stage, 23.8 min / 5 s): sharper and faithful; plates, rust and track links readable.
   Sent `runs/drum/drum_A_480_B_4k.mp4`. `experiments/drum/fourk.py` renders the 4K of the harvester loop the user
   liked as its own run (`harvester_4k`), outside the acceptance gate.

9. **`harvester_4k` (FlashVSR 4K of the user-passed loop, 5 chunks x 31 min = 2.6 h):** joins 0.90-1.05x, wrap
   1.2-1.32x, accept. Drum over the whole loop: explained 0.36 vs 0.26 at 480 (same loop), flow 0.52 vs 0.47, every
   48-frame window 0.30-0.38. At native 4K pixels (4.6x of the 832 source) the plates look painterly; at a ~2x crop
   they read well. Sent `runs/drum/harvester_4k_drum.mp4`.

10. **Review verdict on the 4K (2026-09-28): still squashed and smeared; the teeth drag instead of turning
    cleanly.** -> the 4K finish sharpens but cannot fix re-synthesis: the motion itself must change -> model.
11. **Wan 2.2 Fun VACE A14B + the still's depth as camera lock** (`experiments/drum/vace_probe.py`, 81 f @ 16 fps,
    4-step Lightning, 7.5 min): seed 306 explained 0.46 / flow 1.07 / camera 0.04 px, crops show a rigid geared drum
    turning; seed 307 frozen (0.01 / 0.03). BUT depth-only VACE REPAINTS the scene: by frame 40 colours, smoke, suns
    and machine design all differ from the still (frame 0). Next: + the still as a VACE landscape reference (`--ref`).

12. **VACE + `--ref` (the still as landscape reference, "VAKI"):** appearance kept exactly, but the drum froze on both
    seeds (explained 0.01-0.02). **+ the concrete rotation wording** (runs/inputs/harvester_motion_rot.txt): seeds
    306 / 307 / 308 = 0.11 / 0.20 / **0.39** explained, flow 0.10 / 0.23 / **0.99**; seed 308 keeps the scene, camera
    0.1 px, kymograph = clean regular diagonals (teeth moving as blocks), crisp teeth in crops. First candidate with
    both a locked scene and a rigid turning drum (1 of 3 seeds). Sent `runs/drum/drum_A_ltx_B_wan.mp4`; verdict pending.
    Open if adopted: Wan runs at 16 fps (RIFE to 24), no LTX latent closure machinery (VACE closures were proven in
    September: ADR 0006 era), seed yield, 81 f windows (a 20 s take = sliding windows).

13. **Reviewer on B (Wan VACE s308): would work well if only the drum animated, not the components around it; the
    components are janky.** Jank measure = raw frame change in the box right of the drum (x 36-60 %, rows
    36-62 %): LTX 0.63, VACE refrot s308 1.57 (flow 0.05: the parts shimmer / redraw, they do not move).
    - Wording "only the drums turn; housings, hubs, pistons, pipes ... stay perfectly rigid": surroundings 1.36 / 1.61 /
      1.49 (no better); drum 0.16 / 0.40 / 1.21 flow. Wording does not steady the surroundings.
    - User rule (2026-09-28): a mask only if the pipeline makes it automatically and it generalises to other scenes.
      Candidate: SAM 3.1 text grounding of the director's FIXED phrases minus its MOVING subjects -> VACE holds those
      pixels (`experiments/drum/sam_mask.py`, `vace_probe.py --lock`; only without a declared moving light).
      **Failed at the mask:** on this still single phrases ("drum", "excavation drum", "machine", "hull", "mountains",
      "ladder") all return 0 % (only "sun" 3 %, "rocks" 2 %); the long fixed-phrase list returned 58 % = the whole
      machine incl. the drum + the whole ground. WanGP hard-codes SAM3 thresholds (detection 0.5, new object 0.7).
      Parked (would need vendor patching; not reliable enough to be generic).
    - **Motion-evidence lock (generic, no words):** from the run's own LTX take, per-pixel mean frame change
      (blur 1.5, every 4th frame after 48), smoothed; pixels below the 55th percentile, minus a 21 px dilation of
      the active ones, opened 9 px = hold as the still (35 % of the frame: machine body, calm sky). The activity map
      lights up exactly the two drums (runs/drum/lock_harvester/overlay_motion.jpg). VACE + ref + rotation wording +
      this lock (`vace_mlock_s306..308`; a first run had a 1-channel mask bug, rerun): drum 0.04 / 0.02 / **0.42
      explained**, flow 0.05 / 0.04 / **0.95**; s308 held areas change 0.62/frame (LTX 0.63) vs free 1.49; held pixels
      sit ~6 grey from the still (tone), steady. Scene kept. Sent `runs/drum/drum_A_ltx_B_wan_C_lock.mp4`.
      Yield so far 1/3 seeds turn the drum (every VACE arm: 306/307 weak, 308 strong).

**Decision (2026-09-28):** drop masking and the Wan route; the director should edit against parts that rotate like
this, which LTX struggles with. Review of the 3-way: C good; A acceptable if more dust obscured the view. -> director v19: a rotating part keeps turning slowly and is veiled by the dust / steam it
churns up (recorded as an adaptation); contract v4 framing matches. Test: `harvester_dust` (the passed loop's
keyframe + seed; drum clause = dense churned dust, same density throughout).

**Earlier conclusion (superseded by the review verdict above):** the drum smear is missing detail at 480, not missing
rotation; local 720 freezes the drum over a full take (2 of 2); the practical fix is the 480 loop + the 4K finish.

**Conclusion round 1 (one seed, metrics + stills; user verdict pending):** at 832x480 the drum essentially does not rotate,
it re-synthesises in place. 1280x704 turns it 2.5x more and a third of its change is coherent motion, with lower drift
and a steadier frame, at +20 % time for 121 f. Still not rigid. Wan 2.2 Lightning is out for this scene (no camera
lock). Cost caveat: a 481 f 720p take is 42.5 min at 63.2/64 GiB RAM (crawler_720); 720p long returns are unmeasured.
