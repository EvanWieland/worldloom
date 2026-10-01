"""review stage: packet files, join steps, doubt line. Needs cv2/numpy (WanGP venv)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import numpy as np
    from looper.stages import review
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "needs cv2/numpy (WanGP venv)")
class TestReview(unittest.TestCase):
    def _loop(self, jump_at):
        rng = np.random.default_rng(0)
        base = rng.integers(60, 120, (48, 64, 3), np.uint8)
        frames = []
        for i in range(40):
            f = base.copy()
            f[:, i % 64] = 200  # a moving stripe: every step is a small change
            if i >= jump_at:
                f[:24] = np.clip(f[:24].astype(int) + 60, 0, 255).astype(np.uint8)  # a visible jump at jump_at
            frames.append(f)
        return frames

    def test_packet_and_doubt(self):
        from looper import loopkit
        frames = self._loop(jump_at=20)
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "loop.mp4"
            loopkit.write_video(frames, src, lossless=True)
            meta = review.run({"loop": src}, {"joins": {"closure gap": 20},
                                             "metrics": {"take drift": (6.1, 4.0), "seed": 306},
                                             "warnings": [], "title": "t"}, Path(d))
            for k in ("output", "video", "sheet"):
                self.assertTrue(Path(meta[k]).exists(), k)
            md = Path(meta["output"]).read_text(encoding="utf-8")
        self.assertIn("closure gap", meta["join_steps"])
        self.assertIn("wrap", meta["join_steps"])
        self.assertGreater(meta["join_steps"]["closure gap"], 1.8)  # the jump is at the declared join
        self.assertTrue(any("closure gap" in x for x in meta["doubt"]))
        self.assertIn("DOUBT", md)
        self.assertTrue(any("take drift 6.1 > 4.0" in x for x in meta["doubt"]))  # an over-gate metric is a doubt
        self.assertIn("| take drift | 6.1 (gate 4.0) |", md)
        self.assertIn("| seed | 306 |", md)

    def test_clean_loop_passes(self):
        from looper import loopkit
        frames = self._loop(jump_at=99)  # no jump; the wrap (stripe 39 -> 0) is a step like any other
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "loop.mp4"
            loopkit.write_video(frames, src, lossless=True)
            meta = review.run({"loop": src}, {"joins": {}, "metrics": {}, "warnings": []}, Path(d))
        self.assertEqual(meta["doubt"], [])

    def test_detail_kept_sees_a_blurred_video(self):
        import cv2
        from looper import loopkit, trace
        still = np.random.default_rng(1).integers(0, 255, (96, 128, 3), np.uint8)
        with tempfile.TemporaryDirectory() as d:
            cv2.imwrite(str(Path(d) / "still.png"), still)
            sharp = loopkit.write_video([still] * 30, Path(d) / "sharp.mp4", lossless=True)
            soft = loopkit.write_video([cv2.GaussianBlur(still, (0, 0), 2)] * 30, Path(d) / "soft.mp4", lossless=True)
            self.assertGreater(trace.detail_kept(sharp, Path(d) / "still.png")["worst"], 0.9)
            self.assertLess(trace.detail_kept(soft, Path(d) / "still.png")["worst"], 0.3)


if __name__ == "__main__":
    unittest.main()
