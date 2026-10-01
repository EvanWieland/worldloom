"""WanGP's location: $WANGP_ROOT, else a Wan2GP checkout beside the repository; a clear error when missing."""
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestWanGPRoot(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("WANGP_ROOT", None)
        from looper.adapters import wangp
        importlib.reload(wangp)

    def test_env_wins_and_a_missing_checkout_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            os.environ["WANGP_ROOT"] = d
            from looper.adapters import wangp
            importlib.reload(wangp)
            self.assertEqual(wangp.WANGP_ROOT, Path(d))
            with self.assertRaises(FileNotFoundError) as e:
                wangp.ensure_path()
            self.assertIn("WANGP_ROOT", str(e.exception))
            (Path(d) / "wgp.py").write_text("")
            wangp.ensure_path()  # a checkout: no error
            self.assertIn(d, sys.path)
            sys.path.remove(d)

    def test_default_is_beside_the_repository(self):
        from looper.adapters import wangp
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "looper"
            repo.mkdir()
            self.assertEqual(wangp.default_root(repo), Path(d) / "Wan2GP")  # nothing installed: the documented place
            (Path(d) / "tools" / "Wan2GP").mkdir(parents=True)
            self.assertEqual(wangp.default_root(repo), Path(d) / "tools" / "Wan2GP")
            (Path(d) / "Wan2GP").mkdir()
            self.assertEqual(wangp.default_root(repo), Path(d) / "Wan2GP")  # right beside the repository wins


if __name__ == "__main__":
    unittest.main()
