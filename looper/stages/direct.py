"""direct stage (spec docs/superpowers/specs/2026-09-25-director-design.md): user prompt [+ image] -> keyframe prompt,
LTX motion prompt, negative. The model supplies FACTS (what the scene contains and how each element moves); the
wording that decided quality in review (locked camera, real-time pacing, settled accumulating elements, no events) is
code in motion_style.py. With an image the user's prompt is the motion prompt word for word: only missing fixed
clauses are added, and unloopable wording becomes a warning (user prompt is authoritative, invariant 11).
Replaces the unwired interpret stage."""
from __future__ import annotations

import json
import re
from pathlib import Path

from looper import models, motion_style

VERSION = 24  # v24: the brief tells the model that people and animals stay put and the wind moves their clothing
#            (spice_handsoff v23: "a hooded traveler approaching ..." in the scene sentence, "cloak dragging behind").
#            v23: a clause dropped for locomotion keeps its clothing parts; "the twin suns ..." counts as a sun clause.
#            v22: a person / figure that travels (walks, advances, crosses ...) is a violation: loops keep subjects put.
#            v21: the sea clause needs an unambiguous water word ("waves" in a robe made a desert a sea scene).
#            v20: fabric may billow (a cloak / flag in the wind is cloth motion, not growth); the ban had dropped the
#            cloak clause from the motion prompt, which the motion-donor route (ADR 0016) also feeds to Hunyuan.
#            v19: rotating machinery turns slowly and is veiled by the dust / steam it churns up (review 2026-09-28:
#            LTX struggles with things that move in circles, so the director should tone them down;
#            research/harvester-drum.md: resolution, single-stage, wording and 4K do not fix it).
#            v18: a pulsing light is worded concretely (flares brighter / dims, how often, what it floods). HYPOTHESIS
#            from one scene: the leviathan's "emitters pulse rhythmically" rendered +-0.65 grey, the concrete wording
#            9.4 grey with the lava lit in step (research/leviathan.md).
#            v17: fixed clause capped at 8 items.
#            v16: dust counts as an accumulating medium; the first proposal's moving clauses are recorded.
#            v15: realism amendment 2026-09-27: no beam / breaking-wave bans, per-phenomenon speed instead of "slow,
#            steady" for everything, a beam may bring a light established medium, daylight keeps its sun (no motion).
#            v14: v14: a one-line prompt-only run renders the still from the user's words verbatim (report §9 P1).
#            v13: an --image run with a multi-line/long brief is directed (composed), not passed through verbatim.
#            v12: lights keep a quick living flicker (lantern); slow real-time water clause for sea scenes.
#            v11: v11: no breaking waves, no sweeping beams, no daylight clause at dusk/night/storm.
#            v10: v10: JSON retry; no settled clause unless asked; sun rule on motion only, sun words out of motion.
#             v9: daylight clause without sun words.
# v8: SUN_HIDDEN clause for daylight, sun-subject clauses dropped. v7: sun out of frame (brief). v6: plural-aware grounding. v5: motion must be grounded in the scene/still; sparkle kept.
# v2: list fields given as one string are split (v1 dropped them); raw reply saved. v3: head-noun
#              contradiction check, "spread" allowed. v4: no invented mist/fog/steam; settled clause only when present

SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["scene", "style", "keyframe_details", "moving", "fixed", "negatives", "adaptations"],
          "properties": {
              "scene": {"type": "string"}, "style": {"type": "string"}, "keyframe_details": {"type": "string"},
              "moving": {"type": "array", "items": {"type": "string"}},
              "fixed": {"type": "array", "items": {"type": "string"}},
              "negatives": {"type": "array", "items": {"type": "string"}},
              "adaptations": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["asked", "changed_to", "why"],
                  "properties": {"asked": {"type": "string"}, "changed_to": {"type": "string"},
                                 "why": {"type": "string"}}}}}}

