"""keyframe stage: WanGP T2I (Z-Image Turbo) -> keyframe.png at the loop resolution. The look is settled here,
cheaply, before any GPU-minutes are spent on video (ARCHITECTURE.md). One call per seed (fan-out key keyframe[i])."""
from __future__ import annotations

from pathlib import Path

from looper import hw
from looper.adapters import wangp

VERSION = 2  # v2: output cover-cropped to config["size"] (the loop resolution); one seed per call


def fit(src: Path, dst: Path, size: tuple[int, int]) -> None:
    from PIL import Image
    w, h = size
    im = Image.open(src).convert("RGB")
    s = max(w / im.width, h / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    left, top = (im.width - w) // 2, (im.height - h) // 2
    im.crop((left, top, left + w, top + h)).save(dst)


def fit_video(src: Path, dst: Path, still_size: tuple[int, int], size: tuple[int, int], speed: float = 1.0,
              frames: int | None = None) -> Path:
    """--take-guide: another render of the still (any size, e.g. Hunyuan's 848x480) -> the loop size with fit()'s exact
    geometry: back to the still's own size first, then fit()'s cover scale + centre crop, so the guide and the keyframe
    share one framing (a direct cover-crop of the render is ~1 px off at the frame edges). speed < 1 (--donor-speed,
    ADR 0016): the render slowed first and motion-interpolated back to 24 fps, so guide frame k shows it at time
    speed * k; frames: trim to the window."""
    from looper.ffmpeg_utils import run_ffmpeg
    (W, H), (w, h) = still_size, size
    s = max(w / W, h / H)
    sw, sh = round(W * s), round(H * s)
    slow = (f"setpts=PTS/{speed},minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            if speed != 1 else "")
    run_ffmpeg(["-i", str(src), "-vf", f"{slow}scale={W}:{H}:flags=lanczos,scale={sw}:{sh}:flags=lanczos,"
                f"crop={w}:{h}:{(sw - w) // 2}:{(sh - h) // 2}", *(["-frames:v", str(frames)] if frames else []),
                "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(dst)])
    return dst


FIT_VERSION = 1


def fit_guide_run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {video}; config: {still_size: [w, h] of the user's --image, size: [w, h] [, speed, frames]}"""
    out = fit_video(Path(inputs["video"]), Path(out_dir) / "guide.mp4", tuple(config["still_size"]), tuple(config["size"]),
                    config.get("speed", 1.0), config.get("frames"))
    return {"output": str(out)}


def fit_run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """fit stage: a user's --image -> the loop resolution, as the generated keyframes get. A 1672x941 still went
    straight to the depth-control encode and libx264 refused its odd height (dir_furnace, 2026-09-26).
    inputs: {image}; config: {size: [w, h]}"""
    out = Path(out_dir) / "keyframe.png"
    fit(Path(inputs["image"]), out, tuple(config["size"]))
    return {"output": str(out)}


def run(inputs: dict, config: dict, out_dir: Path, *, scratch_dir: Path) -> dict:
    """config: {prompt, seed, size: [w, h]}"""
    settings = {"model_type": "z_image", "prompt": config["prompt"], "resolution": "1280x720",
                "num_inference_steps": 8, "seed": config["seed"], "image_mode": 1}
    with hw.HardwareSampler() as sampler:
        meta = wangp.generate(settings, out_dir, "keyframe_raw.png", scratch_dir=scratch_dir)
    out = Path(out_dir) / "keyframe.png"
    fit(Path(meta["output"]), out, tuple(config["size"]))
    return {"output": str(out), "raw": meta["output"], "settings": settings, "peak_hw": sampler.peak}
