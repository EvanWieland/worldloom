"""Frame-level helpers for the loop stages (ADR 0006/0007): video I/O, deterministic tone/sharpness matching,
the in-overlap splice mix, window layout math, and the step profile used to pick a closure.
Colour domain: 8-bit display-referred BT.709 as decoded by OpenCV, float intermediates, rounded once.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


# ---------- video I/O ----------
def read_frames(path: Path) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    if not out:
        raise RuntimeError(f"no frames read from {path}")
    return out


def write_video(frames, path: Path, fps: int = 24, crf: int = 10, pix_fmt: str = "yuv444p", lossless: bool = False) -> Path:
    """Intermediates 4:4:4 (4:2:0 round trips drift luma -1.66); mbtree=0 (MB-tree starves a file's last frame,
    a codec seam exactly at the loop point). Delivery files pass pix_fmt="yuv420p". lossless (qp 0) for loop masters:
    even 4:4:4 crf 10 raised a loop's wrap step 1.76x -> 2.19x (last P-frame vs first keyframe), and the user saw it.
    keyint=infinite + scenecut=0 (2026-09-26): x264's default keyframe every 250 frames re-codes the grain and made a
    2.1-2.8x whole-frame step at every I-frame of a crf-17/20 file (the master had 1.5x); a reviewer saw a severe shudder
    at ~30 s and the earlier "gear lurch at frames 249/499" was the same pop. One I-frame per file; stream copies of a
    block still start on it."""
    h, w = frames[0].shape[:2]
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", *(["-qp", "0"] if lossless else ["-crf", str(crf)]),
                          "-x264-params", "mbtree=0:keyint=infinite:scenecut=0",
                          "-pix_fmt", pix_fmt, str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg failed writing {path}")
    return Path(path)


def gray(f: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)


# ---------- tone / mix / sharpness ----------
def cdfs(f: np.ndarray) -> list[np.ndarray]:
    return [np.cumsum(np.bincount(f[..., c].ravel(), minlength=256)) / f[..., c].size for c in range(3)]


def tone(f: np.ndarray, target: list[np.ndarray]) -> np.ndarray:
    """Per-channel histogram match of f onto target CDFs (a per-frame LUT; no mixing between frames)."""
    src = cdfs(f)
    return np.stack([np.searchsorted(target[c], src[c]).clip(0, 255).astype(np.uint8)[f[..., c]] for c in range(3)], -1)


def lerp_cdfs(a: list[np.ndarray], b: list[np.ndarray], t: float) -> list[np.ndarray]:
    return [a[c] + (b[c] - a[c]) * t for c in range(3)]


def mix(x: np.ndarray, y: np.ndarray, w: float) -> np.ndarray:
    return np.clip(np.rint((1 - w) * x.astype(np.float32) + w * y.astype(np.float32)), 0, 255).astype(np.uint8)


def laplacian_var(f: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def adjust_sharpness(f: np.ndarray, t: float) -> np.ndarray:
    """t < 0: Gaussian blur of sigma -t; t > 0: unsharp amount t (sigma 1); 0: unchanged."""
    fl = f.astype(np.float32)
    if t < 0:
        return np.clip(np.rint(cv2.GaussianBlur(fl, (0, 0), -t)), 0, 255).astype(np.uint8)
    if t > 0:
        return np.clip(np.rint(fl + t * (fl - cv2.GaussianBlur(fl, (0, 0), 1.0))), 0, 255).astype(np.uint8)
    return f


def match_sharpness(frames: list[np.ndarray], target: float, iters: int = 14) -> tuple[list[np.ndarray], float]:
    """One global setting so the frames' median Laplacian variance equals target (bisection)."""
    cur = float(np.median([laplacian_var(f) for f in frames]))
    sign = -1.0 if cur > target else 1.0
    lo, hi = 0.0, 2.0 if sign < 0 else 3.0
    probe = frames[::3] or frames
    for _ in range(iters):
        mid = (lo + hi) / 2
        v = float(np.median([laplacian_var(adjust_sharpness(f, sign * mid)) for f in probe]))
        lo, hi = (mid, hi) if (v > target if sign < 0 else v < target) else (lo, mid)
    t = sign * (lo + hi) / 2
    return [adjust_sharpness(f, t) for f in frames], t


