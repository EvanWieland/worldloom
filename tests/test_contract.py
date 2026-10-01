"""Scene contract (looper/contract.py): the director cannot erase a required element (handoff 2026-09-27 §6), and a
beam the director selects is kept (realism amendment 2026-09-27: no ban on beams)."""
import unittest

from looper import contract, motion_style
from looper.stages import direct

LIGHTHOUSE = "A lighthouse on a rocky cliff in a storm at dusk"
# lighthouse_lr_s02's effective motion prompt (dir_lighthouse2 director output): the lantern survived the director
LR_S02 = ("Static locked-off shot on a tripod. A coastal stone lighthouse perched on a jagged rock formation during a "
          "stormy dusk. Low cloud layers drift slowly from left to right; Dark water rolls as a steady horizontal swell "
          "across the frame; Heavy rain falls continuously in vertical sheets; Warm interior lantern light emits a "
          "steady glow through glass panes. There is no movement and no change of shape in Stone lighthouse tower, "
          "Brass lantern housing. Calm and unhurried, filmed in real time at normal speed.")
BEAM_PLAN = ("Static locked-off shot on a tripod. The lighthouse beam sweeps steadily around through the rain; "
             "waves break into foam on the rocks. There is no movement and no change of shape in the stone tower.")


def plan_of(facts):
    return {k: v for k, v in direct.compose(facts, settled=False).items() if k in ("motion_prompt", "negative")}


