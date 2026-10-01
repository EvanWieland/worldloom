# ARCHITECTURE

Status: **Phase 1 engine implemented and verified. The ADR 0005/0007 loop path is implemented (2026-09-25) as
`python -m looper loop` (`looper/loop_pipeline.py`)**: scene prompt [+ keyframe image] → one seamless forward loop.
A director front end (`looper/front.py`, 2026-09-25) completes every prompt and, without an image, makes and
self-checks the keyframe. The old `run` path (pool/ping-pong, ADR 0004) was removed 2026-09-25. T3, remote execution and
other benchmark scenes are not built.

## Front end (`looper/front.py`)

```
user prompt [+ image]
   ▼
[direct]            LLM facts (JSON; vision when an image is given) -> code composes keyframe / motion / negative
   │                prompts from motion_style clauses. Image path: the user's words verbatim + missing fixed clauses.
   ▼
[contract]          CPU (ADR 0013 as amended): requirements from the user's words + the director's selected defining
   │                effects (beam, machinery, sea, light shafts; first proposal and final plan both count). Checks the
   │                plan (motion prompt + negative), puts back an omitted element (a static glow for a sweep counts
   │                as omitted), drops a negative naming a required element; records a technical plan (route,
   │                controls, evaluation) per requirement; prompt-only runs get framing clauses in the keyframe
   │                prompt. Runs on --raw-prompt too.
   ▼  prompt-only
[keyframe] × 3      Z-Image 1280x720 -> cover-crop to 832x480, seeds 1000..1002
[keyframe_qc] × 3   vision critic scores vs the brief; front picks the best (best effort + warning if none passes)
   ▼
pause (default)     run.awaiting_approval + runs/<id>/review/{review.md, keyframes.jpg}; exit.
                    `--approve [--keyframe N]` resumes from cache; `--auto` never pauses.
   ▼
loop pipeline below (the chosen keyframe or the user's image; the director's motion prompt + negative)
```
Director/critic model: local `qwen3.6:35b` via Ollama by default (director with thinking, critic without;
`research/director.md` §1b); `--director claude` (ADR 0008) runs the Claude Code
CLI headless on the user's login. Every Ollama call unloads its model before a WanGP stage (6 GB card).

## Loop pipeline (ADR 0007; `looper/loop_pipeline.py`, stages in `looper/stages/`)

