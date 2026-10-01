"""The single event writer (ARCHITECTURE.md § Observability: "a file is the bus").
Producers call emit()/emit_current(); readers (looper/observe.py, the dashboard, a future
web page) only read the JSONL files. Nothing here may raise into a pipeline stage."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TELEMETRY_DIR = REPO_ROOT / "telemetry"

_lock = threading.Lock()  # one process-wide lock: WanGP callbacks run on another thread
_current: tuple[Path, str | None, str | None] | None = None


def jobs_path() -> Path:
    return TELEMETRY_DIR / "jobs.jsonl"


def emit(path, type_: str, payload: dict, *, run_id: str | None = None, stage: str | None = None) -> None:
    try:
        from looper.engine import redact  # local import (engine imports this module); inside the try: never raise
        rec = {"ts": time.time(), "run_id": run_id, "stage": stage, "type": type_, "payload": redact(payload)}
        line = json.dumps(rec, default=str) + "\n"
        p = Path(path)
        with _lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
    except Exception as e:  # observability must never break a render
        print(f"[looper.events] dropped {type_}: {e}", file=sys.stderr)


def set_current(events_path, run_id: str | None = None, stage: str | None = None) -> None:
    global _current
    _current = None if events_path is None else (Path(events_path), run_id, stage)


def current() -> tuple[Path, str | None, str | None] | None:
    if _current is not None:
        return _current
    env = os.environ.get("LOOPER_EVENTS")
    if not env:
        return None
    path, run_id, stage = (env.split("|") + ["", ""])[:3]
    return Path(path), (run_id or None), (stage or None)


def emit_current(type_: str, payload: dict) -> None:
    ctx = current()
    if ctx is not None:
        emit(ctx[0], type_, payload, run_id=ctx[1], stage=ctx[2])
