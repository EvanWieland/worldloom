"""WanGP adapter: sys.path bootstrap + one warm session per process, kept resident so the
~20-30s model load/text-encode isn't repaid per clip (WanGP's own docs: "keep the last
loaded model alive across requests" -- measured basis: research/local-video-baseline.md).
Isolated here so it can be relocated behind a real executor later (ARCHITECTURE.md
"Execution model") without touching stage logic.

WanGP's session writes to ONE output_dir fixed at session creation (its API has no per-call
override), but every stage run has its own fingerprinted out_dir. So every call here writes
into a shared scratch dir and the result is immediately relocated into the caller's out_dir.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

from looper import events

PREVIEW_MIN_INTERVAL_S = 5.0
PREVIEW_KEEP = 20
PREVIEW_MAX_W = 480
_WINDOW_RE = re.compile(r"Sliding Window (\d+)/(\d+)")


class WanGPEventBridge:
    """WanGP session callbacks -> looper events (dashboard spec § Producers). Writes nothing
    when no run context is set, so scripts that don't care behave exactly as before."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._last_step: tuple[int, float] | None = None
        self._sec_per_step: float | None = None
        self._last_preview = float("-inf")
        self.phase_s: dict[str, float] = {}  # wall seconds per WanGP phase (handoff §12): loading_model, encoding_text,
        self._phase: tuple[str, float] | None = None  # inference, decoding; the last phase is closed by close()

    def _account(self, phase: str) -> None:
        now = self._clock()
        if self._phase:
            p, t = self._phase
            self.phase_s[p] = round(self.phase_s.get(p, 0.0) + now - t, 2)
        self._phase = (phase, now) if phase else None

    def close(self) -> dict:
        self._account("")
        return dict(self.phase_s)

    def on_progress(self, u) -> None:
        try:  # WanGP calls this without a try: an exception here would kill the render
            self._account(getattr(u, "phase", "") or "unlabelled")
            self._on_progress(u)
        except Exception as e:
            print(f"[wangp] progress event dropped: {e}")

    def _on_progress(self, u) -> None:
        if events.current() is None:
            return
        now = self._clock()
        step = getattr(u, "current_step", None)
        if step is not None and self._last_step and step > self._last_step[0]:
            self._sec_per_step = (now - self._last_step[1]) / (step - self._last_step[0])
        if step is not None and (not self._last_step or step != self._last_step[0]):
            self._last_step = (step, now)
        m = _WINDOW_RE.search(f"{getattr(u, 'status', '')} {getattr(u, 'phase', '')}")
        events.emit_current("stage.progress", {
            "step": step, "total_steps": getattr(u, "total_steps", None),
            "window": int(m.group(1)) if m else None, "total_windows": int(m.group(2)) if m else None,
            "sec_per_step": round(self._sec_per_step, 2) if self._sec_per_step else None,
            "phase": getattr(u, "phase", ""), "progress": getattr(u, "progress", None)})

    def on_preview(self, u) -> None:
        ctx = events.current()
        img = getattr(u, "image", None)
        now = self._clock()
        if ctx is None or img is None or now - self._last_preview < PREVIEW_MIN_INTERVAL_S:
            return
        self._last_preview = now
        try:
            pdir = ctx[0].parent / "previews"
            pdir.mkdir(parents=True, exist_ok=True)
            im = img.convert("RGB")
            if im.width > 2.5 * im.height:  # some models (LTX) preview a filmstrip of frames: keep the newest tile
                n = max(1, round(im.width / (im.height * 16 / 9)))
                tile_w = im.width / n
                im = im.crop((round(im.width - tile_w), 0, im.width, im.height))
            if im.width > PREVIEW_MAX_W:
                im = im.resize((PREVIEW_MAX_W, round(im.height * PREVIEW_MAX_W / im.width)))
            # number past whatever earlier calls in this run left, so pruning never eats the new frame
            nums = [int(p.stem) for p in pdir.glob("*.jpg") if p.stem.isdigit()]
            path = pdir / f"{max(nums, default=-1) + 1:04d}.jpg"
            tmp = path.with_suffix(".tmp")
            im.save(tmp, format="JPEG", quality=85)
            os.replace(tmp, path)  # readers never see a half-written JPEG
            for old in sorted(pdir.glob("*.jpg"))[:-PREVIEW_KEEP]:
                old.unlink(missing_ok=True)
            events.emit_current("render.preview", {"path": str(path), "frame_index": getattr(u, "current_step", None),
                                                   "width": im.width, "height": im.height})
        except Exception as e:  # a preview must never break a render
            print(f"[wangp] preview dropped: {e}")


# A rented GPU (ADR 0014) runs the same code from its own WanGP checkout, with a memory profile / attention kernel for
# its card; the attention kernel is recorded in every result's metadata by callers that compare locations.
def default_root(repo: Path) -> Path:
    """A Wan2GP checkout beside the repository, or in a tools/ folder beside it."""
    return next((p for p in (repo.parent / "Wan2GP", repo.parent / "tools" / "Wan2GP") if p.exists()),
                repo.parent / "Wan2GP")


