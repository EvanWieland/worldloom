"""models.complete() streams from Ollama and emits token events. Ollama is faked."""
import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import events, models


def fake_stream(chunks, final):
    lines = [json.dumps({"response": c, "done": False}) for c in chunks]
    lines.append(json.dumps({"response": "", "done": True, **final}))
    return io.BytesIO(("\n".join(lines) + "\n").encode())


class TestStreaming(unittest.TestCase):
    def test_text_meta_and_events(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "e.jsonl"
            events.set_current(p, "r", "interpret")
            body = fake_stream(["Hel", "lo"], {"prompt_eval_count": 12, "eval_count": 2, "eval_duration": 1_000_000_000})
            with mock.patch("urllib.request.urlopen", return_value=body), \
                 mock.patch("looper.models.STREAM_EMIT_INTERVAL_S", 0.0):
                text, meta = models.complete("interpret", "hi")
            events.set_current(None)
            self.assertEqual(text, "Hello")
            self.assertEqual((meta["input_tokens"], meta["output_tokens"], meta["tokens_per_s"]), (12, 2, 2.0))
            recs = [json.loads(l) for l in p.read_text().splitlines()]
            types = [r["type"] for r in recs]
            self.assertIn("model.stream", types)
            self.assertEqual(types[-1], "model.response")
            self.assertEqual(recs[-1]["payload"]["output_tokens"], 2)
            self.assertEqual(recs[-1]["stage"], "interpret")

    def test_stream_without_done_is_an_error(self):  # review #4
        body = io.BytesIO((json.dumps({"response": "trunc", "done": False}) + "\n").encode())
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(body.getvalue())):
            with self.assertRaises(models.ModelError):
                models.complete("t", "hi", retries=1)

    def test_error_chunk_is_an_error(self):  # review #4
        data = (json.dumps({"response": "a", "done": False}) + "\n" + json.dumps({"error": "out of memory"}) + "\n").encode()
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(data)):
            with self.assertRaises(models.ModelError) as cm:
                models.complete("t", "hi", retries=0)
        self.assertIn("out of memory", str(cm.exception))

    def test_connection_reset_mid_stream_is_retried_then_model_error(self):  # review #4
        class Boom(io.BytesIO):
            def __iter__(self):
                raise ConnectionResetError("reset")
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: Boom(b"")):
            with self.assertRaises(models.ModelError):
                models.complete("t", "hi", retries=1)

    def test_total_timeout_caps_a_runaway_stream(self):  # review #5
        chunks = "".join(json.dumps({"response": "x", "done": False}) + "\n" for _ in range(50)).encode()
        clock = iter(range(0, 10_000, 10))  # every time.time() call advances 10 s
        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(chunks)), \
             mock.patch("looper.models.time.time", side_effect=lambda: next(clock)):
            with self.assertRaises(models.ModelError):
                models.complete("t", "hi", timeout_s=60, retries=0)

    def test_no_context_no_events_still_works(self):
        events.set_current(None)
        body = fake_stream(["ok"], {"prompt_eval_count": 1, "eval_count": 1, "eval_duration": 1})
        with mock.patch("urllib.request.urlopen", return_value=body):
            text, _ = models.complete("t", "hi")
        self.assertEqual(text, "ok")


