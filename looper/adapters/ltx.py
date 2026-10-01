"""LTX-2.5 specifics that WanGP's settings API can't express, applied as temporary patches of WanGP's own LTX
pipeline functions around one generation (ADR 0007; evidence research/particle-loop-closure.md):

- save_latents: keep the run's own latents (stage-1 latent before the spatial upsampler, final latent before the
  VAE decode). Re-encoding decoded frames keeps only ~0.69 of fine motion, and anything conditioned on re-encoded
  frames inherits that loss.
- context: clean timestep-0 conditioning through LTX's own VideoConditionByLatentIndex (the path WanGP uses for the
  I2V first frame / continuation prefix). Prefix = window frames 0..8(P-1), suffix = frames from 8(I0-1)+1, each
  optionally replaced by (or blended with) the source run's saved latents.

Vendor imports stay inside this module (CLAUDE.md invariant 9). In-process only: WanGP runs the task in a worker
thread of this process, so module-level patches reach it; they are restored when the context exits.
"""
from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from looper.adapters import wangp

MODEL = "ltx2_25_22B_distilled"


@dataclass
class TrueLatents:
    """A source run's saved latents: window latents map to source latents [first_latent, ...)."""
    stage1: Path
    stage2: Path
    first_latent: int
    alpha: float = 1.0  # < 1: blend alpha * true + (1 - alpha) * re-encoded (continuations: 0.5)


@dataclass
class Context:
    source: np.ndarray            # (F, H, W, 3) RGB uint8, F = 8k + 1; frames outside the context are ignored
    prefix_latents: int           # P: window latents 0..P-1 are context (0 = none)
    suffix_latent: int            # I0: window latents I0.. are context (= latent count: none)
    prefix_true: TrueLatents | None = None
    suffix_true: TrueLatents | None = None
    diag: dict = field(default_factory=dict)


def settings(prompt: str, negative: str, image: Path, control_video: Path, frames: int, seed: int,
             resolution: str = "832x480", motion_speed: float = 1.0, guide_strength: float = 1.0,
             single_stage: bool = False) -> dict:
    """The proven clip recipe: distilled 8 steps, depth IC-LoRA fed the keyframe held still (camera lock).
    motion_speed < 1 adds the Slow-Motion-Control LoRA; the caller must also pass it to hooks() (the motion clock).
    guide_strength: WanGP's denoising_strength, which for "DVG" IS the depth guide's control strength
    (models/ltx2/ltx2.py `control_strength = denoising_strength`); the union IC-LoRA itself stays at multiplier 1.0.
    single_stage: WanGP guidance_phases 1 = no half-size stage 1 + upsampler + refine; motion is decided at the full
    size (research/harvester-drum.md: the 832x480 drum re-synthesised at 416x240)."""
    extra = {"activated_loras": [SPEED_LORA], "loras_multipliers": "1.0"} if motion_speed != 1.0 else {}
    if single_stage:
        extra["guidance_phases"] = 1
    return {**extra, "model_type": MODEL, "num_inference_steps": 8, "prompt": prompt, "negative_prompt": negative,
            "image_prompt_type": "S", "image_start": str(image), "video_prompt_type": "DVG",
            "video_guide": str(control_video), "denoising_strength": guide_strength, "resolution": resolution,
            "video_length": frames, "seed": seed}


SPEED_LORA = "ltx-2.5-22b-lora-slow-motion-control-1.0.safetensors"


def stage1_latent_path(out_dir: Path, single_stage: bool) -> Path:
    """A single-stage run has one full-size latent: it stands in for stage 1 too (load_true picks the file by the
    height it is asked for, and a single-stage window never asks for a half-size one)."""
    return Path(out_dir) / ("lat_stage2.pt" if single_stage else "lat_stage1.pt")


def scale_motion_clock(positions, motion_speed: float):
    """Slow-Motion-Control LoRA's motion clock (model card: motion_fps = playback_fps / speed): every video token's
    temporal RoPE coordinate (seconds, [start, end) per token, axis 0 of dim 1) times speed; spatial axes untouched.
    Applied to the finished state, so appended IC-LoRA guide tokens and clean contexts share the clock."""
    if not 0.0 < motion_speed <= 1.0:
        raise ValueError(f"motion_speed must be in (0, 1], got {motion_speed}")
    if motion_speed == 1.0:
        return positions
    p = positions.clone()
    p[:, 0] *= motion_speed
    return p


