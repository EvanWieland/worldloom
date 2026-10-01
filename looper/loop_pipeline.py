"""run_loop(): keyframe image + scene prompt -> one seamless 30-60 s forward loop (ADR 0005 target, ADR 0007 recipe):
  take (LTX, steady light, latents saved) -> take_qc (global + per-region drift, camera; next seed if it drifts)
  -> [extend -> join]   only when the loop must outlast one take (single step, alpha 0.5; next seed if it drifts)
  -> close x N  generated 32 f closure per seed, returning to take frame >= 89
  -> splice x N, loop_qc x N  -> best accepted closure  -> deliver (4:2:0 loop + N x stream copy)
Every stage is fingerprinted (ADR 0001): changing the closure seeds reruns only close/splice/qc; a new target length
reruns extend onward, never the take. Loop length ~= (take - start_frame) + extension + gap.
The keyframe comes from --image, or from the director + Z-Image (front.py) for prompt-only runs.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from looper import loopkit, motion_style
from looper.contract import MACHINERY
from looper.engine import Engine
from looper.stages import (audition, bloom, close, direct, deliver, donor, endpoint, extend, grow, join, keyframe, loop_qc, review,
                           settle, splice, take, take_qc, upscale)

DEFAULT_NEGATIVE = motion_style.BASE_NEGATIVE
DEFAULTS = {"seconds": 30.0, "take_frames": 481, "take_seed": 306, "take_attempts": 3, "close_seeds": [306, 307, 308],
            "start_frame": 89, "gap_frames": 32, "prefix_latents": 7, "close_frames": 145, "alpha": 0.5,
            "resolution": "832x480", "repeats": 3, "block_periods": 4, "extend_attempts": 2,
            "region_drift_max": 4.0, "fallback_drift_max": 7.5, "settle": "auto", "bloom": None, "min_seconds": 17.0,
            "director": "local", "director_model": None, "raw_prompt": False, "auto": False, "approve": False,
            "keyframe": None, "keyframe_seeds": [1000, 1001, 1002],
            "final_4k": False, "upscale_chunk": 144, "upscale_margin": 8, "upscale_model": "flashvsr*4",
            "size_4k": [3840, 2160], "codec_4k": "hevc_nvenc", "cq_4k": 19, "final_minutes": 60,
            "motion_speed": 1.0, "guide_strength": 1.0, "single_stage": False, "long_return": None, "early_accept": True,
            "audition": False, "take_guide": None, "motion_donor": False, "donor_speed": 1.0, "cli": None}
# A closure this clean ends the seed loop early: seeds of one take score within noise (closing ratio +-0.05) and every
# loop the user passed has worst-region churn <= 1.48 (research/scene-perfection-round2.md). Saves 1-2 closures
# (~8 min per run; ~28 min with --long-return).
EARLY_CLOSING_MAX, EARLY_CHURN_WORST_MAX = 1.2, 1.4


def held_donor(engine: Engine, name: str, cfg_donor: dict, image: Path, scratch: Path, seed: int,
               warnings: list) -> Path:
    """ADR 0016: render a motion donor, check that its subject stays where it is (donor_hold), and re-roll the seed when
    it travels -- every take follows the donor (sample_2 seed 306 stepped 13.6 px, spice v23 walked 114 px). The first
    attempt keeps the old stage key and config (cached runs restore); the steadiest donor wins when none holds."""
    tried = []
    for k in range(donor.DONOR_ATTEMPTS):
        suffix = name if k == 0 else f"{name}_{k}"
        r = engine.run_stage("donor", donor.VERSION, {**cfg_donor, "seed": seed + k}, {"image": image},
                             lambda inp, c, out: donor.run(inp, c, out, scratch_dir=scratch), key=f"donor[{suffix}]")
        h = engine.run_stage("donor_hold", donor.HOLD_VERSION, {}, {"video": Path(r.meta["output"])}, donor.hold_run,
                             key=f"donor_hold[{suffix}]")
        engine.emit("donor.hold", {"donor": name, "seed": seed + k, **h.meta})
        if not h.meta["travels"]:  # False: holds; None: no person found (nothing to hold)
            return Path(r.meta["output"])
        tried.append((abs(h.meta["net_px"]), seed + k, r))
    net, kept, r = min(tried, key=lambda t: t[0])
    warnings.append(f"the {name} donor's subject moved in every seed ({net} px net at best, seed {kept}): expect the "
                    f"figure to drift")
    engine.emit("donor.travels", {"donor": name, "kept_seed": kept, "net_px": net})
    return Path(r.meta["output"])


def lull_mode(prompt: str) -> dict:
    """loop_qc v10: only a freeze fails a scene without rotating machinery (the user passed calm lulls in cloth and
    sand; a stalled drum is a fault however brief)."""
    return {} if MACHINERY.search(prompt) else {"lull": "freeze"}


def flags(c: dict) -> list:
    """A closure's loop_qc fails with where they trip ("c20.low (bottom-left, 19.9 s)"); old results have no places."""
    return [f"{f} ({c['fail_where'][f]})" if f in c.get("fail_where", {}) else f for f in c["fails"]]


def clearly_clean(c: dict) -> bool:
    return bool(c["accept"]) and c["closing_over_rest"] <= EARLY_CLOSING_MAX and not c["fails"] and         c.get("gap_churn_worst_cell") is not None and c["gap_churn_worst_cell"] <= EARLY_CHURN_WORST_MAX
MAX_GAP = 368  # one LTX window: WanGP splits clips > 481 f into sliding windows (a 497 f closure crashed)


