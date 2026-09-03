# Releasing to customers

Every instance used to deploy from `main`. A change pushed at eleven at night
was live in a paying customer's business three minutes later, before anyone had
used it once. This is how that stops.

## Two products, four branches

There are two things being shipped, and each has a working branch and a channel
that deployed instances follow.

| Branch | Who runs it | When it moves |
|---|---|---|
| `main` | **Your own instance.** | Every push. Immediately. |
| `stable` | **Every customer instance of the CRM.** | Only when you release. |
| `feature/tenancy` | **Nobody.** The bench where Akye is built. | Every push. |
| `akye-stable` | **Every cleaning company on Akye.** | Only when you release. |

Your business is the canary for the CRM. A change lands on `main`, you use it on
your own bookings for a day or two, and whatever is wrong with it is wrong for
you rather than for someone whose payroll depends on it. When it has earned its
keep, you promote it.

Akye has no canary — nobody's own business runs it — so the test suite is the
only gate, which is why the gate is the whole suite and not a subset.

> **Akye used to have no gate at all.** It deployed straight off
> `feature/tenancy` on every push, so anything typed went live to businesses
> paying to use it. `/version` still said `channel: feature/tenancy`, which was
> the tell. If you ever see a channel that is a working branch rather than a
> `*-stable` one, that instance is taking every change the moment it is pushed.

## Releasing

```bash
python3 release.py                 # the CRM: what would go out — changes nothing
python3 release.py --go            # the CRM: test, tag, promote stable

python3 release.py --akye          # Akye: what would go out
python3 release.py --akye --go     # Akye: test, tag, promote akye-stable
```

`--go` refuses to release if you have uncommitted work, if your branch and
GitHub's disagree, or if **any** test suite fails. Nothing reaches a customer
that hasn't passed the full suite on your machine first.

**You must be on the branch you're releasing.** The tests run against whatever
is checked out, so releasing Akye from a `main` checkout would test one product
and ship the other — green, and meaningless. The script checks and refuses:

```
You are on “main” but releasing Akye, which ships from “feature/tenancy”.
```

Releases are tagged per product — `v2026.09.03` for the CRM,
`akye-v2026.09.03` for Akye — so two releases on the same day can't take each
other's number, and `--rollback` can't walk one product back onto a release
built for the other.

It tags each release by date — `v2026.08.20`, then `v2026.08.20.2` if you
release twice in a day — so every instance can tell you exactly which release it
is running.

## When a release goes wrong

```bash
python3 release.py --rollback
```

Customers go back to the previous release within a few minutes. **Their data is
untouched** — this only changes which code runs against it.

One caveat worth understanding: a release that added a database column can be
rolled back safely, because the old code ignores a column it doesn't know about.
A release that *removed* or *renamed* one cannot. Adding is safe, removing is
not — which is why `_migrate_db()` in `app.py` only ever adds.

## What a release actually publishes

Tagging a release pushes the tag, and CI builds the customer image from it:

```
ghcr.io/queenofsidehustles-ai/dazzle-shine-crm:v2026.08.19.3   # that release
ghcr.io/queenofsidehustles-ai/dazzle-shine-crm:stable          # what customers follow
```

Customers deploy the **image**, not this repository — they get every release and
never get the code. Nothing needs Docker on your laptop; the build runs in
GitHub Actions. Watch it with `gh run list --workflow=publish-image.yml`.

If a build fails, the tag exists but the image does not, and customers simply
stay where they are. Fix it and run `release.py --go` again, or re-run the
workflow by hand from the Actions tab.

## Checking what an instance is running

Open `/version` on any instance. No login needed:

```json
{"build": "de446b9", "channel": "stable", "release": "v2026.08.20"}
```

- `channel: stable` — a customer instance, moving only on release
- `channel: main` — your own, moving on every push

It's also at the foot of the sidebar on every page. When a customer reports
something odd, this is the first thing to ask for: two instances behaving
differently is almost always two different releases.

## Setting up a new customer instance

In Railway → their service → **Settings → Source**:

- Repository: this repo
- **Branch: `stable`** ← the one thing that must not be `main`

Everything else follows **NEW_CUSTOMER_SETUP.md**. If you ever find a customer's
service pointing at `main`, that instance is taking every change the moment it's
pushed — put it back on `stable`.

## The Akye service

Same rule, different branch. In Railway → the Akye service → **Settings →
Source**:

- **Branch: `akye-stable`** ← not `feature/tenancy`

This is the one manual step that makes the Akye channel real. Until the service
is repointed, `akye-stable` exists and nothing follows it, and Akye carries on
deploying every push to `feature/tenancy`.

Check it took: `https://www.akyehq.com/version` should report
`"channel":"akye-stable"`. If it still says `feature/tenancy`, the source
didn't save.

## Your own instance

Stays on `main` deliberately. You want your changes immediately; that is the
whole point of being the canary. If you'd rather be on the same footing as your
customers, point your own service at `stable` too and release to everyone at
once — but then nobody is testing anything before customers see it.
