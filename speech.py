"""Reading Nana's answers out loud, in a voice worth listening to.

The browser can already do this for nothing, and it sounds like it. Every
device ships a speech engine, picks its flattest voice by default, and the
result is the tone of a car park announcement reading out your takings.

So the words are sent to a real voice instead, and the audio comes back and
plays. The browser voice stays as the floor: if there is no key, if the
service is down, if this month's allowance is spent, the page falls back to
it and nobody is told anything. A slightly flat answer beats no answer, and
it beats an error message about quotas that means nothing to somebody
holding a mop.

## Why this cannot run up a bill

Two limits, both hard.

Nana already refuses to answer more than MONTHLY_LIMIT questions a month, so
the number of things there are to read out is capped before this file is
reached. On top of that, this counts characters spoken per company per month
and stops paying for them at CAP_CHARS. It does not stop speaking -- it drops
to the free browser voice for the rest of the month.

That matters because the company most likely to hit the ceiling is the one
using the product hardest, and switching their assistant off is the wrong
thing to do to your best customer.
"""
import os

# Two ways in, and the one already paid for comes first.
#
# OpenRouter carries the same model behind an endpoint with the same shape, and
# there is already a working OpenRouter key in this deployment with a card
# behind it. Going direct to OpenAI meant a second account, a second card and a
# second bill for exactly the same voice -- which is a poor trade at any time
# and a worse one when the card is being declined.
#
# Both URLs and the model names were checked against the live services rather
# than typed from memory. The last model name in this codebase was typed from
# memory, did not exist, and every question came back "I did not follow that".
OPENAI_URL = 'https://api.openai.com/v1/audio/speech'
ROUTER_URL = 'https://openrouter.ai/api/v1/audio/speech'

# gpt-4o-mini-tts takes an `instructions` string, which is the only reason it
# is here rather than tts-1: the voice can be told how to sound, and the
# complaint that started this was that it had no personality.
MODEL = os.environ.get('SPEECH_MODEL', 'gpt-4o-mini-tts')

# Which voice models to try through OpenRouter, best first.
#
# The first version named one model and nothing else. It was not served, every
# request failed, the page fell back to the device voice exactly as designed --
# and because that fallback is deliberately silent, it looked like the natural
# voice simply sounded bad. I had checked that a web page existed for that
# model, which is not the same as the API serving it.
#
# So it tries them in order and remembers the one that answers. Being wrong
# about any single name now costs a retry rather than the whole feature.
ROUTER_MODELS = [m.strip() for m in (
    os.environ.get('SPEECH_MODELS_ROUTER')
    or 'openai/gpt-4o-mini-tts,deepgram/aura-2,microsoft/mai-voice-2,'
       'hexgrad/kokoro-82m,mistralai/voxtral-mini-tts-2603'
).split(',') if m.strip()]

# Which one last worked, so the failures are paid for once rather than nightly.
WORKING_KEY = 'speech_model_working'

# 60,000 characters is about 300 answers of the length Nana actually gives,
# which is the most she will answer in a month anyway. At $15 per million
# characters that is 90 cents per company per month, and it is a ceiling
# rather than an estimate.
CAP_CHARS = int(os.environ.get('SPEECH_CAP_CHARS') or 60_000)

# Nothing longer than this is ever sent. An answer is three sentences; a
# 20,000-character request would be a bug, and a bug should not be expensive.
MAX_ONE = 1200


def _month_key():
    from datetime import date
    return f'speech_chars_{date.today():%Y-%m}'


def used_this_month():
    from models import BusinessSetting
    try:
        return int(BusinessSetting.get(_month_key()) or 0)
    except (TypeError, ValueError):
        return 0


def remaining():
    return max(0, CAP_CHARS - used_this_month())


def _count(chars):
    """Spend the allowance before the call, not after.

    Counting after would mean a request that timed out cost money and counted
    for nothing, which is the direction in which a bill runs away quietly.
    """
    from models import BusinessSetting
    from extensions import db
    BusinessSetting.set(_month_key(), str(used_this_month() + chars))
    db.session.commit()


def provider():
    """(url, models, key) for whoever can speak, or None if nobody can.

    A direct OpenAI key wins when one is set, because it is one hop fewer and
    the model name there is certain. Otherwise the OpenRouter key that is
    already answering questions does this job too, and nothing new has to be
    signed up for.
    """
    direct = (os.environ.get('OPENAI_API_KEY') or '').strip()
    if direct:
        return OPENAI_URL, [MODEL], direct
    router = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if router:
        known = _remembered()
        ordered = ([known] + [m for m in ROUTER_MODELS if m != known]
                   if known else list(ROUTER_MODELS))
        return ROUTER_URL, ordered, router
    return None


def _remembered():
    from models import BusinessSetting
    try:
        return (BusinessSetting.get(WORKING_KEY) or '').strip() or None
    except Exception:
        return None


def _remember(model):
    from extensions import db
    from models import BusinessSetting
    try:
        if _remembered() != model:
            BusinessSetting.set(WORKING_KEY, model)
            db.session.commit()
    except Exception:
        pass


def configured():
    return provider() is not None


def say(text):
    """Audio for `text`, or None to mean 'let the browser read it'.

    None is not an error and is never explained to anybody. It is the normal
    answer when no key is set up, when the month's allowance is gone, or when
    the service did not answer.
    """
    text = (text or '').strip()
    if not text:
        return None
    who = provider()
    if not who:
        return None
    url, models, key = who
    if len(text) > MAX_ONE:
        text = text[:MAX_ONE]
    if remaining() < len(text):
        return None

    _count(len(text))
    import requests

    tried = []
    for model in models:
        body = {'model': model, 'input': text, 'response_format': 'mp3'}
        # Voice names and the `instructions` string are OpenAI's. Sending them
        # to a provider that has never heard of them is a refusal, so they go
        # only where they mean something.
        if model.endswith('gpt-4o-mini-tts') or url == OPENAI_URL:
            body['voice'] = VOICE
            body['instructions'] = MANNER
        audio, why = _attempt(requests, url, key, body)
        if audio:
            _remember(model)
            return audio
        tried.append(f'{model}: {why}')

    # Nobody could speak. The page reads it with the device voice and says so;
    # this is the only place the actual reason exists.
    _trouble('no voice model answered — ' + ' | '.join(tried)[:600])
    return None


def _attempt(requests, url, key, body):
    """(audio, why-not) for one model."""
    try:
        r = requests.post(url, timeout=30, headers={
            'Authorization': f'Bearer {key}',
            'Content-Type': 'application/json',
        }, json=body)
    except Exception as e:
        return None, type(e).__name__

    if r.status_code == 200 and 'audio' in (r.headers.get('Content-Type') or ''):
        return r.content, None

    # `instructions` is the newest part of this API. A refusal is worth one
    # more try without it before giving up on the model entirely.
    if r.status_code == 400 and 'instructions' in body:
        body = {k: v for k, v in body.items() if k != 'instructions'}
        try:
            r = requests.post(url, timeout=30, headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
            }, json=body)
        except Exception as e:
            return None, type(e).__name__
        if r.status_code == 200 and 'audio' in (r.headers.get('Content-Type') or ''):
            return r.content, None
    return None, f'{r.status_code} {r.text[:120]}'


def _trouble(detail):
    """The owner hears the browser voice. Somebody who can fix it sees this."""
    try:
        import errors
        errors.capture(RuntimeError(f'speech: {detail}'), path='/ask/voice',
                       method='POST')
    except Exception:
        pass
