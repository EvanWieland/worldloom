"""take_qc stage (CPU): is a take (or a take + extension) stationary enough to loop? A loop must return to its start
state, so any slow trend becomes a visible reset at the loop point.
  global: per-second mean luma range / mean (after the first 2 s)       <= 8 %
  regional trend: rise of a line fitted through the per-second means of each 3x4 cell   <= 4 grey levels
  regional pulse: peak-to-peak of those means after removing that line                  <= 12 grey levels
  camera: ORB similarity transform start -> end                          <= 1.5 px shift, <= 0.5 % zoom
Regional gate added 2026-09-25: the waterfall take passed the global gate (+3.7 %) while foliage / side-fall cells
drifted 11-14 grey (29 with the extension) and a reviewer saw the scene shift at each phase; the user-passed rain
take's worst cell moved 1.7 grey (1.9 with its extension). Separate from `take` so gates can change without
regenerating.
v2 (2026-09-26, review: glow and pulse must pass): the cell gate was the per-second range, which rejected a breathing
fireplace (cabin take: range 7.0, trend 0.9). Trend = range on every take the user judged (rain 1.7/1.7, furnace
2.2/1.6, neon 1.1/0.9, pine7 10.7/10.5), so the 4 / 7.5 calibration carries over. The pulse cap keeps one-off events
out (pine4 sun flare: trend 4.3, pulse 59). Sub-second flicker (candles, embers) never counted: seconds are averaged.
v3 (2026-09-27, research/gate-replay.md): the cell gate is the BOUNDARY, |mean of the last 2 s - mean of the first
2 s|: what the generated closure must bridge, and phase-invariant (a fitted trend swings 0-7.3 grey with the phase of
one 4-grey sinusoid). Boundary = trend within 1-2 grey on every cached take, so the calibration is unchanged; trend
stays in the meta. Also split: `common_range` (median cell change = global exposure) vs `resid_max` (the worst cell
after removing it = a shadow / flare): pine7's passing shadow is residual 8.5 over common 1.4-2.5, the rejected
lighthouse take was common 34 (true exposure pumping). Diagnostic only; the gate stays on the worst cell.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from looper import loopkit

VERSION = 4
# v4 (2026-09-28, research/leviathan.md): with a declared moving light (average_s > 1) the cell boundary is taken on the
# FLOOR of each window (10th percentile of the frame means), not its mean: pulsing emitters / lightning are brief rises
# above a steady floor, and a trough at the wrap is fine. Leviathan: pulsing take 9.95 (mean) -> 3.23 (floor) passes;
# a real start transient (settle take, 12.7 -> 9.0) and a storm-then-calm regime change (20.8 -> 14.5) still fail.
FLOOR_PCT = 10
LUMA_DRIFT_MAX = 0.08
REGION_DRIFT_MAX = 4.0
REGION_PULSE_MAX = 12.0  # ponytail: hypothesis; fireplace breathes 7, dappled pine 8-10, sun flares 15-59. Tune on verdicts.
CAMERA_SHIFT_MAX_PX = 1.5
GRID = (3, 4)


def trend_pulse(v: list) -> tuple[float, float]:
    """(trend, pulse) of a per-second series: the fitted line's rise over the series, and what is left after removing it."""
    if len(v) < 2:
        return 0.0, 0.0
    x = np.arange(len(v))
    a, b = np.polyfit(x, v, 1)
    return float(abs(a) * (len(v) - 1)), float(np.ptp(np.asarray(v) - (a * x + b)))


def boundary(v: list) -> float:
    """|mean of the last 2 s - mean of the first 2 s| of a per-second series: the loop's end-to-start mismatch."""
    v = np.asarray(v, dtype=float)
    return float(abs(v[-2:].mean() - v[:2].mean())) if len(v) >= 2 else 0.0


