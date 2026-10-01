"""CLI: python -m looper loop --image KEYFRAME --prompt "..." [--seconds 30] [--run-id ID] ...
Must run under WanGP's venv python -- see CLAUDE.md Environment & commands.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"


def prune(older_than_days: float | None, delete: bool) -> None:
    import shutil
    from looper.engine import last_activity, stale_stage_dirs

    def size(p: Path) -> int:
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    now, total = time.time(), 0
    for run in sorted(p for p in RUNS_DIR.glob("*") if (p / "manifest.json").exists()):
        idle_days = (now - last_activity(run)) / 86400
        if idle_days < 1 / 24:  # an in-flight stage dir is not in the manifest yet
            print(f"skip {run.name}: active in the last hour")
            continue
        victims = [run] if older_than_days is not None and idle_days > older_than_days else stale_stage_dirs(run)
        for v in victims:
            n = size(v)
            total += n
            print(f"{n / 2**20:9.1f} MB  {v.relative_to(RUNS_DIR)}{'  (whole run)' if v == run else ''}")
            if delete:
                shutil.rmtree(v)
    print(f"{'deleted' if delete else 'would delete (dry run; --yes to delete)'}: {total / 2**30:.2f} GB")


def main() -> None:
    parser = argparse.ArgumentParser(prog="looper")
    sub = parser.add_subparsers(dest="command", required=True)

    loop_p = sub.add_parser("loop", help="keyframe image + scene prompt -> one seamless forward loop (ADR 0007)")
    loop_p.add_argument("--image", default=None, help="keyframe (omit: the director + Z-Image make one, then pause)")
    loop_p.add_argument("--prompt", default=None, help="scene + how it should move (the director completes it)")
    loop_p.add_argument("--prompt-file", default=None, help="read the prompt (or a whole brief) from a UTF-8 file")
    loop_p.add_argument("--auto", action="store_true", help="prompt-only: render the critic's pick without pausing")
    loop_p.add_argument("--approve", action="store_true", help="resume a paused --run-id and render")
    loop_p.add_argument("--keyframe", type=int, default=None, help="with --approve: render keyframe N instead")
    loop_p.add_argument("--director", choices=["local", "claude"], default=None,
                        help="director/critic: local Ollama (default) or the `claude` CLI on your login (ADR 0008)")
    loop_p.add_argument("--director-model", default=None, help="e.g. an Ollama model, or opus/sonnet for claude")
    loop_p.add_argument("--raw-prompt", action="store_true", help="skip the director: render the prompt as written")
    loop_p.add_argument("--4k", dest="final_4k", action="store_true",
                        help="also FlashVSR x4 the loop -> 3840x2160 HEVC (T3a local; ~13 s/frame, hours)")
    loop_p.add_argument("--final-minutes", type=float, default=None, help="length of final_4k.mp4 (default 60)")
    loop_p.add_argument("--negative", default=None)
    loop_p.add_argument("--seconds", type=float, default=None, help="loop length (default 30)")
    loop_p.add_argument("--take-seed", type=int, default=None)
    loop_p.add_argument("--close-seeds", default=None, help="comma-separated closure seeds (default 306,307,308)")
    loop_p.add_argument("--scene", default=None, help="optional regions JSON for loop_qc (default: automatic regions)")
    loop_p.add_argument("--repeats", type=int, default=None)
    loop_p.add_argument("--region-drift-max", type=float, default=None,
                        help="take_qc per-region drift limit in grey levels (default 4; calibration runs only)")
    loop_p.add_argument("--fallback-drift-max", type=float, default=None,
                        help="best-effort take drift limit when no take passes the strict gate (default 7.5); the "
                             "review still reports the take against the strict gate")
    loop_p.add_argument("--no-settle", action="store_true",
                        help="use --image as the keyframe as-is (default: settle only a demonstrated start transient "
                             "in a scene with smoke/mist/steam; see stages/settle.py)")
    loop_p.add_argument("--always-settle", action="store_true", help="the pre-2026-09-27 behaviour: always settle")
    loop_p.add_argument("--bloom", choices=["mild", "strong"], default=None,
                        help="highlight bloom on the keyframe's own pixels before the take (brilliance; stages/bloom.py)")
    loop_p.add_argument("--long-return", action=argparse.BooleanOptionalAction, default=None,
                        help="close with ONE long generated return sized to --seconds: no extension, no 32 f closure "
                             "(ADR 0012; default whenever one return window fits, i.e. ~30 s loops). "
                             "--no-long-return: the extension + 32 f closure route")
    loop_p.add_argument("--motion-speed", type=float, default=None,
                        help="GENERATION-side motion clock for every LTX stage (Slow-Motion-Control LoRA + scaled temporal "
                             "positions): 1 = native (no LoRA), 0.5 = the model renders 2x slower motion. Playback is "
                             "never retimed (24 fps)")
    loop_p.add_argument("--guide-strength", type=float, default=None,
                        help="depth-guide (camera lock) control strength for every LTX stage (default 1.0; 0.5 held the "
                             "camera on the furnace)")
    loop_p.add_argument("--single-stage", action="store_true",
                        help="LTX in one full-size pass (no half-size stage 1 + upscale): motion is decided at the full "
                             "size; research/harvester-drum.md (rotating drums re-synthesised at half size)")
    loop_p.add_argument("--resolution", default=None, help="LTX generation size WxH (default 832x480; e.g. 1280x704)")
    loop_p.add_argument("--take-guide", default=None, metavar="VIDEO",
                        help="EXPERIMENTAL (research/ltx-cloak-screen.md): another model's render of --image as the "
                             "take's moving depth guide instead of the held still (cloth motion transfer); >= the take's "
                             "frames, starts from the still; the return keeps the held-still guide; implies --no-settle")
    loop_p.add_argument("--motion-donor", action="store_true",
                        help="ADR 0016: Hunyuan 1.5 renders the scene's motion from the still (+ a continuation from "
                             "the loop's end); LTX follows it as a moving depth guide in the take AND the return (shape "
                             "motion: cloth, hair, flags). Implies --single-stage; ~+45-60 min locally. With "
                             "--take-guide VIDEO that video is the donor")
    loop_p.add_argument("--donor-speed", type=float, default=None,
                        help="play the donor's motion at this speed, (0, 1] (default 1; the spice cloak wanted 0.6)")
    loop_p.add_argument("--audition", action="store_true",
                        help="pause after the take for a content review (looper accept RUN take), before any closure")
    loop_p.add_argument("--run-id", default=None, help="reuse to resume a prior run")

    prune_p = sub.add_parser("prune", help="list (or with --yes delete) superseded stage outputs and old runs")
    prune_p.add_argument("--older-than", type=float, default=None, metavar="DAYS",
                         help="also remove whole runs with no event for this many days")
    prune_p.add_argument("--yes", action="store_true", help="delete (default: dry run)")

    verdict_p = sub.add_parser("verdict", help="record a human review verdict for a run (shown in the dashboard)")
    verdict_p.add_argument("run_id")
    verdict_p.add_argument("text")

    accept_p = sub.add_parser("accept", help="decide on a paused content gate: the take (--audition) or the loop (--4k)")
    accept_p.add_argument("run_id")
    accept_p.add_argument("subject", choices=["take", "loop"])
    accept_p.add_argument("--reject", action="store_true", help="reject: nothing downstream runs on this artifact")
    accept_p.add_argument("--best-effort", action="store_true", help="accept, but record that it is not fully right")
    accept_p.add_argument("--note", default="")

    trace_p = sub.add_parser("trace", help="stage comparison report of a run: where quality changes (runs/<id>/trace/)")
    trace_p.add_argument("run_id")

    job_p = sub.add_parser("job", help="export one stage as a reproducible job description (disabled: submits nothing)")
    job_p.add_argument("run_id")
    job_p.add_argument("key", help="manifest key, e.g. take[0]")

    sub.add_parser("hw", help="run the hardware telemetry sampler (Ctrl+C to stop)")
    sub.add_parser("dash", help="open the terminal dashboard")

    args = parser.parse_args()

    if args.command == "loop":
        from looper.adapters import wangp
        wangp.ensure_path()  # no WanGP checkout: say so now, not minutes later after the director's LLM call
        from looper.loop_pipeline import run_loop
        # fail before any GPU time: dir_furnace lost a director call to an image the encoder refused
        if bool(args.prompt) == bool(args.prompt_file):
            parser.error("give exactly one of --prompt / --prompt-file")
        prompt = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
        if not prompt.strip():
            parser.error("the prompt is empty")
        if args.motion_speed is not None and not 0 < args.motion_speed <= 1:
            parser.error("--motion-speed must be in (0, 1]")
        if args.guide_strength is not None and not 0 < args.guide_strength <= 1:
            parser.error("--guide-strength must be in (0, 1]")
        if args.resolution and not re.fullmatch(r"\d+x\d+", args.resolution):
            parser.error("--resolution must look like 1280x704")
        if args.image:
            from PIL import Image
            try:
                with Image.open(args.image) as im:
                    im.verify()
            except Exception as e:  # noqa: BLE001
                parser.error(f"--image {args.image}: not a readable image ({e})")
        if args.take_guide and not (args.image and Path(args.take_guide).is_file()):
            parser.error("--take-guide needs --image (the guide is a render of that still) and an existing video")
        if args.donor_speed is not None and not (args.motion_donor and 0 < args.donor_speed <= 1):
            parser.error("--donor-speed needs --motion-donor and a value in (0, 1]")
        run_id = args.run_id or f"loop_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        run_dir = RUNS_DIR / run_id
        config = {"seconds": args.seconds, "take_seed": args.take_seed, "repeats": args.repeats,
                  "region_drift_max": args.region_drift_max, "fallback_drift_max": args.fallback_drift_max, "settle": False if args.no_settle else True if args.always_settle else None, "bloom": args.bloom,
                  "close_seeds": [int(s) for s in args.close_seeds.split(",")] if args.close_seeds else None,
                  "auto": args.auto, "approve": args.approve, "keyframe": args.keyframe, "director": args.director,
                  "director_model": args.director_model, "raw_prompt": args.raw_prompt,
                  "final_4k": args.final_4k, "final_minutes": args.final_minutes,
                  "long_return": args.long_return, "motion_speed": args.motion_speed,
                  "guide_strength": args.guide_strength, "single_stage": args.single_stage or None, "resolution": args.resolution, "audition": args.audition or None,
                  "take_guide": str(Path(args.take_guide).resolve()) if args.take_guide else None,
                  "motion_donor": args.motion_donor or None, "donor_speed": args.donor_speed,
                  "cli": "<WanGP python> -m looper " + subprocess.list2cmdline(
                      sys.argv[1:] + ([] if args.run_id else ["--run-id", run_id]))}
        print(f"run_id={run_id}\nrun_dir={run_dir}", flush=True)
        t0 = time.time()
        result = run_loop(Path(args.image).resolve() if args.image else None, prompt, config, run_dir, run_id,
                          negative=args.negative, scene=Path(args.scene).resolve() if args.scene else None)
        print(json.dumps(result, indent=1))
        if result.get("status") == "awaiting_approval":
            print(f"paused: review {result['review']}\nresume: {result['resume']}")
        print(f"done in {time.time() - t0:.1f}s")
    elif args.command == "prune":
        prune(args.older_than, args.yes)
    elif args.command == "verdict":
        from looper import events
        if not (RUNS_DIR / args.run_id / "manifest.json").exists():
            sys.exit(f"no run {args.run_id!r} under {RUNS_DIR}")
        events.emit(RUNS_DIR / args.run_id / "events.jsonl", "verdict", {"text": args.text}, run_id=args.run_id)
    elif args.command == "accept":
        from looper import acceptance, events
        status = "rejected" if args.reject else "best_effort" if args.best_effort else "accepted"
        try:
            rec = acceptance.record(RUNS_DIR / args.run_id, args.subject, status, args.note)
        except FileNotFoundError as e:
            sys.exit(str(e))
        events.emit(RUNS_DIR / args.run_id / "events.jsonl", "review.decision", rec, run_id=args.run_id)
        print(f"{args.subject} {status}: {rec['output']}")
    elif args.command == "trace":
        from looper import trace
        if not (RUNS_DIR / args.run_id / "manifest.json").exists():
            sys.exit(f"no run {args.run_id!r} under {RUNS_DIR}")
        print(trace.report(RUNS_DIR / args.run_id))
    elif args.command == "job":
        from looper import job
        try:
            print(job.export(RUNS_DIR / args.run_id, args.key))
        except (KeyError, FileNotFoundError) as e:
            sys.exit(str(e))
    elif args.command == "hw":
        from looper.hw import run_sampler
        run_sampler()
    elif args.command == "dash":
        import datetime
        import threading
        from looper.dashboard.app import LooperDash
        from looper.hw import hw_path, run_sampler
        f = hw_path(datetime.date.today())
        if not f.exists() or time.time() - f.stat().st_mtime > 10:  # no `looper hw` running: sample in-process
            # ponytail: two dash windows opened together both sample (duplicate points); a lock file if that matters
            threading.Thread(target=run_sampler, daemon=True).start()
        LooperDash().run()


if __name__ == "__main__":
    main()
