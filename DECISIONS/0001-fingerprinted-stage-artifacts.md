# 0001 — Fingerprinted, immutable stage artifacts for resume and invalidation
Status: **accepted** (Phase 1 slice demonstrated it, 2026-09-22 — see Evidence)
Date: 2026-09-21

## Problem
Late-stage failures must not rerun earlier stages, and a change must invalidate only what actually depends on it (`prompt.txt` § Hydration / Resumability).

## Considered approaches
1. **Timestamp/mtime-based (make-style).** Simple, but breaks across machines and on config changes that touch no file.
2. **Explicit hand-written invalidation rules per change type.** Flexible, but every new option needs a new rule; silent staleness when one is forgotten.
3. **Content fingerprint per stage** = hash(stage name + stage version + that stage's config slice + seed + input artifact hashes); output stored under the fingerprint; existing `ok` directory = cache hit.
4. **Adopt a workflow tool (DVC, Snakemake, Prefect, …).** Gives caching/DAGs, but adds a heavy dependency and its own model for events, remote execution, and metadata that we'd have to work around.

## Evidence
Implemented (`looper/engine.py`, ~180 lines) and exercised on real pipeline runs (`STATE.md`, 2026-09-22), not just unit tests:
- Growing the clip pool 3→4 reran exactly the one new clip; the 3 pre-existing clips' full generate/enhance/validate chains (9 stage checks) all cache-hit.
- An identical rerun at pool_size 4 was 14/14 cache hits, 0.1s total, producing the same final video.
- A real bug (`generate` failing on every clip with `KeyError: 'seed'`) demonstrated resume-after-failure for real: the already-succeeded `keyframe` stage stayed cached and was reused across 3 subsequent invocations while the bug was found and fixed.
- Bumping `plan.py`/`validate.py`'s stage `VERSION` after fixing real output-affecting bugs correctly invalidated exactly those stages (and their downstream) without touching `interpret`/`keyframe`/`generate`/`enhance`.
- 36 unit tests (`tests/test_engine.py` etc.) cover the mechanism in isolation; the real runs above cover it end-to-end.

Approach 3 is the well-established build-system technique (Bazel/Nix-style); the pipeline is a short linear-ish DAG, so the implementation stayed small as predicted.

## Decision
Approach 3, implemented directly (small amount of code, fully tested). Artifacts immutable; reruns write new directories.

## Tradeoffs
- Requires disciplined, explicit per-stage config slices — a sloppy slice over-invalidates.
- Stage authors must bump the stage version when output-affecting logic changes; forgetting causes stale hits.
- Old fingerprints accumulate on a disk with little free space → needs a prune command eventually.

## Consequences
Resume, retry, "rerender only", and "change resolution without rebuilding" are all the same operation: run the pipeline again. Non-deterministic stages are handled because the persisted output, not regeneration, is the source of truth.

## Revisit when
The DAG becomes large/dynamic, multi-machine scheduling gets complicated, or cross-run artifact sharing becomes important — then re-evaluate approach 4 or a global content-addressed store.
