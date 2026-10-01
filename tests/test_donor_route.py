"""The motion donor route end to end on the CPU (ADR 0016): the three GPU stages (take, close, donor) are replaced by
fakes that write small synthetic videos; every CPU stage between them runs for real (fit, fit_guide with the retime,
take_qc, the cut, donor_start, return_guide, splice, loop_qc, deliver, review). Catches wiring errors before a
3-hour run. Needs cv2 / numpy / PIL / ffmpeg (WanGP venv)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    import cv2
    import numpy as np
    from looper import loop_pipeline, loopkit
    from looper.stages import close, donor, loop_qc, take
except ImportError:  # system Python
    loop_pipeline = None

W, H = 256, 144          # loop size (--resolution)
DW, DH = 320, 180        # the donor's own render size (Hunyuan picks its size from the still)
BG = None


def _frame(x: float, w: int = W, h: int = H) -> "np.ndarray":
    """A textured static scene (the camera anchor) with a small dark 'cloak' blob at x (fraction of the width)."""
    global BG
    if BG is None or BG.shape[:2] != (h, w):  # sharp-cornered blocks: take_qc's ORB camera check needs real corners
        rng = np.random.default_rng(7)
        BG = cv2.resize(rng.integers(40, 220, (h // 8, w // 8, 3), np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)
    f = BG.copy()
    cv2.circle(f, (int(w * x), int(h * 0.7)), max(3, h // 20), (20, 20, 20), -1)
    # render-like grain: a perfectly still background ties regional_qc's activity percentile at zero (empty static mask)
    grain = np.random.default_rng(int(x * 1e6)).integers(-3, 4, f.shape, np.int16)
    return np.clip(f.astype(np.int16) + grain, 0, 255).astype(np.uint8)


def _x(t: float) -> float:
    return 0.25 + 0.05 * np.sin(2 * np.pi * t / 48)  # a 2 s sway


@unittest.skipIf(loop_pipeline is None, "needs cv2/numpy/PIL (WanGP venv)")
class DonorRoute(unittest.TestCase):
    def test_donor_route_runs_take_and_return_with_guides_and_skips_grow(self):
        seen = {}

        def fake_donor(inputs, config, out_dir, *, scratch_dir):
            n = config["frames"]
            path = Path(out_dir) / "donor.mp4"
            # every seed / start image is its own render (identical fakes would share one cached hold verdict)
            shift = (config["seed"] - 306) * 3 + (7 if Path(inputs["image"]).name == "start.png" else 0)
            loopkit.write_video([_frame(_x(i) + shift, DW, DH) for i in range(n)], path, crf=10)
            seen.setdefault("donor_frames", []).append(n)
            seen.setdefault("donor_seeds", []).append(config["seed"])
            return {"output": str(path), "frames": n, "settings": {"seed": config["seed"]}}

        def fake_hold(inputs, config, out_dir):  # the take's first donor walks off; every later donor holds
            walks = len(seen.setdefault("holds", [])) == 0
            seen["holds"].append(walks)
            return {"travels": walks, "net_px": 40.0 if walks else 1.0, "span_px": 45.0 if walks else 2.0, "found": 13}

        def fake_take(inputs, config, out_dir, *, scratch_dir):
            g = inputs.get("guide")
            seen["take_guide_frames"] = int(cv2.VideoCapture(str(g)).get(cv2.CAP_PROP_FRAME_COUNT)) if g else None
            path = Path(out_dir) / "take.mp4"
            loopkit.write_video([_frame(_x(i)) for i in range(config["frames"])], path, crf=10)
            lat = Path(out_dir) / "lat_stage2.pt"
            lat.write_bytes(b"fake")
            return {"output": str(path), "latents": {"stage1": str(lat), "stage2": str(lat)},
                    "settings": {"seed": config["seed"]}, "frames": config["frames"]}

        def fake_close(inputs, config, out_dir, *, scratch_dir):
            lay = loopkit.CloseLayout(config["frames"], config["prefix_latents"], config["gap_frames"])
            g = inputs.get("guide")
            seen["close"] = {"guide_frames": int(cv2.VideoCapture(str(g)).get(cv2.CAP_PROP_FRAME_COUNT)) if g else None,
                             "window": lay.frames, "gap": lay.gap_frames}
            e, s0, E, G = config["end_frame"], config["start_frame"], lay.E, lay.gap_frames
            # a generated return that keeps swaying (~real speed) and lands on the loop start's phase (period 48)
            span = G + (s0 - e - G) % 48
            gap = [_frame(_x(e + k * span / G)) for k in range(G)]
            frames = [_frame(_x(t)) for t in range(e - E, e)] + gap + [_frame(_x(t)) for t in range(s0, s0 + lay.S)]
            path = Path(out_dir) / "window.mp4"
            loopkit.write_video(frames, path, crf=10)
            return {"output": str(path), "layout": {"E": E, "G": G, "S": lay.S}}

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            still = d / "still.png"
            cv2.imwrite(str(still), _frame(_x(0), 512, 288))
            # explicit QC regions (the pipeline's --scene): auto regions + their 25 px dilation leave no static 32 px
            # tile on a frame this small (real 832x448 frames have plenty)
            scene = d / "scene.json"
            scene.write_text(json.dumps({"regions": {"cloak": [[int(W * 0.15), int(H * 0.55), int(W * 0.35), H]]}}))
            prep = {"image": still, "prompt": "a cloak sways", "negative": "blur", "warnings": [], "contract": None}
            cfg = {"motion_donor": True, "donor_speed": 0.6, "resolution": f"{W}x{H}", "close_seeds": [306],
                   "fallback_drift_max": 50.0}
            real_qc = loop_qc.run

            def qc_accepts(inputs, config, out_dir):  # the real QC runs; its verdict on a synthetic loop is not the test
                return {**real_qc(inputs, config, out_dir), "accept": True, "fails": []}

            with mock.patch("looper.front.prepare", return_value=prep), \
                    mock.patch.object(take, "run", fake_take), mock.patch.object(close, "run", fake_close), \
                    mock.patch.object(donor, "run", fake_donor), mock.patch.object(donor, "hold_run", fake_hold), \
                    mock.patch.object(loop_qc, "run", qc_accepts):
                result = loop_pipeline.run_loop(still, "a cloak sways", cfg, d / "run", "donor_route", scene=scene)
            stages = json.loads((d / "run" / "manifest.json").read_text(encoding="utf-8"))["stages"]
            review_md = Path(result["review"]).read_text(encoding="utf-8")
            final_exists = Path(result["final_video"]).exists()

        for key in ("donor[take]", "fit_guide", "take[0]", "donor_start", "donor[return]", "fit_guide[return]",
                    "return_guide", "close[306]", "splice[306]", "loop_qc[306]"):
            self.assertIn(key, stages)
        self.assertNotIn("take[settle]", stages)  # a guided take starts from the still itself
        self.assertNotIn("close[grow]", stages)  # an unguided interior bridge would freeze the donor's motion
        self.assertEqual(seen["donor_frames"][0], donor.frames_for(481, 0.6))  # the take's donor at 0.6x
        # a donor whose subject travels is re-rolled before any take is spent (sample_2 seed 306 stepped, spice walked)
        self.assertEqual(seen["donor_seeds"][:2], [306, 307])
        self.assertEqual(seen["holds"], [True, False, False])  # take donor x2, then the return's continuation
        self.assertIn("donor_hold[take_1]", stages)
        self.assertEqual(seen["take_guide_frames"], 481)  # retimed + trimmed to the take
        c = seen["close"]
        self.assertEqual(c["guide_frames"], c["window"])  # the return guide covers the whole return window
        self.assertTrue(c["gap"] % 8 == 0 and 32 <= c["gap"] <= loop_pipeline.MAX_GAP)
        self.assertTrue(final_exists)
        self.assertIn("motion donor (speed, return gap, wrap distance)", review_md)


if __name__ == "__main__":
    unittest.main()
