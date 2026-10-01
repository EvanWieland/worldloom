"""CLI flags reach the run config."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from PIL import Image
except ImportError:  # system Python without PIL
    Image = None


@unittest.skipIf(Image is None, "needs PIL (WanGP venv)")
class FallbackDriftFlag(unittest.TestCase):
    def test_the_best_effort_limit_reaches_the_run_without_moving_the_strict_gate(self):
        """sample1b (2026-09-30): seed 307 missed the 7.5 best-effort limit by 0.05 grey. Resuming with a higher limit
        must leave the strict gate alone -- raising that would make the review call a 7.55 take a clean pass."""
        from looper import __main__ as cli, loop_pipeline
        from looper.adapters import wangp
        seen = {}
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "still.png"
            Image.new("RGB", (64, 48)).save(img)
            argv = ["looper", "loop", "--image", str(img), "--prompt", "x", "--fallback-drift-max", "8", "--run-id", "t"]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(cli, "RUNS_DIR", Path(d)), \
                    mock.patch.object(wangp, "ensure_path", lambda: None), \
                    mock.patch.object(loop_pipeline, "run_loop", lambda *a, **k: seen.update(a[2]) or {}):
                cli.main()
        self.assertEqual((seen["fallback_drift_max"], seen["region_drift_max"]), (8.0, None))


class NoWanGP(unittest.TestCase):
    """A stranger without WanGP gets the WANGP_ROOT error at once -- before the director's minutes-long LLM call or
    any other import (public-release review, 2026-10-01)."""
    def test_loop_stops_before_the_pipeline_when_wangp_is_missing(self):
        import importlib
        import os
        from looper.adapters import wangp
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"WANGP_ROOT": d}), \
                mock.patch.dict(sys.modules, {"looper.loop_pipeline": None}), \
                mock.patch.object(sys, "argv", ["looper", "loop", "--prompt", "rain", "--run-id", "t_no_wangp"]):
            importlib.reload(wangp)  # WANGP_ROOT = the empty temp dir
            from looper import __main__ as cli
            with self.assertRaises(FileNotFoundError) as e:  # not ImportError from the blocked pipeline import
                cli.main()
            self.assertIn("WANGP_ROOT", str(e.exception))
        importlib.reload(wangp)


if __name__ == "__main__":
    unittest.main()
