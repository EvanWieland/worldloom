"""review stage (CPU): the finished loop -> a packet a reviewer can judge without anyone building it by hand
(2026-09-26: the pipeline should run unattended):
  review.mp4       the loop played twice, 4:2:0, small enough to send
  joins.jpg        contact sheet: frames around every join (closure gap start, extension join, the wrap)
  review.md        title, what to look at (join timestamps), metrics, warnings, a pass / doubt line
Replaces experiments/qc_tools/loopcheck.py's manual step for the normal case.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from looper import loopkit

VERSION = 4  # v4: detail kept vs the still (research/harvester-drum.md). v3: the scene contract's checklist (content is judged separately from joins); a missing element = DOUBT.
# v2: keyint=infinite encode; the encoded file's own worst step is measured (the master's was clean while
# the crf-20 file popped 2.8x at every I-frame and the user saw it)


def _tile(frame: np.ndarray, label: str) -> np.ndarray:
    t = cv2.resize(frame, (416, 240))
    cv2.putText(t, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 5)  # outline: readable over bright mist
    return cv2.putText(t, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {loop [, reference: the take]}; config: {joins: {name: loop frame}, metrics: {...}, warnings: [...], crf}"""
    loop = loopkit.read_frames(inputs["loop"])
    n = len(loop)
    out_dir = Path(out_dir)
    mp4 = out_dir / "review.mp4"
    loopkit.write_video(loop * 2, mp4, crf=config.get("crf", 20), pix_fmt="yuv420p")
    joins = dict(config["joins"])
    joins["wrap"] = n  # frame n-1 -> 0
    rows = []
    for name, at in joins.items():
        rows.append(np.hstack([_tile(loop[(at + k) % n], f"{name} {(at + k) % n}") for k in (-2, -1, 0, 1)]))
    sheet = out_dir / "joins.jpg"
    cv2.imwrite(str(sheet), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])
    d = loopkit.step_profile(loop)
    steps = {name: round(float(d[(at - 1) % n]), 2) for name, at in joins.items()}
    worst_other = round(float(max(d[i] for i in range(n) if (i + 1) not in joins.values() and (i + 1) % n)), 2)
    metrics = {}  # a metric may be (value, gate): over the gate -> shown and a DOUBT
    doubt = list(config.get("warnings", []))
    for k, v in config.get("metrics", {}).items():
        if isinstance(v, (list, tuple)):
            value, gate = v
            metrics[k] = f"{value} (gate {gate})"
            if value > gate:
                doubt.append(f"{k} {value} > {gate}")
        else:
            metrics[k] = v
    doubt += [f"{k} step {v}x" for k, v in steps.items() if v > 1.8]
    from looper import trace
    cam = trace.camera_drift(inputs["loop"])  # handoff §10: static geometry over the whole loop, not just take ends
    metrics["camera over the loop (max px / zoom %)"] = f"{cam['max_shift_px']} / {cam['max_zoom_pct']}" + \
        (f" at {cam['worst_at_s']} s" if cam["worst_at_s"] is not None else "")
    if (cam["max_shift_px"] or 0) > 1.5 or (cam["max_zoom_pct"] or 0) > 0.5:
        doubt.append(f"the camera / geometry moves {cam['max_shift_px']} px, {cam['max_zoom_pct']} % zoom "
                     f"(worst at {cam['worst_at_s']} s)")
    content = None
    if inputs.get("reference"):  # handoff §10: content diagnostics vs the take, separate from the join metrics
        content = trace.compare(inputs["loop"], inputs["reference"])
        metrics["moving regions: loop motion / take motion (min, mean)"] = \
            f"{content['motion_ratio_min']}, {content['motion_ratio_mean']}"
        metrics["brightest light: loop min / take mean"] = content["emission_min_over_take"]
        if content["motion_ratio_min"] is not None and content["motion_ratio_min"] < trace.FREEZE_MIN:
            doubt.append(f"a moving region nearly stops in the loop (x{content['motion_ratio_min']} of the take)")
        if content["emission_min_over_take"] < trace.FADE_MIN:
            doubt.append(f"the brightest light dims to x{content['emission_min_over_take']} of the take")
    if inputs.get("still"):  # fine detail kept vs the still the take rendered from (diagnostic, uncalibrated)
        dk = trace.detail_kept(inputs["loop"], inputs["still"])
        metrics["detail kept vs the still (worst textured cell / mean)"] = f"{dk['worst']} ({dk['worst_cell']}) / {dk['mean']}"
    beam = None
    if config.get("periodic"):  # a declared moving light: its phase through every join (realism amendment §10)
        from looper import periodic
        beam = periodic.phase_report(periodic.beam_track(loop), joins)
        metrics["beam (net turns / one-way share / jumps)"] = f"{beam['net_turns']} / {beam['one_way']} / {beam['jumps']}"
        for name, j in beam["joins"].items():
            metrics[f"beam at {name} (step deg, x median)"] = f"{j['mean_step_deg']} ({j['speed_ratio']})"
        doubt += periodic.doubts(beam)
    enc = loopkit.step_profile(loopkit.read_frames(mp4), cyclic=False)  # the file the user watches, not the master
    enc_worst = int(np.argmax(enc))
    enc_step = round(float(enc[enc_worst]), 2)
    metrics["review encode worst step"] = f"{enc_step}x at {(enc_worst + 1) / 24:.1f} s (master {worst_other}x)"
    if enc_step > 1.8:
        doubt.append(f"review encode step {enc_step}x at {(enc_worst + 1) / 24:.1f} s")
    secs = n / 24
    lines = [f"# Review — {config.get('title', 'loop')} ({secs:.1f} s loop, played twice)", "",
             "## Look at", ""]
    for name, at in joins.items():
        t = (at % n) / 24
        lines.append(f"- **{name}** at {t:.1f} s and {t + secs:.1f} s" + (" (end of the video)" if name == "wrap" else ""))
    if config.get("contract_status") == "missing":
        doubt.append("a required element is missing from the plan (see Required content): best effort at most")
    lines += ["", "One question: is any join visible, and does anything drift over the minute?", ""]
    if config.get("checklist"):
        lines += ["## Required content (a separate check: joins passing says nothing about these)", "",
                  *config["checklist"], ""]
    lines += ["## Metrics", "", "| check | value |", "|---|---|"]
    for k, v in metrics.items():
        lines.append(f"| {k} | {v} |")
    lines += [f"| join step ({k}) | {v}x of median (loop's worst elsewhere {worst_other}x) |" for k, v in steps.items()]
    lines += ["", "## Verdict", "", ("**PASS (self-QC)** — send as is." if not doubt else
                                     "**DOUBT** — " + "; ".join(doubt))]
    md = out_dir / "review.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(md), "video": str(mp4), "sheet": str(sheet), "joins": joins, "join_steps": steps,
            "worst_other_step": worst_other, "doubt": doubt, "size_mb": round(mp4.stat().st_size / 2**20, 1),
            "beam": beam, "content": content, "camera": {k: v for k, v in cam.items() if k != "track"}}
