# Common room: the first interior fire-and-moonlight scene (2026-10-01)

**Status: in progress** (the final loop is rendering: `runs/gcr_photo_final`). Run `runs/gcr_fire`: the user's still (1507x1044 castle common room:
stone fireplace with a small fire, one moonbeam through a leaded window, sparse dust motes, a brass lamp, a mug of tea)
+ the user's prompt (`runs/inputs/gcr_prompt.md`: slow, delicate motion; steady moonlight through "both" windows;
motes; tea steam; "Preserve the composition"). Plain route (no person, no donor), `--resolution 832x576` (the still's
own 1.44 aspect: the default 832x480 cover-crop would cut the mug and the window top).

## What happened

- **Director v24** kept the user's motion closely; it also put two steady lights among the moving elements:
  "Silvery moonlight streams steadily through the leaded glass, forming soft beams ..." and "The brass lamp maintains a
  steady, warm golden glow".
- **take[settle] (20 s from the still) grew the moonlight for the whole take:** left beam region 60 -> 78 grey, the
  small alcove window (no beam in the still) grew a strong beam into the hearth (73 -> 90), whole frame +5.4, the
  scene shifted blue, the motes vanished into the beam haze. Not a transient that settles (still rising at 20 s).
- **settle (auto) took the take's LAST frame as the keyframe** (early 9.09 / late 4.29 grey, the same pattern as the
  steam / mist starts it was built for). The loop therefore starts from a grown, different-looking room.
  A similarity guard on settle is **not** supported: still-vs-settled frame difference was 16.3 grey here and 13-21
  on the neon / falls / leviathan settles that helped -- motion texture dominates the number.
- **The loop itself is technically excellent:** take drift 0.51, closing 0.883, loop drift 1.79, no QC flags. Fine
  stone texture is much softer than the still (Laplacian variance of the hood cell 713 -> 114).
- **Review 12:** joins invisible; smoke, steam and moonbeams about twice too fast; no floating motes in the air (wanted),
  though motes carried inside the moonbeams, as here, are acceptable. -- the grown beams are acceptable; speed is the
  defect.
- Contract false positives on this scene and on spice ("streams steadily through", "subtly waves and shimmers") put
  a water item on both review checklists: fixed (contract v7 / v8).

## Speed probes (121 f from the loop's own start frame, seed 306)

Optical-flow speed per region vs native (Farneback, frames 24-120; `runs/gcr_fire/speed_compare/`):

| motion clock | smoke above the fire | tea steam | moonbeams |
|---|---|---|---|
| 0.5 | 0.53x | 0.44x | 0.38x |
| 0.3 | 0.42x | 0.50x | 0.30x |

On an unguided plain-route take the clock slows LTX's own smoke / steam / beam dust about in proportion (unlike the
donor-guided spice takes, 0.92-1.10x). Nothing looked syrupy at 0.3 (water at 0.2 did, lighthouse). **User picked
0.3x** from the three-row comparison. Full loop: `runs/gcr_fire_s030` = the settled frame + director v24's motion
prompt verbatim (`runs/inputs/gcr_motion_prompt.txt`, `--raw-prompt`), `--no-settle --motion-speed 0.3`.
The queued light test never ran: Windows PowerShell 5.1 drops an empty-string argument to a native program
(`--sub "..." ""` arrived one argument short); not re-run since the user accepted the beams.

## The 0.3x loop (Review 13)

