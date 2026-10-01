"""take stage (ADR 0007): one LTX-2.5 distilled pass, depth-locked to the still keyframe, steady-light prompt,
up to 481 frames (WanGP's LTX window caps at 501), with the run's own latents saved for the closure and any extension.
Whether the take is loopable (stationary) is judged by the separate CPU stage `take_qc`.
"""
from __future__ import annotations

from pathlib import Path

from looper import hw, loopkit
from looper.adapters import ltx, wangp
from looper.motion_style import steady_light

VERSION = 1

def run(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """inputs: {"image": keyframe [, "guide": a moving control video at the keyframe's framing (--take-guide)]};
    config: {prompt, negative_prompt, frames, seed, resolution}"""
    prompt, negative = steady_light(config["prompt"], config["negative_prompt"], config.get("moving_light", False))
    ctrl = ltx.control(inputs["image"], config["frames"], out_dir / "control.mp4", inputs.get("guide"))
    speed = config.get("motion_speed", 1.0)  # absent (= 1) for every run without --motion-speed
    s = ltx.settings(prompt, negative, inputs["image"], ctrl, config["frames"], config["seed"], config["resolution"],
                     speed, config.get("guide_strength", 1.0), config.get("single_stage", False))
    ltx.write_settings(out_dir / "settings.json", s)
    with hw.HardwareSampler() as sampler, ltx.hooks(save_latents_to=out_dir, motion_speed=speed):
        meta = wangp.generate(s, out_dir, "take.mp4", scratch_dir=scratch_dir)
    lat1 = ltx.stage1_latent_path(out_dir, config.get("single_stage", False))
    for f in (lat1, out_dir / "lat_stage2.pt"):
        if not f.exists():
            raise RuntimeError(f"latent hook did not fire: {f.name} missing (WanGP LTX pipeline changed?)")
    frames = loopkit.read_frames(Path(meta["output"]))
    if len(frames) != config["frames"]:
        raise RuntimeError(f"take has {len(frames)} frames, asked for {config['frames']}")
    meta.update(peak_hw=sampler.peak, frames=len(frames), runtime=ltx.runtime(s, speed),
                latents={"stage1": str(lat1), "stage2": str(out_dir / "lat_stage2.pt")})
    return meta
