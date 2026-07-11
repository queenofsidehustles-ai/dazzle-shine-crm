# Dazzle & Shine CRM

A full **operations system for a home-services (cleaning) business** — replacing
spreadsheets and disconnected apps with one integrated platform that runs bookings,
payments, communication, hiring, and contractor payouts.

Built for Dazzle & Shine Maids (Orlando, FL) and designed to be **white-labeled** as a
licensable product for any cleaning, landscaping, or home-maintenance company.

---

## What it does

| Area | Capability |
|------|------------|
| **Bookings & CRM** | Leads, quotes, scheduling, and customer history in one pipeline |
| **Customer payments** | Pay-by-link, morning-of auto-invoices, and on-site QR "Take Payment" |
| **Two-way messaging** | Automated + live SMS (Twilio) and email (Resend), with owner alerts |
| **Open-job board** | Jobs broadcast to the team; first available cleaner claims them |
| **Contractor payouts** | Automated splits via Stripe Connect |
| **Hiring** | Async video-interview screening and a guided job-quality checklist |
| **Automations** | Scheduled reminders, balance requests, and follow-up drips |

## Tech

- **Python + Flask** with SQLAlchemy (`app.py`, `blueprints/`, `auth.py`, `extensions.py`)
- Integrations: Stripe, Stripe Connect, Twilio, Resend
- Deployed on **Railway**
- Installable as a home-screen app (PWA)

## Project

Designed and built by **Monica Lewis**. Featured case study of AI Horizons Global
Consultants — [aihorizonsglobal.com](https://aihorizonsglobal.com).
