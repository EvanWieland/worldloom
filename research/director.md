# Director: local model vs Claude CLI (T0, text only)

_2026-09-25. Spec `docs/superpowers/specs/2026-09-25-director-design.md`, ADR 0008. Everything here is a **hypothesis**
until keyframes (section 2) and loops (section 3) are judged by the user._

## 1. T0 — 19 prompts through the `direct` stage, no video

Prompts: the 14 sweep scene titles (`experiments/night_scenes/scenes.py`, which also holds the hand-written
prompts they are compared against) + 5 deliberately unloopable prompts. Script `experiments/director_t0/run.py`;
outputs `experiments/director_t0/{ollama,claude}/<scene>/direction.json`, logs `local.log`, `claude.log`.

| | local `gemma4:12b` (Ollama) | Claude Code CLI (default model: Sonnet 5) |
|---|---|---|
| completed | 19/19 | 19/19 |
| time per prompt | 41–98 s (reload after every call: `keep_alive 0`) | 12–30 s |
| cost | free | ~$0.07 API-equivalent per call (CLI-reported figure) |
| hard prompts adapted correctly | 3 of 5 | 4.5 of 5 |

Hard prompts:

| prompt | local | Claude |
|---|---|---|
| sunrise over a misty lake | golden-hour light (scene text still says "during a sunrise") | a held dawn moment + mist at constant density |
| woman walking her dog | **still walks forward** (adaptation: "walking in a repetitive cycle") | stands still, scarf/tail/leash idle motion |
| thunderstorm with lightning | steady distant glow | soft glow pulsing inside the clouds, storm at constant intensity |
| busy Tokyo crossing | **cars crawl forward**, "rain droplets suspended" on a clear night | cars waiting, a steady red light; crowd density constant (crowd still walks — partial) |
| campfire with sparks | steady twilight | fire never burns down, continuous spark stream, held dusk |

Other observations:
- Claude gives every light source its natural behaviour (lighthouse beam "sweeps slowly and steadily around";
  research/motion-prompting.md rule 10); local does sometimes ("lighthouse beam rotates clockwise").
- Both write clauses in the style of the hand prompts (direction, pace). Claude's are richer (5–7 moving elements,
  explicit directions); local's are shorter (3–5).
