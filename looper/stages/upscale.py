"""T3a local 4K (PLAN.md D1): the approved 832x480 loop -> FlashVSR x4 (3328x1920, measured to recover real detail,
research/local-video-baseline.md E5) -> cover-scale + centre crop to 3840x2160 -> HEVC delivery.

Chunks are CIRCULAR: each chunk is upscaled with `margin` frames of real neighbours on both sides (the first chunk
gets the loop's last frames), and only its own frames are kept. So every chunk boundary -- including the loop point --
sees the same temporal context as the inside of a chunk; the loop point is not a special case. One fingerprinted
stage per chunk (~13 s/frame on the 6 GB card): a crash mid-upscale resumes at the next chunk (invariant 3).
Frames never all sit in RAM at 4K (a 4-period 4K block would be ~70 GB): join and delivery stream through ffmpeg.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from looper import loopkit
from looper.adapters import wangp
from looper.ffmpeg_utils import run_ffmpeg

VERSION = 1
MIN_CHUNK_FRACTION = 0.5  # a last chunk shorter than this is merged into the previous one


def layout(n: int, chunk: int) -> list[tuple[int, int]]:
    spans = [(s, min(s + chunk, n)) for s in range(0, n, chunk)]
    if len(spans) > 1 and spans[-1][1] - spans[-1][0] < chunk * MIN_CHUNK_FRACTION:
        spans[-2:] = [(spans[-2][0], n)]
    return spans


def source_indices(n: int, start: int, end: int, margin: int) -> list[int]:
    return [i % n for i in range(start - margin, end + margin)]


def _frames(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return int(out.stdout.strip())


def _fit(w: int, h: int) -> str:
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2:flags=lanczos,"
            f"crop={w}:{h}")


def run_chunk(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """inputs: {loop}; config: {start, end, margin, size: [w, h], model}"""
    s, e, m = config["start"], config["end"], config["margin"]
    frames = loopkit.read_frames(inputs["loop"])
    idx = source_indices(len(frames), s, e, m)
    src = loopkit.write_video([frames[i] for i in idx], Path(out_dir) / "src.mp4", crf=8, pix_fmt="yuv420p")
    up = wangp.postprocess(src, out_dir, "up.mp4", scratch_dir=scratch_dir, spatial_upsampling=config["model"])
    got = _frames(Path(up["output"]))
    if got != len(idx):
        raise RuntimeError(f"upscaler returned {got} frames for {len(idx)}: circular trimming would misalign")
    w, h = config["size"]
    out = Path(out_dir) / "chunk.mp4"
    run_ffmpeg(["-i", up["output"], "-vf", f"trim=start_frame={m}:end_frame={m + e - s},setpts=N/24/TB,{_fit(w, h)}",
                "-r", "24", "-c:v", "libx264", "-crf", "10", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-x264-params", "mbtree=0", str(out)])
    return {"output": str(out), "frames": _frames(out), "source_frames": len(idx), "upscaled": up["output"]}


JOIN_VERSION = 2  # v2: ramp between neighbouring runs; v1 butt-joined chunks and stepped ~10x median (dir_neon)
DELIVER_VERSION = 3  # v3: chunk-join steps + accept. v2: nvenc -maxrate (v1 was silently capped at ~20 Mbps)


def _fit_frame(f, w: int, h: int):
    import cv2
    s = max(w / f.shape[1], h / f.shape[0])
    f = cv2.resize(f, (round(f.shape[1] * s), round(f.shape[0] * s)), interpolation=cv2.INTER_LANCZOS4)
    y, x = (f.shape[0] - h) // 2, (f.shape[1] - w) // 2
    return f[y:y + h, x:x + w]


def _frames_of(path: Path, first: int, count: int, w: int, h: int):
    """Yield frames [first, first + count) of a video, fitted to w x h, one at a time (a 4K chunk held whole is
    ~3.6 GB -- next to an LTX take at 56-59 GB of the 64)."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        for _ in range(first):  # decode + discard: CAP_PROP_POS_FRAMES seeking is inexact on H.264
            if not cap.grab():
                raise RuntimeError(f"{path}: fewer than {first} frames")
        for k in range(count):
            ok, f = cap.read()
            if not ok:
                raise RuntimeError(f"{path}: frame {first + k} missing")
            yield _fit_frame(f, w, h)
    finally:
        cap.release()


