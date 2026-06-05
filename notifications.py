import os
import requests as http_requests


def send_email(to_email, to_name, subject, html, from_name=None):
    api_key = os.environ.get('BREVO_API_KEY')
    from_email = os.environ.get('FROM_EMAIL', 'bookings@dazzleandshinemaids.com')
    if not from_name:
        from_name = os.environ.get('FROM_NAME', 'Dazzle & Shine Maids')
    if not api_key:
        return
    try:
        http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'api-key': api_key, 'Content-Type': 'application/json'},
            json={
                'sender': {'name': from_name, 'email': from_email},
                'to': [{'email': to_email, 'name': to_name}],
                'subject': subject,
                'htmlContent': html,
            },
            timeout=10,
        )
    except Exception:
        pass


def send_sms(to_phone, message):
    account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
    auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
    from_phone = os.environ.get('TWILIO_PHONE')
    if not all([account_sid, auth_token, from_phone]):
        return
    try:
        from twilio.rest import Client
        digits = ''.join(filter(str.isdigit, to_phone))
        formatted = ('+1' + digits) if not to_phone.startswith('+') else to_phone
        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_phone, to=formatted)
    except Exception:
        pass
