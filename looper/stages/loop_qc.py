"""loop_qc stage: judge one closed loop before any human sees it (an obviously broken render never reaches review).
  - closing score: largest normalised frame step across the closure gap + joins vs the largest anywhere else in the
    loop (human passes 0.98-1.80, fails 2.78-4.76)
  - regional QC (`looper/regional_qc.py`) against the take itself from start_frame on (scene boxes if given, else
    automatic regions), cyclic.
Not a stage failure when a loop fails its gates: accept is recorded and the pipeline picks the best candidate.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from looper import loopkit, regional_qc

VERSION = 10  # v10: config lull "freeze" (scenes without machinery): a low that is neither deep nor long is a lull.
# v9: every fail says where it trips (screen position + loop time; same gates).
# v8: with a declared moving light, spikes > 1 s from any join are events (lightning), not seams.
# v7: with a declared moving light (config moving_light) the low / low_texture limits are source-relative
#            (min(fixed, 0.85 x the take's own min)): the leviathan lull runs from the take into the return's first
#            frames, inside the modified margin. (v6 -- low flags only inside modified frames -- reverted: replay passed
#            the harvester old-route closures whose drum-cell stall the user saw; experiments/gate_replay/loop_qc_replay.py)
# v5: whole-loop slow drift (loop_drift, review DOUBT > 8 grey)
# v4: v4: closure-gap texture churn vs the window's own contexts (review DOUBT only) when the window is given
# v2: a spike rejects only inside the frames the pipeline modified (gap, ramps, wrap, extension join)
# v3: per-region closure-gap activity ratio written to qc.json (diagnostic)
# Calibrated on the 10 human-judged rain loops with automatic regions (research/particle-loop-closure.md section 11):
# passes 0.98-1.80, un-retimed fails 2.78 / 4.76. static.edge_dev fired on 3/5 passes (dark-wall grain): not a reject.
# The two RETIMED fails (4 interpolated frames) scored 1.10-1.18 with no flags: the metric cannot see retime
# artifacts, so the pipeline never retimes.
CLOSING_OVER_REST_MAX = 2.0
# ponytail: review DOUBT only. Mean normalised step through the gap + joins: 1.19-1.30 on every loop the user passed
# (rain, furnace_bright), 1.54-1.58 on dir_furnace_mild's three seeds (the whole frame churns through the gap; verdict
# pending). Not a reject until a verdict lands.
CLOSING_MEAN_MAX = 1.4
# ponytail: review DOUBT only. loopkit.gap_churn on the close window: passed loops 0.99-1.29, rated very slight 1.36,
# rejected furnace closures 1.54-1.62 (research/scene-perfection-round2.md). Not a reject: one scene of failures.
GAP_CHURN_MAX = 1.4
# The worst cell separates better (2026-09-27, falls_loop's closure: mean 1.29 but worst 1.61, seen at 7 s in review):
# passed loops peak 1.10-1.48, every one rated visible / slight 1.57-1.83. Review DOUBT only.
GAP_CHURN_WORST_MAX = 1.5
# Whole-loop slow drift (loopkit.loop_drift): passed loops 2.3-6.5 grey, the pine passing shadow 10.5; the take gate's
# calibration agrees (10.7 rated noticeable). One failure: review DOUBT only.
LOOP_DRIFT_MAX = 8.0
RAMP, MARGIN = 8, 12  # splice/join ramps; half a second of slack around every modified range
# Per-region closure-gap activity ratio (regional_qc.gap_motion) is written to qc.json as a DIAGNOSTIC only: it does
# not separate the furnace wheel's visible catch-up (1.25-1.31) from the rain loop the user passed (1.19-1.26);
# experiments/qc_tools/gapmotion.py, research/furnace-scene.md. A rotation-specific measure is still open.


@functools.lru_cache(maxsize=4)
def _reference(path: str, start_frame: int, scene_path: str, _stamp: tuple | None = None) -> regional_qc.Reference:
    """The QC reference of the take is identical for every closure seed of a run: build it once per process
    (~13 s each; profiled 2026-09-27). Keyed by path + size + mtime so a changed file is never served stale."""
    return _build_reference(path, start_frame, scene_path)


def _build_reference(path: str, start_frame: int, scene_path: str) -> regional_qc.Reference:
    scene = json.loads(Path(scene_path).read_text(encoding="utf-8")) if scene_path else None
    return regional_qc.reference(loopkit.read_frames(Path(path))[start_frame:], scene)


def in_modified(frame: int, n: int, gap_start: int, ext_join: int | None) -> bool:
    """Is loop frame `frame` inside a range the pipeline generated or ramped? Unmodified source frames keep their
    natural rhythm (sea swell at 11.8 s in dir_lighthouse2, the cabin fire): a spike there is the scene, not a
    seam, and the closure being judged did not put it there."""
    f = frame % n
    if f >= gap_start - RAMP - MARGIN or f < RAMP + MARGIN:  # gap + tail ramp ... wrap ... head ramp
        return True
    return ext_join is not None and abs(f - ext_join) <= RAMP + MARGIN


_ROWS, _COLS = ("top", "middle", "bottom"), ("left", "centre-left", "centre-right", "right")


def where(region: str, frame: int, fps: int = 24) -> str:
    """A QC flag in plain words (sample_2: the review said only "c20.low"; the reviewer could not tell where the
    lull was): an automatic 3x4 cell c<row><col> as its screen position, a named scene region as its name, then the
    loop time."""
    if len(region) == 3 and region[0] == "c" and region[1:].isdigit():
        r, c = _ROWS[int(region[1])], _COLS[int(region[2])]
        region = f"{r}-{c}" if r != "middle" and c in ("left", "right") else f"{r}, {c}"
    return f"{region}, {frame / fps:.1f} s"


# v10: without rotating machinery a low is a FREEZE only when it is deep or long. User-judged replay
# (research/ltx-cloak-screen.md): passed lulls sample_2 0.39-0.49 for 0.2-2.1 s, sample_1b 0.43 for 0.3 s; the
# held-still return froze the cloak at 0.17-0.24 for 8-14 s. Machinery keeps the strict gate: the harvester drum stall
# a reviewer saw scored only 0.49 for 0.08 s -- a stalled drum is obvious, a calm cloak is weather.
FREEZE_MIN, FREEZE_S = 0.3, 4.0


def freeze(rm, limit: float, fps: float) -> dict:
    """rm: a region's rolling R (cyclic loop). Deep (min < FREEZE_MIN) or long (below limit > FREEZE_S) = frozen."""
    import numpy as np
    below = np.concatenate([rm < limit, rm < limit])  # cyclic: a dip may wrap
    longest = cur = 0
    for b in below:
        cur = cur + 1 if b else 0
        longest = max(longest, cur)
    longest_s = min(longest, len(rm)) / fps
    lo = float(np.nanmin(rm))
    return {"min": round(lo, 3), "longest_s": round(longest_s, 2), "freeze": lo < FREEZE_MIN or longest_s > FREEZE_S}


