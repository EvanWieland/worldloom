# Generative-video route: how to make it loop, last, and fit 6 GB — 2026-09-21

**Evidence level: desk research only. No video model has been run on this machine yet.** Follows the user's decision to use generative video as the backbone (ADR 0003). Background survey: `solution-space.md`.

## Building blocks

| Need | Candidates | Notes |
|---|---|---|
| Local dev model (6 GB) | **Wan 2.2 TI2V-5B** (FP8 / GGUF + offload); Wan 2.2 I2V-A14B GGUF Q4 @480p + LightX2V 4-step distill LoRAs; LTX-2.x GGUF | Reported: 5B ≈ 5 s 720p in <9 min on a "consumer GPU" (likely a 4090 — expect much slower here); 14B-GGUF on 6–8 GB ≈ 20–30 min per 5 s clip without distillation. Advice found: 5B at higher precision beats 14B at Q3. LTX-2.x GGUF realistically wants 8–16 GB. **All to be measured.** |
| Host | ComfyUI (headless `/prompt` API, Dynamic VRAM) or WanGP (CLI/API, tuned for low VRAM) | Pick by trial. Either way the pipeline talks to it over HTTP → same code drives a rented GPU later. |
| Start frame | T2I still (Z-Image Turbo / FLUX.2 klein locally) → I2V | Separating *look* (still) from *motion* (video) makes the look cheap to iterate and keeps identity anchored. |
| Loop closure | (a) FLF2V / first=last frame — static-collapse risk; (b) **VACE bridge**: last N + gap + first N frames → generated transition; (c) **Loopy** circular RoPE (Wan 2.2 T2V-A14B, 53 f @ 480p, 8-GPU reference → rented only, T2V only) | (b) is the most general: closes *any* clip, including a long chained one. |
| Long duration without drift | **Stable Video Infinity (SVI)** — ICLR 2026 oral, open LoRAs for Wan, error-recycling fine-tune, "infinite-length without drift", per-clip prompts; plain last-frame chaining (drifts/degrades) | SVI + VACE bridge back to frame 0 ⇒ a **multi-minute loop** — the video route's answer to perceptual repetition. |
| Static-region stability | prompt for locked tripod / fixed lighting; less fine background detail; **deflicker before upscale**; temporal-aware SR | Known weak spot of this route: shimmer/"boiling" in areas that should be still. Must be a measured QA metric (flicker in low-motion regions). |
| Upscale / fps | SeedVR2 (3B/7B, GGUF, block-swap), FlashVSR (one-step, streaming), RIFE | SR is video-to-video: it preserves the validated motion. |

## WanGP as host — findings from its source/docs (2026-09-21, commit 59e5560; **read, not yet run**)

- **Interfaces usable without the web UI:** in-process Python API (`shared.api.init(root, cli_args)` → `session.submit_task(settings)` → `job.events` with `progress` (phase, step, %), `preview`, `stream` (stdout lines), `status`; `job.result()` → `generated_files`, `errors`; `job.cancel()`), plus `python wgp.py --process queue.zip|settings.json --output-dir X` and an MCP server. Settings JSON is the export of the UI's "Export Settings". Maps directly onto our event architecture. Running it as a subprocess per stage (CLI `--process`) matches our "stage = command with inputs → output dir" contract and also works on a rented GPU.
- **Terms:** WanGP asks that products integrating its API disclose that WanGP is used (docs/API.md). Fine for a non-commercial project; note it in the README when one exists.
- **Models present in `defaults/` that map to our plan:** `ti2v_2_2` and `ti2v_2_2_fastwan` (Wan 2.2 5B, FastWan 3-step LoRA); `i2v_2_2` (14B, high+low noise experts); **`i2v_2_2_svi2pro`** (Stable Video Infinity 2 Pro LoRAs: continue videos indefinitely, reuses the start frame or an **anchor image across all windows** as reference — the drift control we wanted); `i2v_2_2_Enhanced_Lightning_v2(_svi2pro)` (FP8, Lightning-accelerated finetune); `vace_14B_2_2` (VACE for loop closure; docs say support is only partial); `flf2v_720p`; `ltx2_22B_distilled_gguf_q4_k_m` / `ltx2_25_22B_distilled*`; `qwen_image_2512_20B`, Z-Image, Flux for keyframe stills. Upscalers/interpolators built in: FlashVSR, SeedVR2, RIFE (`edit_postprocessing` mode operates on an existing video — usable for the enhance stage).
- **Flags for 6 GB:** `--profile 4` (default; loads model parts as needed) or 5 (minimum RAM), `--attention sage2` (RTX 30xx+, needs triton-windows) else `sdpa`, `--compile` optional, `--perc-reserved-mem-max`. Weights download on first use from `DeepBeepMeep/*` HF repos into the WanGP tree (disk!).
- Unknown until run: real VRAM/time on this GPU, whether FP8 14B files are used as-is or quantized on the fly, whether the 6 GB card can run VACE.

