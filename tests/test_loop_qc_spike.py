"""loop_qc v2: a spike rejects only inside the pipeline's modified frame ranges. Stdlib only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from looper.stages.loop_qc import in_modified
    HAVE = True
except ImportError:  # loop_qc imports cv2 via loopkit
    HAVE = False


@unittest.skipUnless(HAVE, "needs cv2/numpy (WanGP venv)")
class TestSpikeRanges(unittest.TestCase):
    def test_ranges(self):
        n, gap = 432, 400  # 18 s loop, 32-frame gap at the end
        for f in (400, 415, 431, 0, 5, 19, 380):  # gap, tail ramp+margin, head ramp+margin
            self.assertTrue(in_modified(f, n, gap, None), f)
        for f in (283, 200, 100, 30, 379):  # dir_lighthouse2's swell spike at 11.8 s (283) is the scene
            self.assertFalse(in_modified(f, n, gap, None), f)
        self.assertTrue(in_modified(283, n, gap, 290))  # ...unless an extension join sits there
        self.assertFalse(in_modified(260, n, gap, 290))

    def test_a_flag_says_where_on_screen_and_when(self):
        """sample_2 (2026-09-30): the review said only "c20.low"; the reviewer could not tell where the lull was."""
        from looper.stages.loop_qc import where
        self.assertEqual(where("c20", 478), "bottom-left, 19.9 s")
        self.assertEqual(where("c11", 295), "middle, centre-left, 12.3 s")
        self.assertEqual(where("c03", 0), "top-right, 0.0 s")
        self.assertEqual(where("cloak", 48), "cloak, 2.0 s")  # a named scene region keeps its name

    def test_every_flag_gets_its_place(self):
        from looper.stages.loop_qc import fail_where
        report = {"fails": ["c20.low", "static.luma_dev"],
                  "gates": {"c20": {"low": {"at": ["c20|raw|8", 478]}}, "static": {"luma_dev": {"at": 431}}}}
        self.assertEqual(fail_where(report), {"c20.low": "bottom-left, 19.9 s", "static.luma_dev": "static areas, 18.0 s"})
        from looper.loop_pipeline import flags
        self.assertEqual(flags({"fails": ["c20.low", "c11.spike"], "fail_where": {"c20.low": "bottom-left, 19.9 s"}}),
                         ["c20.low (bottom-left, 19.9 s)", "c11.spike"])  # the review / failed-run line

    def test_a_lull_is_not_a_freeze(self):
        """v10, scenes without machinery: the user passed brief calm dips (sample_2 0.39-0.49 for 0.2-2.1 s, sample_1b
        0.43 for 0.3 s) and the held-still return froze the cloak (0.17-0.24 for 8-14 s)."""
        import numpy as np
        from looper.stages.loop_qc import freeze
        fps, calm = 24, np.ones(720)
        lull = calm.copy(); lull[400:450] = 0.42                 # ~2 s at 0.42: the user saw nothing
        deep = calm.copy(); deep[400:412] = 0.2                  # 0.5 s at 0.2: too deep for a lull
        long_ = calm.copy(); long_[100:250] = 0.45               # 6 s at 0.45: too long
        froze = calm.copy(); froze[360:700] = 0.2                # the held-still return
        self.assertFalse(freeze(lull, 0.5, fps)["freeze"])
        self.assertTrue(freeze(deep, 0.5, fps)["freeze"])
        self.assertTrue(freeze(long_, 0.5, fps)["freeze"])
        self.assertTrue(freeze(froze, 0.5, fps)["freeze"])
        self.assertAlmostEqual(freeze(lull, 0.5, fps)["longest_s"], 50 / 24, places=2)

    def test_machinery_keeps_the_strict_lull_gate(self):
        from looper.loop_pipeline import lull_mode
        self.assertEqual(lull_mode("Two cutting drums rotate at a heavy, steady pace; slag pours"), {})  # harvester
        self.assertEqual(lull_mode("The traveler's heavy cloak flaps; sand skims the dunes"), {"lull": "freeze"})

    def test_far_from_joins(self):
        from looper.stages.loop_qc import far_from_joins
        n, gap = 720, 360  # leviathan_v2: flashes at 404 / 467 / 510 are events; near the gap or the wrap they are not
        for f in (404, 467, 510):
            self.assertTrue(far_from_joins(f, n, gap), f)
        for f in (350, 370, 5, 715, 720):
            self.assertFalse(far_from_joins(f, n, gap), f)


if __name__ == "__main__":
    unittest.main()
