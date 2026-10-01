"""splice stage (ADR 0006 step 4 / ADR 0007): closure window -> loop.mp4, CPU only.
  loop = LONG[start_frame:] + tone(gap)                wrap: gap -> LONG[start_frame]
Gap frames are histogram-matched to the CDF interpolated between the real frames on either side, then given one
global sharpness setting matching the take (LTX's gap came out ~30 % sharper). At both splices an R-frame ramp (R = 8:
with true-latent context the re-render is within 1.3-1.8 grey of the real frames, and 8 beat 3 on the wrap step on all
3 seeds of rain_loop_e2e, 1.50-1.53x vs 1.72-1.76x, no new QC flags) mixes
the real frame toward LTX's render of the SAME instant (context re-render, histogram-matched to its real twin):
two renders of one moment, never different content (invariant 10).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from looper import loopkit

VERSION = 3  # v2: lossless master (codec wrap seam), 8-frame ramps; v3: optional end (the endpoint stage's cut)


def splice(long: list, gen: list, start: int, E: int, G: int, R: int = 8, match_sharp: bool = True,
           end: int | None = None, tone: bool = True) -> tuple[list, dict]:
    """tone False: the gap stays raw -- the per-frame CDF target (a straight blend between the two ends' whole-frame
    histograms) would flatten an intended moving light (realism amendment §8; the guided beam loops used a raw gap and
    passed review 3-4). The same-instant ramps are still matched to their real twins (two renders of one moment)."""
    part = list(long[start:end])
    n = len(part)
    ca, cb = loopkit.cdfs(part[-1]), loopkit.cdfs(part[0])
    raw = list(gen[E:E + G])
    gap = [loopkit.tone(f, loopkit.lerp_cdfs(ca, cb, (i + 1) / (G + 1))) if tone else f for i, f in enumerate(raw)]
    # amendment §8: how much the correction changed the generated light (mean |grey| toned vs raw; worst frame).
    # Evidence for "is the correction erasing intended illumination?" -- not a gate.
    shift = [float(np.abs(loopkit.gray(a).astype(np.float32) - loopkit.gray(b).astype(np.float32)).mean())
             for a, b in zip(gap[::4], raw[::4])]
    info = {"gap_start": n, "sharpness_setting": 0.0, "tone": "cdf_lerp" if tone else "none",
            "tone_shift_mean": round(float(np.mean(shift)), 2) if shift else 0.0,
            "tone_shift_max": round(max(shift), 2) if shift else 0.0}
    if match_sharp:
        target = float(np.median([loopkit.laplacian_var(f) for f in part[::6]]))
        gap, t = loopkit.match_sharpness(gap, target)
        info["sharpness_setting"] = round(t, 3)
    for k in range(R):
        w = (R - k) / (R + 1)
        part[n - 1 - k] = loopkit.mix(part[n - 1 - k], loopkit.tone(gen[E - 1 - k], loopkit.cdfs(part[n - 1 - k])), w)
        part[k] = loopkit.mix(part[k], loopkit.tone(gen[E + G + k], loopkit.cdfs(part[k])), w)
    return part + gap, info


def provenance(n: int, start: int, G: int, E: int, R: int) -> list[dict]:
    """Handoff §8: where every loop frame comes from. `out` = loop frames [a, b); `src` = frames of `from` [c, d).
    ramp = the source frame mixed with the model's render of the SAME instant (window frames noted); generated = the
    closure's new frames (no frame-for-frame ground truth)."""
    return [{"out": [0, R], "kind": "ramp", "from": "long", "src": [start, start + R], "window": [E + G, E + G + R]},
            {"out": [R, n - R], "kind": "source", "from": "long", "src": [start + R, start + n - R]},
            {"out": [n - R, n], "kind": "ramp", "from": "long", "src": [start + n - R, start + n], "window": [E - R, E]},
            {"out": [n, n + G], "kind": "generated", "from": "window", "src": [E, E + G]}]


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {long, window}; config: {start_frame, E, G, R, match_sharp, [end_frame]}"""
    loop, info = splice(loopkit.read_frames(inputs["long"]), loopkit.read_frames(inputs["window"]),
                        config["start_frame"], config["E"], config["G"], config.get("R", 8), config.get("match_sharp", True),
                        end=config.get("end_frame"), tone=config.get("tone", "cdf_lerp") == "cdf_lerp")
    loopkit.write_video(loop, out_dir / "loop.mp4", lossless=True)
    G, R = config["G"], config.get("R", 8)
    return {"output": str(out_dir / "loop.mp4"), "frames": len(loop), "seconds": round(len(loop) / 24, 2), **info,
            "provenance": provenance(len(loop) - G, config["start_frame"], G, config["E"], R)}
