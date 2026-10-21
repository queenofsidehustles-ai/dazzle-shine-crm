"""An interview recording is this company's, and only its office can watch it.

Job photos were given a tenant folder and signed delivery. Interview video
never caught up: it went up through an unsigned preset, which let the page name
its own folder, so every recording in the product landed in one flat
`interviews/` with no company in the path. The resulting URL was stored and
rendered straight into the review page, so anyone holding the link could watch
a named applicant's recorded interview without logging in to anything.

Two halves are fixed here. The upload is signed, so the folder and the delivery
type are decided by the server and Cloudinary rejects a page that edits them.
And playback goes through the application behind the office login, which hands
back a signed URL rather than publishing one.

The recordings already uploaded are the awkward part. They are flat objects
with a plain URL and nothing to verify, and an empty review page for every
applicant already interviewed would be a worse outcome than the exposure. They
keep playing, through the same logged-in route, and are listed in the release
record as a known backlog rather than quietly treated as fixed.
"""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/iv.db'
os.environ['SECRET_KEY'] = 'test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
from models import ContractorApplication, InterviewResponse
import private_media

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


SLUG = 'single-business'      # what _media_tenant_slug falls back to off-host
KIND = 'interview'

with app.app_context():
    db.create_all()

    # Stand in for Cloudinary so no network and no account are needed.
    import integrations
    integrations.cloudinary_cloud_name = lambda: 'testcloud'
    integrations.cloudinary_api_key = lambda: 'key-123'
    integrations.cloudinary_api_secret = lambda: 'secret-456'
    integrations.photos_ready = lambda: True
    # _configure itself is left alone: it reads the stubbed getters above and
    # configures the client with test credentials. Stubbing it out instead left
    # the client with no cloud name, which is a fault in the stub rather than
    # in the code under test.

    print('\n1. The server decides where a recording may go')
    params = private_media.upload_params(tenant_slug=SLUG, kind=KIND,
                                         resource_type='video')
    check(params['folder'] == f'akye-private/{SLUG}/{KIND}',
          f'the folder carries the company ({params["folder"]})')
    check(params['type'] == 'authenticated',
          'and the asset is authenticated, not a public upload')
    check(params['signature'] and params['api_key'],
          'a signature and key are handed to the browser')
    check('/video/upload' in params['url'], 'aimed at the video endpoint')
    check('upload_preset' not in params,
          'and no unsigned preset is involved any more')

    print('\n2. A reference is only minted for this company\'s own folder')
    good = private_media.ref_from_upload(
        {'public_id': f'akye-private/{SLUG}/{KIND}/abc', 'version': '1',
         'format': 'mp4', 'resource_type': 'video'},
        tenant_slug=SLUG, kind=KIND)
    check(good and private_media.is_private_ref(good), 'a real upload gets a reference')

    for bad, why in [
        ({'public_id': 'interviews/abc', 'version': '1', 'format': 'mp4',
          'resource_type': 'video'}, 'the old flat folder'),
        ({'public_id': 'akye-private/someone-else/interview/abc', 'version': '1',
          'format': 'mp4', 'resource_type': 'video'}, "another company's folder"),
        ({'public_id': f'akye-private/{SLUG}/{KIND}/abc', 'format': 'mp4',
          'resource_type': 'video'}, 'a reply missing its version'),
    ]:
        check(private_media.ref_from_upload(bad, tenant_slug=SLUG, kind=KIND) is None,
              f'refused: {why}')

    print('\n3. A reference cannot be edited into somebody else\'s asset')
    tampered = good[:-4] + ('aaaa' if not good.endswith('aaaa') else 'bbbb')
    check(private_media.parse_ref(tampered, tenant_slug=SLUG, kind=KIND) is None,
          'an edited signature is rejected')
    check(private_media.parse_ref(good, tenant_slug='other-co', kind=KIND) is None,
          'and a valid one does not work for another company')

    print('\n4. Saving an answer stores the reference, not a provider URL')
    rec = ContractorApplication(name='A Candidate', email='cand@example.com',
                                interview_token='tok-123', interview_status='sent')
    db.session.add(rec); db.session.commit()
    c = app.test_client()
    r = c.post('/interview/tok-123/save', json={
        'question_index': 0, 'question_en': 'Why cleaning?',
        'public_id': f'akye-private/{SLUG}/{KIND}/q0', 'version': '7',
        'format': 'mp4', 'resource_type': 'video',
        'cloudinary_public_id': f'akye-private/{SLUG}/{KIND}/q0',
        'cloudinary_url': 'https://res.cloudinary.com/testcloud/video/upload/q0.mp4',
        'transcript': 'I like it.', 'transcript_lang': 'en',
    })
    check(r.status_code == 200, 'the answer saves')
    row = InterviewResponse.query.filter_by(application_id=rec.id, question_index=0).first()
    check(row is not None, 'and is recorded')
    check(private_media.is_private_ref(row.cloudinary_url),
          'what is stored is a signed reference')
    check('res.cloudinary.com' not in (row.cloudinary_url or ''),
          'not the raw provider URL the browser offered')

    print('\n5. Playback is behind the office login')
    anon = app.test_client()
    r = anon.get(f'/admin/interviews/response/{row.id}/video')
    check(r.status_code in (301, 302) and '/login' in (r.headers.get('Location') or ''),
          f'a signed-out visitor is sent to log in (got {r.status_code})')
    with c.session_transaction() as sess:
        sess['logged_in'] = True; sess['role'] = 'owner'
    r = c.get(f'/admin/interviews/response/{row.id}/video')
    check(r.status_code in (301, 302), 'the office gets a redirect to the asset')
    target = r.headers.get('Location') or ''
    check('res.cloudinary.com' in target, 'pointing at Cloudinary')
    check('/authenticated/' in target or 's--' in target,
          f'as a signed, authenticated delivery URL ({target[:90]})')

    print('\n6. The review page links through the app, never straight at the provider')
    page = c.get(f'/admin/interviews/{rec.id}').data.decode()
    check(f'/admin/interviews/response/{row.id}/video' in page,
          'the player points at the application route')
    check('res.cloudinary.com' not in page,
          'and no provider URL is printed into the page at all')

    print('\n7. Recordings made before signing existed still play')
    old = InterviewResponse(application_id=rec.id, question_index=1,
                            cloudinary_public_id='interviews/legacy',
                            cloudinary_url='https://res.cloudinary.com/testcloud/video/upload/legacy.mp4')
    db.session.add(old); db.session.commit()
    r = c.get(f'/admin/interviews/response/{old.id}/video')
    check(r.status_code in (301, 302) and 'legacy.mp4' in (r.headers.get('Location') or ''),
          'the backlog is served rather than 404ing the review page')
    r = anon.get(f'/admin/interviews/response/{old.id}/video')
    check('/login' in (r.headers.get('Location') or ''),
          'and it is behind the same login as everything else')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 Recordings are namespaced, signed, and only the office can open them.')
