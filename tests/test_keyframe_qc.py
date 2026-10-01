"""keyframe_qc: verdict rule and seed selection; run() with a faked model. No GPU/LLM."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper.stages import keyframe_qc as kq

GOOD = {"brief": 5, "motion_visible": 4, "settled": 4, "cinematic": 5, "hard_fails": [], "notes": "fine"}


class TestVerdict(unittest.TestCase):
    def test_accept_rule(self):
        self.assertEqual(kq.verdict(GOOD)["accept"], True)
        self.assertEqual(kq.verdict(GOOD)["total"], 18)
        self.assertFalse(kq.verdict({**GOOD, "settled": 2})["accept"])
        self.assertFalse(kq.verdict({**GOOD, "hard_fails": ["a person in frame"]})["accept"])

    def test_bad_scores_count_as_zero(self):
        v = kq.verdict({"brief": "high", "motion_visible": 9, "hard_fails": "x"})
        self.assertEqual(v["scores"], {"brief": 0, "motion_visible": 5, "settled": 0, "cinematic": 0})
        self.assertFalse(v["accept"])

    def test_pick_prefers_accepted_then_total(self):
        c = [{"accept": False, "total": 19}, {"accept": True, "total": 15}, {"accept": True, "total": 17}]
        self.assertEqual(kq.pick(c), (2, None))
        idx, warn = kq.pick([{"accept": False, "total": 10}, {"accept": False, "total": 12}])
        self.assertEqual(idx, 1)
        self.assertIn("no keyframe passed", warn)


class TestRun(unittest.TestCase):
    def test_prose_scores_trigger_one_retry(self):
        # real qwen3.6 reply (dir_neon, 2026-09-25): prose for "brief", true for "motion_visible" -> scored as 0
        bad = {**GOOD, "brief": "The frame perfectly captures the scene.", "motion_visible": True}
        replies = iter([(bad, {"request_id": "a"}), (GOOD, {"request_id": "b"})])
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", side_effect=lambda *a, **k: next(replies)) as cj:
            img = Path(d) / "k.png"
            img.write_bytes(b"x")
            out = kq.run({"image": img}, {"brief": "b", "motion": "m", "provider": "ollama", "model": "q"}, Path(d))
        self.assertEqual(cj.call_count, 2)
        self.assertIn("integer", cj.call_args_list[1].args[1])
        self.assertTrue(out["accept"])

    def test_unparseable_twice_is_a_zero_score_not_a_crash(self):
        # final review #2: one bad critic reply aborted the whole front end; the spec's policy is best effort
        from looper import models
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", side_effect=models.ModelError("not JSON")) as cj:
            img = Path(d) / "k.png"
            img.write_bytes(b"x")
            out = kq.run({"image": img}, {"brief": "b", "motion": "m", "provider": "ollama", "model": "q"}, Path(d))
        self.assertEqual(cj.call_count, 2)
        self.assertEqual((out["accept"], out["total"]), (False, 0))
        self.assertIn("not JSON", out["notes"])

    def test_prompt_shows_integer_example(self):
        self.assertRegex(kq._ASK, r'"brief": \d')

    def test_run_writes_qc(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("looper.models.complete_json", return_value=(GOOD, {"request_id": "q"})) as cj:
            img = Path(d) / "k.png"
            img.write_bytes(b"x")
            out = kq.run({"image": img}, {"brief": "a waterfall", "motion": "water falls", "provider": "ollama",
                                          "model": "gemma4:12b"}, Path(d))
            self.assertTrue((Path(d) / "qc.json").exists())
        self.assertTrue(out["accept"])
        self.assertEqual(cj.call_args.kwargs["images"], [img])
        self.assertTrue(cj.call_args.kwargs["unload"])
        self.assertIn("a waterfall", cj.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
