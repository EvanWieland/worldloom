"""looper/periodic.py on synthetic sequences (software tests, not evidence of generation quality)."""
import math
import unittest

try:
    import cv2
    import numpy as np
    HAVE = True
except ImportError:
    HAVE = False
try:
    from looper import periodic
except ImportError as e:  # system Python: no numpy / cv2 / torch -- the whole module needs the WanGP venv
    raise unittest.SkipTest(f"needs the WanGP venv ({e})")


class TestTiming(unittest.TestCase):
    def test_phase_times_have_no_terminal_duplicate(self):
        t = periodic.phase_times(30.0)
        self.assertEqual((len(t), t[0]), (720, 0.0))
        self.assertLess(t[-1], 30.0)

    def test_turns_and_compatible_duration(self):
        self.assertEqual(periodic.turns(30.0, 10.0), 3)
        self.assertIsNone(periodic.turns(30.0, 7.0))
        self.assertEqual(periodic.compatible_duration([10.0, 6.0]), 30.0)
        self.assertEqual(periodic.compatible_duration([7.0]), 35.0)
        self.assertIsNone(periodic.compatible_duration([7.0, 11.0]))  # 77 s > 60: surfaced, not silently fixed


def frames_for(angles, w=160, h=96, c=(80, 40)):
    out = []
    for a in angles:
        f = np.zeros((h, w, 3), np.uint8)
        end = (int(c[0] + 90 * math.cos(math.radians(a))), int(c[1] - 90 * math.sin(math.radians(a))))
        cv2.line(f, c, end, (255, 255, 255), 3)
        cv2.circle(f, c, 4, (255, 255, 255), -1)
        out.append(f)
    return out


@unittest.skipUnless(HAVE, "needs cv2 (WanGP venv)")
class TestBeamTrack(unittest.TestCase):
    def test_steady_rotation_closes_cleanly(self):
        ang = [i * 6.0 for i in range(120)]  # 2 whole turns, 6 deg per frame: the wrap continues the sweep
        rep = periodic.phase_report(periodic.beam_track(frames_for(ang)), {"closure gap": 60})
        self.assertAlmostEqual(abs(rep["net_turns"]), 2.0, delta=0.1)
        self.assertGreater(rep["one_way"], 0.95)
        self.assertEqual(periodic.doubts(rep), [])

    def test_reversal_and_pause_at_a_join_are_flagged(self):
        ang = [i * 6.0 for i in range(60)] + [354.0 - i * 6.0 for i in range(12)] + [(i + 48) * 6.0 for i in range(48)]
        rep = periodic.phase_report(periodic.beam_track(frames_for(ang)), {"closure gap": 66})
        self.assertIn("beam reverses at the closure gap", periodic.doubts(rep))
        still = [i * 6.0 for i in range(60)] + [360.0] * 12 + [(i + 60) * 6.0 for i in range(48)]
        rep = periodic.phase_report(periodic.beam_track(frames_for(still)), {"closure gap": 66})
        self.assertTrue(any("speed" in d for d in periodic.doubts(rep)), rep["joins"])


if __name__ == "__main__":
    unittest.main()
