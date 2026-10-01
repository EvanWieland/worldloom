"""settle stage (CPU): keyframe -> settled keyframe. The pipeline first generates a normal take from the user's image
(the `take` stage, so it is cached / reused as a take); this stage writes its LAST frame as the keyframe for every
later stage. Accumulating elements (steam, mist, haze) then start at the level the model builds them up to instead of
building up during the loop: neon alley region drift 16 / 34 / 9 grey -> 6.7 / 9.5 / 10 (one pass) -> 6.8 / 7.0 / 7.4
(two passes); the settled loop was rated very slight in review (research/particle-loop-closure.md section 15).

mode "auto" (default since 2026-09-27; realism amendment: "trim only a demonstrated transient"): settle only when the
prompt names an accumulating medium AND the take shows a start transient (worst 3x4 cell, mean of the first second vs
seconds 3-5) above TRANSIENT_MIN grey. Otherwise the user's own image stays the keyframe, and the next take is the
settle take itself (same config and inputs: a cache hit). Calibration on the cached settle takes (early / late grey):
neon 4.9 / 1.8 and 7.3 / 4.6, falls 5.4-5.9 / 4.2-4.9 (mist: settled, helped); cabin 1.3, furnace 2.7 (no transient);
pine4 41 / 5.5 converged too, but it was a sun flare appearing in a scene without mist -- settling baked it in (the
documented regression), which the accumulating-medium condition excludes. mode "always": the old behaviour.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from looper import loopkit

VERSION = 2  # v2: mode auto (demonstrated transient in a scene with an accumulating medium)
TRANSIENT_MIN = 4.0  # grey; the take_qc pass gate. HYPOTHESIS: 10 takes, no verdict on an auto decision yet


def transient(frames: list) -> dict:
    """Worst-cell change of the first second vs seconds 3-5 (early) and of the last 3-7 s window vs the last 3 s (late)."""
    g = [loopkit.gray(f).astype(np.float32) for f in frames]
    n = len(g)

    def cells(a, b):
        x = np.mean(g[a:b], axis=0)
        h, w = x.shape
        return np.array([x[r * h // 3:(r + 1) * h // 3, c * w // 4:(c + 1) * w // 4].mean() for r in range(3) for c in range(4)])
    return {"early": round(float(np.abs(cells(0, 24) - cells(72, 120)).max()), 2),
            "late": round(float(np.abs(cells(max(0, n - 240), max(1, n - 168)) - cells(n - 72, n)).max()), 2)}


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {video}; config: {frame} (-1 = last) [, mode "auto", accumulating: bool]"""
    frames = loopkit.read_frames(inputs["video"])
    f = frames[config.get("frame", -1)]
    out = out_dir / "settled.png"
    cv2.imwrite(str(out), f)
    meta = {"output": str(out), "source_frame": config.get("frame", -1) % len(frames), "use": True}
    if config.get("mode") == "auto":
        t = transient(frames)
        meta.update(transient=t, use=bool(config.get("accumulating")) and t["early"] > TRANSIENT_MIN)
    return meta