_BRIEF = """You direct one shot of a cinematic video that will play as a seamless loop for hours: a locked-off
camera and persistent geometry, with believable real-time motion, lighting, materials, scale and atmosphere inside the
scene. Make it visually compelling. Beams, rotating lights, moving machinery, strong emission, reflections and active
natural phenomena are supported creative goals: use them when they serve the scene, describe them as already
established when the shot begins, and never remove, freeze, dim or slow a defining effect to make looping easier. {source}
Respond with ONLY a JSON object with exactly these keys:
- "scene": one sentence naming the place, time of day and weather.
- "style": the visual style in a few words ("Photorealistic, cinematic" unless the prompt asks for another style).
- "keyframe_details": what a single still frame shows -- subjects, materials, colours, light, composition. Appearance
  only: no motion verbs. Accumulating elements (steam, mist, smoke, fog, spray) are already fully developed.
- "moving": 2 to 5 short present-tense clauses, one per moving element, each continuous and ongoing, with its own
  natural real-time speed, amplitude and weight and a direction when it has one (rain falls fast and splashes, surf
  rolls in and breaks into foam, embers rise from the fire, a gear turns at a steady rate, branches sway from
  anchored trunks). Give every light source a clause with its natural life (a candle flickers, a lantern glows and
  breathes, neon hums). A pulsing light (an engine core, an emitter, a beacon) says concretely what happens: its core
  flares much brighter and dims back down, about how often (every one to three seconds), and which nearby surfaces its
  light floods -- a bare "pulses rhythmically" renders as a steady glow. An operating lighthouse or searchlight at dusk, night or in a storm sweeps its beam steadily
  around through the rain / spray / haze, already turning when the shot begins, while its lantern stays lit -- say
  both. State what is stable and what moves; never "everything is still".
- "fixed": solid things that never move or change shape, as short noun phrases. Never an item that is in "moving".
- Rotating machinery (drums, gears, wheels, cogs, fans, propellers, turbines): the video model cannot turn a large,
  sharply detailed rotating part rigidly -- its teeth and spokes smear and drag. Keep it turning, slowly, and veil
  it: dense dust, steam or spray that the part itself churns up swirls thickly around it at the same density
  throughout, half hiding it. Record this in "adaptations".
- Do not invent mist, fog, haze, steam, smoke or spray unless the user's prompt asks for it, a light beam needs a
  medium to be seen, or a rotating part needs its veil; then keep it established and evenly spread (it must not
  build up). Only give motion to
  things you described in "keyframe_details" -- never add a stream, river or animal that is not in the frame.
- Water moves at natural real-time speed with real weight: waves travel in toward the shore or rocks and break into
  foam, continuously (not sliding sideways across the frame as one mass).
- People and animals stay exactly where they are, in the scene sentence too: never let them walk, step, advance,
  approach or cross anything (a looping subject cannot travel). Give the wind's motion to their clothing, hair and
  anything loose instead (a heavy cloak billows and snaps, a hem lifts and falls), and record a travelling subject of
  the prompt in "adaptations".
- Daylight scenes: the daylight is established and the exposure steady; keep the sun where the scene has it, but give
  it no motion clause.
- Continuous sparkle, glinting, twinkling or shimmering light (sun glinting through swaying needles, sparkling water)
  loops well: keep it when the prompt asks for it, as a steady continuous effect.
- "negatives": things that must not appear (e.g. people, cars), short phrases.
- "adaptations": for every part of the prompt that cannot loop -- a one-way change over time (sunrise, a light
  turning on), a single one-off event (one lightning strike), something crossing or leaving the frame, growth (steam
  building up) -- {{"asked": what the prompt asked, "changed_to": the closest ongoing version you used, "why": one
  short reason}}. Keep the effect and make it ongoing; never drop it. Periodic motion (a sweeping beam, a turning
  wheel, breaking waves) loops and is NOT an adaptation.
Never use these words or ideas: billows (except fabric: a cloak, flag or sail billows in the wind), builds up,
thickens, sunrise, sunset, the whole scene gets darker or brighter, lightning, thunder, explosion, turns on, switches
on, pan, zoom, dolly, tracking shot, camera moves."""

_PROMPT_ONLY = "The user's prompt:\n{prompt}"
_WITH_IMAGE = ("The attached image is the first frame. The user's prompt describes how it should move; describe the "
               "image and the prompt together:\n{prompt}")

FABRIC = re.compile(r"\b(cloaks?|capes?|robes?|cloth\w*|fabrics?|flags?|banners?|sails?|curtains?|scarf|scarves|shawls?|"
                    r"dress\w*|skirts?|coats?|tunics?|veils?|tapestr\w*|canop\w*|tents?|garments?|hoods?)\b")
