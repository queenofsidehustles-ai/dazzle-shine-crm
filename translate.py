"""Lightweight text translation via Claude (the platform's Claude API credits),
or OpenRouter when no Claude key is set. Fails soft: returns the original text
if the API key is missing or the call errors, so messaging never breaks."""
import os
import requests

_LANG = {'es': 'Spanish', 'en': 'English'}


def translate(text, target='es'):
    text = (text or '').strip()
    if not text:
        return text
    import demo_guard
    if demo_guard.active():
        return text
    import llm
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key and not llm.ready():
        return text
    lang = _LANG.get(target, target)
    prompt = (
        f"Translate the following text message to {lang}. It's a casual message "
        f"between a house-cleaning business owner and a cleaner. Keep it natural, "
        f"friendly, and concise. If it is already in {lang}, return it unchanged. "
        f"Reply with ONLY the translation — no quotes, no notes.\n\n{text}"
    )
    if llm.ready():
        try:
            return llm.complete('You translate short messages. Reply with only the translation.',
                                prompt, max_tokens=1200, timeout=15) or text
        except Exception:
            if not api_key:
                return text
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
