"""The main person's torso position per frame, from WanGP's DWPose ONNX models (YOLOX person boxes + whole-body
keypoints) on the CPU. QC only -- it measures whether a motion donor's subject travels (ADR 0016); it never steers a
render (no masks). Vendor imports stay inside this module (CLAUDE.md invariant 9).
"""
from __future__ import annotations

import contextlib

import numpy as np

from looper.adapters import wangp

TORSO = [5, 6, 11, 12]  # COCO shoulders + hips: a billowing cloak moves the person's box, not these


def torso_x(frames: list, step: int = 12) -> list:
    """Torso x (pixels) of the largest detected person in every step-th frame; None where nobody / no torso is found.
    ponytail: one subject (the largest box); a crowd would need tracking."""
    wangp.ensure_path()
    import onnxruntime as ort
    from preprocessing.dwpose.assets import query_download_def
    from preprocessing.dwpose.onnxdet import inference_detector
    from preprocessing.dwpose.onnxpose import inference_pose
    from shared.utils.download import process_files_def_if_needed
    with contextlib.chdir(wangp.WANGP_ROOT):  # WanGP resolves ckpts/ against the cwd (a looper-root run re-downloaded)
        process_files_def_if_needed(query_download_def())
    ckpts = wangp.WANGP_ROOT / "ckpts" / "pose"
    det = ort.InferenceSession(str(ckpts / "yolox_l.onnx"), providers=["CPUExecutionProvider"])
    pose = ort.InferenceSession(str(ckpts / "dw-ll_ucoco_384.onnx"), providers=["CPUExecutionProvider"])
    out = []
    for f in frames[::step]:
        boxes = inference_detector(det, f)
        if len(boxes) == 0:
            out.append(None)
            continue
        box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        kp, sc = inference_pose(pose, np.asarray([box]), f)
        p, s = kp[0][TORSO], sc[0][TORSO]
        out.append(float(p[s > 0.3, 0].mean()) if (s > 0.3).sum() >= 2 else None)
    return out
