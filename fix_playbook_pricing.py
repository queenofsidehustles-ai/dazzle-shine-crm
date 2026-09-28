"""Correct the pricing tiers in the "Growth Program" playbook.

That playbook's ## Akye pricing tiers section was written before entitlements.py
was found -- it proposed $0/$29/$79 tiers that don't exist. The product's real,
already-implemented pricing is $0/$79/$249 (see entitlements.PLANS), enforced by
every feature gate in the app and wired to Stripe. This corrects the playbook's
text in place -- same row, same title, only the content changes -- rather than
adding a duplicate.

Run once, the same way seed_growth_playbook.py is:

    railway run python3 fix_playbook_pricing.py
"""
import sys

import control_plane
import provisioning

TITLE = 'Growth Program — Overview & Strategy'

OLD_SECTION = r"""## Akye pricing tiers

No pricing tiers exist in the codebase today (no billing/plan-gating logic in models.py or elsewhere) — this is a proposal built to support the growth program above, priced to stay meaningfully under the competitors in the comparison section while still being sustainable. It needs sign-off from whoever owns product/pricing before it's published anywhere.

| Tier | Price | Users | Key features | Best for |
| --- | --- | --- | --- | --- |
| Free | $0, forever | 1 | Bookings & CRM (up to 50 active customers), manual pay-by-link, email-only customer messaging, Akye branding on customer-facing pages | Solo operators just leaving spreadsheets |
| Pro | $29/mo | Up to 3 | Unlimited customers, auto-invoices + on-site QR payment, two-way SMS + email, automations & follow-up drips, no branding | Small crews (1–3 people) ready to stop manually chasing payments and leads |
| Team | $79/mo | Up to 10 | Everything in Pro, plus the open-job board, contractor payouts via Stripe Connect, hiring/video-interview screening, priority support | Growing crews with contractors or W-2 hires |
| White-label / Enterprise | Custom — contact sales | Unlimited | Full white-label licensing under the licensee's own brand and domain, dedicated onboarding, everything in Team | Other cleaning, landscaping, or home-maintenance companies licensing Akye as their own platform (the model the README already describes) |

How this reconciles with the founding-cohort offer used throughout this plan: "free forever for the first 500 signups" means Pro tier access at $0, not a fifth tier — it's a time-limited, quantity-limited promotion on top of the real pricing above. Once the cohort closes (or the 500 spots fill), new signups land on the standard Free tier by default and can upgrade to Pro at $29/mo. This is why the founding-cohort deadline in week 3 matters for real unit economics, not just marketing urgency — it caps how many users get Pro-tier features at zero long-term revenue."""

NEW_SECTION = r"""## Akye pricing tiers

The product's real, already-implemented pricing (`entitlements.py`), enforced by every feature gate in the app and wired to Stripe — not a proposal; this is what's actually live. (An earlier draft of this section proposed $0/$29/$79 tiers before `entitlements.py` was found — those numbers were never real and are corrected here.)

| Tier | Price | Field workers | Key features | Best for |
| --- | --- | --- | --- | --- |
| Solo | $0, forever | Up to 2 | Bookings & CRM, up to 20 jobs/month, 1 checklist template, 1 office login, email only (no texting), no automations, no card payments | The owner still doing the work themselves |
| Pro | $79/mo | Up to 10 | Everything in Solo, plus unlimited jobs/checklist templates/office logins, 1,000 texts/month, card payments, automations, recurring jobs, hiring & video interviews, payroll & 1099s, SOP library, reporting, and asking Nana | The owner who has stopped cleaning and started managing |
| Scale | $249/mo | Unlimited | Everything in Pro, unlimited team size, 5,000 texts/month, every feature with no ceiling | Multi-crew operations and commercial contracts |

There is no separate white-label/enterprise pricing tier for other companies to license Akye under their own brand — that would be a licensed deployment, not a subscription, and isn't priced or built yet. Don't promise it in outreach copy until it exists.

How this reconciles with the founding-cohort offer used throughout this plan: "free forever for the first 500 signups" means **Pro tier access — a $79/month value — at $0**, not a separate tier. That's a stronger offer than earlier drafts of this plan assumed, so lead with the full $79/mo value in founding-cohort messaging: "normally $79/month, free forever for the first 500." Once the cohort closes or the 500 spots fill, new signups land on the standard Solo (free) tier by default and can upgrade to Pro at $79/mo or Scale at $249/mo. The founding-cohort deadline in week 3 matters for real unit economics, not just marketing urgency — it caps how many users get $79/mo of value at zero long-term revenue."""


def main():
    engine = provisioning._engine()
    control_plane.ensure_table(engine)

    docs = [d for d in control_plane.all_console_docs(engine) if d['title'] == TITLE]
    if not docs:
        print(f'  ❌ no playbook titled {TITLE!r} found — nothing to fix.')
        return 1
    doc = docs[0]

    if OLD_SECTION not in doc['content']:
        if NEW_SECTION in doc['content']:
            print('  ⏭  already fixed — the corrected pricing section is already there.')
            return 0
        print('  ❌ the pricing section text has changed since this script was written '
              '(probably hand-edited in the console) — not touching it. '
              'Fix it by hand via the Edit button on that playbook instead.')
        return 1

    new_content = doc['content'].replace(OLD_SECTION, NEW_SECTION)
    control_plane.update_console_doc(engine, doc['id'], doc['title'], new_content)
    print(f'  ✅ corrected the pricing tiers section in {TITLE!r}.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