class TestContract(unittest.TestCase):
    def test_lighthouse_words_imply_the_lantern(self):
        ids = [r["id"] for r in contract.derive(LIGHTHOUSE)["requirements"]]
        self.assertEqual(ids, ["lantern_emission"])

    def test_director_rules_no_longer_drop_beams_or_breaking_waves(self):
        facts = {"moving": ["The lighthouse beam sweeps steadily around through the rain",
                            "Waves break into foam against the rocks"]}
        f, dropped = direct.drop_violations(facts)
        self.assertEqual(dropped, [])
        self.assertEqual(len(f["moving"]), 2)

    def test_director_selected_beam_becomes_a_requirement_and_survives_a_static_rewrite(self):
        c = contract.derive(LIGHTHOUSE, selected_plan=BEAM_PLAN)
        beam = next(r for r in c["requirements"] if r["id"] == "beam_rotation")
        self.assertEqual(beam["origin"], "director_selected")
        self.assertIn("static_glow_instead_of_rotation", beam["forbidden_substitutions"])
        # a later rewrite / retry turns the sweep into a steady glow: detected and repaired, not accepted
        static = {"motion_prompt": "The lighthouse lantern glows steadily. Waves break on the rocks.", "negative": ""}
        self.assertFalse(contract.check(c, static)["ok"])
        fixed, result, repairs = contract.enforce(c, static)
        self.assertTrue(result["ok"], result)
        self.assertIn("keeps sweeping steadily around", fixed["motion_prompt"])
        route = next(i for i in result["items"] if i["id"] == "beam_rotation")["route"]
        self.assertEqual(route, "unverified")

    def test_beam_dropped_by_a_director_retry_is_still_required(self):
        # the first proposal had the sweep; the retry answer only glows -> the contract (from both) puts it back
        c = contract.derive(LIGHTHOUSE, selected_plan="The lighthouse beam sweeps around through the rain. "
                                                      "The lantern glows steadily.")
        self.assertIn("beam_rotation", {r["id"] for r in c["requirements"]})
        plan = contract.technical_plan(c)
        beam = next(p for p in plan if p["id"] == "beam_rotation")
        self.assertEqual(beam["status"], "unverified")
        self.assertIn("raw generated frames (no whole-frame tone target)", beam["controls"])

    def test_plan_without_any_light_gets_the_lantern_back(self):
        facts = {"scene": "A stone lighthouse on a rocky cliff in a storm at dusk.", "style": "Photorealistic",
                 "keyframe_details": "A stone lighthouse above dark sea and rocks.",
                 "moving": ["Dark water rolls toward the rocks", "Rain falls in sheets"],
                 "fixed": ["stone tower"], "negatives": [], "adaptations": []}
        c = contract.derive(LIGHTHOUSE)
        plan = plan_of(facts)
        self.assertFalse(contract.check(c, plan)["ok"])
        fixed, result, repairs = contract.enforce(c, plan)
        self.assertTrue(result["ok"], result)
        self.assertIn("lighthouse lantern stays lit", fixed["motion_prompt"])

    def test_lr_s02_plan_needs_no_repair(self):
        c = contract.derive(LIGHTHOUSE, selected_plan=LR_S02)
        plan, result, repairs = contract.enforce(c, {"motion_prompt": LR_S02, "negative": motion_style.BASE_NEGATIVE})
        self.assertEqual((repairs, plan["motion_prompt"]), ([], LR_S02))

    def test_requested_beam_negative_is_removed(self):
        c = contract.derive("A lighthouse at night, its beam sweeping slowly through the fog")
        self.assertTrue({"lantern_emission", "beam_rotation", "smoke_motion"} <= {r["id"] for r in c["requirements"]})
        plan, result, repairs = contract.enforce(c, {"motion_prompt": "The beam sweeps through the fog. Fog drifts.",
                                                     "negative": "zoom, sweeping light beams, text"})
        self.assertEqual(plan["negative"], "zoom, text")
        self.assertEqual(contract.status(result), "ok")

    def test_base_negative_has_no_beam_ban(self):
        self.assertNotIn("beam", motion_style.BASE_NEGATIVE)

    def test_event_wording_is_not_a_beam(self):
        ids = [r["id"] for r in contract.derive("A cafe at dusk where the lights turn on one by one")["requirements"]]
        self.assertNotIn("beam_rotation", ids)

    def test_fixed_clause_does_not_count_as_motion(self):
        c = contract.derive("A waterfall in a jungle")
        r = contract.check(c, {"motion_prompt": "There is no movement and no change of shape in the waterfall rocks.",
                               "negative": ""})
        self.assertFalse(r["items"][0]["mapped"])

    # realism amendment §14 planning regressions (they prove requirements survive rewriting, not that renders look real)
    def test_industrial_ruin_gear_is_kept_turning(self):
        c = contract.derive("An industrial ruin with one operating gear turning slowly, smoke and sparks from a furnace")
        ids = {r["id"] for r in c["requirements"]}
        self.assertTrue({"machine_rotation", "fire_emission", "smoke_motion"} <= ids, ids)
        frozen = {"motion_prompt": "Smoke rises from the furnace; sparks drift. There is no movement and no change of "
                                   "shape in the gear.", "negative": ""}
        fixed, result, _ = contract.enforce(c, frozen)
        self.assertTrue(result["ok"])
        self.assertIn("gear keeps turning rigidly", fixed["motion_prompt"])

    def test_castle_light_shafts_are_moving_light(self):
        p = "A castle on a hill; shafts of light shift across the walls as the clouds pass."
        c = contract.derive(p)
        self.assertIn("light_shafts", {r["id"] for r in c["requirements"]})
        self.assertTrue(motion_style.MOVING_LIGHT.search(p))  # -> exposure-only clause, raw gap, 5 s QC means
        self.assertFalse(motion_style.ROTATING_BEAM.search(p))  # no beam phase track
        f, dropped = direct.drop_violations({"moving": ["sunbeams shift across the walls as clouds pass"]})
        self.assertEqual(dropped, [])  # the sun rule only drops the sun itself moving

    def test_rain_on_cabin_window_keeps_rain(self):
        c = contract.derive("Rain on a cabin window at night, a fire glowing inside")
        self.assertEqual({r["id"] for r in c["requirements"]}, {"rain_motion", "fire_emission"})
        _, result, repairs = contract.enforce(c, {"motion_prompt": "Rain streams down the glass. The fire flickers.",
                                                  "negative": ""})
        self.assertEqual((result["ok"], repairs), (True, []))

    def test_crawler_exclusions_stay_excluded(self):
        # crawler_720 (2026-09-27, first real contract run): "Avoid ... neon" became a neon requirement, the neon
        # negative was removed and "The neon stays lit" added; "a stream of glowing slag" became water + a sea framing
        brief = ("A rear chute pours incandescent slag onto a long trail of cooling waste. Fierce amber furnace light "
                 "escapes through deep processing vents, illuminating nearby iron and smoke. Show an uninterrupted "
                 "stream of glowing slag. No human cockpit or crew. Capture sustained operation, with no startup "
                 "effects or explosions. Avoid conventional excavator styling, weapons, neon, glossy spaceship "
                 "surfaces, cartoon effects, motion streaks, text, and watermarks.")
        plan = ("Two angled cutting drums rotate at a heavy steady pace; a continuous stream of incandescent slag "
                "falls from the rear chute; amber furnace vents glow. Neon signs flicker on the hull. Filmed in real "
                "time at normal speed.")
        c = contract.derive(brief, selected_plan=plan)
        ids = {r["id"] for r in c["requirements"]}
        self.assertNotIn("neon_emission", ids)
        self.assertNotIn("water_motion", ids)
        self.assertTrue({"fire_emission", "smoke_motion", "machine_rotation"} <= ids, ids)
        self.assertEqual([x["id"] for x in c["exclusions"]], ["neon_emission"])
        fixed, result, repairs = contract.enforce(c, {"motion_prompt": plan, "negative": "text, neon lighting"})
        self.assertIn("neon lighting", fixed["negative"])
        self.assertNotIn("Neon signs", fixed["motion_prompt"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(any("you excluded it" in line for line in contract.checklist(c, result)))
        self.assertNotIn("sea", " ".join(contract.FRAMING[r] for r in ids if r in contract.FRAMING).lower())

    def test_collective_nouns_of_particles_are_not_water_or_sky(self):
        # spice_desert (2026-09-28): "streams and clouds of sparkling spice ... move" became water + cloud requirements
        # and "The streams / clouds keep moving" was added to the motion prompt; "waves of airborne material" too
        brief = ("Dense streams and clouds of sparkling spice visibly move through the open space. Occasional "
                 "stronger gusts create denser waves of airborne material. A sea of dunes rolls to the horizon. "
                 "Large volumes of dust drift gradually through the distance. Midground: dense visible spice streams "
                 "and dust clouds drift past.")
        ids = {r["id"] for r in contract.derive(brief)["requirements"]}
        self.assertEqual(ids, {"smoke_motion"})
        real = {r["id"] for r in contract.derive("Waves break on the shore while clouds drift over the river")["requirements"]}
        self.assertEqual(real, {"water_motion", "cloud_motion"})

    def test_stream_and_wave_as_verbs_are_not_water(self):
        # sample_1 (2026-09-30): "spice particles sparkle ... and stream through the air" became a water requirement
        brief = ("Fine golden spice particles sparkle visibly in the foreground and stream through the air. Sunlight "
                 "streams in through a gap. A tattered banner waves in the wind.")
        self.assertNotIn("water_motion", {r["id"] for r in contract.derive(brief)["requirements"]})
        for water in ("A mountain stream flows over mossy rocks", "Waves roll in toward the beach",
                      "A thin cascade spills down the cliff"):
            self.assertIn("water_motion", {r["id"] for r in contract.derive(water)["requirements"]}, water)

    def test_heat_haze_that_waves_and_shimmers_is_not_water(self):
        # spice_handsoff (2026-10-01): the director's "Heat distortion subtly waves and shimmers above the hottest parts
        # of the desert floor" put "The water visibly moves" on a desert loop's review checklist
        plan = "Heat distortion subtly waves and shimmers above the hottest parts of the desert floor"
        self.assertNotIn("water_motion", {r["id"] for r in contract.derive("A desert", selected_plan=plan)["requirements"]})
        self.assertIn("water_motion", {r["id"] for r in contract.derive("Waves and foam wash over the rocks")["requirements"]})

    def test_light_that_streams_steadily_through_a_window_is_not_water(self):
        # gcr_fire (2026-10-01): the user's "Silvery moonlight streams steadily through both leaded windows" became a
        # water requirement (an adverb between the verb and where it goes)
        brief = "Silvery moonlight streams steadily through both leaded windows, forming soft beams."
        self.assertNotIn("water_motion", {r["id"] for r in contract.derive(brief)["requirements"]})
        self.assertIn("water_motion", {r["id"] for r in contract.derive("Streams slowly carve the valley floor")["requirements"]})

    def test_steady_light_keeps_old_clause_unless_moving_light(self):
        p, _ = motion_style.steady_light("Rain falls.", "")
        self.assertIn(motion_style.STEADY_LIGHT_POS, p)
        p, _ = motion_style.steady_light(BEAM_PLAN, "", moving_light=True)
        self.assertIn(motion_style.STEADY_EXPOSURE_POS, p)
        self.assertNotIn(motion_style.STEADY_LIGHT_POS, p)
        self.assertTrue(motion_style.MOVING_LIGHT.search(BEAM_PLAN))
        self.assertFalse(motion_style.MOVING_LIGHT.search(LR_S02))

    def test_pulsing_or_flashing_light_is_moving_light(self):
        m = motion_style.MOVING_LIGHT.search
        self.assertTrue(m("The anti-gravity emitters beneath the hull pulse rhythmically with bright white-amber light;"))
        self.assertTrue(m("Bright white forks of atmospheric discharge flash intermittently across the sky;"))
        self.assertFalse(m("Industrial floodlights glow steadily with subtle intensity fluctuations."))
        self.assertFalse(m("Waves flash white against the rocks; the lamp stays dim."))  # flash without a light source

    def test_light_shafts_move_with_the_motion_word_before_them(self):
        m = motion_style.MOVING_LIGHT.search
        self.assertTrue(m("Shifting shafts of light fall through the dusty hall;"))
        self.assertTrue(m("Slowly moving light shafts cut through the haze;"))
        self.assertTrue(m("God rays drift across the nave as clouds pass."))  # the old order still matches
        self.assertFalse(m("Dust drifts slowly through the still rays of the lamp."))  # the dust moves, not the rays


if __name__ == "__main__":
    unittest.main()