# no "spread": ripples spreading is natural motion (Claude CLI T0 dropped it); steam growth is billow/build up/thicken
BANNED = [(r"\bbillow\w*", "growth"), (r"\bbuild(s|ing)? up\b", "growth"), (r"\bthicken\w*", "growth"),
          (r"\b(sunrise|sunset|gets? (darker|brighter))\b", "change over time"),
          (r"\b(lightning|thunder|explo\w+)\b", "event"), (r"\b(turns?|switch(es)?) on\b", "event"),
          (r"\b(pans?|panning|zooms?|dolly|tracking shot|camera moves?)\b", "camera move")]
# motion clauses only: a clause about the sun itself grew a sun + rays in every pine take (dir_pine5, 55.6 grey); on
# the scene sentence it only cost a retry (final review #4) -- compose() keeps sun words out of the motion prompt
# the sun itself moving grew a sun (dir_pine5/6); sunbeams / rays shifting are intended moving light (amendment §14)
MOTION_ONLY = [(r"^\s*(the\s+)?(\w+\s+)?(suns?|sunlight|sunshine)\b", "sun in frame")]  # v22: + "the twin suns ..."
# v22: a figure that travels cannot loop (model bakeoff review: a person walking away cannot loop; the goal is clothing
# that moves while the person stays put); spice_handsoff's brief ("crosses the desert")
# became "the hooded figure advances ... toward the megastructure" beside the donor's hold-still clause
_PERSON = (r"(figure|person|people|traveler|traveller|man|woman|monk|wanderer|pilgrim|rider|crowd|someone|soldier|nomad|"
           r"hiker|explorer|stranger|child|girl|boy)s?")
_TRAVEL = (r"(walk\w*|advanc\w*|cross(es|ing)?|strid\w*|steps?\b|stepping|march\w*|approach\w*|wander\w*|trek\w*|"
           r"trudg\w*|heads?\s+(toward|towards|to|into|for)\b|moves?\s+(toward|towards|forward|away|across|closer)\b)")
MOTION_ONLY.append((rf"\b{_PERSON}\b[^.;]*?\b{_TRAVEL}",
                    "locomotion: a looping subject stays in place -- give the motion to its clothing or hair"))
# v15 (review 2026-09-27: no ban on beams; scenes should be striking and as realistic as possible):
# the v11 bans on breaking waves and sweeping beams are gone. Their evidence (dir_lighthouse 43.6 / 41.5 grey) is kept in
# research/quality-handoff-2026-09-27.md; a sweeping beam loops as whole turns (research/rotating-beam.md reviews 3-4).
# v21: unambiguous water words only -- "slow waves travel through the heavy robe" (sample_2) put the sea clause into a
# desert; waves / swell also live in cloth, heat and sound, and a real sea scene always names its water
SEA = re.compile(r"\b(sea|ocean|surf|tide|lake|bay|harbou?r|shore|coast\w*)\b", re.I)
_NOT_DAYLIGHT = re.compile(r"\b(dusk|night|nighttime|evening|twilight|storm\w*)\b", re.I)
_SUN_ADJ = re.compile(r"\b(sunlit|sunny|sun-dappled|sun-drenched|sun-kissed)\s+", re.I)
_SUN_NOUN = re.compile(r"\b(sun|sunlight|sunshine|sunbeams?|sunrays?)\b", re.I)
DAYLIGHT = re.compile(r"\b(sun\w*|daylight|midday|noon|morning|afternoon|golden hour|dawn|daytime)\b", re.I)
# the fixed clause names the most prominent solids only: crawler_720 listed 17 and pushed the prompt over the render
# guard (1586 chars); the depth lock holds the geometry, the clause only reminds the model what must not deform
MAX_FIXED = 8
_MIN_WORD = 4  # contradiction check ignores short words ("the", "and")
# accumulating elements: the drift source of every failed take so far (neon steam, waterfall mist, pine mist)
BEAM = motion_style.MOVING_LIGHT
ACCUMULATING = re.compile(r"\b(mist\w*|fog\w*|haz[ey]\w*|steam\w*|smok\w*|spray\w*|vapou?r\w*|dust\w*)\b", re.I)


