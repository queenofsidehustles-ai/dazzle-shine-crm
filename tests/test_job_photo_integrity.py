"""A checklist token may only retain bounded images from its own upload account."""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp()
os.environ['DATABASE_URL'] = f'sqlite:///{TMP}/photos.db'
os.environ['SECRET_KEY'] = 'test'
os.environ['CLOUDINARY_CLOUD_NAME'] = 'cleaning-wonder'
os.environ['CLOUDINARY_UPLOAD_PRESET'] = 'job-photos'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from models import Booking, JobChecklist
from blueprints.workorders import MAX_JOB_PHOTOS_PER_PHASE

app = create_app()
app.config['TESTING'] = True

with app.app_context():
    db.create_all()
    booking = Booking(name='Photo Test', service_type='standard', status='pending')
    db.session.add(booking)
    db.session.flush()
    checklist = JobChecklist(booking_id=booking.id, token='photo-token')
    db.session.add(checklist)
    db.session.commit()

client = app.test_client()
route = '/workorders/checklist/photo-token/add-photo'
good = 'https://res.cloudinary.com/cleaning-wonder/image/upload/v1/jobs/before.jpg'

assert client.post(route, json={'phase': 'before', 'url': 'https://evil.example/track.jpg'}).status_code == 400
assert client.post(route, json={'phase': 'before', 'url': 'https://res.cloudinary.com/other/image/upload/x.jpg'}).status_code == 400
assert client.post(route, json={'phase': 'before', 'url': good}).status_code == 200
assert client.post(route, json={'phase': 'before', 'url': good}).status_code == 200

with app.app_context():
    checklist = JobChecklist.query.filter_by(token='photo-token').one()
    assert json.loads(checklist.before_photos) == [good]
    checklist.after_photos = json.dumps([
        f'https://res.cloudinary.com/cleaning-wonder/image/upload/v1/jobs/{i}.jpg'
        for i in range(MAX_JOB_PHOTOS_PER_PHASE)
    ])
    db.session.commit()

overflow = 'https://res.cloudinary.com/cleaning-wonder/image/upload/v1/jobs/overflow.jpg'
response = client.post(route, json={'phase': 'after', 'url': overflow})
assert response.status_code == 400
assert 'limit' in response.get_json()['error'].lower()
print('job photo integrity checks passed')
