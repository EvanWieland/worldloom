# 0010 — Shorter loops are cut at the easiest boundary, not at a fixed frame
Status: accepted (2026-09-26/27, executor ruling under a standing instruction to proceed without asking; for user review)
Date: 2026-09-27

## Problem
When no extension is stationary (≤ 7.5 grey best effort), the pipeline fell back to the take alone, cut at fixed
frames (start 89, end 481): a 17.7 s loop whose end-to-start mismatch is whatever the take happened to do. On the
drifting scenes that is the very-slight-to-noticeable band (falls_loop 5.8, pine7 8.5 grey), while the rejected
extension's long take often contains a later, flatter window the fixed cut never sees.

## Considered approaches
1. Fixed take-only cut (status quo).
2. Search every legal (end, start) pair of every long take that exists (the take, each rejected extension's long)
   for the smallest end-to-start mismatch at ≥ 17 s, ranked by the same measure take_qc gates on; render the
   closure there. Video-texture endpoint selection (Schödl 2000) applied to a *generated* transition.
3. Pair the search with more closure seeds / longer gaps — orthogonal, not needed for this decision.

## Evidence
`research/plan-2026-09-26.md` row 2, `experiments/endpoint_search/bridge.py`, loops in `runs/endpoint/`:
pine7 3.68 vs 8.51 take-only (bridge accepted, joins 1.17 / 1.05; the delivered 30 s loop was 9.76 and showed
a passing shadow in review); falls_loop 3.75 vs 5.82; cabin 0.51 vs 1.88; dir_falls: the fixed cut is already the best
(4.4 vs 4.09, below the 0.5 margin). Legal frames: 8j + 1 (latent groups), start ≥ 49 (close.MIN_START_FRAME),
start context inside the take, end context inside one source. A ranking on a finer grid picked a pair the gate
scored worse than the fixed cut — the ranking measure must be the calibrated one (3x4 cells, 2 s means).

## Decision
Option 2 as `stages/endpoint.py` (CPU, fingerprinted): in `_shorter_cut`, the best pair wins when its boundary beats
the take-only cut by more than 0.5 grey; `close` v2 and `splice` v3 take an `end_frame`. A 30 s best-effort extension
still wins over any 17 s cut (30 s is preferred at equal drift). Human verdicts on the rescued loops are pending.

## Tradeoffs
A shorter loop, declared as such in the warning ("loop cut to 17.0 s at frames 401-777"). The start context may sit
late in the take (frame 401), so the loop's "first frame" is no longer the keyframe's moment; nothing downstream
assumed it was. One extra CPU stage per long (seconds).

## Consequences
The fallback ladder is now: extension seeds → best-effort extension ≤ 7.5 → easiest cut ≥ 17 s → fixed take-only
cut → failure packet. Interior expansion (plan exp 6, positive on the rain loop) may later make 30 s reachable
without an extension at all; that would be its own ADR.

## Revisit when
A user verdict on a rescued loop contradicts the boundary calibration, or interior expansion supersedes the extension.
