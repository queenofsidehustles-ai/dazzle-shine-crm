"""The short videos that walk a new owner through setup.

Six of them, each a minute or so, recorded on Loom. Each one sits next to the
thing it explains -- on the signup page, beside a Getting Started step, in the
email that asks for that step -- rather than on a help page nobody opens.

The links live in the environment, not in code, so a re-recorded video is a
settings change on Railway rather than a deploy:

    AKYE_VIDEO_OVERVIEW            what it looks like once it is set up (signup page)
    AKYE_VIDEO_SIGNUP              sign up and find your address
    AKYE_VIDEO_TEAM_AND_CUSTOMER   add a cleaner, add a customer
    AKYE_VIDEO_BOOKING_PAGE        your booking page and where to put the link
    AKYE_VIDEO_BOOK_JOB            book a job and send it to a cleaner
    AKYE_VIDEO_MIGRATION           bring your old list over

A video that is not set simply does not appear. Nothing here ever shows a
broken player or an empty box.

In email a video is a still picture that links out, never an embed: most mail
apps strip embedded players, and what is left is a blank rectangle.
"""
import html as _html
import os
import re

VIDEOS = {
    'overview': ('What it looks like once it is set up', 'AKYE_VIDEO_OVERVIEW'),
    'signup': ('Sign up and find your address', 'AKYE_VIDEO_SIGNUP'),
    'team_and_customer': ('Add a cleaner and a customer', 'AKYE_VIDEO_TEAM_AND_CUSTOMER'),
    'booking_page': ('Your booking page, and where to share it', 'AKYE_VIDEO_BOOKING_PAGE'),
    'book_job': ('Book a job and send it to a cleaner', 'AKYE_VIDEO_BOOK_JOB'),
    'migration': ('Bring your customer list over', 'AKYE_VIDEO_MIGRATION'),
}

_LOOM = re.compile(r'loom\.com/(?:share|embed)/([0-9a-f]{20,})', re.I)


def url(key):
    """The watch link, or '' when that video has not been recorded yet."""
    meta = VIDEOS.get(key)
    if not meta:
        return ''
    value = (os.environ.get(meta[1]) or '').strip()
    return value if value.startswith('https://') else ''


def title(key):
    meta = VIDEOS.get(key)
    return meta[0] if meta else ''


def loom_id(link):
    m = _LOOM.search(link or '')
    return m.group(1) if m else ''


def thumbnail(key):
    """A still with a play button, for email. Loom serves one per video."""
    vid = loom_id(url(key))
    return f'https://cdn.loom.com/sessions/thumbnails/{vid}-with-play.gif' if vid else ''


def embed_url(key):
    vid = loom_id(url(key))
    return f'https://www.loom.com/embed/{vid}' if vid else ''


def all_set():
    """{key: url} for the videos that exist, for templates."""
    return {k: url(k) for k in VIDEOS if url(k)}


def email_block(key, caption=None):
    """The video as it should appear in an email, or '' when there is none."""
    link = url(key)
    if not link:
        return ''
    cap = _html.escape(caption or f'Watch: {title(key)} (about a minute)')
    thumb = thumbnail(key)
    pic = (f'<a href="{_html.escape(link)}"><img src="{_html.escape(thumb)}" '
           f'alt="{cap}" width="480" style="max-width:100%;border-radius:10px;'
           f'border:1px solid #e6eaf2;display:block"></a>') if thumb else ''
    return (f'<div style="margin:18px 0">{pic}'
            f'<p style="margin:8px 0 0;font-size:14px"><a href="{_html.escape(link)}" '
            f'style="color:#16213a;font-weight:600">&#9654; {cap}</a></p></div>')
