"""looper.observe: stdlib-only reader. Fixtures are written by hand -- no GPU, no Ollama."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import observe


def line(ts, type_, payload=None, run_id="r1", stage=None):
    return json.dumps({"ts": ts, "run_id": run_id, "stage": stage, "type": type_, "payload": payload or {}}) + "\n"


class TestTailer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "e.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_incremental_and_truncated_line(self):
        t = observe.Tailer()
        self.p.write_text(line(1, "a") + line(2, "b")[:10], encoding="utf-8")
        self.assertEqual([r["type"] for r in t.read_new(self.p)], ["a"])
        with open(self.p, "a", encoding="utf-8") as f:
            f.write(line(2, "b")[10:] + line(3, "c"))
        self.assertEqual([r["type"] for r in t.read_new(self.p)], ["b", "c"])
        self.assertEqual(t.read_new(self.p), [])

    def test_corrupt_line_counted_not_raised(self):
        t = observe.Tailer()
        self.p.write_text("not json\n" + line(1, "a"), encoding="utf-8")
        self.assertEqual([r["type"] for r in t.read_new(self.p)], ["a"])
        self.assertEqual(t.bad_lines, 1)

    def test_missing_file_is_empty(self):
        self.assertEqual(observe.Tailer().read_new(self.p), [])

    def test_reader_does_not_block_writer(self):
        t = observe.Tailer()
        with open(self.p, "a", encoding="utf-8") as w:  # writer keeps its handle open (like a live producer)
            w.write(line(1, "a")); w.flush()
            self.assertEqual(len(t.read_new(self.p)), 1)
            w.write(line(2, "b")); w.flush()  # must still be writable after the reader polled
        self.assertEqual(len(t.read_new(self.p)), 1)


class TestObserver(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.now = [10_000.0]
        self.obs = observe.Observer(self.root, clock=lambda: self.now[0])

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(text)

    def test_empty_root(self):
        s = self.obs.poll()
        self.assertIsNone(s.now)
        self.assertEqual((s.queue, s.history), ([], []))
        self.assertFalse(s.hw.sampler_alive)
        self.assertIn("hardware sampler not running", " ".join(s.warnings))
        json.dumps(s.to_dict())  # serialisable

    def test_active_run_progress_eta_preview(self):
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(9_000, "run.started") + line(9_000, "stage.started", {"stage": "chain"}, stage="chain")
                   + line(9_900, "stage.progress", {"step": 2, "total_steps": 4, "window": 1, "total_windows": 2,
                                                    "sec_per_step": 60.0, "phase": "Denoising"}, stage="chain")
                   + line(9_950, "render.preview", {"path": "p.jpg"}, stage="chain"))
        n = self.obs.poll().now
        self.assertEqual((n.run_id, n.stage, n.step, n.window), ("r1", "chain", 2, 1))
        # remaining: 2 steps of window 1 + 4 steps of window 2 = 6 steps * 60 s
        self.assertAlmostEqual(n.eta_s, 360.0)
        self.assertEqual(n.preview_path, "p.jpg")
        self.assertFalse(n.stalled)
        self.now[0] = 9_950 + observe.STALL_S + 1
        self.assertTrue(self.obs.poll().now.stalled)

    def test_plan_eta_from_typical_stage_durations_and_announced_keyframe(self):
        # an earlier run finished its stages: take 700 s, close 240 s
        self.write("runs/old/events.jsonl",
                   line(1, "stage.ok", {"stage": "take", "key": "take[0]", "duration_s": 700.0}, run_id="old")
                   + line(2, "stage.ok", {"stage": "close", "key": "close[306]", "duration_s": 240.0}, run_id="old")
                   + line(3, "run.finished", {"status": "ok"}, run_id="old"))
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(9_000, "run.started")
                   + line(9_000, "run.plan", {"stages": ["take[0]", "close[306]", "close[307]"], "keyframe": "kf.png"})
                   + line(9_000, "stage.started", {"stage": "take", "key": "take[0]"}, stage="take")
                   # a fast text-encoding progress bar: the per-bar fallback would say 24 * 0.2 s = 5 s
                   + line(9_100, "stage.progress", {"step": 24, "total_steps": 48, "sec_per_step": 0.2}, stage="take"))
        self.now[0] = 9_100
        n = self.obs.poll().now
        # take: 700 - 100 elapsed = 600, + two closes at 240 = 1080 s
        self.assertAlmostEqual(n.eta_s, 1080.0)
        self.assertEqual(n.keyframe_path, "kf.png")

    def test_token_log_llm_stream_and_video_rate(self):
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(10, "run.started")
                   + line(11, "model.request", {"model": "qwen3:8b", "task": "interpret", "prompt": "A rainy cabin"})
                   + line(12, "model.stream", {"model": "qwen3:8b", "output_tokens_so_far": 3, "text": "{\"scene\""})
                   + line(13, "model.stream", {"model": "qwen3:8b", "output_tokens_so_far": 6, "text": ": \"cabin\"}"})
                   + line(14, "model.response", {"model": "qwen3:8b", "input_tokens": 40, "output_tokens": 6,
                                                  "tokens_per_s": 30.0, "latency_s": 0.4})
                   + line(20, "stage.started", {"stage": "take", "key": "take[0]"}, stage="take")
                   + line(21, "model.tokens", {"model": "ltx", "video_tokens": 30000, "generated_tokens": 28000,
                                                "context_tokens": 0, "control_tokens": 2000, "latent_frames": 61,
                                                "latent_hw": [7, 13]}, stage="take")
                   + line(30, "stage.progress", {"step": 3, "total_steps": 8, "sec_per_step": 10.0}, stage="take"))
        self.now[0] = 30
        s = self.obs.poll()
        self.assertEqual(s.tokens[0], "▶ qwen3:8b · interpret: A rainy cabin")
        self.assertEqual(s.tokens[1], "◀ qwen3:8b: {\"scene\": \"cabin\"}")  # stream deltas merged into one line
        self.assertTrue(s.tokens[2].startswith("✓ qwen3:8b: in 40 · out 6 tok"))
        self.assertIn("30,000 tokens per step", s.tokens[3])
        self.assertIn("3,000 video tok/s", s.tokens_live)
        json.dumps(s.to_dict())

    def test_queue_and_history_from_jobs_file(self):
        self.write("telemetry/jobs.jsonl",
                   line(1, "run.queued", {"title": "A", "position": 0}, run_id="a")
                   + line(2, "run.queued", {"title": "B", "position": 1}, run_id="b")
                   + line(3, "run.started", {"title": "A"}, run_id="a")
                   + line(50, "run.finished", {"title": "A", "status": "ok", "results": {"joins": [2.0, 3.0]}}, run_id="a")
                   + line(60, "run.started", {"title": "B"}, run_id="b")
                   + line(70, "run.finished", {"title": "B", "status": "failed", "error": "rc=1"}, run_id="b"))
        s = self.obs.poll()
        self.assertEqual(s.queue, [])
        self.assertEqual([(h.run_id, h.status) for h in s.history], [("b", "failed"), ("a", "ok")])  # newest first
        self.assertEqual(s.history[1].duration_s, 47.0)
        self.assertEqual(s.history[0].error, "rc=1")

    def test_newer_run_supersedes_stalled(self):
        # old: stalled (1000 s silent) but not yet abandoned; new: started later
        self.write("runs/old/events.jsonl", line(9_000, "stage.started", {"stage": "chain"}, run_id="old", stage="chain"))
        self.write("runs/new/events.jsonl", line(9_900, "stage.started", {"stage": "vace"}, run_id="new", stage="vace"))
        self.assertEqual(self.obs.poll().now.run_id, "new")

    def test_long_dead_run_moves_to_history_as_abandoned(self):
        self.write("runs/dead/events.jsonl", line(100, "stage.started", {"stage": "interpret"}, run_id="dead", stage="interpret"))
        self.now[0] = 100 + observe.ABANDON_S + 1
        s = self.obs.poll()
        self.assertIsNone(s.now)
        self.assertEqual([(h.run_id, h.status) for h in s.history], [("dead", "abandoned")])

    def test_abandoned_run_revives_on_new_event(self):
        ev = "runs/slow/events.jsonl"
        self.write(ev, line(100, "stage.started", {"stage": "bridge"}, run_id="slow", stage="bridge"))
        self.now[0] = 100 + observe.ABANDON_S + 1
        self.obs.poll()
        self.write(ev, line(self.now[0], "stage.progress", {"step": 2, "total_steps": 30}, run_id="slow", stage="bridge"))
        s = self.obs.poll()
        self.assertEqual(s.now.run_id, "slow")
        self.assertEqual(s.history, [])

    # -- review fixes -------------------------------------------------------
    def test_engine_run_without_run_finished_reaches_history(self):  # review #1
        ev = "runs/eng/events.jsonl"
        self.write(ev, line(9_000, "run.started", run_id="eng")
                   + line(9_001, "stage.started", {"stage": "plan"}, run_id="eng", stage="plan")
                   + line(9_002, "stage.ok", {"stage": "plan", "duration_s": 1.0}, run_id="eng", stage="plan"))
        self.now[0] = 9_002 + observe.STALL_S + 1
        s = self.obs.poll()
        self.assertEqual([(h.run_id, h.status) for h in s.history], [("eng", "idle")])

    def test_explicit_run_finished_from_engine(self):  # review #1
        ev = "runs/eng/events.jsonl"
        self.write(ev, line(9_000, "run.started", run_id="eng") + line(9_050, "run.finished", {"status": "ok"}, run_id="eng"))
        self.assertEqual([(h.run_id, h.status) for h in self.obs.poll().history], [("eng", "ok")])

    def test_retry_with_same_run_id_starts_new_attempt(self):  # review #2
        self.write("telemetry/jobs.jsonl", line(9_000, "run.started", {"title": "x"}, run_id="r")
                   + line(9_010, "run.finished", {"status": "failed", "error": "rc=1"}, run_id="r")
                   + line(9_100, "run.started", {"title": "x"}, run_id="r"))
        self.write("runs/r/events.jsonl", line(9_101, "stage.started", {"stage": "chain"}, run_id="r", stage="chain")
                   + line(9_102, "stage.progress", {"step": 1, "total_steps": 4}, run_id="r", stage="chain"))
        s = self.obs.poll()
        self.assertEqual(s.now.run_id, "r")
        self.assertEqual(s.history, [])

    def test_cross_file_order_does_not_finish_a_newer_attempt(self):  # review #2
        # runs/ file is ingested before telemetry/, but the older run.finished must not close the newer stage
        self.write("runs/r/events.jsonl", line(9_101, "stage.started", {"stage": "chain"}, run_id="r", stage="chain"))
        self.write("telemetry/jobs.jsonl", line(9_000, "run.started", run_id="r")
                   + line(9_010, "run.finished", {"status": "failed"}, run_id="r"))
        self.assertEqual(self.obs.poll().now.run_id, "r")

    def test_stale_llm_live_is_dropped(self):  # review #6
        self.write("runs/r1/events.jsonl", line(9_998, "model.stream", {"output_tokens_so_far": 5}, stage="interpret"))
        self.assertIsNotNone(self.obs.poll().models.llm_live)
        self.now[0] = 9_998 + observe.LLM_LIVE_STALE_S + 1
        self.assertIsNone(self.obs.poll().models.llm_live)

    def test_malformed_records_counted_not_raised(self):  # review #9
        self.write("runs/r1/events.jsonl", "null\n5\n" + json.dumps({"ts": "x", "run_id": "r1", "type": "stage.ok", "payload": "str"}) + "\n")
        s = self.obs.poll()
        self.assertGreaterEqual(self.obs._tail.bad_lines + s.warnings.__len__(), 1)
        self.assertTrue(any("unreadable" in w for w in s.warnings))

    def test_hw_series_and_sampler_alive(self):
        self.write("telemetry/hw-20260924.jsonl",
                   line(self.now[0] - 700, "hw.sample", {"vram_mib": 1.0}, run_id=None)
                   + line(self.now[0] - 3, "hw.sample", {"vram_mib": 5000.0, "ram_gib": 58.0}, run_id=None))
        hwi = self.obs.poll().hw
        self.assertTrue(hwi.sampler_alive)
        self.assertEqual([v for _, v in hwi.series["vram_mib"]], [5000.0])  # older than 600 s dropped
        self.assertEqual(hwi.latest["ram_gib"], 58.0)

    def test_model_tokens_live_then_final(self):
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(9_998, "model.stream", {"model": "qwen3:8b", "output_tokens_so_far": 40, "tokens_per_s": 38.0},
                            stage="interpret"))
        m = self.obs.poll().models
        self.assertEqual(m.llm_live["output_tokens_so_far"], 40)
        self.write(ev, line(9_995, "model.response", {"model": "qwen3:8b", "input_tokens": 900, "output_tokens": 612,
                                                      "tokens_per_s": 38.2, "latency_s": 16.1}, stage="interpret"))
        m = self.obs.poll().models
        self.assertIsNone(m.llm_live)
        self.assertEqual(m.llm_last["output_tokens"], 612)

    def test_awaiting_approval_is_its_own_status_and_resume_clears_it(self):
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(1, "run.started") + line(2, "stage.started", {"stage": "keyframe"})
                   + line(3, "stage.ok", {"stage": "keyframe", "duration_s": 1})
                   + line(4, "run.awaiting_approval", {"review": "r.md", "chosen": 1}))
        h = self.obs.poll().history[0]
        self.assertEqual((h.status, h.results["chosen"]), ("awaiting approval", 1))
        self.write(ev, line(9_990, "run.resumed") + line(9_991, "stage.started", {"stage": "take"}))
        self.assertIsNotNone(self.obs.poll().now)

    def test_latest_verdict_event_without_reviving_the_run(self):
        ev = "runs/r1/events.jsonl"
        self.write(ev, line(1, "run.started") + line(2, "stage.started", {"stage": "take"})
                   + line(3, "stage.ok", {"stage": "take", "duration_s": 1}))
        self.assertEqual(self.obs.poll().history[0].status, "idle")
        self.write(ev, line(9_990, "verdict", {"text": "slight"}) + line(9_991, "verdict", {"text": "nothing noticed"}))
        h = self.obs.poll().history[0]
        self.assertEqual((h.status, h.verdict), ("idle", "nothing noticed"))


if __name__ == "__main__":
    unittest.main()
