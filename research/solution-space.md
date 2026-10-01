# Solution space survey (R1–R4) — 2026-09-21

**Evidence level: desk research only (web sources, Sept 2026). Nothing here has been run on this machine.** Claims from vendor blogs/listicles are marked (unverified) where they matter. Experiments that would confirm/refute are listed at the end.

## Key framing insight

Ambient "living photograph" video has a **locked camera** and mostly **static pixels**. That changes the ranking of approaches: whatever produces the static pixels must be flawless and rock-stable at 4K for hours; motion is needed only in masked regions, and must loop by construction. General video generation solves a harder problem than we have (camera + everything moving) and pays for it in resolution, stability, and clip length.

## Approach families

### A. Pure generative video (T2V / I2V), made to loop

State of the art (open weights): Wan 2.1/2.2 (14B MoE; 5B variant), LTX-2 / 2.3 / 2.5 (22B, native 4K claimed, ≥16 GB VRAM), HunyuanVideo 1.5, MiniMax H3 (unverified name/details, listed by WanGP). Hosted: Veo 3.1, Kling 3.0 (~$0.10/s), Wan 2.6/2.7 API (~$0.05/s, first/last-frame), Runway Gen-4.5 (~$0.15/s), Luma Ray (keyframes + loop flag). Prices are per *generated* second, so loops are cheap; hours of unique footage are not.

Looping methods:
- **Loopy** (Aug 2026, Apache-2.0, code+weights: `WeChatCV/Loopy`, `htdong/Loopy`): shifts RoPE per layer group so the DiT perceives time as a circle; LoRA fixes VAE linear bias. Works on Wan 2.1/2.2, HunyuanVideo 1.5, and **Wan-Alpha (RGBA)**. Released weights: Wan2.2-T2V-A14B, **53 frames @ 832×480**, reference inference uses 8 GPUs, T2V only. Avoids the "static collapse" of first=last-frame tricks.
- **Mobius** (2025): latent shift, training-free, older backbones. Outperformed by Loopy per Loopy's paper.
- **DreamLoop** (Jan 2026): cinemagraph from a single photo, first=last frame + motion tracks + static-region tracks, "general scenes". Code/weights availability **unconfirmed**.
- Community: Wan FLF2V with same first/last image (prone to static collapse); **VACE loop closure** (feed last 15 + blank 51 + first 15 frames, generate the bridge) — turns any clip into a loop.

Local feasibility: **WanGP** (`deepbeepmeep/Wan2GP`) runs Wan/LTX/Hunyuan etc. with ≥6 GB VRAM via offload/quantization, has headless/CLI + API mode, Windows installer, Python 3.11, built-in FlashVSR/SeedVR2/RIFE. 6 GB ⇒ roughly 5 s @ 480p, slow (no trustworthy timing found; measure). ComfyUI (headless `/prompt` API, Dynamic VRAM allocator since v0.18) is the alternative host.

Assessment vs requirements: quality of *motion* is the best available for hard content (rolling waves, animals, fabric). But: 3–5 s loops at 480–720p, texture shimmer in regions that should be static, weak controllability, not reproducible across hardware, short period ⇒ obviously repetitive. **Fails as the whole pipeline; valuable as a component** for masked regions and RGBA elements.

### B. Full 3D procedural (Blender)

- LLM-authored Blender: SceneCraft, LL3M (multi-agent, writes/debugs bpy), BlenderLLM, Scene Co-pilot (LLM + Infinigen assets). Research-grade; output looks like CG/stylized assets, not cinematic photoreal. **Infinigen** (BSD-3) gives photoreal *nature* procedurally, but Linux/macOS only (WSL2 possible), heavy, nature-only — no castles, boats, buffalo at hero quality.
- **HY-World 2.0** (Tencent, open, Apr 2026): text/image → 3D world as meshes/3DGS importable to Blender. VRAM need unknown (likely ≫6 GB → rented GPU). Static worlds; animation still ours to add.
- Looping in Blender is fully solvable by construction: ocean modifier time wrap, 4D-noise on a circle, baked sims with blended caches, particle pre-roll (well-documented community techniques).
- Tiering is natural: EEVEE for preview (one report: 24 s vs 5 min/frame for a volumetric scene vs Cycles), Cycles for final, trivially farmable headless.

Assessment: best controllability/loopability/reproducibility/cloud scaling; **worst at "arbitrary prompt → photoreal hero subject automatically"**, which is risk #1. Not the backbone; keep as an optional element source (volumetric clouds, water surfaces rendered as layers).

### C. 2.5D "plate + motion layers"

