"""Motion donor stages (ADR 0016): Hunyuan renders the scene's motion from the still; its video, converted to depth by
WanGP, guides the LTX take and -- through a continuation from the loop's end -- the LTX return. Only shape motion
transfers; LTX renders every pixel and closes the loop from its own latents.

  donor         one Hunyuan render of an image (the still: donor[take]; the loop end: donor[return])
  donor_start   the donor frame at the loop's last body frame, at the still's own size (the continuation's image)
  return_guide  take guide [e-E:e] + continuation [1:G+1] + take guide [s:s+S], G chosen by the whole-frame wrap match
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from looper import hw, loopkit, motion_style
from looper.motion_style import steady_light

VERSION = 2  # the donor render (a Hunyuan render is 30-40 min: never invalidate it for a CPU-stage change).
#             v2: the hold-position clause (motion_style.donor_prompt)
START_VERSION = 1
GUIDE_VERSION = 2  # v2: the wrap match is activity-weighted (v1's whole-frame correlation was flat on a real donor)


SLOW_MARGIN = 2  # donor frames: the motion-interpolated retime loses ~2 output frames at the clip's end (479 of 481)
HOLD_VERSION = 1
# A subject that travels in the donor travels in every take. Net torso movement on six real donors (832 px wide):
# holding 0.1 / 1.7 / 1.9, a sway 12.4, a step 13.6 (its take's figure stepped 18 px), a walk 114.5 -> 1 % of the width
TRAVEL_FRAC = 0.01
DONOR_ATTEMPTS = 3


def travels(xs: list, width: int) -> dict:
    """Net movement of the subject over the donor: median of the last three samples minus the first three (a sway of
    the cloak or the torso averages out), in 832-px units. None = no subject found (nothing to hold)."""
    v = np.asarray([x for x in xs if x is not None], dtype=float) * 832 / width
    if len(v) < 6:
        return {"travels": None, "net_px": None, "span_px": None, "found": int(len(v))}
    net = float(np.median(v[-3:]) - np.median(v[:3]))
    return {"travels": abs(net) > TRAVEL_FRAC * 832, "net_px": round(net, 1), "span_px": round(float(np.ptp(v)), 1),
            "found": int(len(v))}


def hold_run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """donor_hold stage (CPU): does the donor's subject stay where it is? inputs: {video}"""
    from looper.adapters import pose
    frames = loopkit.read_frames(Path(inputs["video"]))
    return travels(pose.torso_x(frames), frames[0].shape[1])


def frames_for(guide_frames: int, speed: float) -> int:
    """Donor length (Hunyuan clips: 4k + 1 frames) that a guide of guide_frames frames at speed stays inside."""
    need = math.ceil(round((guide_frames - 1) * speed, 6)) + (SLOW_MARGIN if speed < 1 else 0)
    return 4 * math.ceil(need / 4) + 1


def start_frame(end_frame: int, speed: float) -> int:
    """The donor frame the take guide shows at the loop's last body frame (end_frame - 1): the continuation's start."""
    return round(round((end_frame - 1) * speed, 6))


def _structure(f: np.ndarray) -> np.ndarray:
    """Tone-normalised grey at 1/4 of 832x480 (a small cloak must stay a few pixels wide)."""
    g = cv2.resize(loopkit.gray(f).astype(np.float32), (208, 120), interpolation=cv2.INTER_AREA)
    return (g - g.mean()) / (g.std() + 1e-6)


def activity(frames: list) -> np.ndarray:
    """Where the take moves: per-pixel std over time of tone-normalised grey, summing to 1. Derived from the take
    itself (no regions); used only to choose the cut, never to steer generation."""
    a = np.std(np.stack([_structure(f) for f in frames]), axis=0)
    return a / max(float(a.sum()), 1e-6)


def wrap_match(cont: list, start: list, gaps, weight: np.ndarray) -> tuple[int, dict]:
    """The gap G whose continuation frames cont[G+1 .. G+len(start)] run best into the loop's first frames: the
    activity-weighted mean |difference| of tone-normalised grey (lower = closer). An unweighted whole-frame match is
    decided by the static scene: on the spice donor every gap scored 0.92-0.93; weighted, it picks the cut the user
    passed (research/ltx-cloak-screen.md)."""
    ref = [_structure(f) for f in start]
    scores = {G: float(np.mean([(weight * np.abs(_structure(cont[G + 1 + k]) - ref[k])).sum() for k in range(len(ref))]))
              for G in gaps if G + len(ref) < len(cont)}
    if not scores:
        raise ValueError(f"a continuation of {len(cont)} frames is too short for the gaps {list(gaps)}")
    return min(scores, key=scores.get), scores


def return_guide_frames(take: list, cont: list, s: int, e: int, E: int, S: int, G: int) -> list:
    """cont[0] is the take guide's last body frame itself, so the gap starts at cont[1]."""
    return take[e - E:e] + cont[1:G + 1] + take[s:s + S]


def run(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """inputs: {image}; config: {prompt, negative_prompt, frames, seed [, moving_light]}"""
    from looper.adapters import hunyuan, wangp
    prompt, negative = steady_light(motion_style.donor_prompt(config["prompt"]), config["negative_prompt"],
                                    config.get("moving_light", False))
    s = hunyuan.settings(" ".join(prompt.split()), negative, inputs["image"], config["frames"], config["seed"])
    with hw.HardwareSampler() as sampler:
        meta = wangp.generate(s, out_dir, "donor.mp4", scratch_dir=scratch_dir)
    n = len(loopkit.read_frames(Path(meta["output"])))
    if n < config["frames"]:
        raise RuntimeError(f"donor has {n} frames, asked for {config['frames']}")
    meta.update(peak_hw=sampler.peak, frames=n)
    return meta


def start_run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {video: the donor}; config: {frame, still_size}. At the still's own size, Hunyuan renders the
    continuation at the donor's size and framing (a donor-sized image would come out 832 wide instead of 848)."""
    f = loopkit.read_frames(Path(inputs["video"]))[config["frame"]]
    out = Path(out_dir) / "start.png"
    cv2.imwrite(str(out), cv2.resize(f, tuple(config["still_size"]), interpolation=cv2.INTER_LANCZOS4))
    return {"output": str(out)}


def return_guide_run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {take_guide, cont_guide} (both fitted to the keyframe); config: {start, end, E, S, gaps}"""
    take, cont = loopkit.read_frames(Path(inputs["take_guide"])), loopkit.read_frames(Path(inputs["cont_guide"]))
    s, e = config["start"], config["end"]
    G, scores = wrap_match(cont, take[s:s + 8], config["gaps"], activity(take[::4]))
    out = Path(out_dir) / "guide.mp4"
    loopkit.write_video(return_guide_frames(take, cont, s, e, config["E"], config["S"], G), out, crf=12,
                        pix_fmt="yuv420p")
    return {"output": str(out), "G": G, "score": round(scores[G], 4),
            "scores": {str(k): round(v, 4) for k, v in scores.items()}}
