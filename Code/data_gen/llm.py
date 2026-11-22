"""Thin client for any OpenAI-compatible endpoint (OpenAI, or llama.cpp's llama-server locally).

Every call is logged to Data/logs/<role>.jsonl with the prompt, the reply and token usage,
so every generated row can be traced and the dataset rebuilt.
`mock=True` returns a caller-supplied answer instead of calling a model (dry runs, tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

from .common import DATA, append_jsonl


class LLM:
    def __init__(self, role: str, cfg: dict, mock: bool = False, log_dir=None):
        self.role, self.cfg, self.mock = role, cfg["models"][role], mock
        self.log = (log_dir or DATA / "logs") / f"{role}.jsonl"
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self.client = None
        if not mock:
            from openai import OpenAI  # imported here so tests run without the package
            key = os.environ.get(self.cfg.get("api_key_env") or "OPENAI_API_KEY", "not-needed")
            self.client = OpenAI(api_key=key, base_url=self.cfg.get("base_url"))

    def json(self, prompt: str, meta: dict | None = None, mock_answer=None, temperature=None) -> dict:
        t0 = time.time()
        if self.mock:
            out, usage = (mock_answer() if callable(mock_answer) else mock_answer), {}
        else:
            out, usage = self._call(prompt, self.cfg.get("temperature") if temperature is None else temperature)
        self.usage["calls"] += 1
        self.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        self.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        append_jsonl(self.log, {"ts": round(t0, 2), "role": self.role, "model": self.cfg["model"], "mock": self.mock,
                                "prompt_sha": hashlib.sha1(prompt.encode()).hexdigest()[:12], "meta": meta or {},
                                "seconds": round(time.time() - t0, 2), "usage": usage, "prompt": prompt, "response": out})
        return out

    def _call(self, prompt: str, temperature) -> tuple[dict, dict]:
        last = None
        for attempt in range(4):
            try:
                r = self.client.chat.completions.create(
                    model=self.cfg["model"], temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"})
                text = r.choices[0].message.content
                usage = {"prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens} if r.usage else {}
                return parse_json(text), usage
            except Exception as e:  # network errors, rate limits, bad JSON
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.role} call failed after retries: {last}")


def parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def write_batch_file(path, requests: list[tuple[str, str]], cfg: dict, role: str = "generator") -> None:
    """Write an OpenAI Batch API input file: one chat request per (custom_id, prompt)."""
    m = cfg["models"][role]
    with open(path, "w", encoding="utf-8") as f:
        for cid, p in requests:
            f.write(json.dumps({"custom_id": cid, "method": "POST", "url": "/v1/chat/completions",
                                "body": {"model": m["model"], "temperature": m.get("temperature"),
                                         "response_format": {"type": "json_object"},
                                         "messages": [{"role": "user", "content": p}]}}) + "\n")


def read_batch_output(path) -> dict[str, dict]:
    """Map custom_id -> parsed JSON reply from an OpenAI Batch API output file."""
    out = {}
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        body = (r.get("response") or {}).get("body") or {}
        try:
            out[r["custom_id"]] = parse_json(body["choices"][0]["message"]["content"])
        except Exception:
            out[r["custom_id"]] = None
    return out
