import unittest

try:
    from looper.stages import grow
except ImportError as e:  # system Python: no numpy / cv2 / torch -- the whole module needs the WanGP venv
    raise unittest.SkipTest(f"needs the WanGP venv ({e})")


class Plan(unittest.TestCase):
    def test_take_only_loop_cuts_mid_take(self):  # rain_loop_e2e shape: 17.7 s take-only loop -> 30 s
        p = grow.plan(424, 720, 89, 481, 481, has_ext=False)
        self.assertEqual((p["e"], p["s"], p["G"]), (281, 313, 328))
        self.assertEqual(p["end"], ("take", 281))
        self.assertEqual(p["start"], ("take", 313))

    def test_cut_inside_the_extension_uses_window_frames(self):  # the pine7 17 s cut (401-777) -> 30 s
        p = grow.plan(408, 720, 401, 777, 481, has_ext=True)
        self.assertEqual(p["G"], 344)
        self.assertEqual(p["e"] % 8, 1)
        kind, le = p["end"]
        self.assertEqual((kind, le), ("ext", p["e"] - 432))
        self.assertGreaterEqual(le, 57)
        self.assertEqual(p["start"], ("ext", p["s"] - 432))
        self.assertGreaterEqual(p["e"] - 49, 401 + 8)
        self.assertLessEqual(p["s"] + 64, 777 - 8)

    def test_long_enough_or_no_room(self):
        self.assertIsNone(grow.plan(710, 720, 89, 481, 481, has_ext=False))  # < 1 s short
        self.assertIsNone(grow.plan(150, 720, 89, 200, 481, has_ext=False))  # segment too short for both contexts

    def test_gap_capped_by_the_ltx_window(self):
        self.assertEqual(grow.plan(200, 1440, 89, 481, 481, has_ext=False)["G"], grow.MAX_GAP)

    def test_no_straddling_start_context(self):  # start context may not cross the take/window boundary
        p = grow.plan(408, 720, 97, 777, 481, has_ext=True)
        s = p["s"]
        self.assertTrue(s + 64 <= 481 or s >= 481)

    def test_rotate(self):
        loop = list(range(100))  # segment 0..67 (long 10..77) + 32-frame closure
        rot = grow.rotate(loop, 10, 40, 72)
        self.assertEqual(rot[0], 62)  # long frame 72
        self.assertEqual(rot[-1], 29)  # long frame 39 = e - 1
        self.assertEqual(len(rot), 100 - 32)


if __name__ == "__main__":
    unittest.main()
