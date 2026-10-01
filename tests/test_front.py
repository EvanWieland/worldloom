"""front.prepare(): director + keyframes + critic + pause/approve, with the model and WanGP faked. Needs PIL."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from PIL import Image
    HAVE = True
except ImportError:  # only PIL is optional; a missing looper module must fail, not skip
    HAVE = False
from looper import front
from looper.engine import Engine

FACTS = {"scene": "A waterfall.", "style": "Photorealistic, cinematic", "keyframe_details": "white water, ferns",
         "moving": ["the water falls steadily"], "fixed": ["the rocks"], "negatives": [], "adaptations": []}
CFG = {"director": "local", "director_model": None, "raw_prompt": False, "auto": False, "approve": False,
       "keyframe": None, "keyframe_seeds": [1000, 1001, 1002]}


def fake_model(task, prompt, **kw):
    if task == "direct":
        return FACTS, {"request_id": "d"}
    seed_total = {"k0": 3, "k1": 5, "k2": 4}[Path(kw["images"][0]).parent.name[-2:]]  # see fake_generate dirs
    return {"brief": seed_total, "motion_visible": 4, "settled": 4, "cinematic": 4, "hard_fails": [], "notes": ""}, {}


def fake_generate(settings, out_dir, dest_name, *, scratch_dir):
    p = Path(out_dir) / dest_name
    Image.new("RGB", (1280, 720), (settings["seed"] % 255, 0, 0)).save(p)
    return {"output": str(p), "settings": settings}


@unittest.skipUnless(HAVE, "needs PIL (WanGP venv)")
class TestPrepare(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.patches = [mock.patch("looper.models.complete_json", side_effect=fake_model),
                        mock.patch("looper.adapters.wangp.generate", side_effect=fake_generate),
                        mock.patch("looper.adapters.wangp._free_gpu"),
                        mock.patch("looper.stages.keyframe.hw.HardwareSampler")]
        for p in self.patches:
            p.start()
        # keyframe out dirs are fingerprints; tag them so fake_model can tell seeds apart
        orig = front.keyframe.run

        def tagged(inp, c, out, *, scratch_dir):
            tag = Path(out).parent / f"{Path(out).name}_k{c['seed'] - 1000}"
            tag.mkdir(parents=True, exist_ok=True)
            return orig(inp, c, tag, scratch_dir=scratch_dir)
        self.patches.append(mock.patch.object(front.keyframe, "run", side_effect=tagged))
        self.patches[-1].start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self._tmp.cleanup()

    def engine(self):
        return Engine(self.run_dir, "r", original_prompt="a waterfall")

    def events(self):
        return [json.loads(l) for l in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_default_pauses_with_best_keyframe_and_review(self):
        with self.assertRaises(front.AwaitingApproval) as cm:
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        info = cm.exception.info
        self.assertEqual(info["chosen"], 1)  # seed 1001 scored highest
        self.assertTrue(Path(info["review"]).exists())
        self.assertTrue((self.run_dir / "review" / "keyframes.jpg").exists())
        self.assertIn("run.awaiting_approval", [e["type"] for e in self.events()])

    def test_approve_resumes_from_cache_and_honours_choice(self):
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        out = front.prepare(self.engine(), "a waterfall", None, {**CFG, "approve": True, "keyframe": 2}, self.run_dir)
        self.assertTrue(str(out["image"]).endswith("keyframe.png"))
        self.assertIn("_k2", str(out["image"]))
        types = [e["type"] for e in self.events()]
        self.assertEqual(types.count("stage.started"), 8)  # direct + contract + 3 keyframes + 3 qc, first pass only
        self.assertIn("run.approved", types)

    def test_approve_with_a_different_prompt_refuses_instead_of_rendering_unseen_stills(self):
        # final review #1: a retyped/changed --prompt re-ran the director and went straight into GPU hours
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        with self.assertRaises(ValueError) as cm:
            front.prepare(self.engine(), "a jungle waterfall", None, {**CFG, "approve": True}, self.run_dir)
        self.assertIn("paused", str(cm.exception))

    def test_approve_with_different_director_flags_refuses(self):
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        with self.assertRaises(ValueError):
            front.prepare(self.engine(), "a waterfall", None, {**CFG, "approve": True, "director_model": "other"},
                          self.run_dir)

    def test_resume_hint_carries_the_real_prompt(self):
        with self.assertRaises(front.AwaitingApproval) as cm:
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        self.assertIn('"a waterfall"', cm.exception.info["resume"])

    def test_approve_without_prior_pause_just_runs(self):  # review focus
        out = front.prepare(self.engine(), "a waterfall", None, {**CFG, "approve": True}, self.run_dir)
        self.assertIn("_k1", str(out["image"]))

    def test_auto_never_pauses(self):
        out = front.prepare(self.engine(), "a waterfall", None, {**CFG, "auto": True}, self.run_dir)
        self.assertIn("The water falls steadily.", out["prompt"])

    def test_local_director_thinks_and_critic_does_not(self):
        calls = []

        def spy(task, prompt, **kw):
            calls.append((task, kw["model"], kw.get("think", False)))
            return fake_model(task, prompt, **kw)
        with mock.patch("looper.models.complete_json", side_effect=spy):
            front.prepare(self.engine(), "a waterfall", None, {**CFG, "auto": True}, self.run_dir)
        self.assertEqual(calls[0], ("direct", "qwen3.6:35b", True))
        self.assertTrue(all(c == ("keyframe_qc", "qwen3.6:35b", False) for c in calls[1:]))

    def test_keyframe_out_of_range(self):  # review focus
        with self.assertRaises(ValueError) as cm:
            front.prepare(self.engine(), "a waterfall", None, {**CFG, "approve": True, "keyframe": 3}, self.run_dir)
        self.assertIn("0..2", str(cm.exception))

    def test_image_path_skips_keyframes(self):
        img = Path(self._tmp.name) / "u.png"
        Image.new("RGB", (832, 480)).save(img)
        out = front.prepare(self.engine(), "Rain falls. Locked-off tripod shot.", img, CFG, self.run_dir)
        self.assertEqual(out["image"], img)
        self.assertFalse((self.run_dir / "stages" / "keyframe").exists())

    def test_raw_prompt_skips_director(self):
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(self.engine(), "exact words", None, {**CFG, "raw_prompt": True}, self.run_dir)
        self.assertFalse((self.run_dir / "stages" / "direct").exists())

    def test_same_prompt_new_run_dir_is_a_new_run(self):  # review focus
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(self.engine(), "a waterfall", None, CFG, self.run_dir)
        other = Path(self._tmp.name) / "run2"
        with self.assertRaises(front.AwaitingApproval):
            front.prepare(Engine(other, "r2", original_prompt="a waterfall"), "a waterfall", None, CFG, other)
        self.assertTrue((other / "stages" / "direct").exists())


if __name__ == "__main__":
    unittest.main()
