"""A Spanish text should not open an English page.

Messages have been translated for a long time — a job offer, a claim link, a
reminder. The pages those messages link to were not, so a cleaner set to
Spanish got a text she could read, tapped it, and landed on a page she could
not. That is worse than not translating the text at all: it promises
something the next screen does not deliver.

The rules here:

  * a cleaner's own language setting — the one that already decides what
    language her texts arrive in — decides what language her pages are in
  * a toggle can override it for one browser, and must never lose the token
    that got her to the page
  * a missing translation shows English, never a key. A half-translated page
    is usable; `clock_in.button.label` is not.
  * names, addresses and prices are never translated
  * page furniture is written down, not fetched. A cleaner standing at a
    locked door does not wait on an API call, and a page that silently falls
    back to English tells nobody why.
"""
import os, sys, tempfile, secrets
from datetime import date, timedelta

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/es.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ.pop('OPENROUTER_API_KEY', None)     # prove it works with no API key
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_sms = lambda *a, **k: (True, 'stub')
notifications.send_email = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import Booking, Staff
import i18n

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


with app.app_context():
    db.drop_all()
    db.create_all()
    maria = Staff(name='Maria Alvarez', email='m@x.com', phone='4075550101',
                  is_active=True, pay_type='hourly', pay_rate=22.0,
                  language='es', agreement_token=secrets.token_urlsafe(20))
    jen = Staff(name='Jennifer Ward', email='j@x.com', phone='4075550102',
                is_active=True, pay_type='percent', pay_rate=50.0,
                language='en', agreement_token=secrets.token_urlsafe(20))
    db.session.add_all([maria, jen])
    db.session.commit()
    job = Booking(name='Mrs Johnson', email='c@x.com', phone='4075559999',
                  address='118 Oak Street', city='Winter Park', zip_code='32789',
                  service_type='deep', preferred_date=date.today().isoformat(),
                  preferred_time='10:00 AM', status='confirmed',
                  assigned_cleaner='Maria Alvarez', price=280.0,
                  estimated_hours=4.0,
                  access_notes='Lockbox on the side gate, code 4471.')
    db.session.add(job)
    db.session.commit()
    MT, JT = maria.agreement_token, jen.agreement_token

c = app.test_client()


print('\n1. The translation table itself')
check(i18n.t('Clock in', 'es') == 'Marcar entrada', 'Spanish comes back for a known string')
check(i18n.t('Clock in', 'en') == 'Clock in', 'English is left alone')
check(i18n.t('A string nobody has translated', 'es') == 'A string nobody has translated',
      'and an unknown string falls back to English rather than showing a key')
check(i18n.t(None, 'es') == '', 'None does not blow up')
for raw, want in (('es-MX', 'es'), ('ES', 'es'), ('fr', 'en'), (None, 'en'), ('', 'en')):
    check(i18n.normalise(raw) == want, f'{raw!r} reads as {want!r}')


print("\n2. A cleaner's page is in her own language, without her doing anything")
es = c.get(f'/contractors/my-day/{MT}').data.decode('utf8', 'replace')
check('Hola Maria' in es, 'Maria is set to Spanish, so she is greeted in Spanish')
check('Tu horario' in es, "'Your schedule' is translated")
check('TÚ GANAS' in es, "'YOU EARN' is translated")
check('Cómo llegar' in es, "and the Navigate button, which is the one that matters")
check('lang="es"' in es, 'the page declares itself Spanish for a screen reader')

en = c.get(f'/contractors/my-day/{JT}').data.decode('utf8', 'replace')
check('Hi Jennifer' in en, 'Jennifer is set to English and gets English')
check('Hola' not in en, 'with no Spanish leaking into it')


print('\n3. Names, addresses and money are never translated')
# The one kind of mistake that would send somebody to the wrong house.
check('118 Oak Street' in es, 'the street address is untouched')
check('Mrs Johnson' in es, "so is the customer's name")
check('Winter Park' in es, 'and the town')
check('Maria Alvarez' in es or 'Maria' in es, "and the cleaner's own name")


print('\n4. The toggle overrides, and does not lose the link')
# It lost the token once. A cleaner who taps ES and is thrown out of her own
# job page will not tap it twice.
page = c.get(f'/contractors/my-day/{MT}').data.decode('utf8', 'replace')
check('langsw' in page, 'the toggle is on the page')
check(MT in page, 'and its links still carry the token that got her here')

back = c.get(f'/contractors/my-day/{MT}?lang=en').data.decode('utf8', 'replace')
check('Hi Maria' in back, 'asking for English gives English')
check('Hola' not in back, 'with no Spanish left behind')
fwd = c.get(f'/contractors/my-day/{JT}?lang=es').data.decode('utf8', 'replace')
check('Hola Jennifer' in fwd, 'and an English cleaner can ask for Spanish')


print('\n5. A job offered to the team')
with app.app_context():
    import blueprints.claims as claims
    b = Booking(name='Sunrise Daycare', email='d@x.com', phone='4075558888',
                address='3300 Colonial Drive', city='Fairview', zip_code='32803',
                service_type='commercial', price=430.0, estimated_hours=5.0,
                status='confirmed',
                preferred_date=(date.today() + timedelta(days=1)).isoformat(),
                preferred_time='8:30 AM')
    db.session.add(b)
    db.session.commit()
    claims.broadcast_job(b)
    ct = db.session.get(Booking, b.id).claim_token

offer = c.get(f'/claim/{ct}/{MT}').data.decode('utf8', 'replace')
check('Trabajo disponible' in offer, 'the offer page is in Spanish')
check('Tomar este trabajo' in offer, 'including the button that takes the job')
check('El primero en tomarlo' in offer, 'and the first-to-claim rule')
check('3300 Colonial' not in offer,
      'the address is still withheld — translating it would not change that')
check('Fairview' in offer, 'but the area still shows, which is enough to decide')


print('\n6. It works with no translation API at all')
# The page furniture is written down precisely so that a missing key, a slow
# API or an outage cannot leave a cleaner with a page she cannot read.
check(not os.environ.get('OPENROUTER_API_KEY'),
      'this whole file has run without an API key')
check('Marcar entrada' in es,
      'and the Spanish still arrived, because it is not fetched')
check(i18n.auto('Lockbox on the side gate', 'es') == 'Lockbox on the side gate',
      "what the owner typed is returned unchanged rather than lost")


if failures:
    print(f'\n\n❌ {len(failures)} Spanish check(s) failed.\n')
    sys.exit(1)
print('\n\n✅ A Spanish text opens a Spanish page.\n')
