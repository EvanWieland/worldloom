# 0009 — Same-instant ramp at 4K upscale chunk joins
Status: accepted (2026-09-26, executor ruling under a standing instruction to proceed without asking; for user review)
Date: 2026-09-26

## Problem
The local 4K stage (`looper/stages/upscale.py`) upscales a loop in chunks (6 GB GPU; ~31 min per 160 frames). Each
FlashVSR run invents fine texture differently, so butt-joined chunks popped at every join and at the loop point:
~10-11x the median frame step (dir_neon, joins at frames 143/287/431/575 and the wrap). Real neighbour frames on both
sides of every chunk ("circular" margins) did not help: two runs never agree on invented detail.

## Considered approaches
1. One run over the whole loop — RAM/VRAM at 4K for 720+ frames is untested and the loop point would still join the
   run's first and last frames (early vs late state).
2. Butt joins (v1) — measured pop, rejected.
3. Ramp from run i-1 to run i over the context overlap, circular at the loop point.

## Evidence
dir_neon: v1 joins 9.6-10.6x median step; v2 (8-frame ramp) joins 0.36-0.99x, i.e. below an ordinary frame step;
loop wraps 1.27-1.36, file wrap 1.82 vs max natural 3.62 (`research/director.md` §3, ledger
`.superpowers/sdd/2026-09-25-director/progress.md`).

## Decision
Option 3. Both sides of every ramp are renders of the **same source instant** (the same 832x480 frame upscaled by two
runs), which is the exception invariant 10 already grants inside ADR 0006's bridge context overlap; this ADR extends
it to upscale chunk overlaps. It is not a blend between different content. `run_deliver4k` gates every join
(`join_steps`, `accept`).

## Tradeoffs
A ~1/3 s cross-fade between two texture hallucinations at each join (not visible in the metrics or by eye so far).

## Consequences
Invariant 10's wording in CLAUDE.md cites this ADR next to ADR 0006.

## Revisit when
A single-run upscale of a whole 30 s loop fits the machine (or a rented GPU), or the user sees the ramps.