```
keyframe image (user) + scene prompt (light sources worded dim/steady; motion_style.steady_light appends the rest)
   │
[fit]       ──► keyframe.png                only for a user image not already at the loop size: cover-crop to
   │                                         832x480 (an odd-height photo broke the depth-control encode).
[bloom]     ──► keyframe.png                only with --bloom mild|strong: highlight glow on the still's own pixels
   │                                         (brilliance lives in the still; research/furnace-scene.md). Off by default.
   ▼
[take]+[settle] ─► settled.png             a take from the image; its LAST frame can become the keyframe, so steam /
   │                                         mist start at the level the model builds them up to (neon drift 16-34 ->
   │                                         ~7 grey). v2 `auto` (default 2026-09-27): only when the prompt names an
   │                                         accumulating medium AND the take shows a start transient > 4 grey; else
   │                                         the image stays and take[0] is this same render (cache hit).
   │                                         `--always-settle` = the old rule; `--no-settle` = never.
   ▼
[take]      ──► take.mp4, lat_stage1/2.pt   LTX-2.5 distilled 8 steps, depth IC-LoRA fed the still keyframe (camera
   │            settings.json                lock), ≤ 481 f (WanGP window max 501), own latents saved. Output is
   │                                         832x448 (LTX rounds 480 down to a multiple of 32), so the 4K stage's 16:9
   │                                         cover-crop loses ~4.3 % of the width (1280x704: 2.2 %; the audition draws it).
   │                                         Meta: runtime (WanGP rev, LoRA sizes, generation clock vs playback) and
   │                                         timing (wall s per WanGP phase, CUDA peak, OOM retries).
[take_qc]   ──► accept                      CPU: camera, global luma drift, per-region (3x4) end−start boundary ≤ 4 grey
   │                                         (v3, research/gate-replay.md; trend and a global-vs-regional split in the
   │                                         meta as diagnostics), pulse ≤ 12;
   │                                         a drifting take → next seed (≤ 3); none → best effort: the steadiest
   │                                         take ≤ 7.5 grey with a "very slight seam" warning (user decision).
[audition]  ──► audition.{md,mp4}, crops.jpg only with --audition (ADR 0013): content packet, then the take gate pauses
   │                                         until `looper accept RUN take` (decision bound to fingerprint + output
   │                                         hash + contract; rejection stops the run). Without it: compatibility mode.
   ▼
[extend]    ──► window.mp4, lat_stage1/2.pt only if the loop must outlast one take: ONE continuation from the take's
   │                                         last 49 frames, context = 0.5 × own latents + 0.5 × re-encoded.
[join]      ──► long.mp4 (lossless)         CPU: take + new frames, tone + sharpness matched, 8-frame ramp; same
   │                                         stationarity gates → next extension seed on drift; none → best effort
   │                                         ≤ 7.5 grey, else a shorter loop:
[endpoint]  ──► candidates.json             CPU (ADR 0010): the easiest legal (end, start) cut of every long that
   │                                         exists (the take, each rejected extension's long), ≥ min_seconds (17),
   │                                         ranked by take_qc's boundary; used when it beats the take-only cut
   │                                         (s = 89, e = 481), which stays the fallback. close/splice take end_frame.
   ▼
   Route (ADR 0012, accepted): long return by default whenever one return window fits (~30 s; --no-long-return\n   forces the extension + 32 f closure route, which 60 s loops still use): no extension; keep the take's calmest stretch
   (loopkit.calmest_segment, >= 352 f) and close with ONE return of up to 368 f that fills the loop to length.
   --motion-speed S: every LTX stage runs the Slow-Motion-Control LoRA with its motion clock scaled by S
   (generation-side; there is no playback retime anywhere in the loop path, output is always 24 fps).
   --guide-strength G: depth-guide control strength (WanGP denoising_strength for "DVG"; union IC-LoRA stays 1.0).
   --resolution WxH (default 832x480). Values at their default stay out of the fingerprints.
   --motion-donor [--donor-speed S] (ADR 0016, proposed): [donor[take]] Hunyuan 1.5 480p renders the still (or
   --take-guide VIDEO is the donor) -> [fit_guide] retimed to S (motion-interpolated) and framed exactly like the
   keyframe -> the take's moving depth guide instead of the held still (single stage implied, no settle). After the
   cut: [donor_start] the donor frame at the loop's last body frame -> [donor[return]] Hunyuan continuation ->
   [fit_guide[return]] -> [return_guide] take guide [e-E:e] + continuation [1:G+1] + take guide [s:s+64], G = the
   target gap or up to 64 f less, chosen by a whole-frame structural wrap match; every close seed uses it (close
   inputs.guide via ltx.control); no grow. Only shape motion transfers (depth): cloth, hair, flags; never light.
[close] × seeds ─► window.mp4               145 f LTX window [end ctx 49 | gap 32 | start ctx 64]; both contexts as
   │                                         clean timestep-0 latents from the runs' OWN saved latents; start context
   │                                         from take frame ≥ 89 (past the I2V settling).
   ▼
[splice] × seeds ─► loop.mp4 (4:4:4)        long[start:] + tone/sharpness-matched gap, 3-frame in-overlap ramps.
   ▼
[loop_qc] × seeds ─► qc.json, qc.png        regional QC vs the take (`looper/regional_qc.py`, auto regions unless a
   │                                         scene JSON is given) + closing step score; accept rule calibrated on 10
   │                                         human-judged loops. A spike rejects only inside the modified frames
   │                                         (gap, ramps, wrap, extension join ± 0.5 s); elsewhere it is recorded as
   │                                         `natural_spikes`. Best accepted seed wins. None accepted → a review packet
   │                                         of the least-bad closure marked FAILED (`review[failed]`), then the run fails.
   │                                         v4: closure texture churn vs the window's own contexts (review DOUBT: mean
   │                                         > 1.4, worst region > 1.5). v5: whole-loop slow drift (DOUBT > 8 grey).
   │                                         The take's QC reference is built once per process (cached by path+mtime).
   │                                         Early accept (default on): the first seed that is accepted, closing <= 1.2,
   │                                         no flags, worst-region churn <= 1.4 ends the seed loop.
   ▼
[grow]      ──► rotated.mp4 (lossless)      ADR 0011, only when the chosen loop is > 1 s short: pick an interior cut
   │                                         (e, e + 32) near the segment's middle, contexts inside one source; render a
   │                                         G-frame two-sided bridge with close[grow] (G = missing + 32, ≤ 368: one 481 f window), rotate
   │                                         the accepted loop so the cut sits at the wrap, splice[grow], loop_qc[grow].
   │                                         Fails loop_qc → rollback: the accepted short loop is delivered (warning).
   ▼
[deliver]   ──► loop_420.mp4, final.mp4     4:2:0 crf 17 mbtree=0 keyint=infinite, a 4-period block + N × stream copy.
   ▼
[review]    ──► review.md, review.mp4,      CPU: the packet a human judges on a small screen — loop ×2 (crf 20), frames
                joins.jpg                   around every join, metrics table, join timestamps, PASS / DOUBT line
                                             (`review.ready` event). Nothing is built by hand for a normal run.
                                             v3: the contract checklist (content judged apart from joins); loop-vs-take
                                             content diagnostics (moving-region motion, brightest light; DOUBT below
                                             0.5 / 0.7 -- hypotheses, never fired on a passed loop); for a rotating beam,
                                             its phase track through every join (looper/periodic.py). Outcome of the
                                             run: needs_review until `looper accept`; best_effort if the contract
                                             still misses an element.
   ▼  --4k (T3a local, stages/upscale.py): pauses first until `looper accept RUN loop` (ADR 0013)
[upscale] × chunks ─► chunk.mp4             FlashVSR ×4 (832x480 -> 3328x1920) of 144-frame CIRCULAR chunks with 8
   │                                         real neighbour frames each side (the first chunk gets the loop's last
   │                                         frames), trimmed, cover-scaled + centre-cropped to 3840x2160. The loop
   │                                         point gets the same temporal context as any chunk boundary. ~13 s/frame.
[upscale_join] ──► period_4k.mp4            8-frame ramp from run i-1 to run i at every join, circular at the loop
   │                                         point (same-instant renders, ADR 0009); streamed, frame count checked.
[deliver4k] ──► loop_4k, block_4k, final_4k  HEVC NVENC cq 19 + -maxrate 120M (without it NVENC caps at 20 Mbps),
                                             4-period continuous block, final = N × stream copy for --final-minutes
                                             (default 60); join + wrap steps gated on a small proxy (`accept`).
```

