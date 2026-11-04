"""Read a business's own website: what it says about itself, and its public email.

Envoy's drafts are only as specific as what it knows, and a Google listing
knows a name, a category and a phone number. The business's own homepage says
what it actually is -- "family dental practice since 1998", "three locations",
"now leasing" -- and very often lists the email address it wants enquiries
sent to, which Google never has. One read of the homepage, and of its contact
page when the homepage shows no address, is enough for both.

## Only public websites, and only a little of each

The address comes from a Google listing, which anybody can edit, so it is
treated as untrusted:

  * http and https only, ports 80 and 443 only;
  * every address the host resolves to must be a public internet address --
    never this server, its private network, or a cloud metadata endpoint --
    checked again on every redirect, at most three;
  * eight seconds and 400 KB per page, HTML only.

What the page says is handed to Claude as data about the business, never as
instructions (envoy.SYSTEM says so), and a draft still has to pass
envoy.problems() before anybody sees it.

Never raises: a site that is down, slow or odd is simply a business Envoy
knows less about.
"""
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

TIMEOUT = 8
MAX_BYTES = 400_000
MAX_REDIRECTS = 3
SUMMARY_CHARS = 1500
UA = 'Mozilla/5.0 (compatible; AkyeEnvoy/1.0; reads a business homepage once)'

_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
# Addresses that appear in page source and are nobody's inbox.
_JUNK_DOMAINS = ('sentry', 'wixpress', 'example', 'domain.com', 'email.com', 'yourdomain',
                 'godaddy', 'squarespace', 'wordpress', 'schema.org', 'w3.org',
                 'googleapis', 'cloudflare', 'mysite', 'website.com')
_JUNK_SUFFIX = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js')
_PREFERRED = ('info', 'office', 'contact', 'hello', 'admin', 'frontdesk', 'manager',
              'leasing', 'facilities', 'operations', 'service', 'inquiries', 'enquiries')


class Blocked(Exception):
    """Not a public website we may read."""


def _public(host):
    """Every address `host` resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        raise Blocked('that address does not exist')
    addrs = {i[4][0] for i in infos}
    if not addrs:
        raise Blocked('that address does not exist')
    for a in addrs:
        ip = ipaddress.ip_address(a.split('%')[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked('not a public internet address')
    return True


def check_url(url):
    """The URL, normalised, or Blocked. Pure apart from the DNS lookup."""
    url = (url or '').strip()
    if url and '://' not in url:
        url = 'https://' + url
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise Blocked('not a web address')
    if p.username or p.password:
        raise Blocked('not a plain web address')
    if p.port not in (None, 80, 443):
        raise Blocked('not a standard web port')
    _public(p.hostname)
    return url


def _fetch(url):
    """(final_url, html) for one page, following redirects only to public
    addresses. Raises on anything else."""
    import requests
    for _ in range(MAX_REDIRECTS + 1):
        url = check_url(url)
        r = requests.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True,
                         headers={'User-Agent': UA, 'Accept': 'text/html'})
        try:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('Location'):
                url = urljoin(url, r.headers['Location'])
                continue
            if r.status_code != 200:
                raise Blocked(f'the site answered {r.status_code}')
            if 'html' not in (r.headers.get('Content-Type') or 'text/html').lower():
                raise Blocked('not a web page')
            body = b''
            for chunk in r.iter_content(16_384):
                body += chunk
                if len(body) >= MAX_BYTES:
                    break
            return url, body[:MAX_BYTES].decode(r.encoding or 'utf-8', 'replace')
        finally:
            r.close()
    raise Blocked('too many redirects')


class _Page(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'template', 'iframe'}
    KEEP = {'h1', 'h2', 'h3', 'p', 'li'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.description = '', ''
        self.parts, self.mailtos, self.links = [], [], []
        self._skip, self._in, self._buf, self._in_title = 0, None, [], False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP:
            self._skip += 1
        elif tag == 'title':
            self._in_title = True
        elif tag == 'meta' and (a.get('name') or a.get('property') or '').lower() in (
                'description', 'og:description') and not self.description:
            self.description = (a.get('content') or '').strip()
        elif tag == 'a':
            href = (a.get('href') or '').strip()
            if href.lower().startswith('mailto:'):
                self.mailtos.append(href[7:].split('?')[0])
            elif href:
                self.links.append(href)
        if tag in self.KEEP and not self._skip:
            self._in, self._buf = tag, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == 'title':
            self._in_title = False
        elif tag == self._in:
            text = ' '.join(''.join(self._buf).split())
            if len(text) > 2:
                self.parts.append(text)
            self._in = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        if self._in:
            self._buf.append(data)


def _domain(url_or_host):
    host = (urlparse(url_or_host).hostname if '://' in url_or_host else url_or_host) or ''
    host = host.lower().removeprefix('www.')
    bits = host.split('.')
    return '.'.join(bits[-2:]) if len(bits) >= 2 else host


def pick_email(candidates, site_url):
    """The address the business wants enquiries sent to, or ''.

    Only an address on the business's own domain: a gmail address on a page is
    as likely to be the web designer's as the owner's, and the wrong person
    receiving cold email is exactly what this exists not to do."""
    own = _domain(site_url)
    seen, good = set(), []
    for raw in candidates:
        e = raw.strip().strip('.,;:<>()[]"\'').lower()
        if not _EMAIL.fullmatch(e) or e in seen:
            continue
        seen.add(e)
        dom = e.split('@', 1)[1]
        if e.endswith(_JUNK_SUFFIX) or any(j in dom for j in _JUNK_DOMAINS):
            continue
        if own and _domain(dom) == own:
            good.append(e)
    good.sort(key=lambda e: (0 if e.split('@')[0] in _PREFERRED else 1, len(e)))
    return good[0] if good else ''


def parse(html, url):
    """{'title', 'summary', 'emails', 'contact_url'} from one page's HTML."""
    page = _Page()
    try:
        page.feed(html or '')
    except Exception:
        pass
    text_emails = _EMAIL.findall(' '.join(page.parts))
    summary, used = [], 0
    for chunk in ([page.description] if page.description else []) + page.parts:
        if used + len(chunk) > SUMMARY_CHARS:
            break
        if chunk not in summary:
            summary.append(chunk)
            used += len(chunk) + 1
    contact = ''
    host = urlparse(url).hostname or ''
    for href in page.links:
        full = urljoin(url, href)
        if 'contact' in full.lower() and (urlparse(full).hostname or '') == host:
            contact = full
            break
    return {'title': ' '.join(page.title.split())[:200],
            'summary': '\n'.join(summary)[:SUMMARY_CHARS],
            'emails': page.mailtos + text_emails,
            'contact_url': contact}


def read(url, fetch=None):
    """What a business's site says. Never raises.

    {'ok', 'url', 'title', 'summary', 'email', 'error'}."""
    fetch = fetch or _fetch
    out = {'ok': False, 'url': (url or '')[:300], 'title': '', 'summary': '',
           'email': '', 'error': ''}
    if not (url or '').strip():
        out['error'] = 'no website listed'
        return out
    try:
        final, html = fetch(url)
        home = parse(html, final)
        out.update(ok=True, url=final[:300], title=home['title'], summary=home['summary'])
        email = pick_email(home['emails'], final)
        if not email and home['contact_url']:
            try:
                c_url, c_html = fetch(home['contact_url'])
                email = pick_email(parse(c_html, c_url)['emails'], final)
            except Exception:
                pass
        out['email'] = email
    except Blocked as e:
        out['error'] = str(e)[:200]
    except Exception as e:  # noqa: BLE001
        out['error'] = f'could not read the site ({type(e).__name__})'
    return out
