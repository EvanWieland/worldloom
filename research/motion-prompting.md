# Motion prompting: how prompt wording and NAG control motion (2026-09-23)

**Evidence level:** one scene (B1 moonlit castle), one keyframe, seed 306, Wan 2.2 i2v Enhanced Lightning v2 (4 steps), 121 f windows + colour correction. Every rule below is a **hypothesis** until it holds on a second benchmark scene (invariant 14). Detailed runs and numbers: `research/loop-direction.md` (A5–A6, A5b/c, c1, cb1–3, g1–3, h1–3).

**Measurement used throughout:** Farneback optical flow on frames resized to 848×480, per region: clouds (rows 30–130), low haze (100–180), valley mist (rows 180–300, left), plants (rows 330+). Speed = median |flow| px/frame; direction = mean dx; back-and-forth sway = std of dx over time. Texture = sky Laplacian variance relative to frame 0 (> ~1.4× reads as fake/painterly).

## Candidate rules

1. **NAG scale is the global motion dial.** Same prompt, cloud speed: NAG 9 → 0.035 px/f (decaying to ~0), NAG 7 → 0.09, NAG 5 → 0.12–0.20. No texture cost at 5. NAG 9 was chosen earlier for camera lock, which is now also held by the prompt; revisit the camera-lock yield at NAG 5–7.
2. **Texture-softening words freeze motion.** "soft, hazy clouds" + negatives "sharp clouds, crisp cloud edges, oversharpened, stylized" froze the sky (0.01–0.02 px/f) across four chains, whatever motion the sky line asked for. Fix the fake look with narrow negatives ("painterly, illustration"), not sharpness words.
3. **Asking for stillness freezes; asking for pace slows.** "stand completely still, no wind", "no drift", "in place" → frozen elements. "filmed in real time at normal speed, not a time-lapse, not sped up" + speed negatives ("time-lapse, sped up, fast-moving fog, rushing mist, strong wind, gusts") slowed things without freezing them. Degree words work in order: "drift slowly" > "drift almost imperceptibly" (0.2 → 0.02 px/f clouds).
4. **State one wind direction for every element.** The model follows an explicit direction ("from right to left" → clouds dx −0.31 px/f, constant sign). Without one, each element picks its own (g3: clouds and mist left, plants swinging both ways).
5. **The direction must agree with the keyframe's static cues** (bent grass, smoke, flags, leaning trees). User caught grass bent to the right while clouds and mist drifted left. The model cannot re-bend a plant already bent the other way without looking wrong. → The wind direction should be decided once, at plan time, and written into **both** the keyframe prompt and the video prompt. For an externally supplied keyframe, read the lean from the image (qwen3-vl is available locally; untested for this).
6. **Describe each element's motion separately.** One global "slow, gentle motion" clause changed mist but not plants (plant sway 0.73–0.77 px/f in all g-variants). Plants need their own clause + negatives against oscillation ("grass swaying back and forth, waving grass, bushes shaking").
7. **Concrete, physical phrasing beats abstract phrasing.** "wisps of thin cloud slowly pass in front of the moon" moved clouds 2× more than "thin clouds creep slowly across the sky" (but it also looked more time-lapse and cost mist motion).
8. **Pipeline-side preconditions** (not prompt): 121 f windows + colour correction keep one direction across windows (81 f windows with 1-frame handoff flipped direction every window); loop closure is done by Wan 2.2 Fun VACE with 16 frames of context on each side (`loop-direction.md`), which keeps the motion through the loop point.

## Human verdicts behind the rules

| sample | review verdict |
|---|---|
| A5 ("change shape in place", NAG 9) | clouds morph, look fake |
| A5b / A6 | good texture, too still |
| A5c (billowing mist, soft hazy clouds) | mist excellent, sky frozen |
| cb2 / cb3 (creep / wisps, NAG 5 / 9) | decent clouds, but time-lapse-like; mist as if in 100 mph winds |
| g3 (still quiet night, faintest breeze, NAG 5) | most realistic; plants slightly too active and leaning against the wind; slightly more foreground cloud movement wanted |

## Proposed formalisation (not built)