Vendor specifics (patching WanGP's LTX conditioning and latent hand-off) live only in `looper/adapters/ltx.py`
(invariant 9). Shared frame maths (tone/sharpness match, layout, step profile) in `looper/loopkit.py`.

**Why these boundaries:** take (≈ 13 min) and extend (≈ 8 min) are the expensive GPU artifacts and are reused by
every closure attempt; close (≈ 5 min) fans out per seed; splice/qc are CPU and cheap, split from close so assembly
or gate changes never regenerate. Closure selection is pipeline logic over recorded qc metadata (no stage state).

**Architecture checklist for this layout:** quality — the only recipe that passed the user on particle
content; iteration — take cached, closures re-seeded independently; rerunnable + persisted — every stage
fingerprinted, latents are artifacts; replaceable — LTX hooks isolated in one adapter; observable — existing
events/dashboard, qc.png per candidate; diagnosable — qc.json with per-region gates and the step profile; laptop —
all steps measured on the 6 GB RTX 3060 (take 3.8 GB VRAM / 56 GB RAM); scales — frames/resolution are config;
demonstrated problem — yes (Review E, research/particle-loop-closure.md).

## Stage contract

Every stage defines **Inputs → Processing → Outputs → Validation → Metadata**:

- A stage is a pure-ish function of `(input artifacts, its config slice, seed, stage version)`.
- It reads only declared inputs and writes only inside its own output directory.
- It writes `stage.json`: inputs (with hashes), config slice, seed, stage version, pipeline version, model calls, timings, validation result, status, error info on failure.
- Persisted artifacts are immutable. A rerun produces a new directory, never an overwrite.

## Persistence & run layout

```
runs/<run_id>/
  manifest.json          run-level: original prompt, config, pipeline version, stage → fingerprint → status
  events.jsonl           append-only structured event log (see Observability)
  stages/<stage>/<fingerprint>/
      stage.json         metadata described above
      ...artifacts...
      logs/              stdout/stderr of subprocesses
```

The manifest answers: which run/stage produced a file, from which inputs/config/model/seed/version, did validation pass, what must rerun.

## Resumability & invalidation

`fingerprint = hash(stage name, stage version, config slice for this stage, seed, hashes of input artifacts)`

- Before running a stage, compute its fingerprint. If `stages/<stage>/<fingerprint>/` exists with status `ok` → **cache hit**, hydrate from disk, emit `stage.restored`.
- Invalidation needs no special logic: a change propagates only if it changes a downstream fingerprint. Change a closure seed → that `close` and its splice/loop_qc rerun; take/extend and the other closures are hits. Change the delivery repeats → only `deliver` reruns. If a rerun stage produces byte-identical output, downstream stays cached (early cutoff).
- Failed stage → status `failed` + diagnostics kept; `resume` = run the pipeline again; everything before the failure is a cache hit.
- Config slices must be explicit per stage, otherwise everything invalidates everything. This is the main design discipline.
- Non-deterministic stages (LLM, GPU generative): the *persisted output* is the source of truth, so resume is still exact; regeneration is not bit-reproducible — record that in `stage.json`.
- Superseded fingerprints stay on disk until `python -m looper prune` (dry run; `--yes` deletes; `--older-than DAYS` removes whole runs). "Superseded" = not the manifest's latest fingerprint for any key, so pruning means an older config regenerates instead of restoring. Runs with an event in the last hour are skipped.
- ponytail ceiling: cache is per-run-directory plus explicit "fork run from" support; a global cross-run content store only if reuse across runs proves valuable.

See `DECISIONS/0001-fingerprinted-stage-artifacts.md`.

## Scene representation (implemented: `looper/stages/direct.py`)

`direction.json` keeps `original_prompt` verbatim next to the model's facts (`scene`, `style`, `keyframe_details`,
`moving[]`, `fixed[]`, `negatives[]`, `adaptations[]`), the composed prompts, clauses the checker dropped, warnings and
the model-call metadata — so every inferred word is traceable (invariant 11). The model supplies facts only; wording is
code (`motion_style.py`). Lesson kept from the retired `plan` stage: never let one loud element set a whole scene's
motion level (`max()` let one misclassified "windy" override 3 "gentle" elements on B1).

