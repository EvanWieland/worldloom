"""deliver stage: the chosen 4:4:4 loop -> delivery files (4:2:0, mbtree=0: ADR 0006 step 5).
A 4:2:0 file's own wrap (last predicted frame -> first keyframe) measured 1.16-1.24x the loop's largest natural step
at every crf / ipratio / keyint tried, while the 4:4:4 master's wrap was 1.0x (rain_loop_e2e, 2026-09-25). So the
loop is encoded as a BLOCK of `block_periods` consecutive periods in one continuous encode (internal loop points are
ordinary frames), and final.mp4 = N x stream copy of that block (research/long-form-assembly.md: zero cost, zero
generation loss). The codec wrap then occurs once per block instead of once per period.
"""
from __future__ import annotations

from pathlib import Path

from looper import loopkit
from looper.ffmpeg_utils import run_ffmpeg

VERSION = 3  # v2: continuous multi-period block; v3: keyint=infinite (no I-frame pops every 250 frames)


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {loop}; config: {repeats (blocks in final.mp4), block_periods, crf}"""
    loop = loopkit.read_frames(inputs["loop"])
    block = out_dir / "block.mp4"
    loopkit.write_video(loop * config["block_periods"], block, crf=config.get("crf", 17), pix_fmt="yuv420p")
    one = out_dir / "loop_420.mp4"  # single period, for review / short players (has the codec wrap)
    loopkit.write_video(loop, one, crf=config.get("crf", 17), pix_fmt="yuv420p")
    final = out_dir / "final.mp4"
    run_ffmpeg(["-stream_loop", str(config["repeats"] - 1), "-i", str(block), "-c", "copy", "-movflags", "+faststart", str(final)])
    d = loopkit.step_profile(loopkit.read_frames(block))
    n = len(loop)
    inner = [round(float(d[k * n - 1]), 2) for k in range(1, config["block_periods"])]
    return {"output": str(final), "block": str(block), "loop": str(one), "repeats": config["repeats"],
            "block_periods": config["block_periods"], "block_seconds": round(n * config["block_periods"] / 24, 1),
            "inner_wrap_steps": inner, "file_wrap_step": round(float(d[-1]), 2),
            "max_other_step": round(float(max(d[i] for i in range(len(d)) if (i + 1) % n)), 2)}
