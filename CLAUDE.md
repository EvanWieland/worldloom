# worldloom — guide for Claude Code

Pipeline: one still image (or a keyframe the director writes) + a prompt → one cinematic 30–60 s forward-motion loop
whose last frame flows seamlessly into its first; hours of playback = plain looping of that file.

Read `README.md` for the overview, `ARCHITECTURE.md` for the design, `QUALITY.md` for the gates, `DECISIONS/` for why
things are the way they are and `research/` for the evidence behind them. Read the decision records and research notes
that touch a change before making it.

## Critical invariants

Do not violate these without a decision record (`DECISIONS/`) backed by evidence.

1. **Quality matters** — the target is cinematic, not novelty AI video.
2. **Iterate cheaply** — never run a final-quality render to find out whether an idea works: short diagnostic renders
   first, then a full take, then the loop, then 4K (gates in `QUALITY.md`).
3. **Every expensive stage is recoverable** — a late failure never forces rerunning earlier stages.
4. **Artifacts are first-class** — every stage persists its outputs and metadata (`stage.json`); nothing important lives
   only in memory.
5. **Previous work stays reusable unless its inputs actually changed** — invalidation is by fingerprint, never
   "rebuild everything".
6. **Observability is architecture** — the engine emits structured events (`looper/events.py` is the only writer);
   the dashboard only observes. No business logic in the dashboard.
7. **Works locally** at useful quality on a 6 GB laptop GPU with 64 GB RAM. Degrade gracefully, don't crash.
8. **Compute location is an execution concern**, not a scene-design concern. No stage may assume all stages share one
   machine.
9. **Models and providers are replaceable** — no vendor SDK types outside the adapters (`looper/adapters/`,
   `looper/models.py`); record execution metadata for every model call.
10. **Looping is designed in, not patched on**: the closure is *generated* (conditioned on the loop's end and start
    frames) and never a cross-fade — the only exception is ramping between two renders of the *same instant* inside a
    context overlap (ADR 0006, 0009) — and every closure is gated on motion across its whole length, not just the join
    frames (ADR 0005). Mathematically seamless ≠ visually seamless ≠ perceptually non-repetitive: three problems.
11. **The user's prompt is authoritative.** Keep the original prompt and the enhanced spec side by side; every inferred
    creative decision is traceable (what, why, which stage / model).
12. **Generative video is the backbone** (ADR 0003): no mask-and-animate of stills, no region masks to steer or patch
    parts of a scene.
13. **Local GPU for development and validation**; a rented GPU only for final renders or budget-capped experiments
    (ADR 0014). A hosted LLM may run the director when a run opts in (`--director claude`, ADR 0008).
14. **Research uncertain assumptions**; don't silently turn them into architecture. Label hypotheses as hypotheses.
15. **Secrets never reach logs, events, manifests or state files.** Keys come from environment variables only; the
    engine redacts secret-named keys and credential-shaped text (`looper/engine.py` `redact()`).

## Rules for changing things

- **Resumability:** any change to a stage's logic that can change its output must bump that stage's `VERSION` (it is
  part of the fingerprint). Never mutate a persisted artifact in place. Never write outside the stage's own output
  directory.
- **Decisions:** a consequential choice gets a decision record before the code (`DECISIONS/NNNN-slug.md`, template in
  `DECISIONS/README.md`). Abstractions must serve a demonstrated substitution need — one implementation = no interface.
- **Docs:** durable design → `ARCHITECTURE.md` / `DECISIONS/`; experiment conclusions + evidence → `research/<topic>.md`.
  Superseded content is updated or deleted, not left to rot.
- **Scope:** prefer vertical slices; prove changes on real scenes, including the ones that make the pipeline look bad.
  Earn complexity incrementally. Evidence over familiarity; profile before optimizing.
- **Generic methods only:** per-scene hand tuning is a probe, never a stage.

## Package layout

```
looper/
  engine.py          fingerprinting, run_stage(), manifest, events.jsonl, redaction
  hw.py              VRAM / RAM / GPU sampler
  models.py          LLM adapter: complete() / complete_json(); Ollama (default) + Claude Code CLI (opt-in, ADR 0008)
  front.py           front end: direct -> contract -> [keyframe x3 -> keyframe_qc x3 -> approval pause] (prompt-only)
  contract.py        scene contract (ADR 0013): the user's requirements vs the director's plan
  acceptance.py      human content decisions bound to fingerprint + output hash + contract (--audition, --4k gates)
  trace.py           stage comparison report: python -m looper trace RUN_ID
  periodic.py        periodic effects (rotating beams): phase sampling, whole-turn durations
  motion_style.py    proven LTX prompt clauses, as code
  loop_pipeline.py   run_loop(): take -> [extend] -> long return / closures -> splice -> loop_qc -> deliver -> review
  loopkit.py         frame helpers for the loop stages
  regional_qc.py     regional, source-relative loop QC
  __main__.py        CLI: python -m looper loop | accept | verdict | trace | prune | dash | hw | job
  adapters/          wangp.py (WanGP session, WANGP_ROOT), ltx.py (LTX patches, motion clock), hunyuan.py (motion
                     donor, ADR 0016), pose.py (person torso track for the donor hold check)
  events.py          the only event writer
  observe.py         event reader -> snapshot for the dashboard
  dashboard/         Textual TUI (read-only)
  stages/            one module per stage (direct, keyframe, take, take_qc, close, splice, loop_qc, review, upscale, ...)
tests/               unit tests, no GPU
runs/                run outputs (git-ignored), created by the pipeline
```

## Environment and commands

- The package runs in **WanGP's own Python environment** (https://github.com/deepbeepmeep/Wan2GP). Put the checkout
  beside this repository (`../Wan2GP` or `../tools/Wan2GP`) or set `WANGP_ROOT`. Below, `$PY` is WanGP's Python.
- Run from the repository root: `$PY -m looper loop --image STILL.png --prompt "..." --run-id my_loop` (all modes in
  the README). The same command resumes an interrupted run.
- Tests (fast, CPU only): `$PY -m unittest discover tests`. Tests that need cv2 / numpy / torch / textual self-skip
  under another Python; prefer WanGP's so every test runs.
- Dashboard: `$PY -m looper dash`, next to `$PY -m looper hw` (GPU telemetry).
- ffmpeg / ffprobe on `PATH`; Ollama for the director (default `qwen3.6:35b`), or `--raw-prompt`.
- One GPU job at a time: two jobs on a 6 GB card thrash. Long jobs (a loop takes about an hour) run detached.

## Testing expectations

- Engine logic (fingerprints, invalidation, resume, manifests, event emission) gets real automated tests — it is the
  part that must never silently break.
- Every stage writes a machine-readable validation result; objective checks are automated, subjective ones are flagged
  for human review (`QUALITY.md`).
- Never claim something works without running it. Report failures with their output.