# ---------- layout ----------
def ctx_frames(latents: int) -> int:
    """Pixel frames covered by the first `latents` latents of an LTX window (1 + 8 (n - 1))."""
    return 8 * (latents - 1) + 1


@dataclass(frozen=True)
class CloseLayout:
    """Closure window (ADR 0007): [end context E | gap G | start context S] = F frames, all 8k+1-aligned."""
    frames: int = 145
    prefix_latents: int = 7
    gap_frames: int = 32

    @property
    def E(self) -> int:
        return ctx_frames(self.prefix_latents)

    @property
    def suffix_latent(self) -> int:
        assert self.gap_frames % 8 == 0
        return self.prefix_latents + self.gap_frames // 8

    @property
    def S(self) -> int:
        return self.frames - self.E - self.gap_frames


def true_first_latent(src_frames: int, from_frame: int) -> int:
    """Index of the source latent whose 8-frame group starts at from_frame (causal first latent = frame 0)."""
    if from_frame == 0 or (from_frame - 1) % 8:
        raise ValueError(f"frame {from_frame} does not open a latent group (needs 8j + 1)")
    if (src_frames - 1) % 8:
        raise ValueError(f"source length {src_frames} is not 8k + 1")
    return (from_frame + 7) // 8


def extension_window(new_frames: int, prefix_latents: int = 7, max_window: int = 497) -> int:
    """Smallest 8k+1 window holding the prefix context plus at least new_frames generated frames."""
    E = ctx_frames(prefix_latents)
    n = E + int(np.ceil(new_frames / 8)) * 8
    if n > max_window:
        raise ValueError(f"extension of {new_frames} frames needs a {n}-frame window (WanGP max {max_window + 4})")
    return n


# ---------- closure metrics ----------
def step_profile(frames: list[np.ndarray], cyclic: bool = True) -> np.ndarray:
    """d[i] = mean |frame i+1 - frame i| (grey), wrapping at the end when cyclic, divided by its median."""
    g = [gray(f) for f in frames]
    n = len(g)
    m = n if cyclic else n - 1
    d = np.array([np.abs(g[(i + 1) % n] - g[i]).mean() for i in range(m)])
    return d / np.median(d)


def closing_score(d: np.ndarray, gap_start: int, margin: int = 6) -> dict:
    """Largest normalised step across the closing gap + both joins vs the largest anywhere else in the loop.
    The acceptance bar (ADR 0006/0007): the closure must not produce a step above the loop's own natural ones."""
    n = len(d)
    idx = list(range(gap_start - margin, n)) + list(range(0, margin))
    inside = d[idx]
    rest = np.delete(d, [i % n for i in idx])
    return {"closing_max": round(float(inside.max()), 3), "closing_mean": round(float(inside.mean()), 3),
            "rest_max": round(float(rest.max()), 3),
            "closing_over_rest": round(float(inside.max() / rest.max()), 3)}


