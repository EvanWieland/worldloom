"""Reader side of the event bus (dashboard spec § looper/observe.py). Pure stdlib, no UI
imports: the Textual dashboard renders Snapshot objects, and a future web page can serve
Snapshot.to_dict() as JSON. Never writes anything."""
from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field
from pathlib import Path


class Tailer:
    """Remembers a byte offset per file; returns only new complete lines. Opens and closes
    the file on every poll so it never holds a handle that could block a Windows writer."""

    def __init__(self):
        self._offsets: dict[Path, int] = {}
        self.bad_lines = 0

    def read_new(self, path: Path) -> list[dict]:
        path = Path(path)
        try:
            with open(path, "rb") as f:
                f.seek(self._offsets.get(path, 0))
                data = f.read()
        except OSError:
            return []
        end = data.rfind(b"\n")
        if end < 0:
            return []  # only a partial line so far
        self._offsets[path] = self._offsets.get(path, 0) + end + 1
        out = []
        for raw in data[:end].split(b"\n"):
            if not raw.strip():
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                self.bad_lines += 1
        return out


# -- snapshot ---------------------------------------------------------------
STALL_S = 300
ABANDON_S = 3600  # an open stage silent this long is a dead process, not a current job
SAMPLER_DEAD_S = 10
LLM_LIVE_STALE_S = 5  # model.stream arrives ~2 Hz; silence longer than this means the call ended or died
HW_WINDOW_S = 600
EVENTS_KEPT = 200
TOKEN_LINES_KEPT = 300
HW_KEYS = ("vram_mib", "gpu_util", "temp_c", "power_w", "ram_gib", "cpu_util")


@dataclass
class NowInfo:
    run_id: str
    title: str
    stage: str | None = None
    phase: str = ""
    step: int | None = None
    total_steps: int | None = None
    window: int | None = None
    total_windows: int | None = None
    sec_per_step: float | None = None
    stage_pct: float | None = None
    elapsed_s: float = 0.0
    eta_s: float | None = None
    preview_path: str | None = None
    keyframe_path: str | None = None
    stalled: bool = False


@dataclass
class QueueItem:
    run_id: str
    title: str
    position: int


@dataclass
class HistoryItem:
    run_id: str
    title: str
    status: str
    duration_s: float | None
    error: str | None = None
    results: dict = field(default_factory=dict)
    verdict: str | None = None
    keyframe_path: str | None = None
    stages: list = field(default_factory=list)


@dataclass
class ModelInfo:
    llm_live: dict | None = None
    llm_last: dict | None = None
    video_stage: str | None = None
    sec_per_step: float | None = None
    frames_per_min: float | None = None


@dataclass
class HwInfo:
    series: dict = field(default_factory=dict)
    latest: dict = field(default_factory=dict)
    sampler_alive: bool = False


@dataclass
class Snapshot:
    now: NowInfo | None
    queue: list
    history: list
    models: ModelInfo
    hw: HwInfo
    warnings: list
    generated_at: float
    tokens: list = field(default_factory=list)   # recent token-log lines (TOKENS panel), oldest first
    tokens_live: str | None = None                # current throughput line while a model is working

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class _Run:
    run_id: str
    title: str = ""
    started: float | None = None
    finished: float | None = None
    status: str | None = None
    error: str | None = None
    results: dict = field(default_factory=dict)
    last_ts: float = 0.0
    open_stage: str | None = None
    open_stage_ts: float | None = None
    progress: dict = field(default_factory=dict)
    preview: str | None = None
    stages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    plan: list = field(default_factory=list)       # stage keys announced by run.plan, in order
    done_keys: set = field(default_factory=set)
    keyframe: str | None = None
    verdict: str | None = None


