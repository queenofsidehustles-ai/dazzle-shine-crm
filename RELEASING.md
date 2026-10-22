# Releasing to customers

Every instance used to deploy from `main`. A change pushed at eleven at night
was live in a paying customer's business three minutes later, before anyone had
used it once. This is how that stops.

## The branches now (October 2026)

Dazzle & Shine moved onto Akye as one of its companies. Akye works on `main`
and releases to `akye-stable`.

| Branch | What it is |
|---|---|
| `main` | **Akye's working branch.** Every pull request targets it, and its checks run on every pull request and push. Nothing deploys it: merging is not releasing. |
| `akye-stable` | **Every cleaning company on Akye**, Dazzle & Shine included. Railway deploys it. It moves only when a release promotes `main` to it, fast-forward. |
| `dazzle-shine-single-tenant` | The last single-business CRM: `main` as it was at `3b0cc92` (29 Sep 2026), before Akye was first promoted onto it, plus the commits that let its own `release.py` ship the CRM from this branch. An archive: nothing deploys it, and `release.py --go` from a checkout of it is the only way to move `stable`. |
| `stable` | The single-business CRM's customer channel (`v2026.09.21`). Frozen. |

### Releasing Akye

    git checkout main && git pull
    python3 release.py --akye           # what would go out — changes nothing
    python3 release.py --akye --go      # every suite, then tag and promote akye-stable
    python3 release.py --akye --rollback   # akye-stable back one release

`--go` refuses unless the four checks that ran on the push to `main` (the
full suite, the launch certification, the golden journeys and privacy
lifecycle) all passed on that exact commit. It asks GitHub with `gh`; without
it, you paste the link to each check's run (a different run for each: they
are four separate workflows) and name a second person who checked them, and
both go into the release's tag (a typed-back hash is not evidence, and the
exception needs somebody other than the releaser). Then every suite runs again here on Python 3.12, and only then does it
write `RELEASE` (the one change on top of the checked commit), tag
`akye-vYYYY.MM.DD`, and fast-forward `akye-stable` to `main`. Railway deploys
it; the push to `akye-stable` certifies the exact deployed commit once more.
A fix goes in on `main` and goes out in the next release; `akye-stable` never
takes a commit `main` does not have.

The release's record is its tag. `git show akye-vYYYY.MM.DD` gives the
checked commit, each required check with the run it passed in, the migration
head every company moves to, the changes, and the rollback command; `--go`
prints the same at the end.

`--rollback` starts from the release `akye-stable` is on and goes back one,
so running it twice goes back two.

Everything that touches production runs the release, not `main`: Railway,
the nightly Akye backup, and the hourly and daily automations, which check
out `akye-stable` even though their schedule fires from `main`.

The rest of this page describes the two-product setup it replaced, and is kept
for its history.

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

## Making main the working branch

`akye-stable` contains `main` (main was merged into it, keeping akye-stable's
code, after checking every change main had made was already here), so `main`
moves to it as a fast-forward: no reset, no force-push, nothing in main's
history lost. Railway stays on `akye-stable`; nothing deploys.

    git fetch origin
    git merge-base --is-ancestor origin/main origin/akye-stable && echo ok
    git push origin origin/akye-stable:main      # refused unless it fast-forwards

From then on, open pull requests against `main` (retarget any still open
against `akye-stable`), and release with `release.py --akye --go`. Protect both
branches in GitHub: `main` to require a pull request and its four checks,
`akye-stable` to refuse force-pushes and deletion. `--go` pushes its `RELEASE`
commit straight to `main` and moves `akye-stable` itself, so whoever releases
must be allowed to bypass those rules (an admin, with bypass left on); a
`--rollback` force-pushes `akye-stable`, so it needs that bypass too.

A service still deploying `main` (your old instance, above) would now take
every merge. `main` has carried Akye's code since the first promotion
(81a635d), so such a service already runs it as a single business (no
`BASE_DOMAIN`); main's photo-wording migration id is kept as a no-op
(`0021_photo_optional_wording`), so its database upgrades through
0021_quote_prospect to 0033 with every row kept. Better to retire it.

### What a dry run of the promotion found (20 Oct 2026)

Rehearsed on a database built by main's own code (migrations, then the demo
seed), with akye-stable's code run against it as the push would:

- **Startup:** migrates 0021_photo_optional_wording → 0033, rows unchanged,
  pages load.
- **Nightly backup of your own database** (the `dazzle` job, which checks out
  `main`): failed on akye-stable's backup.py while that database had not been
  migrated, demanding contract evidence it predates. Fixed: the manifest now
  records which schemas had an audit chain at source, and only those are held
  to it. That database has not changed between nightly backups (every table's
  count identical, including `cron_run`), so nothing is running against it
  and it would have stayed on 0021, and failed, every night.
- **release.py** mapped the CRM line `main → stable`, so once `main` was Akye,
  `release.py --go` would have put Akye on `stable`. It now ships the CRM from
  `dazzle-shine-single-tenant`, and Akye `main → akye-stable`.
- **CI** ran only for `akye-stable`, so pull requests against `main`, the
  default branch, got no checks. Every workflow now runs for `main` too.
