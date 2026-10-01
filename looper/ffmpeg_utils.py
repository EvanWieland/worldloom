"""Small ffmpeg subprocess helper with consistent error handling, used by deliver and the LTX adapter."""
from __future__ import annotations

import subprocess


def run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[:2000]}")