def _return_need(cfg: dict) -> int:
    return math.ceil(cfg["seconds"] * 24) - (cfg["take_frames"] - cfg["start_frame"])


def long_return_gap(cfg: dict) -> int:
    """ADR 0012 (accepted): one closure whose gap fills the loop to length -- no extension, no 32 f closure.
    G = target - (take - start_frame), 8-aligned, within one LTX window."""
    return max(32, min(MAX_GAP, 8 * math.ceil(_return_need(cfg) / 8)))


def long_return_fits(cfg: dict) -> bool:
    """Default route (ADR 0012) whenever one return window can fill the loop (30 s: yes; 60 s: extension route)."""
    return 8 * math.ceil(_return_need(cfg) / 8) <= MAX_GAP


def final_4k(engine: Engine, loop: Path, cfg: dict, run_dir: Path) -> dict:
    """T3a local 4K of the chosen loop master (stages/upscale.py): one fingerprinted stage per circular chunk, then
    join + delivery. final_4k.mp4 = enough stream-copied blocks for cfg["final_minutes"]."""
    scratch = Path(run_dir) / "_wangp_scratch"
    n = len(loopkit.read_frames(loop))
    spans = upscale.layout(n, cfg["upscale_chunk"])
    ups = {}
    for i, (s, e) in enumerate(spans):
        r = engine.run_stage("upscale", upscale.VERSION,
                             {"start": s, "end": e, "margin": cfg["upscale_margin"], "size": cfg["size_4k"],
                              "model": cfg["upscale_model"]}, {"loop": loop},
                             lambda inp, c, out: upscale.run_chunk(inp, c, out, scratch_dir=scratch), key=f"upscale[{i}]")
        ups[f"c{i}"] = Path(r.meta["upscaled"])  # the raw FlashVSR run incl. its context frames: the join ramps in them
    period = Path(engine.run_stage("upscale_join", upscale.JOIN_VERSION,
                                   {"n": n, "spans": spans, "margin": cfg["upscale_margin"], "ramp": cfg["upscale_margin"],
                                    "size": cfg["size_4k"]}, ups, upscale.run_join).meta["output"])
    block_s = n * cfg["block_periods"] / 24
    repeats = max(1, math.ceil(cfg["final_minutes"] * 60 / block_s))
    return engine.run_stage("deliver4k", upscale.DELIVER_VERSION,
                            {"repeats": repeats, "block_periods": cfg["block_periods"], "cq": cfg["cq_4k"],
                             "codec": cfg["codec_4k"], "spans": spans}, {"period": period}, upscale.run_deliver4k).meta


def plan_lengths(cfg: dict) -> dict:
    """How many new frames the extension must add for the requested loop length (0: the take alone is enough)."""
    body = cfg["take_frames"] - cfg["start_frame"]
    need = math.ceil(cfg["seconds"] * 24) - body - cfg["gap_frames"]
    if need <= 0:
        return {"extension_window": 0, "loop_frames": body + cfg["gap_frames"]}
    win = loopkit.extension_window(need, cfg["prefix_latents"])
    return {"extension_window": win, "loop_frames": body + win - loopkit.ctx_frames(cfg["prefix_latents"]) + cfg["gap_frames"]}


def run_loop(image: Path | None, prompt: str, config: dict, run_dir: Path, run_id: str, negative: str | None = None,
             scene: Path | None = None) -> dict:
    """image None = prompt-only (director -> keyframes -> approval). negative None = the director's negative."""
    from looper import front
    cfg = {**DEFAULTS, **{k: v for k, v in config.items() if v is not None}}
    if cfg["long_return"] is None:
        cfg["long_return"] = long_return_fits(cfg)
    if cfg["motion_donor"]:  # ADR 0016: the guide only renders as cloth in one full-size pass; the return is guided too
        if not cfg["long_return"]:
            raise ValueError("--motion-donor needs the long-return route (a loop of up to ~35 s)")
        cfg["single_stage"] = True
    if cfg["long_return"]:
        g = long_return_gap(cfg)
        cfg["gap_frames"], cfg["close_frames"] = g, cfg["close_frames"] + g - 32
    engine = Engine(run_dir, run_id, original_prompt=prompt)
    try:
        p = front.prepare(engine, prompt, Path(image) if image else None, cfg, Path(run_dir))
        result = _run(engine, p["image"], p["prompt"], negative or p["negative"], cfg, run_dir, scene, p["contract"])
        result["warnings"] = p["warnings"] + result["warnings"]
    except front.AwaitingApproval as a:
        return {"status": "awaiting_approval", **a.info}
    except Exception as e:
        engine.finish("failed", error=str(e), results=unresolved(engine, str(e)))
        raise
    engine.finish("ok", results={"final_video": result["final_video"], "outcome": result["outcome"]})
    return result


FAILURES = [  # (error substring, failing stage, the unmet requirement) -- realism amendment §11: report what was not met
    ("no usable take", "take_qc", "a loopable take: every take seed drifted past the best-effort limit"),
    ("no closure passed loop_qc", "loop_qc", "a closure that passes continuity QC"),
    ("every closure failed to render", "close", "a rendered closure"),
    ("rejected in review", "review", "your content review"),
    ("unrenderable prompt", "direct", "a renderable plan"),
]


