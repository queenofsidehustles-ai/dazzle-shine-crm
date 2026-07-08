"""Lightweight text translation via OpenRouter (Claude Haiku) — reuses the
same key/model as the Content Studio. Fails soft: returns the original text
if the API key is missing or the call errors, so messaging never breaks."""
import os
import requests

_LANG = {'es': 'Spanish', 'en': 'English'}


def translate(text, target='es'):
    text = (text or '').strip()
    if not text:
        return text
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        return text
    lang = _LANG.get(target, target)
    prompt = (
        f"Translate the following text message to {lang}. It's a casual message "
        f"between a house-cleaning business owner and a cleaner. Keep it natural, "
        f"friendly, and concise. If it is already in {lang}, return it unchanged. "
        f"Reply with ONLY the translation — no quotes, no notes.\n\n{text}"
    )
    try:
        res = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'model': 'anthropic/claude-haiku-4-5',
                  'messages': [{'role': 'user', 'content': prompt}],
                  'max_tokens': 600, 'temperature': 0.2},
            timeout=15,
        )
        data = res.json()
        out = (data['choices'][0]['message']['content'] or '').strip()
        return out or text
    except Exception:
        return text