def compensated_residual(frames: list[np.ndarray], grid: tuple[int, int] = (3, 4)) -> np.ndarray:
    """(F, cells): per frame pair, |frame - previous frame warped by Farneback flow| (grey, half resolution) per grid
    cell -- texture turnover that transport does not explain. Row 0 is zeros."""
    R, C = grid
    h, w = frames[0].shape[:2]
    hs, ws = h // 2, w // 2
    yy, xx = np.mgrid[0:hs, 0:ws].astype(np.float32)
    out = np.zeros((len(frames), R * C), np.float32)
    prev = cv2.resize(gray(frames[0]), (ws, hs), interpolation=cv2.INTER_AREA)
    for i in range(1, len(frames)):
        cur = cv2.resize(gray(frames[i]), (ws, hs), interpolation=cv2.INTER_AREA)
        f = cv2.calcOpticalFlowFarneback(cur.astype(np.uint8), prev.astype(np.uint8), None, 0.5, 3, 15, 3, 5, 1.2, 0)
        r = np.abs(cur - cv2.remap(prev, xx + f[..., 0], yy + f[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
        out[i] = [r[a * hs // R:(a + 1) * hs // R, b * ws // C:(b + 1) * ws // C].mean() for a in range(R) for b in range(C)]
        prev = cur
    return out


def gap_churn(window: list[np.ndarray], E: int, G: int) -> dict:
    """Closure-gap texture churn relative to the SAME window's context frames (one decode, so no decode offset):
    mean over cells of residual(gap) / residual(contexts). Calibration (research/scene-perfection-round2.md):
    loops the user passed 0.99-1.29, rated very slight 1.36, rejected furnace closures 1.54-1.62."""
    res = compensated_residual(window)
    ctx = np.concatenate([res[2:E], res[E + G + 2:]]).mean(0)
    ratio = res[E:E + G + 1].mean(0) / np.maximum(ctx, 1e-3)
    return {"gap_churn": round(float(ratio.mean()), 3), "gap_churn_worst_cell": round(float(ratio.max()), 3)}


def loop_drift(frames: list[np.ndarray], grid: tuple[int, int] = (3, 4)) -> dict:
    """Slow drift over a whole loop: per-second mean luma per grid cell, range (max - min) over the loop, worst cell.
    Calibration (research/scene-perfection-round2.md): loops the user passed 2.3-6.5 grey; the 30 s pine loop with the
    passing shadow 10.5."""
    R, C = grid
    h, w = frames[0].shape[:2]
    n = len(frames) // 24 * 24
    cm = np.array([[g[r * h // R:(r + 1) * h // R, c * w // C:(c + 1) * w // C].mean() for r in range(R) for c in range(C)]
                   for g in (gray(f) for f in frames[:n])])
    sec = cm.reshape(-1, 24, R * C).mean(1)
    rng = sec.max(0) - sec.min(0)
    return {"loop_drift": round(float(rng.max()), 2), "loop_drift_cell": f"c{int(rng.argmax()) // C}{int(rng.argmax()) % C}"}


def calmest_segment(frames: list[np.ndarray], min_len: int, max_len: int, first: int = 49,
                    grid: tuple[int, int] = (3, 4)) -> tuple[int, int, float]:
    """For a long return (ADR 0012): the stretch [s, e) of a take (s, e = 8j + 1, first <= s, min_len <= e - s <=
    max_len) with the least slow drift -- max(worst-cell range of per-second means, worst-cell end-vs-start boundary
    of 2 s means). The return only has to undo what the kept stretch drifts. -> (s, e, score)."""
    R, C = grid
    h, w = frames[0].shape[:2]
    cm = np.array([[g[r * h // R:(r + 1) * h // R, c * w // C:(c + 1) * w // C].mean() for r in range(R) for c in range(C)]
                   for g in (gray(f) for f in frames)])
    cs = np.cumsum(np.vstack([np.zeros((1, R * C)), cm]), 0)
    n = len(frames)
    best = None
    for s in range(first + (1 - first) % 8, n, 8):
        for e in range(s + min_len + (-min_len) % 8, min(n, s + max_len) + 1, 8):
            secs = np.array([(cs[a + 24] - cs[a]) / 24 for a in range(s, e - 23, 24)])
            rng = float((secs.max(0) - secs.min(0)).max())
            bnd = float(np.abs((cs[e] - cs[e - 48]) / 48 - (cs[s + 48] - cs[s]) / 48).max())
            if best is None or max(rng, bnd) < best[2]:
                best = (s, e, round(max(rng, bnd), 2))
    if best is None:
        raise ValueError(f"no stretch of {min_len}-{max_len} frames in a {n}-frame take")
    return best
