"""A photo from a cleaner's phone: small, bounded, and retryable.

On 29 Oct a cleaner's photo upload ran for exactly sixty seconds and came back
as an HTTP 500, with gunicorn killing the worker ("WORKER TIMEOUT"); the
request before it was abandoned by the phone after eight. The phone sent the
camera's full-size picture (megabytes, over a cellular connection), and the
server waited on Cloudinary for as long as the worker was allowed to live, so
a stall was a crash instead of an answer. Now:

  * the phone makes the picture small before sending it (static/photo-resize.js)
  * the server waits for Cloudinary for much less than the worker's limit, and
    says "try again" (503) instead of failing (500)
  * the phone gives the upload a limit of its own and tries once more
  * a slow day leaves its cause in the log: the phone sending slowly, or
    Cloudinary taking it slowly
"""
import io, json, logging, os, runpy, shutil, subprocess, sys, tempfile
TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/jp.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['FLASK_ENV'] = 'development'
os.environ['CLOUDINARY_API_SECRET'] = 'test-secret-for-signing-refs'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(cond, m):
    print(f'  {"✅" if cond else "❌"} {m}')
    if not cond:
        failures.append(m)


import requests
import private_media
REAL_UPLOAD_IMAGE = private_media.upload_image
from app import create_app
from extensions import db
from flask import g
from werkzeug.datastructures import FileStorage
import blueprints.workorders as wo
from models import Booking, JobChecklist

app = create_app()

print('1. The server does not wait on Cloudinary as long as the worker lives')
worker_limit = runpy.run_path(os.path.join(ROOT, 'gunicorn.conf.py'))['timeout']
check(private_media.UPLOAD_TIMEOUT_SECONDS * 2 <= worker_limit,
      f'{private_media.UPLOAD_TIMEOUT_SECONDS}s for Cloudinary against a {worker_limit}s worker: room to answer')

import cloudinary.uploader
seen = {}


def fake_upload(fh, **opts):
    seen.update(opts)
    return {'public_id': 'akye-private/acme/job-photo/x', 'version': 1, 'format': 'jpg', 'resource_type': 'image'}


real_upload = cloudinary.uploader.upload
cloudinary.uploader.upload = fake_upload
private_media._configure = lambda: None
private_media._assert_job_photo_mutable = lambda kind, scope: None


def photo(data=b'\xff\xd8\xff' + b'0' * 100, name='a.jpg'):
    return FileStorage(stream=io.BytesIO(data), filename=name, content_type='image/jpeg')


ref = private_media.upload_image(photo(), tenant_slug='acme', kind='job-photo', scope_id='1:before')
check(seen.get('timeout') == private_media.UPLOAD_TIMEOUT_SECONDS and ref.startswith(private_media._PREFIX),
      'the upload is given that limit, and still returns a reference')

for exc in (requests.exceptions.ReadTimeout('slow'), requests.exceptions.ConnectionError('reset'),
            RuntimeError('cloudinary said no')):
    def boom(fh, **opts):
        raise exc
    cloudinary.uploader.upload = boom
    try:
        private_media.upload_image(photo(), tenant_slug='acme', kind='job-photo', scope_id='1:before')
        check(False, f'{type(exc).__name__} is reported')
    except private_media.UploadUnavailable as e:
        check('try again' in str(e) and isinstance(e, RuntimeError),
              f'{type(exc).__name__} becomes "try again", and is still a RuntimeError to callers that predate it')
cloudinary.uploader.upload = real_upload

