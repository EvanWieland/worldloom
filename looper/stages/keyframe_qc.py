"""keyframe_qc stage: a vision critic scores one generated keyframe against the director's brief. The pipeline
ranks the seeds with pick() (spec: automatic self-check). The critic's judgement is UNPROVEN until compared with the
user's picks (research/director.md)."""
from __future__ import annotations

import json
from pathlib import Path

from looper import models

VERSION = 3  # v3: unreadable replies -> retry, then a zero score (best effort) instead of failing.
# v2: integer example in the prompt + one retry when a score comes back as prose/bool
CRITERIA = ("brief", "motion_visible", "settled", "cinematic")
MIN_SCORE = 3

SCHEMA = {"type": "object", "additionalProperties": False, "required": [*CRITERIA, "hard_fails", "notes"],
          "properties": {**{c: {"type": "integer"} for c in CRITERIA},
                         "hard_fails": {"type": "array", "items": {"type": "string"}}, "notes": {"type": "string"}}}

_ASK = """You are checking one still frame before it becomes the first frame of a calm, locked-off, looping video.
The frame was generated from this description:
{brief}
The video will show this motion:
{motion}
Score four criteria, each an INTEGER from 1 (bad) to 5 (excellent):
- brief: does the frame show what the description asks for
- motion_visible: are the elements that will move clearly present and visible
- settled: are steam, mist, smoke, fog or spray already fully developed (5 if there are none)
- cinematic: composition, lighting and detail
hard_fails: list of serious problems -- people, animals, text or watermarks the description did not ask for; melted
or impossible structures; extra limbs; heavy artifacts. Empty list if none. notes: one short sentence.
Respond with ONLY a JSON object shaped exactly like this example (numbers, not words):
{{"brief": 4, "motion_visible": 5, "settled": 3, "cinematic": 4, "hard_fails": [], "notes": "..."}}"""
_RETRY = "\n\nYour previous answer used words or true/false where an integer 1-5 was required. Answer again."


def _is_score(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def verdict(raw: dict) -> dict:
    def score(v):
        return min(5, max(0, v)) if _is_score(v) else 0
    scores = {c: score(raw.get(c)) for c in CRITERIA}
    fails = [s for s in raw.get("hard_fails") or [] if isinstance(s, str) and s.strip()] \
        if isinstance(raw.get("hard_fails"), list) else []
    return {"scores": scores, "hard_fails": fails, "accept": not fails and min(scores.values()) >= MIN_SCORE,
            "total": sum(scores.values()), "notes": raw.get("notes") if isinstance(raw.get("notes"), str) else ""}


def pick(cands: list[dict]) -> tuple[int, str | None]:
    best = max(range(len(cands)), key=lambda i: (cands[i]["accept"], cands[i]["total"]))
    warn = None if cands[best]["accept"] else \
        f"no keyframe passed the critic; using the best-scoring one ({cands[best]['total']}/20)"
    return best, warn


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {"image"}; config: {brief, motion, provider, model}"""
    ask = _ASK.format(brief=config["brief"], motion=config["motion"])
    call = dict(provider=config.get("provider", "ollama"), model=config["model"], images=[Path(inputs["image"])],
                unload=True, schema=SCHEMA, timeout_s=300)
    try:
        raw, meta = models.complete_json("keyframe_qc", ask, **call)
    except models.ModelError as e:  # one retry; best effort after that (a bad reply must not abort the front end)
        raw, meta = {"notes": f"critic reply unreadable: {e}"[:300]}, {}
    if not all(_is_score(raw.get(c)) for c in CRITERIA):  # qwen3.6 wrote prose / true for 2 of 3 stills (dir_neon)
        try:
            raw, meta = models.complete_json("keyframe_qc", ask + _RETRY, **call)
        except models.ModelError as e:
            raw, meta = {"notes": f"critic reply unreadable twice: {e}"[:300]}, {}
    v = verdict(raw)
    (Path(out_dir) / "qc.json").write_text(json.dumps({**v, "raw": raw, "model_call": meta}, indent=1), encoding="utf-8")
    return {**v, "model_meta": meta}
