# Visual regression set (handoff 2026-09-27 §17, realism amendment §14)

Reference videos with the user's actual verdicts, for checking that pipeline changes keep what already worked. No
numeric quality assertions: diagnostics may be compared (`python -m looper trace RUN`), the verdict comes from the eye.
All under `runs/` (gitignored, local disk).

| case | artifact | verdict (review) | what must stay true |
|---|---|---|---|
| rain cabin, 30 s | `rain_loop_e2e/stages/deliver/73fc153f1b762cbf/loop_420.mp4` | nothing noticed | rain keeps falling, no join, steady interior |
| rain cabin grown 35 / 42 s | `endpoint/rain_loop_e2e_interior_e281_g160/`, `..._g320/` | not noticeable / not noticed | long two-sided bridges invisible |
| pine, grown 17 -> 30 s | `endpoint/dir_pine7_grow30_e601_g344/` | **no visible join** | dappled light and sway, no drift over 30 s |
| pine endpoint cut, 17 s | `endpoint/dir_pine7_e777_s401_g32/` | transition not noticeable at all | ADR 0010 cut |
| waterfall grown to 30 s | `falls_loop/stages/deliver/bd9e40bf51347c1a/loop_420.mp4` | transition visible only at 7 s (the kept 32 f closure) | failure case: short closure between distant states |
| furnace | `dir_furnace_mild/stages/deliver/46f840f183be559c/loop_420.mp4` | clearly noticeable | failure case: closure churn; periodic wheel re-synthesises (rigid-rotation example) |

Content diagnostics on the delivered loops (review v3 `trace.compare`, loop vs its own take): moving-region motion
ratio min 0.90-0.99, brightest light 0.97-0.99 on the passed loops -- the freeze / fade DOUBT lines (0.5 / 0.7) do
not fire on any of them.

## Reproducing a passed loop under its original recipe

The recipe of every stage is in its `stage.json` (config, seed, input hashes) and `settings.json` (exact WanGP
settings, incl. the prompt as rendered). Defaults changed on 2026-09-27 (director v15, settle `auto`, PACE /
WATER_PACE / BASE_NEGATIVE wording), so to re-render an old scene the old way: take its `take/*/settings.json` prompt
and negative, and run `looper loop --image <its keyframe> --raw-prompt --prompt-file <that prompt> --negative "<that
negative>" --always-settle` (or `--no-settle` when the run had no `take[settle]`). Cached stages of the old runs stay
valid as they are: nothing rewrites a finished stage.
