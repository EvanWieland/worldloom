"""looper.events: the one writer every producer uses. stdlib only."""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import events
from looper.engine import Engine


class TestEmit(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        events.set_current(None)
        os.environ.pop("LOOPER_EVENTS", None)

    def tearDown(self):
        events.set_current(None)
        self._tmp.cleanup()

    def read(self, p):
        return [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines()]

    def test_writes_record_shape(self):
        p = self.dir / "e.jsonl"
        events.emit(p, "stage.progress", {"step": 1}, run_id="r", stage="chain")
        (rec,) = self.read(p)
        self.assertEqual(set(rec), {"ts", "run_id", "stage", "type", "payload"})
        self.assertEqual((rec["run_id"], rec["stage"], rec["type"]), ("r", "chain", "stage.progress"))

    def test_creates_parent_dirs(self):
        p = self.dir / "a" / "b" / "e.jsonl"
        events.emit(p, "x", {})
        self.assertTrue(p.exists())

    def test_redacts_secrets(self):
        p = self.dir / "e.jsonl"
        events.emit(p, "x", {"api_key": "sk-123"})
        self.assertEqual(self.read(p)[0]["payload"]["api_key"], "<redacted>")

    def test_never_raises_on_unwritable_path(self):
        bad = self.dir / "file_not_dir"
        bad.write_text("x")
        events.emit(bad / "e.jsonl", "x", {})  # parent is a file -> write fails; must not raise

    def test_concurrent_threads_no_interleave(self):
        p = self.dir / "e.jsonl"
        payload = {"blob": "y" * 5000}
        ts = [threading.Thread(target=lambda: [events.emit(p, "x", payload) for _ in range(50)]) for _ in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        recs = self.read(p)  # json.loads fails on any interleaved line
        self.assertEqual(len(recs), 200)

    def test_current_context_and_env_fallback(self):
        p = self.dir / "e.jsonl"
        self.assertIsNone(events.current())
        events.emit_current("x", {})  # no context -> no-op
        self.assertFalse(p.exists())
        os.environ["LOOPER_EVENTS"] = f"{p}|envrun|chain"
        self.assertEqual(events.current(), (p, "envrun", "chain"))
        events.set_current(p, "memrun", "vace")  # explicit context wins over env
        events.emit_current("x", {"a": 1})
        self.assertEqual(self.read(p)[0]["run_id"], "memrun")
        os.environ.pop("LOOPER_EVENTS")


class TestEngineFinish(unittest.TestCase):  # review #1
    def test_finish_emits_run_finished(self):
        with tempfile.TemporaryDirectory() as d:
            eng = Engine(Path(d) / "run", run_id="t")
            eng.finish("failed", error="boom")
            last = json.loads(eng.events_path.read_text().splitlines()[-1])
            self.assertEqual((last["type"], last["payload"]["status"], last["payload"]["error"]), ("run.finished", "failed", "boom"))


class TestEngineUsesEmitter(unittest.TestCase):
    def test_run_stage_sets_and_clears_current(self):
        with tempfile.TemporaryDirectory() as d:
            eng = Engine(Path(d) / "run", run_id="t")
            seen = {}

            def fn(inputs, config, out_dir):
                seen["ctx"] = events.current()
                events.emit_current("stage.progress", {"step": 1})
                return {}

            eng.run_stage("chain", 1, {}, {}, fn)
            self.assertEqual(seen["ctx"], (eng.events_path, "t", "chain"))
            self.assertIsNone(events.current())
            types = [json.loads(l)["type"] for l in eng.events_path.read_text().splitlines()]
            self.assertEqual(types, ["run.started", "stage.started", "stage.progress", "stage.ok"])


if __name__ == "__main__":
    unittest.main()
