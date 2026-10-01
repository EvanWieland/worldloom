# 0012 — The loop closes with one long return instead of extension + a 32-frame closure
Status: **accepted** (2026-09-27) — review verdicts: harvester transition imperceptible; furnace 320 f, waterfall 328 f, pine 328 f returns barely noticeable, passed (each). Implemented: default route when one window fits (`loop_pipeline.long_return_fits`); `--no-long-return` for the old route.
Date: 2026-09-27

## Problem
Every transition reviewed since ADR 0007 is a 32-frame closure (falls_loop visible only at 7 s; furnace_mild
clearly noticeable x2; dir_furnace / dir_falls very slight), while every long two-sided bridge (160-344 f, four
scenes) has been judged clean. A 32 f closure between two distant states re-synthesises the whole frame (churn worst
region 1.57-1.83 on visible ones); the extension that makes 30 s possible is itself the main drift source.

## Considered approaches
1. Status quo: take -> extension -> 32 f closure (-> endpoint cut -> grow, ADR 0010/0011).
2. **Long return:** take -> ONE closure whose gap fills the loop to length: loop = take[89:481] (16.3 s) + G-frame
   return (G = target - kept take, up to 368 per 481-frame LTX window). No extension, no short closure.
3. Better pairs at 32 f (motion-aware ranking): tried, 1.42-1.45 on the furnace, not enough (research §1 C2).

## Evidence (research/scene-perfection-round2.md §1)
- Furnace positive control: the model fills 32 f between NEIGHBOURING states cleanly (1.13); only the return fails.
- Furnace 320 f return: churn 1.04 (vs 1.54-1.62 for six 32 f closures), drift 1.29. Verdict pending.
- Waterfall 328 f return: churn 1.02 / worst 1.11, drift 1.92. Verdict pending.
- **Harvester (2026-09-27, first user-judged A/B on one take):** extension + 32 f closures failed loop_qc x3 (churn
  1.28, drum cells low), reviewer: rough and very noticeable, the smoke rebuilds suddenly after the stitch. Long return
  (seed 306, 12.8 min at 832x480): PASS, churn 1.08 / worst 1.18, drift 4.3; **reviewer: transitions imperceptible.**
- M2: a two-sided passage holds the medium's statistics; a one-sided one drifts 13.5 grey in 13.7 s.

## Decision (if both verdicts pass)
Option 2 as the default loop path for 30 s; the take seeds and take_qc stay; `close` runs with G = target - body;
1-2 seeds (a 328 f window is ~14 min). The endpoint cut and grow stages remain the fallback when the take drifts.

## Tradeoffs
~14 min per closure seed instead of ~4 (but no ~8.5 min extension per seed). 60 s loops need growth (ADR 0011) on
top, since one window adds at most 16 s.

## Revisit when
Either verdict fails, or a scene's take cannot hold 16 s.
