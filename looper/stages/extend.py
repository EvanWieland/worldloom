"""extend stage (ADR 0007, only when the loop must be longer than one take): continue the take from its own last
49 frames. Context = the take's saved latents blended 0.5 with re-encoded ones (pure true latents overshoot drip
activity, pure re-encoded ones decay it; research/particle-loop-closure.md section 4). One step only: chained
continuations drift. Writes the raw LTX window (its latents saved: the closure's end context); the CPU stage `join`
turns take + window into the long take.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from looper import hw, loopkit
from looper.adapters import ltx, wangp
from looper.motion_style import steady_light

VERSION = 2  # v2: window only (join moved to its own stage)


def run(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """inputs: {image, take, take_lat1, take_lat2}; config: {prompt, negative_prompt, window, seed, resolution, alpha,
    prefix_latents}"""
    take = loopkit.read_frames(inputs["take"])
    P, N = config["prefix_latents"], config["window"]
    E = loopkit.ctx_frames(P)
    src = take[len(take) - E:] + [np.full_like(take[0], 127)] * (N - E)
    first = out_dir / "first.png"
    cv2.imwrite(str(first), src[0])
    ctx = ltx.Context(source=np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in src]), prefix_latents=P,
                      suffix_latent=(N - 1) // 8 + 1,
                      prefix_true=ltx.TrueLatents(Path(inputs["take_lat1"]), Path(inputs["take_lat2"]),
                                                  loopkit.true_first_latent(len(take), len(take) - E + 1),
                                                  alpha=config["alpha"]))
    prompt, negative = steady_light(config["prompt"], config["negative_prompt"], config.get("moving_light", False))
    ctrl = ltx.still_control(inputs["image"], N, out_dir / "control.mp4")
    speed = config.get("motion_speed", 1.0)  # absent (= 1) for every run without --motion-speed
    s = ltx.settings(prompt, negative, first, ctrl, N, config["seed"], config["resolution"],
                     speed, config.get("guide_strength", 1.0), config.get("single_stage", False))
    ltx.write_settings(out_dir / "settings.json", s)
    with hw.HardwareSampler() as sampler, ltx.hooks(save_latents_to=out_dir, context=ctx, motion_speed=speed):
        meta = wangp.generate(s, out_dir, "window.mp4", scratch_dir=scratch_dir)
    window = loopkit.read_frames(Path(meta["output"]))
    if len(window) != N:
        raise RuntimeError(f"extension window has {len(window)} frames, asked for {N}")
    meta.update(peak_hw=sampler.peak, runtime=ltx.runtime(s, speed), context=ctx.diag, E=E,
                latents={"stage1": str(ltx.stage1_latent_path(out_dir, config.get("single_stage", False))),
                         "stage2": str(out_dir / "lat_stage2.pt")})
    return meta
