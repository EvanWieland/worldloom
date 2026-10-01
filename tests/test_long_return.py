import unittest
from pathlib import Path

try:
    from looper import loop_pipeline
    from looper.adapters import ltx
except ImportError:  # system Python without cv2/numpy
    loop_pipeline = None


@unittest.skipIf(loop_pipeline is None, "needs cv2/numpy (WanGP venv)")
class LongReturn(unittest.TestCase):
    def cfg(self, **kw):
        return {**loop_pipeline.DEFAULTS, **kw}

    def test_gap_fills_30_s_without_extension(self):
        c = self.cfg(seconds=30.0)
        g = loop_pipeline.long_return_gap(c)
        self.assertEqual(g, 328)  # 720 - (481 - 89)
        c.update(gap_frames=g, close_frames=145 + g - 32)
        self.assertEqual(loop_pipeline.plan_lengths(c), {"extension_window": 0, "loop_frames": 720})

    def test_gap_is_capped_by_one_window(self):
        self.assertEqual(loop_pipeline.long_return_gap(self.cfg(seconds=60.0)), loop_pipeline.MAX_GAP)

    def test_default_route_is_long_return_only_when_one_window_fits(self):
        self.assertTrue(loop_pipeline.long_return_fits(self.cfg(seconds=30.0)))
        self.assertFalse(loop_pipeline.long_return_fits(self.cfg(seconds=60.0)))

    def test_speed_adds_the_lora_only_when_slowed(self):
        base = ltx.settings("p", "n", "i.png", "c.mp4", 121, 1)
        self.assertNotIn("activated_loras", base)
        slow = ltx.settings("p", "n", "i.png", "c.mp4", 121, 1, motion_speed=0.5)
        self.assertEqual(slow["activated_loras"], [ltx.SPEED_LORA])
        self.assertEqual({k: v for k, v in slow.items() if k not in ("activated_loras", "loras_multipliers")}, base)

    def test_single_stage_is_one_guidance_phase_and_its_latent_stands_for_stage1(self):
        self.assertNotIn("guidance_phases", ltx.settings("p", "n", "i.png", "c.mp4", 121, 1))
        self.assertEqual(ltx.settings("p", "n", "i.png", "c.mp4", 121, 1, single_stage=True)["guidance_phases"], 1)
        self.assertEqual(ltx.stage1_latent_path(Path("d"), True).name, "lat_stage2.pt")
        self.assertEqual(ltx.stage1_latent_path(Path("d"), False).name, "lat_stage1.pt")


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(loop_pipeline is None, "needs cv2/numpy (WanGP venv)")
class ControlVideo(unittest.TestCase):
    def test_a_moving_guide_replaces_the_held_still_only_when_it_covers_the_window(self):
        import tempfile
        import numpy as np
        from looper import loopkit
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            guide = loopkit.write_video([np.zeros((64, 96, 3), np.uint8)] * 9, d / "guide.mp4")
            self.assertEqual(ltx.control(d / "key.png", 9, d / "c.mp4", guide), guide)
            with self.assertRaises(ValueError):  # a short guide would leave the window's tail unguided
                ltx.control(d / "key.png", 17, d / "c.mp4", guide)
            cv2 = __import__("cv2")
            cv2.imwrite(str(d / "key.png"), np.zeros((64, 96, 3), np.uint8))
            held = ltx.control(d / "key.png", 9, d / "held.mp4")  # no guide: the keyframe held still (camera lock)
            self.assertEqual(len(loopkit.read_frames(held)), 9)


@unittest.skipIf(loop_pipeline is None, "needs cv2/numpy (WanGP venv)")
class EarlyAccept(unittest.TestCase):
    def test_only_a_clearly_clean_closure_stops_the_seed_loop(self):
        ok = {"accept": True, "closing_over_rest": 1.0, "fails": [], "gap_churn_worst_cell": 1.3}
        self.assertTrue(loop_pipeline.clearly_clean(ok))
        for bad in ({"accept": False}, {"closing_over_rest": 1.5}, {"fails": ["c10.spike"]},
                    {"gap_churn_worst_cell": 1.61}, {"gap_churn_worst_cell": None}):
            self.assertFalse(loop_pipeline.clearly_clean({**ok, **bad}), bad)


@unittest.skipIf(loop_pipeline is None, "needs cv2/numpy (WanGP venv)")
class CalmestSegment(unittest.TestCase):
    def test_avoids_the_drifting_part_of_a_take(self):
        import numpy as np
        from looper import loopkit
        frames = [np.full((48, 64, 3), 100, np.uint8) for _ in range(481)]
        for i in range(300, 481):  # the take's second half darkens steadily in one region
            frames[i] = frames[i].copy()
            frames[i][:16, :16] = 100 - (i - 300) // 6
        s, e, score = loopkit.calmest_segment(frames, 200, 392)
        self.assertEqual((s % 8, e % 8), (1, 1))
        self.assertGreaterEqual(e - s, 200)
        self.assertLessEqual(e, 320)  # stays out of the drift
        self.assertLess(score, 1.0)