def unresolved(engine: Engine, error: str) -> dict:
    """A run that gives up is `unresolved`, never a simplified success: the failing stage, the unmet requirement, and
    which scene requirements were still unverified (their route never got a verdict)."""
    stage, unmet = next(((s, u) for pat, s, u in FAILURES if pat in error), (None, error[:300]))
    if stage is None:
        failed = [k for k, v in engine.manifest["stages"].items() if v.get("status") == "failed"]
        stage = failed[-1] if failed else "unknown"
    reqs = []
    con = engine.manifest["stages"].get("contract")
    if con:
        p = engine.run_dir / "stages" / "contract" / con["fingerprint"] / "contract.json"
        if p.exists():
            reqs = [r["id"] for r in json.loads(p.read_text(encoding="utf-8"))["contract"]["requirements"]]
    return {"outcome": "unresolved", "failed_at": stage, "unmet": unmet, "requirements_unverified": reqs}


def _gate(engine: Engine, run_dir: Path, subject: str, ref: dict, info: dict) -> dict:
    """Human content gate (handoff 2026-09-27 §7): passes only on a decision recorded for exactly this artifact +
    contract (acceptance.py); a rejection stops the run; no decision pauses it with the packet in `info`."""
    from looper import acceptance, front
    d = acceptance.decision(run_dir, subject, ref)
    if d and d["status"] == "rejected":
        raise RuntimeError(f"{subject} rejected in review ({d['note'] or 'no note'}): change the recipe or seed; "
                           f"nothing downstream runs on it")
    if d:
        engine.emit("review.accepted", {"subject": subject, "status": d["status"], "fingerprint": ref["fingerprint"]})
        return d
    acceptance.write_pending(run_dir, subject, ref)
    engine.emit("review.pending", {"subject": subject, **info})
    engine.emit("run.awaiting_approval", info)
    raise front.AwaitingApproval(info)


def _ref(key: str, r, output: Path, contract: dict | None) -> dict:
    from looper.engine import hash_file
    recipe = Path(r.out_dir) / "settings.json"  # the exact WanGP settings that rendered it (takes); absent for CPU stages
    return {"stage": key, "fingerprint": r.fingerprint, "output": str(output), "output_sha": hash_file(Path(output)),
            "contract_sha": (contract or {}).get("contract_sha"),
            "recipe": str(recipe) if recipe.exists() else None, "recipe_sha": hash_file(recipe) if recipe.exists() else None}


def _shorter_cut(engine: Engine, cfg: dict, take_mp4: Path, take_lat: dict, tried_ext: list, warnings: list) -> tuple:
    """No stationary extension: search every long take that exists (the take, each rejected extension's long) for the
    easiest legal (end, start) cut of at least cfg["min_seconds"] (stages/endpoint.py); use it when it beats the
    take-only cut, else the take-only loop. -> (long, end_video, end_latents, start_frame, end_frame, end_local)."""
    sources = [("take", take_mp4, None)] + [(f"long{i}", Path(j.meta["long"]), e) for i, (e, j) in enumerate(tried_ext)]
    ep_cfg = {"min_seconds": cfg["min_seconds"], "gap": cfg["gap_frames"], "start_frame": cfg["start_frame"],
              "take_frames": cfg["take_frames"]}
    best, take_only = None, None
    for name, long_p, r_e in sources:
        r_ep = engine.run_stage("endpoint", endpoint.VERSION, ep_cfg, {"long": long_p}, endpoint.run, key=f"endpoint[{name}]")
        if name == "take":
            take_only = r_ep.meta["take_only"]
        b = r_ep.meta["best"]
        if b and (best is None or b["boundary"] < best[0]["boundary"]):
            best = (b, long_p, r_e)
    n_take, E = cfg["take_frames"], loopkit.ctx_frames(cfg["prefix_latents"])
    if best and take_only and best[0]["boundary"] + 0.5 < take_only["boundary"]:
        b, long_p, r_e = best
        secs = b["loop_frames"] / 24
        warnings.append(f"no stationary extension in {cfg['extend_attempts']} seeds: loop cut to {secs:.1f} s at frames "
                        f"{b['s']}-{b['e']} (boundary {b['boundary']} grey; the take-only cut was {take_only['boundary']})")
        engine.emit("extension.best_effort", {"loop_seconds": round(secs, 1), "cut": b, "take_only": take_only})
        if b["e"] <= n_take:
            return take_mp4, take_mp4, take_lat, b["s"], b["e"], b["e"]
        return long_p, Path(r_e.meta["output"]), r_e.meta["latents"], b["s"], b["e"], b["e"] - (n_take - E)
    short = (n_take - cfg["start_frame"] + cfg["gap_frames"]) / 24
    warnings.append(f"no stationary extension in {cfg['extend_attempts']} seeds: loop shortened to {short:.1f} s")
    engine.emit("extension.best_effort", {"loop_seconds": round(short, 1), "take_only": take_only})
    return take_mp4, take_mp4, take_lat, cfg["start_frame"], None, None


