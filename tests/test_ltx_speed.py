import unittest

try:
    import torch
except ImportError:  # system Python: no torch
    torch = None

try:
    from looper.adapters import ltx
except ImportError as e:  # system Python: no numpy / cv2 / torch -- the whole module needs the WanGP venv
    raise unittest.SkipTest(f"needs the WanGP venv ({e})")


@unittest.skipIf(torch is None, "needs torch (WanGP venv)")
class MotionClock(unittest.TestCase):
    def setUp(self):
        self.p = torch.rand(1, 3, 10, 2) * 5  # (batch, [t, h, w], tokens, [start, end))

    def test_speed_one_is_identity(self):
        self.assertIs(ltx.scale_motion_clock(self.p, 1.0), self.p)

    def test_half_speed_halves_time_only(self):
        q = ltx.scale_motion_clock(self.p, 0.5)
        self.assertTrue(torch.allclose(q[:, 0], self.p[:, 0] * 0.5))
        self.assertTrue(torch.equal(q[:, 1:], self.p[:, 1:]))
        self.assertFalse(q is self.p)

    def test_rejects_out_of_range(self):
        for s in (0.0, -1.0, 1.5):
            with self.assertRaises(ValueError):
                ltx.scale_motion_clock(self.p, s)


if __name__ == "__main__":
    unittest.main()
