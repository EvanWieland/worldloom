"""Human review decisions (handoff 2026-09-27 §7): tied to the exact artifact (stage fingerprint + output hash) and the
scene contract, so a changed recipe, contract or output invalidates them. Cached computation (a restored stage) is not
cached approval: a gate passes only on a decision recorded for this very artifact.

runs/<id>/review/pending_<subject>.json  what is waiting for a decision (written by the gate)
runs/<id>/acceptance.jsonl               append-only decisions; history is never rewritten
"""
from __future__ import annotations

import json
import time
from pathlib import Path

SUBJECTS = ("take", "loop")
STATUSES = ("accepted", "rejected", "best_effort")


def _key(ref: dict) -> tuple:
    return ref["fingerprint"], ref["output_sha"], ref.get("contract_sha")


def write_pending(run_dir: Path, subject: str, ref: dict) -> Path:
    p = Path(run_dir) / "review" / f"pending_{subject}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ref, indent=1), encoding="utf-8")
    return p


def record(run_dir: Path, subject: str, status: str, note: str = "") -> dict:
    """Decide on what the gate left pending for `subject`. Raises when nothing is pending."""
    if subject not in SUBJECTS or status not in STATUSES:
        raise ValueError(f"subject {subject!r} / status {status!r}")
    p = Path(run_dir) / "review" / f"pending_{subject}.json"
    if not p.exists():
        raise FileNotFoundError(f"nothing pending for '{subject}' in {run_dir} (run with --audition, or --4k for 'loop')")
    rec = {"ts": time.time(), "subject": subject, "status": status, "note": note, **json.loads(p.read_text(encoding="utf-8"))}
    with open(Path(run_dir) / "acceptance.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def decision(run_dir: Path, subject: str, ref: dict) -> dict | None:
    """The newest decision recorded for exactly this artifact + contract, else None (pending / invalidated)."""
    log = Path(run_dir) / "acceptance.jsonl"
    hits = [r for r in (json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip())
            if r["subject"] == subject and _key(r) == _key(ref)] if log.exists() else []
    return hits[-1] if hits else None
