"""Headless Textual smoke test on a recorded fixture. Skips without textual (system python)."""
import asyncio
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import textual  # noqa: F401
except ImportError:
    textual = None


def line(ts, type_, payload=None, run_id="r1", stage=None):
    return json.dumps({"ts": ts, "run_id": run_id, "stage": stage, "type": type_, "payload": payload or {}}) + "\n"


@unittest.skipIf(textual is None, "needs textual (run with WanGP's venv python)")
class TestDashboard(unittest.TestCase):
    def test_panels_render_and_keys(self):
        from looper.dashboard.app import LooperDash
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            t0 = time.time() - 60
            (root / "runs/r1").mkdir(parents=True)
            (root / "runs/r1/events.jsonl").write_text(
                line(t0 + 1, "stage.started", {"stage": "chain"}, stage="chain")
                + line(t0 + 2, "stage.progress", {"step": 1, "total_steps": 4, "sec_per_step": 40.0}, stage="chain"))
            (root / "telemetry").mkdir()
            (root / "telemetry/jobs.jsonl").write_text(
                line(t0, "run.started", {"title": "Done one"}, run_id="r0")
                + line(t0 + 5, "run.finished", {"title": "Done one", "status": "ok"}, run_id="r0"))

            async def go():
                app = LooperDash(root)
                async with app.run_test(size=(140, 44)) as pilot:
                    await pilot.pause(0.3)
                    for wid in ("#now", "#preview", "#hardware", "#history", "#models"):
                        self.assertIsNotNone(app.query_one(wid))
                    self.assertIn("chain", str(app.query_one("#now").render()))
                    await pilot.press("l"); await pilot.pause(0.1)
                    self.assertEqual(app.screen.name, "log")
                    await pilot.press("escape"); await pilot.press("h"); await pilot.pause(0.1)
                    self.assertEqual(app.screen.name, "hardware")
                    await pilot.press("escape"); await pilot.press("enter"); await pilot.pause(0.1)
                    self.assertEqual(app.screen.name, "detail")
                    await pilot.press("escape"); await pilot.press("q")
            asyncio.run(go())


@unittest.skipIf(textual is None, "needs textual (run with WanGP's venv python)")
class TestDashboardHostileData(unittest.TestCase):  # review #7, #8
    def test_markup_chars_and_truncated_preview_do_not_crash(self):
        from looper.dashboard.app import LooperDash
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            t0 = time.time() - 30
            bad_jpg = root / "runs/r1/previews/0000.jpg"
            bad_jpg.parent.mkdir(parents=True)
            bad_jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)  # JPEG header, then truncated
            (root / "runs/r1/events.jsonl").write_text(
                line(t0, "stage.started", {"stage": "chain [/b]"}, stage="chain")
                + line(t0 + 1, "render.preview", {"path": str(bad_jpg)}, stage="chain"))
            (root / "telemetry").mkdir()
            (root / "telemetry/jobs.jsonl").write_text(
                line(t0, "run.queued", {"title": "scene [/b] odd", "position": 0}, run_id="q")
                + line(t0, "run.started", {"title": "[red]x"}, run_id="f")
                + line(t0 + 2, "run.finished", {"title": "[red]x", "status": "failed", "error": "KeyError('[/i]')"}, run_id="f"))

            async def go():
                app = LooperDash(root)
                async with app.run_test(size=(140, 44)) as pilot:
                    await pilot.pause(1.5)  # at least one refresh tick + image render
                    self.assertIn("scene [/b] odd", str(app.query_one("#now").render()))
                    await pilot.press("q")
            asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