## Scene realization — historical (pre-ADR 0007 Wan chain + flf2v bridge; superseded by the loop pipeline above)

Keyframe still (T2I, Z-Image Turbo) → **one forward sliding-window chain** from that keyframe (Wan 2.2 14B Lightning + NAG, calm recipe in `research/local-video-baseline.md`) → **one generated bridge** from the chain's end back to its first frame (flf2v_720p) → validate → enhance (RIFE, retime) → N× stream copy. Playback is plain looping of one 30–60 s file. No pools, no reversal, no dissolves.

Measured facts that shaped this (`research/local-video-baseline.md`): sliding-window seams are invisible (≤ 1.6× median adjacent change, camera locked 0.21 px / 10 s) but the chain drifts after 10–15 s; ping-pong reversal is visible at any directional motion; dissolves morph; first=last, SVI end-anchor and VACE bridges all failed closure by 5–40×; flf2v at native res is artifact-free but eases into its target (flow 0.40 → 0.13 px/frame vs chain 0.35) — the freeze a human rejected.

The model host (WanGP) is driven in-process via its Python API, one warm session per run (`looper/adapters/wangp.py`) — isolated so it can move behind a real executor once a second target exists. **Policy: local GPU proves the recipe (T1/T2); the final render is T3a locally (FlashVSR of the approved loop) or T3b on a rented GPU (regenerate at 720p).** Masked/procedural animation of stills is not pursued.

