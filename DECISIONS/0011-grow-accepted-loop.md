# 0011 — A shortened loop is grown back to length from the inside
Status: accepted (2026-09-27, applying the round-2 research report's suggestions as instructed; backed by two
user verdicts)
Date: 2026-09-27

## Problem
When the extension drifts, the fallback ladder (ADR 0010) delivers a shorter loop (17-18 s), below the 30 s target.
Open-ended extension is the drift source (pine7's 30 s loop showed a passing shadow in review); more extension seeds do not fix it.

## Considered approaches
1. Accept the short loop (status quo).
2. Grow the accepted loop from the inside (report §1 / §3 C3): keep its closure, replace one interior 32-frame passage
   with a longer generated passage whose clean contexts are the loop's own frames on BOTH sides (two-sided bridge,
   true latents, the close stage unchanged). The loop's outer boundary is untouched; nothing is continued open-ended.
3. One long return (take end back to frame 89 with a ~320 f gap) instead of extension + 32 f closure: positive on
   metrics for the furnace (churn 1.04 vs 1.54-1.62), user verdict pending. A separate decision, not this one.

## Evidence
`research/scene-perfection-round2.md` §1, `research/plan-2026-09-26.md` row 6:
- rain 30 s loop -> 35.3 s (160 f bridge): no visible join in review; -> 42 s (320 f): unnoticed.
- pine7 17 s cut (passed) -> 30.0 s (344 f bridge, contexts in the extension window) **passed, no visible join**
  (review, 2026-09-27); region drift over the loop 2.95 grey (the extension-route 30 s loop: 9.76), churn 1.06.
- Two-sided vs one-sided (report §8 M2, same waterfall passage, same seed): one-sided drifts monotonically to 13.5 grey
  outside the take's envelope in 13.7 s (the mist brightens); two-sided stays at ~3 (the decode-offset floor).
- falls_loop grown 17.7 -> 30 s by the stage itself: the user saw only the KEPT 32 f closure (7 s); both joins of
  the 328 f passage were clean.

## Decision
`stages/grow.py` + the loop path: after a closure is selected, when the loop is shorter than the requested length by
more than a second, pick the interior cut (e, e + 32) nearest the middle of the loop's segment whose contexts lie
inside one source (take or extension window) and clear of the splice ramps; G = the missing frames + 32 (8-aligned,
capped by WanGP's 481-frame LTX window: G <= 368, i.e. up to +14.0 s per growth). Render with `close` (end_frame = e,
start_frame = e + 32), rotate the accepted loop so the cut sits at the wrap (`grow` stage, CPU), `splice` it, and
`loop_qc` it. **Rollback:** if the grown loop fails loop_qc, the accepted short loop is delivered with a warning.

## Tradeoffs
~15 min GPU per growth. The grown loop's first frame is the interior cut's start, not the keyframe moment (nothing
downstream assumes it). A preserved boundary preserves only that boundary: the new joins and the new passage still
need review (report §1), so the review packet marks both joins.

## Consequences
Fallback ladder: extension seeds -> best-effort extension <= 7.5 -> easiest cut >= 17 s -> **grow to length** ->
failure packet. One growth per run for now; two shorter growths instead of one long one is untested (report §1).

## Revisit when
A grown loop fails review, a scene needs more than one growth (> 14.8 s missing), or approach 3 (long return) wins
its verdict and makes the extension unnecessary altogether.
