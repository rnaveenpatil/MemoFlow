"""OpenAI-compatible LLM client for hosted and local providers.

Set LLM_BASE_URL, LLM_MODEL_ID and (for hosted providers) LLM_API_KEY in .env.
Local endpoints on localhost/127.0.0.1 may be used without an API key.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from MemoFlow.config import LLM_BASE_URL, LLM_MODEL_ID, LLM_API_KEY


def _settings():
    # Environment overrides also allow settings to be changed by a launcher.
    base_url = (os.environ.get("LLM_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or LLM_BASE_URL).strip().rstrip("/")
    model = (os.environ.get("LLM_MODEL_ID")
             or os.environ.get("OPENAI_MODEL")
             or LLM_MODEL_ID).strip()
    api_key = (os.environ.get("LLM_API_KEY")
               or os.environ.get("GROQ_API_KEY")
               or os.environ.get("OPENAI_API_KEY")
               or LLM_API_KEY or "").strip()
    host = (urlparse(base_url).hostname or "").lower()
    local_endpoint = host in {"localhost", "127.0.0.1", "::1"}
    return base_url, model, api_key, local_endpoint


def call_llm(prompt, system_prompt=None, max_tokens=800):
    """Call a hosted or local OpenAI-compatible chat-completions endpoint.

    Returns None on configuration/network/provider errors. The caller must treat
    None as unavailable and must not fabricate an answer.
    """
    base_url, model, api_key, local_endpoint = _settings()
    if not base_url or not model:
        print("[MemoFlow LLM] Configure LLM_BASE_URL and LLM_MODEL_ID in .env.",
              file=sys.stderr)
        return None
    if not api_key and not local_endpoint:
        print("[MemoFlow LLM] LLM_API_KEY is missing for this hosted endpoint.",
              file=sys.stderr)
        return None

    endpoint = f"{base_url}/chat/completions"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "MemoFlow/1.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    started = time.monotonic()
    request = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
        choices = raw.get("choices") or []
        if not choices:
            raise ValueError("provider response did not contain choices")
        message = choices[0].get("message") or {}
        answer = message.get("content")
        if isinstance(answer, list):
            # Some compatible providers return content blocks.
            answer = "".join(
                part.get("text", "") for part in answer if isinstance(part, dict)
            )
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("provider returned an empty message")

        usage = raw.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
        # Pricing differs by provider/model; do not report a fabricated cost.
        return {
            "text": answer.strip(),
            "usage": {
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "cost_usd": 0.0,
                "ms": int((time.monotonic() - started) * 1000),
            },
        }
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:700]
        except Exception:
            detail = str(exc)
        print(f"[MemoFlow LLM] HTTP {exc.code}: {detail}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"[MemoFlow LLM] Connection failed: {exc}", file=sys.stderr)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"[MemoFlow LLM] Invalid provider response: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[MemoFlow LLM] Request failed: {exc}", file=sys.stderr)
    return None


def compute_usage(prompt_text, output_text, elapsed_ms):
    """Fallback token estimate; cost is unknown without provider pricing."""
    input_tokens = max(0, len(prompt_text) // 4)
    output_tokens = max(0, len(output_text) // 4)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": 0.0,
        "ms": max(0, elapsed_ms),
    }
