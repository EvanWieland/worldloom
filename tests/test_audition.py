"""Audition framing (handoff §15) and the splice tone diagnostic (amendment §8)."""
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "needs numpy/cv2 (WanGP venv)")
class TestFraming(unittest.TestCase):
    def test_cover_crop_share(self):
        from looper.stages import audition
        with tempfile.TemporaryDirectory() as d:
            self.assertIn("2.2 % of the width", audition.framing(np.zeros((704, 1280, 3), np.uint8), Path(d) / "a.jpg"))
            self.assertIn("4.3 % of the width", audition.framing(np.zeros((448, 832, 3), np.uint8), Path(d) / "b.jpg"))


@unittest.skipUnless(HAVE, "needs numpy/cv2 (WanGP venv)")
class TestSpliceTone(unittest.TestCase):
    def test_raw_gap_is_untouched_and_the_shift_is_reported(self):
        from looper.stages import splice
        rng = np.random.default_rng(0)
        long = [rng.integers(40, 60, (32, 48, 3), dtype=np.uint8) for _ in range(40)]
        gen = [rng.integers(140, 200, (32, 48, 3), dtype=np.uint8) for _ in range(30)]  # a bright generated passage
        _, toned = splice.splice(long, gen, 0, 8, 10, R=2, match_sharp=False)
        loop, raw = splice.splice(long, gen, 0, 8, 10, R=2, match_sharp=False, tone=False)
        self.assertGreater(toned["tone_shift_mean"], 50)  # the whole-frame target pulled the light down
        self.assertEqual(raw["tone_shift_mean"], 0.0)
        self.assertTrue(all((a == b).all() for a, b in zip(loop[40:], gen[8:18])))


@unittest.skipUnless(HAVE, "needs numpy/cv2 (WanGP venv)")
class TestProvenance(unittest.TestCase):
    def test_splice_map_tiles_the_loop(self):  # handoff §8: every loop frame has exactly one recorded origin
        from looper.stages import splice
        prov = splice.provenance(n=392, start=89, G=32, E=49, R=8)
        self.assertEqual([p["out"][0] for p in prov[1:]], [p["out"][1] for p in prov[:-1]])  # contiguous
        self.assertEqual((prov[0]["out"][0], prov[-1]["out"][1]), (0, 424))
        for p in prov:
            self.assertEqual(p["out"][1] - p["out"][0], p["src"][1] - p["src"][0])
        self.assertEqual(prov[-1]["kind"], "generated")


if __name__ == "__main__":
    unittest.main()
