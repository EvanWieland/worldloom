# QUALITY — what "good" means

Objective checks are automated and block gates. Subjective criteria are scored by a human (optionally pre-screened by a vision model — feasibility is research task R7). **All numeric thresholds below are initial guesses to be calibrated on synthetic good/bad clips (R7); update them here with evidence.**

## Objective validation (automated)

| Check | Method (initial) | Fail when (uncalibrated) |
|---|---|---|
| Loop seam | frame diff (last→first) vs distribution of adjacent-frame diffs (MSE/SSIM + optical-flow magnitude) | seam diff > 1.5× median adjacent diff, **evaluated per tile (max over tiles)** — a global mean missed a small-area seam jump in testing (`research/long-form-assembly.md`) |
| Motion continuity at seam | optical flow field last→first vs neighbors (direction/velocity jump) | flow discontinuity beyond neighbor variance |
| **Motion level + direction across the whole loop, per region** (2026-09-23: the whole-frame version passed a bridge whose sky swept back at 6–10× while the foreground stayed calm) | per 8-frame block: sky-ROI |flow| ÷ chain median, and sign of sky horizontal flow; bridges included | any block outside 0.8–1.25×, or sky direction sign flips anywhere in the loop |
| Luminance jumps | per-frame mean luma and per-region luma deltas | delta > k·MAD of the clip's deltas |
| Temporal flicker / shimmer | high-frequency temporal energy in low-motion regions (from the plan's 'must stay still' list or measured optical flow). **Key risk of the video route.** | above threshold |
| **Unintended camera motion (primary per-clip gate)** — phase-correlation shift, frame 0 vs last frame; `experiments/clip_gate.py` | measured on 6 seeds of B1 @848×480: locked 0.10–0.11 px (seeds 42, 104), drifted 4.66–8.28 px (seeds 7, 101–103) — clean separation | **> 1.5 px** (calibrated on n=6, one scene/resolution only — recalibrate before trusting elsewhere) |
| Structural fidelity of a clip to its keyframe (edge-map mismatch on the subject region; `experiments/hub_pingpong.py`) | secondary/diagnostic only — found to trip early (frame ~10) on something other than gross drift; not yet trustworthy as a standalone gate | not set; do not gate on this alone until re-investigated |
| Geometry/texture stability | pixel variance inside static masks | non-zero beyond noise floor |
| Frozen animation | motion energy inside regions the plan marks animated | ≈ 0 |
| **Motion matches the scene's intended level, per region** (see `ARCHITECTURE.md` § Scene representation). Human review, 2026-09-22: near-still pines rated excellent for a calmer scene, swaying pines excellent where wind is expected. Region motion via `motion_speed.py --box`; for vegetation over fog, measure dark (silhouette) pixels separately from bright (fog) pixels. | B1 pines, trees-only flow at native speed: calm ≈ 1.15 (seed 306), windy ≈ 5.1 (seed 302), both human-approved for their mood | outside the target band for the scene's level (bands uncalibrated) |
| **Motion too fast** (added after human review found the B1 clips far too fast: racing clouds, flickering lights, swaying trees) | mean optical-flow magnitude, px/s at 448 px width (`experiments/motion_speed.py`, enforced by `experiments/clip_gate.py --max-flow`). Measure the clip **as delivered** (after slow motion). Human confirmed the ranking tracks perception (seed 204 busier than 203). | **> 2.4 px/s** (provisional; calm label 2.04, too-fast labels 2.85–3.57; seed 203 at 2.68 unlabeled in absolute terms). Calm prompt + ½-speed slow motion brought the busiest clip (3.54) to 1.88 |
| Frame integrity | frame count vs expected, duplicate-frame hashes, NaN/black/corrupt frames | any mismatch |
| Encoding | ffprobe: resolution, fps, pix_fmt, GOP structure, duration, timestamp monotonicity | differs from spec |
| Long-form assembly | decode across N loop joins; timestamps continuous; no re-encode generation loss | any discontinuity |
| Repetition visibility (proxy) | self-similarity over time of the long-form schedule; shortest exactly repeating period | period shorter than target |

The plan stage's list of what must move vs stay still (plus measured optical flow) is what makes several of these checks possible — another reason the plan is a persisted artifact.

## Subjective rubric (1–5, human; 4+ required at T2 gate)

- **Prompt fidelity** — everything the user asked for is present; inferred additions don't override intent.
- **Composition** — clear subject, depth (fg/mid/bg), balanced framing, cinematic lighting.
- **Motion realism / physical plausibility** — speeds, scales, and coupling make sense (wind affects trees *and* fog *and* smoke consistently).
- **Image quality / artifacting** — no AI smear, warping, banding, aliasing, compression artifacts.
- **Lighting continuity** — changes are slow, motivated, and loop cleanly.
- **Seam visibility** — reviewer watching the loop 5× cannot point to the seam.
- **Repetition visibility** — reviewer watching several minutes cannot identify a repeating pattern.
- **"Living photograph" feel** — calm, continuous, nothing draws the eye as wrong.

## Tier gates

| Gate | Must pass |
|---|---|
| T0 → T1 | spec/plan schema valid; keyframe still approved (composition, look, every requested element present); motion prompts reviewed |
| T1 → T2 | preview segment: motion character/intensity approved, camera locked, no gross artifacts |
| T2 → T3 (the only step that spends money) | all objective checks on the full dev-res loop incl. seam, shimmer, drift; subjective rubric ≥ 4 on every line except image sharpness, which T3 is expected to fix |
| T3 → assemble | frame integrity + encoding + seam checks on the final loop(s) |

Expensive tiers never run on a scene that has not passed the cheaper gate.

## Benchmark scenes

Chosen to expose weaknesses, not to flatter. The first four are the prompts from the original project brief.

| ID | Scene | Stresses |
|---|---|---|
| B1 castle | Moonlit castle on a hill, rolling clouds, valley fog, swaying trees, flickering warm windows, shifting moonlight | atmosphere, clouds, volumetrics, artificial + slowly varying light, distant vegetation. **Likely first slice (most forgiving).** |
| B2 sailboat | Sailboat on ocean: rolling waves, clouds, reflected light, spray, shifting sails, boat motion | water simulation/looping, reflections, rigid-body motion coupled to water, fabric, particles |
| B3 cabin | Cabin by forest lake: reflected lights, shimmering water, mist, trees, chimney smoke | reflections of animated sources, calm water, smoke/particles, near vegetation |
| B4 buffalo | Buffalo on prairie: wind in grass, fur, clouds, dust, insects, atmospheric light | animal/organic subject, fur, dense foreground vegetation, tiny particles. **Expected hardest.** |
| B5 rain street | Rainy city street at night, neon signs reflecting in puddles, drifting steam | weather, hard-surface/man-made geometry, many artificial lights, high-frequency particles (loop-hostile) |

For each benchmark, record results and failure modes per approach in `research/`.
