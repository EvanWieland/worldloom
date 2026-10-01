# 0014 — Budget-limited cloud experiments alongside local development
Status: **accepted** (user decision, 2026-09-29: run Hunyuan on a rented GPU; provider **RunPod**, a per-experiment
dollar cap; the first experiment = the Hunyuan 1.5 720p bake-off finalists). Relaxes CLAUDE.md invariant 13.
Date: 2026-09-27 (proposed), 2026-09-29 (accepted)

## Decision (2026-09-29)
- Provider RunPod, with a local watchdog that terminates the pod at the experiment's time/cost cap whatever state
  the session is in.
- API key only from the user environment variable `RUNPOD_API_KEY` (invariant 15): never printed, logged or stored.
- Recipe parity: same WanGP commit, same `wgp_config.json` quantization, same attention mode, same settings as the
  local arm; one seed re-rendered remotely that already exists locally (parity check), so a remote result can be
  compared with a local one before it is trusted.
- Every paid experiment gets its own cap from the user; this acceptance does not pre-authorize later spending.
- The cap is money, not time (a longer run is acceptable while spend stays under the cap): the watchdog deadline
  is the moment estimated spend reaches the cap minus a small margin (`runpod.py cap`), and finished results are
  pulled as they land so a cap termination only loses work in progress.

## First experiment (2026-09-29): Hunyuan 1.5 720p finalists
H100 80GB SXM secure, $3.49/h, 68 min, ~$3.96, under the cap. 21 / 19 / 19 min per 5 s clip vs 234 min on the laptop.
Parity: same settings reproduce the laptop's clip behaviour, not its pixels (sdpa vs sage2, different GPU).
Lessons (fixed in `experiments/cloud/runpod.py`): Cloudflare rejects Python's default User-Agent (403 / 1010); a
backgrounded `cd x && cmd &` keeps ssh open for the whole job; Git Bash rewrites `/workspace/...` arguments to
Windows paths (MSYS_NO_PATHCONV=1). Results: `research/model-bakeoff-2026-09.md`.

## Problem
Invariant 13 allows rented GPU only for the final render / enhance stage. Some questions (a 720p Dev two-stage recipe,
a larger model, a quality baseline) cannot be answered on the 6 GB laptop in useful time, and today they cannot be
answered anywhere.

## Proposal
Local operation stays complete. Explicitly enabled, budget-capped cloud runs may establish quality and performance
baselines. Every remote job is a job contract (`looper/job.py`, `python -m looper job RUN KEY`): stage version,
config, seed, input hashes, contract fingerprint, recipe, WanGP revision, output destination, wall-time and cost
caps. Execution location may not change the recipe; a returned result whose fingerprint differs is a new candidate
that needs content and continuity review, never a drop-in.

## Not decided / not built
No provider, no submission path, no credentials. The job contract exists and is `enabled: false`. Before any paid job:
the user names a provider and a per-experiment ceiling; startup, download, storage and inference costs are reported
separately. A territory-restricted licence (MiniMax H3's) is not worked around by renting hardware elsewhere.
