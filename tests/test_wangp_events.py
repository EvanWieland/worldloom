"""WanGP progress/preview callbacks -> events + preview JPEGs. No GPU; WanGP objects are faked."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from PIL import Image
except ImportError:
    Image = None
from looper import events


@unittest.skipIf(Image is None, "needs PIL (run with WanGP's venv python)")
class TestBridge(unittest.TestCase):
    def setUp(self):
        from looper.adapters.wangp import WanGPEventBridge
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.ev = self.run_dir / "events.jsonl"
        events.set_current(self.ev, "r", "chain")
        self.t = [1000.0]
        self.bridge = WanGPEventBridge(clock=lambda: self.t[0])

    def tearDown(self):
        events.set_current(None)
        self._tmp.cleanup()

    def recs(self):
        return [json.loads(l) for l in self.ev.read_text().splitlines()]

    def prog(self, step, status="Sliding Window 2/3, Denoising"):
        return SimpleNamespace(phase="Denoising", status=status, progress=50, current_step=step, total_steps=4)

    def test_progress_event_with_window_and_sec_per_step(self):
        self.bridge.on_progress(self.prog(1))
        self.t[0] += 40.0
        self.bridge.on_progress(self.prog(2))
        p = self.recs()[-1]["payload"]
        self.assertEqual((p["step"], p["total_steps"], p["window"], p["total_windows"]), (2, 4, 2, 3))
        self.assertAlmostEqual(p["sec_per_step"], 40.0)

    def test_preview_throttle_and_prune(self):
        img = Image.new("RGB", (832, 480), "red")
        for i in range(30):
            self.t[0] += 6.0  # > PREVIEW_MIN_INTERVAL_S, so each is saved
            self.bridge.on_preview(SimpleNamespace(image=img, phase="", status="", progress=0, current_step=i, total_steps=30))
        self.t[0] += 1.0  # within the interval -> dropped
        self.bridge.on_preview(SimpleNamespace(image=img, phase="", status="", progress=0, current_step=31, total_steps=30))
        files = sorted((self.run_dir / "previews").glob("*.jpg"))
        self.assertEqual(len(files), 20)
        with Image.open(files[-1]) as im:
            self.assertLessEqual(im.width, 480)
        prev = [r for r in self.recs() if r["type"] == "render.preview"]
        self.assertEqual(len(prev), 30)
        self.assertTrue(Path(prev[-1]["payload"]["path"]).exists())

    def test_second_bridge_continues_numbering(self):  # review #3
        from looper.adapters.wangp import WanGPEventBridge
        img = Image.new("RGB", (100, 60), "blue")
        for i in range(25):
            self.t[0] += 6.0
            self.bridge.on_preview(SimpleNamespace(image=img, current_step=i))
        second = WanGPEventBridge(clock=lambda: self.t[0])
        self.t[0] += 6.0
        second.on_preview(SimpleNamespace(image=img, current_step=0))
        last = [r for r in self.recs() if r["type"] == "render.preview"][-1]["payload"]["path"]
        self.assertTrue(Path(last).exists(), "new call's preview must survive pruning")
        self.assertEqual(Path(last).name, "0025.jpg")

    def test_preview_written_atomically(self):  # review #8
        img = Image.new("RGB", (100, 60), "green")
        self.t[0] += 6.0
        self.bridge.on_preview(SimpleNamespace(image=img, current_step=1))
        pdir = self.run_dir / "previews"
        self.assertEqual([p.suffix for p in pdir.iterdir()], [".jpg"])  # no temp file left behind
        with Image.open(next(pdir.iterdir())) as im:
            im.load()  # complete, decodable

    def test_phase_wall_time_is_accumulated(self):  # handoff §12
        for t, phase in [(0, "loading_model"), (20, "encoding_text"), (25, "inference"), (85, "inference"),
                         (145, "decoding")]:
            self.t[0] = t
            self.bridge.on_progress(SimpleNamespace(phase=phase, status="", progress=0, current_step=None, total_steps=8))
        self.t[0] = 175
        self.assertEqual(self.bridge.close(), {"loading_model": 20, "encoding_text": 5, "inference": 120, "decoding": 30})

    def test_progress_callback_never_raises(self):  # review #10
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError("bad update object")
        self.bridge.on_progress(Hostile())  # must not propagate into WanGP's render worker

    def test_filmstrip_preview_is_cropped_to_last_tile(self):  # found live on LTX: preview = frames side by side
        strip = Image.new("RGB", (6 * 160, 90), "black")
        strip.paste(Image.new("RGB", (160, 90), "white"), (5 * 160, 0))  # newest tile on the right
        self.t[0] += 6.0
        self.bridge.on_preview(SimpleNamespace(image=strip, current_step=1))
        path = [r for r in self.recs() if r["type"] == "render.preview"][-1]["payload"]["path"]
        with Image.open(path) as im:
            self.assertLess(im.width / im.height, 2.5)  # a single frame, not a strip
            self.assertGreater(sum(im.convert("L").resize((1, 1)).getdata()), 200)  # the white (last) tile

    def test_no_context_is_silent(self):
        events.set_current(None)
        self.bridge.on_progress(self.prog(1))
        self.assertFalse(self.ev.exists())


if __name__ == "__main__":
    unittest.main()