def stationarity(frames: list, skip: int = 48, camera: bool = True, region_max: float = REGION_DRIFT_MAX,
                 average_s: int = 1) -> dict:
    """average_s > 1: every per-second value is the mean of the next average_s seconds (sliding by 1 s), so a declared
    periodic light (a beam turning every few seconds) averages out instead of reading as drift or pulse. 1 = v3 exactly.
    HYPOTHESIS: 5 s is not calibrated against human verdicts; an unguided beam's period wanders (rotating-beam.md v7a)."""
    g = [loopkit.gray(f) for f in frames]
    L = 24 * average_s
    secs = range(skip, len(g) - L + 1, 24)
    fm = np.array([x.mean() for x in g])
    per_s = [float(np.percentile(fm[s:s + L], FLOOR_PCT) if average_s > 1 else fm[s:s + L].mean()) for s in secs]
    drift = (max(per_s) - min(per_s)) / float(np.mean(per_s)) if per_s else 0.0
    h, w = g[0].shape
    R, C = GRID
    cells, pulses, trends, series, mean_bound = {}, {}, {}, [], {}
    for r in range(R):
        for c in range(C):
            ys, xs = slice(r * h // R, (r + 1) * h // R), slice(c * w // C, (c + 1) * w // C)
            m = np.array([x[ys, xs].mean() for x in g])
            v = [float(m[s:s + L].mean()) for s in secs]
            t, p = trend_pulse(v)
            k = f"c{r}{c}"
            cells[k], pulses[k], trends[k] = round(boundary(v), 2), round(p, 2), round(t, 2)
            if average_s > 1:  # v4: moving light -- pulses / flashes rise above a floor; only the floor must return
                mean_bound[k] = cells[k]
                cells[k] = round(boundary([float(np.percentile(m[s:s + L], FLOOR_PCT)) for s in secs]), 2)
            series.append(v)
    worst = max(cells, key=cells.get)
    worst_p = max(pulses, key=pulses.get)
    S = np.asarray(series, dtype=float).T if series[0] else np.zeros((1, R * C))  # (seconds, cells)
    d = S - S[:1]  # change from the first second
    common = np.median(d, axis=1)
    resid = np.abs(d - common[:, None])
    out = {"luma_per_s": [round(x, 2) for x in per_s], "luma_drift": round(drift, 4), "region_drift": cells,
           "region_drift_max": cells[worst], "region_drift_worst": worst,
           "region_pulse": pulses, "region_pulse_max": pulses[worst_p], "region_pulse_worst": worst_p,
           "region_trend": trends, "common_range": round(float(np.ptp(common)), 2),
           "resid_max": round(float(resid.max()), 2), "resid_cell": list(cells)[int(np.unravel_index(resid.argmax(), resid.shape)[1])],
           **({"region_drift_mean_boundary": mean_bound} if mean_bound else {})}
    ok = drift <= LUMA_DRIFT_MAX and cells[worst] <= region_max and pulses[worst_p] <= REGION_PULSE_MAX
    if camera:
        orb, bf = cv2.ORB_create(3000), cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        a, b = g[skip].astype(np.uint8), g[-1].astype(np.uint8)
        ka, da = orb.detectAndCompute(a, None)
        kb, db = orb.detectAndCompute(b, None)
        m = bf.match(da, db)
        M, _ = cv2.estimateAffinePartial2D(np.float32([ka[x.queryIdx].pt for x in m]), np.float32([kb[x.trainIdx].pt for x in m]),
                                           method=cv2.RANSAC, ransacReprojThreshold=2)
        shift = float(np.hypot(M[0, 2], M[1, 2])) if M is not None else float("inf")
        zoom = abs(float(np.hypot(M[0, 0], M[1, 0])) - 1) * 100 if M is not None else float("inf")
        out.update(camera_shift_px=round(shift, 2), zoom_pct=round(zoom, 3))
        ok = ok and shift <= CAMERA_SHIFT_MAX_PX and zoom <= 0.5
    out["accept"] = bool(ok)
    return out


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {video}; config: {skip, region_drift_max}"""
    return stationarity(loopkit.read_frames(inputs["video"]), config.get("skip", 48),
                        region_max=config.get("region_drift_max", REGION_DRIFT_MAX), average_s=config.get("average_s", 1))
