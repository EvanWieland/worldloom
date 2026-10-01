import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import hw


class TestSampler(unittest.TestCase):
    def test_sample_once_parses_and_tolerates_failure(self):
        s = hw.sample_once(nvsmi=lambda: "5226, 6144, 100, 69, 65.2")
        self.assertEqual((s["vram_mib"], s["vram_total_mib"], s["gpu_util"], s["temp_c"], s["power_w"]),
                         (5226.0, 6144.0, 100.0, 69.0, 65.2))

        def boom():
            raise TimeoutError("nvidia-smi hung")
        s2 = hw.sample_once(nvsmi=boom)
        self.assertIsNone(s2["vram_mib"])
        if hw.psutil:  # system python has no psutil; WanGP's venv does
            self.assertIsNotNone(s2["ram_total_gib"])  # psutil part still works

    def test_run_sampler_writes_daily_file_and_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old = hw.hw_path(datetime.date.today() - datetime.timedelta(days=9), root)
            old.write_text("{}\n")
            hw.run_sampler(interval_s=0.0, root=root, iterations=3, nvsmi=lambda: "1, 2, 3, 4, 5")
            self.assertFalse(old.exists())
            recs = [json.loads(l) for l in hw.hw_path(datetime.date.today(), root).read_text().splitlines()]
            self.assertEqual([r["type"] for r in recs], ["hw.sample"] * 3)


if __name__ == "__main__":
    unittest.main()
