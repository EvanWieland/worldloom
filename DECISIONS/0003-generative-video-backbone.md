# 0003 — Scene realization backbone: generative video
Status: accepted (user decision, 2026-09-21). Supersedes 0002.
Date: 2026-09-21

## Problem
Choose how scenes are created and animated.

## Considered approaches
See `research/solution-space.md`. ADR 0002 proposed a generated still + masked/procedural motion layers.

## Evidence
- **User's direct prior experience:** mask-and-animate approaches were tried before and never produced good results. This outweighs the desk-research preference in 0002, which had no experimental backing.
- Desk research on making the video route loop and last: `research/video-route.md` (SVI for drift-free long chains, VACE bridge / Loopy for closure, SR for final quality). Untested locally.

## Decision
Generative video is the backbone: keyframe still → I2V clips → validation → enhancement (deflicker/SR/interpolation) → assembly. **Update 2026-09-21: the original 'chained segments + generated loop closure' was tested and failed locally; see ADR 0004 for the replacement (keyframe-anchored clip pool + dissolves).** Masked procedural animation of stills is **not** pursued.

Constraints set by the user at the same time:
- **Local GPU only for all development and validation.** Rented GPU is allowed for the **final render stage only**.
- Output is **non-commercial** → research/non-commercial model licenses are acceptable.

## Tradeoffs
- 6 GB VRAM makes local iteration slow; preview tiers must be designed around minutes-per-clip, and long jobs must be unattended + resumable per segment.
- Static-region shimmer and drift are inherent risks; they become first-class QA metrics.
- A final tier that *regenerates* at higher quality produces a different video than the one validated. Default is therefore "final = enhance the validated loop"; regeneration is an experiment.
- Bit-level reproducibility is not available across GPUs/precisions; persisted artifacts are the source of truth.

## Consequences
Model host (ComfyUI or WanGP) is reached over an HTTP API so the same stage code can target a rented GPU. Segments are individual fingerprinted artifacts. Coprime-layer non-repetition (looping.md) does not apply; long chained loops and loop families replace it.

## Revisit when
Local experiments show the route cannot reach acceptable stability/looping even at T3, or a fundamentally better open model/technique appears.
