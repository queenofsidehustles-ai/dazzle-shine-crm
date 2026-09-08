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
ROUTER_MODEL = os.environ.get('SPEECH_MODEL_ROUTER', 'openai/gpt-4o-mini-tts')
VOICE = os.environ.get('SPEECH_VOICE', 'sage')

# How she is asked to sound. Warm and unhurried, not bright and salesy --
# she is mostly reading out money, some of it bad news.
MANNER = (os.environ.get('SPEECH_MANNER') or
          'Warm, calm and unhurried, like a trusted assistant talking to '
          'someone they know well. Natural pace, gentle downward intonation '
          'at the end of sentences. Never bright, chirpy or salesy.')

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
    """(url, model, key) for whoever can speak, or None if nobody can.

    A direct OpenAI key wins when one is set, because it is one hop fewer.
    Otherwise the OpenRouter key that is already answering questions does this
    job too, and nothing new has to be signed up for.
    """
    direct = (os.environ.get('OPENAI_API_KEY') or '').strip()
    if direct:
        return OPENAI_URL, MODEL, direct
    router = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
    if router:
        return ROUTER_URL, ROUTER_MODEL, router
    return None


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
    url, model, key = who
    if len(text) > MAX_ONE:
        text = text[:MAX_ONE]
    if remaining() < len(text):
        return None

    _count(len(text))
    import requests

    def attempt(body):
        try:
            return requests.post(url, timeout=30, headers={
                'Authorization': f'Bearer {key}',
                'Content-Type': 'application/json',
            }, json=body)
        except Exception as e:
            _trouble(f'could not reach the voice service: {type(e).__name__}')
            return None

    body = {'model': model, 'voice': VOICE, 'input': text,
            'instructions': MANNER, 'response_format': 'mp3'}
    r = attempt(body)
    if r is None:
        return None

    # `instructions` is how the voice is told to sound warm rather than flat,
    # and it is the newest part of this API. If a provider has not got it yet,
    # the answer should still be read aloud in a plain voice rather than not at
    # all -- so a refusal is tried once more without it.
    if r.status_code == 400 and 'instructions' in body:
        body.pop('instructions')
        r = attempt(body)
        if r is None:
            return None

    # An error comes back as JSON where audio should be. Reading the content
    # type is how we tell the two apart without guessing from the length.
    if r.status_code != 200 or 'audio' not in (r.headers.get('Content-Type') or ''):
        detail = r.text[:200] if r.status_code != 200 else 'no audio in the reply'
        _trouble(f'voice service said {r.status_code}: {detail}')
        return None
    return r.content


def _trouble(detail):
    """The owner hears the browser voice. Somebody who can fix it sees this."""
    try:
        import errors
        errors.capture(RuntimeError(f'speech: {detail}'), path='/ask/voice',
                       method='POST')
    except Exception:
        pass
