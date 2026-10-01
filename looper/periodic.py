"""Periodic effects (realism amendment 2026-09-27 §10): phase closure arithmetic and a beam phase track that can be
inspected through the whole loop, joins included. Diagnostics: they show whether a sweep keeps its direction and speed
across the closure; they do not prove it looks real (only review does).

Timing: a loop of T seconds holds whole turns of a period P when T / P is an integer; samples are t in [0, T) -- never
a duplicated t = T frame, which repeats as a pause. Beam track: the image-plane angle of the strongest light on a ring
around the source (static scene removed by the per-angle median), as experiments/beam_probe/measure.py measured every
beam review.
"""
from __future__ import annotations

import math

import numpy as np

from looper import loopkit

FPS = 24


def phase_times(loop_s: float, fps: int = FPS) -> list[float]:
    """Sample times of one loop period: [0, T), no terminal duplicate."""
    return [i / fps for i in range(round(loop_s * fps))]


def turns(loop_s: float, period_s: float, tol_frames: float = 0.5, fps: int = FPS) -> int | None:
    """Whole turns in the loop, or None when the period does not close within tol_frames at the loop's end."""
    k = round(loop_s / period_s)
    return k if k >= 1 and abs(loop_s - k * period_s) * fps <= tol_frames else None


def compatible_duration(periods: list[float], min_s: float = 30.0, max_s: float = 60.0, fps: int = FPS) -> float | None:
    """Shortest loop length in [min_s, max_s] (whole frames) that holds whole turns of every period; None if there is
    none -- then a period must be revisited openly, never silently slowed (amendment §10)."""
    for n in range(math.ceil(min_s * fps), math.floor(max_s * fps) + 1):
        if all(turns(n / fps, p, fps=fps) for p in periods):
            return n / fps
    return None


def source_point(frame: np.ndarray) -> tuple[int, int]:
    """Brightest blurred spot of the upper two thirds (a lantern / work light); (x, y)."""
    import cv2
    g = cv2.GaussianBlur(loopkit.gray(frame).astype(np.float32), (15, 15), 0)
    top = g[: 2 * g.shape[0] // 3]
    y, x = np.unravel_index(int(np.argmax(top)), top.shape)
    return int(x), int(y)


def beam_track(frames: list[np.ndarray], center: tuple[int, int] | None = None, r0: float = 0.05,
               r1: float = 0.27) -> dict:
    """Per frame: the angle (deg, 0 = right, 90 = up) of the strongest light on a ring r0..r1 (fractions of the width)
    around the source, and its strength over the ring's median. Tracked at <= 320 px wide (a 720-frame 1280x704 grey
    stack would be 2.6 GB inside a process already holding the video model); center in full-frame pixels."""
    import cv2
    s = min(1.0, 320 / frames[0].shape[1])
    small = [cv2.resize(f, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else f for f in frames]
    g = np.stack([loopkit.gray(f).astype(np.float32) for f in small])
    h, w = g.shape[1:]
    fx, fy = center or source_point(frames[0])
    cx, cy = int(fx * s), int(fy * s)
    ang = np.deg2rad(np.arange(360))
    radii = np.arange(r0 * w, r1 * w, max(1.0, w / 200))
    xs = np.clip((cx + np.outer(radii, np.cos(ang))).astype(int), 0, w - 1)
    ys = np.clip((cy - np.outer(radii, np.sin(ang))).astype(int), 0, h - 1)
    k = g[:, ys, xs].mean(axis=1)
    k -= np.median(k, axis=0)
    return {"angle": k.argmax(axis=1).astype(float), "strength": k.max(axis=1) - np.median(k, axis=1),
            "center": [int(fx), int(fy)]}


def _steps(angle: np.ndarray) -> np.ndarray:
    """Per-frame angle step, wrapped to (-180, 180], cyclic (the last entry is the wrap frame n-1 -> 0)."""
    return (np.diff(np.append(angle, angle[0])) + 180) % 360 - 180


def phase_report(track: dict, joins: dict[str, int], clear_min: float = 30.0, window: int = 6) -> dict:
    """Loop-wide: net turns, share of clear frames moving the dominant way, jumps (> 45 deg in a frame). Per join
    (frame index where the new material starts): the mean step across the join window vs the loop's median step, and
    whether the direction there matches the dominant one. Frames where the beam is not clear are ignored."""
    a, s = track["angle"], track["strength"]
    n = len(a)
    d = _steps(a)
    clear = (s > clear_min) & (np.roll(s, -1) > clear_min)
    ok = clear & (np.abs(d) <= 45)
    dom = float(np.sign(d[ok].sum())) or 1.0
    med = float(np.median(np.abs(d[ok]))) if ok.any() else 0.0
    out = {"clear": round(float(clear.mean()), 3), "net_turns": round(float(d[ok].sum() / 360), 2),
           "one_way": round(float((np.sign(d[ok]) == dom).mean()), 3) if ok.any() else None,
           "jumps": int((clear & (np.abs(d) > 45)).sum()), "median_step_deg": round(med, 2), "joins": {}}
    for name, at in joins.items():
        idx = [(at + k) % n for k in range(-window, window)]
        sel = [i for i in idx if ok[i]]
        mean = float(np.mean(d[sel])) if sel else None
        out["joins"][name] = {"clear_frames": len(sel), "mean_step_deg": None if mean is None else round(mean, 2),
                              "same_direction": None if mean is None else bool(np.sign(mean) == dom),
                              "speed_ratio": None if mean is None or not med else round(abs(mean) / med, 2),
                              "jumps": int(sum(clear[i] and abs(d[i]) > 45 for i in idx))}
    return out


def doubts(report: dict) -> list[str]:
    """Review DOUBT lines (hypothesis thresholds: a reversal, a jump, or a speed change beyond 2x at a join)."""
    out = []
    for name, j in report["joins"].items():
        if j["same_direction"] is False:
            out.append(f"beam reverses at the {name}")
        if j["jumps"]:
            out.append(f"beam jumps at the {name}")
        if j["speed_ratio"] is not None and not 0.5 <= j["speed_ratio"] <= 2.0:
            out.append(f"beam speed x{j['speed_ratio']} at the {name}")
    return out
