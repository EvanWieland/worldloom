"""direct stage: checker, composition, image-path pass-through, run() with a faked model. No GPU/LLM."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import motion_style
from looper.stages import direct

FACTS = {"scene": "A tropical waterfall at midday.", "style": "Photorealistic, cinematic",
         "keyframe_details": "tall white waterfall into a jade pool, ferns, mossy rocks, soft haze",
         "moving": ["the water falls steadily into the pool", "fine mist drifts slowly to the left",
                    "the ferns barely move"],
         "fixed": ["the rocks", "the ferns", "the cliff face"], "negatives": ["people"],
         "adaptations": [{"asked": "sunrise", "changed_to": "steady midday light", "why": "light change cannot loop"}]}
ROOT = Path(__file__).resolve().parent.parent


class TestCheck(unittest.TestCase):
    def test_clean_facts_pass_except_the_contradiction(self):
        self.assertEqual(direct.check(FACTS), ["'the ferns' is both moving and fixed"])

    def test_fabric_may_billow_smoke_may_not(self):
        """v20: 'billow' was banned as growth (steam builds up); a cloak or flag billowing in the wind is the motion the
        motion-donor route exists for (ADR 0016) -- dropping it removed the cloth clause from both models' prompts."""
        for ok in ("the traveler's heavy cloak billows and rolls in the wind", "a flag billows on its pole",
                   "the robe and cape billow sideways in the gusts"):
            self.assertEqual(direct._banned(ok, motion=True), [], ok)
        for bad in ("steam billows from the vent", "dust billows up around the crawler", "smoke billows skyward"):
            self.assertTrue(direct._banned(bad, motion=True), bad)

    def test_a_looping_subject_does_not_travel(self):
        """v22 (spice_handsoff 2026-10-01: the brief's traveler "crosses the desert" became "The hooded figure advances
        ... toward the megastructure" next to the donor's hold-still clause; model bakeoff review: a person walking
        away cannot loop, the goal is clothing that moves while the person stays put)."""
        for bad in ("The hooded figure advances at a barely perceptible speed toward the megastructure",
                    "a lone traveler walks slowly across the dunes", "the monk crosses the courtyard",
                    "the person heads toward the gate", "a pilgrim strides into the wind"):
            self.assertTrue(any(why.startswith("locomotion") for _, why in direct._banned(bad, motion=True)), bad)
        for ok in ("Fine sand skims across the dune surfaces", "waves advance toward the shore",
                   "the traveler's cloak billows while the figure stands still", "dust drifts toward the camera"):
            self.assertFalse(any(why.startswith("locomotion") for _, why in direct._banned(ok, motion=True)), ok)

    def test_a_travel_clause_keeps_its_cloth_motion(self):
        """spice_handsoff (v22): the retry still wrote "advances" and the whole clause was dropped -- with it the cloak
        motion the donor route exists for. The clothing part of a locomotion-only violation survives."""
        f = {**FACTS, "moving": ["The hooded figure advances with a very slow, repeating gait that keeps them anchored "
                                 "in place, their heavy cloak snapping and billowing rhythmically back into the wind",
                                 "dust drifts past"], "fixed": []}
        cleaned, dropped = direct.drop_violations(f)
        self.assertIn("their heavy cloak snapping and billowing rhythmically back into the wind", cleaned["moving"])
        self.assertIn("dust drifts past", cleaned["moving"])
        self.assertFalse(any("advances" in m for m in cleaned["moving"]))

    def test_the_brief_keeps_subjects_in_place(self):
        """v24: the model kept writing the brief's traveler as advancing / approaching (the motion-clause rule caught
        it, the scene sentence slipped through); the instruction itself must say so."""
        self.assertIn("People and animals stay exactly where they are", direct._BRIEF)
        self.assertIn("cloak billows", direct._BRIEF)

    def test_a_named_sun_is_kept_out_of_motion(self):
        """spice_handsoff: "The twin suns emit a steady, diffused glow ..." passed the "the sun ..." rule."""
        for bad in ("The twin suns emit a steady, diffused glow", "the two suns shine diffusely", "the setting sun glows"):
            self.assertTrue(any(why == "sun in frame" for _, why in direct._banned(bad, motion=True)), bad)
        self.assertFalse(direct._banned("the sunlit dunes stay still while sand streams", motion=True))

    def test_banned_growth_event_and_camera_words(self):
        f = {**FACTS, "moving": ["steam billows from the vent", "lightning flashes", "the camera pans left"], "fixed": []}
        v = direct.check(f)
        self.assertEqual(len(v), 3)
        self.assertTrue(any("growth" in x for x in v) and any("event" in x for x in v) and any("camera" in x for x in v))

    def test_drop_violations_removes_bad_clauses_and_contradictions(self):
        f = {**FACTS, "moving": FACTS["moving"] + ["steam builds up"]}
        cleaned, dropped = direct.drop_violations(f)
        self.assertNotIn("steam builds up", cleaned["moving"])
        self.assertNotIn("the ferns", cleaned["fixed"])
        self.assertEqual(len(dropped), 2)
        self.assertEqual(direct.check(cleaned), [])

    def test_contradiction_uses_the_fixed_items_head_noun(self):
        # Claude CLI T0 (2026-09-25): "Stone lighthouse tower" was dropped because "lighthouse" is in the beam clause
        # (a sweeping beam is banned since dir_lighthouse; a steady glow keeps "lighthouse" in a moving clause)
        f = {**FACTS, "moving": ["the lighthouse lantern glows softly and steadily", "faint ripples spread gently"],
             "fixed": ["Stone lighthouse tower", "the ripples"]}
        self.assertEqual(direct.check(f), ["'the ripples' is both moving and fixed"])  # "spread" is natural motion

    def test_clean_tolerates_missing_and_bad_types(self):  # review focus: malformed model JSON
        f = direct.clean({"scene": "A cabin.", "moving": ["rain falls", 3, None, ""], "fixed": 7})
        self.assertEqual((f["moving"], f["fixed"], f["negatives"], f["adaptations"]), (["rain falls"], [], [], []))

    def test_clean_splits_lists_given_as_one_string(self):
        # real gemma4:12b reply (2026-09-25): every list field came back as a single string, and all motion was lost
        f = direct.clean({"scene": "A cabin.", "moving": "The flames dance in place. The snow falls slowly; smoke drifts.",
                          "fixed": "Wooden beam, stone fireplace frame, armchair", "negatives": "people, cars"})
        self.assertEqual(f["moving"], ["The flames dance in place", "The snow falls slowly", "smoke drifts"])
        self.assertEqual(f["fixed"], ["Wooden beam", "stone fireplace frame", "armchair"])
        self.assertEqual(f["negatives"], ["people", "cars"])

    def test_one_comma_separated_motion_sentence_is_split(self):
        # gemma4:12b on GPU with think off (2026-09-25): one sentence of comma-separated clauses
        f = direct.clean({"moving": "Flames dance in the hearth, sparks rise upward, snowflakes drift downward outside."})
        self.assertEqual(f["moving"], ["Flames dance in the hearth", "sparks rise upward", "snowflakes drift downward outside"])


