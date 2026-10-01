# Architectural decision records

Only consequential, hard-to-reverse choices. Not for implementation details.

File name: `NNNN-short-slug.md`. Status: `proposed` | `accepted` | `superseded by NNNN`. Never delete an accepted ADR; supersede it.

## Template

```markdown
# NNNN — Title
Status: proposed | accepted | superseded by NNNN
Date: YYYY-MM-DD

## Problem
## Considered approaches
## Evidence
(experiments, measurements, links to research/*.md — say so explicitly if there is none)
## Decision
## Tradeoffs
## Consequences
## Revisit when
```

## Index

- [0001 — Fingerprinted, immutable stage artifacts](0001-fingerprinted-stage-artifacts.md) — accepted
- [0002 — Plate + looping motion layers backbone (hybrid, 2.5D-first)](0002-plate-plus-motion-layers-backbone.md) — rejected, superseded by 0003
- [0003 — Generative video backbone; local GPU for dev, rented GPU for final only](0003-generative-video-backbone.md) — accepted; refined by 0004
- [0004 — Keyframe-anchored clip pool + ping-pong legs (cross-dissolve rejected by human review)](0004-keyframe-anchored-clip-pool.md) — ping-pong rejected; long-form framing superseded by 0005; `enhance.py`+`assemble.py` still implement it (to be rewritten)
- [0005 — Target is a 30–60 s seamless forward-motion loop, proven locally, final-rendered offsite](0005-short-seamless-forward-loop.md) — accepted (user decision 2026-09-22)
- [0006 — Loop closure: 16 fps Wan Fun VACE with context both sides + in-overlap splice ramp](0006-vace-closure-with-splice-ramp.md) — accepted (user verdict 2026-09-24, first imperceptible loop)
- [0007 — Loop closure for particle content: crossover exception vs true-latent LTX gap](0007-particle-content-closure.md) — accepted for single-generation loops (option 2, generated true-latent LTX gap; user blind verdict 2026-09-25); long takes still open
- [0008 — Hosted LLM allowed for the director step, opt-in](0008-hosted-llm-director.md) — accepted (user decision 2026-09-25)
- [0009 — Same-instant ramp at 4K upscale chunk joins](0009-upscale-chunk-join-ramp.md) — accepted 2026-09-26, for user review
- [0010 — Shorter loops are cut at the easiest boundary (endpoint stage)](0010-endpoint-cut-fallback.md) — accepted 2026-09-27, for user review
- [0011 — A shortened loop is grown back to length from the inside (grow stage)](0011-grow-accepted-loop.md) — accepted 2026-09-27 (rain + pine verdicts)
- [0012 — The loop closes with one long return instead of extension + 32 f closure](0012-long-return-closure.md) — proposed 2026-09-27, waiting for two verdicts
- [0013 — Scene contract and content gates, separate from loop continuity](0013-scene-contract-and-content-gates.md) — accepted 2026-09-27
- [0014 — Budget-limited cloud experiments alongside local development](0014-budgeted-cloud-experiments.md) — accepted 2026-09-29 (RunPod, per-experiment dollar caps)
- [0015 — Wan 2.2 VACE route for rotating machinery, with a motion-evidence structure lock](0015-wan-vace-machinery-route.md) — rejected by the user 2026-09-28; director v19 veils rotating parts instead
- [0016 — Motion donor: another model renders the motion, LTX renders the picture and the closure](0016-motion-donor-route.md) — accepted 2026-09-30 (second scene passed: sample_1b, joins and scene approved in review)