WANGP_ROOT = Path(os.environ.get("WANGP_ROOT") or default_root(Path(__file__).resolve().parents[2]))
WANGP_PROFILE = os.environ.get("WANGP_PROFILE", "4")
WANGP_ATTENTION = os.environ.get("WANGP_ATTENTION", "sage2")
WANGP_EXTRA_ARGS = os.environ.get("WANGP_EXTRA_ARGS", "").split()  # probes only, e.g. "--save-masks" (processed guide)

_session = None
_scratch: Path | None = None


def ensure_path() -> None:
    """Make WanGP's own packages importable (adapters that patch WanGP internals need this)."""
    if not (WANGP_ROOT / "wgp.py").exists():
        raise FileNotFoundError(f"WanGP not found at {WANGP_ROOT}: install it there or set WANGP_ROOT to your Wan2GP "
                                f"checkout (https://github.com/deepbeepmeep/Wan2GP)")
    if str(WANGP_ROOT) not in sys.path:
        sys.path.insert(0, str(WANGP_ROOT))


def _get_session(scratch_dir: Path):
    global _session, _scratch
    scratch_dir = Path(scratch_dir)
    if _session is None or _scratch != scratch_dir:
        ensure_path()
        from shared.api import init  # WanGP's own package, only importable once path is set

        scratch_dir.mkdir(parents=True, exist_ok=True)
        _session = init(
            root=WANGP_ROOT, output_dir=scratch_dir,
            cli_args=["--attention", WANGP_ATTENTION, "--profile", WANGP_PROFILE, *WANGP_EXTRA_ARGS], console_output=False,
        )
        _scratch = scratch_dir
    return _session


def _relocate(files: list[str], out_dir: Path, dest_name: str) -> Path:
    if not files:
        raise RuntimeError("WanGP reported success but produced no output files")
    # Multi-window (sliding window / SVI) jobs list one file per window and the combined
    # clip LAST; taking files[0] silently returned only the first window (found 2026-09-22).
    dest = Path(out_dir) / dest_name
    shutil.move(files[-1], str(dest))
    for extra in files[:-1]:
        Path(extra).unlink(missing_ok=True)
    return dest


def _free_gpu() -> None:
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def generate(settings: dict, out_dir: Path, dest_name: str, *, scratch_dir: Path) -> dict:
    """One WanGP generation task (T2I or I2V), blocking. Relocates the result into out_dir.
    Frees cached GPU memory first and retries once on CUDA OOM: a second 481-frame LTX take in the same process
    OOMed at the start of inference on the 6 GB card (neon_loop, 2026-09-25) after the first had run fine."""
    s = _get_session(scratch_dir)
    events.emit_current("model.request", {"provider": "wangp", "model": settings.get("model_type"),
                                          "task": dest_name, "prompt": (settings.get("prompt") or "")[:4000],
                                          "frames": settings.get("video_length"), "resolution": settings.get("resolution")})
    for attempt in (1, 2):
        _free_gpu()
        cuda_peak = _reset_cuda_peak()
        bridge = WanGPEventBridge()
        t0 = time.time()
        result = s.submit_task(settings, callbacks=bridge).result()
        if result.success:
            break
        errors = "; ".join(getattr(e, "message", str(e)) for e in result.errors)
        if attempt == 1 and "out of memory" in errors.lower():
            print("[wangp] CUDA out of memory: freeing cache and retrying once", flush=True)
            continue
        raise RuntimeError(f"WanGP generation failed: {errors or 'unknown error'}")
    dest = _relocate(result.generated_files, out_dir, dest_name)
    # handoff §12: per-phase wall time (a loading_model share >> 0 = a cold model), torch's peak allocation in this
    # process (None = unavailable); retries = 1 when the OOM retry ran
    return {"output": str(dest), "settings": settings,
            "timing": {"wall_s": round(time.time() - t0, 1), "phase_s": bridge.close(), "retries": attempt - 1,
                       "cuda_peak_alloc_gb": cuda_peak()}}


def _reset_cuda_peak():
    """Reset torch's peak-allocation counter; returns a reader (None when torch/CUDA is unavailable)."""
    try:
        import torch
        if not torch.cuda.is_available():
            return lambda: None
        torch.cuda.reset_peak_memory_stats()
        return lambda: round(torch.cuda.max_memory_allocated() / 2**30, 2)
    except Exception:  # noqa: BLE001 -- instrumentation never breaks a render
        return lambda: None


def postprocess(source: Path, out_dir: Path, dest_name: str, *, scratch_dir: Path, **kwargs) -> dict:
    """One WanGP postprocessing task (RIFE / upscale / etc), blocking. Relocates the result."""
    s = _get_session(scratch_dir)
    result = s.submit_media_postprocessing(str(source), return_media=False, callbacks=WanGPEventBridge(), **kwargs).result()
    if not result.success:
        errors = "; ".join(getattr(e, "message", str(e)) for e in result.errors)
        raise RuntimeError(f"WanGP postprocessing failed: {errors or 'unknown error'}")
    dest = _relocate(result.generated_files, out_dir, dest_name)
    return {"output": str(dest), "postprocess": kwargs}
