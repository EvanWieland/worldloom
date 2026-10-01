"""Pure logic of the ADR 0007 loop path: window layout / latent alignment, length planning, closing score, the splice
structure, and the steady-light prompt rule. No GPU. Needs numpy/cv2 (WanGP venv); self-skips otherwise."""
import unittest

try:
    import numpy as np
    from looper import loopkit
    from looper.loop_pipeline import DEFAULTS, plan_lengths
    from looper.stages.splice import splice
    HAVE = True
except ImportError:  # system python without numpy/cv2
    HAVE = False
from looper.motion_style import SETTLED_STATE_CLAUSE, STEADY_LIGHT_NEG, STEADY_LIGHT_POS, settled_keyframe_prompt, steady_light


@unittest.skipUnless(HAVE, "needs numpy + cv2 (WanGP venv)")
class TestLayout(unittest.TestCase):
    def test_close_layout_matches_experiments(self):
        lay = loopkit.CloseLayout()  # 145 f, P=7, G=32: the configuration the user passed
        self.assertEqual((lay.E, lay.suffix_latent, lay.S), (49, 11, 64))
        self.assertEqual(lay.E + lay.gap_frames + lay.S, 145)

    def test_true_first_latent(self):
        self.assertEqual(loopkit.true_first_latent(481, 433), 55)   # take end context (latents 55..60)
        self.assertEqual(loopkit.true_first_latent(481, 89), 12)    # start context at frame 89
        self.assertEqual(loopkit.true_first_latent(241, 9), 2)
        with self.assertRaises(ValueError):
            loopkit.true_first_latent(481, 88)  # not the first frame of a latent group
        with self.assertRaises(ValueError):
            loopkit.true_first_latent(480, 89)  # source not 8k+1

    def test_extension_window(self):
        self.assertEqual(loopkit.extension_window(296), 345)
        self.assertEqual((loopkit.extension_window(1) - 1) % 8, 0)
        with self.assertRaises(ValueError):
            loopkit.extension_window(460)  # beyond WanGP's 501-frame LTX window

    def test_plan_lengths(self):
        p = plan_lengths({**DEFAULTS, "seconds": 30})
        self.assertEqual(p["loop_frames"], 720)
        self.assertEqual(p["extension_window"], 345)
        self.assertEqual(plan_lengths({**DEFAULTS, "seconds": 15})["extension_window"], 0)


@unittest.skipUnless(HAVE, "needs numpy + cv2 (WanGP venv)")
class TestSpliceAndScore(unittest.TestCase):
    def test_closing_score_flags_a_snap(self):
        d = np.ones(100)
        d[10] = 2.0             # natural busiest step elsewhere
        d[95] = 5.0             # snap inside the closing window (gap starts at 90)
        s = loopkit.closing_score(d, 90)
        self.assertAlmostEqual(s["closing_over_rest"], 2.5)
        d[95] = 1.5
        self.assertLess(loopkit.closing_score(d, 90)["closing_over_rest"], 1.0)

    def test_splice_structure(self):
        rng = np.random.default_rng(0)
        long = [rng.integers(0, 255, (16, 16, 3), dtype=np.uint8) for _ in range(40)]
        gen = [rng.integers(0, 255, (16, 16, 3), dtype=np.uint8) for _ in range(30)]
        loop, info = splice(long, gen, start=9, E=5, G=8, R=3, match_sharp=False)
        self.assertEqual(len(loop), (40 - 9) + 8)
        self.assertEqual(info["gap_start"], 31)
        np.testing.assert_array_equal(loop[5], long[14])  # outside both ramps: the real frame, untouched

    def test_bloom_touches_only_highlights(self):
        from looper.stages.bloom import VARIANTS, bloom
        img = np.full((96, 128, 3), 40, np.uint8)
        img[40:56, 60:76] = (30, 60, 230)  # a saturated red sun, dark in luma
        out = bloom(img, **VARIANTS["mild"])
        self.assertGreater(int(out[48, 68].max()), 230)  # the core got hotter
        self.assertGreater(int(out[48, 90].sum()), int(img[48, 90].sum()))  # a glow next to it
        np.testing.assert_array_equal(out[5, 5], img[5, 5])  # far away: untouched

    def test_tone_identity(self):
        f = np.random.default_rng(1).integers(0, 255, (32, 32, 3), dtype=np.uint8)
        self.assertLessEqual(int(np.abs(loopkit.tone(f, loopkit.cdfs(f)).astype(int) - f).max()), 1)


