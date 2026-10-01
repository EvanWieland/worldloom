"""Scene contract (handoff 2026-09-27 §6 + realism amendment): the scene's requirements, persisted per run and checked
against the plan (effective motion prompt + negative) before any GPU time. Requirements come from the user's words
(origin "user") and from the director's selected design (origin "director_selected": a sweeping beam or turning
machinery the director chose becomes a requirement of that design). A required element the plan left out is put back
as one plain clause; a negative that names it is removed; an element still missing makes the run best-effort.
Beams and machinery are rendered, but their route is marked UNVERIFIED until a human passes the result.

Deterministic word rules, not semantics: they catch omission of a named element and a negative that names it; they
cannot prove the effective prompt means what the user meant. The audition/review packet shows original and effective
prompt side by side for that (§6.2). Every requirement stays `needs_review` until a human judges the rendered clip.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = 3  # v3: exclusions; v2: director_selected requirements, effect fields, route proven / unverified
VERSION = 8  # stage version (part of the fingerprint); v8: an adverb may stand between the verb and where it goes ("streams steadily through"). v7: an adverb before wave / stream / cascade makes it a verb. v6: a verb "stream / wave / cascade + where" is not water
# (sample_1); v5: collective "X of ..." is not water / sky (spice_desert);
# v4: machine_rotation framing = veiled, not "large and clearly
# visible" (director v19). v3: negation-aware (a user's "avoid neon" is an exclusion,
#              not a requirement); v2: realism amendment (beams are requirements, not gaps)

LIGHT = re.compile(r"\b(light(?!house)\w*|glow\w*|lit|flame\w*|flicker\w*|burn\w*|shin\w*|emit\w*|hum\w*|shimmer\w*|"
                   r"breath\w*|pulse\w*|illuminat\w*|bright\w*|beams?)\b", re.I)
TURN = re.compile(r"\b(rotat\w*|sweep\w*|revolv\w*|spin\w*|turn\w*|circl\w*)\b", re.I)

# a figure of speech, not water / sky: "streams of X", "streams and clouds of X", "spice streams", "dust clouds"
_MATERIALS = ("dust", "sand", "spice", "smoke", "steam", "ash", "spark", "ember", "slag", "lava", "particle", "debris")
OF = r"(?!\s+of\b)(?!\s+(?:and|or)\s+\w+\s+of\b)"
NOT_MATERIAL = "".join(rf"(?<!{w}\s)(?<!{w}s\s)" for w in _MATERIALS)
# a noun that is also a motion verb, followed by where it goes, is the verb ("stream through", "waves in the wind")
# (an adverb may stand between: "moonlight streams steadily through the windows", gcr_fire 2026-10-01)
VERB_USE = (r"(?!(?:\s+\w+ly)?\s+(?:through|across|past|around|over|into|in|out|down|up|along|from|towards?|off|away|"
            r"between|behind)\b)")

# (id, element noun pattern, family, description, extra condition on the user's prompt)
# family decides the route: emission / flow / atmosphere = the proven full-frame recipe; periodic_illumination and
# rigid_periodic = the same full-frame recipe, unverified (research/rotating-beam.md).
RULES = [
    ("lantern_emission", r"lighthouses?|lanterns?|beacons?", "emission",
     "The lighthouse lantern / lantern stays visibly lit throughout.", None),
    ("lamp_emission", r"lamps?|streetlights?|street lights?|lamp ?posts?|work ?lights?|floodlights?|spotlights?|"
                      r"headlights?", "emission",
     "The lamps stay visibly lit throughout.", None),
    ("candle_emission", r"candles?|candlelight", "emission", "The candle flames stay lit throughout.", None),
    ("fire_emission", r"fires?|fireplaces?|campfires?|bonfires?|hearths?|furnaces?|forges?|flames?|embers?", "emission",
     "The fire keeps burning visibly throughout.", None),
    ("neon_emission", r"neon", "emission", "The neon signs stay lit throughout.", None),
    # "a stream of glowing slag" (crawler 2026-09-27), "streams and clouds of spice", "waves of airborne material",
    # "a sea of dunes" (spice_desert 2026-09-28) are not water / sky: a collective "X of ..." is a figure of speech;
    # nor is the verb: "particles ... stream through the air" (sample_1 2026-09-30), "a banner waves in the wind"
    # an adverb before it makes it a verb too: "heat distortion subtly waves and shimmers" (spice_handsoff 2026-10-01)
    ("water_motion", rf"{NOT_MATERIAL}(?:sea|ocean|surf|swell|tide|river|creek|brook|waterfalls?|rapids|"
                     rf"(?<!ly\s)(?:waves?|streams?|cascades?){VERB_USE}){OF}",
     "flow", "The water visibly moves (propagates, flows) at believable real-time speed.", None),
    ("rain_motion", r"rain\w*|drizzle|downpour", "atmosphere", "Rain keeps falling throughout.", None),
    ("snow_motion", r"snow\w*|snowfall|blizzard", "atmosphere", "Snow keeps falling throughout.", None),
    ("smoke_motion", r"smoke|steam|mist|fog|haze|spray|dust", "atmosphere",
     "The smoke / steam / mist / dust keeps moving throughout at a steady density.", None),
    ("cloud_motion", rf"{NOT_MATERIAL}clouds?{OF}", "flow", "The clouds visibly drift.", r"\b(drift\w*|mov\w*|roll\w*|scud\w*|pass\w*)\b"),
    ("beam_rotation", r"beams?|beacons?|lights?", "periodic_illumination",
     "The light beam visibly sweeps / rotates.", TURN.pattern),
    ("machine_rotation", r"gears?|wheels?|windmills?|water ?wheels?|fans?|propellers?|cogs?|carousels?|drums?",
     "rigid_periodic", "The machinery visibly turns with rigid, steady rotation.", TURN.pattern),
    ("light_shafts", r"shafts?|god ?rays|sunbeams?|rays", "moving_illumination",
     "The light shafts keep shifting with the clouds / dust (coherent changing illumination).",
     r"\b(mov\w*|shift\w*|drift\w*|pass\w*|sweep\w*|slid\w*|travel\w*|wander\w*)\b"),
]
PROVEN = {"emission", "flow", "atmosphere"}  # families with loops the user passed
# rotating machinery anywhere in a prompt: loop_qc keeps its strict lull gate (a stalled drum is obvious to the eye)
MACHINERY = re.compile(rf"\b({next(r[1] for r in RULES if r[0] == 'machine_rotation')})\b", re.I)
# Realism amendment 2026-09-27: beams and machinery are supported creative goals, rendered full-frame; their route is
# UNVERIFIED (not a gap): only a human review of the take and the closure can pass them.
UNVERIFIED = {"periodic_illumination": "unguided full-frame beam: looked real in review 1 but its speed wanders "
                                       "(research/rotating-beam.md v7a); the closure must keep direction and phase",
              "rigid_periodic": "turning parts re-synthesise instead of rotating rigidly; the director veils them in "
                                "churned dust / steam (v19, research/harvester-drum.md)",
              "moving_illumination": "no passed loop with moving light shafts yet; the whole-frame tone target is "
                                     "off for such runs (it would flatten them)"}
REPAIR_CLAUSE = {"emission": "The {w} stay{s} lit throughout with a living glow.",
                 "flow": "The {w} keep{s} moving naturally at real-time speed.",
                 "atmosphere": "The {w} keep{s} moving steadily throughout.",
                 "periodic_illumination": "The {w} keep{s} sweeping steadily around through the air, already turning "
                                          "when the shot begins, and its source stays lit.",
                 "rigid_periodic": "The {w} keep{s} turning rigidly at a steady rate in one direction.",
                 "moving_illumination": "The {w} of light keep shifting slowly as the clouds and dust pass."}
EFFECT = {  # amendment §6: what a defining periodic effect must keep; substitutions a retry may never make
    "periodic_illumination": {
        "source": "the beam's light source", "phenomenon": "rotating light scattered by the air / rain / spray / dust",
        "initial_state": "already_operating",
        "motion": {"direction": "consistent", "period_seconds": None,
                   "period_origin": "model_chosen (unguided route); measured after the take, loop cut to whole turns"},
        "expected_relationships": ["beam anchored to the lantern", "visibility varies with direction and medium",
                                   "opaque geometry occludes the beam", "surfaces brighten where the beam passes"],
        "forbidden_substitutions": ["static_glow_instead_of_rotation", "beam_removed",
                                    "whole_frame_brightness_pulse_instead_of_sweep"]},
    "rigid_periodic": {
        "initial_state": "already_operating", "motion": {"direction": "consistent", "period_seconds": None,
                                                         "period_origin": "model_chosen"},
        "expected_relationships": ["shape, spokes and teeth persist", "constant direction and rate"],
        "forbidden_substitutions": ["frozen_machine", "reversal", "re-synthesised_spokes"]},
    "moving_illumination": {
        "initial_state": "already_operating",
        "expected_relationships": ["shafts start at a plausible source (sun, gap in clouds, lamp)",
                                   "brightness follows the shafts across surfaces"],
        "forbidden_substitutions": ["light variation normalised away", "static shafts"]}}
DEFINING = ("beam_rotation", "machine_rotation", "water_motion", "light_shafts")  # director-selectable; then kept
# Realism amendment §5: a prompt-originated still must give a defining effect room to read (the lighthouse sea was a
# ~35 px strip at 1280x704 and never looked like surf). Appended to the KEYFRAME prompt of prompt-only runs only; a
# user's own image is never recomposed.
FRAMING = {"water_motion": "The sea fills the lower part of the frame, close enough to see individual waves break "
                           "into foam.",
           "beam_rotation": "Open sky or air around the light source leaves room for its beam.",
           "machine_rotation": "The turning mechanism is partly veiled by the dust or steam it churns up."}  # director v19


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;!?])\s+", text) if s.strip()]


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]




def _requirement(rid: str, noun: str, family: str, desc: str, hits: list, origin: str) -> dict:
    return {"id": rid, "origin": origin, "evidence": sorted(set(h.lower() for h in hits)), "required": True,
            "description": desc, "motion_family": family, "noun": noun,
            "validation": "human_with_image_measurements" if family in ("emission", "periodic_illumination")
            else "human_with_motion_diagnostics", "status": "needs_review", **EFFECT.get(family, {})}


# an exclusion runs from its negation word to the end of the clause: "Avoid ... weapons, neon, ...", "No human crew",
# "with no startup effects" (crawler brief 2026-09-27: "Avoid ... neon" became a neon REQUIREMENT, its negative was
# removed and "The neon stays lit" added -- the user's exclusion inverted)
NEGATION = re.compile(r"\b(avoid\w*|no|without|never|not|nor|exclud\w*)\b[^.;:]*", re.I)


def _positive(s: str) -> str:
    """The sentence minus its excluded spans (also drops "There is no movement ... in X")."""
    return NEGATION.sub(" ", s)


def _hits(text: str, noun: str, cond: str | None) -> list[str]:
    out = []
    for s in _sentences(text):
        s = _positive(s)
        m = re.search(rf"\b({noun})\b", s, re.I)
        if m and (cond is None or re.search(cond, s, re.I)):
            out.append(m.group(0))
    return out


def _excluded(prompt: str) -> list[dict]:
    """Rule elements the user named only inside an exclusion span."""
    spans = " ".join(m.group(0) for m in NEGATION.finditer(prompt))
    out = []
    for rid, noun, *_ in RULES:
        m = re.search(rf"\b({noun})\b", spans, re.I)
        if m and not _hits(prompt, noun, None):
            out.append({"id": rid, "noun": noun, "evidence": m.group(0).lower()})
    return out


def derive(prompt: str, image_sha: str | None = None, selected_plan: str = "") -> dict:
    """User prompt [+ image hash] [+ the director's selected motion plan] -> contract. The user's words give "user"
    requirements; a defining effect (beam sweep, turning machinery) in the director's selected plan becomes a
    "director_selected" requirement of that design, so no later rewrite or retry can quietly drop it."""
    reqs = []
    for rid, noun, family, desc, cond in RULES:
        hits = _hits(prompt, noun, cond)
        if rid == "beam_rotation" and not re.search(r"\b(beams?|beacons?|lighthouse\w*|searchlights?)\b", prompt, re.I):
            hits = []  # "lights turn on" is an event word, not a rotating beam
        if hits:
            reqs.append(_requirement(rid, noun, family, desc, hits, "user"))
        elif rid in DEFINING and selected_plan:
            sel = _hits(selected_plan, r"beams?|beacons?|searchlights?" if rid == "beam_rotation" else noun, cond)
            if sel:
                reqs.append(_requirement(rid, noun, family, desc, sel, "director_selected"))
    return {"schema_version": SCHEMA_VERSION, "source": {"prompt": prompt, "prompt_sha": _hash(prompt), "image_sha": image_sha},
            "camera": {"mode": "locked"}, "composition": {"preserve_source": image_sha is not None},
            "requirements": reqs, "exclusions": _excluded(prompt),
            "allowed_variation": ["exact wave / flame / particle shapes", "wording of the effective prompt",
                                  "a beam dimming or hiding when it points away"],
            "forbidden_substitutions": ["dropping a required element", "a negative that names a required element",
                                        "freezing, dimming or globally slowing a defining effect"]}


def _mapped(req: dict, motion_prompt: str) -> bool:
    """A sentence of the plan names the element and (emission) gives it light / (periodic) gives it a turn."""
    for s in _sentences(motion_prompt):
        s = _positive(s)
        if not re.search(rf"\b({req['noun']})\b", s, re.I):
            continue
        if req["motion_family"] == "emission" and not (LIGHT.search(s) or req["id"] in ("fire_emission", "neon_emission")):
            continue
        if req["motion_family"] in ("periodic_illumination", "rigid_periodic") and not TURN.search(s):
            continue  # a static glow is not a sweeping beam (forbidden substitution)
        return True
    return False


def check(contract: dict, plan: dict) -> dict:
    """plan: {motion_prompt, negative}. Per required item: mapped / forbidden negative phrases / route."""
    items = []
    negs = [n.strip() for n in plan.get("negative", "").split(",") if n.strip()]
    for r in contract["requirements"]:
        if not r["required"]:
            continue
        forbidden = [n for n in negs if re.search(rf"\b({r['noun']})\b", n, re.I)
                     and (r["motion_family"] != "periodic_illumination" or TURN.search(n))]
        items.append({"id": r["id"], "mapped": _mapped(r, plan["motion_prompt"]), "forbidden_negatives": forbidden,
                      "route": "proven" if r["motion_family"] in PROVEN else "unverified",
                      "route_note": UNVERIFIED.get(r["motion_family"])})
    excluded = [s for s in _sentences(plan["motion_prompt"]) for x in contract.get("exclusions", [])
                if re.search(rf"\b({x['noun']})\b", _positive(s), re.I)]
    return {"items": items, "excluded_in_plan": excluded,
            "ok": all(i["mapped"] and not i["forbidden_negatives"] for i in items) and not excluded}


def enforce(contract: dict, plan: dict) -> tuple[dict, dict, list[str]]:
    """-> (plan, check result, repairs). Removes negatives that name a required element; puts back an omitted element
    as one plain clause (a static glow where a sweep was required gets the sweep clause)."""
    first = check(contract, plan)
    repairs, plan = [], dict(plan)
    bad = {n for i in first["items"] for n in i["forbidden_negatives"]}
    if bad:
        plan["negative"] = ", ".join(n.strip() for n in plan["negative"].split(",") if n.strip() and n.strip() not in bad)
        repairs += [f"negative removed (names a required element): {n}" for n in sorted(bad)]
    for s in dict.fromkeys(first["excluded_in_plan"]):  # the user excluded it: the director may not bring it back
        plan["motion_prompt"] = " ".join(plan["motion_prompt"].replace(s, " ").split())
        repairs.append(f"removed (you excluded it): {s}")
    by_id = {r["id"]: r for r in contract["requirements"]}
    for i in first["items"]:
        r = by_id[i["id"]]
        if not i["mapped"]:
            w = _element_word(r)
            plural = w.endswith("s") and not w.endswith("ss")
            clause = REPAIR_CLAUSE[r["motion_family"]].format(w=w, s="" if plural else "s")
            plan["motion_prompt"] = _insert(plan["motion_prompt"], clause)
            repairs.append(f"added (required, missing from the plan): {clause}")
    return plan, check(contract, plan), repairs


def _element_word(r: dict) -> str:
    ev = r["evidence"][0]
    return {"lighthouse": "lighthouse lantern", "lighthouses": "lighthouse lantern"}.get(ev, ev)


def _insert(motion_prompt: str, clause: str) -> str:
    """Before the fixed-things / pace sentences when present, so the clause reads with the other motion."""
    for anchor in ("There is no movement", "Filmed in real time", "Calm and unhurried"):
        k = motion_prompt.find(anchor)
        if k > 0:
            return f"{motion_prompt[:k]}{clause} {motion_prompt[k:]}"
    return f"{motion_prompt.rstrip()} {clause}"


def status(result: dict) -> str:
    """ok | missing (a required element is not in the plan: the run can at best be best_effort)."""
    return "ok" if result["ok"] else "missing"


def checklist(contract: dict, result: dict) -> list[str]:
    """Review lines: one per required element."""
    by_id = {i["id"]: i for i in result["items"]}
    out = []
    for r in contract["requirements"]:
        i = by_id.get(r["id"], {})
        state = ("in the plan; UNVERIFIED route: " + i["route_note"]) if i.get("mapped") and i.get("route") == "unverified" \
            else "in the plan" if i.get("mapped") else "MISSING from the plan"
        who = "from your words" if r["origin"] == "user" else "director's design"
        out.append(f"- [ ] {r['description']} ({r['id']}, {who}: {', '.join(r['evidence'])}) -- {state}")
    out += [f"- [ ] NOT in the scene (you excluded it): {x['evidence']}" for x in contract.get("exclusions", [])]
    return out


ROUTE = "LTX-2.5 distilled full-frame take (depth-locked camera) + two-sided generated closure (ADR 0007)"
CONTROLS = {"periodic_illumination": ["exposure-only steady clause", "raw generated frames (no whole-frame tone target)",
                                      "take_qc means over 5 s"],
            "moving_illumination": ["exposure-only steady clause", "raw generated frames (no whole-frame tone target)",
                                    "take_qc means over 5 s"]}
EVALUATION = {"emission": ["review: brightest light, loop min / take mean", "human"],
              "flow": ["review: moving-region motion, loop / take", "human at real speed"],
              "atmosphere": ["review: moving-region motion, loop / take", "human"],
              "periodic_illumination": ["review: beam phase track through every join (direction, speed, jumps)",
                                        "human: a whole sweep incl. the closure"],
              "rigid_periodic": ["human (no rigid-rotation metric yet)"],
              "moving_illumination": ["human (no shaft metric yet)"]}


def technical_plan(contract: dict) -> list[dict]:
    """Amendment §5 technical pass: for each requirement, the route that renders it, the controls applied, and the
    evidence that will judge it. A failed route changes route or parameters, never the requirement."""
    return [{"id": r["id"], "route": ROUTE, "controls": CONTROLS.get(r["motion_family"], []),
             "evaluation": EVALUATION.get(r["motion_family"], ["human"]),
             "status": "proven" if r["motion_family"] in PROVEN else "unverified"} for r in contract["requirements"]]


def run(inputs: dict, config: dict, out_dir: Path) -> dict:
    """contract stage (CPU). inputs: {} or {"image"}; config: {prompt, plan: {motion_prompt, negative}}"""
    from looper.engine import hash_file
    image_sha = hash_file(Path(inputs["image"])) if inputs.get("image") else None
    contract = derive(config["prompt"], image_sha,
                      selected_plan=f"{config.get('selected', '')}. {config['plan']['motion_prompt']}")
    plan, result, repairs = enforce(contract, config["plan"])
    st = status(result)
    warnings = [f"contract: {x}" for x in repairs]
    warnings += [f"contract: '{i['id']}' is still missing from the plan -- best effort at most"
                 for i in result["items"] if not i["mapped"]]
    record = {"contract": contract, "check": result, "status": st, "repairs": repairs,
              "original_plan": config["plan"], "effective_plan": plan}
    (Path(out_dir) / "contract.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    framing = [FRAMING[r["id"]] for r in contract["requirements"] if r["id"] in FRAMING]
    record["framing"] = framing
    record["technical_plan"] = technical_plan(contract)
    (Path(out_dir) / "contract.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"output": str(Path(out_dir) / "contract.json"), "plan": plan, "status": st, "repairs": repairs,
            "warnings": warnings, "checklist": checklist(contract, result), "contract_sha": _hash(contract),
            "framing": framing}
