"""Resend's signed webhooks: what is accepted and what is refused (AKY-014).

Resend signs with Svix: HMAC-SHA256 over "<svix-id>.<svix-timestamp>.<body>"
with the base64 secret after "whsec_", sent as one or more "v1,<sig>" values
(two while a secret is being rotated). /api/email-events writes delivery
outcomes into customer records and /api/email-reply files replies, so anything
not provably from Resend must be refused -- including a genuine request
replayed later, which a signature alone cannot tell apart.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/resendsig.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
import blueprints.api as api

app = create_app()
failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


KEY = b'resend-signing-key-for-tests-32b'
OTHER = b'a-different-signing-key-entirely'
SECRET = 'whsec_' + base64.b64encode(KEY).decode()
BODY = json.dumps({'type': 'email.delivered', 'data': {'email_id': 're_1'}}).encode()


def sign(key, mid, stamp, body):
    return base64.b64encode(hmac.new(key, f'{mid}.{stamp}.'.encode() + body,
                                     hashlib.sha256).digest()).decode()


def headers(key=KEY, mid='msg_1', stamp=None, body=BODY, sig=None):
    stamp = str(int(time.time())) if stamp is None else stamp
    return {'svix-id': mid, 'svix-timestamp': stamp,
            'svix-signature': sig if sig is not None else f'v1,{sign(key, mid, stamp, body)}'}


def ok(hdrs, body=BODY, env=('RESEND_EVENTS_WEBHOOK_SECRET', 'RESEND_WEBHOOK_SECRET')):
    with app.test_request_context('/api/email-events', method='POST', data=body, headers=hdrs):
        return api._resend_signature_ok(body, env)


os.environ.pop('RESEND_WEBHOOK_SECRET', None)
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = SECRET

print('\n1. A genuine request is accepted')
check(ok(headers()), 'signed with the secret, just now')
check(ok(headers(stamp=str(int(time.time()) - 240))), 'four minutes old (clocks drift)')
two = f'v1,{sign(OTHER, "msg_1", str(int(time.time())), BODY)} v1,{sign(KEY, "msg_1", str(int(time.time())), BODY)}'
check(ok(headers(sig=two)), 'two signatures while a secret is rotated, one of them good')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = base64.b64encode(KEY).decode()
check(ok(headers()), 'a secret pasted without its whsec_ prefix')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = ''
os.environ['RESEND_WEBHOOK_SECRET'] = SECRET
check(ok(headers()), 'the shared secret, where the events webhook has none of its own')
os.environ.pop('RESEND_WEBHOOK_SECRET')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = SECRET

print('\n2. Everything else is refused')
check(not ok(headers(key=OTHER)), 'signed with another key')
check(not ok(headers(), body=BODY + b' '), 'the body changed after signing')
h = headers()
h['svix-id'] = 'msg_2'
check(not ok(h), 'the message id changed after signing')
for missing in ('svix-id', 'svix-timestamp', 'svix-signature'):
    h = headers()
    h.pop(missing)
    check(not ok(h), f'no {missing} header')
check(not ok(headers(sig='v1,')), 'an empty signature')
now = str(int(time.time()))
good = sign(KEY, 'msg_1', now, BODY)
check(not ok(headers(stamp=now, sig='v2,' + good)), 'a good signature under a scheme that is not v1')
flipped = good[:-2] + ('A' if good[-2] != 'A' else 'B') + good[-1]
check(not ok(headers(stamp=now, sig='v1,' + flipped)), 'a signature with one character changed')
old = str(int(time.time()) - 6 * 60)
check(not ok(headers(stamp=old)), 'a genuine request replayed six minutes later')
future = str(int(time.time()) + 6 * 60)
check(not ok(headers(stamp=future)), 'a timestamp six minutes in the future')
check(not ok(headers(stamp='yesterday')), 'a timestamp that is not a number')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = ''
check(not ok(headers()), 'no secret configured: nothing can be authenticated, so nothing is')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = 'whsec_not base64 at all!!'
check(not ok(headers()), 'a secret that does not decode')
os.environ['RESEND_EVENTS_WEBHOOK_SECRET'] = SECRET

print('\n3. The endpoints refuse with 403, before reading anything')
c = app.test_client()
for path in ('/api/email-events', '/api/email-reply'):
    r = c.post(path, data=BODY, content_type='application/json')
    check(r.status_code == 403, f'{path}: unsigned is 403 ({r.status_code})')
    r = c.post(path, data=BODY, content_type='application/json',
               headers=headers(stamp=str(int(time.time()) - 3600)))
    check(r.status_code == 403, f'{path}: replayed an hour later is 403 ({r.status_code})')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print('   -', f)
    sys.exit(1)
print('\n🎉 Only Resend, signed and recent, gets in.')