1. Generate a hero still with an image model — image models are far ahead of video models in fidelity/resolution. Local on 6 GB: Z-Image Turbo (6B), FLUX.2 klein 4B, FLUX.2 dev GGUF-Q4 (tight), Krea 2 (unverified); or any hosted image API. Upscale to 4K with tiled SR.
2. Decompose: **Qwen-Image-Layered** (Apache-2.0, RGBA layer decomposition with inpainted occlusions, Dec 2025), **SAM 3** (text-prompted masks; custom SAM License — check terms), **Depth Anything 3** (depth ordering).
3. Animate each layer procedurally in a shader/compositor: periodic flow-field warps (Eulerian cinemagraph idea — cf. Text2Cinemagraph, which predicts flow for water/clouds/smoke), sway for vegetation, emission flicker, fog/mist/particle overlays, slow light grading.

Assessment: static regions are *perfectly* stable; loops exact by construction; per-layer periods are free parameters (enables coprime-period non-repetition, see `looping.md`); preview is real-time ⇒ fastest possible iteration; trivial VRAM; deterministic. **Weakness: motion realism ceiling** — warps can't do rolling waves, sails, animal motion, fur; disocclusion artifacts on large motion.

### D. Hybrid: C as backbone + generative/3D *elements* only where procedural motion fails

- For a masked region that needs real dynamics (ocean surface, buffalo, sail): generate a **looping low-res video patch** conditioned on the plate crop (I2V + Loopy-style circular time or VACE loop closure; DreamLoop if released), upscale with **SeedVR2** (3B/7B, GGUF, block-swap for low VRAM) or **FlashVSR** (one-step streaming), composite back under the mask. Artifacts stay confined to the mask; everything else remains the pristine plate.
- Loopy on **Wan-Alpha** can produce *RGBA looping elements* (smoke, fog, spray, fire) to composite — a generative alternative to particle systems.
- Blender-rendered elements (volumetric clouds, ocean) are another element source; **3D-previz → video-to-video** (RealMaster; VACE depth control + Depth Anything 3, shown on 16 GB cards) is a later option.
- Expensive element generation runs locally at low quality (WanGP) or on rented GPUs: RTX 4090 ~$0.34–0.51/h, RTX 5090 from ~$0.25/h (Vast, unverified), H100 ~$2–3/h. RunPod has per-second billing + serverless.

## Comparison (desk judgment, 1–5, higher better)

| Criterion | A gen-video | B full 3D | C 2.5D | D hybrid |
|---|---|---|---|---|
| Static-region quality / stability at 4K | 2 | 4 | 5 | 5 |
| Motion realism on hard content | 5 | 3 | 2 | 4 |
| Loop by construction | 2–3 | 5 | 5 | 4 |
| Long-period non-repetition | 1 | 4 | 5 | 4 |
| Arbitrary prompts, automated | 4 | 1–2 | 3–4 | 4 |
| Fits 6 GB / iteration speed | 1–2 | 3 | 5 | 4 |
| Reproducibility | 2 | 5 | 4 | 3 |
| Cloud scalability | 5 | 5 | n/a (cheap) | 5 |

## Provisional recommendation — SUPERSEDED

> **Superseded 2026-09-21 by ADR 0003:** the user has tried mask-and-animate before with poor results and chose the generative-video route (family A). See `video-route.md`. The survey above remains valid as background; the recommendation and experiments below are obsolete.

### (obsolete) original recommendation

**D, built C-first.** The first vertical slice is pure C (plate + procedural motion layers) on benchmark B1 castle, because it needs no heavy model beyond one image generation and exercises the entire engine. Generative video patches are the second motion-system type, added when B2/B4 demonstrate the realism ceiling.

Consequence for architecture: the plan stage assigns each animated element a **motion system** (`flow_warp`, `sway`, `flicker`, `particles`, `fog`, later `gen_video_patch`, `blender_element`). Each motion system must declare its period and guarantee closure. This is a substitution point demanded by the scene variety itself, not speculative.

## Tool shortlist (to validate, not yet adopted)