def clean(facts: dict) -> dict:
    """Normalise model output: missing/odd fields become empty, non-string list items are skipped."""
    def text(v):
        return v.strip() if isinstance(v, str) else ""

    def items(v, sep):
        if isinstance(v, str):  # gemma4:12b returned every list as one string (2026-09-25)
            parts = [s for s in re.split(sep, v) if s.strip()]
            v = parts if len(parts) > 1 else re.split(r",\s*", v)  # one sentence of comma-separated clauses
        return [s.strip().rstrip(".;") for s in v if isinstance(s, str) and s.strip().rstrip(".;")] \
            if isinstance(v, list) else []
    clauses, nouns = r"[.;]\s*", r"[,.;]\s*"  # a motion clause may itself contain commas
    adapt = [a for a in facts.get("adaptations") or [] if isinstance(a, dict)] \
        if isinstance(facts.get("adaptations"), list) else []
    return {"scene": text(facts.get("scene")), "style": text(facts.get("style")) or "Photorealistic, cinematic",
            "keyframe_details": text(facts.get("keyframe_details")), "moving": items(facts.get("moving"), clauses),
            "fixed": items(facts.get("fixed"), nouns), "negatives": items(facts.get("negatives"), nouns),
            "adaptations": [{k: text(a.get(k)) for k in ("asked", "changed_to", "why")} for a in adapt]}


def _banned(text: str, motion: bool = False) -> list[tuple[str, str]]:
    rules = BANNED + MOTION_ONLY if motion else BANNED
    low = text.lower()
    hits = [(m, why) for pat, why in rules for m in [re.search(pat, low)] if m]
    fabric = FABRIC.search(low)  # v20: a cloak / flag billowing is cloth motion, not growth -- when the fabric is the
    # subject (named before the verb): "smoke billows past the flag" is still growth
    return [(m.group(0), why) for m, why in hits
            if not (m.group(0).startswith("billow") and fabric and fabric.start() < m.start())]


def _contradicts(fixed_item: str, moving: list[str]) -> bool:
    """The fixed item's head noun (its last word) also moves. Any shared word was too eager: "Stone lighthouse tower"
    lost its clause because the beam clause says "lighthouse" (Claude CLI T0, 2026-09-25)."""
    words = set(re.findall(r"[a-z]+", " ".join(moving).lower()))
    head = (re.findall(r"[a-z]+", fixed_item.lower()) or [""])[-1]
    return len(head) >= _MIN_WORD and head in words


def check(facts: dict) -> list[str]:
    f = clean(facts)
    out = [f"'{word}' ({why}) in: {t}" for t in [f["scene"], f["keyframe_details"]] for word, why in _banned(t)]
    out += [f"'{word}' ({why}) in: {t}" for t in f["moving"] for word, why in _banned(t, motion=True)]
    out += [f"'{x}' is both moving and fixed" for x in f["fixed"] if _contradicts(x, f["moving"])]
    return out


def _salvage(clause: str) -> list[str]:
    """v22: a clause dropped only for locomotion often carries the cloth motion the donor route needs ("the hooded
    figure advances ..., their heavy cloak snapping and billowing back into the wind"): keep its clothing parts."""
    hits = _banned(clause, motion=True)
    if not hits or any(not why.startswith("locomotion") for _, why in hits):
        return []
    return [p.strip() for p in re.split(r",\s*|;\s*|\s+(?:while|as)\s+", clause)
            if FABRIC.search(p) and not _banned(p, motion=True)]


def drop_violations(facts: dict) -> tuple[dict, list[str]]:
    f = clean(facts)
    dropped = [f"moving: {m}" for m in f["moving"] if _banned(m, motion=True)]
    moving = [x for m in f["moving"] for x in ([m] if not _banned(m, motion=True) else _salvage(m))]
    dropped += [f"fixed: {x}" for x in f["fixed"] if _contradicts(x, moving)]
    return {**f, "moving": moving, "fixed": [x for x in f["fixed"] if not _contradicts(x, moving)]}, dropped


