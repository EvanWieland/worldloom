# Best video model this machine can hold (desk research, 2026-09-27)

**Trigger:** lighthouse verdict — joins invisible, but the waves very poor and the overall quality very low. Requested: find the
best models the machine will hold; speed may be sacrificed, CPU/RAM may be used.
**Evidence level:** web sources + WanGP code on this machine. No new renders. Supersedes the candidate table in
`model-options.md` (2026-09-24), which predates MiniMax H3, Cosmos 3 and MAGI-2.

## Conclusions

1. **The quality gap is real and large.** Artificial Analysis I2V arena (no audio): Gemini Omni Flash 1369, Wan 3.0
   1362 (closed), **MiniMax H3 1358 (open)**, Cosmos 3 Super 4-step 1273 / base 1253 (open). With audio: H3 1181,
   MAGI-2 Preview 1094, **LTX-2.5 Fast 1036 (what we run)**. H3 is ~150-300 Elo above LTX-2.5.
2. **MiniMax H3 is already in our WanGP** (`minimax_h3_fl2va`, `_pruned` 20B, `_vdn` 8-step, int8 ConvRot) and a
   documented run did it on 8 GB VRAM: pruned 20B int8, WanGP, ~48 GB resident RAM, 480p, 8-15 min per clip
   ([source](https://mountainmeadowsystems.com/writing/minimax-h3-local-8gb-vram)). Our 6 GB / 64 GB is plausible at
   480p (hypothesis until run). FL2VA = first AND last frame conditioning, so it could also generate closures.
   **BLOCKER — licence:** the H3 Community License forbids local use in the US, EU, UK and Korea
   ([LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/LICENSE)); MiniMax grants licences on request.
   Usable only outside those territories or with a licence granted by MiniMax; **not pursued here** (form https://platform.minimax.io/h3-license, or api@minimax.io; no
   public reports of approvals yet).
3. **Cosmos 3 Super (64B, OpenMDW = permissive, global)** is the best permissively licensed open model, but bf16-only
   (NVIDIA supports nothing else), 128 GB of weights; NF4 community wrappers need ~40 GB VRAM, Linux
   ([HF](https://huggingface.co/nvidia/Cosmos3-Super-Image2Video), [wrapper](https://github.com/zbrad/scg-Cosmos3)).
   Does not fit 64 GB RAM even at int8. **Rented GPU only** (invariant 13 allows it for the final render). Nano (16B)
   is ~32 GB bf16, no quantisation, unranked — not worth it.
4. **MAGI-2 Preview** (114B MoE, 6B active, Apache 2.0): 307 GB repo, reference inference on 8× Hopper, no WanGP /
   ComfyUI support. Not local.
5. **Wan 2.5/2.6/2.7/3.0 are closed** (API only). Wan-AI's HF org tops out at 2.2
   ([HF org](https://huggingface.co/Wan-AI), [receipts](https://www.atlascloud.ai/blog/tips/is-wan-3.0-open-source));
   "open Wan 2.7/3.0" pages are fan sites. SkyReels V4: no public weights (GitHub 404).
6. **Unused levers inside the model we already run (LTX-2.5):**
   - **NAD Diffusion Decoder** — LTX-2.5's new decoder, WanGP label "slower, higher VRAM, better motion"; Lightricks:
     keeps "fast motion sharp". It is an opt-in `system_configs` choice (`models/ltx2/ltx2_handler.py:555`); we use the
     default VAE. Weights already downloaded (`ltx-2.5-22b_diffusion_video_vae_bf16.safetensors`).
   - **Dev checkpoint + two-stage pipeline** (half-res generation, x2 spatial upscaler refine, real CFG) — downloaded,
     unused; we run distilled, 8 steps, single stage at 832x448. Waves in a wide shot are a few pixels tall at 448p.
   - Lightricks claims the 2.5 distilled is near Dev quality (RL-trained), so Dev is a probe, not a sure win.
7. **Other local candidates in WanGP:** Kandinsky 5 Pro I2V 19B (paper claims better visual quality and motion than
   Wan 2.2 A14B; unranked on AA), HunyuanVideo 1.5 720p I2V 8B (480p step-distilled rendered on the lighthouse,
   `runs/ocean/hy15/sbs.mp4`, not judged), LongCat-Video 13.6B (native continuation, no drift claims).
8. **"Run on CPU" is not a lever.** Pure-CPU diffusion is ~50-100x slower than the 3060; the useful form — weights in
   RAM streamed to the GPU per block — is what WanGP already does. **64 GB RAM is the ceiling**: a model fits if its
   quantised weights + text encoder + activations stay under ~55 GB (LTX take already peaks 56-59 GB). That admits
   H3 pruned int8 (~21 GB), H3 full int8 (~33 GB, tight), Kandinsky 19B, LTX Dev; it excludes Cosmos Super and MAGI-2.

**What remains unproven:** every quality claim above is from leaderboards/secondary sources (general I2V, not water).
No source compares models on ocean waves specifically; open models reportedly move water as one viscous mass. Only
our own renders on the lighthouse still decide.

## Proposed bake-off (T0, one GPU job at a time, lighthouse still, same prompt, seeds 306/307, ~5 s)

| # | candidate | cost guess | note |
|---|---|---|---|
| 0 | current: LTX-2.5 distilled, 832x448, default VAE | have | baseline |
| 1 | same + NAD Diffusion Decoder | ~+2 min | one-setting change |
| 2 | LTX-2.5 Dev two-stage, 1280x704 | 20-40 min | resolution + CFG |
| 3 | Kandinsky 5 Pro I2V 19B int8 | 30-60 min | first download ~20 GB |
| 4 | HunyuanVideo 1.5 480p (rendered) / 720p I2V | have / ~40 min | judge existing sbs first |
| 5 | MiniMax H3 pruned 20B int8 (+VDN 8-step) | 15-40 min | **only where the licence allows** |

Judge by eye (waves: breaking crests, foam, independent swells, correct speed) on one side-by-side; winner goes to a
full loop. Camera lock and loop-closure recipes are LTX-specific (depth IC-LoRA, true-latent closure) — a non-LTX
winner means re-proving closure, so the bar is "visibly better water", not "slightly better".

### Results so far (stopped by the user mid hy15_720; `runs/models/bakeoff/measures.json`)

| arm | time | worst region drift (grey) | eye check (frame 90, sea crop) |
|---|---|---|---|
| ltx_base 832x448 | - | 5.33 | reference |
| ltx_nad | 5.7 min | 4.81 | darker, Laplacian ~half and falling (46-66 vs 102-110): reject |
| ltx_720 1280x704 | 5.7 min | 1.02 | sharper rocks and water, spray visible |
| ltx_dev_720 | 14.5 min | 0.69 | nearly identical to ltx_720 |

Camera held on all (0.05-0.07 px). Motion not yet judged by eye. Observation: the lighthouse still's sea is ~10 % of
the frame, which limits what any model can show; a water-dominant still is the fairer ocean test.

Rented option for the final render: Cosmos 3 Super 4-step I2V on an H100/H200 (permissive licence).
