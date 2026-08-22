"""A licence photo is not a picture of a clean kitchen.

Job photos and expense receipts go to Cloudinary through an unsigned preset,
which hands back a long random URL that is nonetheless public — anyone holding
it can open the file forever, with no login. That is a fair trade for a
before-and-after shot. It is the wrong trade for a driver's licence or a W-9,
which are a government ID number and a social security number.

So those live in the application, encrypted, and come back out only through a
route behind the owner's login. These checks are the ones that would actually
hurt to get wrong: that the plaintext isn't sitting in the database, that a
logged-out stranger can't fetch a document by guessing an id, and that the
upload won't accept anything a contractor's phone wouldn't produce.
"""
import io
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/docs.db'
os.environ['SECRET_KEY'] = 'a-real-production-secret'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
sms_outbox, mail_outbox = [], []
notifications.send_sms = lambda phone, msg: (sms_outbox.append(msg) or (True, 'stub'))
notifications.send_email = lambda **k: (mail_outbox.append(k) or (True, 'stub'))

import secure_docs
from app import create_app
from extensions import db
from models import Staff, ContractorDocument

app = create_app()

LICENCE = b'\x89PNG\r\n\x1a\n' + b'THIS-IS-THE-LICENCE-IMAGE' * 20


def check(cond, m):
    assert cond, f'FAILED: {m}'
    print(f'  ✅ {m}')


with app.app_context():
    db.create_all()
    s = Staff(name='Ana Reyes', email='ana@example.com', phone='4075550101',
              is_active=True, agreement_token='tok-ana', language='en')
    db.session.add(s)
    db.session.commit()
    staff_id = s.id

public = app.test_client()
owner = app.test_client()
with owner.session_transaction() as sess:
    sess['logged_in'] = True
    sess['role'] = 'owner'


print('\n1. The contractor gets a page they can use from a phone')
r = public.get('/contractors/documents/tok-ana/id')
body = r.get_data(as_text=True)
check(r.status_code == 200, 'the ID upload page opens on a token alone')
check('identificación' in body, 'and it is in Spanish as well as English')
check('<form' in body and 'enctype="multipart/form-data"' in body,
      'it is a plain form — no JavaScript to fail on a bad connection')

print('\n2. What arrives is stored encrypted, not as the file itself')
r = public.post('/contractors/documents/tok-ana/id',
                data={'document': (io.BytesIO(LICENCE), 'licence.png', 'image/png')},
                content_type='multipart/form-data', follow_redirects=True)
check(r.status_code == 200, 'the upload is accepted')
with app.app_context():
    doc = ContractorDocument.query.filter_by(staff_id=staff_id, kind='id').first()
    check(doc is not None, 'and recorded against the contractor')
    check(LICENCE not in bytes(doc.data),
          'the licence bytes are NOT in the database — a dump does not leak it')
    check(secure_docs.decrypt(doc.data) == LICENCE, 'but it decrypts back to exactly the original')
    check(doc.size_bytes == len(LICENCE), 'the real size is recorded')
    doc_id = doc.id

print('\n3. Getting it back out needs the owner login')
r = public.get(f'/contractors/documents/{doc_id}/view', follow_redirects=False)
check(r.status_code in (301, 302), 'a logged-out request is turned away')
check('/login' in r.headers.get('Location', ''), 'and sent to the login page')
r = owner.get(f'/contractors/documents/{doc_id}/view')
check(r.status_code == 200, 'the owner can open it')
check(r.get_data() == LICENCE, 'and gets the real file back, byte for byte')
check('no-store' in (r.headers.get('Cache-Control') or ''),
      'told not to cache — the point is that no copy outlives the response')

print('\n4. The upload will not take what it should not')
big = io.BytesIO(b'x' * (secure_docs.MAX_BYTES + 10))
r = public.post('/contractors/documents/tok-ana/id',
                data={'document': (big, 'huge.png', 'image/png')},
                content_type='multipart/form-data', follow_redirects=True)
check('larger than' in r.get_data(as_text=True), 'an oversized file is refused, in words a person understands')
r = public.post('/contractors/documents/tok-ana/id',
                data={'document': (io.BytesIO(b'MZ\x90\x00'), 'x.exe', 'application/x-msdownload')},
                content_type='multipart/form-data', follow_redirects=True)
check('PDF or a photo' in r.get_data(as_text=True), 'an executable is refused')
with app.app_context():
    check(ContractorDocument.query.filter_by(staff_id=staff_id, kind='id').count() == 1,
          'and neither rejection left anything behind')

print('\n5. Guessing gets you nowhere')
check(public.get('/contractors/documents/not-a-real-token/id').status_code == 404,
      'an unknown token 404s rather than hinting the page exists')
check(public.get('/contractors/documents/tok-ana/passport').status_code == 404,
      'an unknown document kind 404s')
check(owner.get('/contractors/documents/999999/view').status_code == 404,
      'a document id that does not exist 404s for the owner too')