| Role | Candidates |
|---|---|
| LLM (interpret/plan) | local Ollama models already installed (qwen3, gemma, gpt-oss:20b); hosted frontier model via adapter for quality comparison |
| Vision QA | qwen3-vl:4b local; hosted VLM |
| Plate image | Z-Image Turbo / FLUX.2 klein / FLUX.2 dev GGUF locally; hosted image API |
| Layers / masks / depth | Qwen-Image-Layered, SAM 3, Depth Anything 3 |
| Model host | ComfyUI headless API **or** WanGP API — pick one by experiment; both hide VRAM juggling |
| Motion/compositing renderer | undecided: GPU shader renderer (moderngl/wgpu from Python) vs Blender compositor/EEVEE planes. Shader = real-time preview + same code for final; Blender = free volumetrics/3D elements. Needs experiment. |
| Gen-video patches | Wan 2.2 (+Loopy, VACE), LTX-2.x on rented GPU |
| Upscale / interpolate | SeedVR2, FlashVSR, RIFE |
| Encode / assemble | ffmpeg (see `long-form-assembly.md`) |
| TUI | Textual/Rich (low risk, decide at Phase 5) |

## Experiments that would change this conclusion

1. **C ceiling test:** one generated castle still, hand-made masks, flow-warp clouds + fog overlay + window flicker. Does it read as cinematic or as a cheap parallax wallpaper? (Most important; cheap.)
2. Qwen-Image-Layered / SAM 3 / DA3 on 6 GB: do they run, how long, are layers clean enough at 4K (or must they run at 1–2K and be upsampled as mattes)?
3. WanGP on this machine: time + quality for a 5 s 480p I2V patch; does VACE loop closure hold up after SeedVR2 upscale?
4. Loopy single-GPU feasibility (reference is 8-GPU) — likely rented-GPU only.
5. Renderer choice: shader prototype vs Blender for the same layered scene; measure preview fps and 4K frame time.

## Sources

- https://github.com/deepbeepmeep/Wan2GP · https://www.mimicpc.com/learn/wan2gp-guide-to-low-vram-ai-video-generation · https://localaimaster.com/blog/local-text-to-video-low-vram
- https://www.hyperstack.cloud/blog/case-study/best-open-source-video-generation-models · https://ltx.io/blog/open-source-video-generation-models-guide · https://ltx.io/model/ltx-2-5 · https://www.marktechpost.com/2026/08/11/the-video-production-stack-now-fits-on-one-desk-ltx-2-5-launches-as-nvidia-accelerated-open-weights-world-model/
- Loopy: https://www.alphaxiv.org/abs/2608.23090 · https://huggingface.co/htdong/Loopy — Mobius: https://arxiv.org/pdf/2502.20307 — DreamLoop: https://arxiv.org/abs/2601.02646 — LoopAnimate: https://arxiv.org/pdf/2404.09172
- VACE loop: https://openart.ai/workflows/nomadoor/loop-anything-with-wan21-vace/qz02Zb3yrF11GKYi6vdu · https://www.nextdiffusion.ai/tutorials/wan-2-2-looping-animations-in-comfyui
- LLM→Blender: https://arxiv.org/html/2508.08228v1 (LL3M) · https://arxiv.org/html/2403.01248v1 (SceneCraft) · https://arxiv.org/html/2411.18644v1 (Scene Co-pilot) · https://github.com/FreedomIntelligence/BlenderLLM · https://github.com/princeton-vl/infinigen
- HY-World 2.0: https://www.blog.brightcoding.dev/2026/09/16/tencent-hunyuanhy-world-20-open-3d-world-generation-from-text-images-and-video · https://github.com/Tencent-Hunyuan/HunyuanWorld-Mirror
- Layers/masks/depth: https://github.com/QwenLM/Qwen-Image-Layered · https://github.com/facebookresearch/sam3 · https://sourceforge.net/projects/depth-anything-3.mirror/
- Cinemagraph: https://github.com/text2cinemagraph/text2cinemagraph
- Render→real: https://www.emergentmind.com/papers/2603.23462 (RealMaster) · https://arxiv.org/html/2501.03847v1 (Diffusion as Shader)
- Upscalers: https://upsampler.com/blog/seedvr-vs-flashvsr-ai-video-super-resolution-2026 · https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
- Image models: https://www.bentoml.com/blog/a-guide-to-open-source-image-generation-models · https://botmonster.com/ai/best-local-image-generation-models-2026/
- Hosted video pricing: https://www.buildmvpfast.com/api-costs/ai-video · https://evolink.ai/blog/best-ai-video-generation-models-2026-pricing-guide
- GPU rental: https://www.runpod.io/pricing · https://vast.ai/pricing/gpu/RTX-5090 · https://gpuperhour.com/
- ComfyUI: https://docs.comfy.org/development/comfyui-server/comms_overview · https://blog.comfy.org/p/dynamic-vram-in-comfyui-saving-local
- Blender: https://www.blendernation.com/2024/08/08/the-ultimate-guide-to-seamless-looping-animations-in-blender-4-2/ · https://garagefarm.net/blog/eevee-vs-cycles
