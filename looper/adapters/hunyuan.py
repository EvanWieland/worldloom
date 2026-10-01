"""Hunyuan Video 1.5 as a MOTION DONOR (ADR 0016): its video is only ever a depth guide for LTX, never loop pixels.
WanGP's official 480p step-distilled i2v (8 steps, no CFG, shift 5; ~10 min per 5 s on the laptop). Longer clips are
chained by WanGP in 121-frame windows that overlap ONE frame (the restarts do not reach the guided LTX take:
research/ltx-cloak-screen.md). Vendor specifics stay here (CLAUDE.md invariant 9)."""
from __future__ import annotations

from pathlib import Path

MODEL = "hunyuan_1_5_480_i2v_step_distilled"


def settings(prompt: str, negative: str, image: Path, frames: int, seed: int) -> dict:
    return {"model_type": MODEL, "resolution": "832x480", "num_inference_steps": 8, "guidance_scale": 1.0,
            "flow_shift": 5.0, "sliding_window_size": 121, "prompt": prompt, "negative_prompt": negative,
            "image_prompt_type": "S", "image_start": str(image), "video_length": frames, "seed": seed}
