# 0007 — Loop closure for particle content (rain on glass): candidates for a user decision
Status: accepted, option 2 only, for loops closed inside ONE generation (blind review 2026-09-25: both generated
closures on the 10 s clip, nothing noticed). Invariant 10 unchanged; the crossover exception is not needed.
Extended 2026-09-25: 30 s loops work too when the loop returns past the I2V settling (take frame >= 89): nothing noticed in review
on a 30.7 s loop. The earlier visible stitches returned to frame 9.
Date: 2026-09-24

## Problem
ADR 0006 (16 fps Wan VACE gap + in-overlap ramp) closed the waterfall imperceptibly but failed on the rain cabin
(Review E: the rain slows down, nearly stops, then starts again). Every both-ends-constrained generator tried
before this session stalled the window drips (VACE 0.1-0.25x motion, then a 7-8x snap; LTX RePaint made a new shot or
stalled). Invariant 10 requires generated closure and forbids dissolves between different content.

## Considered approaches
Evidence for all of them: `research/particle-loop-closure.md` (this session) and `research/loop-transition.md`.
1. **Source crossover (rule exception).** Two moving streams of the SAME generated take, `C[k] = (1-a)V[b+k] + aV[a+k]`,
   over L = 4-6 frames (0.17-0.25 s) at a searched pair (a, b); or per-pane switch times (space-time variant).
2. **Generated closure, LTX-2.5 with clean true-latent context (fits invariant 10 as written).** The clip's own
   latents (saved from a bit-exact rerun) as clean timestep-0 context on both sides of a 32-frame gap (best of 16/24/32/40), then ADR 0006's
   tone-matched 3-frame in-overlap ramp and a global sharpness match.
3. Cut-point search alone (hard cut): ruled out, no pair in a 10 s clip is closer than a random pair.
4. Longer units via cross-seed cycles: ruled out, each seed is a different room. Via chained continuation: motion
   decays (re-encoded context) or overshoots (true-latent context) generation over generation; not stationary yet.

## Evidence (automatic regional QC, `experiments/loop_eval/rqc.py`, calibrated on damaged controls + 2 human verdicts)
- Crossover L = 4-6: passes every regional gate on the searched pairs (P1, P2, P3); L <= 3 spikes, L >= 8 thins the
  visible beads (the dissolve transparency the handoff warned about). Keeps 100 % original footage.
- Generated true-latent LTX gap, 32 frames: on 3/3 seeds glass, rail and exterior pass every regional gate (energy,
  spikes, all glass bead statistics); left: the noisy side-glass bead-moving statistic and dark-wall grain (static
  edge gate); largest step in the gap 1.6-2.1x median (24 f: 2-4x catch-up step before the start frames). Old
  loop_qc passes.
- No human verdict on either yet.

## Human verdict (2026-09-25, blind, `experiments/loop_eval/VERDICTS_blind.md`)
- Generated 32 f true-latent closure on the 10 s clip, seeds 306 and 308: **nothing noticed** (both).
- Per-pane crossover: nothing noticed. 6-frame crossover: glass fine, maybe a slight disturbance on the bushes
  outside. Direct cut: jump. Review E (anchor): slowed or stopped. The blind set discriminated as intended.
- Same closure on the stationary 20 s take (with and without the retime) and on the 30 s take: **visible at the
  stitch** (a jump, and the window-rain distortion breaks up). There the raw catch-up step was 4-8x vs 1.6-2.1x on
  the 10 s clip; the retime did not hide it.

## Recipe (accepted; experiment code until Phase C, `experiments/ltx_clean/`)
1. Take: LTX-2.5 distilled, depth-locked, **steady-light prompt** (long passes otherwise drift to amber), 481 f single
   window (WanGP max 501), latents saved (`_save_latents`). For 30 s: + one continuation from the take's own latents
   blended 0.5 with re-encoded ones (`run.py extend --true --alpha 0.5`, 361 f window).
2. Closure: `run.py close2`, 32-frame gap, prefix = the take's last 49 frames as its own latents, suffix = latents
   from **take frame >= 89** (after the I2V settling), `assemble2.py --match-sharp` (tone-matched 3-frame in-overlap
   ramps, global sharpness match). Pick the best of ~3 seeds by closing-step max vs the loop's own steps + `rqc.py`.
3. No retime (`fix_snap.py` fooled the gates, not the eye).
4. (Pipeline, 2026-09-25) 8-frame in-overlap ramps, LOSSLESS loop master (a crf-10 master's own codec wrap was
   visible), delivery as a continuously encoded multi-period block + stream copies. Implemented as
   `python -m looper loop`; its first output passed review (nothing noticed).

5. (2026-09-25, generalisation) The closure works on any scene; what the viewer sees tracks how stationary the take
   is (worst 3x4-cell luma range: 1.7 grey nothing noticed, 6.7 very slight on two scenes, 13.7 a shift, 35 a
   clearly visible build-up). Hence `take_qc` (gate 4 grey), **always settle the keyframe** (user decision: a take's
   last frame becomes the keyframe; neon 16-34 -> ~7 grey), and **best effort + warning** when no take reaches 4
   grey (steadiest take ≤ 7.5) or no extension stays steady (take-only loop). Prompt wording fixed lighting drift
   but not steam accumulation; longer extension context (to 6 s) did not reduce extension drift.

## Decision (original proposal, kept for context)
- If the blind review finds the crossover imperceptible and the generated gap perceptible: adopt a **narrow
  exception** to invariant 10: "for particle / stochastic-texture regions of a locked-camera shot, the loop may close
  with a <= 6-frame crossover between two moving streams of the SAME generated take (same seed, same room), chosen by
  the regional search and passing rqc; never between different takes, seeds or re-dressed rooms, never frozen
  endpoints". Label it in the manifest as a source transition, not generated closure.
- If the generated gap is imperceptible: keep invariant 10 unchanged and adopt option 2 as ADR 0006's LTX variant.
- If neither passes: pursue the per-pane space-time switch or a longer same-take source (fix continuation drift).

## Tradeoffs
Crossover: cheapest (CPU, seconds), no second model, but a period can't exceed the take (one 241 f LTX pass = 9.5 s);
30-60 s needs a longer same-room take, which is the open drift problem. Generated gap: fits the rule and needs no
longer take to close, but costs ~5 min GPU per try, needs the latents saved at generation time, and still shows a
small catch-up step.

## Consequences
- Either way the pipeline must keep each clip's latents (`gen_job.py "_save_latents"`): re-encoding decoded frames
  loses ~30 % of glass motion energy and 20 % of visible beads, and contexts built from re-encodes weaken whatever is
  conditioned on them.
- `rqc.py` (regional, source-relative) replaces `loop_qc.py` as the pre-review gate for motion content.

## Revisit when
The blind review of `blind2` is in; or a stationary same-room take of >= 30 s exists.
