# Security

What protects the data in here, what does not yet, and why.

Two different businesses' data sits in this database: yours, and — on Akye —
every cleaning company paying to use it. Their client home addresses, the note
saying where the key is kept, their cleaners' W-9s and background checks. This
file is the honest account of how that is held.

## What is in place

**One company cannot see another's data.** Every company gets its own
PostgreSQL schema, and the `search_path` is set on every checkout from the
connection pool rather than per request — a connection handed back to the pool
carrying the last company's path is the classic version of this bug, and the
pool guard is what prevents it. `tests/test_tenancy.py` covers thirteen groups
of this, including that dropping a schema refuses to touch anything that is not
a company's.

**Passwords** are hashed with `pbkdf2:sha256`. They are never stored and cannot
be recovered, only reset.

**Sessions** are `HttpOnly` so no script can read the cookie, `SameSite=Lax` so
it is not sent on a cross-site POST, and HTTPS-only in production. They expire
after fourteen days, because a shared office laptop should not stay signed in
forever.

**Cross-site request forgery** is refused by checking where a state-changing
request says it came from. The exemptions are deliberate and listed in
`security.py`: Stripe's webhook, which is verified by signature instead, and
Twilio's inbound texts.

**Repeated failed logins** from one address are throttled. Attempts are written
down without the password and without enough of the username to be worth
stealing.

**The three documents worth stealing** — driver's licence, W-9, background
check — are encrypted and stored in the database, never given a public URL, and
readable only behind the owner's login. `secure_docs.is_ready()` reports when
`SECRET_KEY` is still the development default, so the interface can say the
protection is absent rather than imply one that is not there.

**Saved API keys** (Stripe, Twilio, Resend) are Fernet-encrypted at rest.

**Backups** are AES-256 encrypted before they leave the build machine, and every
night the job restores what it just made and counts the rows back. A backup
nobody has restored is a file, not a backup.

## What is not in place

Listed because an undocumented gap is one nobody fixes.

**No HTTP security headers.** No HSTS, Content-Security-Policy, X-Frame-Options
or Referrer-Policy are sent. A customer's page can be framed by another site,
and a browser that once reached us over HTTP is not told never to do so again.

**Job photos are public to anyone holding the link.** They go to Cloudinary
through an unsigned preset, which returns a long random but entirely public URL
— see the note at the top of `secure_docs.py`. For a before-and-after of a
kitchen that is a reasonable trade. These are photographs of the inside of
customers' homes and the link lives in texts and email indefinitely, so it is a
trade worth making deliberately rather than by default.

**No two-factor authentication.** An owner's password is the only thing between
an attacker and every client address, access note and W-9 in that company.

**The database is reachable from the internet.** Public networking is on so the
nightly backup can reach it from outside Railway, which is the point of running
the backup somewhere else. It is protected by its password alone.

**`SECRET_KEY` is a single point of failure.** It signs sessions and derives the
keys for both saved API keys and encrypted documents. Rotating it does not error
— it silently makes all of them unreadable.

## Dependencies

Pinned in `requirements.txt` so every instance runs what was tested. A version
moves when it fixes a published vulnerability, not because it is newer.

Checked with:

```bash
python3 -m pip_audit -r requirements.txt
```

### Outstanding

None. `pip-audit` reports no known vulnerabilities in what this ships.

That was not true earlier: nine remained, in `aiohttp`, `click`, `python-dotenv`,
`requests` and `urllib3`, and every one was fixed only in a release requiring
Python 3.10 or newer. The tests ran on the laptop's 3.9 while production built on
3.12, so the safe versions were available to production and could not be verified
by the suite that gates the release. Pinning them anyway would have shipped
versions the tests had never run against, which is the trade this project
refuses everywhere else.

The fix was to move the gate onto the version production uses rather than to pin
past it:

```bash
brew install python@3.12
python3.12 -m pip install -r requirements.txt
python3.12 release.py --akye        # the gate now runs where production runs
```

`aiohttp`, `urllib3` and `click` are pinned explicitly although nothing here
imports them. They arrive through twilio, requests and flask, and the versions
those resolve to on their own still carried published vulnerabilities. A
transitive dependency is no less reachable for being unmentioned.

### The gate checks its own footing

`release.py` now refuses to run the suite on anything older than the version in
`docker/Dockerfile`, and `tests/test_release.py` checks the two agree.

This is not tidiness. Moving the suite to 3.12 changed a money test: Python 3.12
gave `sum()` compensated summation for floats, so ten dimes come to exactly
$1.00 there and to $0.9999999999999999 on 3.9. The suite had been recording the
drift as current behaviour while production, built on 3.12, no longer had it.
A test green on a version nobody runs is not a gate, and the difference showed
up in money.

### There is no CI running the test suite

Worth stating plainly, because it is easy to assume otherwise. GitHub Actions
runs the nightly backup and the customer image build. **It does not run the
tests.** The only thing that runs the full suite is `release.py` on one laptop,
which is why the version of Python on that laptop is a security question and not
a preference — and why the gate now refuses to run on the wrong one.

## Reporting something

Email the address on the site. If it concerns a specific company's data, say so
without including any of it.
