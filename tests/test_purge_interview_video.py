"""A purged tenant's interview recordings leave Cloudinary with it.

Job photos are authenticated assets under akye-private/<tenant>/<kind>/, so a
prefix sweep finds them and cannot reach into another company's folder. The
purge was written against exactly that shape.

Interview video is not that shape. It is uploaded straight from the applicant's
browser into a flat `interviews/` folder with no tenant segment, so the prefix
sweep never matched a single recording. A company could be closed, its retention
period served and its schema destroyed, while video of named applicants -- their
face, their voice, their name in the filename's neighbours -- stayed on the
provider indefinitely, with nothing left in any database to say whose it was or
that it should have gone.

The tenant's own rows are what make the list precise: each response records the
id Cloudinary gave it, and the rows live inside that tenant's schema.

Against a real disposable Postgres, because tenant schemas are the point.
"""
import os
import secrets
import sys

os.environ['DATABASE_URL'] = os.environ.get(
    'TEST_POSTGRES_URL', 'postgresql://app_user:localtest@127.0.0.1:5432/postgres')
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['BASE_DOMAIN'] = 'akyehq.test'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notifications
notifications.send_email = lambda *a, **k: (True, 'stub')
notifications.send_sms = lambda *a, **k: (True, 'stub')

from app import create_app
from extensions import db
import control_plane
import provisioning
import tenancy
import tenant_data_lifecycle as tdl

app = create_app()
failures = []


def check(cond, m):
    if cond:
        print(f'  ✅ {m}')
    else:
        print(f'  ❌ {m}')
        failures.append(m)


TAG = secrets.token_hex(4)
MINE = f'purgevid{TAG}'
NEIGHBOUR = f'neighbour{TAG}'

with app.app_context():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)
    db.session.remove()
    for slug in (MINE, NEIGHBOUR):
        provisioning.provision(slug, f'Co {slug}', owner_email=f'o-{slug}@example.com',
                               quiet=True)
    db.session.remove()

    def add_recordings(slug, ids):
        db.session.remove()
        try:
            with tenancy.use_tenant(slug):
                from models import ContractorApplication, InterviewResponse
                app_rec = ContractorApplication(name='A Candidate',
                                                email=f'cand-{slug}@example.com')
                db.session.add(app_rec)
                db.session.flush()
                for i, pid in enumerate(ids):
                    db.session.add(InterviewResponse(
                        application_id=app_rec.id, question_index=i,
                        cloudinary_public_id=pid,
                        cloudinary_url=f'https://res.cloudinary.com/x/video/upload/{pid}.mp4'))
                db.session.commit()
        finally:
            db.session.remove()

    print('\n1. Two companies, each with recorded interviews')
    add_recordings(MINE, ['interviews/mine-a', 'interviews/mine-b'])
    add_recordings(NEIGHBOUR, ['interviews/neighbour-a'])
    mine = tdl._interview_video_ids(MINE)
    theirs = tdl._interview_video_ids(NEIGHBOUR)
    check(mine == ['interviews/mine-a', 'interviews/mine-b'],
          f'this tenant\'s recordings are found by its own rows ({mine})')
    check(theirs == ['interviews/neighbour-a'],
          'and the neighbour\'s list is its own')
    check(not set(mine) & set(theirs),
          'with no overlap — the flat folder does not blur them together')

    print('\n2. Nothing is listed for a tenant with no interviews')
    empty = f'quiet{TAG}'
    provisioning.provision(empty, 'Quiet Co', owner_email=f'q-{TAG}@example.com', quiet=True)
    db.session.remove()
    check(tdl._interview_video_ids(empty) == [],
          'an empty list, not an error and not somebody else\'s files')

    print('\n3. A purge asks Cloudinary to delete exactly those recordings')
    asked = []

    class FakeApi:
        @staticmethod
        def delete_resources_by_prefix(prefix, **kw):
            asked.append(('prefix', prefix, kw.get('resource_type'), kw.get('type')))
            return {'deleted': {}}

        @staticmethod
        def delete_resources(ids, **kw):
            asked.append(('ids', tuple(ids), kw.get('resource_type'), kw.get('type')))
            return {'deleted': {i: 'deleted' for i in ids}}

    import private_media
    real_ready, real_conf = private_media.is_ready, private_media._configure
    private_media.is_ready = lambda: True
    private_media._configure = lambda: None
    import sys as _s, types
    fake_mod = types.ModuleType('cloudinary.api')
    fake_mod.delete_resources_by_prefix = FakeApi.delete_resources_by_prefix
    fake_mod.delete_resources = FakeApi.delete_resources
    fake_pkg = types.ModuleType('cloudinary')
    fake_pkg.api = fake_mod
    saved = {k: _s.modules.get(k) for k in ('cloudinary', 'cloudinary.api')}
    _s.modules['cloudinary'] = fake_pkg
    _s.modules['cloudinary.api'] = fake_mod
    try:
        result = tdl._delete_private_media(MINE)
    finally:
        private_media.is_ready, private_media._configure = real_ready, real_conf
        for k, v in saved.items():
            if v is None:
                _s.modules.pop(k, None)
            else:
                _s.modules[k] = v

    prefix_calls = [a for a in asked if a[0] == 'prefix']
    id_calls = [a for a in asked if a[0] == 'ids']
    check(prefix_calls and prefix_calls[0][1] == f'akye-private/{MINE}/',
          'the job-photo prefix sweep still runs, scoped to this tenant')
    check(id_calls, 'and the recordings are deleted by id — this is what never happened before')
    deleted_ids = set()
    for _, ids, rtype, dtype in id_calls:
        deleted_ids |= set(ids)
        check(rtype == 'video', f'asked for video, not image ({rtype})')
    check(deleted_ids == set(mine),
          'exactly this tenant\'s recordings were named')
    check('interviews/neighbour-a' not in deleted_ids,
          'and the neighbour\'s recording was never named — no cross-tenant deletion')
    types_asked = {d for _, _, _, d in id_calls}
    check(types_asked == {'upload', 'authenticated'},
          'both delivery types are covered, so a signed future does not strand the unsigned past')
    check(result.get('videos_deleted') == len(mine),
          f'and the count is reported for the record ({result.get("videos_deleted")})')

    print('\n4. The neighbour is untouched by all of it')
    check(tdl._interview_video_ids(NEIGHBOUR) == ['interviews/neighbour-a'],
          'their rows, and so their recordings, are still there')

if failures:
    print(f'\n❌ {len(failures)} failed:')
    for f in failures:
        print(f'   - {f}')
    raise SystemExit(1)
print('\n🎉 A purged company takes its recordings with it.')
