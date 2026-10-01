# Gate replay: is the take gate phase-dependent, and what actually drifted? (2026-09-26/27, experiment 1 of the ChatGPT plan)

Zero GPU. `experiments/gate_replay/replay.py` re-scores every cached take / long take (per 3x4 cell, per-second luma
means from frame 89 = the loop's start) with four measures side by side, then splits each drift into a global
(exposure) part and a regional (shadow / flare) residual.

| measure | definition | what it means for a loop |
|---|---|---|
| trend | take_qc v2: rise of a fitted line | the current gate |
| boundary | \|mean(last 2 s) − mean(first 2 s)\| | what the generated closure has to bridge |
| excursion | range of a 3 s moving average | how far the scene wanders, whatever the shape |
| pulse | take_qc v2: detrended peak-to-peak | allowed glow / breathing (cap 12) |

## 1. The plan's counterexample is right, and irrelevant to every take we have

`Y = 100 + 4 sin(2πt/20 + φ)`, twenty one-second means:

| phase | trend | pulse | boundary | excursion |
|---|---|---|---|---|
| 0° / 180° | 7.31 | 6.05 | 2.44 | 7.64 |
| 90° / 270° | 0.00 | 7.90 | 0.00 | 7.27 |
| true creep +6 | 6.00 | 0.00 | 5.68 | 5.37 |

The fitted trend of one periodic signal swings 0–7.3 with its phase (rejected at 180°, passed at 90°); boundary and
excursion do not move. **But on every real take the three agree within ~1–2 grey** (table below): no LTX take has ever
been periodic at this time scale — they creep. So the v2 gate has not been discarding cycles; its calibration
(1.7 nothing noticed / 6–7 very slight / 10.7 noticeable) transfers to `boundary` unchanged.

**Adopted (take_qc v3):** the cell gate is `boundary` (the quantity the closure must bridge; phase-invariant) with the
same 4 / 7.5 limits; `trend` stays in the meta as a diagnostic. Decisions on all judged takes are unchanged.

## 2. Real takes (worst cell; `qc` = the number the pipeline recorded, from frame 48 instead of 89)

| run | video | trend | pulse | boundary | excursion | common | residual (cell) | qc | verdict |
|---|---|---|---|---|---|---|---|---|---|
| rain_loop_e2e | take s306 | 1.57 | 0.72 | 1.42 | 1.37 | 0.25 | 1.26 | | nothing noticed |
| rain_loop_e2e | long | 2.41 | 1.30 | 1.81 | 1.88 | 0.74 | 1.95 | | nothing noticed |
| dir_neon | long | 1.47 | 1.27 | 1.12 | 1.51 | 0.63 | 1.50 | 1.79 | hard to tell |
| dir_furnace | long (4.26 best effort) | 3.39 | 3.04 | 2.38 | 3.59 | 1.13 | 2.05 | 4.26 | very slight jump |
| dir_furnace_bright | long | 2.39 | 2.68 | 2.63 | 3.05 | 1.15 | 3.54 | 3.31 | no drift complaint |
| neon_loop | take s306 (accepted) | 3.70 | 1.81 | 3.37 | 3.48 | 0.59 | 3.90 | 3.93 | really hard to tell |
| falls_loop | take s306 (best effort) | — | — | — | — | — | — | 6.88 | very slight (as warned) |
| dir_pine7 | long | 9.44 | 6.04 | 7.83 | 8.65 | **2.51** | **8.47 (c9)** | 9.76 | noticeable, passing shadow |
| dir_pine7 | take s306 | 8.99 | 2.53 | 8.20 | 7.92 | 1.35 | 8.46 (c9) | 10.71 | (same) |
| dir_pine4 | take s307 (sun flare) | 14.03 | 51.3 | 12.4 | 34.1 | 3.65 | **44.8 (c3)** | | unjudged, flare baked |
| dir_lighthouse2 | take s306 (rejected) | 58.7 | 24.0 | 57.3 | 52.9 | **33.9** | 26.4 | | true exposure pumping |
| dir_cabin | take s308 (fireplace) | 1.31 | 5.32 | 1.34 | 3.55 | 0.58 | 3.20 | 6.99* | unjudged |

\* take_qc v1 range; v2 trend 0.93. Full table: `runs/logs/gate_replay.log`.

## 3. Global exposure vs regional change (plan §4.4 rank 1)

`common` = median cell change per second (a global exposure move); `residual` = the worst cell after removing it.

- **dir_pine7's drift is regional, not exposure**: common 1.4–2.5 grey, residual 8.5 in the bottom-left cells (the
  path / lower trunks). That is a moving shadow or dappled-light change, exactly what review described as a passing shadow.
  A global exposure gate would not have caught it; a global colour fix would not fix it.
- **dir_pine4**: residual 24–45 in the top-right cell (the baked sun flare), common 3.7–5.5.
- **dir_lighthouse2 s306 (rejected)**: common 34 = the whole frame pumped. True exposure drift exists and the same
  split isolates it.

So the two failure modes the plan asked to separate are separable from the cell series alone. The split is written
into take_qc v3's meta (`common_range`, `resid_max`, `resid_cell`) so the review packet can say *what* drifted.
It is diagnostic; the gate stays on the worst-cell boundary because the user sees regional drift too (pine7).

## 4. What this does not settle

- No judged take is periodic, so the v3 gate is not yet proven on a case where trend and boundary disagree. When a
  breathing / pulsing take arrives (fire, furnace throb), boundary will pass it and pulse ≤ 12 decides — that is the
  intended behaviour (glow and pulsing are allowed), unverified by a verdict.
- The per-second cell series cannot see sub-second flicker or texture change; regional_qc (loop_qc) covers that.
