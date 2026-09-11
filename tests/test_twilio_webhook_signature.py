"""Only this business's Twilio account may write to the inbound inbox."""
import os
import sys

from flask import Flask
from twilio.request_validator import RequestValidator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import blueprints.messages as messages


app = Flask(__name__)
token = 'tenant-specific-twilio-auth-token'
original_token = messages.integrations.twilio_auth_token
messages.integrations.twilio_auth_token = lambda: token

try:
    payload = {'From': '+12025550100', 'Body': 'Please call me', 'MessageSid': 'SM123'}

    with app.test_request_context('/messages/incoming', method='POST', data=payload):
        assert messages._twilio_request_valid() is False

    url = 'https://cleaningwonder.akyehq.com/messages/incoming'
    signature = RequestValidator(token).compute_signature(url, payload)
    with app.test_request_context(
        url, method='POST', data=payload,
        headers={'X-Twilio-Signature': signature},
    ):
        assert messages._twilio_request_valid() is True

    tampered = dict(payload, Body='STOP')
    with app.test_request_context(
        url, method='POST', data=tampered,
        headers={'X-Twilio-Signature': signature},
    ):
        assert messages._twilio_request_valid() is False
finally:
    messages.integrations.twilio_auth_token = original_token

print('✅ Twilio signatures protect inbound messages and opt-out state.')