def fail_where(report: dict) -> dict:
    """{flag: where it trips} for every remaining fail (the review and the failed-run message print it)."""
    out = {}
    for f in report["fails"]:
        cell, _, gate = f.partition(".")
        at = report["gates"].get(cell, {}).get(gate, {}).get("at")
        frame = at if isinstance(at, int) else at[1] if at else None
        if frame is not None:
            out[f] = f"static areas, {frame / 24:.1f} s" if cell == "static" else where(cell, int(frame))
    return out


JOIN_GUARD = 24  # v8: with a declared moving light, a spike more than 1 s from a join is a flash / pulse EVENT


def far_from_joins(frame: int, n: int, gap_start: int) -> bool:
    """Leviathan v2: lightning flashes inside a generated return (frames 404 / 467 / 510, gap 360, wrap 720) failed
    every closure; the user's brief only forbids a flash AT the loop boundary."""
    f = frame % n
    return min(abs(f - gap_start), f, n - f) > JOIN_GUARD


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {loop, reference (the take), [scene json], [window]}; config: {start_frame, gap_start, [ext_join], [E, G]}"""
    loop = loopkit.read_frames(inputs["loop"])
    st = Path(inputs["reference"]).stat()
    ref = _reference(str(inputs["reference"]), config["start_frame"], str(inputs.get("scene", "")),
                     (st.st_size, st.st_mtime_ns))
    report, res = regional_qc.evaluate(loop, ref, wrap=True, relative_low=bool(config.get("moving_light")))
    score = loopkit.closing_score(loopkit.step_profile(loop), config["gap_start"])
    try:
        regional_qc.plots(res, ref.S, ref.masks, [config["gap_start"], 0], out_dir / "qc.png",
                          f"{report['verdict']} {' '.join(report['fails'])[:150]}")
    except Exception as e:  # a plot must never fail the stage
        report["plot_error"] = str(e)
    n, natural = len(loop), []
    for f in list(report["fails"]):
        cell, _, gate = f.partition(".")
        if gate == "spike":
            at = report["gates"][cell][gate]["at"]
            if at and (not in_modified(int(at[1]), n, config["gap_start"], config.get("ext_join"))
                       or (config.get("moving_light") and far_from_joins(int(at[1]), n, config["gap_start"]))):
                natural.append(f"{f}@{int(at[1])}")
                report["fails"].remove(f)
    lulls = []
    if config.get("lull") == "freeze":  # v10: no rotating machinery in the scene -> a calm lull is weather, not a fault
        w = max(1, round(regional_qc.ROLL_S * res["fps"]))
        for f in [f for f in report["fails"] if f.endswith((".low", ".low_texture"))]:
            cell, _, gate = f.partition(".")
            g = report["gates"][cell][gate]
            key = g["at"][0] if g.get("at") else None
            if key not in ref.S["med"]:
                continue
            fz = freeze(regional_qc.roll_mean(res["E"][key] / (ref.S["med"][key] + 1e-6), w, True), g["limit"], res["fps"])
            if not fz["freeze"]:
                lulls.append({"flag": f, "where": where(cell, int(g["at"][1])), **fz})
                report["fails"].remove(f)
    accept = score["closing_over_rest"] <= CLOSING_OVER_REST_MAX and not any(
        f.endswith((".spike", ".low", ".low_texture")) for f in report["fails"])
    gm = regional_qc.gap_motion(res, ref.S, config["gap_start"])
    score.update(loopkit.loop_drift(loop))
    if "window" in inputs:
        score.update(loopkit.gap_churn(loopkit.read_frames(inputs["window"]), config["E"], config["G"]))
    (out_dir / "qc.json").write_text(json.dumps({**report, **score, "natural_spikes": natural, "gap_motion": gm}, indent=1),
                                     encoding="utf-8")
    return {"accept": accept, "verdict": report["verdict"], "fails": report["fails"], "fail_where": fail_where(report),
            "lulls": lulls,
            "natural_spikes": natural, "regions": list(ref.scene["regions"]), "auto_regions": bool(ref.scene.get("auto")),
            **score}