class TestCompose(unittest.TestCase):
    def test_prompt_only_composition(self):
        cleaned, _ = direct.drop_violations(FACTS)
        out = direct.compose(cleaned)
        self.assertTrue(out["motion_prompt"].startswith(motion_style.LOCKED_CAMERA))
        self.assertIn("The water falls steadily into the pool; fine mist drifts slowly to the left; the ferns barely move.",
                      out["motion_prompt"])
        self.assertIn("There is no movement and no change of shape in the rocks and the cliff face.", out["motion_prompt"])
        self.assertTrue(out["motion_prompt"].endswith(motion_style.PACE + " Photorealistic, cinematic."))
        self.assertTrue(out["keyframe_prompt"].endswith(motion_style.SETTLED_STATE_CLAUSE))
        self.assertIn("jade pool", out["keyframe_prompt"])
        self.assertNotIn("falls steadily", out["keyframe_prompt"])  # appearance only
        self.assertEqual(out["negative"], motion_style.BASE_NEGATIVE + ", people")

    def test_hand_prompts_pass_through_unchanged(self):
        cabin = (  # the rain-cabin hand prompt that passed review (formerly read from the lab notes)
                 'Static locked-off shot on a tripod. The camera does not move at all during the entire shot: no pan, '
                 'no tilt, no zoom, no dolly, no push-in, no handheld shake; the framing stays exactly the same from '
                 'the first frame to the last. A dark cozy cabin bedroom at night beside large wooden-framed windows '
                 'during a steady rainstorm. Outside, rain falls steadily and continuously through the dark pine '
                 'forest; raindrops streak and trickle slowly down the window glass; the wet foliage and trees outside '
                 'sway very gently in the rain; the small roof outside glistens. Inside, the small bedside lamp gives '
                 'a dim, perfectly steady light; the overall lighting, exposure and colour of the room stay exactly '
                 'constant from the first frame to the last, dark blue-green night tones; the bed, window frames and '
                 'room stay completely still. Calm and peaceful, filmed in real time at normal speed, not a '
                 'time-lapse, not sped up. Photorealistic, cinematic.')
        self.assertEqual(direct.complete_user_prompt(cabin, FACTS)["motion_prompt"], cabin)
        neon = ("Locked-off tripod shot, completely static camera. A rain-soaked neon alley at night. Light rain falls "
                "steadily. The buildings never change shape. Calm and unhurried, filmed in real time at normal speed, "
                "not a time-lapse, not sped up. Photorealistic, cinematic.")
        self.assertEqual(direct.complete_user_prompt(neon, FACTS)["motion_prompt"], neon)

    def test_short_user_prompt_gets_missing_clauses(self):
        out = direct.complete_user_prompt("Rain falls on a cabin window at night.", {**FACTS, "fixed": ["the window frame"]})
        m = out["motion_prompt"]
        self.assertTrue(m.startswith(motion_style.LOCKED_CAMERA + " Rain falls on a cabin window at night."))
        self.assertIn("There is no movement and no change of shape in the window frame.", m)
        self.assertTrue(m.endswith(motion_style.PACE))


