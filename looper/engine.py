"""Pipeline engine: fingerprinted stage artifacts, resume, manifest, events.

See DECISIONS/0001-fingerprinted-stage-artifacts.md and ARCHITECTURE.md
"Resumability & invalidation" for the design this implements. The invariant:
previous work stays reusable unless its inputs, config, seed, or stage version
actually changed (CLAUDE.md invariant 5).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from looper import PIPELINE_VERSION, events

# A key is secret when one of its WORDS is (access_token, RUNPOD_API_KEY, clientSecret) -- not a substring: the stage
# "key", "keyframe" and "input_tokens" are data the dashboard reads (public-release privacy review, 2026-10-01).
SECRET_WORDS = {"token", "secret", "password", "passwd", "authorization", "credential", "credentials", "apikey"}
SECRET_PAIRS = {("api", "key"), ("private", "key"), ("access", "key")}
# credential formats inside text (a key pasted into a prompt or an error message): OpenAI / Anthropic, Hugging Face,
# RunPod, GitHub, AWS, Slack, JWT, bearer headers
SECRET_TEXT = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}|\bhf_[A-Za-z0-9]{20,}|\brpa_[A-Za-z0-9]{10,}|\bgh[pousr]_[A-Za-z0-9]{20,}"
                         r"|\bAKIA[0-9A-Z]{16}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}"
                         r"|\bBearer\s+[\w.~+/=-]{8,}")


def _secret_key(k: str) -> bool:
    words = re.split(r"[_\-.\s]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", k).lower())
    return any(w in SECRET_WORDS for w in words) or any(p in SECRET_PAIRS for p in zip(words, words[1:]))


def redact(obj: Any) -> Any:
    """Strip secrets before anything is written to disk or emitted as an event (invariant 15): values under
    secret-named keys, and credential-shaped strings anywhere. Not a general personal-data scrubber: prompts and
    paths stay (they are the run's record). Fingerprints use the raw config, so caching is unaffected."""
    if isinstance(obj, dict):
        return {k: ("<redacted>" if isinstance(k, str) and _secret_key(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return SECRET_TEXT.sub("<redacted>", obj)
    return obj


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def hash_dir(path: Path) -> str:
    """Fallback for a stage input that's a whole directory. Real stages prefer a specific
    file path (see stages/*.py); this exists so an input CAN be a directory without the
    fingerprint silently ignoring its contents."""
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(hash_file(p).encode())
    return h.hexdigest()[:16]


def hash_input(path: Path) -> str:
    path = Path(path)
    return hash_dir(path) if path.is_dir() else hash_file(path)


def fingerprint(stage: str, version: int, config: dict, seed: Any, input_hashes: dict[str, str]) -> str:
    payload = {
        "stage": stage, "version": version, "config": config, "seed": seed,
        "inputs": {k: input_hashes[k] for k in sorted(input_hashes)},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def stale_stage_dirs(run_dir: Path) -> list[Path]:
    """Stage output dirs the manifest no longer points at (superseded by a newer config/version/input). The manifest
    keeps only the latest fingerprint per key, so going back to an older config regenerates instead of restoring.
    A run still writing a stage has that dir outside the manifest too -- callers skip active runs."""
    manifest = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    live = {v["fingerprint"] for v in manifest["stages"].values()}
    return [d for d in sorted((Path(run_dir) / "stages").glob("*/*")) if d.is_dir() and d.name not in live]


def last_activity(run_dir: Path) -> float:
    """Timestamp of the run's last event, ignoring `verdict` (a later human review is not run activity);
    the manifest's mtime when there are no events."""
    log, ts = Path(run_dir) / "events.jsonl", []
    for line in (log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else []):
        try:
            rec = json.loads(line)
            if rec.get("type") != "verdict":
                ts.append(float(rec["ts"]))
        except (ValueError, KeyError, TypeError, AttributeError):  # a torn last line from a live writer
            pass
    return max(ts, default=(Path(run_dir) / "manifest.json").stat().st_mtime)


@dataclass
class StageResult:
    name: str
    fingerprint: str
    out_dir: Path
    status: str  # "ok" | "failed"
    cached: bool
    meta: dict = field(default_factory=dict)


class Engine:
    """One Engine per run. Owns the run directory, manifest, and event log."""

    def __init__(self, run_dir: Path, run_id: str, original_prompt: str = ""):
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "manifest.json"
        self.events_path = self.run_dir / "events.jsonl"
        resuming = self.manifest_path.exists()
        if resuming:
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        else:
            self.manifest = {
                "run_id": run_id, "original_prompt": original_prompt,
                "created": time.time(), "stages": {},
            }
            self._write_manifest()
        self._emit("run.resumed" if resuming else "run.started", {"prompt": original_prompt})

    # -- events ---------------------------------------------------------
    def emit(self, type_: str, payload: dict) -> None:
        """Public hook for ad hoc events outside the run_stage lifecycle -- e.g. a clip
        being rejected by validate, which is a normal outcome, not a stage failure."""
        self._emit(type_, payload)

    def finish(self, status: str = "ok", error: str | None = None, results: dict | None = None) -> None:
        """Marks the run done for observers (dashboard HISTORY). Not part of any fingerprint."""
        self._emit("run.finished", {"status": status, "error": error, "results": results or {}})

    def _emit(self, type_: str, payload: dict) -> None:
        events.emit(self.events_path, type_, payload, run_id=self.run_id, stage=payload.get("stage"))

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(json.dumps(self.manifest, indent=1, default=str), encoding="utf-8")

    # -- stage execution --------------------------------------------------
    def run_stage(
        self,
        name: str,
        version: int,
        config: dict,
        inputs: dict[str, Path],
        fn: Callable[[dict, dict, Path], dict | None],
        *,
        seed: Any = None,
        key: str | None = None,
    ) -> StageResult:
        """
        name: stage name (e.g. "generate")
        version: bump when fn's output-affecting logic changes -- part of the fingerprint
        config: this stage's config slice (JSON-serialisable); keep it explicit, see
            ARCHITECTURE.md "Config slices must be explicit per stage, otherwise everything
            invalidates everything"
        inputs: {logical_name: path} -- files/dirs this stage reads; hashed into the fingerprint
        fn(inputs, config, out_dir) -> optional meta dict; must write only inside out_dir;
            raise on failure
        key: manifest key for fan-out stages (e.g. "generate[2]"); defaults to `name`
        """
        manifest_key = key or name
        input_hashes = {k: hash_input(Path(p)) for k, p in inputs.items()}
        fp = fingerprint(name, version, config, seed, input_hashes)
        out_dir = self.run_dir / "stages" / name / fp
        stage_json = out_dir / "stage.json"
        prior_fp = self.manifest["stages"].get(manifest_key, {}).get("fingerprint")
        if prior_fp and prior_fp != fp:  # a resumed run replans this stage (new version / config / inputs): say so;
            # the old output dir stays on disk untouched (realism amendment §13: never rewrite what an old run meant)
            self._emit("stage.superseded", {"stage": name, "key": manifest_key, "old": prior_fp, "new": fp})

        if stage_json.exists():
            prior = json.loads(stage_json.read_text(encoding="utf-8"))
            if prior.get("status") == "ok":
                self._emit("stage.restored", {"stage": name, "key": manifest_key, "fingerprint": fp})
                self.manifest["stages"][manifest_key] = {"fingerprint": fp, "status": "ok"}
                self._write_manifest()
                return StageResult(name, fp, out_dir, "ok", cached=True, meta=prior.get("meta", {}))
            shutil.rmtree(out_dir)  # clear a failed attempt's partial output before retrying

        out_dir.mkdir(parents=True, exist_ok=True)
        self._emit("stage.started", {"stage": name, "key": manifest_key, "fingerprint": fp})
        t0 = time.time()
        try:
            events.set_current(self.events_path, self.run_id, name)
            try:
                meta = fn(inputs, config, out_dir) or {}
            finally:
                events.set_current(None)
            record = {
                "stage": name, "version": version, "pipeline_version": PIPELINE_VERSION,
                "config": redact(config), "seed": seed,
                "inputs": input_hashes, "fingerprint": fp, "status": "ok",
                "duration_s": round(time.time() - t0, 2), "meta": redact(meta),
            }
            stage_json.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
            self.manifest["stages"][manifest_key] = {"fingerprint": fp, "status": "ok"}
            self._write_manifest()
            self._emit("stage.ok", {"stage": name, "key": manifest_key, "fingerprint": fp,
                                     "duration_s": record["duration_s"]})
            return StageResult(name, fp, out_dir, "ok", cached=False, meta=meta)
        except Exception as e:
            record = {
                "stage": name, "version": version, "pipeline_version": PIPELINE_VERSION,
                "config": redact(config), "seed": seed,
                "inputs": input_hashes, "fingerprint": fp, "status": "failed",
                "duration_s": round(time.time() - t0, 2), "error": str(e),
            }
            stage_json.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
            self.manifest["stages"][manifest_key] = {"fingerprint": fp, "status": "failed"}
            self._write_manifest()
            self._emit("stage.failed", {"stage": name, "key": manifest_key, "fingerprint": fp, "error": str(e)})
            raise