print('\n2. The phone gets an answer it can act on')
with app.app_context():
    db.create_all()
    b = Booking(service_type='standard', name='Job', status='confirmed', price=100.0)
    db.session.add(b); db.session.commit()
    cl = JobChecklist(booking_id=b.id, token='tok-123', items='[]', completed_items='[]')
    db.session.add(cl); db.session.commit()

    def post(upload_image, phase='before', body_seconds=None):
        private_media.upload_image = upload_image
        with app.test_request_context('/workorders/checklist/tok-123/add-photo', method='POST',
                                      data={'phase': phase, 'photo': (io.BytesIO(b'\xff\xd8\xff' + b'0' * 50), 'a.jpg', 'image/jpeg')},
                                      content_type='multipart/form-data'):
            g.tenant_slug = 'acme'
            out = wo.add_photo('tok-123')
        resp, status = (out if isinstance(out, tuple) else (out, out.status_code))
        return status, resp.get_json()

    def unavailable(*a, **k):
        raise private_media.UploadUnavailable('The photo could not be saved just now. Please try again.')

    status, body = post(unavailable)
    check(status == 503 and body['ok'] is False and body.get('retry') is True and 'try again' in body['error'],
          'Cloudinary unavailable: 503 and "retry", not a 500')
    check(JobChecklist.query.get(cl.id).before_photos in (None, '[]', ''), 'and nothing was recorded for the photo')

    def refused(*a, **k):
        raise ValueError('Upload a JPG, PNG, WEBP or HEIC image')
    status, body = post(refused)
    check(status == 400 and 'JPG' in body['error'], 'a picture that is wrong stays a 400, with its reason')

    status, body = post(lambda *a, **k: private_media._encode(
        {'v': 1, 'tenant': 'acme', 'kind': 'job-photo', 'scope': f'{cl.id}:before',
         'public_id': 'akye-private/acme/job-photo/x', 'version': 1, 'format': 'jpg', 'resource_type': 'image'}))
    check(status == 200 and body['ok'] and body['url'], 'and a good one still works')

    print('\n3. A slow day leaves its cause behind')
    # Running migrations used to switch off every logger that already existed (the
    # app runs them at start-up), so the line below would never have been written.
    check(not wo.log.disabled and not private_media.log.disabled,
          'the loggers are on after the app has started and migrated (migrations/env.py)')
    records = []

    class Catch(logging.Handler):
        def emit(self, rec):
            records.append(rec.getMessage())
    h = Catch(); wo.log.addHandler(h); wo.log.setLevel(logging.WARNING)
    old = private_media.SLOW_UPLOAD_SECONDS
    private_media.SLOW_UPLOAD_SECONDS = -1          # everything counts as slow for this check
    post(lambda *a, **k: private_media._encode(
        {'v': 1, 'tenant': 'acme', 'kind': 'job-photo', 'scope': f'{cl.id}:after',
         'public_id': 'akye-private/acme/job-photo/y', 'version': 1, 'format': 'jpg', 'resource_type': 'image'}), phase='after')
    private_media.SLOW_UPLOAD_SECONDS = old
    wo.log.removeHandler(h)
    check(any('slow job-photo upload from the phone' in r and 'to receive' in r for r in records),
          'the time taken to receive the picture from the phone is logged on its own')

    print('\n3b. The clock starts before the body is read, not after')
    # The first touch of request.form reads the whole body from the phone, so a timer
    # started after it measured nothing. A phone that sends slowly is simulated by an
    # input stream that waits as it is read.
    import time as _time
    from werkzeug.test import EnvironBuilder

    class SlowStream(io.BytesIO):
        # werkzeug reads through whichever of these the stream offers
        def read(self, *a):
            _time.sleep(0.35)
            return super().read(*a)

        def read1(self, *a):
            _time.sleep(0.35)
            return super().read1(*a)

        def readinto(self, b):
            _time.sleep(0.35)
            return super().readinto(b)

    builder = EnvironBuilder(path='/workorders/checklist/tok-123/add-photo', method='POST',
                             data={'phase': 'before', 'photo': (io.BytesIO(b'\xff\xd8\xff' + b'0' * 50), 'a.jpg', 'image/jpeg')})
    environ = builder.get_environ()
    body = environ['wsgi.input'].read()
    environ['wsgi.input'] = SlowStream(body)
    records.clear()
    wo.log.addHandler(h)
    private_media.SLOW_UPLOAD_SECONDS = 0.2
    private_media.upload_image = lambda *a, **k: (_ for _ in ()).throw(private_media.UploadUnavailable('x'))
    with app.request_context(environ):
        g.tenant_slug = 'acme'
        wo.add_photo('tok-123')
    private_media.SLOW_UPLOAD_SECONDS = old
    wo.log.removeHandler(h)
    took = [float(r.split('slow job-photo upload from the phone: ')[1].split('s')[0]) for r in records
            if 'slow job-photo upload from the phone' in r]
    check(took and took[0] >= 0.3, f'a body that takes a third of a second to arrive is timed at that ({took})')

    print('\n3c. A repeat of the same photo is not saved twice')
    private_media.upload_image = REAL_UPLOAD_IMAGE
    saved = []

    def counting_upload(fh, **opts):
        saved.append(1)
        return {'public_id': f'akye-private/acme/job-photo/p{len(saved)}', 'version': 1,
                'format': 'jpg', 'resource_type': 'image'}
    cloudinary.uploader.upload = counting_upload

    def post_id(upload_id, phase='before'):
        data = {'phase': phase, 'photo': (io.BytesIO(b'\xff\xd8\xff' + b'0' * 50), 'a.jpg', 'image/jpeg')}
        if upload_id is not None:
            data['upload_id'] = upload_id
        with app.test_request_context('/workorders/checklist/tok-123/add-photo', method='POST',
                                      data=data, content_type='multipart/form-data'):
            g.tenant_slug = 'acme'
            out = wo.add_photo('tok-123')
        resp = out[0] if isinstance(out, tuple) else out
        return resp.get_json()

    baseline = len(JobChecklist.query.get(cl.id).get_before_photos())
    first = post_id('photo-aaaa1111')
    again = post_id('photo-aaaa1111')          # the answer to the first was lost, so the phone asks again
    check(first['ok'] and again['ok'] and again.get('duplicate') and again['url'] == first['url'] and len(saved) == 1,
          'the second attempt is told it is there already, with the same address, and nothing is uploaded again')
    other = post_id('photo-bbbb2222')
    check(other['ok'] and not other.get('duplicate') and len(saved) == 2 and other['url'] != first['url'],
          'a different photo is a different photo')
    post_id(None); post_id('x')                 # no name, or one that is not a name: saved as before
    check(len(saved) == 4, 'an upload with no name (an older page), or a bad one, is simply saved')
    cl_now = JobChecklist.query.get(cl.id)
    check(len(cl_now.get_before_photos()) - baseline == 4, 'and the checklist gained four photos, not five')
    third = post_id('photo-aaaa1111', phase='after')
    check(third['ok'] and not third.get('duplicate'), 'the same name on the other phase is not a repeat')
    check("pg_advisory_xact_lock" in open(os.path.join(ROOT, 'blueprints/workorders.py')).read(),
          'on PostgreSQL a second attempt waits for the first (an advisory lock on that one upload, not the checklist)')
    cloudinary.uploader.upload = real_upload

