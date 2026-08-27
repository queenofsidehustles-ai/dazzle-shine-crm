# Backups

The business is in one Postgres database on Railway. Not a copy of the business
— the business. Every client, every job ever run, who cleaned it, what they were
paid, and the access notes that say where the key is kept.

This is how there comes to be a second copy, and how you find out it works
before you need it to.

---

## Set it up — about 20 minutes, once

### 1. Two secrets on GitHub

Repo → **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Where it comes from |
|---|---|
| `BACKUP_DATABASE_URL` | Railway → your Postgres service → **Variables** → **`DATABASE_PUBLIC_URL`** |
| `BACKUP_PASSPHRASE` | A long random string you generate. See below. |

> **It must be `DATABASE_PUBLIC_URL`, not `DATABASE_URL`.** The internal one
> points at `*.railway.internal`, which only resolves inside Railway. Used here
> it fails every night with a DNS error, and a nightly job that has been failing
> since March is worth less than no job at all, because you think you have
> backups.

Generate the passphrase:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Store that passphrase somewhere that is not this repository and not your
laptop.** A password manager, or written down at home. The backups are encrypted
with it; without it they are noise. Losing the laptop and the passphrase together
is the scenario this whole file exists to survive.

### 2. Run it once by hand

GitHub → **Actions → Nightly backup → Run workflow**.

Watch it go green. The run summary prints the row counts, and those should look
like your business — if it says 3 clients and you have 180, the connection
string is pointing at the wrong database.

After that it runs itself at 08:00 UTC nightly. GitHub emails you when a
scheduled workflow fails, so **do not filter those emails.** A silent failure is
the only kind that matters.

> GitHub disables scheduled workflows in a repository with no activity for 60
> days. You push most weeks, so this is unlikely — but if you ever step away for
> a couple of months, check the backup is still running when you come back.

---

## The restore drill — do this now, and then twice a year

**A backup nobody has restored is a file.** Until you have watched your own data
come back, you do not have backups, you have a routine that produces files.

Every nightly run already restores itself into a scratch database and counts the
rows back, so the *file* is checked automatically. What the drill adds is that
**you** have done it, with the real passphrase, on a laptop, at a moment when
nothing is on fire.

```bash
# 1. Actions → the latest Nightly backup run → Artifacts → download backup-N
unzip backup-123.zip

# 2. Decrypt it
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in backup-2026-08-27T08-00-00Z.json.gz.enc \
  -out restored.json.gz

# 3. Check it restores and the counts match
python3 backup.py --verify-only restored.json.gz

# 4. Put it in a scratch database and actually look at it
python3 backup.py --restore restored.json.gz --into "sqlite:///scratch.db" --yes
DATABASE_URL="sqlite:///scratch.db" ADMIN_USER=you ADMIN_PASS=temp-password-here \
  python3 app.py
```

Open it in a browser and log in. **Find a client you recognise. Open a job you
remember. Check the price is right.**

That is the drill. If that worked, you have backups.

Put a recurring reminder in your calendar for the 1st of January and the 1st of
July. It takes ten minutes and it is the only thing that keeps this file honest.

---

## Taking one by hand

Before anything you would rather be able to undo — a migration, a bulk edit, a
release you are unsure about:

```bash
DATABASE_URL="<the Railway public URL>" python3 backup.py --verify
```

Other things it does:

```bash
python3 backup.py --list                 # what you have
python3 backup.py --verify-only FILE     # check one restores
python3 backup.py --restore FILE --into URL   # put it back
```

`--restore` **deletes everything in the target first** and makes you type
`RESTORE` to confirm. That is deliberate. `--into` has no default, because a
tool that guesses which database to overwrite will eventually guess wrong.

---

## Putting it back for real

The day you actually need this, work in this order. Do not rush step 1.

1. **Stop writing to the broken database.** Pause the Railway service. Every
   minute it stays up is another booking written into a state you are about to
   replace, and those will be gone.
2. **Take a backup of the broken database anyway.** It is the only copy of
   whatever happened between last night and now, and you may want it later.
   `python3 backup.py --dir ./broken`
3. **Decrypt last night's backup** and `--verify-only` it *before* touching
   anything. If it does not verify, use the night before — that is what the
   30-day window is for.
4. **Restore into a fresh Postgres database, not over the broken one.** Add a
   new Postgres service in Railway, restore into that, and point the app at it
   once it looks right. Restoring on top of the damaged database means that if
   the restore is wrong too, there is nothing left to try again from.
5. **Look at it before you tell anyone it is fixed.** Clients, this week's jobs,
   the crew list, last month's P&L.
6. **Then work out what is missing.** Everything between the backup and the
   incident is gone — up to 24 hours of bookings. Your texts, your email and
   your Stripe dashboard are the record of what happened in that window.

---

## What this covers, and what it does not

**Covers:** a dropped table, a bad migration, a bulk edit that went wrong, a
deleted Railway project, a suspended account, Railway having a bad day, and
losing your laptop.

**Does not cover:**

- **Up to 24 hours of work.** It runs nightly. A failure at 7pm loses that day's
  bookings. Take a manual one before anything risky.
- **Uploaded files.** Contractor documents, W-9s and interview videos live in
  Cloudinary, not in the database. The database keeps the URLs; Cloudinary keeps
  the files. If that account goes, the links point at nothing. Worth solving
  separately — it is currently the biggest uncovered gap.
- **Stripe.** Your money history lives at Stripe and is their problem, which is
  the right place for it.

---

## How it works, briefly

`backup.py` reads every table through SQLAlchemy and writes one gzipped
JSON-lines file, in foreign-key order so it can be inserted straight back.

It is deliberately **not** `pg_dump`. `pg_dump` makes a better backup and needs
the Postgres client tools installed at the same major version as the server —
one more thing that has to be working on the day everything else is on fire.
This needs nothing but Python, restores into Postgres or SQLite, and does not
care what version either one is.

**The schema is not in the backup.** It is built from `models.py` by
`create_all()` at restore time, which means a backup taken in March restores into
today's code and picks up every column added since.

Two checks guard against the failure that actually happens — not a crash, which
is loud, but a run that completes happily against an empty or wrong database and
writes a valid backup of nothing, night after night, until you need it:

- **Every run is restored and counted back** before it is accepted.
- **Every run is compared to the last one.** A critical table going from
  thousands of rows to zero, or the database shrinking by more than a third
  overnight, fails the job loudly. A brand-new instance with nothing in it
  passes, because there is nothing to compare it against yet.

Backups are gitignored. They contain customer home addresses and access notes
and must never be committed.