## Looping model — historical notes (ADR 0005 era; current recipe: ADR 0007)

**Closure.** Generated, not blended: the bridge is conditioned on the chain's end and start frames. Every candidate is judged first by a **motion-level gate** (median flow per 8-frame block through chain+bridge stays within 0.8–1.25× the chain's median; direction consistent with the chain), because seam-frame metrics passed a bridge that visibly froze. Candidates in cost order: flow-constant retiming of the bridge (a resample, counted as generated closure by user decision), best-cut-point selection, anti-stillness CFG prompt, longer bridge, and — only if those fail — looped context windows (closure by construction; hypothesis, needs ComfyUI + wrapper install).

**Drift.** Colour drift (luma +23 %/30 s) and texture drift (sky → painterly → blotches) are separate metrics and separate fixes; only generation-time levers fix texture. Levers in cost order: WanGP colour correction (window-to-previous-window only — `any2video.py:690–694`), native 720p chain, longer windows (fewer conditioning hops), non-distilled CFG, post colour match to the keyframe. **Fallback:** re-anchored segments — N × (10–15 s chain + bridge back to the keyframe), different seeds, inside one 30–60 s loop; the keyframe state recurs every 12–17 s, which the user has agreed to test by eye.

**Three problems, kept separate** (invariant 10): mathematically seamless (frame diff at the join), visually seamless (motion level/direction across the bridge, sharpness continuity), perceptually non-repetitive (loop period 30–60 s accepted as not repeating too quickly; K-recurrence in the fallback is an open perceptual question).

### Rejected designs, for the record
- **ADR 0004 clip pool + ping-pong legs**: reversal jolt 3.9–6.9× at gentle motion; in review the clouds' back-and-forth slide looked unnatural. Cross-dissolve joins: visible morph. Both rejected by the user on real output.
- **Camera-lock gate** (phase-correlation shift ≤ 1.5 px) and the calm/still flow-speed band carry over unchanged from that design — they are per-chain checks now.

## Quality tiers

| Tier | Purpose | Where / cost target |
|---|---|---|
| T0 diagnostic | scene spec, keyframe still(s), motion prompts; VLM + human check of the still | local, seconds–minutes |
| T1 screening | short chain at 448×256 (≈ 2.2 min/window): identity, camera lock, gross motion character, drift-lever screening. Cannot approve a specific clip, cannot calibrate gates | local, minutes |
| T2 validation | full 30–60 s chain at 848×480 (≈ 7 min/window) + bridge at native 720p (~1 h) + all gates + the assembled loop for human review (R-C) | local, unattended (hours), resumable per stage |
| T3a final, local | FlashVSR ×4 the *approved* T2 loop (≈ 20 min / 81 f); delivers exactly what was approved, bounded by 480p generation | local, hours; free |
| T3b final, rented | regenerate at native 720p with the proven recipe, bridge, FlashVSR ×4 → 5120×2880 → 3840×2160 | rented GPU; only after T2 gates + R-C; cost measured before spending |

Tiers are config of the generation stages only, so tier changes never redo interpretation or the keyframe. Resolution is part of the chain fingerprint, so T3b is a new chain artifact in the same run dir, gated again. No CLI flag selects a tier yet.

## Model abstraction (implemented for Ollama: `looper/models.py`)