_NOT_SUBJECTS = set("""with from over into onto through across along toward towards left right gently gentle slowly
slow steadily steady softly soft continuously continuous clear smooth slight slightly very barely small faint fine
outer inner their they that this each every while under above below around downward upward down upstream downstream
evenly even constant constantly calm quietly still""".split())


def _stem(w: str) -> str:
    """Crude singular: branches -> branch, bushes -> bush, glasses -> glass, needles -> needle (rstrip("s") made
    "branche" and dropped "Branch tips sway", dir_pine3)."""
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def _content(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= _MIN_WORD and w not in _NOT_SUBJECTS}


def ground(facts: dict, prompt: str = "") -> tuple[dict, list[str]]:
    """Drop motion for things neither the user's prompt nor the scene / still shows (dir_pine2: a river "flows"
    through a dry pine forest -- the video model then invents water, or nothing). Keeps all if none would be left."""
    f = clean(facts)
    seen = _content(prompt + " " + f["scene"] + " " + f["keyframe_details"])
    keep = [m for m in f["moving"] if _content(m) & seen]
    if not keep:
        return f, []
    return {**f, "moving": keep}, [f"moving (not in the scene or still): {m}" for m in f["moving"] if m not in keep]


def _join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _sentence(s: str) -> str:
    s = s.strip().rstrip(".;")
    return s[:1].upper() + s[1:] + "." if s else ""


def _negative(f: dict) -> str:
    return ", ".join([motion_style.BASE_NEGATIVE, *f["negatives"]])


def compose(facts: dict, settled: bool | None = None) -> dict:
    """settled None = from the facts; run() passes False when the user never asked for mist/steam (final review #3)."""
    f = clean(facts)
    # the settled-state clause names steam/mist/fog...; appended to a scene without them it invites them (dir_pine)
    if settled is None:
        settled = any(ACCUMULATING.search(t) for t in [f["scene"], f["keyframe_details"], *f["moving"]])
    look = f["scene"] + " " + f["keyframe_details"]
    daylight = bool(DAYLIGHT.search(look)) and not _NOT_DAYLIGHT.search(look)  # "late afternoon storm at dusk"
    scene_m = _SUN_ADJ.sub("", f["scene"]) if daylight else f["scene"]
    if _SUN_NOUN.search(scene_m):  # "Sunlight filters through ..." cannot be de-sunned: the still carries the look
        scene_m = ""
    parts = [motion_style.LOCKED_CAMERA, _sentence(scene_m)]
    if f["moving"]:
        parts.append(_sentence("; ".join(m.rstrip(".;") for m in f["moving"])))
    if SEA.search(" ".join([f["scene"], f["keyframe_details"], *f["moving"]])):
        parts.append(motion_style.WATER_PACE)
    if daylight:
        parts.append(motion_style.SUN_HIDDEN)
    if f["fixed"]:
        parts.append(f"There is no movement and no change of shape in {_join(f['fixed'][:MAX_FIXED])}.")
    parts.append(f"{motion_style.PACE} {_sentence(f['style'])}")
    keyframe = " ".join(x for x in (_sentence(f["scene"]), _sentence(f["keyframe_details"]), _sentence(f["style"])) if x)
    if settled:
        keyframe = motion_style.settled_keyframe_prompt(keyframe)
    return {"keyframe_prompt": keyframe, "motion_prompt": " ".join(p for p in parts if p), "negative": _negative(f)}


def is_brief(prompt: str) -> bool:
    """A written brief (several lines or paragraphs) rather than a one-line render prompt."""
    p = prompt.strip()
    return "\n" in p or len(p) > 600


