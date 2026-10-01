import unittest

try:
    import cv2  # noqa: F401
    import numpy as np
    from looper import loopkit
except ImportError:  # system Python: no cv2/numpy
    loopkit = None


@unittest.skipIf(loopkit is None, "needs cv2/numpy (WanGP venv)")
class GapChurn(unittest.TestCase):
    def texture(self, seed):
        g = np.random.default_rng(seed).integers(0, 255, (60, 80), dtype=np.uint8)
        g = cv2.resize(cv2.GaussianBlur(g, (0, 0), 2), (320, 240), interpolation=cv2.INTER_CUBIC)
        return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

    def moving(self, n, base):  # one texture translating 1 px/frame: transport explains every change
        return [np.roll(base, i, axis=1) for i in range(n)]

    def test_transport_only_scores_about_one(self):
        w = self.moving(30, self.texture(0))
        self.assertLess(loopkit.gap_churn(w, 10, 8)["gap_churn"], 1.3)

    def test_redrawn_gap_scores_high(self):
        w = self.moving(30, self.texture(0))
        for k in range(10, 19):  # the gap re-synthesises the texture every frame
            w[k] = self.texture(100 + k)
        self.assertGreater(loopkit.gap_churn(w, 10, 8)["gap_churn"], 1.5)



@unittest.skipIf(loopkit is None, "needs cv2/numpy (WanGP venv)")
class LoopDrift(unittest.TestCase):
    def test_a_passing_shadow_is_measured_in_its_region(self):
        frames = [np.full((96, 128, 3), 100, np.uint8) for _ in range(24 * 10)]
        for i in range(24 * 4, 24 * 7):  # one region darkens by 12 grey for 3 s
            frames[i] = frames[i].copy()
            frames[i][:32, :32] = 88
        d = loopkit.loop_drift(frames)
        self.assertAlmostEqual(d["loop_drift"], 12.0, places=1)
        self.assertEqual(d["loop_drift_cell"], "c00")

    def test_steady_loop_scores_zero(self):
        self.assertEqual(loopkit.loop_drift([np.full((96, 128, 3), 50, np.uint8)] * 48)["loop_drift"], 0.0)


if __name__ == "__main__":
    unittest.main()