`complete(task, prompt, *, model, json_mode) → (text, metadata)`, stdlib `urllib` only (no SDK dependency). Metadata per call: provider, model, tokens in/out, latency, tok/s, retries, cost (`None`, always free/local today), request id, task, timestamp — written into `direct`'s `direction.json` / `keyframe_qc`'s `qc.json` and folded into `stage.json`/events via `engine.py`'s redaction hook. Providers: Ollama (default, `format: "json"` — a schema object hung gemma4 > 300 s; `think: false` — thinking models stalled in a field we don't read) and the Claude Code CLI (opt-in per run, ADR 0008; `claude -p --output-format json --json-schema`, temp-dir cwd, Read tool only; cost = the CLI's `total_cost_usd`). A future Codex/Gemini CLI is another branch in `complete()`. `images=[...]` for vision; `unload=True` frees Ollama VRAM before GPU stages. Image/video generation has its own adapter (`looper/adapters/wangp.py`), separate from the text-completion one, per the original design note here ("get their own adapter when first needed").

## Execution model

A stage run = `(input dirs, config) → output dir`. **No `Executor` interface exists** — `adapters/wangp.py` calls WanGP in-process directly. This is deliberate: one implementation would be an unrequested abstraction (the project's own rule against interfaces with a single implementation). The adapter is isolated specifically so it *can* be relocated behind a real executor once a second execution target (rented GPU) actually exists — see Phase 6. Hardware sampling (`looper/hw.py`) records VRAM/RAM/temp/power peaks per GPU-heavy stage today; it does not yet gate or degrade behavior based on them.

Job contract (2026-09-27, ADR 0014 proposed): `python -m looper job RUN KEY` exports one finished stage as a
reproducible job description (stage version, config, seed, input hashes, contract fingerprint, recipe, runtime, caps)
with `enabled: false`. No executor, provider or submission exists; a remote result whose fingerprint differs is a new
candidate needing review.

## Observability

```
engine / stages / hardware sampler ──emit──► events.jsonl (+ human-readable log)
                                                   ▲
                               dashboard (TUI), tests, other UIs only read
```

- Event: `{ts, run_id, stage, type, payload}` (`stage` may be null). **Writer: `looper/events.py` only** (`emit`, never raises; `set_current`/`emit_current` give producers the active run context, with env var `LOOPER_EVENTS=<path>|<run_id>|<stage>` for subprocesses). **Reader: `looper/observe.py`** folds the files into a JSON-serialisable `Snapshot` (a future web page serves `Snapshot.to_dict()`); the Textual dashboard (`python -m looper dash`) renders snapshots only.
- Types in use: `run.started|resumed|queued|finished`, `run.plan {stages: [keys in order], keyframe}` (loop pipeline: lets the reader compute a stage-level ETA from the median duration of each stage name across all runs, and show the `--image` keyframe), `stage.started|restored|ok|failed`, `stage.progress {step, total_steps, window, total_windows, sec_per_step, phase}` (WanGP adapter), `render.preview {path, frame_index, width, height}` (WanGP adapter), `model.request {model, task, prompt}` (`models.py` for LLM calls, `adapters/wangp.py` for every generation), `model.stream` (~2 Hz, carries the new `text` since the previous event) / `model.response {input_tokens, output_tokens, tokens_per_s, latency_s}` (`models.py`), `model.tokens {video_tokens, generated_tokens, context_tokens, control_tokens, latent_frames, latent_hw}` (`adapters/ltx.py`, once per LTX stage; the reader turns it + `sec_per_step` into video tok/s for the dashboard TOKENS panel, `t` = full view), `hw.sample {vram_mib, gpu_util, temp_c, power_w, ram_gib, cpu_util, …}` (`python -m looper hw`). `run.awaiting_approval {review, chosen, keyframes, scores, warnings, resume}` / `run.approved {keyframe, auto}` (front end; the reader shows a paused run as "awaiting approval", not idle), `verdict {text}` (a human review, written by `python -m looper verdict RUN_ID "text"`; the reader shows the latest one per run and does not count it as run activity).
- Files: `runs/<id>/events.jsonl`; `runs/<id>/previews/NNNN.jpg` (≤ 480 px, last 20); `telemetry/hw-YYYYMMDD.jsonl` (2 s samples, 7 days); `telemetry/jobs.jsonl` (batch queue/lifecycle); scratch experiment jobs write `<job_dir>/events.jsonl`, which the reader also discovers.
- Reader rules: a stage silent > 5 min shows "stalled?"; silent > 1 h it moves to history as "abandoned" (revived by any new event); hardware sampler "down" when the last sample is > 10 s old.
- A file is the bus: works across subprocesses and machines, survives crashes, and logs exist without the dashboard. ponytail ceiling: polling a JSONL file; swap for a socket only if latency matters.
- The dashboard holds no business logic and the engine never imports it.

## Failure handling

On failure a stage records: what/where, inputs, config slice, stdout/stderr paths, model response if any, hardware snapshot, retries attempted, last good artifact, recommended resume point. Partial outputs are kept. A failed run is never deleted automatically.