def complete_user_prompt(prompt: str, facts: dict) -> dict:
    """Image path: the user's words stay as written; add only the clauses they left out."""
    f, low = clean(facts), prompt.lower()
    parts = [] if any(k in low for k in ("locked-off", "tripod", "static camera")) else [motion_style.LOCKED_CAMERA]
    parts.append(prompt.strip())
    fixed = [x for x in f["fixed"] if not _contradicts(x, f["moving"])]
    if fixed and not any(k in low for k in ("change shape", "completely still", "stay still")):
        parts.append(f"There is no movement and no change of shape in {_join(fixed[:MAX_FIXED])}.")
    if "time-lapse" not in low and "real time" not in low:
        parts.append(motion_style.PACE)
    return {"keyframe_prompt": prompt.strip(), "motion_prompt": " ".join(parts), "negative": _negative(f)}


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """inputs: {} or {"image"}; config: {prompt, provider, model, think}"""
    prompt, image = config["prompt"], inputs.get("image")
    brief = _BRIEF.format(source=(_WITH_IMAGE if image else _PROMPT_ONLY).format(prompt=prompt))
    # think: local models only follow the loop rules when they reason first (qwen3.6 hard prompts 1/5 -> ~4/5,
    # research/director.md); 2-4 min per call, so the timeout is generous
    call = dict(provider=config.get("provider", "ollama"), model=config["model"], schema=SCHEMA, unload=True,
                images=[Path(image)] if image else None, timeout_s=900, think=bool(config.get("think")))
    def ask(text):  # spec: invalid JSON twice -> the stage fails (once was fatal; thinking replies carry prose)
        try:
            return models.complete_json("direct", text, **call)
        except models.ModelError:
            return models.complete_json("direct", text, **call)

    raw, meta = ask(brief)
    proposed = clean(raw)["moving"]  # the selected design before any retry: the contract keeps its defining effects
    warnings, dropped = [], []
    # A structured brief (multi-line / long) is not a render prompt: verbatim, LTX got 5.8k chars of markdown incl.
    # "No neon, holograms, people, vehicles" (naming summons) and growth words (dir_furnace). Direct it like a
    # prompt-only run; the original stays in direction.json beside the result (invariant 11).
    if image and not is_brief(prompt):
        facts = clean(raw)
        out = complete_user_prompt(prompt, facts)
        warnings = [f"your prompt: '{w}' ({why}) may not loop well" for w, why in _banned(prompt)]
        warnings += [f"'{a['asked']}' may not loop: {a['why']}" for a in facts["adaptations"]]
    else:
        violations = check(raw)
        if violations:
            retry = brief + "\n\nYour previous answer broke these rules; fix them:\n- " + "\n- ".join(violations)
            raw, meta = ask(retry)
        facts, dropped = drop_violations(raw)
        if not ACCUMULATING.search(prompt):  # never add a drifting element the user did not ask for (dir_pine) --
            # except the medium a sweeping beam is seen through (v15): the beam clause names it, the beam is the point
            gone = [m for m in facts["moving"] if ACCUMULATING.search(m) and not BEAM.search(m)]
            dropped += [f"moving (not in the prompt, accumulates): {m}" for m in gone]
            facts = {**facts, "moving": [m for m in facts["moving"] if m not in gone]}
        facts, ungrounded = ground(facts, prompt)
        dropped += ungrounded
        if not facts["scene"]:
            raise RuntimeError(f"direct: model returned no scene sentence: {raw}")
        asked = bool(ACCUMULATING.search(prompt))
        out = compose(facts, settled=True if asked else False)
        if not is_brief(prompt):  # v14: the still renders the user's own words (blind stills: the rewrite lost the
            # waterfall twice, the user's words won 2 of 3); the director's version is kept for traceability
            out["director_keyframe_prompt"] = out["keyframe_prompt"]
            kf = prompt.strip()
            out["keyframe_prompt"] = motion_style.settled_keyframe_prompt(kf) if asked else kf
        warnings = check(facts)  # banned words left in scene/keyframe_details (not droppable)
        if not asked:  # final review #3: the still's description can still carry an invented accumulating element
            warnings += [f"the still description adds '{m.group(0)}' (not in your prompt; it may build up)"
                         for t in (facts["scene"], facts["keyframe_details"]) for m in [ACCUMULATING.search(t)] if m]
    record = {"original_prompt": prompt, "image": str(image) if image else None, **out, "raw": raw, "facts": facts,
              "adaptations": facts["adaptations"], "dropped": dropped, "warnings": warnings, "model_call": meta,
              "proposed_moving": proposed}
    (out_dir / "direction.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    for key in ("keyframe_prompt", "motion_prompt", "negative"):
        (out_dir / f"{key}.txt").write_text(out[key], encoding="utf-8")
    return {**out, "adaptations": facts["adaptations"], "dropped": dropped, "warnings": warnings, "facts": facts,
            "model_meta": meta, "proposed_moving": proposed}
