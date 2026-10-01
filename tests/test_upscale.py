"""upscale stages: circular chunk layout (pure) + chunk -> join -> deliver4k on a tiny synthetic loop with FlashVSR
replaced by a plain ffmpeg x4 scale. Needs numpy/cv2 + ffmpeg (WanGP venv); self-skips otherwise."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import numpy as np
    from looper import loopkit
    HAVE = True
except ImportError:
    HAVE = False
try:
    from looper.stages import upscale
except ImportError as e:  # system Python: no numpy / cv2 / torch -- the whole module needs the WanGP venv
    raise unittest.SkipTest(f"needs the WanGP venv ({e})")


class TestEncode(unittest.TestCase):
    def test_nvenc_quality_is_not_silently_capped(self):
        # hevc_nvenc -cq 17 -b:v 0 still came out at 20 Mbps (its default cap); with -maxrate: 75 Mbps (2026-09-26)
        with mock.patch("looper.stages.upscale.run_ffmpeg") as ff:
            upscale._encode(["-i", "x.mp4"], Path("y.mp4"), "hevc_nvenc", 19)
        args = ff.call_args.args[0]
        self.assertEqual(args[args.index("-cq") + 1], "19")
        self.assertIn("-maxrate", args)


class TestLayout(unittest.TestCase):
    def test_chunks_cover_the_loop_once(self):
        spans = upscale.layout(100, chunk=40)
        self.assertEqual(spans, [(0, 40), (40, 80), (80, 100)])

    def test_short_last_chunk_is_merged(self):  # a 5-frame tail would get almost no temporal context of its own
        self.assertEqual(upscale.layout(85, chunk=40), [(0, 40), (40, 85)])

    def test_source_indices_wrap_around_the_loop(self):
        self.assertEqual(upscale.source_indices(10, 0, 4, margin=2), [8, 9, 0, 1, 2, 3, 4, 5])
        self.assertEqual(upscale.source_indices(10, 6, 10, margin=2), [4, 5, 6, 7, 8, 9, 0, 1])


def fake_flashvsr(source, out_dir, dest_name, *, scratch_dir, **kw):
    dest = Path(out_dir) / dest_name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf", "scale=iw*4:ih*4:flags=neighbor",
                    "-c:v", "libx264", "-qp", "0", str(dest)], check=True)
    return {"output": str(dest)}


def upscale_all(d, loop, n, size, fake, chunk=12, margin=3, ramp=3):
    spans = upscale.layout(n, chunk=chunk)
    ups = {}
    with mock.patch("looper.adapters.wangp.postprocess", side_effect=fake):
        for i, (s, e) in enumerate(spans):
            out = d / f"c{i}"
            out.mkdir()
            m = upscale.run_chunk({"loop": loop}, {"start": s, "end": e, "margin": margin, "size": size,
                                                   "model": "flashvsr*4"}, out, scratch_dir=d / "scr")
            ups[f"c{i}"] = Path(m["upscaled"])
    (d / "j").mkdir()
    return upscale.run_join(ups, {"n": n, "spans": spans, "margin": margin, "ramp": ramp, "size": size}, d / "j")


def fake_flashvsr_per_run_offset():
    """Each call is a new 'run' whose invented texture differs: modelled as +6 grey per run (dir_neon: the chunk
    joins stepped ~10x the median frame step)."""
    calls = []

    def fake(source, out_dir, dest_name, *, scratch_dir, **kw):
        dest = Path(out_dir) / dest_name
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf",
                        f"scale=iw*4:ih*4:flags=neighbor,lutrgb=r=val+{6 * len(calls)}:g=val+{6 * len(calls)}:"
                        f"b=val+{6 * len(calls)}", "-c:v", "libx264", "-qp", "0", str(dest)], check=True)
        calls.append(1)
        return {"output": str(dest)}
    return fake


@unittest.skipUnless(HAVE, "needs numpy + cv2 (WanGP venv)")
class TestChunkJoinDeliver(unittest.TestCase):
    def test_deliver_reports_and_gates_the_chunk_joins(self):
        # final review #5: the v1 join pop (~10x median at every chunk join) was only found by hand
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            n = 36
            loop = loopkit.write_video([np.full((12, 20, 3), 100, np.uint8)] * n, d / "loop.mp4", lossless=True)
            joined = upscale_all(d, loop, n, [96, 48], fake_flashvsr_per_run_offset())
            (d / "del").mkdir()
            out = upscale.run_deliver4k({"period": Path(joined["output"])},
                                        {"repeats": 1, "block_periods": 2, "cq": 20, "codec": "libx265",
                                         "spans": upscale.layout(n, 12)}, d / "del")
            self.assertEqual([j for j, _ in out["join_steps"]], [11, 23])  # frame before each chunk start (not 0)
            self.assertIn("accept", out)

    def test_runs_that_disagree_are_ramped_not_stepped(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            n = 36  # 3 chunks of 12, a static scene: any step is the join
            loop = loopkit.write_video([np.full((12, 20, 3), 100, np.uint8)] * n, d / "loop.mp4", lossless=True)
            joined = upscale_all(d, loop, n, [96, 48], fake_flashvsr_per_run_offset())
            means = [float(f.mean()) for f in loopkit.read_frames(Path(joined["output"]))]
            steps = [abs(means[(i + 1) % n] - means[i]) for i in range(n)]
            # without ramps: +6 at two joins and -12 at the wrap in ONE frame; ramped over 4 steps of ~3 (+-2 grey
            # noise: each chunk's source clip is its own lossy crf-8 encode)
            self.assertLess(max(steps), 6.0, [round(s, 1) for s in steps])
            self.assertGreater(max(means) - min(means), 10)  # the runs really did differ


    def test_frames_come_out_once_in_order_at_target_size(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            n = 30
            # brightness encodes the index, inside video-legal range (values < 16 are crushed by the YUV round trip)
            frames = [np.full((12, 20, 3), 40 + 5 * i, np.uint8) for i in range(n)]
            loop = loopkit.write_video(frames, d / "loop.mp4", lossless=True)
            size = [96, 48]
            joined = upscale_all(d, loop, n, size, fake_flashvsr)
            got = loopkit.read_frames(Path(joined["output"]))
            self.assertEqual(len(got), n)
            self.assertEqual(got[0].shape[:2], (48, 96))
            means = [float(f.mean()) for f in got]
            for i in range(n):  # relative to frame 0 (YUV offset); < half the 5-grey spacing = right frame, right order
                self.assertAlmostEqual(means[i] - means[0], 5 * i, delta=2.4, msg=f"frame {i}")
            (d / "del").mkdir()
            out = upscale.run_deliver4k({"period": Path(joined["output"])}, {"repeats": 2, "block_periods": 2,
                                                                             "cq": 20, "codec": "libx265"}, d / "del")
            self.assertEqual(out["final_frames"], n * 2 * 2)
            # the ramp is not a seamless loop, so every wrap is a big step; the file's own wrap (codec seam) must
            # behave like the block's internal loop points (ordinary frames), as in deliver.py
            self.assertEqual(len(out["inner_wrap_steps"]), 1)
            self.assertLess(abs(out["file_wrap_step"] - out["inner_wrap_steps"][0]), 0.25 * out["inner_wrap_steps"][0])


@unittest.skipUnless(HAVE, "needs numpy + cv2 (WanGP venv)")
class TestPipelineWiring(unittest.TestCase):
    def test_one_stage_per_chunk_and_a_rerun_is_all_cache_hits(self):
        import json
        from looper.engine import Engine
        from looper.loop_pipeline import DEFAULTS, final_4k
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            loop = loopkit.write_video([np.full((12, 20, 3), 40 + 5 * i, np.uint8) for i in range(30)],
                                       d / "loop.mp4", lossless=True)
            cfg = {**DEFAULTS, "upscale_chunk": 12, "upscale_margin": 3, "size_4k": [96, 48],
                   "codec_4k": "libx265", "final_minutes": 0.1}
            with mock.patch("looper.adapters.wangp.postprocess", side_effect=fake_flashvsr) as pp:
                r1 = final_4k(Engine(d / "run", "r"), loop, cfg, d / "run")
                calls = pp.call_count
                r2 = final_4k(Engine(d / "run", "r"), loop, cfg, d / "run")
            self.assertEqual(calls, 3)            # 30 frames / 12 -> [0,12) [12,24) [24,30) (tail = half: kept)
            self.assertEqual(pp.call_count, 3)    # rerun: nothing upscaled again
            self.assertEqual(r1, r2)
            ev = [json.loads(l)["type"] for l in (d / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(ev.count("stage.restored"), 5)  # 3 chunks + join + deliver4k
            self.assertGreaterEqual(r1["final_seconds"], 6.0)


if __name__ == "__main__":
    unittest.main()