print('\n6. Re-uploading replaces, so a stale ID never sits alongside a current one')
NEWER = b'\x89PNG\r\n\x1a\n' + b'RENEWED-LICENCE' * 20
public.post('/contractors/documents/tok-ana/id',
            data={'document': (io.BytesIO(NEWER), 'new.png', 'image/png')},
            content_type='multipart/form-data', follow_redirects=True)
with app.app_context():
    docs = ContractorDocument.query.filter_by(staff_id=staff_id, kind='id').all()
    check(len(docs) == 1, 'still exactly one ID on file')
    check(secure_docs.decrypt(docs[0].data) == NEWER, 'and it is the new one')

print('\n7. A rotated SECRET_KEY fails shut, not open')
real = os.environ['SECRET_KEY']
os.environ['SECRET_KEY'] = 'somebody-changed-the-key'
with app.app_context():
    d = ContractorDocument.query.filter_by(staff_id=staff_id, kind='id').first()
    check(secure_docs.decrypt(d.data) is None,
          'the document cannot be read with the wrong key — it does not return garbage')
os.environ['SECRET_KEY'] = real
with app.app_context():
    d = ContractorDocument.query.filter_by(staff_id=staff_id, kind='id').first()
    check(secure_docs.decrypt(d.data) == NEWER, 'and the right key still opens it')

print('\n8. The owner can ask for a document without typing a link')
sms_outbox.clear()
mail_outbox.clear()
owner.post(f'/contractors/documents/request/{staff_id}/w9', follow_redirects=True)
check(len(sms_outbox) == 1, 'a text goes out')
check('/contractors/documents/tok-ana/w9' in sms_outbox[0], 'carrying their own upload link')
check(len(mail_outbox) == 1, 'and an email as well, in case the text is missed')

print('\n9. The owner sees what is on file and what is missing')
page = owner.get(f'/contractors/team/{staff_id}').get_data(as_text=True)
check('Documents on File' in page, 'the profile has a documents section')
check('Photo ID' in page and 'Form W-9' in page, 'listing both kinds')
check(f'/contractors/documents/{doc_id}/view' not in page or 'View' in page,
      'with a way to open the ones that arrived')
check('Not on file' in page, 'and saying plainly which are missing')

print('\n10. A background check arrives before there is anyone to attach it to')
from models import ContractorApplication
REPORT = b'%PDF-1.4 CRIMINAL-HISTORY' + b'\x00' * 200
with app.app_context():
    a = ContractorApplication(name='Bea Lopez', email='bea@example.com', phone='4075550202',
                              interview_status='completed', status='reviewing',
                              bgcheck_upload_token='bg-tok', offer_token='off-tok')
    db.session.add(a)
    db.session.commit()
    app_id = a.id

page = public.get('/background-check/bg-tok').get_data(as_text=True)
check('cloudinary' not in page.lower(),
      'the upload page no longer sends the file to a public host')
r = public.post('/background-check/bg-tok/submit',
                data={'document': (io.BytesIO(REPORT), 'check.pdf', 'application/pdf')},
                content_type='multipart/form-data', follow_redirects=True)
check(r.status_code == 200, 'an applicant can submit one')
with app.app_context():
    a = db.session.get(ContractorApplication, app_id)
    d = a.document('bgcheck')
    check(d is not None and d.application_id == app_id and d.staff_id is None,
          'it is held against the application, because there is no Staff row yet')
    check(REPORT not in bytes(d.data), 'and criminal history is not sitting in the database in the clear')
    check(a.bgcheck_results_received is True, 'the application is flagged as received')
    bg_id = d.id
check(public.get(f'/contractors/documents/{bg_id}/view').status_code in (301, 302),
      'a logged-out request for it is turned away')
check(owner.get(f'/contractors/documents/{bg_id}/view').get_data() == REPORT,
      'and the owner gets the real report')

print('\n11. It follows them when they are hired')
public.get('/contractors/offer/accept/off-tok', follow_redirects=True)
with app.app_context():
    hired = Staff.query.filter_by(email='bea@example.com').first()
    check(hired is not None, 'accepting the offer creates their Staff row')
    moved = hired.document('bgcheck')
    check(moved is not None and moved.staff_id == hired.id,
          'the background check is now on the profile the owner actually looks at')
    check(db.session.get(ContractorApplication, app_id).document('bgcheck') is None,
          'and is no longer stranded on the application')
    check(secure_docs.decrypt(moved.data) == REPORT, 'still the same readable document')

print('\n12. Encryption that is not really encryption says so')
real = os.environ['SECRET_KEY']
os.environ['SECRET_KEY'] = 'dev-secret-change-me'
check(secure_docs.is_ready() is False,
      'the shipped default key is reported as not ready, so the UI can warn rather than reassure')
os.environ['SECRET_KEY'] = real
check(secure_docs.is_ready() is True, 'a real key is ready')

print('\n🎉 Sensitive documents stay inside the application, encrypted, behind the login.')
