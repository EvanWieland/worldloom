"""grow stage (ADR 0011): an accepted loop that came out short is grown from the inside. The loop's closure stays;
one interior 32-frame passage (e -> e + 32 of the long take) is replaced by a G-frame two-sided bridge rendered by
the close stage (end context = the 49 frames before e, start context = the 64 frames from e + 32, true latents).
This module: plan() picks (e, G) and the sources; run() rotates the accepted loop so the cut sits at the wrap
(CPU, lossless). The pipeline then runs close -> splice -> loop_qc on it and rolls back if loop_qc fails.
Frame bookkeeping: loop frame i = long frame start_frame + i for i < seg_end - start_frame; long frame f >= take_frames
lives in the extension window at f - (take_frames - E) (join: long = take + window[E:]).
"""
from __future__ import annotations

import math
from pathlib import Path

from looper import loopkit

VERSION = 1
MAX_GAP = 368  # one LTX window: WanGP splits clips > 481 f (sliding_window_size) -- 49 + G + 64 <= 481
MIN_START = 49  # close.MIN_START_FRAME (a start context inside the I2V settling snaps)


def plan(loop_frames: int, target_frames: int, start_frame: int, seg_end: int, take_frames: int, has_ext: bool,
         E: int = 49, S: int = 64, R: int = 8) -> dict | None:
    """-> {e, s, G, end: ("take"|"ext", local end frame), start: ("take"|"ext", local start frame)} or None when the loop
    is already long enough (< 1 s short) or no interior cut fits. The cut nearest the segment's middle wins."""
    missing = target_frames - loop_frames
    if missing < 24:
        return None
    G = min(MAX_GAP, 32 + 8 * math.ceil(missing / 8))
    off = take_frames - E  # long frame f >= take_frames = extension window frame f - off
    mid = (start_frame + seg_end) / 2
    best = None
    for e in range(start_frame + E + R, seg_end - 32 - S - R + 1):
        if e % 8 != 1:
            continue
        s = e + 32
        if e <= take_frames:
            end = ("take", e)
        elif has_ext and e - off >= E + 8:  # the end context lies in the window's own generated frames
            end = ("ext", e - off)
        else:
            continue
        if s + S <= take_frames and s >= MIN_START:
            start = ("take", s)
        elif has_ext and s - off >= MIN_START and s >= take_frames:
            start = ("ext", s - off)
        else:
            continue
        if best is None or abs(e - mid) < abs(best["e"] - mid):
            best = {"e": e, "s": s, "G": G, "end": end, "start": start}
    return best


def rotate(loop: list, start_frame: int, e: int, s: int) -> list:
    """The accepted loop from the cut's start context round through the old closure to the cut's end."""
    return loop[s - start_frame:] + loop[:e - start_frame]


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {loop}; config: {start_frame, e, s, old_gap}"""
    loop = loopkit.read_frames(inputs["loop"])
    rot = rotate(loop, config["start_frame"], config["e"], config["s"])
    loopkit.write_video(rot, out_dir / "rotated.mp4", lossless=True)
    a, b = config["s"] - config["start_frame"], config["e"] - config["start_frame"]
    return {"output": str(out_dir / "rotated.mp4"), "frames": len(rot),
            "old_closure_at": len(loop) - config.get("old_gap", 32) - (config["s"] - config["start_frame"]),
            "provenance": [{"out": [0, len(loop) - a], "kind": "source", "from": "loop", "src": [a, len(loop)]},
                           {"out": [len(loop) - a, len(rot)], "kind": "source", "from": "loop", "src": [0, b]}]}