class Observer:
    def __init__(self, root: Path, clock=time.time):
        self.root = Path(root)
        self._clock = clock
        self._tail = Tailer()
        self._runs: dict[str, _Run] = {}
        self._queued: dict[str, QueueItem] = {}
        self._hw: list[tuple[float, dict]] = []
        self._llm_live: dict | None = None
        self._llm_live_ts = 0.0
        self._llm_last: dict | None = None
        self._bad_records = 0
        self._durations: dict[str, list[float]] = {}  # stage name -> completed durations (all runs), for ETAs
        self._tok: list[dict] = []  # token log: {"ts", "kind", "text"} (model.request / stream / response / tokens)
        self._video_tokens: dict | None = None

    # -- ingestion --------------------------------------------------------
    def _run(self, run_id: str) -> _Run:
        return self._runs.setdefault(run_id, _Run(run_id, title=run_id))

    def _ingest(self, rec: dict) -> None:
        t, ts, p, rid = rec.get("type", ""), rec.get("ts", 0.0), rec.get("payload") or {}, rec.get("run_id")
        if t == "hw.sample":
            self._hw.append((ts, p))
            return
        if not rid:
            return
        r = self._run(rid)
        if t == "verdict":  # a human review after the fact: not run activity
            r.verdict = p.get("text")
            return
        if r.status in ("abandoned", "idle") and t != "run.finished":  # it was only slow/quiet: bring it back
            r.finished = r.status = r.error = None
            r.open_stage = r.open_stage or rec.get("stage")
        elif r.finished and t in ("run.started", "run.resumed", "stage.started") and ts > r.finished:
            # a retry/resume under the same run_id is a new attempt, not the old finished one
            r.finished = r.status = r.error = None
            r.results, r.stages, r.started, r.done_keys = {}, [], ts, set()
        r.last_ts = max(r.last_ts, ts)
        r.events = (r.events + [rec])[-EVENTS_KEPT:]
        if p.get("title"):
            r.title = p["title"]
        if t == "run.queued":
            self._queued[rid] = QueueItem(rid, r.title, p.get("position", 0))
        elif t in ("run.started", "run.resumed"):
            self._queued.pop(rid, None)
            r.started = r.started or ts
        elif t == "run.finished":
            if not (r.open_stage and ts < (r.open_stage_ts or 0)):  # an older finish can't close a newer stage
                r.finished, r.status, r.error = ts, p.get("status", "ok"), p.get("error")
                r.results = p.get("results") or {}
                r.open_stage = None
        elif t == "run.awaiting_approval":  # paused on purpose: not idle, not abandoned; a resume reopens it
            r.finished, r.status, r.error, r.results, r.open_stage = ts, "awaiting approval", None, p, None
        elif t == "stage.started":
            r.started = r.started or ts
            r.open_stage, r.open_stage_ts, r.progress = p.get("stage"), ts, {}
        elif t in ("stage.ok", "stage.restored", "stage.failed"):
            if p.get("duration_s") is not None:
                r.stages.append((p.get("stage"), p["duration_s"]))
                if t == "stage.ok":
                    self._durations.setdefault(p.get("stage"), []).append(p["duration_s"])
            r.done_keys.add(p.get("key") or p.get("stage"))
            r.open_stage = None
        elif t == "run.plan":
            r.plan, r.keyframe = list(p.get("stages") or []), p.get("keyframe") or r.keyframe
        elif t == "stage.progress":
            r.progress = p
            r.open_stage = r.open_stage or rec.get("stage")
            r.open_stage_ts = r.open_stage_ts or ts
        elif t == "render.preview":
            r.preview = p.get("path")
        elif t == "model.stream":
            self._llm_live, self._llm_live_ts = p, ts
            if p.get("text"):
                last = self._tok[-1] if self._tok else None
                if last and last["kind"] == "out" and last.get("model") == p.get("model"):
                    last["text"] += p["text"]
                else:
                    self._tok_add(ts, "out", f"◀ {p.get('model')}: {p['text']}", model=p.get("model"))
        elif t == "model.response":
            self._llm_live, self._llm_last = None, p
            self._tok_add(ts, "done", f"✓ {p.get('model')}: in {p.get('input_tokens') or '?'} · out "
                                      f"{p.get('output_tokens') or '?'} tok · {p.get('tokens_per_s') or '—'} tok/s · "
                                      f"{p.get('latency_s') or '—'} s")
        elif t == "model.request":
            extra = f" ({p['frames']} frames {p.get('resolution') or ''})" if p.get("frames") else ""
            who = p.get("model") or p.get("provider")  # the claude CLI runs its own default model (model None)
            self._tok_add(ts, "in", f"▶ {who} · {p.get('task') or ''}{extra}: {p.get('prompt') or ''}")
        elif t == "model.tokens":
            self._video_tokens = {**p, "run_id": rid}
            h, w = (p.get("latent_hw") or [0, 0])
            self._tok_add(ts, "video", f"▦ {p.get('model')}: {p.get('video_tokens', 0):,} tokens per step = "
                                       f"{p.get('generated_tokens', 0):,} generated + {p.get('context_tokens', 0):,} clean "
                                       f"context + {p.get('control_tokens', 0):,} depth control "
                                       f"(latent {p.get('latent_frames')}×{h}×{w})")

    def _files(self) -> list[Path]:
        files = sorted(self.root.glob("runs/*/events.jsonl")) + sorted(self.root.glob("experiments/**/events.jsonl"))
        tel = self.root / "telemetry"
        return files + sorted(tel.glob("hw-*.jsonl")) + [tel / "jobs.jsonl"]

    # -- snapshot ---------------------------------------------------------
    def poll(self) -> Snapshot:
        raw = [rec for f in self._files() for rec in self._tail.read_new(f)]
        batch = [r for r in raw if isinstance(r, dict) and isinstance(r.get("ts", 0), (int, float))]
        self._bad_records += len(raw) - len(batch)
        for rec in sorted(batch, key=lambda r: r.get("ts", 0)):  # merge files in time order
            try:
                if not isinstance(rec.get("payload") or {}, dict):
                    raise TypeError("payload is not an object")
                self._ingest(rec)
            except Exception:
                self._bad_records += 1
        now = self._clock()
        if self._llm_live is not None and now - self._llm_live_ts > LLM_LIVE_STALE_S:
            self._llm_live = None  # the call died without a model.response
        for r in self._runs.values():  # engine runs never emit run.finished: quiet + no open stage = idle
            if not r.finished and not r.open_stage and r.started and now - r.last_ts > STALL_S:
                r.finished, r.status = r.last_ts, "idle"
        self._hw = [(ts, s) for ts, s in self._hw if now - ts <= HW_WINDOW_S]
        warnings = []
        for r in self._runs.values():
            if r.open_stage and not r.finished and now - r.last_ts > ABANDON_S:
                r.finished, r.status = r.last_ts, "abandoned"
                r.error = f"no events after stage '{r.open_stage}' for over {ABANDON_S // 60} min"
                r.open_stage = None

        active = [r for r in self._runs.values() if r.open_stage and not r.finished]
        cur = max(active, key=lambda r: r.last_ts, default=None)
        now_info = self._now_info(cur, now) if cur else None
        if now_info and now_info.stalled:
            warnings.append(f"{cur.run_id}: no events for {int(now - cur.last_ts)} s, stalled?")

        history = []
        for r in sorted((r for r in self._runs.values() if r.finished), key=lambda r: r.finished, reverse=True):
            history.append(HistoryItem(r.run_id, r.title, r.status or "ok",
                                       round(r.finished - r.started, 1) if r.started else None,
                                       r.error, r.results, r.verdict, self._keyframe(r.run_id), r.stages))

        latest = self._hw[-1][1] if self._hw else {}
        alive = bool(self._hw) and now - self._hw[-1][0] <= SAMPLER_DEAD_S
        if not alive:
            warnings.append("hardware sampler not running (start: python -m looper hw)")
        if self._tail.bad_lines + self._bad_records:
            warnings.append(f"{self._tail.bad_lines + self._bad_records} unreadable event lines skipped")
        series = {k: [(ts, s.get(k)) for ts, s in self._hw] for k in HW_KEYS}

        spp = cur.progress.get("sec_per_step") if cur else None
        models = ModelInfo(self._llm_live, self._llm_last, cur.open_stage if cur else None, spp, None)
        queue = sorted(self._queued.values(), key=lambda q: q.position)
        return Snapshot(now_info, queue, history, models, HwInfo(series, latest, alive), warnings, now,
                        [x["text"] for x in self._tok[-60:]], self._tokens_live(cur))

    def _now_info(self, r: _Run, now: float) -> NowInfo:
        p = r.progress
        step, tot, win, twin, spp = (p.get(k) for k in ("step", "total_steps", "window", "total_windows", "sec_per_step"))
        eta = self._plan_eta(r, now)
        if eta is None and step is not None and tot and spp:
            # fallback without a run.plan: the current progress bar only (WanGP runs several bars per stage with
            # very different step times, so this under/over-shoots; see _plan_eta)
            remaining = (tot - step) + ((twin - win) * tot if win and twin else 0)
            eta = remaining * spp
        pct = None
        if step is not None and tot:
            done = ((win - 1) * tot + step) if win and twin else step
            pct = 100.0 * done / (tot * (twin or 1))
        return NowInfo(r.run_id, r.title, r.open_stage, p.get("phase", ""), step, tot, win, twin, spp, pct,
                       now - (r.started or now), eta, r.preview, self._keyframe(r.run_id), now - r.last_ts > STALL_S)

    def _tok_add(self, ts: float, kind: str, text: str, **kw) -> None:
        self._tok = (self._tok + [{"ts": ts, "kind": kind, "text": text, **kw}])[-TOKEN_LINES_KEPT:]

    def _tokens_live(self, cur: _Run | None) -> str | None:
        """Throughput while a video model denoises: its video tokens per step / seconds per step."""
        vt = self._video_tokens
        if not cur or not vt or vt.get("run_id") != cur.run_id:
            return None
        p = cur.progress
        spp, step, tot = p.get("sec_per_step"), p.get("step"), p.get("total_steps")
        if not spp or step is None or tot is None or tot > 16:  # 8+3 denoising steps; other bars aren't denoising
            return None
        return f"⚡ step {step}/{tot} · {vt['video_tokens']:,} tok × {1 / spp:.2f} steps/s = {vt['video_tokens'] / spp:,.0f} video tok/s"

    def _typical(self, stage: str) -> float | None:
        d = sorted(self._durations.get(stage, []))
        return d[len(d) // 2] if d else None

    def _plan_eta(self, r: _Run, now: float) -> float | None:
        """Stage-level ETA: typical duration of the open stage minus time spent in it, plus the typical durations of
        the announced stages not yet done. Typical = median of completed runs of that stage name (events history).
        None when the run announced no plan or a remaining stage has never completed anywhere."""
        if not r.plan:
            return None
        total = 0.0
        for key in r.plan:
            if key in r.done_keys:
                continue
            name = key.split("[")[0]
            typ = self._typical(name)
            if typ is None:
                return None
            if name == r.open_stage and r.open_stage_ts:
                typ = max(typ - (now - r.open_stage_ts), 0.05 * typ)
            total += typ
        return total

    def _keyframe(self, run_id: str) -> str | None:
        r = self._runs.get(run_id)
        if r and r.keyframe:  # runs without a keyframe stage (python -m looper loop --image) announce it
            return r.keyframe
        hits = sorted(self.root.glob(f"runs/{run_id}/stages/keyframe/*/keyframe.png"))
        return str(hits[-1]) if hits else None

    def recent_events(self, run_id: str, n: int = EVENTS_KEPT) -> list[dict]:
        r = self._runs.get(run_id)
        return r.events[-n:] if r else []
