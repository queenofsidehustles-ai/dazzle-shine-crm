# Dazzle & Shine — Email Marketing Automation Plan

Full customer-lifecycle email system (Jobber/Zenmaid style). Built on what already
exists; **bold ⭐/🆕 = new**. All customer-facing emails are editable in the
**Email Templates** admin page. Timing is driven by a daily cron (same system as
reminders/drips). No email sends twice (tracked with timestamps).

---

## Stage A — LEAD (requested a quote, hasn't booked)  → goal: convert to booking
| # | Email | When | Status |
|---|-------|------|--------|
| A1 | Instant Quote | immediately | ✅ exists (`lead_quote`) |
| A2 | Day 2 Follow-Up | 2 days after quote | ✅ exists (`lead_drip_day2`) |
| A3 | Last Chance + 10% off | ~5 days after quote | ✅ exists (`lead_drip_lastchance`) |
| A4 | **Final "still here for you"** | ~10 days, then stop | 🆕 build |

## Stage B — BOOKED (deposit paid)  → goal: reduce no-shows
| # | Email | When | Status |
|---|-------|------|--------|
| B1 | Booking Confirmation | immediately | ✅ exists (`booking_confirmed`) |
| B2 | 24-Hour Reminder | day before | ✅ exists (`booking_reminder_24h`, via reminders cron) |
| B3 | **Morning-of note** ("balance charged today, see you soon") | morning of job | 🆕 build (optional) |

## Stage C — AFTER THE CLEANING (job marked "Completed")  → goal: reviews + recovery
| # | Email | When | Status |
|---|-------|------|--------|
| C1 | Follow-up email | on completion | ✅ exists (`_send_followup_email`) |
| C2 | Review / Google review request | on completion | ✅ exists (`_send_rating_request`) |
| C3 | **Review nudge** (if no rating yet) | 3 days after, once | 🆕 build |
| C4 | **Low-rating internal alert** (< 4 stars → tell Monica) | on rating | 🆕 build (owner alert) |

> ⚠️ C1/C2 only fire when a job is marked **Completed** in the CRM. Marking jobs
> complete is the switch that turns on the whole post-cleaning flow.

## Stage D — RETENTION / UPSELL (the big new value)  → goal: turn one-time into recurring
| # | Email | When | Status |
|---|-------|------|--------|
| D1 | **⭐ One-time → Recurring upsell** — "Loved it? Go Weekly/Bi-Weekly/Monthly and save 5–15%" | 2 days after a **one-time** job completes | ⭐ **BUILD (priority)** |
| D2 | **Upsell nudge** (2nd, if no rebook) | ~9 days after, once | 🆕 build |
| D3 | **Win-back / "We miss you"** + small discount | customer with no booking in ~50 days | 🆕 build |
| D4 | **Recurring "your next clean is coming"** | before next recurring date | 🆕 build (optional; overlaps B2) |

Recurring discounts already in pricing: **Monthly 5% · Bi-Weekly 10% · Weekly 15%**.
Upsell emails quote the customer's real price at each frequency.

## Stage E — OWNER / INTERNAL ALERTS
| # | Email | Status |
|---|-------|--------|
| E1 | New Booking Alert | ✅ exists |
| E2 | New Application Alert | ✅ exists |
| E3 | Payment Failed Alert | ✅ exists |
| E4 | **Low-rating alert** (see C4) | 🆕 build |

---

## Smart rules (so it feels human, not spammy)
- **One-time only** gets the recurring upsell (D1/D2) — never recurring customers.
- **Never send the same email twice** — each has a `*_sent_at` timestamp.
- **Stop when they act** — e.g., if a lead books, drips stop; if they rebook, upsell stops.
- **Quiet hours** — lifecycle emails send during the daily cron window, not midnight.
- **Opt-out link** on all *marketing* emails (drips, upsell, win-back) — legally required
  (CAN-SPAM) and keeps your sender reputation clean. Transactional emails
  (confirmation, reminder, receipt) don't need it.

## Technical foundation
- **New editable templates** seeded for: A4, C3, D1, D2, D3, D4 → you can reword any in the UI.
- **New cron endpoint** `/api/lifecycle-emails` (runs daily on cron-job.org, same as your others)
  finds bookings/leads at each stage and sends the right email once.
- **New tracking fields** (Booking/Client): `upsell_sent_at`, `upsell_nudge_at`,
  `review_nudge_at`, `winback_sent_at`, `last_booking_at`.
- **Opt-out**: `email_opt_out` flag + one-click unsubscribe route; marketing emails skip opted-out people.
- **Controls**: an "Automations" view showing each automation on/off (nice-to-have).

## Build order (all in one delivery, but this is the internal sequence)
1. Tracking fields + migrations + opt-out plumbing
2. Seed the new editable templates (A4, C3, D1, D2, D3)
3. `/api/lifecycle-emails` cron with the smart rules
4. Low-rating owner alert (C4/E4)
5. Wire opt-out link into marketing emails
6. Verify + document the one new cron job for cron-job.org
