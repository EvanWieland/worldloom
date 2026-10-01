"""keyframe.fit: Z-Image's 1280x720 -> the loop's 832x480 without distortion. Needs PIL (WanGP venv)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from PIL import Image
    from looper.stages import keyframe
    HAVE = True
except ImportError:
    HAVE = False


@unittest.skipUnless(HAVE, "needs PIL (WanGP venv)")
class TestFitGuide(unittest.TestCase):
    def test_guide_gets_the_keyframes_framing(self):
        """--take-guide: another model's render of the still (resized to ITS size, 848x480 for Hunyuan 480p) must land
        exactly where fit() puts the still; cover-cropping the render directly is ~1 px off at the traveler."""
        import numpy as np
        from looper import loopkit
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            still = np.zeros((826, 1468, 3), np.uint8)
            still[488:512, 288:312] = 255  # a 24-px marker at (300, 500), traveler-like position
            Image.fromarray(still).save(d / "still.png")
            keyframe.fit(d / "still.png", d / "key.png", (832, 480))
            render = np.asarray(Image.fromarray(still).resize((848, 480), Image.LANCZOS))
            loopkit.write_video([render] * 3, d / "render.mp4", crf=0, pix_fmt="yuv444p")
            keyframe.fit_video(d / "render.mp4", d / "guide.mp4", (1468, 826), (832, 480))
            guide = loopkit.read_frames(d / "guide.mp4")
            key = np.asarray(Image.open(d / "key.png").convert("L"), np.float64)
            self.assertEqual((len(guide), guide[0].shape[:2]), (3, (480, 832)))

            def centroid(g):
                w = np.clip(g - 60, 0, None)
                ys, xs = np.mgrid[:g.shape[0], :g.shape[1]]
                return (xs * w).sum() / w.sum(), (ys * w).sum() / w.sum()
            (kx, ky), (gx, gy) = centroid(key), centroid(loopkit.gray(guide[0]).astype(np.float64))
            self.assertLess(abs(gx - kx), 0.5, (gx, kx))
            self.assertLess(abs(gy - ky), 0.5, (gy, ky))


@unittest.skipUnless(HAVE, "needs PIL (WanGP venv)")
class TestFitGuideSpeed(unittest.TestCase):
    def test_a_slowed_guide_shows_the_donor_at_speed_times_k(self):
        """--donor-speed: guide frame k shows the donor at time speed * k (motion-interpolated), trimmed to frames."""
        import numpy as np
        from looper import loopkit
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            frames = []
            for i in range(25):  # a 24-px square moving 8 px per frame
                f = np.zeros((480, 848, 3), np.uint8)
                f[228:252, 100 + 8 * i:124 + 8 * i] = 255
                frames.append(f)
            loopkit.write_video(frames, d / "donor.mp4", crf=0, pix_fmt="yuv444p")
            keyframe.fit_video(d / "donor.mp4", d / "guide.mp4", (848, 480), (848, 480), speed=0.5, frames=33)
            guide = loopkit.read_frames(d / "guide.mp4")
            self.assertEqual(len(guide), 33)

            def cx(f):
                g = loopkit.gray(f).astype(np.float64)
                w = np.clip(g - 60, 0, None)
                return (np.mgrid[:g.shape[0], :g.shape[1]][1] * w).sum() / w.sum()
            for k in (0, 10, 20, 32):  # donor time 0.5k -> x = 112 + 8 * 0.5k
                self.assertLess(abs(cx(guide[k]) - (112 + 4 * k)), 1.5, k)


@unittest.skipUnless(HAVE, "needs PIL (WanGP venv)")
class TestFit(unittest.TestCase):
    def test_cover_and_centre_crop(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "a.png", Path(d) / "b.png"
            im = Image.new("RGB", (1280, 720), (0, 0, 255))
            for x in range(20):  # red 20-px bands at both edges: the crop must remove equal amounts
                for y in range(720):
                    im.putpixel((x, y), (255, 0, 0))
                    im.putpixel((1279 - x, y), (255, 0, 0))
            im.save(src)
            keyframe.fit(src, dst, (832, 480))
            out = Image.open(dst)
            self.assertEqual(out.size, (832, 480))
            for x in (0, 831):  # symmetric crop: both 13-px bands survive in part (odd 21-px excess, Lanczos edges)
                r, _, b = out.getpixel((x, 240))[:3]
                self.assertTrue(r > 200 and b < 60, (x, r, b))


    def test_fit_stage_odd_user_image(self):  # dir_furnace: a 1672x941 --image broke the libx264 encode
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "user.png"
            Image.new("RGB", (1672, 941), (90, 20, 10)).save(src)
            meta = keyframe.fit_run({"image": src}, {"size": [832, 480]}, Path(d))
            self.assertEqual(Image.open(meta["output"]).size, (832, 480))


if __name__ == "__main__":
    unittest.main()
