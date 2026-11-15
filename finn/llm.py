"""Model router. Two tiers over any OpenAI-compatible endpoint:

  cheap  - bulk work: classifying ambiguous filings, pulling structured fields out of a
           page of text. Called often, small prompts, always JSON.
  strong - the one or two calls per company where reasoning matters (the analyst read).

Every call is cached by content hash (filings and transcripts never change), so a
re-run costs nothing. A ledger records calls, tokens and cache hits per tier so the
cost of a session is visible in the app. With no key configured every caller falls
back to a deterministic path - the app still works, it is just less articulate.
"""
import hashlib
import json
import re
import threading
import time

import requests

from . import cache, config

_lock = threading.Lock()
LEDGER = {"cheap": {"calls": 0, "cache_hits": 0, "in": 0, "out": 0},
          "strong": {"calls": 0, "cache_hits": 0, "in": 0, "out": 0}, "errors": 0, "last_error": ""}


def ready():
    return config.llm_ready()


def _model(tier):
    return config.MODEL_STRONG if tier == "strong" and config.MODEL_STRONG else config.MODEL_CHEAP


def chat(tier, system, user, json_mode=True, max_tokens=1500):
    """Returns the model's text, or None when no model is configured or the call fails."""
    if not ready():
        return None
    model = _model(tier)
    key = "llm:" + hashlib.sha256(f"{model}|{system}|{user}|{json_mode}".encode()).hexdigest()
    hit, _ = cache.get(key)
    if hit is not None:
        with _lock:
            LEDGER[tier]["cache_hits"] += 1
        return hit
    # Newer models spend part of the output budget on hidden reasoning, so a tight cap can
    # return an empty answer. Give generous headroom; answers themselves stay short.
    body = {"model": model, "temperature": 0, "max_tokens": max(max_tokens, 4096),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if config.LLM_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_KEY}"
    try:
        r = requests.post(config.LLM_BASE.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=90)
        if r.status_code == 429:  # free-tier rate limit: wait once, then try again
            time.sleep(8)
            r = requests.post(config.LLM_BASE.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=90)
        if r.status_code == 400 and json_mode:  # endpoint without JSON mode: ask in plain text
            body.pop("response_format")
            r = requests.post(config.LLM_BASE.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=90)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"] or ""
        if not text.strip():
            raise RuntimeError("model returned an empty answer")
        usage = data.get("usage") or {}
    except Exception as e:  # noqa: BLE001
        with _lock:
            LEDGER["errors"] += 1
            LEDGER["last_error"] = str(e)[:200]
        return None
    with _lock:
        LEDGER[tier]["calls"] += 1
        LEDGER[tier]["in"] += usage.get("prompt_tokens", 0)
        LEDGER[tier]["out"] += usage.get("completion_tokens", 0)
    cache.put(key, text)
    return text


def parse_json(text):
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                return None
    return None


def chat_json(tier, system, user, max_tokens=1500):
    return parse_json(chat(tier, system, user, json_mode=True, max_tokens=max_tokens))


def status():
    return {"ready": ready(), "provider": config.LLM_PROVIDER if ready() else None,
            "cheap": config.MODEL_CHEAP or None, "strong": config.MODEL_STRONG or config.MODEL_CHEAP or None,
            "ledger": LEDGER}
