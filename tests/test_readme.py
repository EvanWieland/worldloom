"""The README names what the code actually needs (public-release review, 2026-10-01: it said "LTX-2" while the code
drives LTX-2.5, and `--motion-speed` needs a LoRA WanGP does not download). Stdlib only."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def constant(path: str, name: str) -> str:
    return re.search(rf'^{name} = "([^"]+)"', (ROOT / path).read_text(encoding="utf-8"), re.M).group(1)


class TestReadme(unittest.TestCase):
    def test_names_the_model_and_the_speed_lora_the_code_uses(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(constant("looper/adapters/ltx.py", "MODEL"), readme)       # ltx2_25_22B_distilled
        self.assertIn(constant("looper/adapters/ltx.py", "SPEED_LORA"), readme)  # the Slow-Motion-Control LoRA

    def test_every_embedded_image_ships_with_the_repository(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        srcs = [s for s in re.findall(r'<img[^>]*\ssrc="([^"]+)"', readme) if not re.match(r"[a-z]+://", s)]
        self.assertTrue(srcs, "the README shows a scene")
        for s in srcs:
            self.assertTrue((ROOT / s).is_file(), s)
            self.assertLess((ROOT / s).stat().st_size, 10 * 2**20, f"{s}: keep the hero under 10 MB")


if __name__ == "__main__":
    unittest.main()
