"""Front end of `python -m looper loop` (spec docs/superpowers/specs/2026-09-25-director-design.md):
director -> [3 keyframes -> critic -> pause for approval unless --auto/--approve] -> (image, prompt, negative) for
the unchanged loop recipe. With --image: director only; the user's image is the keyframe."""
from __future__ import annotations

import json
from pathlib import Path

from looper import contract, motion_style
from looper.adapters import wangp
from looper.engine import Engine
from looper.stages import direct, keyframe, keyframe_qc

# (provider, model, director thinks). local: qwen3.6 MoE with thinking beat gemma4:12b and itself without thinking on
# unloopable prompts (research/director.md). claude = the Claude Code CLI on the user's login, model None = its
# default (Codex / Gemini CLIs may follow). The critic never thinks (3 calls per run; speed first until measured).
DIRECTORS = {"local": ("ollama", "qwen3.6:35b", True), "claude": ("claude", None, False)}
KEYFRAME_SIZE = [832, 480]


class AwaitingApproval(Exception):
    def __init__(self, info: dict):
        super().__init__(f"keyframe awaiting approval: {info['review']}")
        self.info = info


def prepare(engine: Engine, prompt: str, image: Path | None, cfg: dict, run_dir: Path) -> dict:
    provider, model, think = DIRECTORS[cfg["director"]]
    model = cfg.get("director_model") or model
    seeds = cfg["keyframe_seeds"]
    if cfg.get("keyframe") is not None and not 0 <= cfg["keyframe"] < len(seeds):
        raise ValueError(f"--keyframe {cfg['keyframe']}: choose 0..{len(seeds) - 1}")
    if not image:
        engine.emit("run.plan", {"stages": [*([] if cfg["raw_prompt"] else ["direct"]),
                                            *[f"keyframe[{i}]" for i in range(len(seeds))],
                                            *[f"keyframe_qc[{i}]" for i in range(len(seeds))]]})
    direct_cfg = {"prompt": prompt, "provider": provider, "model": model, "think": think, "raw": bool(cfg["raw_prompt"])}
    paused = Path(run_dir) / "review" / "paused.json"
    if cfg["approve"] and not image and paused.exists():
        # final review #1: a changed prompt / director flag would re-direct and render stills nobody reviewed
        was = json.loads(paused.read_text(encoding="utf-8"))
        if was["direct"] != direct_cfg:
            raise ValueError(f"--approve must repeat the paused run's prompt and director flags exactly; paused with "
                             f"{was['direct']}, got {direct_cfg}. Use the resume command in review/review.md.")
    if cfg["raw_prompt"]:
        d = {"keyframe_prompt": prompt, "motion_prompt": prompt, "negative": motion_style.BASE_NEGATIVE,
             "warnings": [], "adaptations": []}
    else:
        d = engine.run_stage("direct", direct.VERSION, {"prompt": prompt, "provider": provider, "model": model,
                                                        "think": think},
                             {"image": Path(image)} if image else {}, direct.run).meta
    warnings = list(d["warnings"])
    # one line: WanGP splits a multi-line prompt into one generation per line (dir_furnace: 29 requests, take failed)
    d = {**d, "motion_prompt": " ".join(d["motion_prompt"].split())}
    # the user's requirements are checked against the plan and win over it (handoff 2026-09-27 §6, looper/contract.py)
    selected = ". ".join(d.get("proposed_moving") or [])  # the director's first proposal (pre-retry), kept by contract
    c = engine.run_stage("contract", contract.VERSION,
                         {"prompt": prompt, "plan": {"motion_prompt": d["motion_prompt"], "negative": d["negative"]},
                          **({"selected": selected} if selected else {})},
                         {"image": Path(image)} if image else {}, contract.run).meta
    d = {**d, **c["plan"], "checklist": c["checklist"]}
    if not image and c.get("framing"):  # prompt-only: the still gives the defining effects room (a user image: never)
        d["keyframe_prompt"] = f"{d['keyframe_prompt'].rstrip()} {' '.join(c['framing'])}"
    warnings += c["warnings"]
    con = {k: c[k] for k in ("output", "status", "checklist", "contract_sha")}
    # director self-check, before any GPU time: catches a pasted markdown brief (dir_furnace: 5.8k chars, '#' headers);
    # 1500 was arbitrary and stopped a 1586-char plan (crawler_720) that LTX's text encoder takes easily
    if len(d["motion_prompt"]) > 2500 or "#" in d["motion_prompt"]:
        raise ValueError(f"director produced an unrenderable prompt ({len(d['motion_prompt'])} chars): "
                         f"{d['motion_prompt'][:200]}...")
    if image:
        return {"image": Path(image), "prompt": d["motion_prompt"], "negative": d["negative"], "warnings": warnings,
                "contract": con}

    scratch = Path(run_dir) / "_wangp_scratch"
    size = [int(v) for v in cfg["resolution"].split("x")] if cfg.get("resolution") else KEYFRAME_SIZE
    kfs = [engine.run_stage("keyframe", keyframe.VERSION, {"prompt": d["keyframe_prompt"], "seed": s,
                                                           "size": size}, {},
                            lambda inp, c, out: keyframe.run(inp, c, out, scratch_dir=scratch), seed=s,
                            key=f"keyframe[{i}]") for i, s in enumerate(seeds)]
    wangp._free_gpu()  # Z-Image out of VRAM before the vision model loads (6 GB card)
    cands = []
    for i, (s, k) in enumerate(zip(seeds, kfs)):
        q = engine.run_stage("keyframe_qc", keyframe_qc.VERSION,
                             {"brief": d["keyframe_prompt"], "motion": d["motion_prompt"], "provider": provider,
                              "model": model}, {"image": Path(k.meta["output"])}, keyframe_qc.run, seed=s,
                             key=f"keyframe_qc[{i}]")
        cands.append({"index": i, "seed": s, "image": k.meta["output"],
                      **{x: q.meta[x] for x in ("accept", "total", "scores", "hard_fails", "notes")}})
    best, warn = keyframe_qc.pick(cands)
    if warn:
        warnings.append(warn)
    chosen = best if cfg.get("keyframe") is None else cfg["keyframe"]
    if not (cfg["auto"] or cfg["approve"]):
        flags = "".join([f" --director {cfg['director']}" if cfg["director"] != "local" else "",
                         f" --director-model {cfg['director_model']}" if cfg.get("director_model") else "",
                         " --raw-prompt" if cfg["raw_prompt"] else ""])
        resume = (f"<WanGP python> -m looper loop --run-id {engine.run_id} --prompt \"{prompt.replace(chr(34), chr(92) + chr(34))}\""
                  f"{flags} --approve [--keyframe N]")
        review = write_review(Path(run_dir), engine.run_id, prompt, d, cands, best, warnings, resume)
        paused.write_text(json.dumps({"direct": direct_cfg, "keyframes": [c["image"] for c in cands]}, indent=1),
                          encoding="utf-8")
        info = {"review": str(review), "chosen": best, "keyframes": [c["image"] for c in cands],
                "scores": [c["total"] for c in cands], "warnings": warnings, "resume": resume}
        engine.emit("run.awaiting_approval", info)
        raise AwaitingApproval(info)
    engine.emit("run.approved", {"keyframe": chosen, "auto": bool(cfg["auto"])})
    return {"image": Path(cands[chosen]["image"]), "prompt": d["motion_prompt"], "negative": d["negative"],
            "warnings": warnings, "contract": con}


