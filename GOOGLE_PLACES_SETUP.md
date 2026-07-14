# Getting your Google key for "Find Leads" 🎯

The **Find Leads** tool works in **demo mode** with no setup (it shows fake sample
businesses so you can see how it works). To pull **real** Orlando businesses, you
need one free key from Google. Do this when you're fresh — it takes about 5–10 minutes.

## Steps (one time)

1. Go to **console.cloud.google.com** and sign in with your Google account.
2. Up top, click the project dropdown → **New Project** → name it `Dazzle Leads` → **Create**.
3. In the search bar at the top, type **"Places API (New)"** → click it → press **Enable**.
   - Google may ask you to turn on **Billing** (add a card). Don't panic:
     they give a big monthly free allowance, and you can set a spending cap so
     you're never surprised. For your usage this will almost certainly be **free**.
4. On the left menu: **APIs & Services → Credentials → + Create Credentials → API key**.
5. Copy the key it gives you (looks like `AIzaSy...`).

## Then plug it in

- **Locally:** open the `.env` file in the CRM folder and set:
  `GOOGLE_PLACES_API_KEY=AIzaSy...your-key...`
- **On Railway (live site):** Project → **Variables** → add
  `GOOGLE_PLACES_API_KEY` = your key → it redeploys automatically.

That's it. Refresh **Find Leads**, the demo banner disappears, and real businesses show up. 🎉

## Safety tip
In Google Cloud, you can **restrict the key** to just the Places API and set a
**budget alert** (Billing → Budgets & alerts). Set it low (like $5) so you get an
email if anything ever adds up — it won't, but it's peace of mind.