- Bugs found and fixed on the way (all with tests): gemma4 returns lists as one string (every clause was lost);
  Ollama had run CPU-only since the 2026-09-22 driver update (garbled words, slow) — restart fixed it; thinking models
  need `think: false`; the contradiction check dropped fixed items sharing any word ("Stone lighthouse tower") — now
  head noun only; "spread" was wrongly banned. The local log above was produced with the older checker (its dropped
  lists are over-eager; the model's text is unaffected).

**Conclusion (hypothesis):** Claude CLI is the better director — faster, and it adapts unloopable prompts the way the
spec asks. Local gemma4 is usable for ordinary ambient scenes but misses subjects crossing the frame (walker, cars).
Recommendation: judge keyframes (section 2) with both on the same 4 scenes before choosing the default.

## 1b. Best local model for this machine (user request, 2026-09-25)

Web research (sources below): the strongest open vision models that fit 6 GB VRAM + 64 GB RAM are the MoE models with
~3–4B active parameters — Qwen3.6-35B-A3B (Apr 2026) and Gemma 4 26B-A4B; Qwen3.6 leads on vision evals (71.9 % vs
63.6 % average, Roboflow) and on the Artificial Analysis index. Dense 27–31B models would run several times slower with
most weights on the CPU. Installed `gemma4:12b` is an 11.9B dense model.

Measured here (`experiments/director_t0/model_ab.py`, `think_ab.py`; logs `ab_qwen36.log`, `think_qwen36.log`):

| model | placement | speed | hard prompts right | notes |
|---|---|---|---|---|
| gemma4:12b, no thinking | 54/46 CPU/GPU | 41–98 s/call | 3/5 | walker + cars still cross the frame |
| qwen3.6:35b, no thinking | 87/13 CPU/GPU, 4.3 GB VRAM, ~27 GB RAM | 28–32 tok/s, 32–68 s/call | 1/5 | "light brightens", "flashes", "signals cycle" |
| **qwen3.6:35b, thinking** | same | 30 tok/s, **2–4 min/call** (3.6–6.7k tokens) | **~4/5** | sunrise, storm, street, campfire right; walker paces a small loop in frame |
| Claude CLI | — | ~22 s/call | 4.5/5 | |

- **Thinking is what makes a local director follow the loop rules**, not size. Setup needed: `think: true`, no Ollama
  JSON mode (empty replies), context 16 384 (the 4 096 default filled with thinking, no answer).
- Qwen3.6 hit an intermittent llama-server CUDA crash on reload (1 of 8 calls, `0xc0000409`) — watch for it.
- Decision (provisional): local default director = `qwen3.6:35b` with thinking; the critic stays without thinking
  until section 2 says otherwise.

Sources: [Roboflow vision comparison](https://playground.roboflow.com/models/compare/gemma-4-26b-a4b-vs-qwen3-6-35b-a3b),
[Artificial Analysis](https://artificialanalysis.ai/models/comparisons/qwen3-6-35b-a3b-vs-gemma-4-26b-a4b),
[Qwen 3.5–3.8 guide](https://codersera.com/blog/qwen-3-5-complete-guide-2026/),
[Gemma 4 model card](https://ai.google.dev/gemma/docs/core/model_card_4),
[Ollama gemma4](https://ollama.com/library/gemma4), [Ollama qwen3.6](https://ollama.com/library/qwen3.6).

## 2. Keyframes + critic (2026-09-25/26, no picks yet)

- **Critic (qwen3.6, no thinking):** v1 wrote prose / `true` instead of 1–5 scores for 2 of 3 dir_neon stills (both
  scored 0). v2 (integer example + one retry) returned clean integers on every later run. Its picks matched mine by
  eye on dir_neon, dir_pine, dir_pine2, dir_pine4. Whether they match the user's is still open.
- **Director bugs found by real runs** (all fixed with tests; `direct` v2→v9): lists as one string; invented
  mist (dir_pine) and an invented stream (dir_pine2); "sparkling" adapted away; plural-blind grounding dropped
  "branch tips sway"; the keyframe prompt's settled-state clause named mist/steam in every scene (likely painting them
  in; now only when present).

## 3. Loops (T2, 480p → T3a 4K)

| run | prompt | outcome |
|---|---|---|
| dir_neon | "Rainy neon alley at night" | **30.0 s loop, take drift 1.13 grey (best yet), closure 1.086 → 4K delivered** (58 Mbps, joins < median step). User dislikes the look. |
| dir_pine | "A light, sparkling, photorealistic pine forest scene" | failed: director-invented mist built up (17–43 grey) |
| dir_pine4 | same (director v7) | failed: a sun + rays grew top-right in every take (13.8–60 grey); baked into the settled keyframe |
| dir_pine5/6 | pine4 still, no settle, anti-flare negatives / "sun stays hidden" wording | 55.6 / 68.2 grey: negatives do nothing on distilled LTX; naming the sun grows one |
| dir_pine7 | front-lit still (12× less bright sky), no sun words | **10.7 / 14.1 / 10.9 grey, no sun by eye** — remaining drift: dappled light on the path/moss shifting with branch sway |

Conclusions (hypotheses until repeated):
1. **Daylight: keep the sun out of the prompt entirely and prefer front-lit stills** (bright sky regions become a sun).
2. **Negative prompts are ineffective on the distilled LTX recipe** — every fix must be positive wording or still choice.
3. **Settling only helps scenes with accumulating elements**; on a clean daylight scene it baked in a transient flare.
   The user's "always settle" decision (2026-09-25, for steam scenes) needs revisiting.
4. **Dappled light under swaying branches reads as region drift (~11 grey) — and the eye agrees.** dir_pine7 built at
   a raised gate (11): 30 s loop, closure 1.027. **Reviewer (2026-09-26): noticeable, but reads more like a passing
   shadow; should be more subtle.** Calibration now: 1.7 nothing · 6.1–6.9 very slight · 10.7
   noticeable (passing shadow) · 13.7 a shift · 35 clearly visible. Keep the 7.5 best-effort gate.
5. **4K:** separate FlashVSR runs invent different texture → joins must be ramped (same-instant exception);
   NVENC needs `-maxrate` or it silently caps at 20 Mbps.
