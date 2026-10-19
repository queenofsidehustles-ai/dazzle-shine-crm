"""Run a disposable Akye business, with the Anthropic call intercepted at the
HTTP boundary instead of inside setup_assistant.

The existing suite replaces setup_assistant._post, so nothing it runs ever
builds a real request body. That is the seam the wrong model name lived in for
a day: every test passed while the thing the app actually puts on the wire was
never looked at. Here the app's own llm/requests path runs end to end and the
outgoing body is written down.
"""
import json, os, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = pathlib.Path(os.environ['WIRE_LOG'])
MODE = os.environ.get('PROVIDER_MODE', 'ok')

import requests

_real_post = requests.post


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def record(body):
    with OUT.open('a') as f:
        f.write(json.dumps(body) + '\n')


SCRIPT_FILE = pathlib.Path(os.environ['SCRIPT_FILE'])
MODE_FILE = pathlib.Path(os.environ['MODE_FILE'])


def next_reply():
    """Pop the next scripted reply. The driver writes these between steps."""
    try:
        items = json.loads(SCRIPT_FILE.read_text() or '[]')
    except Exception:
        items = []
    if not items:
        return None
    head, rest = items[0], items[1:]
    SCRIPT_FILE.write_text(json.dumps(rest))
    return head


def mode():
    try:
        return (MODE_FILE.read_text() or 'ok').strip()
    except Exception:
        return 'ok'


def fake_post(url, *a, **kw):
    if 'api.anthropic.com' not in str(url):
        return _real_post(url, *a, **kw)
    body = kw.get('json') or {}
    record({'url': str(url), 'model': body.get('model'),
            'max_tokens': body.get('max_tokens'),
            'has_tools': bool(body.get('tools')),
            'headers': sorted((kw.get('headers') or {}).keys())})
    m = mode()
    if m == 'not_found':
        # Exactly what a model name that does not exist comes back as.
        return FakeResponse({'type': 'error', 'error': {
            'type': 'not_found_error', 'message': f"model: {body.get('model')}"}}, 404)
    if m == 'timeout':
        raise requests.exceptions.ConnectTimeout('timed out')
    nxt = next_reply()
    if nxt is not None:
        return FakeResponse(nxt)
    return FakeResponse({'content': [{'type': 'text', 'text': 'All set.'}],
                         'stop_reason': 'end_turn'})


requests.post = fake_post

from app import create_app
app = create_app()

if os.environ.get('SEED') == '1':
    from extensions import db
    from models import BusinessSetting
    with app.app_context():
        db.create_all()
        BusinessSetting.set('business_name', 'Certify Cleaning Co')
        db.session.commit()
    print('seeded', flush=True)
    raise SystemExit(0)

app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5055')))
