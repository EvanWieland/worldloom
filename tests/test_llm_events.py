"""Dashboard sees the director's LLM calls: engine -> direct stage -> models -> events.jsonl -> observe (TOKENS panel).
Only the transport is faked (Ollama HTTP / the claude subprocess). No GPU/LLM."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from looper import observe
from looper.engine import Engine
from looper.stages import direct

FACTS = {"scene": "A waterfall.", "style": "Photorealistic, cinematic", "keyframe_details": "white water",
         "moving": ["the water falls steadily"], "fixed": ["the rocks"], "negatives": [], "adaptations": []}


def ollama_reply(*a, **k):
    lines = [json.dumps({"response": json.dumps(FACTS), "done": False}),
             json.dumps({"response": "", "done": True, "prompt_eval_count": 400, "eval_count": 90,
                         "eval_duration": 3_000_000_000})]
    return io.BytesIO(("\n".join(lines) + "\n").encode())


def claude_reply(*a, **k):
    out = {"is_error": False, "result": "", "structured_output": FACTS, "total_cost_usd": 0.05, "session_id": "s",
           "usage": {"input_tokens": 900, "output_tokens": 150}, "modelUsage": {"claude-sonnet-5": {}}}
    return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")


class TestDirectorCallsReachTheDashboard(unittest.TestCase):
    def run_direct(self, root, provider, model):
        eng = Engine(root / "runs" / "r1", "r1", original_prompt="a waterfall")
        eng.run_stage("direct", direct.VERSION, {"prompt": "a waterfall", "provider": provider, "model": model}, {},
                      direct.run)
        return observe.Observer(root).poll()

    def test_ollama_call_shows_request_and_response(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("urllib.request.urlopen", side_effect=ollama_reply), \
                mock.patch("looper.models.STREAM_EMIT_INTERVAL_S", 0.0):
            snap = self.run_direct(Path(d), "ollama", "gemma4:12b")
        self.assertTrue(any(t.startswith("▶ gemma4:12b · direct") for t in snap.tokens), snap.tokens)
        self.assertTrue(any(t.startswith("✓ gemma4:12b: in 400 · out 90") for t in snap.tokens), snap.tokens)
        self.assertEqual(snap.models.llm_last["output_tokens"], 90)

    def test_claude_cli_call_is_labelled_by_provider_when_model_is_the_cli_default(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.run", side_effect=claude_reply):
            snap = self.run_direct(Path(d), "claude", None)
        self.assertTrue(any(t.startswith("▶ claude-cli · direct") for t in snap.tokens), snap.tokens)
        self.assertTrue(any(t.startswith("✓ claude-sonnet-5: in 900 · out 150") for t in snap.tokens), snap.tokens)


if __name__ == "__main__":
    unittest.main()
