# 0002 — Scene realization backbone: generated plate + looping motion layers (hybrid, built 2.5D-first)
Status: **rejected / superseded by 0003** — user has prior hands-on experience that mask-and-animate does not work well. Kept for the record only.
Date: 2026-09-21

## Problem
Choose how scenes are created and animated for the first vertical slice without locking out better approaches later.

## Considered approaches
A. Pure generative video made to loop. B. Full 3D procedural (Blender, LLM-authored / Infinigen / HY-World). C. 2.5D: generated still decomposed into layers, animated procedurally. D. Hybrid: C as backbone, with generative-video patches / RGBA elements / 3D-rendered elements only where procedural motion is not realistic enough. Details and scoring: `research/solution-space.md`.

## Evidence
Literature/web survey only. Decisive arguments: ambient scenes have a locked camera and mostly static pixels; image models beat video models on fidelity/resolution; open video models give 3–5 s, 480–720p loops (Loopy: 53 frames @ 832×480) and need far more than 6 GB to run well; layered compositing is cheap enough to allow coprime-period non-repetition (`research/looping.md`); stream-copy assembly verified (`research/long-form-assembly.md`).

## Decision
Adopt D, implemented C-first. The plan stage assigns each animated element a **motion system**; every motion system declares its period and guarantees loop closure. Slice 1 uses only procedural motion systems on benchmark B1.

## Tradeoffs
- Motion realism ceiling for hard content (waves, animals, fabric) until generative patches exist.
- Layer decomposition quality becomes a critical dependency (masks, inpainted occlusions).
- Risk of "animated wallpaper" look — the reason the ceiling test comes first.

## Consequences
Render = composite of per-layer loops; static plate never passes through a video model. Expensive models are confined to per-element artifacts that cache well. Blender remains optional (element source), not a core dependency.

## Revisit when
The ceiling test reads as cheap parallax; or open video models reach stable 4K, minute-long, loop-controllable output on affordable hardware; or text→3D worlds become hero-quality and animatable.
