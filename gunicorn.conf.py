"""Web server settings. gunicorn reads this file from the working directory on
its own, so the start command in the Railway dashboard does not need to change.

Before this the site ran gunicorn's defaults: ONE worker, 30-second timeout.
Every company shared that one worker, so a single slow request -- a bulk send,
a Stripe call, a big CSV -- stalled the site for all of them, and anything
past 30 seconds was killed mid-way.

Processes, not threads. Payment code sets `stripe.api_key` on the module for
each request, which is safe one request per process and not safe with two
requests sharing a process. So: several sync workers.

Each worker is a full copy of the app (roughly 150-250 MB). Three fits
comfortably on Railway's standard plans; raise WEB_CONCURRENCY once memory
shows headroom.
"""
import os


def _int(name, default):
    try:
        return max(1, int(os.environ.get(name) or default))
    except ValueError:
        return default


workers = _int('WEB_CONCURRENCY', 3)
worker_class = 'sync'
timeout = _int('GUNICORN_TIMEOUT', 60)
graceful_timeout = 30
# Recycle each worker after a while, so a slow leak never takes the site down.
max_requests = 2000
max_requests_jitter = 200
