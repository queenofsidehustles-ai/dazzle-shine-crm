"""One door to the Claude API.

Akye's writing and thinking used to go through OpenRouter, paid separately.
The Claude Max plan behind Akye now comes with monthly Claude API credits, so
everything that can run on Claude does, through here. OpenRouter stays as the
fallback: with no ANTHROPIC_API_KEY set, every caller behaves exactly as it
did before.

Two models, because the jobs differ in cost and difficulty:

- FAST: short writing jobs -- an email draft, a translation, a social post.
- SMART: Nana working out what an owner asked, looking things up in several
  steps, and answering. Haiku 5.5 by default; set NANA_MODEL to a Sonnet
  model if a business needs more depth and the credits allow it.
"""
import os

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'

FAST_MODEL = os.environ.get('CLAUDE_FAST_MODEL', 'claude-haiku-5-5')
SMART_MODEL = os.environ.get('NANA_MODEL', 'claude-haiku-5-5')


class ClaudeError(Exception):
    """The API answered with an error, or did not answer."""


class ClaudeUnreachable(ClaudeError):
    """The request never got an answer: network, timeout."""


def key():
    return (os.environ.get('ANTHROPIC_API_KEY') or '').strip()


def ready():
    """Claude is set up for this deployment, and this is not the demo."""
    if not key():
        return False
    try:
        import demo_guard
        if demo_guard.active():
            return False
    except Exception:
        pass
    return True


def post(body, timeout=30):
    """Send one Messages API request. Returns the parsed reply or raises."""
    import time
    import requests
    for attempt in (1, 2):
        try:
            r = requests.post(API_URL, timeout=timeout, json=body, headers={
                'x-api-key': key(),
                'anthropic-version': API_VERSION,
                'content-type': 'application/json',
            })
            out = r.json()
        except Exception as e:
            raise ClaudeUnreachable(f'could not reach Claude: {type(e).__name__}') from e
        if isinstance(out, dict) and out.get('type') != 'error':
            return out
        err = (out.get('error') if isinstance(out, dict) else None) or {}
        # Busy or rate-limited is usually gone a moment later. One more try.
        if attempt == 1 and (getattr(r, 'status_code', 0) in (429, 529)
                             or err.get('type') in ('overloaded_error', 'rate_limit_error')):
            time.sleep(1.5)
            continue
        raise ClaudeError(str(err.get('message') or out)[:200])


def text_of(reply):
    """The written part of a reply, thinking and tool calls left out."""
    return '\n\n'.join((b.get('text') or '').strip()
                       for b in (reply.get('content') or [])
                       if b.get('type') == 'text' and (b.get('text') or '').strip())


def cached_system(text):
    """The system prompt as a cacheable block.

    The business profile and instructions are the same on every step of a
    question and across a conversation, so they are cached: later reads cost
    a tenth of the price. Below the model's minimum size the marker is simply
    ignored, so it is safe to always send.
    """
    return [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]


def complete(system, user, max_tokens=600, model=None, timeout=30):
    """One question, one written answer. Raises ClaudeError on failure."""
    reply = post({'model': model or FAST_MODEL, 'max_tokens': max_tokens,
                  'system': system,
                  'messages': [{'role': 'user', 'content': user}]},
                 timeout=timeout)
    said = text_of(reply)
    if not said:
        raise ClaudeError(f'empty reply (stop_reason={reply.get("stop_reason")})')
    return said