def _grow(engine: Engine, cfg: dict, best: dict, image: Path, gen_cfg: dict, lay, take_mp4: Path, take_lat: dict,
          ext_src: tuple | None, start_frame: int, scratch: Path, scene: Path | None, warnings: list):
    """ADR 0011: a short accepted loop is grown from the inside to the requested length; rollback (None) when it does
    not fit or the grown loop fails loop_qc. -> (candidate dict like the closures', review joins) or None."""
    n_loop = len(loopkit.read_frames(Path(best["loop"])))
    seg_end = start_frame + n_loop - lay.gap_frames
    p = grow.plan(n_loop, math.ceil(cfg["seconds"] * 24), start_frame, seg_end, cfg["take_frames"], ext_src is not None,
                  lay.E, lay.S)
    if p is None:
        return None
    src = {"take": (take_mp4, take_lat), "ext": ext_src}
    (end_kind, end_local), (start_kind, start_local) = p["end"], p["start"]
    end_v, end_l = src[end_kind]
    start_v, start_l = src[start_kind]
    seed = cfg["close_seeds"][0]
    try:
        r_c = engine.run_stage(
            "close", close.VERSION,
            {**gen_cfg, "seed": seed, "start_frame": start_local, "frames": lay.frames + p["G"] - lay.gap_frames,
             "prefix_latents": lay.prefix_latents, "gap_frames": p["G"], "end_frame": end_local},
            {"image": image, "end_video": end_v, "end_lat1": Path(end_l["stage1"]), "end_lat2": Path(end_l["stage2"]),
             "start_video": start_v, "start_lat1": Path(start_l["stage1"]), "start_lat2": Path(start_l["stage2"])},
            lambda inp, c, out: close.run(inp, c, out, scratch_dir=scratch), seed=seed, key="close[grow]")
        r_rot = engine.run_stage("grow", grow.VERSION, {"start_frame": start_frame, "e": p["e"], "s": p["s"],
                                                        "old_gap": lay.gap_frames}, {"loop": Path(best["loop"])}, grow.run)
        r_sp = engine.run_stage("splice", splice.VERSION, {"start_frame": 0, "E": lay.E, "G": p["G"], "R": 8,
                                                           **({"tone": "none"} if gen_cfg.get("moving_light") else {})},
                                {"long": Path(r_rot.meta["output"]), "window": Path(r_c.meta["output"])}, splice.run,
                                key="splice[grow]")
        qc_in = {"loop": Path(r_sp.meta["output"]), "reference": take_mp4, "window": Path(r_c.meta["output"])}
        if scene:
            qc_in["scene"] = Path(scene)
        r_q = engine.run_stage("loop_qc", loop_qc.VERSION, {"start_frame": cfg["start_frame"], "gap_start": r_sp.meta["gap_start"],
                                                            "ext_join": None, "E": lay.E, "G": p["G"],
                                                            **lull_mode(gen_cfg["prompt"])},
                               qc_in, loop_qc.run, key="loop_qc[grow]")
    except Exception as e:
        engine.emit("grow.failed", {"error": str(e), "plan": p})
        warnings.append(f"growing the loop failed ({e}); kept the accepted {n_loop / 24:.1f} s loop")
        return None
    if not r_q.meta["accept"]:
        engine.emit("grow.rejected", {"plan": p, "fails": r_q.meta["fails"], "closing_over_rest": r_q.meta["closing_over_rest"]})
        warnings.append(f"the grown loop failed loop_qc ({r_q.meta['fails']}); kept the accepted {n_loop / 24:.1f} s loop")
        return None
    secs = r_sp.meta["frames"] / 24
    warnings.append(f"loop grown from {n_loop / 24:.1f} s to {secs:.1f} s: a {p['G']}-frame generated passage replaced "
                    f"frames {p['e']}-{p['s']} (ADR 0011); both new joins are marked")
    engine.emit("grow.accepted", {"plan": p, "loop_seconds": round(secs, 1)})
    cand = {"seed": seed, "loop": r_sp.meta["output"], "gap_start": r_sp.meta["gap_start"], **r_q.meta,
            "old_closure_churn_worst": best.get("gap_churn_worst_cell")}  # the kept closure stays the weak spot
    return cand, {"grown passage": r_sp.meta["gap_start"], "wrap (grown passage ends)": 0,
                  "old closure": r_rot.meta["old_closure_at"]}


