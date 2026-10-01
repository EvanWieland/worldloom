"""Job contract (handoff 2026-09-27 §14, ADR 0014 proposed): one stage of a run as a self-contained, reproducible job
description that a remote executor could run with the same recipe. DISABLED: nothing here submits anything; there is
no provider and no authorised paid job. `python -m looper job RUN_ID STAGE_KEY` writes runs/<id>/jobs/<key>.json.

A job carries what the handoff lists: input hashes, contract, recipe, output destination, resource limits, cost/time
caps. Execution location must not change the recipe: the job pins the stage version, config (which includes every
model setting that enters the fingerprint), seed and the WanGP revision; a remote result whose fingerprint differs is
a new candidate, never a drop-in (§14: "even unchanged seeds do not guarantee identity across environments").
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = 1


def export(run_dir: Path, key: str, limits: dict | None = None) -> Path:
    run_dir = Path(run_dir)
    man = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if key not in man["stages"]:
        raise KeyError(f"no stage {key!r} in {run_dir.name}; have {sorted(man['stages'])}")
    name = key.split("[")[0]
    sdir = run_dir / "stages" / name / man["stages"][key]["fingerprint"]
    rec = json.loads((sdir / "stage.json").read_text(encoding="utf-8"))
    contract = man["stages"].get("contract")
    job = {"schema_version": SCHEMA_VERSION, "enabled": False, "run_id": man["run_id"], "stage": name, "key": key,
           "stage_version": rec["version"], "pipeline_version": rec.get("pipeline_version"), "config": rec["config"],
           "seed": rec["seed"], "input_hashes": rec["inputs"], "fingerprint": rec["fingerprint"],
           "contract_fingerprint": contract["fingerprint"] if contract else None,
           "recipe": json.loads((sdir / "settings.json").read_text(encoding="utf-8")) if (sdir / "settings.json").exists()
           else None,
           "runtime": (rec.get("meta") or {}).get("runtime"),
           "output_destination": f"runs/{man['run_id']}/stages/{name}/<fingerprint computed where it ran>",
           "limits": {"max_wall_minutes": None, "max_cost_usd": None, "gpu": None, **(limits or {})},
           "on_return": "recompute the fingerprint; equal -> restore as this stage, different -> a new candidate "
                        "that needs content and continuity review"}
    out = run_dir / "jobs" / f"{key.replace('[', '_').replace(']', '')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(job, indent=1, default=str), encoding="utf-8")
    return out