def write_review(run_dir: Path, run_id: str, prompt: str, d: dict, cands: list[dict], best: int,
                 warnings: list[str], resume: str = "") -> Path:
    """Review file (title, what to look at, one question) + a side-by-side sheet of the keyframes."""
    from PIL import Image, ImageDraw
    out = run_dir / "review"
    out.mkdir(parents=True, exist_ok=True)
    ims = [Image.open(c["image"]).convert("RGB") for c in cands]
    w, h = ims[0].size
    sheet = Image.new("RGB", (w * len(ims), h + 28), (12, 12, 12))
    draw = ImageDraw.Draw(sheet)
    for i, (im, c) in enumerate(zip(ims, cands)):
        sheet.paste(im, (i * w, 28))
        mark = "  <- pick" if i == best else ""
        draw.text((i * w + 8, 6), f"#{i} seed {c['seed']}  {c['total']}/20{'' if c['accept'] else ' (fails)'}{mark}",
                  fill=(255, 255, 255))
    sheet.save(out / "keyframes.jpg", quality=90)
    lines = [f"# Keyframe approval: {run_id}", "",
             "Look at: does the picked still match what you asked for, and is steam/mist already at full strength?",
             "", "![keyframes](keyframes.jpg)", "", f"**Your prompt:** {prompt}", "",
             f"**Keyframe prompt:** {d['keyframe_prompt']}", "", f"**Motion prompt:** {d['motion_prompt']}", ""]
    if d.get("adaptations"):
        lines += ["**Changed so it can loop:**"] + [f"- {a['asked']} -> {a['changed_to']} ({a['why']})"
                                                   for a in d["adaptations"]] + [""]
    if d.get("checklist"):
        lines += ["**Required (from your words):**", *d["checklist"], ""]
    lines += [f"- #{c['index']}: {c['total']}/20 {c['scores']} {'; '.join(c['hard_fails'])} {c['notes']}" for c in cands]
    lines += [""] + [f"Warning: {w}" for w in warnings]
    lines += ["", f"Question: render #{best}? (`--approve`, or `--approve --keyframe N` for another)", "",
              f"Resume: `{resume}`"]
    path = out / "review.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    (out / "candidates.json").write_text(json.dumps(cands, indent=1), encoding="utf-8")
    return path
