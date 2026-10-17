"""Minimal OpenAI-compatible chat client (works with OpenAI / DeepSeek /
Moonshot-Kimi / OpenRouter / Ollama — anything exposing /chat/completions).

Configured entirely via environment variables:
    LLM_API_BASE   default https://api.openai.com/v1
    LLM_API_KEY    required for LLM mode; absent -> fallback rule-based mode
    LLM_MODEL      default gpt-4o-mini
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

log = logging.getLogger("llm.client")


class LLMClient:
    def __init__(self):
        self.base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
        self.key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.enabled = bool(self.key)
        if not self.enabled:
            log.warning("LLM_API_KEY not set — processing layer runs in fallback mode")

    def chat_json(self, system: str, user: str, temperature: float = 0.3,
                  max_tokens: int = 1200, retries: int = 2) -> dict | list | None:
        """Send a chat request and parse the reply as JSON (tolerates code fences)."""
        if not self.enabled:
            return None
        payload = json.dumps({
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode()
        last_err = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(
                    f"{self.base}/chat/completions", data=payload,
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self.key}"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read())
                content = data["choices"][0]["message"]["content"]
                return parse_json_loose(content)
            except Exception as e:
                last_err = e
                log.warning("LLM call failed (attempt %d/%d): %s",
                            attempt + 1, retries + 1, e)
        log.error("LLM call gave up: %s", last_err)
        return None


def parse_json_loose(text: str):
    """Parse JSON possibly wrapped in ```json fences or stray prose."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # last resort: outermost {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        s, e = text.find(opener), text.rfind(closer)
        if s != -1 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    log.error("could not parse JSON from LLM output: %.200s", text)
    return None
