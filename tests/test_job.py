"""Job contract export (looper/job.py): disabled, reproducible, bound to the stage fingerprint."""
import json
import tempfile
import unittest
from pathlib import Path

from looper import job
from looper.engine import Engine


class TestJob(unittest.TestCase):
    def test_export_pins_recipe_and_is_disabled(self):
        d = Path(tempfile.mkdtemp())
        e = Engine(d, "r", original_prompt="p")

        def fn(inputs, config, out):
            (out / "settings.json").write_text(json.dumps({"model_type": "m", "seed": 7}), encoding="utf-8")
            return {"runtime": {"wangp_rev": "abc"}}
        r = e.run_stage("take", 1, {"frames": 481}, {}, fn, seed=7, key="take[0]")
        j = json.loads(job.export(d, "take[0]", {"max_cost_usd": 5}).read_text(encoding="utf-8"))
        self.assertEqual((j["enabled"], j["fingerprint"], j["seed"]), (False, r.fingerprint, 7))
        self.assertEqual(j["recipe"]["model_type"], "m")
        self.assertEqual(j["runtime"]["wangp_rev"], "abc")
        self.assertEqual(j["limits"]["max_cost_usd"], 5)
        with self.assertRaises(KeyError):
            job.export(d, "close[306]")


if __name__ == "__main__":
    unittest.main()
