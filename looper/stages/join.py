"""join stage (CPU): take + extension window -> long.mp4 (the take the loop is cut from).
long = take + window[E:]; the last R take frames ramp toward LTX's render of the same instants (each histogram-matched
to its real twin); the new frames are histogram-matched to the mean CDF of the take's last 8 frames and given one
global sharpness setting matching the take's last 2 s (the waterfall extension came out 12 % sharper and the user saw
the shift at the join). Then take_qc's stationarity gates run on the long take (camera excluded: same camera).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from looper import loopkit
from looper.stages.take_qc import REGION_DRIFT_MAX, stationarity

VERSION = 2  # v2: take_qc v2 gates (trend + pulse) in the meta


def join(take: list, window: list, E: int, R: int = 8, match_sharp: bool = True, tone: bool = True) -> tuple[list, float]:
    """tone False: new frames stay raw (a sweeping beam's own brightness pattern; matching every frame to the take's
    last 8 would pump it -- research/rotating-beam.md used raw windows, reviews 3-4 noticed nothing)."""
    V = list(take)
    n0 = len(V)
    ref = [np.mean([c[i] for c in [loopkit.cdfs(f) for f in V[n0 - 8:]]], axis=0) for i in range(3)]
    new = [loopkit.tone(f, ref) for f in window[E:]] if tone else list(window[E:])
    t = 0.0
    if match_sharp:
        new, t = loopkit.match_sharpness(new, float(np.median([loopkit.laplacian_var(f) for f in V[n0 - 48:]])))
    for k in range(R):
        V[n0 - 1 - k] = loopkit.mix(V[n0 - 1 - k], loopkit.tone(window[E - 1 - k], loopkit.cdfs(V[n0 - 1 - k])),
                                    (R - k) / (R + 1))
    return V + new, t


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {take, window}; config: {E, R, start_frame}"""
    take = loopkit.read_frames(inputs["take"])
    long, t = join(take, loopkit.read_frames(inputs["window"]), config["E"], config.get("R", 8),
                   tone=config.get("tone", "cdf") == "cdf")
    loopkit.write_video(long, out_dir / "long.mp4", lossless=True)
    st = stationarity(long, skip=config["start_frame"], camera=False,
                     region_max=config.get("region_drift_max", REGION_DRIFT_MAX), average_s=config.get("average_s", 1))
    n0, E, R = len(take), config["E"], config.get("R", 8)
    prov = [{"out": [0, n0 - R], "kind": "source", "from": "take", "src": [0, n0 - R]},  # handoff §8
            {"out": [n0 - R, n0], "kind": "ramp", "from": "take", "src": [n0 - R, n0], "window": [E - R, E]},
            {"out": [n0, len(long)], "kind": "generated", "from": "window", "src": [E, E + len(long) - n0]}]
    return {"long": str(out_dir / "long.mp4"), "splice": len(take), "frames_long": len(long), "sharpness_setting": round(t, 3),
            "provenance": prov, **st}
