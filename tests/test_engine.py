"""Tests for looper.engine: fingerprinting, caching, resume-after-failure, manifest/events.
No GPU, no network -- these must run in seconds and are the part CLAUDE.md says "must never
silently break". Run: python -m unittest discover tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper.engine import Engine, fingerprint, last_activity, redact, stale_stage_dirs


class TempRunMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.run_dir = Path(self._tmp.name) / "run"
        self.engine = Engine(self.run_dir, run_id="t", original_prompt="a test scene")

    def tearDown(self):
        self._tmp.cleanup()

    def input_file(self, name: str, content: str) -> Path:
        p = Path(self._tmp.name) / name
        p.write_text(content, encoding="utf-8")
        return p


class TestFingerprint(unittest.TestCase):
    def test_deterministic(self):
        fp1 = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        fp2 = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        self.assertEqual(fp1, fp2)

    def test_changes_with_config(self):
        base = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        changed = fingerprint("s", 1, {"a": 2}, seed=42, input_hashes={"x": "abc"})
        self.assertNotEqual(base, changed)

    def test_changes_with_version(self):
        base = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        changed = fingerprint("s", 2, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        self.assertNotEqual(base, changed)

    def test_changes_with_seed(self):
        base = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        changed = fingerprint("s", 1, {"a": 1}, seed=7, input_hashes={"x": "abc"})
        self.assertNotEqual(base, changed)

    def test_changes_with_input_hash(self):
        base = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "abc"})
        changed = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "def"})
        self.assertNotEqual(base, changed)

    def test_input_key_order_irrelevant(self):
        a = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"x": "1", "y": "2"})
        b = fingerprint("s", 1, {"a": 1}, seed=42, input_hashes={"y": "2", "x": "1"})
        self.assertEqual(a, b)


class TestRedact(unittest.TestCase):
    def test_strips_secret_shaped_keys(self):
        out = redact({"api_key": "sk-abc123", "nested": {"Authorization": "Bearer x"}, "safe": "ok"})
        self.assertEqual(out["api_key"], "<redacted>")
        self.assertEqual(out["nested"]["Authorization"], "<redacted>")
        self.assertEqual(out["safe"], "ok")

    def test_provider_style_names_and_credentials_inside_text(self):
        """Public-release privacy review (2026-10-01): RUNPOD_API_KEY, access_token and a key pasted into a prompt
        were written out unchanged. Counters and stage keys must survive (the dashboard reads them)."""
        out = redact({"RUNPOD_API_KEY": "x" * 20, "access_token": "y", "clientSecret": "z", "db_password": "p",
                      "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE", "private_key": "k",
                      "prompt": "rain at night sk-testFAKEtestFAKEtestFAKE and hf_FAKEexampleFAKEexampleFAKE",
                      "note": "header Bearer abcdefghij.klmnopqrst", "events": [{"Token": "t"}],
                      "key": "take[0]", "keyframe": "k.png", "input_tokens": 3134, "tokens_per_s": 30.5, "pass": True})
        for k in ("RUNPOD_API_KEY", "access_token", "clientSecret", "db_password", "aws_access_key_id", "private_key"):
            self.assertEqual(out[k], "<redacted>", k)
        self.assertEqual(out["events"][0]["Token"], "<redacted>")
        self.assertEqual(out["prompt"], "rain at night <redacted> and <redacted>")
        self.assertEqual(out["note"], "header <redacted>")
        self.assertEqual((out["key"], out["keyframe"], out["input_tokens"], out["tokens_per_s"], out["pass"]),
                         ("take[0]", "k.png", 3134, 30.5, True))


class TestCacheHit(TempRunMixin, unittest.TestCase):
    def test_second_call_is_cache_hit_and_skips_fn(self):
        calls = []

        def fn(inputs, config, out_dir):
            calls.append(1)
            (out_dir / "out.txt").write_text("hello")
            return {"wrote": "out.txt"}

        r1 = self.engine.run_stage("greet", 1, {"x": 1}, {}, fn)
        r2 = self.engine.run_stage("greet", 1, {"x": 1}, {}, fn)

        self.assertEqual(len(calls), 1, "fn should run exactly once across two identical calls")
        self.assertFalse(r1.cached)
        self.assertTrue(r2.cached)
        self.assertEqual(r1.fingerprint, r2.fingerprint)
        self.assertEqual(r1.out_dir, r2.out_dir)

    def test_different_config_is_not_cached(self):
        calls = []

        def fn(inputs, config, out_dir):
            calls.append(config["x"])
            return {}

        self.engine.run_stage("greet", 1, {"x": 1}, {}, fn)
        self.engine.run_stage("greet", 1, {"x": 2}, {}, fn)
        self.assertEqual(calls, [1, 2])


class TestResumeAfterFailure(TempRunMixin, unittest.TestCase):
    def test_failed_stage_reruns_then_caches(self):
        attempts = {"n": 0}

        def flaky(inputs, config, out_dir):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("simulated transient failure")
            (out_dir / "out.txt").write_text("ok")
            return {}

        with self.assertRaises(RuntimeError):
            self.engine.run_stage("gen", 1, {}, {}, flaky)
        self.assertEqual(attempts["n"], 1)

        # resume: same args, retries the failed stage
        r2 = self.engine.run_stage("gen", 1, {}, {}, flaky)
        self.assertEqual(attempts["n"], 2)
        self.assertFalse(r2.cached)
        self.assertEqual(r2.status, "ok")

        # third call: now a cache hit, fn not called again
        r3 = self.engine.run_stage("gen", 1, {}, {}, flaky)
        self.assertEqual(attempts["n"], 2)
        self.assertTrue(r3.cached)

    def test_upstream_success_is_not_rerun_when_downstream_fails(self):
        upstream_calls = []

        def upstream(inputs, config, out_dir):
            upstream_calls.append(1)
            (out_dir / "keyframe.txt").write_text("kf")
            return {}

        def downstream_fails(inputs, config, out_dir):
            raise RuntimeError("boom")

        self.engine.run_stage("interpret", 1, {}, {}, upstream)
        kf_path = self.run_dir / "stages" / "interpret"
        kf_file = next(kf_path.rglob("keyframe.txt"))

        with self.assertRaises(RuntimeError):
            self.engine.run_stage("generate", 1, {}, {"keyframe": kf_file}, downstream_fails)

        # simulate a fresh process resuming the run: re-declare the upstream call
        self.engine.run_stage("interpret", 1, {}, {}, upstream)
        self.assertEqual(len(upstream_calls), 1, "upstream must stay a cache hit across resume")


class TestDownstreamInvalidation(TempRunMixin, unittest.TestCase):
    def test_changing_input_content_reruns_downstream_only(self):
        """Mirrors the real pipeline: changing one clip's content must change assemble's
        fingerprint (via the input hash) without touching sibling clips."""
        clip_a = self.input_file("clip_a.mp4", "content-A")
        clip_b = self.input_file("clip_b.mp4", "content-B")

        b_calls = []

        def build_b(inputs, config, out_dir):
            b_calls.append(1)
            return {}

        def assemble(inputs, config, out_dir):
            return {"joined": sorted(str(p) for p in inputs.values())}

        # "generate" clip b once
        self.engine.run_stage("generate", 1, {}, {"src": clip_b}, build_b, key="generate[1]")
        r1 = self.engine.run_stage("assemble", 1, {}, {"a": clip_a, "b": clip_b}, assemble)
        self.assertFalse(r1.cached)

        # rerun assemble unchanged -> cache hit
        r2 = self.engine.run_stage("assemble", 1, {}, {"a": clip_a, "b": clip_b}, assemble)
        self.assertTrue(r2.cached)

        # clip b's content changes (as if regenerated with a different seed) -> assemble must rerun,
        # but clip b's own stage (already recorded ok) stays a cache hit since its OWN fingerprint
        # (inputs unchanged from its perspective) doesn't move -- this simulates "add clip" not
        # "regenerate clip" since that changes generate's fingerprint too; here we only check
        # assemble's sensitivity to its declared inputs.
        clip_b.write_text("content-B-v2", encoding="utf-8")
        r3 = self.engine.run_stage("assemble", 1, {}, {"a": clip_a, "b": clip_b}, assemble)
        self.assertFalse(r3.cached, "assemble must not cache-hit once an input file's content changed")
        self.assertEqual(len(b_calls), 1, "generate[1] itself was never re-invoked in this test")


class TestManifestAndEvents(TempRunMixin, unittest.TestCase):
    def test_manifest_reflects_stage_status(self):
        def fn(inputs, config, out_dir):
            return {}

        r = self.engine.run_stage("plan", 1, {}, {}, fn)
        manifest = json.loads((self.run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["stages"]["plan"]["status"], "ok")
        self.assertEqual(manifest["stages"]["plan"]["fingerprint"], r.fingerprint)
        self.assertEqual(manifest["original_prompt"], "a test scene")

    def test_events_log_started_ok_then_restored(self):
        def fn(inputs, config, out_dir):
            return {}

        self.engine.run_stage("plan", 1, {}, {}, fn)
        self.engine.run_stage("plan", 1, {}, {}, fn)
        lines = [json.loads(l) for l in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        types = [l["type"] for l in lines]
        self.assertIn("run.started", types)
        self.assertIn("stage.started", types)
        self.assertIn("stage.ok", types)
        self.assertIn("stage.restored", types)

    def test_replanned_stage_emits_superseded_and_keeps_old_output(self):
        r1 = self.engine.run_stage("direct", 14, {}, {}, lambda i, c, o: {})
        r2 = self.engine.run_stage("direct", 15, {}, {}, lambda i, c, o: {})
        lines = [json.loads(l) for l in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        sup = [l["payload"] for l in lines if l["type"] == "stage.superseded"]
        self.assertEqual(sup, [{"stage": "direct", "key": "direct", "old": r1.fingerprint, "new": r2.fingerprint}])
        self.assertTrue((r1.out_dir / "stage.json").exists())

    def test_resuming_run_emits_run_resumed(self):
        engine2 = Engine(self.run_dir, run_id="t", original_prompt="a test scene")
        lines = [json.loads(l) for l in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("run.resumed", [l["type"] for l in lines])

    def test_stale_stage_dirs_are_the_superseded_fingerprints_only(self):
        noop = lambda inputs, config, out_dir: {}
        old = self.engine.run_stage("take", 1, {"seed": 1}, {}, noop, key="take[0]")
        new = self.engine.run_stage("take", 1, {"seed": 2}, {}, noop, key="take[0]")  # supersedes `old`
        other = self.engine.run_stage("take", 1, {"seed": 3}, {}, noop, key="take[1]")
        self.assertEqual(stale_stage_dirs(self.run_dir), [old.out_dir])
        self.assertTrue(new.out_dir.exists() and other.out_dir.exists())

    def test_last_activity_ignores_verdicts(self):
        self.engine.emit("stage.ok", {"stage": "take"})
        before = last_activity(self.run_dir)
        with open(self.run_dir / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": before + 999, "type": "verdict", "payload": {"text": "ok"}}) + "\n{torn")
        self.assertEqual(last_activity(self.run_dir), before)


if __name__ == "__main__":
    unittest.main()
