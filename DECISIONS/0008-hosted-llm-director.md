# 0008 — Hosted LLM allowed for the director step, opt-in
Status: accepted (user decision 2026-09-25)
Date: 2026-09-25

## Problem
Prompt-only loops need a director that turns any user prompt into a keyframe prompt + LTX motion prompt written to
the rules we proved by hand. Invariant 13 keeps everything local; local models are free but weaker (a 12B vision
model copied example phrases and invented details in the 2026-09-25 describe test).

## Considered approaches
1. Local Ollama only (invariant 13 as written).
2. Claude only.
3. Local by default, Claude selectable per run (`--director claude`).

## Evidence
2026-09-25 describe test (STATE.md): gemma4:12b drafts plausible but noisy; qwen3/qwen3-vl return empty responses
(thinking models). No Claude comparison yet — measured in research/director.md.

## Decision
Option 3 (user choice). Only the text/vision director and keyframe critic may call a hosted model, only when the
run asks for it. Video generation, QC and delivery stay local.

## Tradeoffs
Claude costs cents per scene and needs credentials; local stays free and offline.

## Consequences
`looper/models.py` gains a Claude provider that runs the **Claude Code CLI headless** (`claude -p --output-format
json --json-schema ...`) on the user's own login — no API key, no SDK (user decision 2026-09-25: not the
Anthropic API, start with the Claude command line; ChatGPT Codex / Gemini CLIs may be added later the same
way). The CLI runs in a temp dir (no repo CLAUDE.md in its context) with only the Read tool, limited to the image
folders. Measured 2026-09-25: 7 s for an image + schema call, default model Sonnet 5, $0.07 API-equivalent reported.
Invariant 13 reads "local GPU only ..." for generation; hosted text/vision calls are opt-in per run. Every call records
provider, model, tokens and the CLI's cost figure.

## Revisit when
The T0 comparison (research/director.md) shows one provider clearly better, or cost/credentials become a problem.
