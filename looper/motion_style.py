"""Deterministic prompt clauses proven on LTX loops, as CODE rather than something hoped for from an LLM.
Evidence: research/particle-loop-closure.md. (The Wan 2.2 calm/NAG recipe of the retired pool path is recorded in
research/local-video-baseline.md.)
"""
from __future__ import annotations

import re

STEADY_LIGHT_POS = ("The overall lighting, exposure and colour of the scene stay exactly constant from the first frame "
                    "to the last.")
STEADY_LIGHT_NEG = ("brightening, increasing brightness, exposure change, lights turning on, warm amber glow spreading, "
                    "day light, colour shift")


STEADY_EXPOSURE_POS = ("The overall exposure and colour grade stay constant from the first frame to the last; only the "
                       "scene's own moving light changes where its light falls.")
# one sentence names a beam and turns it. The clause switch is a stage-config key (`moving_light`, present only when
# true), so it is in the fingerprint: dir_lighthouse's cached beam takes keep their old recipe.
ROTATING_BEAM = re.compile(r"\b(beams?|beacons?|searchlights?)\b[^.;]*\b(sweep\w*|rotat\w*|revolv\w*|circl\w*|spin\w*|"
                           r"turn\w*)", re.I)
# light shafts / god rays moving with clouds or dust: intended illumination change too (amendment §14 castle case).
# The motion word may also stand before them ("shifting shafts", "moving light shafts"), at most one word away.
_SHAFT = r"(shafts?|god ?rays|sunbeams?|rays)"
_SHIFT = r"(mov\w*|shift\w*|drift\w*|pass\w*|sweep\w*|slid\w*|travel\w*|wander\w*)"
LIGHT_SHAFTS = re.compile(rf"\b{_SHAFT}\b[^.;]*\b{_SHIFT}|\b{_SHIFT}\s+(\w+\s+)?{_SHAFT}\b", re.I)


# a light source that pulses / flashes on purpose (anti-gravity emitters breathing, lightning): "lighting stays exactly
# constant" froze the leviathan's emitters to +-1 grey over 20 s (research/leviathan.md)
PULSING_LIGHT = re.compile(r"(?=[^.;]*\b(light\w*|glow\w*|emitters?|discharge|flares?|cores?)\b)[^.;]*\b(puls\w*|flash\w*|"
                           r"throb\w*|strob\w*)\b", re.I)


class _AnyOf:
    """MOVING_LIGHT.search(text): a rotating beam, moving light shafts, or a pulsing / flashing light in one sentence."""
    def search(self, text: str):
        return ROTATING_BEAM.search(text) or LIGHT_SHAFTS.search(text) or PULSING_LIGHT.search(text)


MOVING_LIGHT = _AnyOf()


def steady_light(prompt: str, negative: str, moving_light: bool = False) -> tuple[str, str]:
    """LTX long passes (> 10 s) drifted toward warm lamplight on 4/5 runs; with this clause (and the lamp worded as
    "dim, perfectly steady" instead of "glows warm") 361 f and 481 f passes stayed flat
    (research/particle-loop-closure.md section 8). Appending without rewording the prompt's own light sources is
    UNTESTED: word light sources as dim and steady in the scene prompt itself.
    moving_light (an intended sweeping beam; the pipeline sets it from MOVING_LIGHT): the exposure-only clause instead,
    since "lighting stays exactly constant" contradicts the beam (realism amendment §8)."""
    pos = STEADY_EXPOSURE_POS if moving_light else STEADY_LIGHT_POS
    p = prompt if pos in prompt else f"{prompt.rstrip()} {pos}"
    n = negative if STEADY_LIGHT_NEG in negative else ", ".join(x for x in (negative.strip(", "), STEADY_LIGHT_NEG) if x)
    return p, n


SETTLED_STATE_CLAUSE = ("Any steam, smoke, mist, fog, haze or spray is already fully developed and evenly spread, "
                        "exactly as it looks after running for hours; nothing is just starting or building up.")


def settled_keyframe_prompt(prompt: str) -> str:
    """Keyframe (T2I) prompt rule for loopable scenes: show accumulating elements at their steady state. LTX takes
    starting from a thin steam plume kept building it up for the whole 20 s (neon alley, 6 takes, 8-35 grey regional
    drift, clearly visible in review), so the loop could never return to its start (research/particle-loop-closure.md
    section 13). HYPOTHESIS until a settled keyframe gives a stationary take."""
    return prompt if SETTLED_STATE_CLAUSE in prompt else f"{prompt.rstrip()} {SETTLED_STATE_CLAUSE}"


HOLD_POSITION = ("Every person and animal stays exactly where it is with its feet planted, never stepping or walking; "
                 "only clothing, hair and anything loose keeps moving.")


def donor_prompt(prompt: str) -> str:
    """Motion donor rule (ADR 0016): Hunyuan's step-distilled model runs without CFG, so a 'walking' negative does
    nothing and the positive prompt must hold every figure in place -- the director's spice prompt ("advances slowly")
    walked the traveler off in every Hunyuan clip; the stand-still wording held him on every seed
    (research/model-bakeoff-2026-09.md), and a guided LTX take follows whatever the donor does."""
    return prompt if HOLD_POSITION in prompt else f"{prompt.rstrip()} {HOLD_POSITION}"


LOCKED_CAMERA = ("Static locked-off shot on a tripod. The camera does not move at all during the entire shot: no pan, "
                 "no tilt, no zoom, no dolly, no push-in, no handheld shake; the framing stays exactly the same from the "
                 "first frame to the last.")  # rain / waterfall prompts that passed review
# v15 realism amendment (user 2026-09-27): no global "calm and unhurried" -- each phenomenon keeps its own real speed
# (the old clause was on every loop the user passed, so their saved prompts stay the record of that recipe).
PACE = "Filmed in real time at normal speed: not a time-lapse, not sped up, not slow motion."
# Sea/lake scenes. dir_lighthouse2 (no clause, speed 1) looked far too fast and fake in review; lighthouse_lr_s02 (the
# old "slowly and heavily" clause + motion clock 0.2) was judged worse still. Weight and travel instead of slowness
# (HYPOTHESIS, experiments/speed_depth).
WATER_PACE = "The water has real weight: waves travel in toward the shore and break into foam at natural real-time speed."

# Daylight scenes. Naming the sun in MOTION grew one in the brightest sky (dir_pine6, 68 grey), so the sun gets no
# motion clause; the still keeps its sun. Positive wording: the distilled LTX largely ignores negatives.
# Name kept for the call sites (it no longer hides anything).
SUN_HIDDEN = "The daylight is established and the exposure stays steady."

# lens flare / sun rays / sun in frame: a flare pulsing in one corner drifted every pine take 13.8-60 grey (2026-09-26).
# v15: "sweeping light beams" and "changing light" removed (a beam is a supported effect; the contract drops any
# negative naming a required element anyway).
BASE_NEGATIVE = ("time-lapse, timelapse, fast motion, sped up, camera movement, zoom, pan, shaky camera, morphing, "
                 "warping, distortion, text, watermark, frozen image, flickering lamp, strobing, lens flare, sun rays, "
                 "sun in frame")
