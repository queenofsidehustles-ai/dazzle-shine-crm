import os
import requests as http_requests


def send_email(to_email, to_name, subject, html, from_name=None):
    api_key = os.environ.get('RESEND_API_KEY')
    from_email = os.environ.get('FROM_EMAIL', 'bookings@dazzleandshinemaids.com')
    if not from_name:
        from_name = os.environ.get('FROM_NAME', 'Dazzle & Shine Maids')
    if not api_key:
        return
    try:
        http_requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'from': f'{from_name} <{from_email}>',
                'to': [to_email],
                'subject': subject,
                'html': html,
            },
            timeout=10,
        )
    except Exception:
        pass


def add_to_mailerlite(email, name, group_id=None):
    api_key = os.environ.get('MAILERLITE_API_KEY')
    if not group_id:
        group_id = os.environ.get('MAILERLITE_GROUP_ID', '189490896944760797')
    if not api_key:
        return
    try:
        http_requests.post(
            'https://connect.mailerlite.com/api/subscribers',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json={
                'email': email,
                'fields': {'name': name},
                'groups': [group_id],
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