class TestRun(unittest.TestCase):
    def test_prompt_only_retry_then_drop(self):
        bad = {**FACTS, "moving": FACTS["moving"] + ["steam billows"]}
        replies = iter([(bad, {"request_id": "a"}), (bad, {"request_id": "b"})])
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", side_effect=lambda *a, **k: next(replies)) as cj:
            out = direct.run({}, {"prompt": "a waterfall at sunrise", "provider": "ollama", "model": "gemma4:12b"}, Path(d))
            saved = json.loads((Path(d) / "direction.json").read_text(encoding="utf-8"))
            self.assertEqual((Path(d) / "motion_prompt.txt").read_text(encoding="utf-8"), out["motion_prompt"])
        self.assertEqual(cj.call_count, 2)
        self.assertIn("billows", cj.call_args_list[1].args[1])  # the retry quotes the violation back
        self.assertNotIn("billows", out["motion_prompt"])
        self.assertEqual(saved["original_prompt"], "a waterfall at sunrise")
        self.assertIn("steam billows", saved["raw"]["moving"])  # the model's own reply, before cleaning/dropping
        self.assertEqual(saved["adaptations"][0]["asked"], "sunrise")
        self.assertTrue(out["dropped"])
        self.assertTrue(all(k["unload"] for k in (c.kwargs for c in cj.call_args_list)))

    def test_invalid_json_is_retried_once(self):
        # final review #2 / spec: "Director JSON invalid twice -> stage fails" (once was already fatal)
        from looper import models
        clean_facts = {**FACTS, "fixed": ["the rocks"]}  # no rule violation, so no violation re-ask either
        replies = iter([models.ModelError("not JSON"), (clean_facts, {"request_id": "b"})])

        def reply(*a, **k):
            r = next(replies)
            if isinstance(r, Exception):
                raise r
            return r
        with tempfile.TemporaryDirectory() as d, mock.patch("looper.models.complete_json", side_effect=reply):
            out = direct.run({}, {"prompt": "a waterfall with mist", "provider": "ollama", "model": "q"}, Path(d))
        self.assertIn("water falls", out["motion_prompt"])

    def test_think_flag_reaches_the_model_call(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(FACTS, {"request_id": "a"})) as cj:
            direct.run({}, {"prompt": "x", "provider": "ollama", "model": "qwen3.6:35b", "think": True}, Path(d))
            direct.run({}, {"prompt": "x", "provider": "ollama", "model": "qwen3.6:35b"}, Path(d))
        self.assertEqual([c.kwargs["think"] for c in cj.call_args_list[::2]], [True, False])

    def test_invented_mist_is_dropped_when_the_prompt_never_asked_for_it(self):
        # dir_pine (2026-09-26): prompt "A light, sparkling, photorealistic pine forest scene"; the director added
        # "cool mist drifts slowly toward the foreground" and all 3 takes built mist up (17-43 grey drift)
        pine = {**FACTS, "scene": "A pine forest at midday.", "keyframe_details": "sunlit trunks, moss, blue sky",
                "moving": ["pine branches sway gently", "cool mist drifts slowly toward the foreground"],
                "fixed": ["the trunks"]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(pine, {"request_id": "a"})):
            out = direct.run({}, {"prompt": "A light, sparkling, photorealistic pine forest scene", "provider": "ollama",
                                  "model": "q"}, Path(d))
        self.assertNotIn("mist", out["motion_prompt"])
        self.assertTrue(any("mist" in x for x in out["dropped"]))
        self.assertNotIn(motion_style.SETTLED_STATE_CLAUSE, out["keyframe_prompt"])  # naming mist invites mist

    def test_motion_for_things_not_in_the_frame_is_dropped(self):
        # dir_pine2 (2026-09-26): "Clear water flows continuously downstream over smooth river stones" -- no water in
        # the prompt, the keyframe description or the stills
        f = {**FACTS, "scene": "A sunlit pine forest clearing at midday.",
             "keyframe_details": "straight trunks, dense boughs of needles, velvety moss, pine cones, granite rocks",
             "moving": ["gentle air pushes outer pine boughs from left to right",
                        "clear water flows continuously downstream over smooth river stones"],
             "fixed": ["the granite rocks"]}
        grounded, dropped = direct.ground(f)
        self.assertEqual(grounded["moving"], ["gentle air pushes outer pine boughs from left to right"])
        self.assertEqual(len(dropped), 1)
        # never drops everything: a scene with no grounded clause keeps what it has
        lone = {**f, "moving": ["clear water flows downstream"]}
        self.assertEqual(direct.ground(lone)[0]["moving"], ["clear water flows downstream"])

    def test_grounding_matches_plural_forms(self):
        # dir_pine3: "Branch tips sway" was dropped although the still shows "canopy branches" (branches -> branche)
        f = {**FACTS, "scene": "A pine forest.", "keyframe_details": "layered canopy branches, bushes, glasses",
             "moving": ["pine needles glint", "branch tips sway slowly", "a bush trembles", "glass glints"], "fixed": []}
        self.assertEqual(direct.ground(f)[1], [])  # "pine needles" matches, so the keep-all fallback is not in play

    def test_sun_flare_is_negative_and_kept_out_of_frame(self):
        # dir_pine4 (2026-09-26): a sun flare / rays in the top-right cell pulsed in every take (13.8-60 grey drift)
        for w in ("lens flare", "sun rays", "sun in frame"):
            self.assertIn(w, motion_style.BASE_NEGATIVE)
        # v15 realism amendment: the scene keeps its sun; only a MOTION clause about the sun is dropped (it grew one)
        self.assertIn("keep the sun where the scene has it", direct._BRIEF.lower())

    def test_daylight_scene_gets_the_sun_hidden_clause_positively(self):
        # dir_pine5: negatives (lens flare, sun rays) did nothing -- distilled LTX mostly ignores them -- and a sun +
        # rays grew in the top-right over the take (55.6 grey). Positive wording instead; sun-moving clauses dropped.
        f = {**FACTS, "scene": "A sunlit pine forest clearing at midday.", "keyframe_details": "pine trunks, moss",
             "moving": ["pine branches sway gently", "sunlight maintains a steady overhead position"], "fixed": []}
        out = direct.compose(direct.drop_violations(f)[0])
        self.assertIn(motion_style.SUN_HIDDEN, out["motion_prompt"])
        self.assertNotIn("overhead position", out["motion_prompt"])
        # dir_pine6: "The sun stays hidden ... no sun disc" itself grew a sun (68 grey); pine7 with no sun words: 10.7
        self.assertNotIn("sun", motion_style.SUN_HIDDEN.lower())
        night = direct.compose({**f, "scene": "A neon alley at night.", "moving": ["rain falls"]})
        self.assertNotIn(motion_style.SUN_HIDDEN, night["motion_prompt"])

    def test_lighthouse_storm_rules(self):
        # v15 (review 2026-09-27: no ban on beams): the v11 bans on a sweeping beam and breaking waves are
        # gone -- nothing of the storm is dropped. Kept: the daylight clause must not fire on "late afternoon storm at
        # dusk" (dir_lighthouse, 2026-09-26)
        f = {**FACTS, "scene": "A stone lighthouse on a cliff during the late afternoon storm at dusk.",
             "keyframe_details": "lighthouse tower, lantern, rocks, sea",
             "moving": ["diagonal streaks of rain fall continuously", "the lighthouse beam sweeps slowly across the clouds",
                        "white-tipped waves break repeatedly against the rock base", "waves crash on the rocks",
                        "a gentle swell rolls steadily toward the rocks"], "fixed": ["the lighthouse tower"]}
        cleaned, dropped = direct.drop_violations(f)
        self.assertEqual(cleaned["moving"], f["moving"])
        self.assertEqual(dropped, [])
        self.assertNotIn("no sweeping", direct._BRIEF.lower())
        self.assertNotIn(motion_style.SUN_HIDDEN, direct.compose(cleaned)["motion_prompt"])  # dusk, not daylight
        self.assertIn(motion_style.SUN_HIDDEN, direct.compose({**cleaned, "scene": "A lighthouse at midday."})["motion_prompt"])

    def test_lights_keep_a_quick_living_flicker(self):
        # dir_lighthouse2 review: the light looked static and lifeless, with no pulse or glow. Only a SLOW change
        # breaks a loop (the drift check averages each second); a quick flicker / breathing glow is loop-safe
        brief = direct._BRIEF.lower()
        self.assertIn("flicker", brief)
        self.assertNotIn("lantern glows steadily", brief)
        f = {**FACTS, "moving": ["the lantern flickers softly and breathes with a warm glow"], "fixed": []}
        self.assertEqual(direct.drop_violations(f)[1], [])

    def test_fixed_clause_is_capped(self):  # crawler_720: 17 fixed items pushed the prompt over the render guard
        f = {**FACTS, "fixed": [f"iron plate {i}" for i in range(17)]}
        m = direct.compose(f)["motion_prompt"]
        self.assertIn("iron plate 7", m)
        self.assertNotIn("iron plate 8", m)

    def test_sea_scenes_get_a_real_time_water_clause(self):
        # dir_lighthouse2 (no clause) looked far too fast and fake in review; lr_s02 ("slowly and heavily" + clock 0.2)
        # was judged worse still -> v15 asks for weight and travel, not slowness
        self.assertNotIn("slowly", motion_style.WATER_PACE)
        sea = {**FACTS, "scene": "A lighthouse on a cliff above the sea at dusk.", "moving": ["the swell rolls in"]}
        self.assertIn(motion_style.WATER_PACE, direct.compose(sea)["motion_prompt"])
        forest = {**FACTS, "scene": "A pine forest.", "keyframe_details": "pines", "moving": ["branches sway"]}
        self.assertNotIn(motion_style.WATER_PACE, direct.compose(forest)["motion_prompt"])

    def test_waves_in_a_robe_are_not_the_sea(self):
        """sample_2 (2026-09-30): "slow waves travel through the heavy fabric of the hooded robe" put the sea clause
        ("waves travel in toward the shore and break into foam") into a desert scene's prompt for both models. Only an
        unambiguous water word makes a sea scene; waves / swell alone also live in cloth, heat and sound."""
        desert = {**FACTS, "scene": "A golden desert seen through a monumental stone archway.",
                  "keyframe_details": "hooded figure, robe, dunes, fortress, twin suns",
                  "moving": ["slow waves travel through the heavy fabric of the hooded robe",
                             "heat waves shimmer above the dunes", "the cloak swells in the gusts"]}
        self.assertNotIn(motion_style.WATER_PACE, direct.compose(desert)["motion_prompt"])

    def test_brief_keeps_continuous_sparkle(self):
        self.assertIn("sparkl", direct._BRIEF.lower())

    def test_unasked_mist_in_the_still_description_gets_no_settled_clause_and_a_warning(self):
        # final review #3: mist in keyframe_details (not motion) still reached the still + the settled clause
        f = {**FACTS, "scene": "A pine forest at midday.", "keyframe_details": "tall pines, soft morning mist between",
             "moving": ["pine branches sway gently"], "fixed": ["the trunks"]}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(f, {"request_id": "a"})):
            out = direct.run({}, {"prompt": "A pine forest", "provider": "ollama", "model": "q"}, Path(d))
        self.assertNotIn(motion_style.SETTLED_STATE_CLAUSE, out["keyframe_prompt"])
        self.assertTrue(any("mist" in w for w in out["warnings"]), out["warnings"])

    def test_sun_words_in_the_scene_sentence_are_not_a_violation_and_stay_out_of_motion(self):
        # final review #4: "sun in frame" fired on the scene sentence (a wasted 2-4 min retry) and "Sunlight ..."
        # still reached the motion prompt through the scene sentence
        f = {**FACTS, "scene": "Sunlight filters through a quiet pine forest at midday.", "keyframe_details": "pines",
             "moving": ["pine branches sway gently"], "fixed": []}
        self.assertEqual(direct.check(f), [])
        motion = direct.compose(f)["motion_prompt"]
        self.assertNotRegex(motion.lower(), r"\bsun")
        self.assertIn("Pine branches sway gently", motion)  # a sun-subject scene sentence is left out (still has it)
        adj = direct.compose({**f, "scene": "A sunlit pine forest at midday."})["motion_prompt"]
        self.assertIn("A pine forest at midday.", adj)  # a sun adjective is just removed

    def test_asked_for_mist_is_kept_and_settled(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(FACTS, {"request_id": "a"})):
            out = direct.run({}, {"prompt": "A jungle waterfall with mist", "provider": "ollama", "model": "q"}, Path(d))
        self.assertIn("mist drifts", out["motion_prompt"])
        self.assertTrue(out["keyframe_prompt"].endswith(motion_style.SETTLED_STATE_CLAUSE))

    def test_one_line_prompt_renders_the_still_from_the_users_words(self):
        # blind stills 2026-09-27: the user's words won 2 of 3; the director's rewrite lost the waterfall twice
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(FACTS, {"request_id": "a"})):
            out = direct.run({}, {"prompt": "A jungle waterfall with mist", "provider": "ollama", "model": "q"}, Path(d))
            rec = json.loads((Path(d) / "direction.json").read_text(encoding="utf-8"))
        self.assertTrue(out["keyframe_prompt"].startswith("A jungle waterfall with mist"))
        self.assertNotIn("jade pool", out["keyframe_prompt"])  # director details stay out of the still
        self.assertIn("jade pool", rec["director_keyframe_prompt"])  # ...but are kept for traceability
        self.assertIn("falls steadily", out["motion_prompt"])  # the motion prompt is still directed

    def test_image_path_warns_instead_of_changing(self):
        user = "Steam billows from a vent in a neon alley."
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(FACTS, {"request_id": "a"})) as cj:
            img = Path(d) / "k.png"
            img.write_bytes(b"x")
            out = direct.run({"image": img}, {"prompt": user, "provider": "ollama", "model": "gemma4:12b"}, Path(d))
        self.assertEqual(cj.call_count, 1)
        self.assertEqual(cj.call_args.kwargs["images"], [img])
        self.assertIn(user, out["motion_prompt"])
        self.assertTrue(any("billows" in w for w in out["warnings"]))

    def test_image_path_brief_is_directed_not_verbatim(self):  # dir_furnace: 5.8k chars of markdown went to LTX
        brief = ("# The Waterfall\n\n## Scene\n\nA waterfall with mist.\n\n## Style\n\n"
                 "- No people, vehicles or neon.\n")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(FACTS, {"request_id": "a"})):
            img = Path(d) / "k.png"
            img.write_bytes(b"x")
            out = direct.run({"image": img}, {"prompt": brief, "provider": "ollama", "model": "q"}, Path(d))
            rec = json.loads((Path(d) / "direction.json").read_text(encoding="utf-8"))
        self.assertNotIn("#", out["motion_prompt"])
        self.assertNotIn("No people", out["motion_prompt"])
        self.assertIn("The water falls steadily", out["motion_prompt"])
        self.assertEqual(rec["original_prompt"], brief)  # the user's words stay recorded beside the result

    def test_is_brief(self):
        self.assertFalse(direct.is_brief("Steam billows from a vent in a neon alley."))
        self.assertTrue(direct.is_brief("line one\nline two"))
        self.assertTrue(direct.is_brief("x" * 601))


if __name__ == "__main__":
    unittest.main()
