"""endpoint stage (CPU): when the loop cannot be the full long take (the extension drifted, or none was made), find the
easiest legal (end e, start s) cut instead of the fixed take-only cut (s = 89, e = 481). Plan 2026-09-26 §4.2 rank 1
("mine a loopable interval before extending or discarding"), evidence research/plan-2026-09-26.md: on three of four
drifting runs a searched 17 s cut sits in the pass band (3.7–3.8 grey) where the take-only cut is 5.8–8.5.
Boundary = take_qc v3's measure (worst 3x4 cell, last 2 s before e vs first 2 s from s), so the 4 / 7.5 calibration
applies to the loop this cut will make. Legal: e, s = 8j + 1 (latent groups), s >= 49, s + 64 <= 481 (start context
inside the take), e - 49 inside one source (take, or the extension window past frame 481 + 8).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from looper import loopkit
from looper.stages.close import MIN_START_FRAME
from looper.stages.take_qc import GRID

VERSION = 1
E, S, TAKE = 49, 64, 481


def cell_means(frames: list) -> np.ndarray:
    R, C = GRID
    h, w = frames[0].shape[:2]
    out = np.zeros((len(frames), R * C), np.float32)
    for i, f in enumerate(frames):
        g = loopkit.gray(f)
        out[i] = [g[r * h // R:(r + 1) * h // R, c * w // C:(c + 1) * w // C].mean() for r in range(R) for c in range(C)]
    return out


def rank_pairs(frames: list, min_frames: int, gap: int = 32, ctx: int = 48, take_frames: int = TAKE) -> list[dict]:
    """Every legal (e, s) whose loop (e - s + gap frames) is long enough, sorted by boundary then length."""
    n = len(frames)
    cm = cell_means(frames)
    cs = np.cumsum(np.vstack([np.zeros((1, cm.shape[1]), np.float32), cm]), axis=0)
    mean = lambda a, b: (cs[b] - cs[a]) / (b - a)  # over frames [a, b)
    starts = [s for s in range(MIN_START_FRAME, take_frames - S + 1, 8) if s % 8 == 1]
    ends = [e for e in range(E, n + 1, 8) if e % 8 == 1 and (e <= take_frames or e - (take_frames - E) >= E + 8)]
    rows = []
    for e in ends:
        me = mean(e - ctx, e)
        for s in starts:
            if e - s + gap < min_frames:
                continue
            rows.append({"e": e, "s": s, "loop_frames": e - s + gap, "boundary": round(float(np.abs(me - mean(s, s + ctx)).max()), 2)})
    rows.sort(key=lambda r: (r["boundary"], -r["loop_frames"]))
    return rows


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {long}; config: {min_seconds, gap, start_frame, take_frames}. Writes candidates.json."""
    frames = loopkit.read_frames(inputs["long"])
    rows = rank_pairs(frames, int(config["min_seconds"] * 24), config["gap"], take_frames=config.get("take_frames", TAKE))
    s0 = config["start_frame"]
    take_only = next((r for r in rows if r["s"] == s0 and r["e"] == config.get("take_frames", TAKE)), None)
    best = rows[0] if rows else None
    (Path(out_dir) / "candidates.json").write_text(json.dumps({"best": best, "take_only": take_only, "top": rows[:30]}, indent=1),
                                                   encoding="utf-8")
    return {"best": best, "take_only": take_only, "frames": len(frames), "pairs": len(rows)}
