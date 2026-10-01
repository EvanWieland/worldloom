"""Model adapter: complete(task, prompt, ...) -> (text, metadata). See ARCHITECTURE.md
"Model abstraction". Providers are swappable behind this one function; only Ollama (local)
exists today, per CLAUDE.md invariant 13 (local-only until the user says otherwise).
stdlib only -- no requests/httpx dependency for one JSON POST.
"""
from __future__ import annotations

import base64
import http.client
import json
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from looper import events

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen3:8b"
PROMPT_EVENT_CHARS = 4000  # events carry the prompt for the dashboard TOKENS panel (local, no secrets)
STREAM_EMIT_INTERVAL_S = 0.5
THINK_NUM_CTX = 16384


class ModelError(RuntimeError):
    pass


class _StreamIncomplete(RuntimeError):
    """Stream closed without Ollama's final done chunk: truncated output, retried."""


def complete(
    task: str,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    json_mode: bool = False,
    timeout_s: float = 120.0,
    retries: int = 1,
    images: list[Path] | None = None,
    unload: bool = False,
    provider: str = "ollama",
    schema: dict | None = None,
    think: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Calls the local Ollama server. Returns (text, metadata) where metadata carries
    everything ARCHITECTURE.md asks a model call to record: provider, model, tokens,
    latency, retries, request id, stage/task, timestamp. Cost is null (local, free).
    No API key is used or needed for Ollama; nothing here ever holds a secret.
    images: for vision models. unload: free the model's VRAM right after (a GPU video stage follows).
    provider "claude" (ADR 0008, opt-in): the Claude Code CLI; --json-schema enforces JSON there. Ollama gets plain "json" format --
    a schema object hung gemma4 for > 300 s (2026-09-25)."""
    if provider == "claude":
        return _complete_claude(task, prompt, model=model, images=images, schema=schema if json_mode else None,
                                timeout_s=timeout_s)
    # think off by default: thinking models (qwen3, gemma4) stalled > 300 s in a "thinking" field we don't read and
    # returned empty responses (2026-09-25); ignored by models without a thinking mode (checked on gemma3:4b).
    # think on + format json returned empty replies (qwen3.6, 5/5): then complete_json cuts the JSON out of the text.
    payload: dict[str, Any] = {"model": model, "prompt": prompt, "stream": True, "think": think}
    if json_mode and not think:
        payload["format"] = "json"
    if think:  # Ollama's 4096-token default filled with thinking before any answer (qwen3.6, 5/5 at ~128 s)
        payload["options"] = {"num_ctx": THINK_NUM_CTX}
    if images:
        payload["images"] = [base64.b64encode(Path(p).read_bytes()).decode("ascii") for p in images]
    if unload:
        payload["keep_alive"] = 0

    request_id = uuid.uuid4().hex[:12]
    events.emit_current("model.request", {"provider": "ollama", "model": model, "task": task,
                                          "prompt": prompt[:PROMPT_EVENT_CHARS], "prompt_chars": len(prompt)})
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            req = urllib.request.Request(
                OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            parts: list[str] = []
            n_out, last_emit, final, sent = 0, 0.0, {}, 0
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                for raw in resp:
                    if not raw.strip():
                        continue
                    chunk = json.loads(raw.decode("utf-8"))
                    if chunk.get("error"):  # e.g. OOM mid-generation, sent as a 200 stream line
                        raise ModelError(f"Ollama error mid-stream (model={model}): {chunk['error']}")
                    if time.time() - t0 > timeout_s:  # total cap; the socket timeout only bounds token gaps
                        raise TimeoutError(f"generation exceeded {timeout_s} s")
                    if chunk.get("done"):
                        final = chunk
                        break
                    parts.append(chunk.get("response", ""))
                    n_out += 1  # Ollama streams ~one token per chunk
                    now = time.time()
                    if now - last_emit >= STREAM_EMIT_INTERVAL_S:
                        el = now - t0
                        events.emit_current("model.stream", {
                            "provider": "ollama", "model": model, "input_tokens": None,
                            "output_tokens_so_far": n_out, "elapsed_s": round(el, 2),
                            "tokens_per_s": round(n_out / el, 1) if el > 0 else None,
                            "text": "".join(parts[sent:])})  # the text generated since the previous event
                        last_emit, sent = now, len(parts)
            if not final:
                raise _StreamIncomplete(f"stream ended without a done chunk after {n_out} tokens")
            latency = time.time() - t0
            tokens_in = final.get("prompt_eval_count")
            tokens_out = final.get("eval_count", n_out)
            eval_ns = final.get("eval_duration") or 0
            tok_per_s = (tokens_out / (eval_ns / 1e9)) if tokens_out and eval_ns else None
            meta = {
                "provider": "ollama", "model": model, "task": task,
                "input_tokens": tokens_in, "output_tokens": tokens_out,
                "latency_s": round(latency, 3), "tokens_per_s": round(tok_per_s, 1) if tok_per_s else None,
                "retries": attempt, "cost": None, "request_id": request_id,
                "timestamp": t0, "images": [str(p) for p in images or []],
            }
            if sent < len(parts):
                events.emit_current("model.stream", {"provider": "ollama", "model": model, "output_tokens_so_far": n_out,
                                                     "text": "".join(parts[sent:])})
            events.emit_current("model.response", {k: meta[k] for k in (
                "provider", "model", "input_tokens", "output_tokens", "tokens_per_s", "latency_s", "request_id")})
            return "".join(parts), meta
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError,
                http.client.HTTPException, _StreamIncomplete) as e:
            last_err = e
    raise ModelError(f"Ollama call failed after {retries + 1} attempt(s) (model={model}): {last_err}") from last_err


def complete_json(task: str, prompt: str, *, model: str = DEFAULT_MODEL, schema: dict | None = None,
                  **kw) -> tuple[dict, dict]:
    """complete() with json_mode=True, parsed. Raises ModelError with the raw text attached
    (via args) if the model didn't return valid JSON even in json mode -- local 8B models
    occasionally do this."""
    text, meta = complete(task, prompt, model=model, json_mode=True, schema=schema, **kw)
    try:
        if kw.get("think") and "{" in text and "}" in text:  # no JSON mode while thinking: object inside prose/fences
            text = text[text.index("{"):text.rindex("}") + 1]
        return json.loads(text), meta
    except json.JSONDecodeError as e:
        raise ModelError(f"model did not return valid JSON for task={task}: {e}\n--- raw ---\n{text[:2000]}") from e


def _complete_claude(task: str, prompt: str, *, model: str | None, images, schema: dict | None,
                     timeout_s: float) -> tuple[str, dict[str, Any]]:
    """Claude Code CLI, headless (`claude -p`), on the user's own login -- no API key (user decision 2026-09-25;
    Codex / Gemini CLIs may follow). The CLI reads images itself (Read tool, limited to their folders) and runs in a
    temp dir so this repo's CLAUDE.md never enters the prompt. cost = the CLI's API-equivalent figure."""
    images = [Path(p).resolve() for p in images or []]
    if images:
        prompt = "Read these image files first:\n" + "\n".join(str(p) for p in images) + "\n\n" + prompt
    cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence",
           "--tools", "Read" if images else "", "--allowedTools", "Read"]
    for d in sorted({str(p.parent) for p in images}):
        cmd += ["--add-dir", d]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", model]
    events.emit_current("model.request", {"provider": "claude-cli", "model": model, "task": task,
                                          "prompt": prompt[:PROMPT_EVENT_CHARS], "prompt_chars": len(prompt)})
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory(prefix="looper_claude_") as cwd:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                                  timeout=timeout_s, cwd=cwd)
        out = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:  # CLI missing, timeout, not JSON
        raise ModelError(f"claude CLI failed (model={model}): {type(e).__name__}: {e}") from e
    if proc.returncode or out.get("is_error"):
        raise ModelError(f"claude CLI error (rc={proc.returncode}): {out.get('result')} {proc.stderr[:500]}")
    text = json.dumps(out["structured_output"]) if "structured_output" in out else out.get("result", "")
    usage = out.get("usage") or {}
    tin, tout = usage.get("input_tokens"), usage.get("output_tokens")
    latency = time.time() - t0
    meta = {"provider": "claude-cli", "model": next(iter(out.get("modelUsage") or {}), model), "task": task,
            "input_tokens": tin, "output_tokens": tout, "latency_s": round(latency, 3),
            "tokens_per_s": round(tout / latency, 1) if tout and latency > 0 else None, "retries": 0,
            "cost": out.get("total_cost_usd"), "request_id": out.get("session_id"), "timestamp": t0,
            "images": [str(p) for p in images], "num_turns": out.get("num_turns")}
    events.emit_current("model.response", {k: meta[k] for k in (
        "provider", "model", "input_tokens", "output_tokens", "tokens_per_s", "latency_s", "request_id")})
    return text, meta
