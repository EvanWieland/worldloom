"""audition stage (CPU; handoff 2026-09-27 §7): the accepted-by-QC take -> a packet a human judges for CONTENT before
any closure / growth / 4K is spent on it:
  audition.mp4   the take at native resolution and real playback speed (24 fps)
  crops.jpg      three automatic detail boxes (brightest, most moving, least moving 3x4 cell) at 4 moments, native pixels
  framing.jpg    frame 0 with the 4K 16:9 cover-crop drawn in (what the delivery keeps)
  audition.md    original vs effective prompt, the contract checklist, recipe, seed, timing / memory, gates
Analysis boxes are plain grid cells (no segmentation); they point the eye, they prove nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from looper import loopkit

VERSION = 1


def cells(frames: list[np.ndarray], grid=(3, 4)) -> dict:
    """Grid-cell picks: brightest (p99 grey of frame 0), most / least moving (mean |step| over the clip)."""
    g0 = loopkit.gray(frames[0])
    h, w = g0.shape
    rs, cs = h // grid[0], w // grid[1]
    boxes = [(r * rs, c * cs, rs, cs) for r in range(grid[0]) for c in range(grid[1])]
    step = np.mean([np.abs(loopkit.gray(frames[i + 4]) - loopkit.gray(frames[i])) for i in range(0, len(frames) - 4, 8)], axis=0)
    bright = [float(np.percentile(g0[y:y + a, x:x + b], 99)) for y, x, a, b in boxes]
    motion = [float(step[y:y + a, x:x + b].mean()) for y, x, a, b in boxes]
    return {"brightest": boxes[int(np.argmax(bright))], "most moving": boxes[int(np.argmax(motion))],
            "least moving": boxes[int(np.argmin(motion))], "motion_by_cell": [round(m, 3) for m in motion]}


def crop_sheet(frames: list[np.ndarray], picks: dict, out: Path) -> Path:
    n = len(frames)
    rows = []
    for name in ("brightest", "most moving", "least moving"):
        y, x, a, b = picks[name]
        tiles = []
        for t in (0, n // 3, 2 * n // 3, n - 1):
            tile = frames[t][y:y + a, x:x + b].copy()
            cv2.putText(tile, f"{name} f{t}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 4)
            tiles.append(cv2.putText(tile, f"{name} f{t}", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1))
        rows.append(np.hstack(tiles))
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return out


def framing(frame: np.ndarray, out: Path, target=(3840, 2160)) -> str:
    """The delivery framing (handoff §15): the 4K stage cover-crops to 16:9; draw what survives and say how much goes."""
    h, w = frame.shape[:2]
    s = max(target[0] / w, target[1] / h)
    vw, vh = round(target[0] / s), round(target[1] / s)
    x0, y0 = (w - vw) // 2, (h - vh) // 2
    img = frame.copy()
    cv2.rectangle(img, (x0, y0), (x0 + vw - 1, y0 + vh - 1), (0, 255, 255), 2)
    cut = f"4K 16:9 cover-crop keeps {vw}x{vh} of {w}x{h}: {100 * (1 - vw / w):.1f} % of the width, " \
          f"{100 * (1 - vh / h):.1f} % of the height cut"
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return cut


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {video, settings}; config: {title, original_prompt, prompt, negative, checklist, seed, gates, timing,
    resume}"""
    out_dir = Path(out_dir)
    frames = loopkit.read_frames(inputs["video"])
    mp4 = loopkit.write_video(frames, out_dir / "audition.mp4", crf=18, pix_fmt="yuv420p")
    picks = cells(frames)
    crop_sheet(frames, picks, out_dir / "crops.jpg")
    cut = framing(frames[0], out_dir / "framing.jpg")
    recipe = json.loads(Path(inputs["settings"]).read_text(encoding="utf-8"))
    h, w = frames[0].shape[:2]
    lines = [f"# Audition — {config['title']} (take, {len(frames) / 24:.1f} s at {w}x{h}, 24 fps)", "",
             "Look at: does the scene keep everything you asked for, and does every moving part move believably at "
             "real speed (water, light, particles)? Joins do not exist yet -- this is content only.", "",
             "One question: accept this take for the loop?", "", "![crops](crops.jpg)", "",
             f"Framing: ![framing](framing.jpg) {cut}", "",
             "## Required content (from your words)", "", *(config.get("checklist") or ["- (no named elements found)"]), "",
             "## Prompt", "", f"**Your prompt:** {config['original_prompt']}", "",
             f"**Effective motion prompt:** {config['prompt']}", "", f"**Negative:** {config['negative']}", "",
             "## Recipe", "", "| setting | value |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in recipe.items() if k not in ("prompt", "negative_prompt")]
    lines += [f"| seed | {config['seed']} |", *[f"| {k} | {v} |" for k, v in config.get("timing", {}).items()],
              *[f"| {k} | {v} |" for k, v in config.get("gates", {}).items()], "",
              "## Decide", "", f"- accept: `<WanGP python> -m looper accept {config['run_id']} take`",
              f"- reject: `<WanGP python> -m looper accept {config['run_id']} take --reject --note \"why\"`",
              f"- then resume: `{config['resume']}`"]
    md = out_dir / "audition.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(md), "video": str(mp4), "crops": str(out_dir / "crops.jpg"), "framing": cut,
            "picks": {k: v for k, v in picks.items()}, "size_mb": round(mp4.stat().st_size / 2**20, 1)}