## Proposed structure (hypotheses) — SUPERSEDED by measurement

> **2026-09-21:** steps 2–3 below (chained segments + generated closure) were tested and failed locally (first=last, SVI chain + end anchor). Working design is now ADR 0004 (keyframe-anchored clip pool + dissolves); see local-video-baseline.md. Steps 1, 4–6 remain valid.


1. **Keyframe still** from the scene spec (cheap to iterate; T0).
2. **Segments**: I2V clips of ~5 s chained from the still (SVI or last-frame conditioning). Each segment is its own artifact → a bad segment is regenerated alone.
3. **Closure segment**: VACE-style bridge from the end of the last segment to the start of the first.
4. **Validate** the low-res loop: seam (tile-based), flicker in low-motion regions, luminance drift across segments, identity drift vs keyframe, frozen motion.
5. **Final = enhance the validated loop** (deflicker → SR → interpolation) on a rented GPU, rather than regenerate at high res. Regeneration at another resolution/precision yields a *different* video, which would invalidate everything the cheap tiers proved. Alternative to test: regenerate with a bigger model anchored by the same keyframes and compare.
6. **Assemble** by stream copy (verified, `long-form-assembly.md`). A 3–5 min loop repeated for hours; optional loop family (several closures/variants sharing frame 0) scheduled via concat.

## Tier mapping for the video route

| Tier | What | Where |
|---|---|---|
| T0 | scene spec, keyframe still(s), motion prompt; VLM/human check of the still | local, seconds–minutes |
| T1 | one short low-res segment (few steps, distilled) to check motion character | local, target < 10 min |
| T2 | full chained loop at dev resolution + closure + objective validation | local, hours, unattended, resumable per segment |
| T3 | deflicker + SR to 4K + interpolation (and/or big-model regeneration) | rented GPU |

## Biggest unknowns → experiments

1. **What actually runs on this GPU, how fast, how good?** Wan 2.2 5B vs 14B-Q4+distill at 480p, one 5 s I2V clip each, on B1 castle. Gate for everything else.
2. Does SVI run within 6 GB (it is a LoRA on Wan I2V 14B → probably needs the GGUF path), and does a 60–120 s chain stay consistent with a locked camera?
3. VACE bridge quality on ambient content; does the seam pass the tile-based check?
4. Static-region shimmer: how bad, and how much do prompt discipline + deflicker remove?
5. 480p→4K SR: acceptable, or is 720p the minimum source? (SR trial can run on a short crop locally.)

## Sources

- Wan 2.2: https://github.com/Wan-Video/Wan2.2 · https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B · https://huggingface.co/bullerwins/Wan2.2-I2V-A14B-GGUF · https://willitrunai.com/blog/wan-2-2-vram-requirements · https://localaimaster.com/blog/local-text-to-video-low-vram · https://huggingface.co/lightx2v/Wan2.2-Distill-Loras
- SVI: https://github.com/vita-epfl/Stable-Video-Infinity · https://stable-video-infinity.github.io/homepage/
- Loop closure: https://openart.ai/workflows/nomadoor/loop-anything-with-wan21-vace/qz02Zb3yrF11GKYi6vdu · https://huggingface.co/htdong/Loopy
- LTX GGUF: https://dev.to/gary_yan_86eb77d35e0070f5/how-to-install-and-configure-ltx-2-gguf-models-in-comfyui-complete-2026-guide-1d3m · https://ltxworkflow.com/models
- Flicker: https://unifab.ai/resource/remove-ai-video-flicker · https://wavespeed.ai/blog/posts/blog-fix-flicker-jitter-seedance-2-0/
- Hosts: https://github.com/deepbeepmeep/Wan2GP · https://docs.comfy.org/development/comfyui-server/comms_overview