`runs/gcr_fire_s030`: take drift 1.17 (strict pass, first seed), closure 306 PASS (closing 0.942, loop drift 2.3); the take
part and the generated return move at the same speed (smoke flow 0.108 / 0.107); vs the native loop smoke 0.55x, beams
0.61x. The review encode exaggerated the closure step (1.92x vs the master's 1.5x): the review copy was re-encoded
without keyframes (`keyint=infinite:scenecut=0`, joins 1.67x / 1.46x vs its own worst 1.99x).
**Reviewer:** the moonbeam movement looks bad and should barely move; the speed of everything else is fine.
The beams do not pulse (brightness range 1.6-3.8 grey, like the stone wall's 2.8); the haze /
dust inside them streams (left beam flow 0.081 px/f vs the wall's 0.024). Probes from the same frame at 0.3x:
A = the director's moonlight clause removed ("Silvery moonlight streams steadily ... drifting particles"), motes kept;
C = moonlight and dust-mote clauses removed.

## Calming the moonbeams (2026-10-01)

Beam haze flow at 0.3x, 5 s probes from the grown frame (stone wall 0.018-0.019 for scale): current 0.045 / 0.033
(left / alcove beam); A (moonlight clause removed) 0.052 / 0.033; C (moonlight + mote clauses removed) 0.041 / 0.033;
D (C + "the shafts of moonlight and the haze inside them stay perfectly still" before the fixed list) 0.045 / 0.033.
**Wording does not move the haze inside a grown beam (all within +-14 %).** Nor does the seed: 306 / 307 / 308 gave 0.047 / 0.046 / 0.049 (left beam). What changed it: starting from the user's
own photo (one soft beam) at 0.3x without the moonlight / mote clauses (`take[origC_306]`, 481 f): the beams do not grow
over 20 s (left 64.4 -> 65.5 -> 64.3 -> 63.0 -> 63.8 grey; the first run, native clock + the moonlight clause: 60 -> 78
and a new alcove beam). Two things changed at once (the light clause removed AND the clock 0.3x instead of native), so
which one stopped the growth is untested (HYPOTHESIS: naming steady light as motion grows it, as the pine sun did);
the visible haze motion belonged to the grown, denser beams. **Reviewer picked the version from the photo** (bottom row), approved for the full loop -> `runs/gcr_photo_s030`
(`runs/inputs/gcr_motion_prompt_nolight.txt`, `--raw-prompt --no-settle --motion-speed 0.3`).

## The loop from the photo (Review 14)

`runs/gcr_photo_s030`: take drift 2.04 (strict pass), closure 306 PASS (closing 0.952, loop drift 4.91 in the fire cell),
joins 1.27x / 1.13x vs the loop's own worst 1.33x. The beams moved less than in the grown version (left beam flow 0.043
vs 0.076), but the photo's floating specks now drift as motes (hood region 0.086 vs 0.02) and the fire / smoke region
moved 1.47x as much (0.157 vs 0.107: a bigger, brighter fire as photographed). **Reviewer:** the motes and scene fog move
too fast. Probes from the photo at 0.2 / 0.15 vs a 0.3 reference (121 f) to choose a slower clock.

## Slower clocks from the photo, and motes held by wording

121 f probes from the photo vs a 0.3 reference (flow per region): 0.2 -> fog over the fire 0.68x, motes 0.68x, steam
1.04x, beams 1.09x; 0.15 -> 0.74x / 0.62x / **1.76x / 1.38x** (below ~0.2 the clock stops slowing the fog and makes the
steam and beams churn -- the over-slowed look water showed at 0.2). **Reviewer:** 0.15x is right for the dust, but 0.3x for
the fire and smoke. The clock is one dial for the whole frame (a per-region clock would be a region mask: ruled out).
**Wording does move discrete particles:** 0.3 + "Tiny dust motes hang almost motionless in the air, each drifting only a
hair's breadth over many seconds, while the fire keeps flickering at its natural pace." -> motes 0.58x (= the 0.15 target,
0.033 vs 0.035), fire / smoke region 0.82x, steam 1.02x, beams 1.14x. (Contrast: no wording moved the haze inside a
grown volumetric beam.) Approved for the full loop -> `runs/gcr_photo_final` (`runs/inputs/gcr_motion_prompt_final.txt`).

## Full-length dust tests (481 f takes; 121 f probes mispredicted long-take motion)

The same settings gave 0.033 mote flow in a 121 f probe and 0.072 in the first seconds of the 481 f take: short
probes do not predict long-take motion; compare full takes. Final loop (`gcr_photo_final`, 0.3 + the motes clause):
reviewer: dust still too fast. Full takes vs that take: A, stronger wording ("The dust motes and the faint haze in the
air hang completely still, suspended like a photograph; only the flames flicker ...") -> motes 0.94x, fog / smoke
1.00x (wording saturates); B, clock 0.2 -> motes 0.67x, fog / smoke over the fire 0.81x, steam 0.92x, beams 0.77x.
Reviewer on B: dust still too fast -> full takes at 0.15 and 0.1.

## Next

1. The 0.3x loop (`runs/gcr_fire_s030`, rendering) -> self-QC -> review.
2. Open, on hold: steady light named as motion grows it (pine sun, this moonlight). No director rule yet -- the user
   accepted the grown beams here; test it on the next scene whose light must stay as photographed.