@unittest.skipUnless(HAVE, "needs numpy + cv2 (WanGP venv)")
class TestTakeQC(unittest.TestCase):
    def _take(self, drift, pulse=0.0):
        rng = np.random.default_rng(2)
        base = rng.integers(60, 120, (48, 64, 3)).astype(np.float32)
        frames = []
        for t in range(24 * 6):
            f = base + rng.normal(0, 2, base.shape)
            f[:16, :16] += drift * t / (24 * 6)  # one grid cell brightens over the take
            f[:16, :16] += pulse / 2 * np.sin(2 * np.pi * t / 48)  # ... or breathes with a 2 s period
            frames.append(np.clip(f, 0, 255).astype(np.uint8))
        return frames

    def test_regional_drift_rejects(self):
        from looper.stages.take_qc import stationarity
        self.assertTrue(stationarity(self._take(0.0), skip=0, camera=False)["accept"])
        r = stationarity(self._take(12.0), skip=0, camera=False)  # waterfall-like: one region +12 grey
        self.assertFalse(r["accept"])
        self.assertEqual(r["region_drift_worst"], "c00")
        self.assertLess(r["luma_drift"], 0.08)  # the global gate alone would have passed it
        self.assertGreater(r["resid_max"], 6)  # v3: a one-cell creep is regional (residual), not global exposure
        self.assertLess(r["common_range"], 2)
        self.assertEqual(r["resid_cell"], "c00")

    def test_endpoint_search_prefers_the_flat_window(self):
        from looper.stages.endpoint import rank_pairs
        rng = np.random.default_rng(3)
        base = rng.integers(60, 120, (48, 64, 3)).astype(np.float32)
        frames = []
        for t in range(481):  # one cell creeps +12 grey over the first 240 frames, then holds
            f = base + rng.normal(0, 1, base.shape)
            f[:16, :16] += 12 * min(t, 240) / 240
            frames.append(np.clip(f, 0, 255).astype(np.uint8))
        rows = rank_pairs(frames, min_frames=200, take_frames=481)
        best = rows[0]
        self.assertGreaterEqual(best["s"], 241)  # the flat second half
        self.assertLess(best["boundary"], 1.5)
        take_only = next(r for r in rows if r["s"] == 89 and r["e"] == 481)
        self.assertGreater(take_only["boundary"], 6)
        self.assertTrue(all(r["e"] % 8 == 1 and r["s"] % 8 == 1 and r["s"] >= 49 for r in rows))

    def test_shorter_cut_uses_the_endpoint_stage(self):
        import tempfile
        from pathlib import Path
        from looper.engine import Engine
        from looper.loop_pipeline import DEFAULTS, _shorter_cut
        rng = np.random.default_rng(4)
        base = rng.integers(60, 120, (48, 64, 3)).astype(np.float32)
        frames = []
        for t in range(481):
            f = base + rng.normal(0, 1, base.shape)
            f[:16, :16] += 12 * min(t, 240) / 240
            frames.append(np.clip(f, 0, 255).astype(np.uint8))
        with tempfile.TemporaryDirectory() as d:
            take = loopkit.write_video(frames, Path(d) / "take.mp4", lossless=True)
            lat = {"stage1": "l1", "stage2": "l2"}
            warnings = []
            cfg = {**DEFAULTS, "extend_attempts": 2, "min_seconds": 8}  # 17 s would only let a lone take shift 16 frames
            long_p, end_p, end_lat, s, e, e_local = _shorter_cut(Engine(Path(d) / "run", "r"), cfg, take, lat, [], warnings)
            self.assertEqual((long_p, end_p, end_lat), (take, take, lat))
            self.assertGreaterEqual(s, 241)  # the flat half, not the fixed take-only cut
            self.assertEqual(e, e_local)
            self.assertEqual(e % 8, 1)
            self.assertIn("loop cut to", warnings[0])

    def test_boundary_is_phase_invariant(self):
        from looper.stages.take_qc import boundary, trend_pulse
        t = np.arange(20) + 0.5
        b = [boundary(list(100 + 4 * np.sin(2 * np.pi * t / 20 + ph))) for ph in (0, np.pi / 2, np.pi)]
        tr = [trend_pulse(list(100 + 4 * np.sin(2 * np.pi * t / 20 + ph)))[0] for ph in (0, np.pi / 2, np.pi)]
        self.assertLess(max(b), 3)  # the same cycle at any phase: nothing to bridge
        self.assertGreater(max(tr) - min(tr), 5)  # the fitted trend swings with the phase (the v2 defect)
        self.assertAlmostEqual(boundary(list(100 + np.linspace(0, 6, 20))), 5.68, places=1)

    def test_pulse_passes_until_capped(self):
        from looper.stages.take_qc import REGION_PULSE_MAX, stationarity
        r = stationarity(self._take(0.0, pulse=8.0), skip=0, camera=False)  # fireplace-like breathing: not a trend
        self.assertTrue(r["accept"], r)
        self.assertLess(r["region_drift_max"], 4.0)
        r = stationarity(self._take(0.0, pulse=4 * REGION_PULSE_MAX), skip=0, camera=False)  # a sun flare coming and going
        self.assertFalse(r["accept"])
        self.assertEqual(r["region_pulse_worst"], "c00")

    def test_moving_light_judges_the_floor(self):
        """v4: pulses on a steady floor, ending in a trough, pass with a declared moving light; a floor step fails."""
        from looper.stages.take_qc import stationarity
        rng = np.random.default_rng(5)
        base = rng.integers(60, 100, (48, 64, 3)).astype(np.float32)

        def take(step):
            frames = []
            for t in range(24 * 20):
                f = base + rng.normal(0, 1, base.shape)
                if t % 96 < 24 and t < 24 * 13:  # a 1 s flare every 4 s; the last 7 s are between flares
                    f[:16, :16] += 30  # pulse metric ~9, like the leviathan take (9.3)
                f[:16, :16] += step * (t > 240)
                frames.append(np.clip(f, 0, 255).astype(np.uint8))
            return frames
        pulsing = take(0)
        self.assertGreater(stationarity(pulsing, skip=48, camera=False, average_s=5)["region_drift_mean_boundary"]["c00"], 4)
        self.assertTrue(stationarity(pulsing, skip=48, camera=False, average_s=5)["accept"])
        self.assertFalse(stationarity(take(12), skip=48, camera=False, average_s=5)["accept"])


class TestSteadyLight(unittest.TestCase):
    def test_appends_once(self):
        p, n = steady_light("A cabin at night.", "text, watermark")
        self.assertIn(STEADY_LIGHT_POS, p)
        self.assertTrue(n.endswith(STEADY_LIGHT_NEG))
        self.assertEqual(steady_light(p, n), (p, n))


    def test_settled_keyframe_rule_appends_once(self):
        p = settled_keyframe_prompt("A neon alley with a steaming vent.")
        self.assertTrue(p.endswith(SETTLED_STATE_CLAUSE))
        self.assertEqual(settled_keyframe_prompt(p), p)


if __name__ == "__main__":
    unittest.main()
