"""bloom stage (CPU, optional `--bloom mild|strong`): brilliance on the keyframe's OWN pixels — a highlight glow
screened back over the still, hotter cores where the highlights are strongest, every other pixel untouched.
Evidence (research/furnace-scene.md): light wording in the motion prompt only drifts the light; image editors
(Kontext, Qwen Edit) regenerate every pixel and changed more than asked; this bloom on the user's still: mild and
strong both passed review (2026-09-26). The mask is the brightest CHANNEL, not luma: a red giant is dark in luma but
saturated. Runs after `fit` and before `settle`, so the take is rendered from the bloomed still.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

VERSION = 1
VARIANTS = {"mild": dict(thresh=0.80, radius=30, gain=1.2, core=0.35),
            "strong": dict(thresh=0.74, radius=40, gain=2.0, core=0.6)}


def bloom(img: np.ndarray, thresh: float, radius: int, gain: float, core: float) -> np.ndarray:
    """Screen a blurred copy of the highlights back over the image; `core` also lifts the highlights themselves."""
    f = img.astype(np.float32) / 255
    value = f.max(axis=2)
    mask = (np.clip((value - thresh) / (1 - thresh), 0, 1) ** 1.5)[..., None]
    hi = f * mask
    glow = cv2.GaussianBlur(hi, (0, 0), radius) * gain + cv2.GaussianBlur(hi, (0, 0), radius / 4) * gain * 0.6
    out = 1 - (1 - f) * (1 - np.clip(glow, 0, 1))  # screen
    out = out + mask * core * (0.35 + 0.65 * f)  # hotter, whiter cores where the mask is strongest
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {image}; config: {variant}"""
    src = cv2.imread(str(inputs["image"]))
    out = Path(out_dir) / "keyframe.png"
    cv2.imwrite(str(out), bloom(src, **VARIANTS[config["variant"]]))
    return {"output": str(out), "variant": config["variant"]}
