"""PAY-01: work-order email and SMS must display the same exact crew pay."""
from types import SimpleNamespace


def test_workorder_crew_pay_preserves_cents(monkeypatch):
    import blueprints.workorders as workorders

    emails = []
    texts = []
    monkeypatch.setattr(workorders, 'send_email', lambda **kw: emails.append(kw))
    monkeypatch.setattr(workorders, 'send_sms', lambda to, body, **kw: texts.append((to, body)))
    monkeypatch.setattr(
        workorders, 'url_for',
        lambda endpoint, **kw: f"https://tenant.example/{endpoint}",
    )

    cleaner = SimpleNamespace(
        id=1,
        name='Cents Cleaner',
        email='cents@example.test',
        phone='3015550101',
    )
    row = SimpleNamespace(pay_amount=64.50)
    crew_member = SimpleNamespace(staff=cleaner, staff_id=cleaner.id)
    booking = SimpleNamespace(
        crew=[crew_member],
        crew_size=2,
        is_crew_job=True,
        crew_row_for=lambda staff: row,
        preferred_date='2026-09-20',
        preferred_time='9:00 AM',
        extras='',
        internal_notes='',
        notes='',
        access_notes='',
        address='1 Exact Cents Way',
        city='Germantown',
        zip_code='20874',
        name='Exact Cents Customer',
        service_label='Standard Cleaning',
        bedrooms=3,
        bathrooms=2,
    )
    checklist = SimpleNamespace(token='exact-cents-token')

    workorders._send_workorder_to(booking, checklist, cleaner)

    assert len(emails) == 1
    assert len(texts) == 1
    assert '$64.50' in emails[0]['html']
    assert '$64.50' in texts[0][1]
    assert 'Your pay: $64.' not in texts[0][1]