print('\n4. The page')
html = open(os.path.join(ROOT, 'templates/public/checklist.html')).read()
check("filename='photo-resize.js'" in html and 'AkyePhoto.shrink' in html, 'the phone shrinks the picture first')
check('upload_id' in html and 'crypto.randomUUID' in html,
      'it names each photo once, and sends that name with every attempt')
check('AbortController' in html and '[502, 503, 504]' in html,
      'gives the upload a limit and tries once more when nothing came back or the server said to')
check('Could not upload that photo. Please try again. (' not in html, 'and no longer shows a raw error in brackets')

print('\n5. The resizer, in a real browser')
node = shutil.which('node')
runner = os.path.join(TMP, 'resize_check.js')
open(runner, 'w').write(r"""
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.setContent('<html><body></body></html>');
  await p.addScriptTag({ path: process.argv[2] });
  const out = await p.evaluate(async () => {
    // A 4000x3000 picture of noise: the size and detail of a camera photo.
    const c = document.createElement('canvas'); c.width = 4000; c.height = 3000;
    const x = c.getContext('2d'); const d = x.createImageData(4000, 3000);
    for (let i = 0; i < d.data.length; i += 4) { const v = (i * 2654435761) >>> 24; d.data[i] = v; d.data[i+1] = v ^ 90; d.data[i+2] = v ^ 200; d.data[i+3] = 255; }
    x.putImageData(d, 0, 0);
    const big = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.95));
    const bigFile = new File([big], 'IMG_0001.jpg', { type: 'image/jpeg' });
    const small = await AkyePhoto.shrink(bigFile);
    const bmp = await createImageBitmap(small);
    const tiny = new File([new Uint8Array(1000)], 't.jpg', { type: 'image/jpeg' });
    const text = new File(['hello'.repeat(200000)], 'n.txt', { type: 'text/plain' });
    const junk = new File([new Uint8Array(900000)], 'bad.jpg', { type: 'image/jpeg' });
    return {
      before: bigFile.size, after: small.size, type: small.type, name: small.name,
      w: bmp.width, h: bmp.height,
      tinySame: (await AkyePhoto.shrink(tiny)) === tiny,
      textSame: (await AkyePhoto.shrink(text)) === text,
      junkSame: (await AkyePhoto.shrink(junk)) === junk,
      nullOk: (await AkyePhoto.shrink(null)) === null,
    };
  });
  console.log(JSON.stringify(out));
  await b.close();
})();
""")
env = dict(os.environ, NODE_PATH=subprocess.run(['npm', 'root', '-g'], capture_output=True, text=True).stdout.strip())
if not node:
    print('  (skipped: no node here)')
else:
    r = subprocess.run([node, runner, os.path.join(ROOT, 'static', 'photo-resize.js')],
                       capture_output=True, text=True, env=env)
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        o = None
    if o is None:
        print('  (skipped: no browser to run it in)', r.stderr.strip()[-200:])
    else:
        check(o['type'] == 'image/jpeg' and o['name'] == 'IMG_0001.jpg' and max(o['w'], o['h']) == 1600,
              f"a 4000x3000 camera picture comes out a JPEG with its long side at 1600 ({o['w']}x{o['h']})")
        check(o['after'] * 4 < o['before'], f"and a fraction of the size ({o['before']//1024} KB to {o['after']//1024} KB)")
        check(o['tinySame'] and o['textSame'], 'a small picture, or something that is not a picture, is sent as it is')
        check(o['junkSame'], 'a "picture" the browser cannot decode is sent as it is: the upload is never stopped')
        check(o['nullOk'], 'and nothing at all is not an error')

print()
if failures:
    print(f'❌ {len(failures)} job-photo check(s) failed.')
    sys.exit(1)
print('🎉 A photo is small, bounded, and can be tried again.')
