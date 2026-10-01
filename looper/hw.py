"""VRAM/RAM/GPU sampler thread, ported from experiments/e1_baseline.py. Used by GPU-heavy
stages to record peak resource usage in stage metadata (ARCHITECTURE.md observability:
hw.sample / GPU util-mem-temp-power)."""
from __future__ import annotations

import subprocess
import threading

try:
    import psutil
except ImportError:
    psutil = None


class HardwareSampler:
    def __init__(self, interval_s: float = 2.0):
        self.interval_s = interval_s
        self.peak = {"vram_mib": 0.0, "temp_c": 0.0, "power_w": 0.0, "ram_gib": 0.0}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample_loop(self):
        q = ["nvidia-smi", "--query-gpu=memory.used,temperature.gpu,power.draw", "--format=csv,noheader,nounits"]
        while not self._stop.is_set():
            try:
                m, t, p = (float(x) for x in subprocess.check_output(q, text=True).strip().split(","))
                self.peak["vram_mib"] = max(self.peak["vram_mib"], m)
                self.peak["temp_c"] = max(self.peak["temp_c"], t)
                self.peak["power_w"] = max(self.peak["power_w"], p)
                if psutil:
                    used_gib = (psutil.virtual_memory().total - psutil.virtual_memory().available) / 2**30
                    self.peak["ram_gib"] = max(self.peak["ram_gib"], round(used_gib, 2))
            except Exception:
                pass
            self._stop.wait(self.interval_s)

    def __enter__(self):
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        return False


# -- telemetry sampler process (`python -m looper hw`) ---------------------
import datetime  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from looper import events  # noqa: E402

_NVSMI_Q = ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
            "--format=csv,noheader,nounits"]


def _nvsmi_query() -> str:
    return subprocess.check_output(_NVSMI_Q, text=True, timeout=3)


def sample_once(nvsmi=_nvsmi_query) -> dict:
    s = dict.fromkeys(("vram_mib", "vram_total_mib", "gpu_util", "temp_c", "power_w",
                       "ram_gib", "ram_total_gib", "cpu_util"))
    try:
        vals = [float(x) for x in nvsmi().strip().splitlines()[0].split(",")]
        s["vram_mib"], s["vram_total_mib"], s["gpu_util"], s["temp_c"], s["power_w"] = vals
    except Exception:
        pass  # a hung/busy nvidia-smi is recorded as missing, never blocks
    if psutil:
        vm = psutil.virtual_memory()
        s["ram_gib"] = round((vm.total - vm.available) / 2**30, 2)
        s["ram_total_gib"] = round(vm.total / 2**30, 2)
        s["cpu_util"] = psutil.cpu_percent(interval=None)
    return s


def hw_path(day: datetime.date, root: Path = events.TELEMETRY_DIR) -> Path:
    return Path(root) / f"hw-{day:%Y%m%d}.jsonl"


def prune_old(root: Path, keep_days: int = 7) -> None:
    cutoff = datetime.date.today() - datetime.timedelta(days=keep_days)
    for p in Path(root).glob("hw-*.jsonl"):
        try:
            if datetime.datetime.strptime(p.stem[3:], "%Y%m%d").date() < cutoff:
                p.unlink()
        except ValueError:
            pass


def run_sampler(interval_s: float = 2.0, root: Path = events.TELEMETRY_DIR,
                iterations: int | None = None, nvsmi=_nvsmi_query) -> None:
    """One hw.sample every interval_s into today's telemetry file (daily rotation, 7 days kept)."""
    Path(root).mkdir(parents=True, exist_ok=True)
    prune_old(root)
    n = 0
    while iterations is None or n < iterations:
        events.emit(hw_path(datetime.date.today(), root), "hw.sample", sample_once(nvsmi))
        n += 1
        time.sleep(interval_s)