def _run(engine: Engine, image: Path, prompt: str, negative: str, cfg: dict, run_dir: Path, scene: Path | None,
         contract: dict | None = None) -> dict:
    scratch = run_dir / "_wangp_scratch"
    source = image  # the still as given (a motion donor renders from it, not from the fitted keyframe)
    gen_cfg = {"prompt": prompt, "negative_prompt": negative, "resolution": cfg["resolution"],
               # only when set: every existing run keeps its fingerprints (motion clock, experiments/speed, W1)
               **({"motion_speed": cfg["motion_speed"]} if cfg["motion_speed"] != 1.0 else {}),
               **({"guide_strength": cfg["guide_strength"]} if cfg["guide_strength"] != 1.0 else {}),
               **({"single_stage": True} if cfg["single_stage"] else {})}
    # an intended moving light (sweeping beam; realism amendment): exposure-only steady clause, raw generated frames
    # (no whole-frame tone target), and QC means over 5 s so the sweep is not read as drift. Keys only when true.
    moving = bool(motion_style.MOVING_LIGHT.search(prompt))
    gen_cfg.update({"moving_light": True} if moving else {})
    raw = {"tone": "none"} if moving else {}
    avg = {"average_s": 5} if moving else {}
    lengths = plan_lengths(cfg)
    ext = ["extend[0]", "join[0]"] if lengths["extension_window"] else []
    warnings = []
    size = [int(v) for v in cfg["resolution"].split("x")]
    from PIL import Image
    with Image.open(image) as im:
        fit, still_size = list(im.size) != size, list(im.size)
    if fit:  # --image at another size (odd heights break the encodes); unchanged when already at the loop size
        image = Path(engine.run_stage("fit", keyframe.FIT_VERSION, {"size": size}, {"image": image}, keyframe.fit_run)
                     .meta["output"])
    # --take-guide / --motion-donor (ADR 0016): another render of the still (the donor) is the take's moving depth guide,
    # retimed to donor_speed and framed exactly like the fitted keyframe; it starts from the still itself, so no settle
    guide, donor_video, donor_on, speed = {}, None, bool(cfg["motion_donor"]), cfg["donor_speed"]
    donor_cfg = {"prompt": prompt, "negative_prompt": negative, **({"moving_light": True} if moving else {})}
    if cfg["take_guide"] or donor_on:
        donor_video = Path(cfg["take_guide"]) if cfg["take_guide"] else held_donor(
            engine, "take", {**donor_cfg, "frames": donor.frames_for(cfg["take_frames"], speed)}, source, scratch,
            cfg["take_seed"], warnings)
        fg = {"size": size, "still_size": still_size, **({"speed": speed, "frames": cfg["take_frames"]} if donor_on else {})}
        guide = {"guide": Path(engine.run_stage("fit_guide", keyframe.FIT_VERSION, fg, {"video": donor_video},
                                                keyframe.fit_guide_run).meta["output"])}
        if cfg["settle"] is not False:
            engine.emit("settle.skipped", {"reason": "the take follows a moving guide that starts from the still"})
        cfg["settle"] = False
    if cfg["bloom"]:  # brilliance on the still's own pixels (stages/bloom.py); the take renders from it
        image = Path(engine.run_stage("bloom", bloom.VERSION, {"variant": cfg["bloom"]}, {"image": image}, bloom.run)
                     .meta["output"])
    still = image  # the review's detail reference: fitted, before settle replaces it with a generated frame
    if cfg["settle"]:  # a take from the image; its last frame = keyframe. "auto" (default): only a demonstrated start
        # transient in a scene with an accumulating medium (stages/settle.py); else the image stays and take[0] below
        # is this same render (cache hit). True / "always": the 2026-09-25 behaviour.
        r_s = engine.run_stage("take", take.VERSION, {**gen_cfg, "frames": cfg["take_frames"], "seed": cfg["take_seed"]},
                               {"image": image}, lambda inp, c, out: take.run(inp, c, out, scratch_dir=scratch),
                               seed=cfg["take_seed"], key="take[settle]")
        auto = {"mode": "auto", "accumulating": bool(direct.ACCUMULATING.search(prompt))} if cfg["settle"] == "auto" else {}
        r_sf = engine.run_stage("settle", settle.VERSION, {"frame": -1, **auto}, {"video": Path(r_s.meta["output"])},
                                settle.run)
        if r_sf.meta.get("use", True):
            image = Path(r_sf.meta["output"])
        else:
            engine.emit("settle.skipped", {"transient": r_sf.meta.get("transient"), **auto})
    engine.emit("run.plan", {"keyframe": str(image), "stages": [*(["fit"] if fit else []),
                *(["donor[take]"] if donor_on and not cfg["take_guide"] else []), *(["fit_guide"] if guide else []),
                *(["donor_start", "donor[return]", "fit_guide[return]", "return_guide"] if donor_on else []),
                *(["bloom"] if cfg["bloom"] else []),
                *(["take[settle]", "settle"] if cfg["settle"] else []),
                "take[0]", "take_qc[0]", *ext,
                *[f"{st}[{sd}]" for sd in cfg["close_seeds"] for st in ("close", "splice", "loop_qc")], "deliver", "review"]})

    r_take = None
    tried = []
    for i in range(cfg["take_attempts"]):
        seed = cfg["take_seed"] + i
        r = engine.run_stage("take", take.VERSION, {**gen_cfg, "frames": cfg["take_frames"], "seed": seed},
                             {"image": image, **guide}, lambda inp, c, out: take.run(inp, c, out, scratch_dir=scratch),
                             seed=seed, key=f"take[{i}]")
        q = engine.run_stage("take_qc", take_qc.VERSION, {"skip": 48, "region_drift_max": cfg["region_drift_max"], **avg},
                             {"video": Path(r.meta["output"])}, take_qc.run, seed=seed, key=f"take_qc[{i}]")
        if q.meta["accept"]:
            r_take = r
            break
        tried.append((r, q))
        engine.emit("take.rejected", {"seed": seed, "luma_drift": q.meta["luma_drift"],
                                      "region_drift_max": q.meta["region_drift_max"],
                                      "camera_shift_px": q.meta.get("camera_shift_px")})
    if r_take is None:
        # best effort (user decision 2026-09-25): the steadiest take if it is at the very-slight level (6.7 grey was
        # rated very slight in review on two scenes) and its global/camera gates pass; otherwise stop
        ok = [(r, q) for r, q in tried if q.meta["luma_drift"] <= take_qc.LUMA_DRIFT_MAX
              and q.meta.get("camera_shift_px", 0) <= take_qc.CAMERA_SHIFT_MAX_PX
              and q.meta["region_pulse_max"] <= take_qc.REGION_PULSE_MAX
              and q.meta["region_drift_max"] <= cfg["fallback_drift_max"]]
        if not ok:
            raise RuntimeError(f"no usable take in {cfg['take_attempts']} seeds (region drift "
                               f"{[q.meta['region_drift_max'] for _, q in tried]} grey; limit {cfg['fallback_drift_max']})")
        r_take, q = min(ok, key=lambda rq: rq[1].meta["region_drift_max"])
        warnings.append(f"take drift {q.meta['region_drift_max']} grey (> {cfg['region_drift_max']}): expect a very slight "
                        f"seam at the loop point")
        engine.emit("take.best_effort", {"seed": r_take.meta["settings"]["seed"], "region_drift_max": q.meta["region_drift_max"]})
    take_mp4 = Path(r_take.meta["output"])
    take_lat = r_take.meta["latents"]
    if cfg["audition"]:  # content review before any closure / growth / 4K is spent on this take
        seed = r_take.meta["settings"]["seed"]
        r_a = engine.run_stage(
            "audition", audition.VERSION,
            {"title": engine.run_id, "run_id": engine.run_id, "original_prompt": engine.manifest["original_prompt"],
             "prompt": prompt, "negative": negative, "checklist": (contract or {}).get("checklist"), "seed": seed,
             "timing": {"take minutes": round(json.loads((r_take.out_dir / "stage.json").read_text(encoding="utf-8"))
                                              ["duration_s"] / 60, 1), "take peak": r_take.meta.get("peak_hw")},
             "gates": {"take drift (grey)": q.meta["region_drift_max"], "camera shift (px)": q.meta.get("camera_shift_px")},
             "resume": cfg["cli"] or f"<WanGP python> -m looper loop --run-id {engine.run_id} --audition ..."},
            {"video": take_mp4, "settings": r_take.out_dir / "settings.json"}, audition.run)
        _gate(engine, run_dir, "take", _ref(f"take (seed {seed})", r_take, take_mp4, contract),
              {"review": r_a.meta["output"], "video": r_a.meta["video"], "crops": r_a.meta["crops"],
               "resume": cfg["cli"] or "", "subject": "take"})

    r_ext = r_join = None
    start_frame, end_frame, end_local = cfg["start_frame"], None, None  # end_frame: a cut (endpoint stage), else the whole long
    if lengths["extension_window"]:
        tried_ext = []
        for i in range(cfg["extend_attempts"]):
            seed = cfg["take_seed"] + 95 + i
            r_e = engine.run_stage(
                "extend", extend.VERSION,
                {**gen_cfg, "window": lengths["extension_window"], "seed": seed,
                 "alpha": cfg["alpha"], "prefix_latents": cfg["prefix_latents"]},
                {"image": image, "take": take_mp4, "take_lat1": Path(take_lat["stage1"]), "take_lat2": Path(take_lat["stage2"])},
                lambda inp, c, out: extend.run(inp, c, out, scratch_dir=scratch), seed=seed, key=f"extend[{i}]")
            r_j = engine.run_stage("join", join.VERSION, {"E": r_e.meta["E"], "R": 8, "start_frame": cfg["start_frame"],
                                    "region_drift_max": cfg["region_drift_max"], **raw, **avg},
                                   {"take": take_mp4, "window": Path(r_e.meta["output"])}, join.run, seed=seed, key=f"join[{i}]")
            if r_j.meta["accept"]:
                r_ext, r_join = r_e, r_j
                break
            tried_ext.append((r_e, r_j))
            engine.emit("extension.rejected", {"seed": seed, "luma_drift": r_j.meta["luma_drift"],
                                               "region_drift_max": r_j.meta["region_drift_max"]})
        if r_ext is None:  # same best-effort rule as the take: the steadiest long take <= fallback_drift_max, with a
            # warning (dir_furnace: 4.26 / 5.47 grey lost the whole 30 s; review rated 6.1-6.9 very slight)
            ok = [(e, j) for e, j in tried_ext if j.meta["luma_drift"] <= take_qc.LUMA_DRIFT_MAX
                  and j.meta["region_pulse_max"] <= take_qc.REGION_PULSE_MAX
                  and j.meta["region_drift_max"] <= cfg["fallback_drift_max"]]  # join: same camera, no camera gate
            if ok:
                r_ext, r_join = min(ok, key=lambda ej: ej[1].meta["region_drift_max"])
                warnings.append(f"extension drift {r_join.meta['region_drift_max']} grey (> {cfg['region_drift_max']}): "
                                f"expect a very slight change over the loop")
                engine.emit("extension.best_effort", {"seed": r_ext.meta["settings"]["seed"],
                                                      "region_drift_max": r_join.meta["region_drift_max"]})
        if r_ext is None:  # a shorter loop: the easiest legal cut of what exists (endpoint stage), else take-only
            long_mp4, end_mp4, end_lat, start_frame, end_frame, end_local = _shorter_cut(
                engine, cfg, take_mp4, take_lat, tried_ext, warnings)
        else:
            long_mp4, end_mp4, end_lat = Path(r_join.meta["long"]), Path(r_ext.meta["output"]), r_ext.meta["latents"]
    else:
        long_mp4, end_mp4, end_lat = take_mp4, take_mp4, take_lat

    if cfg["long_return"]:  # ADR 0012 (default when it fits): keep the take's calmest stretch, one return fills the loop to length
        target = math.ceil(cfg["seconds"] * 24)
        s_cut, e_cut, calm = loopkit.calmest_segment(loopkit.read_frames(take_mp4), max(8, target - MAX_GAP),
                                                     cfg["take_frames"] - cfg["start_frame"], first=close.MIN_START_FRAME)
        start_frame, end_frame, end_local = s_cut, e_cut, e_cut
        long_mp4, end_mp4, end_lat = take_mp4, take_mp4, take_lat
        cfg["gap_frames"] = max(32, target - (e_cut - s_cut))
        cfg["close_frames"] = DEFAULTS["close_frames"] + cfg["gap_frames"] - 32
        engine.emit("long_return.cut", {"start": s_cut, "end": e_cut, "gap": cfg["gap_frames"], "drift": calm})
    close_guide, donor_wrap = {}, None
    if donor_on:  # ADR 0016: the return follows a donor continuation from the loop's end; its length (the target gap or
        # up to 64 frames less) is where the continuation runs best into the loop's first frames
        start_png = Path(engine.run_stage("donor_start", donor.START_VERSION,
                                          {"frame": donor.start_frame(e_cut, speed), "still_size": still_size},
                                          {"video": donor_video}, donor.start_run).meta["output"])
        g_hi = cfg["gap_frames"]
        cont = held_donor(engine, "return", {**donor_cfg, "frames": donor.frames_for(g_hi + 10, speed)}, start_png,
                          scratch, cfg["take_seed"], warnings)
        cont_guide = Path(engine.run_stage(
            "fit_guide", keyframe.FIT_VERSION, {"size": size, "still_size": still_size, **({"speed": speed} if speed != 1 else {})},
            {"video": cont}, keyframe.fit_guide_run, key="fit_guide[return]").meta["output"])
        E = loopkit.ctx_frames(cfg["prefix_latents"])
        rg = engine.run_stage("return_guide", donor.GUIDE_VERSION,
                              {"start": s_cut, "end": e_cut, "E": E, "S": DEFAULTS["close_frames"] - E - 32,
                               "gaps": list(range(max(32, g_hi - 64), g_hi + 1, 8))},
                              {"take_guide": guide["guide"], "cont_guide": cont_guide}, donor.return_guide_run).meta
        cfg["gap_frames"], cfg["close_frames"] = rg["G"], DEFAULTS["close_frames"] + rg["G"] - 32
        close_guide, donor_wrap = {"guide": Path(rg["output"])}, rg
        engine.emit("donor.return_guide", {"gap": rg["G"], "score": rg["score"], "scores": rg["scores"]})
    lay = loopkit.CloseLayout(cfg["close_frames"], cfg["prefix_latents"], cfg["gap_frames"])
    candidates, errors = [], []
    for seed in cfg["close_seeds"]:
        try:
            r_close = engine.run_stage(
                "close", close.VERSION,
                {**gen_cfg, "seed": seed, "start_frame": start_frame, "frames": lay.frames,
                 "prefix_latents": lay.prefix_latents, "gap_frames": lay.gap_frames,
                 **({"end_frame": end_local} if end_frame else {})},
                {"image": image, "end_video": end_mp4, "end_lat1": Path(end_lat["stage1"]), "end_lat2": Path(end_lat["stage2"]),
                 "start_video": take_mp4, "start_lat1": Path(take_lat["stage1"]), "start_lat2": Path(take_lat["stage2"]),
                 **close_guide},
                lambda inp, c, out: close.run(inp, c, out, scratch_dir=scratch), seed=seed, key=f"close[{seed}]")
            r_splice = engine.run_stage(
                "splice", splice.VERSION, {"start_frame": start_frame, "E": lay.E, "G": lay.gap_frames, "R": 8,
                                           **({"end_frame": end_frame} if end_frame else {}), **raw},
                {"long": long_mp4, "window": Path(r_close.meta["output"])}, splice.run, seed=seed, key=f"splice[{seed}]")
            qc_inputs = {"loop": Path(r_splice.meta["output"]), "reference": take_mp4, "window": Path(r_close.meta["output"])}
            if scene:
                qc_inputs["scene"] = Path(scene)
            r_qc = engine.run_stage(
                "loop_qc", loop_qc.VERSION,
                {"start_frame": start_frame, "gap_start": r_splice.meta["gap_start"], "E": lay.E, "G": lay.gap_frames,
                 "ext_join": r_join.meta["splice"] - start_frame if r_join is not None else None,
                 **({"moving_light": True} if moving else {}), **lull_mode(prompt)},
                qc_inputs, loop_qc.run, seed=seed, key=f"loop_qc[{seed}]")
        except Exception as e:
            engine.emit("closure.failed", {"seed": seed, "error": str(e)})
            errors.append(f"seed {seed}: {str(e)[:300]}")
            continue
        candidates.append({"seed": seed, "loop": r_splice.meta["output"], "gap_start": r_splice.meta["gap_start"], **r_qc.meta})
        if cfg["early_accept"] and clearly_clean(candidates[-1]) and seed != cfg["close_seeds"][-1]:
            engine.emit("closure.early_accept", {"seed": seed, "closing_over_rest": r_qc.meta["closing_over_rest"],
                                                 "gap_churn_worst_cell": r_qc.meta.get("gap_churn_worst_cell"),
                                                 "skipped": cfg["close_seeds"][cfg["close_seeds"].index(seed) + 1:]})
            break

    accepted = [c for c in candidates if c["accept"]]
    if not accepted:
        # failure packet (plan 2026-09-26 §4.11): the user still gets a review of the least-bad closure, marked FAILED,
        # so the review shows WHAT failed; nothing is delivered and the run fails
        why = (f"no closure passed loop_qc: {[(c['seed'], c['closing_over_rest'], flags(c)) for c in candidates]}"
               if candidates else f"every closure failed to render: {errors}")
        if candidates:
            worst = min(candidates, key=lambda c: (c["closing_over_rest"], len(c["fails"])))
            r_rev = engine.run_stage("review", review.VERSION,
                                     {"joins": {"closure gap": worst["gap_start"]}, "metrics": {"closure seed": worst["seed"]},
                                      "warnings": [f"FAILED — {why}", *warnings], "title": f"{engine.run_id} (FAILED)", "crf": 20},
                                     {"loop": Path(worst["loop"])}, review.run, key="review[failed]")
            engine.emit("review.ready", {"md": r_rev.meta["output"], "video": r_rev.meta["video"], "doubt": r_rev.meta["doubt"],
                                         "failed": True})
        raise RuntimeError(why)
    # ratios within 0.05 are noise (seeds 306/307/308 of one take: 0.985-1.021): then fewer flags, then the calmer gap
    best = min(accepted, key=lambda c: (round(c["closing_over_rest"] / 0.05), len(c["fails"]), c["closing_mean"]))
    engine.emit("closure.selected", {"seed": best["seed"], "closing_over_rest": best["closing_over_rest"],
                                     "candidates": [(c["seed"], c["accept"], c["closing_over_rest"]) for c in candidates]})
    joins = {"closure gap": best["gap_start"]}
    ext_src = (end_mp4, end_lat) if Path(end_mp4) != Path(take_mp4) else None
    # a donor loop keeps its length: an unguided interior bridge would freeze the donor's motion again (ADR 0016)
    grown = None if donor_on else _grow(engine, cfg, best, image, gen_cfg, lay, take_mp4, take_lat, ext_src,
                                        start_frame, scratch, scene, warnings)
    if grown is not None:
        best, joins = grown
    r_del = engine.run_stage("deliver", deliver.VERSION, {"repeats": cfg["repeats"], "block_periods": cfg["block_periods"], "crf": 17},
                             {"loop": Path(best["loop"])}, deliver.run)
    if r_join is not None and grown is None:
        joins["extension join"] = r_join.meta["splice"] - start_frame
    metrics = {"take drift (grey)": (q.meta["region_drift_max"], cfg["region_drift_max"]),
               "take pulse (grey)": (q.meta["region_pulse_max"], take_qc.REGION_PULSE_MAX),
               "closure step vs rest": (best["closing_over_rest"], loop_qc.CLOSING_OVER_REST_MAX),
               "closure gap activity (mean step)": (best["closing_mean"], loop_qc.CLOSING_MEAN_MAX),
               **({"closure texture churn (vs its contexts)": (best["gap_churn"], loop_qc.GAP_CHURN_MAX),
                   "closure texture churn, worst region": (best["gap_churn_worst_cell"], loop_qc.GAP_CHURN_WORST_MAX)}
                  if best.get("gap_churn") is not None else {}),
               **({"slow drift over the loop (grey, worst region)": (best["loop_drift"], loop_qc.LOOP_DRIFT_MAX)}
                  if best.get("loop_drift") is not None else {}),
               **({"kept closure texture churn, worst region": (best["old_closure_churn_worst"], loop_qc.GAP_CHURN_WORST_MAX)}
                  if best.get("old_closure_churn_worst") is not None else {}),
               "loop_qc flags": "; ".join(flags(best)) or "none", "natural spikes": " ".join(best.get("natural_spikes", [])) or "none",
               **({"calm lulls passed (not freezes)": "; ".join(f"{x['flag']} ({x['where']}, {x['longest_s']} s)"
                                                               for x in best["lulls"])} if best.get("lulls") else {}),
               "closure seed": best["seed"],
               **({"motion donor (speed, return gap, wrap distance)": f"{speed}x, {donor_wrap['G']} f, {donor_wrap['score']}"}
                  if donor_wrap else {})}
    if r_join is not None:
        metrics["extension drift (grey)"] = (r_join.meta["region_drift_max"], cfg["region_drift_max"])
    r_rev = engine.run_stage("review", review.VERSION,
                             {"joins": joins, "metrics": metrics, "warnings": warnings, "title": engine.run_id, "crf": 20,
                              "checklist": (contract or {}).get("checklist"), **({"periodic": True} if motion_style.ROTATING_BEAM.search(prompt) else {}),
                              "contract_status": (contract or {}).get("status")},
                             {"loop": Path(best["loop"]), "reference": take_mp4, "still": still}, review.run)
    engine.emit("review.ready", {"md": r_rev.meta["output"], "video": r_rev.meta["video"], "doubt": r_rev.meta["doubt"]})
    from looper import acceptance
    loop_ref = _ref("loop (review)", r_rev, Path(best["loop"]), contract)
    decided = acceptance.decision(run_dir, "loop", loop_ref)
    if cfg["final_4k"]:  # ~2.6 h of finishing only on a loop a human accepted (handoff §12)
        decided = _gate(engine, run_dir, "loop", loop_ref, {"review": r_rev.meta["output"], "video": r_rev.meta["video"],
                                                            "resume": cfg["cli"] or "", "subject": "loop"})
    four_k = final_4k(engine, Path(best["loop"]), cfg, run_dir) if cfg["final_4k"] else None
    gap = (contract or {}).get("status") == "missing"
    outcome = "rejected" if decided and decided["status"] == "rejected" else "best_effort" if gap else \
        decided["status"] if decided else "needs_review"
    return {"run_id": engine.run_id, "outcome": outcome, "final_video": r_del.meta["output"], "loop": r_del.meta["loop"],
            "final_4k": four_k,
            "review": r_rev.meta["output"], "review_video": r_rev.meta["video"], "review_doubt": r_rev.meta["doubt"],
            "loop_seconds": round(len(loopkit.read_frames(Path(best["loop"]))) / 24, 2), "closure_seed": best["seed"],
            "candidates": [{k: c[k] for k in ("seed", "accept", "closing_over_rest", "fails")} for c in candidates],
            "extension_window": lengths["extension_window"], "keyframe": str(image), "warnings": warnings}
