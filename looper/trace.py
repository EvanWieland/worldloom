"""Stage comparison report (handoff 2026-09-27 §8): every video a run's stages produced, measured the same way, so a
defect can be pinned to the stage that introduced it before anyone changes that stage.
  python -m looper trace RUN_ID  ->  runs/<id>/trace/{trace.json, trace.md, sheet.jpg}
Per video: frames, size, mean grey, motion energy (mean |grey step|), sharpness (Laplacian variance), the
brightest-cell emission proxy over time (the cell picked once on the first video, same relative box everywhere), and
motion per 3x4 cell. Generated closure frames are labelled from the splice / loop_qc settings: they have no
frame-for-frame source. Diagnostics only: bright pixels do not prove correct light, more motion is not better motion.
A run without a contract gets a PROVISIONAL one derived from its prompt (no approval implied).
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from looper import contract, loopkit

SKIP = ("upscale", "upscale_join", "deliver4k", "review", "audition")  # 4K: too big to decode here; review = re-encode


def compare(loop: Path, reference: Path) -> dict:
    """Loop vs its own take (handoff §10: frozen motion and missing emission must not pass on drift alone): per 3x4
    cell, loop motion / take motion for the cells that move in the take; emission = the take's brightest cell, loop
    min p99 / take mean p99. Diagnostics with HYPOTHESIS thresholds (no human-calibrated freeze / fade gate exists)."""
    ref = measure_path(reference)
    m = measure_path(loop, ref["box"])
    rc, lc = np.array(ref["motion_by_cell"]), np.array(m["motion_by_cell"])
    moving = rc > np.median(rc)
    ratio = lc[moving] / np.maximum(rc[moving], 1e-6)
    return {"motion_ratio_min": round(float(ratio.min()), 2) if moving.any() else None,
            "motion_ratio_mean": round(float(ratio.mean()), 2) if moving.any() else None,
            "emission_min_over_take": round(m["emission_p99"]["min"] / max(ref["emission_p99"]["mean"], 1e-6), 2)}


FREEZE_MIN, FADE_MIN = 0.5, 0.7  # hypothesis thresholds for review DOUBT lines


def detail_kept(loop: Path, still: Path, grid: tuple[int, int] = (3, 4)) -> dict:
    """Fine detail the video keeps vs the still it was rendered from (research/harvester-drum.md: the 480 drum kept ~1/3
    of the still's Laplacian variance and a reviewer saw it streak and smear). Per 3x4 cell: median over one frame per
    second of the loop's Laplacian variance / the still's, for the textured cells (still variance >= the median cell).
    Diagnostic only: no human-calibrated gate; motion blur and genuine change (smoke) also lower it."""
    fr = [f for i, f in enumerate(stream(loop, None)) if i % 24 == 0]
    h, w = fr[0].shape[:2]
    s = cv2.resize(cv2.imread(str(still)), (w, h), interpolation=cv2.INTER_AREA)
    ch, cw = h // grid[0], w // grid[1]

    def lap(img, r, c):
        return float(cv2.Laplacian(loopkit.gray(img[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw]), cv2.CV_32F).var())

    cells = {f"c{r}{c}": (lap(s, r, c), float(np.median([lap(f, r, c) for f in fr])))
             for r in range(grid[0]) for c in range(grid[1])}
    med = np.median([v[0] for v in cells.values()])
    ratios = {k: round(v[1] / max(v[0], 1e-6), 2) for k, v in cells.items() if v[0] >= med}
    worst = min(ratios, key=ratios.get)
    return {"worst_cell": worst, "worst": ratios[worst], "mean": round(float(np.mean(list(ratios.values()))), 2),
            "cells": ratios}


def camera_drift(path: Path, width: int = 640) -> dict:
    """Handoff §10 static stability over the WHOLE loop (take_qc only compares take start -> end): an ORB similarity
    transform frame 0 -> one frame per second, features only on pixels that stay still over the loop (lowest-variance
    half: water, smoke, a beam cannot pose as camera motion -- an analysis crop, not a generation mask). Shift in
    native pixels; gate = take_qc's 1.5 px (calibrated start -> end on takes)."""
    first, samples, n = None, [], 0
    mean = var = None
    for f in stream(path, width):
        g = loopkit.gray(f).astype(np.float32)
        n += 1
        if first is None:
            first, mean, var = g, g.copy(), np.zeros_like(g)
        else:
            d = g - mean
            mean += d / n
            var += d * (g - mean)
        if n % 24 == 1 and n > 1:
            samples.append((n - 1, g))
    cap = cv2.VideoCapture(str(path))
    scale = cap.get(cv2.CAP_PROP_FRAME_WIDTH) / first.shape[1]
    cap.release()
    std = np.sqrt(var / max(1, n - 1))
    mask = (std <= np.median(std)).astype(np.uint8) * 255
    orb, bf = cv2.ORB_create(3000), cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ka, da = orb.detectAndCompute(first.astype(np.uint8), mask)
    if len(ka) < 100:  # dark or all-moving scene (rain over everything): the full frame, RANSAC rejects movers
        mask = None
        ka, da = orb.detectAndCompute(first.astype(np.uint8), None)
    track = []
    for i, g in samples:
        kb, db = orb.detectAndCompute(g.astype(np.uint8), mask)
        m = bf.match(da, db) if da is not None and db is not None else []
        M = cv2.estimateAffinePartial2D(np.float32([ka[x.queryIdx].pt for x in m]), np.float32([kb[x.trainIdx].pt for x in m]),
                                        method=cv2.RANSAC, ransacReprojThreshold=2)[0] if len(m) >= 8 else None
        track.append({"frame": i, "shift_px": round(float(np.hypot(M[0, 2], M[1, 2])) * scale, 2) if M is not None else None,
                      "zoom_pct": round(abs(float(np.hypot(M[0, 0], M[1, 0])) - 1) * 100, 3) if M is not None else None})
    ok = [t for t in track if t["shift_px"] is not None]
    return {"max_shift_px": max((t["shift_px"] for t in ok), default=None),
            "max_zoom_pct": max((t["zoom_pct"] for t in ok), default=None),
            "worst_at_s": round(max(ok, key=lambda t: t["shift_px"])["frame"] / 24, 1) if ok else None,
            "unmeasured": len(track) - len(ok), "static_mask": mask is not None, "track": track}


def _videos(run_dir: Path) -> list[tuple[str, str, Path, dict]]:
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    out = []
    for key, st in man["stages"].items():
        name = key.split("[")[0]
        sj = run_dir / "stages" / name / st["fingerprint"] / "stage.json"
        if st["status"] != "ok" or name in SKIP or not sj.exists():
            continue
        rec = json.loads(sj.read_text(encoding="utf-8"))
        for field in ("output", "long", "loop"):
            if name == "deliver" and field == "output":
                continue  # final.mp4 = stream-copied repeats of its loop (6 min of frames would not fit in RAM)
            p = rec.get("meta", {}).get(field)
            if isinstance(p, str) and p.endswith(".mp4") and Path(p).exists() and Path(p) not in [v[2] for v in out]:
                out.append((key, field, Path(p), rec))
    return out


def _box(frame: np.ndarray) -> tuple[float, float, float, float]:
    """Brightest 3x4 cell of a frame, as fractions (y, x, h, w)."""
    g = loopkit.gray(frame)
    h, w = g.shape
    cells = [(r / 3, c / 4) for r in range(3) for c in range(4)]
    p99 = [np.percentile(g[int(y * h):int((y + 1 / 3) * h), int(x * w):int((x + 1 / 4) * w)], 99) for y, x in cells]
    y, x = cells[int(np.argmax(p99))]
    return y, x, 1 / 3, 1 / 4


def stream(path: Path, width: int = 320):
    """Frames of a video one at a time, resized to `width` (a 720p take would be 1.3 GB as a list)."""
    cap = cv2.VideoCapture(str(path))
    try:
        while True:
            ok, f = cap.read()
            if not ok:
                return
            s = width / f.shape[1] if width else 1  # None: native size
            yield cv2.resize(f, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else f
    finally:
        cap.release()


def measure_path(path: Path, box=None) -> dict:
    """measure() streamed at 320 px wide; box None = the brightest cell of this video's first frame."""
    frames = stream(path)
    first = next(frames)
    box = box or _box(first)
    return {**measure(_chain(first, frames), box, first.shape[:2]), "box": box}


def _chain(first, rest):
    yield first
    yield from rest


def measure(frames, box, hw: tuple[int, int] | None = None) -> dict:
    """frames: a list or an iterator (then hw = (h, w) of its frames)."""
    frames = iter(frames) if hw else frames
    h, w = hw or frames[0].shape[:2]
    y0, x0, bh, bw = int(box[0] * h), int(box[1] * w), int(box[2] * h), int(box[3] * w)
    emis, greys, acc, prev, sharp, n = [], [], np.zeros((h, w), np.float32), None, [], 0
    for f in frames:  # streamed: a take's grey stack would be ~1.5 GB next to a GPU job's 56 GB
        n += 1
        if n in (1, 120, 240):
            sharp.append(loopkit.laplacian_var(f))
        g = loopkit.gray(f).astype(np.float32)
        emis.append(float(np.percentile(g[y0:y0 + bh, x0:x0 + bw], 99)))
        greys.append(float(g.mean()))
        if prev is not None:
            acc += np.abs(g - prev)
        prev = g
    mean_step = acc / max(1, n - 1)
    cell = [[round(float(mean_step[r * h // 3:(r + 1) * h // 3, c * w // 4:(c + 1) * w // 4].mean()), 3)
             for c in range(4)] for r in range(3)]
    return {"frames": n, "size": [w, h], "seconds": round(n / 24, 2),
            "mean_grey": round(float(np.mean(greys)), 1),
            "motion_energy": round(float(mean_step.mean()), 3),
            "sharpness": round(float(np.mean(sharp)), 1),
            "emission_p99": {"first": round(emis[0], 1), "min": round(min(emis), 1), "mean": round(float(np.mean(emis)), 1),
                             "min_at_frame": int(np.argmin(emis))},
            "motion_by_cell": cell}


def _generated(rec: dict) -> list | None:
    """Generated frame ranges of a video: from the stage's own provenance map (handoff §8), else the splice layout."""
    prov = rec.get("meta", {}).get("provenance")
    if prov:
        return [p["out"] for p in prov if p["kind"] == "generated"] or None
    c = rec.get("config", {})
    gs = rec.get("meta", {}).get("gap_start", c.get("gap_start"))
    return [gs, gs + c["G"]] if gs is not None and "G" in c else None


def report(run_dir: Path) -> str:
    run_dir = Path(run_dir)
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    out = run_dir / "trace"
    out.mkdir(exist_ok=True)
    vids = _videos(run_dir)
    rows, tiles, box = [], [], None
    for key, field, path, rec in vids:
        m = measure_path(path, box)
        box = m.pop("box")
        cap = cv2.VideoCapture(str(path))
        native = [int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))]
        cap.set(cv2.CAP_PROP_POS_FRAMES, m["frames"] // 2)
        ok, mid = cap.read()
        cap.release()
        rows.append({"stage": key, "field": field, "path": str(path), "generated_frames": _generated(rec), **m,
                     "size": native, "measured_at_width": m["size"][0],
                     "provenance": rec.get("meta", {}).get("provenance")})
        if ok:
            t = cv2.resize(mid, (416, int(416 * mid.shape[0] / mid.shape[1])))
            cv2.putText(t, f"{key} {field}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
            tiles.append(cv2.putText(t, f"{key} {field}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1))
    con_dir = [run_dir / "stages" / "contract" / man["stages"][k]["fingerprint"] for k in man["stages"] if k == "contract"]
    con = json.loads((con_dir[0] / "contract.json").read_text(encoding="utf-8"))["contract"] if con_dir else \
        {**contract.derive(man.get("original_prompt", "")), "provisional": True}
    data = {"run_id": man["run_id"], "emission_box_fraction": box, "contract": con, "videos": rows}
    (out / "trace.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    if tiles:
        th = max(t.shape[0] for t in tiles)
        tiles = [np.pad(t, ((0, th - t.shape[0]), (0, 0), (0, 0))) for t in tiles]
        tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % 3)
        cv2.imwrite(str(out / "sheet.jpg"), np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)]),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
    lines = [f"# Trace — {man['run_id']}", "", f"Prompt: {man.get('original_prompt', '')[:400]}", "",
             f"Contract{' (PROVISIONAL, derived now; never approved)' if con.get('provisional') else ''}: " +
             (", ".join(r["id"] for r in con["requirements"]) or "no named elements"), "",
             "| stage | s | size | grey | motion | sharp | emission first/min/mean | generated |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        e = r["emission_p99"]
        lines.append(f"| {r['stage']} {r['field']} | {r['seconds']} | {r['size'][0]}x{r['size'][1]} | {r['mean_grey']} | "
                     f"{r['motion_energy']} | {r['sharpness']} | {e['first']}/{e['min']}/{e['mean']} | "
                     f"{r['generated_frames'] or ''} |")
    lines += ["", "Measured at 320 px wide (motion / sharpness are comparable between rows, not with full-res numbers).",
              "Emission = p99 grey of the first video's brightest 3x4 cell (same relative box in every row).",
              "Motion by cell (3x4, mean |grey step|) is in trace.json."]
    (out / "trace.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out / "trace.md")
