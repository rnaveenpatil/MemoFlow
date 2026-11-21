"""LLM integration for MemoFlow supporting Groq, OpenAI-compatible APIs, and local fallback."""
import os, json, time, sys
import urllib.request
import urllib.error
from MemoFlow.config import LLM_BASE_URL, LLM_MODEL_ID, LLM_API_KEY

def call_llm(prompt, system_prompt=None, max_tokens=800):
    """Call Groq / OpenAI-compatible endpoint if API key is provided, or return None."""
    api_key = LLM_API_KEY
    if not api_key or api_key == 'your_groq_api_key_here':
        return None

    endpoint = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    t0 = time.monotonic()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": LLM_MODEL_ID,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "MemoFlow/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_response = json.loads(resp.read().decode('utf-8'))
            ms = int((time.monotonic() - t0) * 1000)

            choice = raw_response.get('choices', [{}])[0]
            text = choice.get('message', {}).get('content', '')

            usage = raw_response.get('usage', {})
            in_tok = usage.get('prompt_tokens', len(prompt) // 4)
            out_tok = usage.get('completion_tokens', len(text) // 4)

            # Standard cost estimation for Groq
            cost = round(in_tok * 0.0000005 + out_tok * 0.0000015, 6)

            return {
                'text': text,
                'usage': {
                    'input_tokens': in_tok,
                    'output_tokens': out_tok,
                    'cost_usd': cost,
                    'ms': ms
                }
            }
    except Exception as e:
        print(f"[MemoFlow LLM] Warning: LLM call failed ({e}), using fallback.", file=sys.stderr)
        return None

def compute_usage(prompt_text, output_text, elapsed_ms):
    """Compute and format standard usage object."""
    in_tokens = min(3500, max(50, len(prompt_text) // 4))
    out_tokens = min(500, max(20, len(output_text) // 4))
    cost = round(in_tokens * 0.0000005 + out_tokens * 0.0000015, 6)
    return {
        'input_tokens': in_tokens,
        'output_tokens': out_tokens,
        'cost_usd': cost,
        'ms': max(10, elapsed_ms)
    }