@contextlib.contextmanager
def hooks(*, save_latents_to: Path | None = None, context: Context | None = None, motion_speed: float = 1.0,
          clock_log: list | None = None):
    """Patch WanGP's LTX distilled pipeline for the duration of one generation. motion_speed < 1: scale the video
    temporal positions once per state construction (both stages) for the Slow-Motion-Control LoRA, which must also
    be loaded (settings activated_loras); clock_log receives the actual transformer-input time span per stage."""
    wangp.ensure_path()
    import torch
    from dataclasses import replace
    from models.ltx2.ltx_core.model.video_vae import TilingConfig
    from models.ltx2.ltx_pipelines import distilled
    from models.ltx2.ltx_pipelines.utils import helpers
    from models.ltx2.ltx_pipelines.utils.media_io import load_video_conditioning

    saved = {k: getattr(distilled, k) for k in
             ("image_conditionings_by_replacing_latent", "upsample_video", "vae_decode_video_to_tensor")}
    saved_noise = helpers.noise_video_state

    def noise_counted(*a, **k):  # report what the transformer processes each step (dashboard TOKENS panel)
        state, tools = saved_noise(*a, **k)
        if motion_speed != 1.0:
            state = replace(state, positions=scale_motion_clock(state.positions, motion_speed))
        if clock_log is not None:
            t = state.positions[0, 0]
            clock_log.append({"speed": motion_speed, "t_min": float(t.min()), "t_max": float(t.max()),
                              "tokens": int(t.shape[0])})
        try:
            from looper import events
            shp = tools.target_shape
            n_t = shp.frames * shp.height * shp.width
            clean = int((state.denoise_mask[0, :n_t] == 0).sum())
            events.emit_current("model.tokens", {
                "model": MODEL, "latent_frames": shp.frames, "latent_hw": [shp.height, shp.width],
                "video_tokens": int(state.latent.shape[1]), "generated_tokens": n_t - clean, "context_tokens": clean,
                "control_tokens": int(state.latent.shape[1]) - n_t})
        except Exception as e:  # telemetry must never break a render
            print(f"[ltx] token event dropped: {e}")
        return state, tools

    helpers.noise_video_state = noise_counted
    try:
        if context is not None:
            c = context
            F = c.source.shape[0]
            nlat = (F - 1) // 8 + 1
            # prefix == suffix start: every latent is context (the no-generation reconstruction control)
            assert (F - 1) % 8 == 0 and 0 <= c.prefix_latents <= c.suffix_latent <= nlat, (F, c.prefix_latents, c.suffix_latent)
            orig_img = saved["image_conditionings_by_replacing_latent"]

            def load_true(t: TrueLatents, height, device, dtype, count):
                lat = torch.load(t.stage1 if height < 400 else t.stage2).to(device=device, dtype=dtype)
                return lat[:, :, t.first_latent:t.first_latent + count]

            def with_context(images, height, width, video_encoder, dtype, device, tiling_config=None):
                conds = orig_img(images=images, height=height, width=width, video_encoder=video_encoder,
                                 dtype=dtype, device=device, tiling_config=tiling_config)
                tc = tiling_config or TilingConfig.default()
                enc = lambda fr: distilled.vae_encode_video(load_video_conditioning(fr, height, width, None, dtype, device),
                                                            video_encoder, tc)
                P, I0 = c.prefix_latents, c.suffix_latent
                if P:
                    pre = enc(c.source[: 8 * (P - 1) + 1])
                    if c.prefix_true:  # latent 0 stays the single-frame encode (LTX's causal first latent)
                        t = load_true(c.prefix_true, height, device, pre.dtype, P - 1)
                        a = c.prefix_true.alpha
                        pre = torch.cat([pre[:, :, :1], a * t + (1 - a) * pre[:, :, 1:]], dim=2)
                    conds += helpers.latent_conditionings_by_latent_sequence(pre, strength=1.0, start_index=0)
                fs = 8 * (I0 - 1) + 1
                if fs < F:  # suffix: first frame duplicated in front (causal single-frame latent), then dropped
                    suf = enc(np.concatenate([c.source[fs:fs + 1], c.source[fs:]]))[:, :, 1:]
                    if c.suffix_true:
                        suf = load_true(c.suffix_true, height, device, suf.dtype, suf.shape[2])
                    conds += helpers.latent_conditionings_by_latent_sequence(suf, strength=1.0, start_index=I0)
                c.diag.setdefault("stages", []).append({"res": [height, width]})
                return conds

            distilled.image_conditionings_by_replacing_latent = with_context

        if save_latents_to is not None:
            out = Path(save_latents_to)
            orig_up, orig_dec = saved["upsample_video"], saved["vae_decode_video_to_tensor"]

            def up_saved(*a, **k):
                torch.save(k["latent"].detach().cpu(), out / "lat_stage1.pt")
                return orig_up(*a, **k)

            def dec_saved(latents, *a, **k):
                torch.save(latents[0].detach().cpu(), out / "lat_stage2.pt")
                return orig_dec(latents, *a, **k)

            distilled.upsample_video, distilled.vae_decode_video_to_tensor = up_saved, dec_saved
        yield
    finally:
        for k, v in saved.items():
            setattr(distilled, k, v)
        helpers.noise_video_state = saved_noise


