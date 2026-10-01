"""close stage (ADR 0007): the generated loop closure. One LTX window [end context | gap | start context], both
contexts as clean timestep-0 latents taken from the source runs' OWN saved latents (end: the take or the extension
window; start: the take from `start_frame`, which must lie past the I2V settling: returning to frame 9 made a 4-8x
catch-up step the eye saw; frame >= 89 did not). 32-frame gap = best of 16/24/32/40. One stage run per seed; the
pipeline picks the best closure after `splice` + `loop_qc`.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from looper import hw, loopkit
from looper.adapters import ltx, wangp
from looper.motion_style import steady_light

VERSION = 2  # v2: optional end_frame (the endpoint stage's cut; the end context ends there instead of at the last frame)
MIN_START_FRAME = 49  # measured: 49 / 89 / 97 / 241 all removed the snap; 9 did not
MAX_FRAMES = 481  # WanGP's LTX sliding_window_size: a longer clip is split into windows and the contexts break


def run(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """inputs: {image, end_video, end_lat1, end_lat2, start_video, start_lat1, start_lat2 [, guide]}
    config: {prompt, negative_prompt, seed, resolution, start_frame, frames, prefix_latents, gap_frames, [end_frame]}
    end_frame: the end context is end_video[end_frame - E : end_frame] (must be 8j + 1); default = the whole video.
    guide: a moving depth guide for the whole window instead of the held still (experimental, report Path B)."""
    lay = loopkit.CloseLayout(config["frames"], config["prefix_latents"], config["gap_frames"])
    s0 = config["start_frame"]
    if lay.frames > MAX_FRAMES:
        raise ValueError(f"closure window of {lay.frames} frames exceeds one LTX window ({MAX_FRAMES})")
    if s0 < MIN_START_FRAME:
        raise ValueError(f"start_frame {s0} is inside the I2V settling (min {MIN_START_FRAME})")
    end, start = loopkit.read_frames(inputs["end_video"]), loopkit.read_frames(inputs["start_video"])
    if config.get("end_frame"):
        end = end[:config["end_frame"]]
    src = end[len(end) - lay.E:] + [np.full_like(end[0], 127)] * lay.gap_frames + start[s0:s0 + lay.S]
    assert len(src) == lay.frames
    first = out_dir / "first.png"
    cv2.imwrite(str(first), src[0])
    ctx = ltx.Context(
        source=np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in src]),
        prefix_latents=lay.prefix_latents, suffix_latent=lay.suffix_latent,
        prefix_true=ltx.TrueLatents(Path(inputs["end_lat1"]), Path(inputs["end_lat2"]),
                                    loopkit.true_first_latent(len(end), len(end) - lay.E + 1)),
        suffix_true=ltx.TrueLatents(Path(inputs["start_lat1"]), Path(inputs["start_lat2"]),
                                    loopkit.true_first_latent(len(start), s0)))
    prompt, negative = steady_light(config["prompt"], config["negative_prompt"], config.get("moving_light", False))
    ctrl = ltx.control(inputs["image"], lay.frames, out_dir / "control.mp4", inputs.get("guide"))
    speed = config.get("motion_speed", 1.0)  # absent (= 1) for every run without --motion-speed
    s = ltx.settings(prompt, negative, first, ctrl, lay.frames, config["seed"], config["resolution"],
                     speed, config.get("guide_strength", 1.0), config.get("single_stage", False))
    ltx.write_settings(out_dir / "settings.json", s)
    with hw.HardwareSampler() as sampler, ltx.hooks(context=ctx, motion_speed=speed):
        meta = wangp.generate(s, out_dir, "window.mp4", scratch_dir=scratch_dir)
    n = len(loopkit.read_frames(Path(meta["output"])))
    if n != lay.frames:
        raise RuntimeError(f"closure window has {n} frames, asked for {lay.frames}")
    meta.update(peak_hw=sampler.peak, runtime=ltx.runtime(s, speed), context=ctx.diag, layout={"E": lay.E, "G": lay.gap_frames, "S": lay.S})
    return meta
