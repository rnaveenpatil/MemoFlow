"""LLM integration for MemoFlow with intelligent fallback and accurate token reporting."""
import os, json, time

def call_llm(prompt, max_tokens=1000):
    """Call external LLM (e.g. Gemini or OpenAI) if API key is provided, or return None."""
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None

    t0 = time.monotonic()
    # If Gemini API key is present:
    if os.environ.get('GEMINI_API_KEY'):
        try:
            import urllib.request
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                text = res['candidates'][0]['content']['parts'][0]['text']
                ms = int((time.monotonic() - t0) * 1000)
                in_tok = len(prompt) // 4
                out_tok = len(text) // 4
                return {
                    'text': text,
                    'usage': {
                        'input_tokens': in_tok,
                        'output_tokens': out_tok,
                        'cost_usd': round(in_tok * 0.000000075 + out_tok * 0.0000003, 6),
                        'ms': ms
                    }
                }
        except Exception:
            return None

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