def run_join(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {c0, c1, ...} FlashVSR outputs (with their `margin` context frames) in loop order;
    config: {n, spans, margin, ramp, size}. Each run invents fine texture differently, so butt-joined chunks popped
    ~10x the median step at every join and at the loop point (dir_neon, 2026-09-26). Frames [s_i, s_i + ramp) ramp
    from run i-1 to run i: both are renders of the SAME source instant (the ADR 0006 exception: a ramp between two
    renders of one instant inside the context overlap), circular at the loop point (run 0 ramps in from the last run).
    Streams through an ffmpeg pipe: ~ramp frames in RAM at a time."""
    n, spans, m, r = config["n"], [tuple(s) for s in config["spans"]], config["margin"], config["ramp"]
    w, h = config["size"]
    if r > m:
        raise ValueError(f"ramp {r} needs at least {r} context frames per side (margin {m})")
    ups = [Path(inputs[f"c{i}"]) for i in range(len(spans))]
    period = Path(out_dir) / "period_4k.mp4"
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "10", "-preset", "medium",
                            "-pix_fmt", "yuv420p", "-x264-params", "mbtree=0", str(period)], stdin=subprocess.PIPE)
    try:
        for i, (s, e) in enumerate(spans):
            ps, pe = spans[i - 1]  # i = 0 -> the last chunk: its after-margin covers loop frames n .. n + m - 1
            prev = list(_frames_of(ups[i - 1], (pe - ps) + m, r, w, h))  # run i-1's render of frames s .. s + r - 1
            for k, f in enumerate(_frames_of(ups[i], m, e - s, w, h)):
                if k < r:
                    f = loopkit.mix(prev[k], f, (k + 1) / (r + 1))
                enc.stdin.write(f.tobytes())
    finally:
        enc.stdin.close()
        if enc.wait():
            raise RuntimeError("ffmpeg failed writing the joined period")
    got = _frames(period)
    if got != n:
        raise RuntimeError(f"joined period has {got} frames, loop has {n}")
    return {"output": str(period), "frames": got, "ramp": r}


def _encode(src_args: list[str], dst: Path, codec: str, cq: int) -> None:
    # nvenc: without -maxrate, -cq is silently capped at ~20 Mbps (cq 17 came out 20.4 Mbps; uncapped 75). dir_neon
    # 5 s, SSIM dB vs the master: capped 16.2, cq21 18.6 (45 Mbps), cq19 19.3 (58), cq17 20.0 (75).
    q = (["-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-maxrate", "120M", "-bufsize", "240M", "-preset", "p6"]
         if codec.endswith("nvenc") else ["-crf", str(cq)])
    run_ffmpeg([*src_args, "-an", "-c:v", codec, *q, "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-r", "24", str(dst)])


def run_deliver4k(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {period}; config: {repeats, block_periods, cq, codec}. Same shape as deliver.py: one continuous
    multi-period block (internal loop points are ordinary frames), final = N x stream copy of the block."""
    period, out_dir = Path(inputs["period"]), Path(out_dir)
    codec, cq, bp = config.get("codec", "hevc_nvenc"), config.get("cq", 20), config["block_periods"]
    block, one, final = out_dir / "block_4k.mp4", out_dir / "loop_4k.mp4", out_dir / "final_4k.mp4"
    _encode(["-stream_loop", str(bp - 1), "-i", str(period)], block, codec, cq)
    _encode(["-i", str(period)], one, codec, cq)
    run_ffmpeg(["-stream_loop", str(config["repeats"] - 1), "-i", str(block), "-c", "copy", "-movflags", "+faststart",
                str(final)])
    proxy = out_dir / "proxy_qc.mp4"  # seam QC on a small proxy: 4K frames of a whole block do not fit in RAM
    run_ffmpeg(["-i", str(block), "-vf", "scale=416:-2:flags=area", "-c:v", "libx264", "-qp", "0", str(proxy)])
    d = loopkit.step_profile(loopkit.read_frames(proxy))
    n = _frames(period)
    # chunk joins (final review #5: the v1 pop at ~10x median was only found by hand): step from the frame before
    # each chunk start, first period; accepted when no join / wrap steps above the loop's own natural steps
    starts = [s for s, _ in config.get("spans") or [] if s > 0]
    joins = [[s - 1, round(float(d[s - 1]), 2)] for s in starts]  # lists: a cached result comes back from JSON
    seams = {s - 1 for s in starts} | {k * n - 1 for k in range(1, bp + 1)}
    natural = float(max(d[i] for i in range(len(d)) if i % n not in {x % n for x in seams}))
    wraps = [round(float(d[k * n - 1]), 2) for k in range(1, bp)]
    accept = all(v <= natural for v in [j for _, j in joins] + wraps + [float(d[-1])])
    return {"output": str(final), "block": str(block), "loop": str(one), "final_frames": _frames(final),
            "final_seconds": round(_frames(final) / 24, 1), "codec": codec, "cq": cq,
            "inner_wrap_steps": wraps, "file_wrap_step": round(float(d[-1]), 2), "join_steps": joins,
            "max_natural_step": round(natural, 2), "accept": accept,
            "max_other_step": round(float(max(d[i] for i in range(len(d)) if (i + 1) % n)), 2)}
