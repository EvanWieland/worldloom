# Rotating lighthouse beam — can LTX render it? (E-beam-0, 2026-09-26)

Context: periodic/timed events report `docs/handoffs/2026-09-26-periodic-events-research-report.md`. Its three ranked
approaches all presuppose LTX-2.5 distilled can *render* a rotating beam; this probe tests only that (no loop, no timing).
Code: `experiments/beam_probe/run.py` (renders), `measure.py` (polar kymograph around the lantern + contact sheet).
Outputs: `runs/beam_probe/` (gitignored). 241 f, 832×480, production recipe minus steady-light clause and minus the
"sweeping light beams, changing light" negatives.

Metric: image-plane angle of the strongest light on a ring (r 40–220 px) around the lantern, per frame, static scene
removed by per-angle median.

**Perspective (corrected mid-probe):** a beam turning horizontally at lantern height, seen from below (eye at sea
level), projects to direction ∝ (sin θ, −(h/D)·cos θ): pointing away it aims DOWN to its vanishing point on the
horizon (short, dim); pointing at the camera it aims UP and runs off the frame (long, flaring). So the image-plane angle
goes all the way round — a one-way "clock hand" circle is physically right — but it is fast through vertical and slow
near level: steep (> 35° off level) only ~10–15 % of the time for a lantern ~10° above the horizon (kf11: 14 %). The
first reading below ("steep = wrong axis") was wrong; the tell-tales of a fake are instead reversals, jumps, too much
time steep, and up/flare and down/dim not coinciding.

## v1 — physics wording ("rotates steadily around its vertical axis ... foreshortens"), keyframe kf11 (beam tilted ~15° up)

| clip | steep | net turns | frames moving one way | jumps | notes |
|---|---|---|---|---|---|
| v1 s1 depth | 26 % | −1.04 | 44 % | 1 | two reversals; flares at 2.5 / 6.5 s |
| v1 s2 depth | 42 % | +0.73 | 64 % | 2 | full circles incl. down onto the sea, reversal mid-clip |
| v1 s3 depth | 29 % | +2.67 | 96 % | 0 | one way, ~2.5 turns |
| v1 s1 no depth | 52 % | −1.97 | 91 % | 0 | one way, too much time steep |

## v2 — prompt describes the projected path (left → flare at camera → right → fades behind tower), same keyframe/seeds

| clip | steep | net turns | one way | jumps | notes |
|---|---|---|---|---|---|
| s1 | 22 % | −0.19 | 33 % | 1 | near-identical to v1 s1: **seed + keyframe dominate, wording barely moves it** |
| s2 | 26 % | +1.06 | 85 % | 0 | one way, slow |
| s3 | 30 % | −1.34 | 83 % | 0 | **physically consistent**: up + lantern flare (toward) at 1 s / 8 s, short dim down behind tower (away) at 4.5 s, period ~5 s → sent as *Beam review 1* |

**Conclusions so far:** LTX renders a convincing volumetric beam attached to the lantern, lighting haze/water/rocks and
flaring when it faces the camera — a big step from dir_lighthouse2's static lamp (whose director had banned sweeps).
Roughly half the seeds keep one direction for 10 s; one (v2 s3) looks physically right. Prompt wording is a weak lever;
no control over period or phase. Depth lock is not what causes reversals.

## v3 — procedural guide as model input (SDEdit), for axis + period + phase control

Base still kf32 (lit lantern, no beam) + a true-perspective render of a 6 s horizontal turn (`run.py guide`), fed to
stage 1 through WanGP's own mask-injection path with an all-zero mask: for the first k of 8 steps the latent is replaced
by the guide noised to sigma[k] (k=5 → 0.909, k=6 → 0.725), then denoised freely; stage 2 untouched; T2V (no start
image), depth lock from the base still. The model renders every delivered pixel (report §6: guide as input only).

- First k5/k6 attempt was **invalid**: only `distilled.prepare_mask_injection` was patched, but every LTX pipeline
  module imports it by name; the injection never fired (k5 and k6 outputs near-identical, guide ignored). Patch all
  modules; WanGP's worker thread swallows `print`, so the hook logs to `runs/beam_probe/guide_debug.txt`.
- **v3test (49 f, T2V, k6): the output tracks the guide** — median angle error 14°, 90 % of frames within 45° — and
  the beam is re-rendered as a soft volumetric shaft, not the guide's flat wedge. T2V side effects: orange frame 0,
  scene much darker than the base still → next run is I2V from the base still with the guide starting beam-away
  (frame 0 ≈ base).