- `plan`: emits one wind direction + a motion level per element (`sky`, `low haze`, `mist/water`, `vegetation`, …), and passes the direction to the keyframe prompt.
- `motion_style`: vocabulary table level → phrase + negatives, one direction clause shared by all elements, NAG from the scene's calmness (5–7), pacing clause always on; no "still"/"in place"/sharpness words.
- `validate`: per-region speed band + direction sign + sway amplitude against the plan; reject/retry on mismatch.
- Calibrate speed bands per level from human-labelled samples (today's table is n=1 scene).

## Open questions

- Do rules 1–7 transfer to a scene with water, a forest, or a character (next benchmark)?
- Does NAG 5–7 keep the camera locked across seeds (the reason NAG 9 was adopted)?
- Can qwen3-vl read wind direction from a keyframe reliably?

## Added 2026-09-23

9. **Text cannot set an absolute speed.** "about 2 mph" and a Beaufort-force-1 description made clouds *faster* (0.39 → 0.55/0.65 px/f); NAG 7 had no effect on the mirrored keyframe. The keyframe itself largely sets element speed (mirroring the same image raised cloud speed ~20× under identical wording). Hitting a target speed needs a **measured retime** after generation (flow per region → playback factor), with the prompt only choosing direction and character.

## Second scene: alien crash site (2026-09-23, `experiments/generic_test/`, run dir `runs/alien_test`)

- User prompt → Claude-enhanced prompt (original + enhanced saved in `runs/alien_test/prompts.json`) → real pipeline stages interpret → plan → keyframe (Z-Image). Wind direction written into the keyframe prompt ("smoke … bends gently to the left in a light breeze blowing from the right") → **the keyframe's smoke plume leans left as asked** (rule 5 works at keyframe time).
- **Genericity gap found:** `plan`/`motion_style` would have produced a motion prompt containing the castle's hard-coded "thin clouds creep … mist drifts in the valley" (`_CALM_BODY`). Hand-built motion prompt used instead (single right→left breeze, smoke/fog/veins clauses, pacing clause, NAG 5).
- Chain 361 f @ 832×480, 121 f windows, colour correction: **51 min** (≈18 min/window vs ~10 on B1; free RAM ~4 GB during the run). VACE closure 7.7 min, whole-loop retime → 21.8 s.
- Gates: lower-third motion is bare rock (0.015 px/f), so every ratio is inflated: joins 7.1× / 12.6×, gap 1–7× chain. Gap luma −0.84. Verdict pending.

## Sweep, 14 scenes (2026-09-23/24, `experiments/night_scenes/`, verdicts in `VERDICTS.md` there)

Recipe per scene: Claude-written enhanced prompt with one wind direction → pipeline interpret/plan/keyframe → 241 f chain (121 f windows, colour correction, NAG 5–6, hand-written motion prompt) → Fun VACE closure (16 ctx + 49 gap) → whole-loop retime. ~45 min/scene. 1 failure (dunes: WanGP exited rc=1 after 35 min, empty log — not diagnosed).

User verdicts (11 reviewed; space station window **poor**: dull, planet changes mid-video, a purple cloud appears from nowhere): zen garden **great**, aurora **great**, jungle waterfall **great**, lava river **excellent**, kelp **very good** (kelp a little too still), cabin **very good** (snow in window a little fake), library **good**, neon alley **pretty good** (rain hitting the ground looks fake), anime hillside **pretty good** (field sway odd, slight darkness at the stitch), lighthouse storm **pretty good** (beam did not rotate).

- **The recipe generalises:** no loop point was reported visible in any of the 10 scenes, across photoreal, anime and high-energy content. The castle work transferred without per-scene tuning.
- **Join ratios are not a usable gate** — library 18.9× and alien 12.6× were invisible. Needs an absolute measure.
- **Brightness offset of the VACE gap:** −7.6 (anime) was *seen* as darkness at the stitch; +7.6 (lava) and +6.8 (neon) were not reported. Provisional gate: |gap luma offset| ≤ ~5, or match the gap's luma to its context before splicing (a per-frame gain, not a blend).
- **Weak spots are small fast particles** (rain splashes, snow behind glass) → they look fake. Consistent with the model, not the loop method.
- **New rule 10 — know each light source's natural behaviour:** "lamp glows steadily" stopped the lighthouse beam from sweeping. The motion vocabulary must say what each light does (beam sweeps, candle flickers softly, neon holds steady).
- Wind-direction baking (rule 5) produced consistent drift in every scene where it was used.
