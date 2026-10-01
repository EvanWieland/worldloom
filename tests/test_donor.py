"""Motion donor route (ADR 0016): donor lengths, the continuation's start frame, the whole-frame wrap match and the
return guide layout. Needs numpy (WanGP venv)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import cv2
    import numpy as np
except ImportError:  # system Python without numpy
    np = None
if np is not None:
    from looper.stages import donor  # a missing module must fail, not skip


@unittest.skipIf(np is None, "needs numpy (WanGP venv)")
class DonorLengths(unittest.TestCase):
    def test_the_donor_covers_the_guide_it_is_slowed_into(self):
        self.assertEqual(donor.frames_for(481, 1.0), 481)  # real time: one donor frame per guide frame, no margin
        self.assertEqual(donor.frames_for(481, 0.6), 293)  # guide frame 480 = donor frame 288, + the retime margin
        n = donor.frames_for(377, 0.6)
        self.assertEqual((n - 1) % 4, 0)  # Hunyuan clip lengths are 4k + 1
        self.assertGreaterEqual(n - 1, (377 - 1) * 0.6)

    def test_the_continuation_starts_at_the_loops_last_body_frame(self):
        self.assertEqual(donor.start_frame(409, 1.0), 408)  # spice_guided: the first continuation's frame
        self.assertEqual(donor.start_frame(409, 0.6), 245)  # guide frame 408 = donor frame 244.8


@unittest.skipIf(np is None, "needs numpy (WanGP venv)")
class DonorHold(unittest.TestCase):
    """A subject that travels in the donor travels in every take (sample_2 seed 306: +13.6 px torso, the take's figure
    stepped +18 px; spice v23: +114 px walk). Calibrated on six real donors: holding ones moved <= 1.9 px net."""

    def test_a_walking_or_stepping_subject_is_caught_and_a_steady_one_passes(self):
        walk = [200 + 10 * i for i in range(13)]
        step = [250.0] * 7 + [264.0] * 6
        hold = [250 + (1.5 if i % 2 else -1.5) for i in range(13)]
        self.assertTrue(donor.travels(walk, 832)["travels"])
        self.assertTrue(donor.travels(step, 832)["travels"])
        r = donor.travels(hold, 832)
        self.assertFalse(r["travels"])
        self.assertLess(abs(r["net_px"]), 2)

    def test_no_subject_found_is_no_verdict(self):
        self.assertIsNone(donor.travels([None] * 13, 832)["travels"])  # a scene without a person: nothing to hold


class DonorPrompt(unittest.TestCase):
    def test_the_donor_is_told_to_keep_every_figure_in_place_once(self):
        """The distilled Hunyuan donor runs without CFG, so a 'walking' negative does nothing; the positive prompt
        must hold figures in place (the director's spice prompt walked the traveler off in every Hunyuan clip)."""
        from looper import motion_style
        p = motion_style.donor_prompt("A hooded traveler in the wind; the cloak billows.")
        self.assertIn("stays exactly where it is", p)
        self.assertTrue(p.startswith("A hooded traveler in the wind"))
        self.assertEqual(motion_style.donor_prompt(p), p)


@unittest.skipIf(np is None, "needs numpy (WanGP venv)")
class WrapMatch(unittest.TestCase):
    def test_picks_the_gap_whose_continuation_runs_into_the_loop_start(self):
        rng = np.random.default_rng(0)
        start = [rng.integers(0, 255, (48, 64, 3), np.uint8) for _ in range(8)]  # the loop's first 8 frames
        cont = [rng.integers(0, 255, (48, 64, 3), np.uint8) for _ in range(60)]
        for k in range(8):  # at gap 40, the continuation's next 8 frames are the loop start (dimmer: tone differs)
            cont[41 + k] = (start[k] * 0.7).astype(np.uint8)
        g, scores = donor.wrap_match(cont, start, [24, 32, 40, 48], donor.activity(start))
        self.assertEqual(g, 40)
        self.assertEqual(min(scores, key=scores.get), 40)  # a distance: lower = closer

    def test_the_moving_part_decides_not_the_static_background(self):
        """Real donors: the static scene dominates a plain whole-frame match (spice: all gaps 0.92-0.93). The take's
        own activity weights the match towards what moves (automatic, no regions)."""
        rng = np.random.default_rng(1)
        bg = cv2.resize(rng.integers(40, 220, (15, 26, 3), np.uint8), (208, 120), interpolation=cv2.INTER_NEAREST)

        def frame(x, tone=1.0):
            f = bg.copy()
            cv2.circle(f, (int(x), 80), 6, (15, 15, 15), -1)
            return np.clip(f * tone, 0, 255).astype(np.uint8)
        take = [frame(40 + 30 * np.sin(i / 8)) for i in range(96)]  # the blob sways; the rest never moves
        start = take[:8]
        cont = [frame(40 + 30 * np.sin(i / 5 + 1.3), tone=0.8) for i in range(80)]  # another sway, darker (drift)
        for k in range(8):
            cont[41 + k] = frame(40 + 30 * np.sin(k / 8), tone=0.8)  # at gap 40 the blob is where the loop starts
        g, _ = donor.wrap_match(cont, start, range(8, 64, 8), donor.activity(take))
        self.assertEqual(g, 40)

    def test_return_guide_is_end_context_then_continuation_then_start_context(self):
        take = [np.full((4, 4, 3), i, np.uint8) for i in range(200)]
        cont = [np.full((4, 4, 3), 250 - i, np.uint8) for i in range(100)]
        g = donor.return_guide_frames(take, cont, s=57, e=150, E=49, S=64, G=40)
        self.assertEqual(len(g), 49 + 40 + 64)
        self.assertEqual(int(g[0][0, 0, 0]), 150 - 49)  # take[e - E]
        self.assertEqual(int(g[49][0, 0, 0]), 250 - 1)  # cont[1]: cont[0] is the take's last body frame itself
        self.assertEqual(int(g[49 + 40][0, 0, 0]), 57)  # take[s]


if __name__ == "__main__":
    unittest.main()