- The guide was also injected BGR (`loopkit.read_frames` is OpenCV BGR; `close.py`/`extend.py` convert, the
  experiment didn't). Fixed, but it was not the main problem.
- **Real bug: a 1-frame mask.** `prepare_mask_injection` pads a mask shorter than the video with ONES (= keep the
  generated latent), so an all-zero 1-frame mask injected only latent 0. Diagnosed with a k=8 round trip (stage-1 latent
  should equal the guide): per-step log showed |latent − guide| = 0.72 after the final masked step, latent 0 exact,
  latents 1–6 uncorrelated. With a full-length zero mask: |latent − guide| = 0.000 and the output tracks the guide
  within 7° median (98 % of frames within 20°). **So v3test/v3b/v3c never tested the idea** — their "dark orange scene,
  beam starting left" is simply the model's own output for the v2 prompt on kf32; v3test's 14° agreement was a
  coincidence (default beam and old guide both started on the left).
- **v4: 241 f, I2V from kf32, stage-1 injection, no stage-2 injection — WORKS.**

| k (start sigma) | median angle error vs guide | within 20° | look |
|---|---|---|---|
| 6 (0.725) | 6° | 99 % | kf32 look kept; soft level shaft, photographic flare + lens ghost at the camera-facing pass; beam slightly clean/regular → *Beam review 2* |
| 5 (0.909) | 6° | 99 % | smokier, more haze texture, rocks brighten as the beam passes; but a bright blob midway along the beam at ~1.5 s / 8 s |

  Axis, period (exactly 6 s) and phase are now set by the guide; the model renders every pixel.

## v5 — guided 481 f take + guided closure → first beam loop (E-beam-1)

`close_loop.py`: take[81:481] + 32-frame gap = 432 f = 3 turns (start frame 81, not the default 89, so the loop is a
whole number of turns; 81 ≥ the measured settling minimum 49). Closure window as `stages/close.py` (49 | 32 | 64, true
latents) + guide at take time injected into the gap only; raw gap (no histogram match: it would pump the beam) +
same-instant 8-frame ramps.

| check | result |
|---|---|
| take vs guide | 7° median, 100 % within 20°, 3.3 regular turns |
| take drift (per-turn cell means, §8.1 of the report) | worst cell **0.7 grey** (gate 4); same-phase repeat one turn apart 1.9 grey |
| beam phase through the gap | 7° median, 13° max — no skip, freeze or reversal |
| wrap step vs the same beam phase 1–2 turns away | ×1.34 (gap start ×1.44; the take's own worst natural step ×1.57) |
| eye (contact sheet 396–431, 0–6) | beam sweeps level-right → flare → up-left and carries on into frame 0 |

Sent as *Beam review 3* (loop ×3 = 54 s). Closure seed 307: wrap ×1.18, otherwise identical.

## v5 + extension — 30 s = 5-turn loop (E-beam-2)

One guided extension (337 f window = 49 context + 288 new, true latents α 0.5, guide on the new frames only; raw
window + same-instant ramps instead of `join`'s histogram match) → long 769 f → loop long[81:769] + 32 = 720 f.

| check | seed 306 | seed 307 |
|---|---|---|
| extension beam vs guide | 7° median (20° max) | same run |
| per-turn cell drift over 5 turns | 3.2 grey (top-row sky creeping up; global 34.6 → 35.5) | 3.2 |
| gap start / wrap vs same beam phase | ×1.32 / ×1.28 | ×1.38 / ×1.10 |
| worst natural step in the loop | ×1.50 (p95 ×1.16) | same |
| beam through the gap | 6° median, 15° max | 6°, 11° |

Earlier unguided extensions drifted 4.6–5.0 grey (other scenes), so 3.2 here is under the gate, but it is one
scene, so this doesn't show the guide reduces drift. The upward sky trend means 60 s (a second extension) would
probably fail. Seed 306 sent as *Beam review 4* (30 s ×2).

## Review verdicts (2026-09-26)

| review | clip | verdict |
|---|---|---|
| 1 | unguided v2 s3, 10 s | **looks real** |
| 2 | guided v4 k6, 10 s | **fake**: the beam's source was always visible and seemed to come from the camera-facing side of the lighthouse, even when it should shine the opposite way; the blinding flare when it points at the camera is good, but the beam seems to shoot far overhead, which contradicts that perspective |
| 3 | 18 s loop | joins: **nothing noticed** |
| 4 | 30 s loop | join / extension stitches / drift: **nothing noticed** |

→ Guide-driven looping (phase-continuous closure + extension) works to the eye. The failure is the **guide's physics**:
(1) no occlusion or dimming when the beam points away (the lantern's front stays lit, the beam starts in front of it);
(2) a level beam above the eye rises overhead when it swings toward the camera, while the flare says the camera is
*inside* the beam. Those contradict each other. Fix: the beam's axis sweeps a cone through the camera (pitched down by
the lantern's elevation angle, 9° here), so facing the camera it projects onto the lantern point → the flare, not a
streak; pointing away it is hidden behind the lantern room at its origin, the lantern front dims, and the beam descends
to the sea; scattered brightness rises as the beam faces the camera.

## v6 — physics-fixed guide: still fake (review 5)

v6 guide (cone through the camera, occlusion, dimming) tracked at 7°; flare with no overhead streak, beam emerging
from behind the lantern when facing away. **Reviewer: still very fake, far worse than the other
scenes, which look great.**

**Conclusion:** the fakeness is the guide itself, not its physics. At k=6 (sigma 0.725) the composition and motion
are fixed by the drawing; LTX only adds texture, so the drawing's hard shapes, perfectly even angular speed and
textbook flare survive. Every scene the user rated real (and review 1) had motion invented entirely by LTX. Control
from a strong drawn guide costs realism. The guided *loop recipe* (whole-cycle length, phase-continuous extension
and closure, raw gap) is still validated (reviews 3–4: nothing noticed) and does not depend on where the motion comes
from.

Next: (A) unguided take (review-1 recipe: kf11, v2 prompt, seed 3) → measure the natural period → loop of whole
turns with an unguided closure; (B) weak guide: heavily blurred glow (only "light here now"), fewer injected steps.

## v7a — unguided 481 f take (review-1 recipe: kf11, v2 prompt, seed 3)

One direction for all 20 s (~2.8 turns, no reversal), but the **speed wanders**: camera-facing flares at frames 15,
91, 198, 303, 478 → turns of 107 and 105 frames, then 177 (the beam lingers pointing right at frames 320–384).
Whole-frame autocorrelation misread the period (280 f; waves dilute it). Flare timing (lantern-glow peaks) is the
reliable landmark; `period.py` autocorrelation is right only for clean periodic takes (guided: 144.1). → Unguided
realism, no steadiness: the steady stretch would give only a ~9 s (2-turn) loop. Trade-off confirmed: realism
(unguided) vs steady rhythm (strong guide).

v7b: weak guide (guide blurred by σ 20 px: only "light over here now"), k6 and k5 — the middle ground.

v7b result: **rhythm held exactly by both** (camera-facing flares at 72 and 216 = 144 f) — even a σ 20 px blurred
guide sets the timing. But the look follows the guide's strength: k6 gives a faint diffuse glow (clear beam only 36 %
of frames); k5 gives short puffy cones. Neither matches review 1's long crisp shaft through haze (self-QC side by
side) → not sent.

## Where this stands (parked 2026-09-26 for the user's Last Furnace scene)

- Timing control is cheap: any guide, even blurred, locks the rhythm. The beam's *look* is decided by how strongly the
  guide constrains the model; nothing tried yet gives rhythm AND review 1's look.
- Untried ideas: guide in the gap/closure only with an unguided take that happens to be steady (seed search on
  period stability); an unblurred but brightness-only guide (no shape: just the glow at the lantern + a faint haze
  lift in the beam's direction); k=5 with a stronger (less blurred, σ 6–8) guide; guide the take only for the first
  ~2 s to set phase, then let it run free (does the model keep a rhythm it's given?).

## Open

- See above; verdicts pending on nothing (reviews 1–5 all judged).
- Guided beams are exactly regular. Real lighthouses are regular too, but review 1's unguided beam varied slightly.
- Water barely moves in this still (kf32); not yet tested with a livelier sea.
- Productising: guide in take/extend/close stages, beam-aware QC (per-turn drift + phase error) replacing per-second
  drift for declared periodic events, and an ADR for "procedural guide as model input".

Side finding: **WanGP's LTX already implements Prompt Relay** (`prompt_relay_frame_offset`, `prompt_relay_epsilon`,
relayed-prompt enhancer in `models/ltx2/ltx2_handler.py`) — the report's approach 2 needs no port.