def still_control(image: Path, frames: int, out: Path) -> Path:
    """Depth-lock control video = the keyframe held still for the whole window."""
    from looper.ffmpeg_utils import run_ffmpeg
    run_ffmpeg(["-loop", "1", "-i", str(image), "-frames:v", str(frames), "-r", "24", "-c:v", "libx264",
                "-crf", "12", "-pix_fmt", "yuv420p", str(out)])
    return out


def control(image: Path, frames: int, out: Path, guide: Path | None = None) -> Path:
    """The window's depth control: a moving full-frame guide at the keyframe's framing when given (--take-guide, a
    return guide; research/ltx-cloak-screen.md), else the keyframe held still. A guide shorter than the window would
    leave its tail unguided -- a different experiment -- so it is refused."""
    if guide is None:
        return still_control(image, frames, out)
    import cv2
    n = int(cv2.VideoCapture(str(guide)).get(cv2.CAP_PROP_FRAME_COUNT))
    if n < frames:
        raise ValueError(f"guide {Path(guide).name} has {n} frames, the window needs {frames}")
    return Path(guide)


def runtime(s: dict, motion_speed: float = 1.0) -> dict:
    """Recipe provenance beyond settings.json (handoff §11.1): WanGP revision, torch/CUDA, GPU, and the size of every
    LoRA file the settings name (a swapped file of the same name shows up as a size change). `time` keeps the two
    timing operations apart (handoff §9): the generation-side motion clock and playback, which is never retimed."""
    import subprocess
    import torch
    rev = subprocess.run(["git", "-C", str(wangp.WANGP_ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True).stdout.strip() or None
    loras = {n: (p.stat().st_size if (p := wangp.WANGP_ROOT / "loras" / "ltx2" / n).exists() else None)
             for n in s.get("activated_loras", [])}
    from looper.engine import hash_file
    mdef = wangp.WANGP_ROOT / "defaults" / f"{s.get('model_type')}.json"
    # checkpoint identity without hashing ~20 GB each run: name (carries the quantisation) + size; the dev weights are
    # left out of distilled runs. The model definition (URLs, default loras) is small enough to hash.
    mt = str(s.get("model_type"))
    family = "ltx-2.5-22b" if mt.startswith("ltx2_25") else "ltx-2.3-22b"
    ckpts = {p.name: p.stat().st_size for p in sorted((wangp.WANGP_ROOT / "ckpts").glob(f"{family}*"))
             if not ("distilled" in mt and "-dev_" in p.name)}
    if "D" in str(s.get("video_prompt_type", "")):  # the union-control IC-LoRA WanGP adds for the depth guide
        ckpts.update({p.name: p.stat().st_size for p in (wangp.WANGP_ROOT / "loras").rglob("*union-control*")})
    return {"wangp_rev": rev, "torch": torch.__version__, "cuda": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None, "lora_bytes": loras,
            "model_def_sha": hash_file(mdef) if mdef.exists() else None, "ckpt_bytes": ckpts,
            "model": s.get("model_type"),
            "time": {"generation_motion_clock": motion_speed, "generated_fps": 24, "playback_fps": 24,
                     "playback_retime": None}}


def write_settings(path: Path, s: dict) -> None:
    path.write_text(json.dumps(s, indent=1), encoding="utf-8")
