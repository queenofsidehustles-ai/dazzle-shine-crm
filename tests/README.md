# Tests

Two kinds, both run against a throwaway database. Neither touches the live CRM,
real cleaners, or real money.

## Python — logic and money

```bash
for t in tests/test_*.py; do python3 "$t"; done
```

Each file prints what it checked in plain sentences, so a failure tells you what
broke rather than which line number threw.

| File | What it protects |
|---|---|
| `test_charge.py` | Charging a saved card takes the right amount and marks the job paid |
| `test_tips.py` | Tips stay the cleaner's, never counted as revenue |
| `test_team.py` | Crew jobs, per-cleaner pay, payout guards |
| `test_bugs.py` | Regressions found in real use |
| `test_calendar.py` | Drag-to-reschedule |
| `test_sendlog.py` | A message that fails is logged with the reason, never silently dropped |
| `test_streamline.py` | Booking confirmations and payment links |
| `test_connections.py` | API keys: encrypted, masked, owner-only |
| `test_portal_invite.py` | Monthly plans hold their date; nothing emails a customer without a preview |
| `test_settings_forms.py` | Saving one settings card can't wipe another |
| `test_whitelabel.py` | No trace of one business reaches another's instance |
| `test_whitelabel_existing.py` | White-labelling didn't change the original business |

## Browser — the whole flow

```bash
# start a local CRM with its own empty database
DATABASE_URL="sqlite:////tmp/e2e.db" SECRET_KEY=e2e-test \
  ADMIN_USER=e2e ADMIN_PASS=e2epass CRM_BASE=http://localhost:5001 \
  python3 -c "from app import create_app; create_app().run(port=5001)"

npx playwright test tests/local-e2e.spec.js
```

Safe by construction: with no Twilio or email keys set, sending returns "not
connected" instead of contacting anybody.

`booking-flow`, `hiring-flow` and `e2e` target a deployed instance — set
`CRM_BASE` (and `SITE_URL`) to point them somewhere. They default to localhost so
they can never surprise a live site.

## Before you push

Run the Python suites and `local-e2e.spec.js`. Together they take under a minute
and cover every path that moves money.