class TestOllamaOptions(unittest.TestCase):
    def test_images_and_unload_are_sent(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "k.png"
            img.write_bytes(b"\x89PNGfake")
            sent = {}

            def fake_urlopen(req, timeout=None):
                sent.update(json.loads(req.data.decode()))
                return fake_stream(["{}"], {"eval_count": 1, "eval_duration": 1})
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                _, meta = models.complete("t", "hi", images=[img], unload=True, json_mode=True)
        self.assertEqual(sent["images"], [base64.b64encode(b"\x89PNGfake").decode()])
        self.assertEqual(sent["keep_alive"], 0)
        self.assertIs(sent["think"], False)  # thinking models otherwise stall > 300 s in a field we don't read
        self.assertEqual(sent["format"], "json")  # never a schema object for Ollama
        self.assertEqual(meta["images"], [str(img)])

    def test_schema_is_not_sent_to_ollama(self):
        sent = {}

        def fake_urlopen(req, timeout=None):
            sent.update(json.loads(req.data.decode()))
            return fake_stream(['{"a": 1}'], {"eval_count": 1, "eval_duration": 1})
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            data, _ = models.complete_json("t", "hi", schema={"type": "object"})
        self.assertEqual((sent["format"], data), ("json", {"a": 1}))


class TestThinking(unittest.TestCase):
    def test_think_sends_think_and_no_json_format_and_parses_json_from_text(self):
        # think + format json gave empty replies on qwen3.6 (5/5, 2026-09-25): JSON is cut out of the text instead
        sent = {}

        def fake_urlopen(req, timeout=None):
            sent.update(json.loads(req.data.decode()))
            return fake_stream(["Here it is:\n```json\n", '{"a": 1}', "\n```"], {"eval_count": 3, "eval_duration": 1})
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            data, _ = models.complete_json("t", "hi", think=True)
        self.assertIs(sent["think"], True)
        self.assertNotIn("format", sent)
        self.assertGreaterEqual(sent["options"]["num_ctx"], 16384)  # 4096 default: thinking filled it, no answer
        self.assertEqual(data, {"a": 1})


def cli_result(structured=None, result='{"ok": true}', is_error=False, rc=0, stderr=""):
    """Shape of `claude -p --output-format json` (captured from Claude Code 2.1.281, 2026-09-25)."""
    out = {"type": "result", "subtype": "success", "is_error": is_error, "result": result, "session_id": "s1",
           "total_cost_usd": 0.0689, "duration_ms": 4691, "num_turns": 3,
           "usage": {"input_tokens": 1000, "output_tokens": 200},
           "modelUsage": {"claude-sonnet-5": {"inputTokens": 1000, "outputTokens": 200}}}
    if structured is not None:
        out["structured_output"] = structured
    return SimpleNamespace(returncode=rc, stdout=json.dumps(out), stderr=stderr)


class TestClaudeCli(unittest.TestCase):
    def test_command_images_schema_and_meta(self):
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "k.png"
            img.write_bytes(b"p")
            with mock.patch("subprocess.run", return_value=cli_result(structured={"ok": True})) as run:
                data, meta = models.complete_json("direct", "hi", provider="claude", model=None, images=[img],
                                                  schema={"type": "object"})
        self.assertEqual(data, {"ok": True})
        cmd, kw = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(cmd[:4], ["claude", "-p", "--output-format", "json"])
        self.assertEqual(json.loads(cmd[cmd.index("--json-schema") + 1]), {"type": "object"})
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read")
        self.assertEqual(cmd[cmd.index("--add-dir") + 1], str(img.parent))
        self.assertNotIn("--model", cmd)  # model None = the CLI's own default
        self.assertIn(str(img), kw["input"])
        self.assertNotEqual(Path(kw["cwd"]).resolve(), Path.cwd().resolve())  # not the repo: no CLAUDE.md context
        self.assertEqual((meta["provider"], meta["model"], meta["cost"]), ("claude-cli", "claude-sonnet-5", 0.0689))
        self.assertEqual((meta["input_tokens"], meta["output_tokens"]), (1000, 200))

    def test_no_images_means_no_tools_and_model_flag_passed(self):
        with mock.patch("subprocess.run", return_value=cli_result()) as run:
            text, _ = models.complete("t", "hi", provider="claude", model="opus")
        cmd = run.call_args.args[0]
        self.assertEqual(text, '{"ok": true}')
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")

    def test_cli_error_or_missing_binary_is_a_model_error(self):
        with mock.patch("subprocess.run", return_value=cli_result(is_error=True, result="usage limit reached")):
            with self.assertRaises(models.ModelError) as cm:
                models.complete("t", "hi", provider="claude", model=None)
        self.assertIn("usage limit", str(cm.exception))
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("claude")):
            with self.assertRaises(models.ModelError) as cm:
                models.complete("t", "hi", provider="claude", model=None)
        self.assertIn("claude", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
